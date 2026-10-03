"""L1 primitives: tabs, navigation, accessibility snapshot, ref-addressed actions, dialogs, uploads.

All engine access goes through `ctx.runtime.actuator` (see actuator/base.py).
"""

from __future__ import annotations

import asyncio
import base64
import fnmatch
import re
from pathlib import Path
from typing import Any

from .. import paths
from ..actuator import render
from .base import Risk, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec, schema

TAB = {"type": "string", "description": "Tab id (tN). Defaults to this session's active tab."}
REF = {"type": "string", "description": "Element ref from page_snapshot, e.g. e12."}

# Generic irreversible-action vocabulary (EN + ZH). Site packs add precise patterns.
GENERIC_RISKS: list[tuple[str, Risk, str]] = [
    (r"\b(pay|place order|purchase|checkout|buy now|transfer|withdraw)\b|支付|付款|下单|购买|转账|提现", Risk.IRREVERSIBLE, "payment"),
    (r"\b(delete|remove permanently|destroy|purge|empty trash)\b|删除|彻底删除|清空", Risk.IRREVERSIBLE, "deletion"),
    (r"\b(approve|reject|sign|ship|refund|cancel order)\b|审批|批准|驳回|签署|发货|退款|取消订单", Risk.IRREVERSIBLE, "business decision"),
    (r"\b(send|submit|publish|post|save|confirm)\b|发送|提交|发布|保存|确认", Risk.SUBMIT, "commit"),
]


def install_generic_risks(runtime: Any) -> None:
    for pattern, risk, reason in GENERIC_RISKS:
        runtime.risk_patterns.append((re.compile(pattern, re.I), None, risk, reason))


def text_risk(runtime: Any, text: str, url: str, base: Risk) -> tuple[Risk, str]:
    risk, reasons = base, []
    for rx, url_glob, prisk, reason in runtime.risk_patterns:
        if url_glob and not fnmatch.fnmatch(url, url_glob):
            continue
        if rx.search(text or ""):
            if prisk > risk:
                risk, reasons = prisk, []
            if prisk == risk:
                reasons.append(f"{reason}: “{(text or '')[:40]}”")
    return risk, "; ".join(reasons)


async def _tab(ctx: ToolContext, args: dict[str, Any]):
    tab = await ctx.runtime.tab_for(ctx.session_id, args.get("tab"))
    ctx.notes["tab"] = tab.id
    return tab


def _no_dialog(tab) -> None:
    if tab.dialog is not None:
        d = tab.dialog
        raise ToolError("dialog_open", f"a {d.type} dialog is open in {tab.id}: “{d.message[:200]}”. "
                                       "Handle it with page_dialog first.", dialog=d.type)


async def assess_element(ctx: ToolContext, args: dict[str, Any]) -> tuple[Risk, str]:
    """Escalate clicks/presses by what the target actually is (submit button, site risk map)."""
    tab = await _tab(ctx, args)
    ref = args.get("ref")
    if not ref:
        return Risk.INPUT, ""
    _no_dialog(tab)
    info = await ctx.runtime.actuator.element(tab, ref)
    base = Risk.SUBMIT if info.is_submit else Risk.INPUT
    risk, reason = text_risk(ctx.runtime, info.name, tab.page.url, base)
    if info.is_submit and risk == Risk.SUBMIT and not reason:
        reason = "form submit"
    return risk, reason


async def _act(tab, coro) -> None:
    """Run an input action, but return as soon as it opens a JS dialog: the input call itself stays
    blocked inside the renderer until the dialog is handled (by page_dialog), which must not deadlock."""
    action = asyncio.ensure_future(coro)

    async def dialog_opened():
        while tab.dialog is None:
            await asyncio.sleep(0.05)

    watcher = asyncio.ensure_future(dialog_opened())
    done, _ = await asyncio.wait({action, watcher}, return_when=asyncio.FIRST_COMPLETED)
    watcher.cancel()
    if action in done:
        action.result()  # propagate errors


async def _settle(tab) -> None:
    try:
        await tab.page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:
        pass


async def _snapshot_result(ctx: ToolContext, tab, force: bool = False, max_items: int = 400) -> ToolResult:
    if tab.dialog is not None:
        d = tab.dialog
        return ToolResult(text=f"tab={tab.id} url={tab.page.url}\ndialog {d.type} “{d.message[:300]}”"
                               + (f" default=“{d.default_value}”" if d.default_value else "")
                               + "\n(the page is blocked until you call page_dialog)")
    snap = await ctx.runtime.actuator.snapshot(tab, max_items)
    ctx.notes["snapshot_hash"] = snap.hash
    unchanged = not force and tab.last_snapshot == snap.hash
    tab.last_snapshot = snap.hash
    return ToolResult(text=render(snap, tab.id, unchanged=unchanged))


