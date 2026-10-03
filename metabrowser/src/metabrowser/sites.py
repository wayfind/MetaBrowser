"""Site packs: per-site knowledge compiled into L3 tools.

A pack is a directory:

    <pack>/site.json               metadata, login detection, feature/interaction map, risks
    <pack>/capabilities/*.json     recipes exposed as tools `site.<pack>.<capability>`
    <pack>/skills/<name>/SKILL.md  metacodes skills that compose capabilities

Recipes are deterministic step lists. Each element target lists several
locator candidates (role+name, label, text, css) tried in order, so small UI
changes don't break replay. When a step fails, the tool returns a structured
``recipe_failed`` error with the failing step and a fresh snapshot, so the
agent can fall back to L1/L2 tools — and that successful fallback trace is the
input for repairing the recipe.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import paths
from .actuator import render
from .tools.base import Risk, ToolContext, ToolError, ToolRegistry, ToolResult, ToolSpec
from .tools.l1 import _settle
from .tools.l2 import _records_result, _rows_to_records

STEP_KINDS = {"goto", "click", "fill", "select", "press", "wait", "extract_table", "extract_text",
              "assert", "ensure_login", "capture_start", "capture_read"}


class _Vars(dict):
    def __missing__(self, key: str) -> str:
        raise ToolError("invalid_arguments", f"recipe needs argument {key!r}")


@dataclass
class Capability:
    name: str
    description: str
    risk: Risk
    input_schema: dict[str, Any]
    steps: list[dict[str, Any]]
    returns: Optional[str] = None
    reads: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)


@dataclass
class SitePack:
    id: str
    name: str
    base_url: str
    root: Path
    meta: dict[str, Any]
    capabilities: dict[str, Capability]

    @property
    def login(self) -> dict[str, Any]:
        return self.meta.get("login", {})

    def render(self, template: str, args: Optional[dict[str, Any]] = None) -> str:
        return template.format_map(_Vars({"base_url": self.base_url.rstrip("/"), **(args or {})}))

    @property
    def skill_dirs(self) -> list[Path]:
        d = self.root / "skills"
        return sorted(p for p in d.iterdir() if (p / "SKILL.md").exists()) if d.is_dir() else []


def _ident(value: str, what: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", value or ""):
        raise ValueError(f"{what} must match [a-z][a-z0-9_]*: {value!r}")
    return value


def load_pack(root: Path) -> SitePack:
    root = Path(root)
    meta = json.loads((root / "site.json").read_text(encoding="utf-8"))
    site_id = _ident(meta.get("id", ""), "site id")
    caps: dict[str, Capability] = {}
    for f in sorted((root / "capabilities").glob("*.json")) if (root / "capabilities").is_dir() else []:
        c = json.loads(f.read_text(encoding="utf-8"))
        name = _ident(c.get("name", f.stem), f"capability name in {f.name}")
        for i, step in enumerate(c.get("steps", [])):
            if step.get("do") not in STEP_KINDS:
                raise ValueError(f"{f.name} step {i}: unknown 'do' {step.get('do')!r}")
        schema = c.get("input_schema") or {"type": "object", "properties": {}}
        if schema.get("type") != "object":
            raise ValueError(f"{f.name}: input_schema root must be an object")
        caps[name] = Capability(name, c.get("description", name), Risk.parse(c.get("risk", "read")), schema,
                                c.get("steps", []), c.get("returns"), c.get("reads", []), c.get("writes", []))
    # Tenant-specific URL (SaaS subdomains, self-hosted ERP) without editing the pack.
    base_url = os.environ.get(f"METABROWSER_SITE_{site_id.upper()}_URL", meta["base_url"])
    return SitePack(site_id, meta.get("name", site_id), base_url, root, meta, caps)


def discover(extra: list[Path] | None = None) -> list[Path]:
    roots = [paths.bundled_sites_dir(), paths.sites_dir(), *(extra or [])]
    found: dict[str, Path] = {}
    for r in roots:
        if Path(r).is_dir():
            for d in sorted(Path(r).iterdir()):
                if (d / "site.json").exists():
                    found[d.name] = d  # later roots (user-installed) override bundled
    return list(found.values())


# -- recipe execution -----------------------------------------------------

def _render_target(site: SitePack, target: Any, values: dict[str, Any]) -> list[dict[str, Any]]:
    """Substitute {args} into locator candidates; regex fields get escaped values."""
    escaped = {k: re.escape(str(v)) for k, v in values.items()}
    out = []
    for c in target if isinstance(target, list) else [target]:
        c = {"css": c} if isinstance(c, str) else c
        out.append({k: site.render(v, values if k == "css" else escaped) if isinstance(v, str) and k != "role" else v
                    for k, v in c.items()})
    return out


async def _resolve(ctx: ToolContext, tab: Any, candidates: list[dict[str, Any]], timeout_ms: int = 8000) -> str:
    """Try locator candidates in order (each gets a share of the timeout); returns an actuator ref."""
    act = ctx.runtime.actuator
    share = max(500, timeout_ms // max(1, len(candidates)))
    for c in candidates:
        kind = {k: v for k, v in c.items() if k in ("role", "name", "label", "placeholder", "text", "css")}
        if not kind:
            raise ToolError("bad_recipe", f"unknown target candidate {c}")
        ref = await act.find(tab, timeout_ms=share, **kind)
        if ref:
            return ref
    raise ToolError("target_not_found", f"none of the locator candidates matched: {candidates}")


async def run_recipe(ctx: ToolContext, site: SitePack, cap: Capability, args: dict[str, Any]) -> ToolResult:
    tab = await ctx.runtime.tab_for(ctx.session_id, args.get("tab"))
    ctx.notes["tab"] = tab.id
    page = tab.page
    act = ctx.runtime.actuator
    outputs: dict[str, Any] = {}
    # Optional inputs default to "" so templates like "{query}" render as empty.
    values = {**{k: "" for k in cap.input_schema.get("properties", {})}, **args}
    sub = lambda v: site.render(v, values) if isinstance(v, str) else v  # noqa: E731
    tgt = lambda st: _render_target(site, st["target"], values)  # noqa: E731
    for i, step in enumerate(cap.steps):
        kind = step["do"]
        try:
            if kind == "goto":
                await page.goto(sub(step["url"]), wait_until="domcontentloaded")
            elif kind == "ensure_login":
                await ctx.registry.call("auth.ensure_login", {"site": site.id, "tab": tab.id},
                                        session_id=ctx.session_id, actor="recipe")
            elif kind == "click":
                await act.click(tab, await _resolve(ctx, tab, tgt(step)))
                await _settle(tab)
            elif kind == "fill":
                await act.type(tab, await _resolve(ctx, tab, tgt(step)), str(sub(step["value"])))
            elif kind == "select":
                await act.select(tab, await _resolve(ctx, tab, tgt(step)), [str(sub(step["value"]))])
            elif kind == "press":
                ref = await _resolve(ctx, tab, tgt(step)) if step.get("target") else None
                await act.press(tab, step["key"], ref)
                await _settle(tab)
            elif kind == "wait":
                t = int(step.get("timeout_ms", 15000))
                if "text" in step:
                    if not await act.find(tab, text=sub(step["text"]), timeout_ms=t):
                        raise ToolError("timeout", f"text {step['text']!r} did not appear")
                elif "selector" in step:
                    if not await act.find(tab, css=step["selector"], timeout_ms=t):
                        raise ToolError("timeout", f"{step['selector']} did not appear")
                elif "url" in step:
                    await page.wait_for_url(re.compile(sub(step["url"])), timeout=t)
                elif "ms" in step:
                    await page.wait_for_timeout(int(step["ms"]))
                else:
                    await page.wait_for_load_state(step.get("state", "networkidle"), timeout=t)
            elif kind == "assert":
                if "selector" in step and not await act.find(tab, css=step["selector"]):
                    raise ToolError("assert_failed", step.get("message", f"missing {step['selector']}"))
                if "text" in step and not await act.find(tab, text=sub(step["text"])):
                    raise ToolError("assert_failed", step.get("message", f"text not found: {step['text']}"))
            elif kind == "extract_table":
                tables = await act.tables(tab, step.get("selector"))
                if not tables:
                    raise ToolError("no_table", "expected table not found")
                t = tables[int(step.get("index", 0))]
                outputs[step.get("as", "table")] = _rows_to_records(t["header"], t["rows"])
            elif kind == "extract_text":
                outputs[step.get("as", "text")] = await act.read_text(tab, step.get("selector"))
            elif kind == "capture_start":
                tab.capture_pattern = sub(step.get("url_glob", "*"))
                tab.captured.clear()
            elif kind == "capture_read":
                if step.get("wait_ms"):
                    await page.wait_for_timeout(int(step["wait_ms"]))
                outputs[step.get("as", "responses")] = [json.loads(c["body"]) for c in tab.captured]
                tab.capture_pattern = None
        except ToolError as e:
            raise await _recipe_failure(ctx, tab, site, cap, i, step, e.message) from e
        except Exception as e:
            raise await _recipe_failure(ctx, tab, site, cap, i, step, f"{type(e).__name__}: {e}") from e
    key = cap.returns
    if key and isinstance(outputs.get(key), list) and outputs[key] and isinstance(outputs[key][0], dict):
        return _records_result(outputs[key], f"{site.id}-{cap.name}")
    value = outputs.get(key) if key else outputs
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return ToolResult(text=f"{site.id}.{cap.name} ok\n{text[:20000]}", data=value)


async def _recipe_failure(ctx, tab, site, cap, i, step, why) -> ToolError:
    try:
        snap = render(await ctx.runtime.actuator.snapshot(tab, 150), tab.id)
    except Exception:
        snap = "(snapshot unavailable)"
    return ToolError("recipe_failed",
                     f"{site.id}.{cap.name} failed at step {i} ({step['do']}): {why}. "
                     "Continue the task with L1/L2 tools from the current page:\n" + snap,
                     step=i, site=site.id, capability=cap.name)


# -- registration -----------------------------------------------------------

def register_pack(reg: ToolRegistry, site: SitePack) -> None:
    reg.remove_prefix(f"site.{site.id}.")
    reg.runtime.sites[site.id] = site
    rt = reg.runtime
    rt.risk_patterns = [p for p in rt.risk_patterns if getattr(p[0], "site", None) != site.id]
    for risk in site.meta.get("risks", []):
        if risk.get("match_text"):
            rx = _SiteRegex(risk["match_text"], site.id)
            rt.risk_patterns.append((rx, risk.get("url_glob"), Risk.parse(risk.get("level", "submit")),
                                     f"{site.id}: {risk.get('reason', risk.get('id', 'site risk'))}"))
    for cap in site.capabilities.values():
        props = dict(cap.input_schema.get("properties", {}))
        props.setdefault("tab", {"type": "string", "description": "Tab id; defaults to your active tab."})
        schema = {**cap.input_schema, "properties": props}

        async def handler(ctx, args, _site=site, _cap=cap):
            return await run_recipe(ctx, _site, _cap, args)

        reg.add(ToolSpec(f"site.{site.id}.{cap.name}", "L3", cap.risk,
                         f"{site.name}: {cap.description}", schema, handler))


class _SiteRegex:
    """re.Pattern wrapper that remembers its site so a reload can drop old patterns."""

    def __init__(self, pattern: str, site: str):
        self._rx = re.compile(pattern, re.I)
        self.site = site

    def search(self, text: str):
        return self._rx.search(text)


def load_all(reg: ToolRegistry, extra: list[Path] | None = None) -> list[SitePack]:
    packs = []
    for root in discover(extra):
        pack = load_pack(root)
        register_pack(reg, pack)
        packs.append(pack)
    return packs
