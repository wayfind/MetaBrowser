"""CdpActuator: CloakBrowser binary driven over the Playwright CDP pipe, pushed as far as CDP allows.

Perception — the browser's own accessibility tree (Accessibility.getFullAXTree), per frame:
  * same-process iframes through the page session (frameId), out-of-process iframes through
    their own CDP sessions, so cross-origin iframes (ERP/SaaS shells) are visible;
  * nothing is injected into the page's JS world and the DOM is never mutated — refs live in
    the actuator, keyed by backendDOMNodeId.
Action — element geometry from DOM.getContentQuads, then the page's mouse/keyboard: under
CloakBrowser humanize those are human-like (Bezier paths, typing cadence) and dispatched through
CloakBrowser's patched CDP input path. No selectors are needed, so humanize restrictions on
selector kinds never apply.
Page-side reads (main text, tables) run in a private isolated world (Page.createIsolatedWorld),
invisible to page scripts.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from ..tools.base import ToolError
from .base import ElementInfo, Snapshot

INTERACTIVE = {
    "button", "link", "textbox", "searchbox", "combobox", "checkbox", "radio", "switch", "tab", "menuitem",
    "menuitemcheckbox", "menuitemradio", "option", "slider", "spinbutton", "listbox", "treeitem", "ListBoxOption",
    "MenuListOption", "textField", "PopUpButton", "DisclosureTriangle",
}
TEXT_INPUT = {"textbox", "searchbox", "textField", "combobox", "spinbutton"}
CONTEXT = {"heading", "alert", "alertdialog", "dialog", "status"}
TABLES = {"table", "grid", "treegrid"}
STATE_PROPS = ("checked", "disabled", "expanded", "selected", "pressed", "required", "focused", "readonly")
WORLD = "__mb_world"

READ_JS = r"""
function (selector) {
  const root = (selector && document.querySelector(selector))
    || document.querySelector('main, [role=main], article') || document.body;
  if (!root) return '';
  const out = [];
  const walk = (el) => {
    for (const node of el.childNodes) {
      if (node.nodeType === 3) { const t = node.textContent.replace(/\s+/g, ' '); if (t.trim()) out.push(t); continue; }
      if (node.nodeType !== 1) continue;
      const tag = node.tagName.toLowerCase();
      if (['script', 'style', 'noscript', 'svg', 'template', 'iframe'].includes(tag)) continue;
      const s = getComputedStyle(node);
      if (s.display === 'none' || s.visibility === 'hidden') continue;
      if (/^h[1-6]$/.test(tag)) { out.push('\n' + '#'.repeat(Number(tag[1])) + ' ' + node.innerText.trim() + '\n'); continue; }
      if (tag === 'li') out.push('\n- ');
      if (tag === 'tr') out.push('\n| ');
      if (tag === 'td' || tag === 'th') { out.push(node.innerText.trim().replace(/\s+/g, ' ') + ' | '); continue; }
      if (tag === 'a' && node.getAttribute('href')) { out.push(`[${node.innerText.trim()}](${node.href})`); continue; }
      if (tag === 'input' && node.type === 'password') continue;
      walk(node);
      if (['p', 'div', 'section', 'br', 'table', 'ul', 'ol'].includes(tag)) out.push('\n');
    }
  };
  walk(root);
  return out.join('').replace(/\n{3,}/g, '\n\n').trim();
}
"""

TABLE_JS = r"""
function (sel) {
  const tables = sel ? [...document.querySelectorAll(sel)] : [...document.querySelectorAll('table, [role=grid], [role=table]')];
  return tables.map((t) => {
    const rowEls = [...t.querySelectorAll('tr, [role=row]')];
    const cellsOf = (r) => [...r.querySelectorAll('th, td, [role=columnheader], [role=cell], [role=gridcell]')]
      .map(c => c.innerText.replace(/\s+/g, ' ').trim());
    const thead = t.querySelector('thead tr') || rowEls.find(r => r.querySelector('th, [role=columnheader]'));
    const header = thead ? cellsOf(thead) : [];
    const rows = rowEls.filter(r => r !== thead).map(cellsOf).filter(r => r.length);
    return { header, rows };
  });
}
"""

SCROLL_JS = "function () { return {y: Math.round(scrollY), height: document.documentElement.scrollHeight, viewport: innerHeight}; }"
SUBMIT_JS = ("function () { const t = (this.type || '').toLowerCase(); "
             "return {submit: !!(this.form && t === 'submit'), tag: this.tagName.toLowerCase(), type: t}; }")
SELECT_JS = r"""
function (labels) {
  if (this.tagName !== 'SELECT') return null;
  const want = labels.map(l => l.trim());
  const chosen = [];
  for (const o of this.options) {
    const hit = want.includes(o.text.trim()) || want.includes(o.value);
    if (hit && (this.multiple || !chosen.length)) { o.selected = true; chosen.push(o.text.trim()); }
    else if (!this.multiple) o.selected = false;
  }
  this.dispatchEvent(new Event('input', {bubbles: true}));
  this.dispatchEvent(new Event('change', {bubbles: true}));
  return chosen;
}
"""


@dataclass
class FrameHandle:
    key: str
    session: Any
    frame_id: str
    url: str
    depth: int = 0
    pw_frame: Any = None          # set for out-of-process iframes (offset computed at action time)

    @property
    def oopif(self) -> bool:
        return self.pw_frame is not None


@dataclass
class AxNode:
    role: str
    name: str
    value: Optional[str]
    props: dict[str, Any]
    backend_id: Optional[int]
    frame: FrameHandle
    node_id: str
    children: list[str]
    ignored: bool


@dataclass
class TabState:
    main: Any = None
    oopif: dict = field(default_factory=dict)        # playwright frame -> CDP session
    not_oopif: set = field(default_factory=set)
    worlds: dict = field(default_factory=dict)       # frame key -> execution context id
    refs: dict = field(default_factory=dict)         # ref -> (FrameHandle, backend id, role, name)
    by_key: dict = field(default_factory=dict)       # (frame key, backend id) -> ref
    counter: itertools.count = field(default_factory=lambda: itertools.count(1))


def render(snap: Snapshot, tab_id: str, unchanged: bool = False) -> str:
    head = f"tab={tab_id} url={snap.url}\ntitle: {snap.title}\nsnapshot={snap.hash}"
    if snap.scroll:
        head += f" scroll={snap.scroll.get('y')}/{snap.scroll.get('height')} viewport={snap.scroll.get('viewport')}"
    if snap.frames > 1:
        head += f" frames={snap.frames}"
    if unchanged:
        return head + "\n(unchanged since your last snapshot of this tab)"
    tail = "\n… (truncated; scroll or use page_read / data_extract_table)" if snap.truncated else ""
    return head + "\n" + "\n".join(snap.lines) + tail


def _clip(text: Any, n: int) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t if len(t) <= n else t[:n] + "…"


def _ax_value(field_: Any) -> Any:
    return field_.get("value") if isinstance(field_, dict) else None


class CdpActuator:
    def __init__(self):
        self._state: dict[str, TabState] = {}

    def forget(self, tab_id: str) -> None:
        self._state.pop(tab_id, None)

    def on_navigated(self, tab: Any) -> None:
        st = self._state.get(tab.id)
        if st is not None:
            st.worlds.clear()

    def _st(self, tab: Any) -> TabState:
        return self._state.setdefault(tab.id, TabState())

    # -- sessions / frames ----------------------------------------------------------------
    async def _main(self, tab: Any) -> Any:
        st = self._st(tab)
        if st.main is None:
            st.main = await tab.page.context.new_cdp_session(tab.page)
        return st.main

    async def frames(self, tab: Any) -> list[FrameHandle]:
        st = self._st(tab)
        main = await self._main(tab)
        tree = (await main.send("Page.getFrameTree"))["frameTree"]
        by_id: dict[str, FrameHandle] = {}

        def walk(node: dict, depth: int) -> None:
            f = node["frame"]
            by_id[f["id"]] = FrameHandle(f"f:{f['id']}", main, f["id"], f.get("url", ""), depth)
            for child in node.get("childFrames", []):
                walk(child, depth + 1)

        walk(tree, 0)
        for pf in tab.page.frames[1:]:
            if pf in st.not_oopif:
                continue
            sess = st.oopif.get(pf)
            if sess is None:
                try:
                    sess = await tab.page.context.new_cdp_session(pf)
                except Exception:
                    st.not_oopif.add(pf)  # in-process frame: covered by the page session
                    continue
                st.oopif[pf] = sess
            try:
                ft = (await sess.send("Page.getFrameTree"))["frameTree"]["frame"]
            except Exception:
                st.oopif.pop(pf, None)
                continue
            by_id[ft["id"]] = FrameHandle(f"o:{ft['id']}", sess, ft["id"], pf.url, 1, pf)
        main_id = tree["frame"]["id"]
        return [by_id[main_id]] + [h for fid, h in by_id.items() if fid != main_id]

    async def _offset(self, fh: FrameHandle) -> tuple[float, float]:
        if not fh.oopif:
            return 0.0, 0.0  # same-process frame quads are already in root-viewport coordinates
        el = await fh.pw_frame.frame_element()
        box = await el.bounding_box()
        if not box:
            raise ToolError("not_visible", "the iframe containing this element is not visible")
        border = await el.evaluate("e => { const s = getComputedStyle(e); return [parseFloat(s.borderLeftWidth) + parseFloat(s.paddingLeft), parseFloat(s.borderTopWidth) + parseFloat(s.paddingTop)]; }")
        return box["x"] + border[0], box["y"] + border[1]

    # -- accessibility scan ----------------------------------------------------------------
    async def _scan(self, tab: Any) -> list[AxNode]:
        nodes: list[AxNode] = []
        for fh in await self.frames(tab):
            try:
                res = await fh.session.send("Accessibility.getFullAXTree", {"frameId": fh.frame_id})
            except Exception:
                continue  # frame navigating or not owned by this session
            raw = res.get("nodes", [])
            idx = {n["nodeId"]: n for n in raw}
            child_ids = {c for n in raw for c in n.get("childIds", [])}
            roots = [n for n in raw if n["nodeId"] not in child_ids] or raw[:1]
            stack = list(reversed(roots))
            while stack:  # document order
                n = stack.pop()
                props = {p["name"]: _ax_value(p.get("value")) for p in n.get("properties", [])}
                nodes.append(AxNode(
                    role=_ax_value(n.get("role")) or "", name=_ax_value(n.get("name")) or "",
                    value=_ax_value(n.get("value")), props=props, backend_id=n.get("backendDOMNodeId"),
                    frame=fh, node_id=n["nodeId"], children=n.get("childIds", []), ignored=n.get("ignored", False)))
                stack.extend(idx[c] for c in reversed(n.get("childIds", [])) if c in idx)
        return nodes

    def _ref(self, tab: Any, node: AxNode) -> str:
        st = self._st(tab)
        key = (node.frame.key, node.backend_id)
        ref = st.by_key.get(key)
        if ref is None:
            ref = f"e{next(st.counter)}"
            st.by_key[key] = ref
        st.refs[ref] = (node.frame, node.backend_id, node.role, node.name)
        return ref

    async def _is_password(self, node: AxNode) -> bool:
        try:
            d = await node.frame.session.send("DOM.describeNode", {"backendNodeId": node.backend_id})
            attrs = d["node"].get("attributes", [])
            return any(attrs[i] == "type" and attrs[i + 1].lower() == "password" for i in range(0, len(attrs) - 1, 2))
        except Exception:
            return True  # fail closed: never print a value we could not classify

    async def snapshot(self, tab: Any, max_items: int = 400) -> Snapshot:
        nodes = await self._scan(tab)
        by_frame_id: dict[tuple[str, str], AxNode] = {(n.frame.key, n.node_id): n for n in nodes}
        lines: list[str] = []
        frames_seen: list[str] = []
        truncated = False
        for n in nodes:
            if len(lines) >= max_items:
                truncated = True
                break
            if n.frame.key not in frames_seen:
                frames_seen.append(n.frame.key)
                if len(frames_seen) > 1:
                    lines.append(f"--- frame {_clip(n.frame.url, 100)}{' (cross-origin)' if n.frame.oopif else ''} ---")
            if n.ignored or n.props.get("hidden"):
                continue
            if n.role in INTERACTIVE and n.backend_id:
                line = f"[{self._ref(tab, n)}] {n.role} \"{_clip(n.name, 60)}\""
                if n.value not in (None, "") and n.role in TEXT_INPUT | {"slider"}:
                    if n.role in TEXT_INPUT and await self._is_password(n):
                        line += " value=***"
                    else:
                        line += f" value=\"{_clip(n.value, 40)}\""
                for prop in STATE_PROPS:
                    v = n.props.get(prop)
                    if v in (True, "true"):
                        line += f" {prop}"
                    elif prop == "checked" and v == "mixed":
                        line += " mixed"
                    elif prop == "expanded" and v in (False, "false"):
                        line += " collapsed"
                if n.role == "combobox":
                    opts = [_clip(c.name, 20) for c in _subtree(n, by_frame_id)
                            if c.role in ("MenuListOption", "option")][:10]
                    if opts:
                        line += " options=[" + ", ".join(opts) + "]"
                if n.props.get("url"):
                    line += " -> " + _clip(n.props["url"], 80)
                lines.append(line)
            elif n.role in CONTEXT and n.name:
                level = n.props.get("level")
                lines.append(f"{n.role}{level or ''} \"{_clip(n.name, 80)}\"")
            elif n.role in TABLES:
                sub = _subtree(n, by_frame_id)
                rows = sum(1 for c in sub if c.role == "row")
                head = " | ".join(_clip(c.name, 20) for c in sub if c.role == "columnheader")
                cols = len([c for c in sub if c.role == "columnheader"])
                label = f' "{_clip(n.name, 40)}"' if n.name else ""
                cols_text = " | ".join(head.split(" | ")[:8]) if cols else ""
                lines.append(f"table{label} rows={rows}" + (f" cols: {cols_text}" if cols else ""))
        page = tab.page
        try:
            title = await page.title()
        except Exception:
            title = ""
        body = page.url + "\n" + "\n".join(lines)
        try:
            scroll = await self.eval(tab, SCROLL_JS)
        except Exception:
            scroll = {}
        return Snapshot(url=page.url, title=title, lines=lines, truncated=truncated, scroll=scroll or {},
                        hash=hashlib.sha256(body.encode()).hexdigest()[:16], frames=len(frames_seen) or 1)

    # -- element lookup ----------------------------------------------------------------------
    def _resolve(self, tab: Any, ref: str) -> tuple[FrameHandle, int, str, str]:
        if not ref or not re.fullmatch(r"e\d+", ref):
            raise ToolError("invalid_arguments", f"invalid ref {ref!r}; take page_snapshot and use an [eN] ref")
        entry = self._st(tab).refs.get(ref)
        if entry is None:
            raise ToolError("stale_ref", f"ref {ref} is unknown in this tab; take a new page_snapshot")
        return entry

    async def element(self, tab: Any, ref: str) -> ElementInfo:
        fh, backend, role, name = self._resolve(tab, ref)
        info = ElementInfo(ref=ref, role=role, name=name, frame_url=fh.url)
        try:
            r = await self._call_on(tab, fh, backend, SUBMIT_JS)
            info.is_submit, info.tag = bool(r.get("submit")), r.get("tag", "")
        except ToolError:
            raise
        except Exception:
            pass
        return info

    async def find(self, tab: Any, *, role: Optional[str] = None, name: Optional[str] = None,
                   text: Optional[str] = None, label: Optional[str] = None, placeholder: Optional[str] = None,
                   css: Optional[str] = None, timeout_ms: int = 0) -> Optional[str]:
        deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
        while True:
            ref = await self._find_once(tab, role=role, name=name, text=text, label=label,
                                        placeholder=placeholder, css=css)
            if ref or asyncio.get_running_loop().time() >= deadline:
                return ref
            await asyncio.sleep(0.25)

    async def _find_once(self, tab, *, role, name, text, label, placeholder, css) -> Optional[str]:
        if css:
            return await self._query_css(tab, css)
        if placeholder:
            hit = await self._query_attr(tab, "placeholder", placeholder)
            if hit:
                return hit
        nodes = [n for n in await self._scan(tab) if not n.ignored and n.backend_id]
        if role or name:
            rx = re.compile(name, re.I) if name else None
            for n in nodes:
                if (not role or n.role == role) and (rx is None or rx.search(n.name)):
                    return self._ref(tab, n)
            return None
        if label or placeholder:
            rx = re.compile(label or placeholder, re.I)
            for n in nodes:
                if n.role in TEXT_INPUT | {"checkbox", "radio", "switch", "listbox"} and rx.search(n.name):
                    return self._ref(tab, n)
            return None
        if text:
            rx = re.compile(text, re.I)
            ranked = sorted((n for n in nodes if n.name and rx.search(n.name)),
                            key=lambda n: (n.role not in INTERACTIVE, n.role == "StaticText"))
            return self._ref(tab, ranked[0]) if ranked else None
        return None

    async def _query_css(self, tab: Any, css: str) -> Optional[str]:
        fh = (await self.frames(tab))[0]
        doc = await fh.session.send("DOM.getDocument", {"depth": 0})
        try:
            found = await fh.session.send("DOM.querySelector", {"nodeId": doc["root"]["nodeId"], "selector": css})
        except Exception as e:
            raise ToolError("invalid_selector", f"bad CSS selector {css!r}: {e}")
        if not found.get("nodeId"):
            return None
        desc = await fh.session.send("DOM.describeNode", {"nodeId": found["nodeId"]})
        return self._ref(tab, AxNode("", "", None, {}, desc["node"]["backendNodeId"], fh, "", [], False))

    async def _query_attr(self, tab: Any, attr: str, pattern: str) -> Optional[str]:
        fh = (await self.frames(tab))[0]
        doc = await fh.session.send("DOM.getDocument", {"depth": 0})
        found = await fh.session.send("DOM.querySelectorAll", {"nodeId": doc["root"]["nodeId"], "selector": f"[{attr}]"})
        rx = re.compile(pattern, re.I)
        for node_id in found.get("nodeIds", []):
            desc = (await fh.session.send("DOM.describeNode", {"nodeId": node_id}))["node"]
            attrs = desc.get("attributes", [])
            values = {attrs[i]: attrs[i + 1] for i in range(0, len(attrs) - 1, 2)}
            if rx.search(values.get(attr, "")):
                return self._ref(tab, AxNode("", "", None, {}, desc["backendNodeId"], fh, "", [], False))
        return None

    # -- isolated-world evaluation -----------------------------------------------------------
    async def _world(self, tab: Any, fh: FrameHandle) -> int:
        st = self._st(tab)
        ctx = st.worlds.get(fh.key)
        if ctx is None:
            r = await fh.session.send("Page.createIsolatedWorld", {"frameId": fh.frame_id, "worldName": WORLD})
            ctx = st.worlds[fh.key] = r["executionContextId"]
        return ctx

    async def eval(self, tab: Any, fn: str, arg: Any = None, fh: Optional[FrameHandle] = None) -> Any:
        """Call `fn` (a JS function source) with `arg` in our isolated world of a frame (default: main)."""
        fh = fh or (await self.frames(tab))[0]
        for attempt in range(2):
            ctx = await self._world(tab, fh)
            try:
                r = await fh.session.send("Runtime.callFunctionOn", {
                    "functionDeclaration": fn, "executionContextId": ctx, "arguments": [{"value": arg}],
                    "returnByValue": True, "awaitPromise": True})
            except Exception as e:
                if attempt == 0 and re.search(r"context|Cannot find", str(e), re.I):
                    self._st(tab).worlds.pop(fh.key, None)  # navigated: the world is gone
                    await asyncio.sleep(0.2)
                    continue
                raise
            if r.get("exceptionDetails"):
                raise ToolError("script_error", _clip(r["exceptionDetails"].get("text", "error"), 300))
            return r.get("result", {}).get("value")
        return None

    async def _call_on(self, tab: Any, fh: FrameHandle, backend: int, fn: str, arg: Any = None) -> Any:
        ctx = await self._world(tab, fh)
        try:
            obj = await fh.session.send("DOM.resolveNode", {"backendNodeId": backend, "executionContextId": ctx})
        except Exception as e:
            self._st(tab).worlds.pop(fh.key, None)
            raise ToolError("stale_ref", f"element is gone ({_clip(e, 80)}); take a new page_snapshot")
        r = await fh.session.send("Runtime.callFunctionOn", {
            "functionDeclaration": fn, "objectId": obj["object"]["objectId"], "arguments": [{"value": arg}],
            "returnByValue": True})
        if r.get("exceptionDetails"):
            raise ToolError("script_error", _clip(r["exceptionDetails"].get("text", "error"), 300))
        return r.get("result", {}).get("value")

    async def read_text(self, tab: Any, selector: Optional[str] = None) -> str:
        parts = []
        for i, fh in enumerate(await self.frames(tab)):
            try:
                text = await self.eval(tab, READ_JS, selector if i == 0 else None, fh)
            except Exception:
                continue
            if text:
                parts.append(text if i == 0 else f"\n\n## frame: {fh.url}\n{text}")
        return "".join(parts)

    async def tables(self, tab: Any, selector: Optional[str] = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for fh in await self.frames(tab):
            try:
                out += [{**t, "frame": fh.url} for t in (await self.eval(tab, TABLE_JS, selector, fh) or [])]
            except Exception:
                continue
        return out

    # -- actions -------------------------------------------------------------------------------
    async def _point(self, tab: Any, ref: str) -> tuple[float, float]:
        fh, backend, _role, _name = self._resolve(tab, ref)
        try:
            await fh.session.send("DOM.scrollIntoViewIfNeeded", {"backendNodeId": backend})
            quads = (await fh.session.send("DOM.getContentQuads", {"backendNodeId": backend})).get("quads", [])
        except Exception as e:
            msg = str(e)
            if "No node" in msg or "not found" in msg:
                raise ToolError("stale_ref", f"ref {ref} no longer exists; take a new page_snapshot")
            raise ToolError("not_visible", f"ref {ref} has no clickable box ({_clip(msg, 80)})")
        if not quads:
            raise ToolError("not_visible", f"ref {ref} is not rendered (hidden or zero-size)")

        def area(q):
            return abs((q[2] - q[0]) * (q[5] - q[1]))

        q = max(quads, key=area)
        ox, oy = await self._offset(fh)
        return ox + sum(q[0::2]) / 4, oy + sum(q[1::2]) / 4

    async def click(self, tab: Any, ref: str, *, button: str = "left", double: bool = False) -> None:
        x, y = await self._point(tab, ref)
        mouse = tab.page.mouse
        if button == "left" and not double:
            await mouse.click(x, y)  # humanized under CloakBrowser (curve + press timing)
            return
        await mouse.move(x, y)
        original = getattr(tab.page, "_original", None)
        raw_click = original.mouse_click if original else mouse.click
        await raw_click(x, y, button=button, click_count=2 if double else 1)

    async def type(self, tab: Any, ref: str, text: str, *, clear: bool = True, submit: bool = False) -> None:
        await self.click(tab, ref)  # focus the way a person does
        kb = tab.page.keyboard
        if clear:
            await kb.press("ControlOrMeta+A")
            await kb.press("Backspace")
        if len(text) > 300:
            await kb.insert_text(text)
        else:
            await kb.type(text)  # humanized cadence under CloakBrowser
        if submit:
            await kb.press("Enter")

    async def select(self, tab: Any, ref: str, labels: list[str]) -> list[str]:
        fh, backend, _r, _n = self._resolve(tab, ref)
        chosen = await self._call_on(tab, fh, backend, SELECT_JS, labels)
        if chosen is None:
            raise ToolError("not_a_select", f"ref {ref} is not a <select>; click it and pick the option ref instead")
        if not chosen:
            raise ToolError("no_such_option", f"none of {labels} is an option of {ref}")
        return chosen

    async def set_checked(self, tab: Any, ref: str, checked: bool) -> None:
        fh, backend, _r, _n = self._resolve(tab, ref)
        state = await self._call_on(tab, fh, backend, "function () { return !!this.checked; }")
        if bool(state) != checked:
            await self.click(tab, ref)

    async def press(self, tab: Any, key: str, ref: Optional[str] = None) -> None:
        if ref:
            fh, backend, _r, _n = self._resolve(tab, ref)
            await fh.session.send("DOM.focus", {"backendNodeId": backend})
        await tab.page.keyboard.press(key)

    async def scroll(self, tab: Any, *, dy: int = 0, ref: Optional[str] = None) -> None:
        if ref:
            fh, backend, _r, _n = self._resolve(tab, ref)
            await fh.session.send("DOM.scrollIntoViewIfNeeded", {"backendNodeId": backend})
        else:
            await tab.page.mouse.wheel(0, dy or 800)

    async def screenshot(self, tab: Any, *, ref: Optional[str] = None, full_page: bool = False) -> bytes:
        if not ref:
            return await tab.page.screenshot(full_page=full_page)
        fh, backend, _r, _n = self._resolve(tab, ref)
        await fh.session.send("DOM.scrollIntoViewIfNeeded", {"backendNodeId": backend})
        quads = (await fh.session.send("DOM.getContentQuads", {"backendNodeId": backend})).get("quads", [])
        if not quads:
            raise ToolError("not_visible", f"ref {ref} is not rendered")
        ox, oy = await self._offset(fh)
        xs, ys = quads[0][0::2], quads[0][1::2]
        clip = {"x": ox + min(xs), "y": oy + min(ys), "width": max(xs) - min(xs), "height": max(ys) - min(ys)}
        return await tab.page.screenshot(clip=clip)


def _subtree(node: AxNode, idx: dict) -> list[AxNode]:
    out, stack = [], list(node.children)
    while stack:
        child = idx.get((node.frame.key, stack.pop()))
        if child is not None:
            out.append(child)
            stack.extend(child.children)
    return out

