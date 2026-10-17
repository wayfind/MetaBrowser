"""Record a user's demonstration in a tab, as semantic steps, for skill forging.

Capture (all invisible to page scripts):
  * a recorder script in a private isolated world (`Page.addScriptToEvaluateOnNewDocument`
    with `worldName`, plus the current document) listens in the capture phase for clicks,
    value changes, Enter and form submits, and describes each target semantically
    (role, accessible name, label, placeholder, text, testid, css path);
  * events reach the daemon through a CDP binding scoped to that world's execution context
    (`Runtime.addBinding(executionContextId=…)`, re-attached for each new document's world via
    `Runtime.executionContextCreated`); the name-scoped variant is not exposed by the CloakBrowser
    binary, and an unscoped binding would be visible to page scripts. The click that triggers a
    navigation is delivered before unload, and events raised before the binding attaches are
    buffered in the world;
  * main-frame navigations and JSON XHR/fetch responses (the data APIs behind dashboards)
    come from the page's network events; compact page snapshots are taken at start and after
    every navigation.
Passwords never leave the page: fields of type password are recorded as a secret parameter
placeholder, and the compiler turns login steps into `ensure_login`.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qsl, urlsplit

from . import paths

WORLD = "__mb_rec"
BINDING = "__mbRecord"

RECORDER_JS = r"""
(() => {
  if (window.__mbRecInstalled) return;
  window.__mbRecInstalled = true;
  const queue = [];
  const flush = () => {
    if (typeof window.__mbRecord !== 'function') return false;
    while (queue.length) { try { window.__mbRecord(queue.shift()); } catch (_) { return false; } }
    return true;
  };
  const send = (e) => { queue.push(JSON.stringify(e)); flush(); };
  const timer = setInterval(() => { if (flush() && !queue.length) clearInterval(timer); }, 50);
  const clip = (t, n) => { t = (t || '').replace(/\s+/g, ' ').trim(); return t.length > n ? t.slice(0, n) : t; };
  const implicitRole = (el) => {
    const t = el.tagName.toLowerCase(), type = (el.getAttribute('type') || '').toLowerCase();
    if (t === 'a' && el.hasAttribute('href')) return 'link';
    if (t === 'button' || (t === 'input' && ['button', 'submit', 'reset', 'image'].includes(type))) return 'button';
    if (t === 'input' && type === 'checkbox') return 'checkbox';
    if (t === 'input' && type === 'radio') return 'radio';
    if (t === 'input' && type === 'search') return 'searchbox';
    if (t === 'input' || t === 'textarea') return 'textbox';
    if (t === 'select') return 'combobox';
    if (/^h[1-6]$/.test(t)) return 'heading';
    return '';
  };
  const labelOf = (el) => (el.labels && el.labels[0] && el.labels[0].innerText) || '';
  const nameOf = (el) => {
    const aria = el.getAttribute('aria-label'); if (aria) return aria;
    const by = el.getAttribute('aria-labelledby');
    if (by) { const t = by.split(/\s+/).map(id => (document.getElementById(id) || {}).innerText || '').join(' '); if (t.trim()) return t; }
    const lab = labelOf(el); if (lab) return lab;
    if (el.tagName === 'INPUT' && ['submit', 'button'].includes(el.type)) return el.value;
    return el.getAttribute('placeholder') || el.getAttribute('title') || el.getAttribute('alt') || el.innerText || '';
  };
  const cssPath = (el) => {
    const parts = [];
    for (let n = el, depth = 0; n && n.nodeType === 1 && depth < 6; n = n.parentElement, depth++) {
      if (n.id && /^[A-Za-z][\w-]*$/.test(n.id)) { parts.unshift('#' + n.id); break; }
      let sel = n.tagName.toLowerCase();
      const testid = n.getAttribute('data-testid'); if (testid) { parts.unshift(`[data-testid="${testid}"]`); break; }
      const nameAttr = n.getAttribute('name'); if (nameAttr && ['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON'].includes(n.tagName)) sel += `[name="${nameAttr}"]`;
      else if (n.parentElement) {
        const sibs = [...n.parentElement.children].filter(c => c.tagName === n.tagName);
        if (sibs.length > 1) sel += `:nth-of-type(${sibs.indexOf(n) + 1})`;
      }
      parts.unshift(sel);
    }
    return parts.join(' > ');
  };
  const describe = (el) => ({
    tag: el.tagName.toLowerCase(),
    role: el.getAttribute('role') || implicitRole(el),
    name: clip(nameOf(el), 80),
    label: clip(labelOf(el), 60),
    placeholder: el.getAttribute('placeholder') || '',
    text: clip(el.innerText || '', 80),
    testid: el.getAttribute('data-testid') || el.getAttribute('data-test') || el.getAttribute('data-qa') || '',
    id: el.id || '',
    name_attr: el.getAttribute('name') || '',
    type: (el.getAttribute('type') || '').toLowerCase(),
    href: el.getAttribute('href') || '',
    css: cssPath(el),
    in_form: !!el.closest('form'),
  });
  const pending = new Map();   // typed values not yet committed by a change event
  const commitFill = (el) => {
    if (!pending.has(el)) return;
    pending.delete(el);
    const secret = el.type === 'password' || /otp|one-time|verification|验证码|code/i.test(el.name || el.id || '');
    send({ kind: 'fill', target: describe(el), value: secret ? '' : String(el.value || ''), secret, url: location.href, frame: window !== top });
  };
  document.addEventListener('input', (ev) => {
    const el = ev.target;
    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable) && !['checkbox', 'radio'].includes(el.type)) pending.set(el, true);
  }, true);
  document.addEventListener('focusout', (ev) => commitFill(ev.target), true);
  const CLICKABLE = 'a,button,input[type=submit],input[type=button],input[type=checkbox],input[type=radio],input[type=image],[role=button],[role=link],[role=tab],[role=menuitem],[role=option],[role=checkbox],[role=switch],summary,label,[onclick]';
  document.addEventListener('click', (ev) => {
    for (const f of [...pending.keys()]) commitFill(f);
    const el = ev.target && ev.target.closest && ev.target.closest(CLICKABLE);
    if (!el) return;
    send({ kind: 'click', target: describe(el), url: location.href, frame: window !== top });
  }, true);
  document.addEventListener('change', (ev) => {
    const el = ev.target;
    if (!el || !el.tagName) return;
    const tag = el.tagName;
    if (tag === 'SELECT') {
      send({ kind: 'select', target: describe(el), value: [...el.selectedOptions].map(o => o.text.trim()).join('|'), url: location.href, frame: window !== top });
    } else if (tag === 'INPUT' && ['checkbox', 'radio'].includes(el.type)) {
      send({ kind: 'check', target: describe(el), value: el.checked ? 'true' : 'false', url: location.href, frame: window !== top });
    } else if (tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable) {
      pending.delete(el);
      const secret = el.type === 'password' || /otp|one-time|verification|验证码|code/i.test(el.name || el.id || '');
      send({ kind: 'fill', target: describe(el), value: secret ? '' : String(el.value || ''), secret, url: location.href, frame: window !== top });
    }
  }, true);
  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Enter' || !ev.target || !['INPUT', 'TEXTAREA'].includes(ev.target.tagName)) return;
    const el = ev.target;
    pending.set(el, true);
    commitFill(el);
    send({ kind: 'press', key: 'Enter', target: describe(el), url: location.href, frame: window !== top });
  }, true);
})();
"""


@dataclass
class Step:
    seq: int
    t: float
    kind: str                       # navigate | click | fill | select | check | press | api
    url: str = ""
    target: dict = field(default_factory=dict)
    value: str = ""
    secret: bool = False
    key: str = ""
    frame: bool = False
    caused_by: Optional[int] = None  # navigate: the user step that triggered it
    api: dict = field(default_factory=dict)


@dataclass
class Recording:
    id: str
    tab: str
    started: float
    start_url: str
    title: str = ""
    intent: str = ""
    site: str = ""
    name: str = ""
    finished: Optional[float] = None
    steps: list[Step] = field(default_factory=list)
    snapshots: list[dict] = field(default_factory=list)   # {after_seq, url, text}

    @property
    def dir(self) -> Path:
        return paths.ensure(paths.home() / "recordings" / self.id)

    def to_dict(self) -> dict[str, Any]:
        return {**{k: v for k, v in asdict(self).items() if k not in ("steps", "snapshots")},
                "steps": [asdict(s) for s in self.steps], "snapshots": self.snapshots}

    def save(self) -> Path:
        path = self.dir / "recording.json"
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        return path


def load_recording(rec_id: str) -> Recording:
    path = paths.home() / "recordings" / rec_id / "recording.json"
    if not path.exists():
        raise FileNotFoundError(f"no recording {rec_id}")
    d = json.loads(path.read_text(encoding="utf-8"))
    steps = [Step(**s) for s in d.pop("steps")]
    snaps = d.pop("snapshots")
    rec = Recording(**d)
    rec.steps, rec.snapshots = steps, snaps
    return rec


def list_recordings() -> list[dict[str, Any]]:
    root = paths.home() / "recordings"
    out = []
    for p in sorted(root.glob("*/recording.json"), key=lambda x: x.stat().st_mtime, reverse=True) if root.is_dir() else []:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append({"id": d["id"], "start_url": d["start_url"], "intent": d.get("intent", ""),
                        "steps": len(d["steps"]), "site": d.get("site", ""), "finished": d.get("finished")})
        except Exception:
            continue
    return out


class Recorder:
    """One active recording per tab."""

    def __init__(self, runtime: Any):
        self.runtime = runtime
        self.active: dict[str, tuple[Recording, Any, list]] = {}   # tab id -> (recording, cdp session, cleanups)
        self.listeners: list = []   # callback(recording, step) — live view in the side panel

    async def start(self, tab: Any) -> Recording:
        if tab.id in self.active:
            return self.active[tab.id][0]
        page = tab.page
        rec = Recording(id=time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6], tab=tab.id,
                        started=time.time(), start_url=page.url, title=await page.title())
        cdp = await page.context.new_cdp_session(page)
        seq = iter(range(1, 1_000_000))
        last_user_step: list[Optional[Step]] = [None]
        snap_task: list[Optional[asyncio.Task]] = [None]

        def add(step: Step) -> None:
            rec.steps.append(step)
            for cb in list(self.listeners):
                try:
                    cb(rec, step)
                except Exception:
                    pass

        def on_binding(ev: dict) -> None:
            if ev.get("name") != BINDING:
                return
            try:
                data = json.loads(ev.get("payload") or "{}")
            except json.JSONDecodeError:
                return
            step = Step(seq=next(seq), t=time.time() - rec.started, kind=data.get("kind", "?"), url=data.get("url", ""),
                        target=data.get("target") or {}, value=data.get("value", ""), secret=bool(data.get("secret")),
                        key=data.get("key", ""), frame=bool(data.get("frame")))
            add(step)
            last_user_step[0] = step

        def on_nav(frame: Any) -> None:
            if frame != page.main_frame:
                return
            prev = last_user_step[0]
            caused = prev.seq if prev is not None and time.time() - rec.started - prev.t < 3 else None
            step = Step(seq=next(seq), t=time.time() - rec.started, kind="navigate", url=frame.url, caused_by=caused)
            add(step)
            if snap_task[0] is None or snap_task[0].done():
                snap_task[0] = asyncio.ensure_future(self._snapshot_later(tab, rec, step.seq))

        async def on_response(resp: Any) -> None:
            try:
                if resp.request.resource_type not in ("xhr", "fetch"):
                    return
                if "json" not in (resp.headers or {}).get("content-type", ""):
                    return
                body = await resp.text()
            except Exception:
                return
            parts = urlsplit(resp.url)
            api_id = f"api{len([s for s in rec.steps if s.kind == 'api']) + 1}"
            (rec.dir / f"{api_id}.json").write_text(body, encoding="utf-8")
            add(Step(seq=next(seq), t=time.time() - rec.started, kind="api", url=resp.url, api={
                "id": api_id, "method": resp.request.method, "status": resp.status,
                "path": parts.path, "query": dict(parse_qsl(parts.query)), "bytes": len(body),
                "shape": _json_shape(body)}))

        resp_handler = lambda r: asyncio.ensure_future(on_response(r))  # noqa: E731

        def on_context(ev: dict) -> None:  # every new document gets a fresh recorder world: bind it
            c = ev.get("context") or {}
            if c.get("name") == WORLD:
                asyncio.ensure_future(_bind(c["id"]))

        async def _bind(context_id: int) -> None:
            try:
                await cdp.send("Runtime.addBinding", {"name": BINDING, "executionContextId": context_id})
            except Exception:
                pass

        cdp.on("Runtime.executionContextCreated", on_context)
        cdp.on("Runtime.bindingCalled", on_binding)
        page.on("framenavigated", on_nav)
        page.on("response", resp_handler)
        await cdp.send("Runtime.enable")
        await cdp.send("Page.enable")
        script = await cdp.send("Page.addScriptToEvaluateOnNewDocument", {"source": RECORDER_JS, "worldName": WORLD})
        tree = await cdp.send("Page.getFrameTree")
        for frame_id in _frame_ids(tree["frameTree"]):
            try:
                ctx = await cdp.send("Page.createIsolatedWorld", {"frameId": frame_id, "worldName": WORLD})
                await _bind(ctx["executionContextId"])
                await cdp.send("Runtime.evaluate", {"expression": RECORDER_JS, "contextId": ctx["executionContextId"]})
            except Exception:
                pass

        async def cleanup() -> None:
            page.remove_listener("framenavigated", on_nav)
            page.remove_listener("response", resp_handler)
            try:
                await cdp.send("Page.removeScriptToEvaluateOnNewDocument", {"identifier": script["identifier"]})
                await cdp.send("Runtime.removeBinding", {"name": BINDING})
                await cdp.detach()
            except Exception:
                pass

        self.active[tab.id] = (rec, cdp, [cleanup])
        await self._snapshot_later(tab, rec, 0, delay=0)
        return rec

    async def _snapshot_later(self, tab: Any, rec: Recording, after_seq: int, delay: float = 0.8) -> None:
        await asyncio.sleep(delay)
        try:
            from .actuator import render

            snap = await self.runtime.actuator.snapshot(tab, 150)
            rec.snapshots.append({"after_seq": after_seq, "url": snap.url, "text": render(snap, tab.id)})
        except Exception:
            pass

    async def stop(self, tab_id: str) -> Recording:
        if tab_id not in self.active:
            raise KeyError(f"tab {tab_id} is not being recorded")
        rec, _cdp, cleanups = self.active.pop(tab_id)
        await asyncio.sleep(0.3)  # let in-flight binding calls land
        for c in cleanups:
            await c()
        rec.steps = clean_steps(rec.steps)
        rec.finished = time.time()
        rec.save()
        return rec


def suggest_site(url: str, sites: dict) -> str:
    """Existing site whose base_url host matches, else a site id from the registrable domain."""
    host = urlsplit(url).hostname or "site"
    for sid, pack in sites.items():
        if urlsplit(pack.base_url).hostname == host:
            return sid
    labels = [x for x in host.split(".") if x not in ("www", "com", "cn", "net", "org", "co")]
    base = labels[-1] if labels else host
    sid = re.sub(r"[^a-z0-9]+", "_", base.lower()).strip("_") or "site"
    return sid if re.match(r"[a-z]", sid) else "site_" + sid


def _frame_ids(node: dict) -> list[str]:
    out = [node["frame"]["id"]]
    for c in node.get("childFrames", []):
        out += _frame_ids(c)
    return out


def _json_shape(body: str, limit: int = 300) -> str:
    """Compact structural summary of a JSON body: keys, list lengths, sample scalars."""
    try:
        data = json.loads(body)
    except Exception:
        return "unparseable"

    def walk(v, depth=0):
        if depth > 3:
            return "…"
        if isinstance(v, dict):
            return "{" + ", ".join(f"{k}: {walk(x, depth + 1)}" for k, x in list(v.items())[:8]) + ("…" if len(v) > 8 else "") + "}"
        if isinstance(v, list):
            return f"[{len(v)}× {walk(v[0], depth + 1)}]" if v else "[]"
        if isinstance(v, str):
            return "str"
        return type(v).__name__

    s = walk(data)
    return s if len(s) <= limit else s[:limit] + "…"


def clean_steps(steps: list[Step]) -> list[Step]:
    """Drop focus clicks on fields that are then filled, keep only the last value per field run, and
    drop repeats of a value already recorded for that field on the same page (Enter + change).
    Navigations caused by a dropped step are re-attributed to the last kept user step."""
    out: list[Step] = []
    seen: dict[str, str] = {}      # css -> last recorded value on the current page
    remap: dict[int, int] = {}     # dropped seq -> kept seq
    last_kept_user: list[int] = [0]

    def drop(step: Step) -> None:
        remap[step.seq] = last_kept_user[0]

    for s in steps:
        if s.kind == "navigate":
            seen.clear()
            if s.caused_by in remap:
                s.caused_by = remap[s.caused_by] or None
        css = s.target.get("css", "")
        if s.kind == "fill" and not s.secret and seen.get(css) == s.value:
            drop(s)
            continue
        if s.kind == "fill":
            seen[css] = s.value
            while out and out[-1].kind in ("fill", "click") and out[-1].target.get("css") == css \
                    and out[-1].target.get("tag") in ("input", "textarea"):
                drop(out.pop())
        out.append(s)
        if s.kind not in ("navigate", "api"):
            last_kept_user[0] = s.seq
    return out


# -- compile a recording into a draft capability ----------------------------------------------

def _candidates(t: dict) -> list[dict]:
    """Locator candidates, most robust first."""
    cands: list[dict] = []
    role, name = t.get("role"), (t.get("name") or "").strip()
    if role and name:
        cands.append({"role": role, "name": "^" + re.escape(name) + "$"})
    if t.get("label"):
        cands.append({"label": re.escape(t["label"].strip())})
    if t.get("placeholder"):
        cands.append({"placeholder": re.escape(t["placeholder"])})
    if t.get("testid"):
        cands.append({"css": f'[data-testid="{t["testid"]}"]'})
    if t.get("text") and not cands:
        cands.append({"text": re.escape(t["text"][:40])})
    if t.get("css"):
        cands.append({"css": t["css"]})
    return cands or [{"css": t.get("tag", "*")}]


def _param_name(t: dict, used: set[str]) -> str:
    raw = t.get("name_attr") or t.get("label") or t.get("placeholder") or t.get("id") or "value"
    base = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_") or "value"
    if not re.match(r"[a-z]", base):
        base = "p_" + base
    name, i = base[:32], 2
    while name in used:
        name, i = f"{base[:28]}_{i}", i + 1
    used.add(name)
    return name


def compile_recording(rec: Recording, base_url: str, name: str, description: str = "") -> dict[str, Any]:
    """A first draft only: the forge agent is expected to question and generalize it."""
    steps: list[dict] = []
    props: dict[str, Any] = {}
    used: set[str] = set()
    demo_args: dict[str, str] = {}
    notes: list[str] = []
    base = base_url.rstrip("/")

    def templ(url: str) -> str:
        return "{base_url}" + url[len(base):] if base and url.startswith(base) else url

    first_nav = rec.start_url
    steps.append({"do": "ensure_login"} if any(s.secret for s in rec.steps) else {"do": "goto", "url": templ(first_nav)})
    if steps[0]["do"] == "ensure_login":
        notes.append("credential fields were typed: replaced by ensure_login; the user logs in manually")
        steps.append({"do": "goto", "url": templ(first_nav)})
    for s in rec.steps:
        if s.kind == "navigate":
            if s.caused_by is None and s.url != first_nav:
                steps.append({"do": "goto", "url": templ(s.url)})
            continue
        if s.kind == "api":
            continue
        if s.secret:
            continue
        cands = _candidates(s.target)
        if s.kind == "click":
            steps.append({"do": "click", "target": cands})
        elif s.kind == "fill":
            p = _param_name(s.target, used)
            props[p] = {"type": "string", "description": f"value for {s.target.get('name') or p}"}
            demo_args[p] = s.value
            steps.append({"do": "fill", "target": cands, "value": "{" + p + "}"})
        elif s.kind == "select":
            p = _param_name(s.target, used)
            props[p] = {"type": "string", "description": f"option of {s.target.get('name') or p}"}
            demo_args[p] = s.value
            steps.append({"do": "select", "target": cands, "value": "{" + p + "}"})
        elif s.kind == "check":
            steps.append({"do": "click", "target": cands})
        elif s.kind == "press":
            steps.append({"do": "press", "key": s.key, "target": cands})
    apis = [s.api for s in rec.steps if s.kind == "api"]
    if apis:
        notes.append("JSON APIs observed: " + "; ".join(f"{a['method']} {a['path']} {a['shape'][:80]}" for a in apis[:6])
                     + " — consider capture_start/capture_read instead of scraping")
    steps.append({"do": "extract_table", "as": "rows"})
    return {
        "name": name,
        "description": description or rec.intent or f"recorded on {rec.start_url}",
        "risk": "read",
        "input_schema": {"type": "object", "properties": props},
        "steps": steps,
        "returns": "rows",
        "tests": [{"args": demo_args, "expect": {"min_rows": 1}}],
        "x-forge": {"recording": rec.id, "intent": rec.intent, "notes": notes, "status": "draft"},
    }


def summarize(rec: Recording, max_snapshot_chars: int = 2500) -> str:
    """Compact, model-facing view of a recording."""
    lines = [f"recording {rec.id} on tab {rec.tab}", f"start: {rec.start_url}  title: {rec.title!r}",
             f"intent (from the user): {rec.intent or '(not given)'}", "steps:"]
    for s in rec.steps:
        t = s.target
        who = f"{t.get('role') or t.get('tag')} \"{t.get('name') or t.get('text') or ''}\"" if t else ""
        if s.kind == "navigate":
            lines.append(f"  {s.seq:>3} navigate {s.url}" + (f" (after step {s.caused_by})" if s.caused_by else " (typed/direct)"))
        elif s.kind == "api":
            a = s.api
            q = "&".join(f"{k}={v}" for k, v in a["query"].items())
            lines.append(f"  {s.seq:>3} api {a['method']} {a['path']}{'?' + q if q else ''} -> {a['status']} {a['bytes']}B "
                         f"{a['shape'][:160]} (body: {a['id']}.json)")
        elif s.kind in ("fill", "select", "check"):
            val = "<secret>" if s.secret else repr(s.value)
            lines.append(f"  {s.seq:>3} {s.kind} {who} = {val}" + (f"  css={t.get('css')}" if t else ""))
        else:
            lines.append(f"  {s.seq:>3} {s.kind}{' ' + s.key if s.key else ''} {who}" + (f"  css={t.get('css')}" if t else ""))
    for snap in rec.snapshots[:6]:
        text = snap["text"]
        lines.append(f"\nsnapshot after step {snap['after_seq']} ({snap['url']}):\n"
                     + (text if len(text) <= max_snapshot_chars else text[:max_snapshot_chars] + "\n…"))
    return "\n".join(lines)
