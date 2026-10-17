"""Run an evaluation suite against the real MetaBrowser agent stack.

Per task × repeat, everything is fresh and isolated: METABROWSER_HOME/outputs/workspace, a
browser context (shared engine), ToolRegistry + PolicyGate + trace, AgentCore runtime + session.
Approvals are answered by the task's policy (e.g. irreversible → deny) and recorded.

Metrics per run: success + per-grader detail, turns, tool calls by tool and layer (L1/L2/L3/
builtin), tokens (input/output/cache read/cache write), wall time, approvals asked, tool error
codes, prompt sha. Outputs: runs.jsonl, summary.json, report.md; `compare` makes paired deltas.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .. import paths
from . import envs
from .suite import SUITE_SITES, SUITES, GradeContext, Task


@dataclass
class RunConfig:
    out: Path
    suite: str = "core"
    tasks: Optional[list[str]] = None
    repeat: int = 1
    label: str = ""
    engine: str = "ungoogled"              # ungoogled | chromium (auto = ungoogled)
    headless: bool = True
    chromium_path: Optional[str] = None
    library: Optional[Path] = None
    agent_overrides: dict[str, Any] = field(default_factory=dict)   # model/provider/base_url/…
    mock: Optional[dict[str, Callable[[str], Any]]] = None           # task id -> script factory(base_url)


@dataclass
class TaskCtx:
    stack: Any
    base_url: str
    extra: dict[str, Any] = field(default_factory=dict)


async def _engine(cfg: RunConfig):
    """Use the same engine/launch flags as the product. No implicit commercial fallback."""
    from ..engine import Engine
    from ..runtime import LaunchOptions

    selected = "ungoogled" if cfg.engine == "auto" else cfg.engine
    owner = Engine(LaunchOptions(engine=selected, browser_path=cfg.chromium_path, headless=cfg.headless))
    browser = await owner.start()
    return browser, owner, selected


def _policy_ui(record: list):
    def ui(sid: str, request: dict) -> Optional[dict]:
        from ..agentcore import permission_response

        if request.get("type") == "permission":
            tool = request["tool"]["name"]
            choice = "allow_once" if tool in ("Read", "Write", "Edit") else "deny_once"
            record.append({"kind": "agentcore", "tool": tool, "answer": choice})
            return permission_response(request, choice)
        questions = request.get("ask_question") or []
        record.append({"kind": "question", "n": len(questions)})
        return {"answers": [{"values": [q["options"][0]["label"]] if q.get("options") else []} for q in questions]}
    return ui


async def run_task(task: Task, rep: int, cfg: RunConfig, browser: Any, env: envs.EnvServer, engine: str) -> dict[str, Any]:
    from ..agentcore import AgentConfig, AgentHost
    from ..stack import build_stack

    run_dir = paths.ensure(cfg.out / "runs" / task.id.replace("/", "_") / f"r{rep}")
    # same layout as the product (~/MetaBrowser with outputs/ inside): "outputs/x.csv" written
    # relative to the workspace lands in the outputs folder graders read
    home, outputs = run_dir / "home", run_dir / "workspace" / "outputs"
    for d in (home, outputs):
        d.mkdir(parents=True, exist_ok=True)
    os.environ.update(METABROWSER_HOME=str(home), METABROWSER_OUTPUTS=str(outputs),
                      METABROWSER_WORKSPACE=str(run_dir / "workspace"), METABROWSER_SITE_EXAMPLE_SHOP_URL=env.url)
    env.reset()
    context = await browser.new_context(accept_downloads=True, viewport={"width": 1280, "height": 900})
    from ..engine import patch_context

    patch_context(context)
    await context.add_cookies(env.cookies())
    external: list[str] = []

    async def sandbox(route):
        # network sandbox: fixture hosts only; anything else is a violation and is never fetched
        url = route.request.url
        host = url.split("/")[2].split(":")[0] if "://" in url else ""
        if host in ("127.0.0.1", "localhost") or url.startswith(("data:", "about:", "blob:")):
            await route.continue_()
        else:
            external.append(url[:200])
            await route.abort()

    await context.route("**/*", sandbox)
    stack = build_stack(context=context, trace_path=run_dir / "trace.ndjson")
    await stack.runtime.start()
    approvals: list[dict] = []

    async def approver(req):
        answer = task.approvals.get(req.risk, "deny")
        approvals.append({"kind": "browser", "tool": req.tool, "risk": req.risk, "answer": answer, "reason": req.reason})
        return answer

    stack.gate.approver = approver
    loop = asyncio.get_running_loop()
    mock_llm = None
    overrides = dict(cfg.agent_overrides)
    if cfg.mock and task.id in cfg.mock:
        import importlib

        mock_mod = importlib.import_module("mock_llm")  # test helper (tests/mock_llm.py on sys.path)
        mock_llm = mock_mod.MockLLM(cfg.mock[task.id](env.url))
        overrides.update(base_url=await mock_llm.start(), api_key="mock")
    agent_cfg = AgentConfig.load()
    for k, v in overrides.items():
        setattr(agent_cfg, k, v)
    agent_cfg.workspace_root = run_dir / "workspace"
    agent_cfg.workspace_home = home / "agent"
    agent_cfg.max_turns = task.max_turns
    skill_dirs = [("builtin", Path(__file__).resolve().parents[1] / "skills")]
    skill_dirs += [(f"site.{p.id}", p.root / "skills") for p in stack.packs]
    host = AgentHost(stack.registry, loop, agent_cfg, ui_handler=_policy_ui(approvals), skill_dirs=skill_dirs,
                     library=cfg.library)
    result: dict[str, Any] = {"task": task.id, "category": task.category, "rep": rep, "engine": engine,
                              "model": agent_cfg.model, "label": cfg.label}
    started = time.time()
    try:
        await loop.run_in_executor(None, host.start)
        ctx = TaskCtx(stack, env.url)
        session_context = await task.setup(ctx) if task.setup else []
        sess = await loop.run_in_executor(None, lambda: host.create_session(f"eval {task.id}", task.mode, session_context))
        host.send(sess.id, task.instruction.format(base=env.url))
        deadline = time.time() + task.timeout_s
        while sess.running and time.time() < deadline:
            await asyncio.sleep(0.2)
        timed_out = sess.running
        if timed_out:
            await loop.run_in_executor(None, host.abort, sess.id)
            while sess.running:
                await asyncio.sleep(0.1)
        events = [e for _, e in host.events_since(sess.id)]
        result.update(_metrics(events, stack.registry), timed_out=timed_out)
        answer = result.pop("answer")
        trace = [json.loads(l) for l in (run_dir / "trace.ndjson").read_text().splitlines() if l.strip()]
        gctx = GradeContext(answer=answer, outputs=outputs, state=dict(env.state.to_dict()), registry=stack.registry,
                            base_url=env.url, trace=trace)
        grades = []
        for g in task.graders:
            try:
                ok, detail = await g(gctx)
            except Exception as e:
                ok, detail = False, f"grader error: {type(e).__name__}: {e}"
            grades.append({"grader": getattr(g, "__name__", "grader"), "ok": ok, "detail": detail})
        if external:
            grades.append({"grader": "network_sandbox", "ok": False,
                           "detail": f"left the sandbox: {len(external)} external request(s), e.g. {external[0]}"})
        result.update(success=all(x["ok"] for x in grades) and not timed_out, grades=grades, external_requests=external,
                      answer=answer[-2000:], approvals=approvals,
                      tool_errors=dict(Counter(t["error"]["code"] for t in trace if t.get("type") == "tool_call" and t.get("error"))))
    except Exception as e:
        result.update(success=False, error=f"{type(e).__name__}: {e}")
    finally:
        result["wall_s"] = round(time.time() - started, 1)
        try:
            await loop.run_in_executor(None, host.stop)
        except Exception:
            pass
        if mock_llm:
            await mock_llm.stop()
        await stack.runtime.stop()
        await context.close()
    (run_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return result


def _metrics(events: list[dict], registry: Any) -> dict[str, Any]:
    text, tools, usage = [], Counter(), Counter()
    run_done, sha = {}, None
    for e in events:
        if "user_message" in e:
            text.clear()
        core = e.get("core_event") or {}
        if isinstance(core.get("text_chunk"), str):
            text.append(core["text_chunk"])
        if core.get("tool_start"):
            text.append("\n")  # answer = text after the last tool call
            tools[core["tool_start"]["name"]] += 1
        if isinstance(core.get("usage"), dict):
            usage.update({k: v for k, v in core["usage"].items() if isinstance(v, int)})
        if core.get("prompt_manifest"):
            sha = core["prompt_manifest"].get("sha256")
        if "run_done" in e:
            run_done = e["run_done"]
    answer = "".join(text).strip()
    layers = Counter()
    for name, n in tools.items():
        spec = registry.get(name)
        layers[spec.layer if spec else "builtin"] += n
    return {"answer": answer, "turns": run_done.get("turns", 0), "tool_calls": sum(tools.values()),
            "tools": dict(tools), "layers": dict(layers), "stop_reason": run_done.get("stop_reason"),
            "tokens": {"input": usage["input_tokens"], "output": usage["output_tokens"],
                       "cache_read": usage["cache_read_input_tokens"], "cache_write": usage["cache_creation_input_tokens"]},
            "prompt_sha": sha}


async def run_suite(cfg: RunConfig) -> dict[str, Any]:
    tasks = [t for t in SUITES[cfg.suite]() if not cfg.tasks or t.id in cfg.tasks]
    if not tasks:
        raise SystemExit(f"no tasks selected from suite {cfg.suite}")
    cfg.out.mkdir(parents=True, exist_ok=True)
    if cfg.library is None:  # resolve against the real home before runs switch to isolated homes
        from ..agentcore import abi

        cfg.library = next((c for c in abi.library_candidates() if c.is_file()), None)
        if cfg.library is None:
            raise SystemExit("AgentCore library not found: run `metabrowser agent build-core` first")
    provenance = _freeze(cfg)
    rg = Path(cfg.library).parent.parent / "bin" / "rg"
    if "RG_BIN" not in os.environ and rg.is_file():
        os.environ["RG_BIN"] = str(rg)
    env = envs.EnvServer()
    await env.start()
    browser, owner, engine = await _engine(cfg)
    saved_env = {k: os.environ.get(k) for k in ("METABROWSER_HOME", "METABROWSER_OUTPUTS", "METABROWSER_WORKSPACE",
                                                 "METABROWSER_SITE_EXAMPLE_SHOP_URL", "METABROWSER_BUNDLED_SITES")}
    os.environ["METABROWSER_BUNDLED_SITES"] = provenance["sites_snapshot"]
    results = []
    try:
        with (cfg.out / "runs.jsonl").open("a", encoding="utf-8") as fh:
            for task in tasks:
                for rep in range(cfg.repeat):
                    r = await run_task(task, rep, cfg, browser, env, engine)
                    results.append(r)
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
                    fh.flush()
                    print(f"{'PASS' if r.get('success') else 'FAIL'} {task.id} r{rep} turns={r.get('turns')} "
                          f"tools={r.get('tool_calls')} tok_in={r.get('tokens', {}).get('input')} {r.get('wall_s')}s"
                          + ("" if r.get("success") else f"  {[g['detail'] for g in r.get('grades', []) if not g['ok']] or r.get('error')}"),
                          flush=True)
    finally:
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        await owner.stop()
        await env.stop()
    summary = summarize(results, cfg)
    summary["provenance"] = provenance
    (cfg.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    (cfg.out / "report.md").write_text(render_report(summary), encoding="utf-8")
    return summary


def _freeze(cfg: RunConfig) -> dict[str, Any]:
    """Pin what this run evaluates: a copy of the site packs (edits during a run cannot leak in) and
    the identity of code, prompts, AgentCore and model, so A/B comparisons are reproducible."""
    import hashlib
    import shutil
    import subprocess

    from ..agentcore import profiles

    snap = cfg.out / "sites_snapshot"
    if snap.exists():
        shutil.rmtree(snap)
    snap.mkdir(parents=True)
    for name in SUITE_SITES.get(cfg.suite, []):
        shutil.copytree(paths.bundled_sites_dir() / name, snap / name)

    def tree_hash(root: Path) -> str:
        h = hashlib.sha256()
        for f in sorted(root.rglob("*")):
            if f.is_file():
                h.update(str(f.relative_to(root)).encode() + b"\0" + f.read_bytes())
        return h.hexdigest()[:16]

    repo = Path(__file__).resolve().parents[3]
    git = lambda *a: subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True).stdout.strip()  # noqa: E731
    manifest = Path(cfg.library).parent.parent / "manifest.json"
    prompt_hash = hashlib.sha256(json.dumps({m: [e.__dict__ for e in profiles.profile(m)] for m in profiles.PROFILES},
                                            ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    return {"git_commit": git("rev-parse", "--short", "HEAD"), "git_dirty": bool(git("status", "--porcelain", "--", ".")),
            "code_hash": tree_hash(Path(__file__).resolve().parents[1]), "sites_hash": tree_hash(snap),
            "prompt_profiles_hash": prompt_hash, "sites_snapshot": str(snap),
            "agentcore": json.loads(manifest.read_text()).get("version") if manifest.exists() else None,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S")}


def _mean(xs: list[float]) -> float:
    return round(statistics.mean(xs), 1) if xs else 0.0


def summarize(results: list[dict[str, Any]], cfg: Optional[RunConfig] = None) -> dict[str, Any]:
    by_task: dict[str, list[dict]] = {}
    for r in results:
        by_task.setdefault(r["task"], []).append(r)
    tasks = {}
    for tid, rs in by_task.items():
        tasks[tid] = {
            "category": rs[0]["category"], "runs": len(rs),
            "pass_rate": round(sum(bool(r.get("success")) for r in rs) / len(rs), 3),
            "pass_all": all(r.get("success") for r in rs),           # pass^k: stable across repeats
            "turns": _mean([r.get("turns", 0) for r in rs]), "tool_calls": _mean([r.get("tool_calls", 0) for r in rs]),
            "tokens_in": _mean([r.get("tokens", {}).get("input", 0) for r in rs]),
            "tokens_out": _mean([r.get("tokens", {}).get("output", 0) for r in rs]),
            "cache_read": _mean([r.get("tokens", {}).get("cache_read", 0) for r in rs]),
            "wall_s": _mean([r.get("wall_s", 0) for r in rs]),
            "layers": dict(sum((Counter(r.get("layers", {})) for r in rs), Counter())),
            "failures": [{"rep": r["rep"], "why": [g["detail"] for g in r.get("grades", []) if not g["ok"]] or [r.get("error")],
                          "tool_errors": r.get("tool_errors", {})} for r in rs if not r.get("success")],
        }
    cats: dict[str, list[float]] = {}
    for t in tasks.values():
        cats.setdefault(t["category"], []).append(t["pass_rate"])
    all_layers = sum((Counter(t["layers"]) for t in tasks.values()), Counter())
    return {
        "label": cfg.label if cfg else "", "suite": cfg.suite if cfg else "", "repeat": cfg.repeat if cfg else 1,
        "engine": results[0].get("engine") if results else "", "model": results[0].get("model") if results else "",
        "pass_rate": round(sum(t["pass_rate"] for t in tasks.values()) / max(1, len(tasks)), 3),
        "stable_pass_rate": round(sum(t["pass_all"] for t in tasks.values()) / max(1, len(tasks)), 3),
        "mean_tokens_in": _mean([t["tokens_in"] for t in tasks.values()]),
        "mean_turns": _mean([t["turns"] for t in tasks.values()]),
        "mean_wall_s": _mean([t["wall_s"] for t in tasks.values()]),
        "layer_share": {k: round(v / max(1, sum(all_layers.values())), 3) for k, v in all_layers.items()},
        "categories": {c: round(sum(v) / len(v), 3) for c, v in cats.items()},
        "tasks": tasks,
    }


def render_report(s: dict[str, Any]) -> str:
    lines = [f"# MetaBrowser eval — {s.get('label') or s.get('suite')}", "",
             f"engine `{s.get('engine')}` · model `{s.get('model')}` · repeat {s.get('repeat')}",
             "provenance: " + ", ".join(f"{k}={v}" for k, v in (s.get("provenance") or {}).items() if k != "sites_snapshot"), "",
             f"- pass rate **{s['pass_rate']:.0%}** (stable across all repeats: {s['stable_pass_rate']:.0%})",
             f"- mean per task: {s['mean_turns']} turns · {s['mean_tokens_in']:.0f} input tokens · {s['mean_wall_s']} s",
             f"- tool layer share: " + ", ".join(f"{k} {v:.0%}" for k, v in sorted(s["layer_share"].items())),
             "", "| category | pass |", "|---|---|"]
    lines += [f"| {c} | {v:.0%} |" for c, v in sorted(s["categories"].items())]
    lines += ["", "| task | pass | turns | tools | tokens in | out | cache read | s | layers |", "|---|---|---|---|---|---|---|---|---|"]
    for tid, t in s["tasks"].items():
        layers = " ".join(f"{k}:{v}" for k, v in sorted(t["layers"].items()))
        lines.append(f"| {tid} | {t['pass_rate']:.0%} | {t['turns']} | {t['tool_calls']} | {t['tokens_in']:.0f} | "
                     f"{t['tokens_out']:.0f} | {t['cache_read']:.0f} | {t['wall_s']} | {layers} |")
    fails = [(tid, f) for tid, t in s["tasks"].items() for f in t["failures"]]
    if fails:
        lines += ["", "## Failures", ""]
        lines += [f"- **{tid}** r{f['rep']}: {'; '.join(map(str, f['why']))[:400]}"
                  + (f" — tool errors {f['tool_errors']}" if f["tool_errors"] else "") for tid, f in fails]
    return "\n".join(lines) + "\n"


def compare(a: dict[str, Any], b: dict[str, Any]) -> str:
    """Paired comparison B vs A over the tasks both ran."""
    lines = [f"# {b.get('label') or 'B'} vs {a.get('label') or 'A'}", "",
             f"- pass rate {a['pass_rate']:.0%} → {b['pass_rate']:.0%} ({(b['pass_rate'] - a['pass_rate']) * 100:+.0f} pts)",
             f"- stable pass {a['stable_pass_rate']:.0%} → {b['stable_pass_rate']:.0%}",
             f"- mean input tokens {a['mean_tokens_in']:.0f} → {b['mean_tokens_in']:.0f} "
             f"({(b['mean_tokens_in'] / a['mean_tokens_in'] - 1) * 100 if a['mean_tokens_in'] else 0:+.0f}%)",
             f"- mean turns {a['mean_turns']} → {b['mean_turns']}", "",
             "| task | pass A→B | turns A→B | tokens in A→B |", "|---|---|---|---|"]
    for tid in a["tasks"]:
        if tid not in b["tasks"]:
            continue
        x, y = a["tasks"][tid], b["tasks"][tid]
        flag = " ⬆" if y["pass_rate"] > x["pass_rate"] else (" ⬇" if y["pass_rate"] < x["pass_rate"] else "")
        lines.append(f"| {tid} | {x['pass_rate']:.0%}→{y['pass_rate']:.0%}{flag} | {x['turns']}→{y['turns']} | "
                     f"{x['tokens_in']:.0f}→{y['tokens_in']:.0f} |")
    return "\n".join(lines) + "\n"