async def _after_action(ctx: ToolContext, tab, include_snapshot: bool) -> ToolResult:
    if tab.dialog is None:
        await _settle(tab)
    if not include_snapshot:
        return ToolResult(text=f"ok tab={tab.id} url={tab.page.url}")
    return await _snapshot_result(ctx, tab, force=True)


# -- handlers ---------------------------------------------------------------

async def tabs_list(ctx, args):
    tabs = await ctx.runtime.describe_tabs()
    active = ctx.runtime.active.get(ctx.session_id)
    lines = [f"{'*' if t['tab'] == active else ' '} {t['tab']} owner={t['owner']} {t['title'][:50]!r} {t['url']}" for t in tabs]
    return ToolResult(text="\n".join(lines) or "(no tabs)", data=tabs)


async def tabs_open(ctx, args):
    tab = await ctx.runtime.open_tab(ctx.session_id, args.get("url"))
    ctx.notes["tab"] = tab.id
    return ToolResult(text=f"opened {tab.id} url={tab.page.url}")


async def tabs_activate(ctx, args):
    tab = await _tab(ctx, args)
    await tab.page.bring_to_front()
    return ToolResult(text=f"active tab={tab.id}")


async def tabs_claim(ctx, args):
    tab = ctx.runtime.claim(ctx.session_id, args["tab"])
    ctx.notes["tab"] = tab.id
    return ToolResult(text=f"claimed {tab.id}")


async def tabs_close(ctx, args):
    tab = await _tab(ctx, args)
    await tab.page.close()
    return ToolResult(text=f"closed {tab.id}")


async def navigate(ctx, args):
    tab = await _tab(ctx, args)
    _no_dialog(tab)
    url = args["url"]
    if url in ("back", "forward", "reload"):
        await getattr(tab.page, {"back": "go_back", "forward": "go_forward", "reload": "reload"}[url])()
    else:
        if not re.match(r"^[a-z][a-z0-9+.-]*:", url):
            url = "https://" + url
        await tab.page.goto(url, wait_until="domcontentloaded")
    return await _after_action(ctx, tab, args.get("snapshot", True))


async def snapshot(ctx, args):
    tab = await _tab(ctx, args)
    return await _snapshot_result(ctx, tab, force=args.get("force", False), max_items=args.get("max_items", 400))


async def click(ctx, args):
    tab = await _tab(ctx, args)
    await _act(tab, ctx.runtime.actuator.click(tab, args["ref"], button=args.get("button", "left"),
                                               double=bool(args.get("double"))))
    return await _after_action(ctx, tab, args.get("snapshot", True))


async def type_text(ctx, args):
    tab = await _tab(ctx, args)
    _no_dialog(tab)
    await ctx.runtime.actuator.type(tab, args["ref"], args["text"], clear=args.get("clear", True),
                                    submit=bool(args.get("submit")))
    return await _after_action(ctx, tab, args.get("snapshot", False))


async def select(ctx, args):
    tab = await _tab(ctx, args)
    _no_dialog(tab)
    values = args["values"] if isinstance(args["values"], list) else [args["values"]]
    chosen = await ctx.runtime.actuator.select(tab, args["ref"], values)
    return ToolResult(text=f"selected {chosen}")


async def press(ctx, args):
    tab = await _tab(ctx, args)
    await _act(tab, ctx.runtime.actuator.press(tab, args["key"], args.get("ref")))
    return await _after_action(ctx, tab, args.get("snapshot", False))


async def scroll(ctx, args):
    tab = await _tab(ctx, args)
    _no_dialog(tab)
    await ctx.runtime.actuator.scroll(tab, dy=int(args.get("dy", 800)), ref=args.get("ref"))
    return await _after_action(ctx, tab, args.get("snapshot", True))


async def wait(ctx, args):
    tab = await _tab(ctx, args)
    timeout = int(args.get("timeout_ms", 15000))
    if args.get("text"):
        if not await ctx.runtime.actuator.find(tab, text=re.escape(args["text"]), timeout_ms=timeout):
            raise ToolError("timeout", f"text “{args['text']}” did not appear within {timeout} ms")
    elif args.get("url"):
        await tab.page.wait_for_url(args["url"], timeout=timeout)
    else:
        await tab.page.wait_for_load_state(args.get("state", "networkidle"), timeout=timeout)
    return ToolResult(text=f"ok url={tab.page.url}")


