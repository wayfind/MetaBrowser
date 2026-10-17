"""Forge tools: turn demonstrations + intent into verified, general site skills.

Lifecycle of a skill (all files under ~/.metabrowser/sites/<site>/, bundled packs are copied
there on first write):
    recording ──recording_draft──► drafts/<name>.json ──skill_draft_test (live, safe mode)──►
    drafts/<name>.tests.json ──skill_promote (all tests pass, ≥2 tests, user approves)──►
    capabilities/<name>.json (+ skills/<site>-<name>/SKILL.md) ──► site_run / site_<id>_<name>

Safe mode: draft tests never execute a step whose real target is submit-level or riskier;
they stop before it and report, so forging a skill cannot place an order or refund by accident.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any

from .. import paths
from ..recorder import compile_recording, load_recording, list_recordings, summarize
from .base import Risk, ToolError, ToolRegistry, ToolResult, ToolSpec, schema

PACK_KEYS = ("modules", "pages", "entities", "risks")


def _ident(value: str, what: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,47}", value or ""):
        raise ToolError("invalid_arguments", f"{what} must match [a-z][a-z0-9_]*: {value!r}")
    return value


def _writable_root(runtime: Any, site_id: str, create: dict | None = None) -> Path:
    """User-owned pack directory; bundled packs are copied on first write."""
    dst = paths.ensure(paths.sites_dir()) / site_id
    pack = runtime.sites.get(site_id)
    if pack is not None and Path(pack.root).resolve() != dst.resolve() and not dst.exists():
        shutil.copytree(pack.root, dst, ignore=shutil.ignore_patterns("drafts"))
    if not (dst / "site.json").exists():
        if create is None:
            raise ToolError("unknown_site", f"no site {site_id!r}; create it with site_map_update(site, patch={{base_url, name}})")
        if not create.get("base_url"):
            raise ToolError("invalid_arguments", "a new site needs patch.base_url")
        dst.mkdir(parents=True, exist_ok=True)
        (dst / "site.json").write_text(json.dumps({"id": site_id, "name": create.get("name", site_id),
                                                   "base_url": create["base_url"], "version": "0.1.0"},
                                                  ensure_ascii=False, indent=1), encoding="utf-8")
    return dst


def _reload(registry: ToolRegistry, root: Path):
    from ..sites import load_pack, register_pack

    pack = load_pack(root)
    register_pack(registry, pack)
    return pack


def _draft_paths(root: Path, name: str) -> tuple[Path, Path]:
    d = paths.ensure(root / "drafts")
    return d / f"{name}.json", d / f"{name}.tests.json"


def _digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


# -- handlers --------------------------------------------------------------------------------

async def recording_list(ctx, args):
    recs = list_recordings()
    return ToolResult(text="\n".join(f"{r['id']} steps={r['steps']} site={r['site'] or '-'} {r['start_url']} "
                                     f"intent={r['intent'][:60]!r}" for r in recs) or "(no recordings)", data=recs)


async def recording_get(ctx, args):
    try:
        rec = load_recording(args["id"])
    except FileNotFoundError as e:
        raise ToolError("not_found", str(e))
    return ToolResult(text=summarize(rec))


async def recording_draft(ctx, args):
    """Mechanical first draft from a recording (to be questioned and generalized)."""
    try:
        rec = load_recording(args["id"])
    except FileNotFoundError as e:
        raise ToolError("not_found", str(e))
    site_id, name = _ident(args["site"], "site"), _ident(args["name"], "name")
    pack = ctx.runtime.sites.get(site_id)
    base = pack.base_url if pack else re.match(r"^[a-z]+://[^/]+", rec.start_url).group(0)
    root = _writable_root(ctx.runtime, site_id, create={"base_url": base, "name": site_id})
    if pack is None:
        _reload(ctx.registry, root)
    draft = compile_recording(rec, base, name, args.get("description", ""))
    dpath, tpath = _draft_paths(root, name)
    dpath.write_text(json.dumps(draft, ensure_ascii=False, indent=1), encoding="utf-8")
    tpath.unlink(missing_ok=True)
    return ToolResult(text=f"draft {site_id}.{name} written ({len(draft['steps'])} steps, params "
                           f"{list(draft['input_schema']['properties'])}). Notes: {draft['x-forge']['notes']}\n"
                           + json.dumps(draft, ensure_ascii=False, indent=1)[:6000], data=draft)


async def site_map_get(ctx, args):
    site_id = args["site"]
    pack = ctx.runtime.sites.get(site_id)
    root = paths.sites_dir() / site_id
    if pack is None and not (root / "site.json").exists():
        return ToolResult(text=f"no site {site_id!r} yet. Known sites: {', '.join(ctx.runtime.sites) or 'none'}. "
                               "Create it with site_map_update(site, patch={base_url, name, pages, ...}).")
    meta = pack.meta if pack else json.loads((root / "site.json").read_text())
    out = {k: meta.get(k) for k in ("id", "name", "base_url", "login", *PACK_KEYS) if meta.get(k) is not None}
    out["capabilities"] = {c.name: {"params": list(c.input_schema.get("properties", {})), "risk": c.risk.label,
                                    "description": c.description, "tests": len(c.tests)}
                           for c in (pack.capabilities.values() if pack else [])}
    drafts = {}
    for d in sorted((root / "drafts").glob("*.json")) if (root / "drafts").is_dir() else []:
        if d.name.endswith(".tests.json"):
            continue
        res = d.with_name(d.stem + ".tests.json")
        status = json.loads(res.read_text()).get("summary", "untested") if res.exists() else "untested"
        drafts[d.stem] = status
    out["drafts"] = drafts
    return ToolResult(text=json.dumps(out, ensure_ascii=False, indent=1)[:12000], data=out)


async def site_map_update(ctx, args):
    """Merge pages/actions/entities/risks/modules by id; create the site if new."""
    site_id = _ident(args["site"], "site")
    patch = args.get("patch") or {}
    root = _writable_root(ctx.runtime, site_id, create=patch)
    meta = json.loads((root / "site.json").read_text(encoding="utf-8"))
    for key in ("name", "base_url", "login", "description"):
        if key in patch:
            meta[key] = patch[key]
    changed = []
    for key in PACK_KEYS:
        for item in patch.get(key, []) or []:
            if not isinstance(item, dict) or not item.get("id"):
                raise ToolError("invalid_arguments", f"{key} items need an id")
            items = meta.setdefault(key, [])
            items[:] = [x for x in items if x.get("id") != item["id"]] + [item]
            changed.append(f"{key}:{item['id']}")
    (root / "site.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    _reload(ctx.registry, root)
    return ToolResult(text=f"site {site_id} updated: {', '.join(changed) or 'metadata'}")


async def skill_draft_save(ctx, args):
    from ..sites import capability_from_dict

    site_id = _ident(args["site"], "site")
    cap = dict(args["capability"])
    try:
        capability_from_dict(cap, "draft")
    except ValueError as e:
        raise ToolError("invalid_draft", str(e))
    root = _writable_root(ctx.runtime, site_id)
    cap.setdefault("x-forge", {})["status"] = "draft"
    dpath, tpath = _draft_paths(root, cap["name"])
    dpath.write_text(json.dumps(cap, ensure_ascii=False, indent=1), encoding="utf-8")
    tpath.unlink(missing_ok=True)  # any edit invalidates earlier test results
    if args.get("skill_md"):
        (dpath.with_suffix(".SKILL.md")).write_text(args["skill_md"], encoding="utf-8")
    warn = "" if len(cap.get("tests", [])) >= 2 else " — add at least one variation test before promoting"
    return ToolResult(text=f"saved draft {site_id}.{cap['name']} ({len(cap.get('steps', []))} steps, "
                           f"{len(cap.get('tests', []))} tests){warn}")


def _check(expect: dict, result: ToolResult) -> tuple[bool, str]:
    data = result.data
    rows = data if isinstance(data, list) else None
    if isinstance(data, dict) and "count" in data:  # saved to CSV
        rows_count = data["count"]
    else:
        rows_count = len(rows) if rows is not None else None
    problems = []
    if "min_rows" in expect and (rows_count is None or rows_count < expect["min_rows"]):
        problems.append(f"rows={rows_count} < min_rows={expect['min_rows']}")
    if "max_rows" in expect and rows_count is not None and rows_count > expect["max_rows"]:
        problems.append(f"rows={rows_count} > max_rows={expect['max_rows']}")
    if "fields" in expect and rows:
        missing = [f for f in expect["fields"] if f not in rows[0]]
        if missing:
            problems.append(f"missing fields {missing}")
    for needle in expect.get("contains", []) if isinstance(expect.get("contains"), list) else \
            ([expect["contains"]] if expect.get("contains") else []):
        if needle not in result.text:
            problems.append(f"output lacks {needle!r}")
    if "all_rows_match" in expect and rows:
        for fld, pattern in expect["all_rows_match"].items():
            bad = [r.get(fld) for r in rows if not re.search(pattern, str(r.get(fld, "")))]
            if bad:
                problems.append(f"{fld} not matching {pattern!r}: {bad[:3]}")
    return not problems, "; ".join(problems) or "ok"


async def skill_draft_test(ctx, args):
    from ..sites import SafeStop, SitePack, capability_from_dict, run_recipe

    site_id, name = args["site"], args["name"]
    root = _writable_root(ctx.runtime, site_id)
    dpath, tpath = _draft_paths(root, name)
    if not dpath.exists():
        raise ToolError("not_found", f"no draft {site_id}.{name}; save one with skill_draft_save")
    draft = json.loads(dpath.read_text(encoding="utf-8"))
    cap = capability_from_dict(draft, "draft")
    pack = ctx.runtime.sites.get(site_id)
    site = pack or SitePack(site_id, site_id, json.loads((root / "site.json").read_text())["base_url"], root,
                            json.loads((root / "site.json").read_text()), {})
    cases = [{"args": args["args"], "expect": args.get("expect", {})}] if args.get("args") is not None else draft.get("tests", [])
    if not cases:
        raise ToolError("no_tests", "the draft has no tests; add tests or pass args")
    tab = await ctx.runtime.tab_for(ctx.session_id, args.get("tab"))
    ctx.notes["tab"] = tab.id
    results, lines = [], []
    for i, case in enumerate(cases):
        log: list = []
        entry = {"case": i, "args": case.get("args", {})}
        try:
            res = await run_recipe(ctx, site, cap, {**case.get("args", {}), "tab": tab.id}, safe_mode=True, log=log)
            ok, why = _check(case.get("expect", {}), res)
            sample = res.data[:3] if isinstance(res.data, list) else (res.data if not isinstance(res.data, str) else res.data[:300])
            entry.update(ok=ok, detail=why, sample=sample, data_digest=_digest(res.data))
        except SafeStop as e:
            entry.update(ok=False, detail=f"safe stop: {e} — a draft test never runs submit/irreversible steps; "
                                          "declare the capability's risk and test up to that step")
        except ToolError as e:
            entry.update(ok=False, detail=e.message[:1500])
        entry["steps"] = log
        results.append(entry)
        lines.append(f"case {i} {'PASS' if entry['ok'] else 'FAIL'} args={entry['args']} — {entry['detail'][:600]}"
                     + (f"\n  sample: {json.dumps(entry.get('sample'), ensure_ascii=False)[:500]}" if entry.get("sample") else ""))
    # Automatic skepticism: different arguments must not yield identical data — otherwise the
    # parameter has no effect (e.g. a search box that never got the value, a stale page read).
    digests: dict[str, list[int]] = {}
    for r in results:
        if r.get("ok") and "data_digest" in r:
            digests.setdefault(r["data_digest"], []).append(r["case"])
    for same in digests.values():
        argsets = {json.dumps(results[c]["args"], sort_keys=True) for c in same}
        if len(same) > 1 and len(argsets) > 1:
            for c in same:
                results[c]["ok"] = False
                results[c]["detail"] = (f"cases {same} returned identical data for different arguments — the parameters "
                                        "have no effect; fix the steps (or the tests) so each case is discriminating")
                lines[c] = f"case {c} FAIL args={results[c]['args']} — {results[c]['detail']}"
    passed = sum(r["ok"] for r in results)
    if args.get("args") is None:  # full test run: record for promotion
        tpath.write_text(json.dumps({"draft": _digest(draft), "results": results,
                                     "summary": f"{passed}/{len(results)} pass"}, ensure_ascii=False, indent=1))
    return ToolResult(text=f"{site_id}.{name}: {passed}/{len(results)} pass\n" + "\n".join(lines),
                      data={"passed": passed, "total": len(results)})


async def skill_promote(ctx, args):
    site_id, name = args["site"], args["name"]
    root = _writable_root(ctx.runtime, site_id)
    dpath, tpath = _draft_paths(root, name)
    if not dpath.exists():
        raise ToolError("not_found", f"no draft {site_id}.{name}")
    draft = json.loads(dpath.read_text(encoding="utf-8"))
    if len(draft.get("tests", [])) < 2:
        raise ToolError("not_verified", "promotion needs at least two tests: the demonstration and a variation")
    if not tpath.exists():
        raise ToolError("not_verified", "run skill_draft_test (all tests) on this draft first")
    report = json.loads(tpath.read_text())
    if report.get("draft") != _digest(draft):
        raise ToolError("not_verified", "the draft changed after its last test run; test it again")
    if not all(r["ok"] for r in report["results"]):
        raise ToolError("not_verified", f"tests failing: {report['summary']}")
    draft.setdefault("x-forge", {})["status"] = "promoted"
    caps = paths.ensure(root / "capabilities")
    (caps / f"{name}.json").write_text(json.dumps(draft, ensure_ascii=False, indent=1), encoding="utf-8")
    skill_md = args.get("skill_md")
    md_draft = dpath.with_suffix(".SKILL.md")
    if not skill_md and md_draft.exists():
        skill_md = md_draft.read_text(encoding="utf-8")
    if skill_md:
        sdir = paths.ensure(root / "skills" / f"{site_id.replace('_', '-')}-{name.replace('_', '-')}")
        (sdir / "SKILL.md").write_text(skill_md, encoding="utf-8")
    pack = _reload(ctx.registry, root)
    return ToolResult(text=f"promoted {site_id}.{name}: callable now via site_run(site={site_id!r}, capability={name!r}); "
                           f"{len(pack.capabilities)} capabilities in {site_id}. New agent sessions also see its SKILL.md.")


def register(reg: ToolRegistry) -> None:
    S = schema
    add = reg.add
    add(ToolSpec("recording.list", "L2", Risk.READ, "List recorded user demonstrations (id, start URL, intent).",
                 S(), recording_list))
    add(ToolSpec("recording.get", "L2", Risk.READ,
                 "A recorded demonstration as semantic steps (targets, values, navigations, JSON APIs seen) plus "
                 "page snapshots, and the user's stated intent.", S({"id": {"type": "string"}}, ["id"]), recording_get))
    add(ToolSpec("recording.draft", "L2", Risk.INPUT,
                 "Mechanically compile a recording into a first capability draft (parameters from typed values, "
                 "multi-candidate targets). Question and generalize it before testing.",
                 S({"id": {"type": "string"}, "site": {"type": "string"}, "name": {"type": "string"},
                    "description": {"type": "string"}}, ["id", "site", "name"]), recording_draft))
    add(ToolSpec("site_map.get", "L2", Risk.READ,
                 "What MetaBrowser knows about a site: pages, actions, entities, risks, capabilities, drafts.",
                 S({"site": {"type": "string"}}, ["site"]), site_map_get))
    add(ToolSpec("site_map.update", "L2", Risk.INPUT,
                 "Merge knowledge into a site map by id (modules/pages/entities/risks; name/base_url/login). "
                 "Creates the site when new (patch.base_url required).",
                 S({"site": {"type": "string"}, "patch": {"type": "object"}}, ["site", "patch"]), site_map_update))
    add(ToolSpec("skill.draft_save", "L2", Risk.INPUT,
                 "Save a capability draft (recipe JSON with name, description, risk, input_schema, steps, returns, "
                 "tests[{args, expect:{min_rows,max_rows,fields,contains,all_rows_match}}]) and optional SKILL.md.",
                 S({"site": {"type": "string"}, "capability": {"type": "object"}, "skill_md": {"type": "string"}},
                   ["site", "capability"]), skill_draft_save))
    add(ToolSpec("skill.draft_test", "L2", Risk.NAVIGATE,
                 "Run a draft in the live browser in safe mode (never executes submit/irreversible steps): all its "
                 "tests, or one ad-hoc case with args/expect. Returns per-case pass/fail, step log, data sample.",
                 S({"site": {"type": "string"}, "name": {"type": "string"}, "args": {"type": "object"},
                    "expect": {"type": "object"}, "tab": {"type": "string"}}, ["site", "name"]), skill_draft_test))
    add(ToolSpec("skill.promote", "L2", Risk.SUBMIT,
                 "Activate a draft whose tests (≥2, current version) all passed; makes it callable via site_run. "
                 "Requires the user's approval.",
                 S({"site": {"type": "string"}, "name": {"type": "string"}, "skill_md": {"type": "string"}},
                   ["site", "name"]), skill_promote))
