"""L2 semantic tools: one call per intent, far fewer tokens than L1 step-by-step.

Large results (tables, captured API payloads, downloads) are written to disk and
returned as path + preview so they never flood the model context.
"""

from __future__ import annotations

import csv
import json
import re
import time
from typing import Any

from .. import paths
from .base import Risk, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec, schema
from .l1 import TAB, REF, _no_dialog, _settle, _tab, assess_element

INLINE_ROWS = 50

def _rows_to_records(header: list[str], rows: list[list[str]]) -> list[dict[str, str]]:
    if not header:
        return [{f"col{i + 1}": v for i, v in enumerate(r)} for r in rows]
    keys = [h or f"col{i + 1}" for i, h in enumerate(header)]
    return [{keys[i] if i < len(keys) else f"col{i + 1}": v for i, v in enumerate(r)} for r in rows]


def _save_records(records: list[dict[str, Any]], stem: str) -> str:
    path = paths.ensure(paths.artifacts_dir()) / f"{stem}-{int(time.time() * 1000)}.csv"
    fields: list[str] = []
    for r in records:
        fields += [k for k in r if k not in fields]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(records)
    return str(path)


def _records_result(records: list[dict[str, Any]], stem: str, note: str = "") -> ToolResult:
    if len(records) <= INLINE_ROWS:
        return ToolResult(text=f"{len(records)} rows{note}\n" + json.dumps(records, ensure_ascii=False), data=records)
    path = _save_records(records, stem)
    preview = json.dumps(records[:10], ensure_ascii=False)
    return ToolResult(text=f"{len(records)} rows{note}; saved to {path}\nfirst 10: {preview}",
                      data={"path": path, "count": len(records)}, artifacts=[path])


async def read(ctx, args):
    tab = await _tab(ctx, args)
    _no_dialog(tab)
    text = await ctx.runtime.actuator.read_text(tab, args.get("selector"))
    offset, limit = int(args.get("offset", 0)), int(args.get("limit", 8000))
    chunk = text[offset:offset + limit]
    more = f"\n… ({len(text) - offset - limit} more chars; call again with offset={offset + limit})" \
        if len(text) > offset + limit else ""
    return ToolResult(text=f"tab={tab.id} url={tab.page.url}\n{chunk}{more}")


async def extract_table(ctx, args):
    tab = await _tab(ctx, args)
    _no_dialog(tab)
    tables = await ctx.runtime.actuator.tables(tab, args.get("selector"))
    if not tables:
        raise ToolError("no_table", "no table/grid found (main page or iframes); try page_read or net_capture for API-backed grids")
    idx = int(args.get("index", 0))
    if idx >= len(tables):
        raise ToolError("no_table", f"only {len(tables)} table(s) on page")
    t = tables[idx]
    return _records_result(_rows_to_records(t["header"], t["rows"]), "table",
                           f" (table {idx + 1}/{len(tables)})")


async def fill_form(ctx, args):
    tab = await _tab(ctx, args)
    _no_dialog(tab)
    act = ctx.runtime.actuator
    done = []
    for f in args["fields"]:
        ref = f.get("ref") or (await act.find(tab, label=re.escape(f["label"]), timeout_ms=3000) if f.get("label") else None)
        if not ref:
            raise ToolError("field_not_found", f"no field for {f.get('label') or f}; take page_snapshot and use refs")
        info = await act.element(tab, ref)
        value = f.get("value", "")
        if info.role in ("checkbox", "radio", "switch"):
            await act.set_checked(tab, ref, bool(value) and str(value).lower() not in ("false", "0", "no"))
        elif info.tag == "select":
            await act.select(tab, ref, [str(value)])
        else:
            await act.type(tab, ref, str(value))
        done.append(f.get("label") or ref)
    return ToolResult(text=f"filled {len(done)} field(s): {', '.join(done)} (not submitted)")


async def collect_pages(ctx, args):
    """Extract a table, click 'next', repeat. Stops on max_pages, missing/disabled next, or no new rows."""
    tab = await _tab(ctx, args)
    _no_dialog(tab)
    act = ctx.runtime.actuator
    max_pages = int(args.get("max_pages", 10))
    next_rx = args.get("next_text", r"^(next|下一页|›|»|>)")
    records: list[dict[str, Any]] = []
    seen = set()
    pages = 0
    for pages in range(1, max_pages + 1):
        tables = await act.tables(tab, args.get("table_selector"))
        if not tables:
            break
        new = 0
        for r in _rows_to_records(tables[0]["header"], tables[0]["rows"]):
            key = json.dumps(r, sort_keys=True)
            if key not in seen:
                seen.add(key)
                records.append(r)
                new += 1
        if new == 0 or pages == max_pages:
            break
        if args.get("next_selector"):
            ref = await act.find(tab, css=args["next_selector"])
        else:
            ref = await act.find(tab, role="link", name=next_rx) or await act.find(tab, role="button", name=next_rx)
        if not ref:
            break
        info = await act.element(tab, ref)
        if info.tag == "button" and await act._call_on(tab, *act._resolve(tab, ref)[:2], "function () { return this.disabled; }"):
            break
        await act.click(tab, ref)
        await _settle(tab)
        try:
            await tab.page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
    return _records_result(records, "pages", f" from {pages} page(s)")


async def capture_start(ctx, args):
    tab = await _tab(ctx, args)
    tab.capture_pattern = args.get("url_glob", "*")
    tab.captured.clear()
    return ToolResult(text=f"capturing JSON XHR/fetch on {tab.id} matching {tab.capture_pattern}; "
                           "now trigger the page action, then call net.capture_read")