async def screenshot(ctx, args):
    tab = await _tab(ctx, args)
    png = await ctx.runtime.actuator.screenshot(tab, ref=args.get("ref"), full_page=bool(args.get("full_page")))
    return ToolResult(text=f"screenshot tab={tab.id}", image_b64=base64.b64encode(png).decode())


async def evaluate(ctx, args):
    tab = await _tab(ctx, args)
    value = await ctx.runtime.actuator.eval(tab, f"function () {{ return ({args['expression']}); }}")
    return ToolResult(text=repr(value)[:20000], data=value)


async def assess_dialog(ctx: ToolContext, args: dict[str, Any]) -> tuple[Risk, str]:
    tab = await _tab(ctx, args)
    d = tab.dialog
    if d is None or not args.get("accept", True) or d.type == "alert":
        return Risk.READ, ""
    base = Risk.NAVIGATE if d.type == "beforeunload" else Risk.INPUT
    return text_risk(ctx.runtime, d.message, tab.page.url, base)


async def dialog(ctx, args):
    tab = await _tab(ctx, args)
    d = tab.dialog
    if d is None:
        return ToolResult(text=f"no dialog open in {tab.id}")
    tab.dialog = None
    if args.get("accept", True):
        await (d.accept(args["text"]) if args.get("text") is not None and d.type == "prompt" else d.accept())
        verb = "accepted"
    else:
        await d.dismiss()
        verb = "dismissed"
    return await _after_action(ctx, tab, args.get("snapshot", True)) if verb == "accepted" else \
        ToolResult(text=f"{verb} {d.type} dialog “{d.message[:120]}”")


def _upload_roots() -> list[Path]:
    return [paths.outputs_dir().resolve(), paths.workspace_dir().resolve()]


async def assess_upload(ctx: ToolContext, args: dict[str, Any]) -> tuple[Risk, str]:
    """Uploading local files sends data off the machine: outside the MetaBrowser folders it needs approval."""
    outside = [p for p in args.get("paths", [])
               if not any(Path(p).expanduser().resolve().is_relative_to(r) for r in _upload_roots())]
    if outside:
        return Risk.IRREVERSIBLE, f"uploads files outside the MetaBrowser folders: {', '.join(outside)[:200]}"
    return Risk.SUBMIT, "uploads local files to the site"


async def upload(ctx, args):
    tab = await _tab(ctx, args)
    files = [str(Path(p).expanduser().resolve()) for p in args["paths"]]
    missing = [f for f in files if not Path(f).is_file()]
    if missing:
        raise ToolError("file_not_found", f"not found: {', '.join(missing)}")
    async with tab.page.expect_file_chooser(timeout=int(args.get("timeout_ms", 15000))) as fc_info:
        await ctx.runtime.actuator.click(tab, args["ref"])
    chooser = await fc_info.value
    await chooser.set_files(files)
    return ToolResult(text=f"attached {len(files)} file(s) to {args['ref']} (not submitted)")


async def permissions(ctx, args):
    tab = await _tab(ctx, args)
    origin = args.get("origin") or re.match(r"^[a-z]+://[^/]+", tab.page.url).group(0)
    await tab.page.context.grant_permissions(args["grant"], origin=origin)
    return ToolResult(text=f"granted {args['grant']} to {origin}")


def register(reg: ToolRegistry) -> None:
    install_generic_risks(reg.runtime)
    S = schema
    add = reg.add
    add(ToolSpec("tabs.list", "L1", Risk.READ, "List all browser tabs with owner session and URL. * marks your active tab.",
                 S(), tabs_list))
    add(ToolSpec("tabs.open", "L1", Risk.NAVIGATE, "Open a new tab (owned by this session) and make it active.",
                 S({"url": {"type": "string"}}), tabs_open))
    add(ToolSpec("tabs.activate", "L1", Risk.NAVIGATE, "Make a tab this session's active tab and bring it to front.",
                 S({"tab": TAB}, ["tab"]), tabs_activate))
    add(ToolSpec("tabs.claim", "L1", Risk.NAVIGATE, "Take over a tab leased by another session (visible to the user).",
                 S({"tab": TAB}, ["tab"]), tabs_claim))
    add(ToolSpec("tabs.close", "L1", Risk.NAVIGATE, "Close a tab.", S({"tab": TAB}), tabs_close))
    add(ToolSpec("page.navigate", "L1", Risk.NAVIGATE,
                 "Go to a URL (or 'back'/'forward'/'reload'). Returns a snapshot unless snapshot=false.",
                 S({"url": {"type": "string"}, "tab": TAB, "snapshot": {"type": "boolean"}}, ["url"]), navigate))
    add(ToolSpec("page.snapshot", "L1", Risk.READ,
                 "Accessibility snapshot of the page and all its iframes (incl. cross-origin): interactive elements "
                 "with [eN] refs, headings, tables. Cheapest way to perceive a page; says 'unchanged' when nothing moved.",
                 S({"tab": TAB, "force": {"type": "boolean"}, "max_items": {"type": "integer"}}), snapshot))
    add(ToolSpec("page.click", "L1", Risk.INPUT,
                 "Click an element by ref (human-like pointer). Payment/delete/approve-like targets require approval.",
                 S({"ref": REF, "tab": TAB, "double": {"type": "boolean"}, "button": {"type": "string"},
                    "snapshot": {"type": "boolean"}}, ["ref"]), click, assess=assess_element))
    add(ToolSpec("page.type", "L1", Risk.INPUT,
                 "Type into a field by ref (focuses it, clears first, human-like typing). submit=true presses Enter. "
                 "Set secret=true for sensitive values so they are redacted from traces.",
                 S({"ref": REF, "text": {"type": "string"}, "tab": TAB, "clear": {"type": "boolean"},
                    "submit": {"type": "boolean"}, "secret": {"type": "boolean"},
                    "snapshot": {"type": "boolean"}}, ["ref", "text"]), type_text))
    add(ToolSpec("page.select", "L1", Risk.INPUT, "Choose option label(s) in a native <select> by ref.",
                 S({"ref": REF, "values": {"type": "array", "items": {"type": "string"}}, "tab": TAB}, ["ref", "values"]),
                 select))
    add(ToolSpec("page.press", "L1", Risk.INPUT, "Press a key (e.g. Enter, Escape, ControlOrMeta+A), optionally focusing a ref.",
                 S({"key": {"type": "string"}, "ref": REF, "tab": TAB, "snapshot": {"type": "boolean"}}, ["key"]),
                 press, assess=assess_element))
    add(ToolSpec("page.scroll", "L1", Risk.READ, "Scroll by dy pixels (human-like wheel), or scroll a ref into view.",
                 S({"dy": {"type": "integer"}, "ref": REF, "tab": TAB, "snapshot": {"type": "boolean"}}), scroll))
    add(ToolSpec("page.wait", "L1", Risk.READ, "Wait for text to appear, a URL glob, or a load state.",
                 S({"text": {"type": "string"}, "url": {"type": "string"}, "state": {"type": "string"},
                    "timeout_ms": {"type": "integer"}, "tab": TAB}), wait))
    add(ToolSpec("page.screenshot", "L1", Risk.READ,
                 "PNG screenshot (viewport, full page, or one ref). Costs more tokens than page_snapshot; use for visual checks.",
                 S({"tab": TAB, "ref": REF, "full_page": {"type": "boolean"}}), screenshot))
    add(ToolSpec("page.dialog", "L1", Risk.INPUT,
                 "Accept or dismiss the JavaScript dialog (alert/confirm/prompt/beforeunload) blocking your tab. "
                 "Accepting a confirm that commits money/deletion requires approval.",
                 S({"accept": {"type": "boolean"}, "text": {"type": "string", "description": "prompt answer"},
                    "tab": TAB, "snapshot": {"type": "boolean"}}), dialog, assess=assess_dialog))
    add(ToolSpec("file.upload", "L1", Risk.SUBMIT,
                 "Click an upload control by ref and attach local files (not submitted). Files outside "
                 "~/MetaBrowser need explicit approval.",
                 S({"ref": REF, "paths": {"type": "array", "items": {"type": "string"}}, "tab": TAB,
                    "timeout_ms": {"type": "integer"}}, ["ref", "paths"]), upload, assess=assess_upload))
    add(ToolSpec("browser.permissions", "L1", Risk.SUBMIT,
                 "Grant site permissions (e.g. geolocation, notifications, clipboard-read) to an origin (default: tab's).",
                 S({"grant": {"type": "array", "items": {"type": "string"}}, "origin": {"type": "string"}, "tab": TAB},
                   ["grant"]), permissions))
    add(ToolSpec("page.evaluate", "L1", Risk.SYSTEM,
                 "Evaluate a JS expression in MetaBrowser's isolated world of the page. Disabled by default.",
                 S({"expression": {"type": "string"}, "tab": TAB}, ["expression"]), evaluate))