async def capture_read(ctx, args):
    tab = await _tab(ctx, args)
    items = list(tab.captured)
    if args.get("stop", True):
        tab.capture_pattern = None
    if not items:
        return ToolResult(text="no matching JSON responses captured yet")
    path = paths.ensure(paths.artifacts_dir()) / f"capture-{int(time.time() * 1000)}.json"
    path.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"{i['method']} {i['status']} {i['url']} ({len(i['body'])} bytes)" for i in items[-20:]]
    return ToolResult(text=f"{len(items)} response(s) saved to {path}\n" + "\n".join(lines) +
                      "\nUse the Read tool on the file, or ask for a specific one.", artifacts=[str(path)])


async def download(ctx, args):
    tab = await _tab(ctx, args)
    out_dir = paths.ensure(paths.outputs_dir())
    async with tab.page.expect_download(timeout=int(args.get("timeout_ms", 60000))) as info:
        await ctx.runtime.actuator.click(tab, args["ref"])
    dl = await info.value
    target = out_dir / (args.get("filename") or dl.suggested_filename)
    await dl.save_as(str(target))
    return ToolResult(text=f"downloaded {target} ({target.stat().st_size} bytes)", artifacts=[str(target)])


async def ensure_login(ctx, args):
    """Detect login state; never types credentials. If logged out, ask the human to log in in the browser."""
    tab = await _tab(ctx, args)
    sites = ctx.runtime.sites
    site = sites.get(args["site"])
    if site is None:
        raise ToolError("unknown_site", f"no site pack {args['site']!r}; installed: {', '.join(sites) or 'none'}")
    login = site.login
    if login.get("check_url") and not tab.page.url.startswith(site.base_url):
        await tab.page.goto(site.render(login["check_url"]), wait_until="domcontentloaded")

    async def logged_in() -> bool:
        if login.get("logged_out_url") and re.search(login["logged_out_url"], tab.page.url):
            return False
        if login.get("logged_in_selector"):
            return await ctx.runtime.actuator.find(tab, css=login["logged_in_selector"]) is not None
        return True

    if await logged_in():
        return ToolResult(text=f"logged in to {site.id} (tab {tab.id})", data={"logged_in": True})
    wait_s = int(args.get("wait_seconds", 0))
    await tab.page.bring_to_front()
    deadline = time.time() + wait_s
    while time.time() < deadline:
        await tab.page.wait_for_timeout(2000)
        if await logged_in():
            return ToolResult(text=f"user logged in to {site.id}", data={"logged_in": True})
    raise ToolError("login_required",
                    f"Not logged in to {site.name}. Ask the user to log in manually in tab {tab.id} "
                    f"(credentials are never handled by the agent), then call auth.ensure_login again "
                    f"with wait_seconds=120.", tab=tab.id)


def register(reg: ToolRegistry) -> None:
    S = schema
    add = reg.add
    add(ToolSpec("page.read", "L2", Risk.READ,
                 "Readable text/markdown of the main content (or a CSS selector), paginated by offset/limit.",
                 S({"tab": TAB, "selector": {"type": "string"}, "offset": {"type": "integer"},
                    "limit": {"type": "integer"}}), read))
    add(ToolSpec("data.extract_table", "L2", Risk.READ,
                 "Extract an HTML table/ARIA grid as records. >50 rows are saved to CSV and returned as a path.",
                 S({"tab": TAB, "selector": {"type": "string"}, "index": {"type": "integer"}}), extract_table))
    add(ToolSpec("form.fill", "L2", Risk.INPUT,
                 "Fill many fields at once by ref or label (text, select, checkbox). Does NOT submit. "
                 "Mark sensitive values with secret=true.",
                 S({"tab": TAB, "fields": {"type": "array", "items": {"type": "object", "properties": {
                     "ref": {"type": "string"}, "label": {"type": "string"}, "value": {"type": "string"},
                     "secret": {"type": "boolean"}}}}}, ["fields"]), fill_form))
    add(ToolSpec("data.collect_pages", "L2", Risk.READ,
                 "Paginate through a list: extract table, click next, repeat until max_pages or no new rows.",
                 S({"tab": TAB, "table_selector": {"type": "string"}, "next_selector": {"type": "string"},
                    "next_text": {"type": "string"}, "max_pages": {"type": "integer"}}), collect_pages))
    add(ToolSpec("net.capture_start", "L2", Risk.READ,
                 "Start recording JSON XHR/fetch responses whose URL matches a glob. Often the cheapest way to "
                 "get SaaS dashboard data exactly.",
                 S({"tab": TAB, "url_glob": {"type": "string"}}), capture_start))
    add(ToolSpec("net.capture_read", "L2", Risk.READ, "Return captured JSON responses (saved to a file).",
                 S({"tab": TAB, "stop": {"type": "boolean"}}), capture_read))
    add(ToolSpec("file.download", "L2", Risk.SUBMIT,
                 "Click a ref that triggers a download and save it to the MetaBrowser outputs folder.",
                 S({"ref": REF, "tab": TAB, "filename": {"type": "string"}, "timeout_ms": {"type": "integer"}}, ["ref"]),
                 download, assess=assess_element))
    add(ToolSpec("auth.ensure_login", "L2", Risk.NAVIGATE,
                 "Check whether the browser is logged in to a site pack's site. Never enters credentials; "
                 "if logged out, the user logs in manually (wait_seconds polls for it).",
                 S({"site": {"type": "string"}, "tab": TAB, "wait_seconds": {"type": "integer"}}, ["site"]),
                 ensure_login))

