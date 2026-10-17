"""metabrowser command line.

  metabrowser                          start MetaBrowser: browser + native side panel + embedded metacodes agent
  metabrowser serve [--no-agent ...]   same, with options (headless, no panel, port, profile ...)
  metabrowser mcp                      stdio MCP bridge to the running daemon (auto-starts it)
  metabrowser mcp --standalone         stdio MCP with an in-process browser (no daemon)
  metabrowser agent build-core         build + install the AgentCore library from a metacodes checkout
  metabrowser agent status             is the embedded agent ready? (library, model config, key present)
  metabrowser agent register-mcp       let a standalone metacodes CLI use this browser via MCP
  metabrowser tools                    list tools (no browser needed)
  metabrowser site list|validate|install|kg-export|kg-sync
  metabrowser trace list|show|verify
  metabrowser record list              recorded demonstrations (record from the side panel)
  metabrowser eval run [--tasks …]     evaluate the agent on the fixture suite (real model from env)
  metabrowser eval report|compare      render / compare eval results
  metabrowser eval serve               run the fixture sites (shop, back-office, ad platform) to try things
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import paths


def _launch_options(a):
    from .runtime import LaunchOptions

    return LaunchOptions(profile=a.profile, headless=a.headless, humanize=not a.no_humanize, proxy=a.proxy,
                         args=list(a.browser_arg), engine=a.engine, browser_path=a.browser_path)


def _add_browser_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--profile", default="default", help="persistent profile name under ~/.metabrowser/profiles")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--no-humanize", action="store_true")
    p.add_argument("--proxy")
    p.add_argument("--site-dir", action="append", type=Path, default=[], help="extra site pack root (repeatable)")
    p.add_argument("--browser-arg", action="append", default=[], help="extra Chromium flag (repeatable)")
    p.add_argument("--engine", default="ungoogled", choices=["ungoogled", "chromium"],
                   help="default: ungoogled-chromium; chromium explicitly uses Playwright's test browser")
    p.add_argument("--browser-path", help="browser executable or Chromium.app (or METABROWSER_BROWSER_PATH)")


# -- serve ---------------------------------------------------------------------

def cmd_serve(a) -> int:
    import logging

    from .server import read_daemon_file, run_daemon, stage_extension
    from .stack import build_stack

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    existing = read_daemon_file()
    if existing and _daemon_alive(existing):
        print(f"MetaBrowser is already running on port {existing['port']} (pid {existing.get('pid')})")
        return 0
    if a.detach:
        log = (paths.ensure(paths.home() / "logs") / "daemon.log").open("ab")
        argv = [sys.executable, "-m", "metabrowser", "serve", *[x for x in sys.argv[2:] if x != "--detach"]]
        subprocess.Popen(argv, stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
        return 0 if _wait_daemon(60) else 1

    token = secrets.token_urlsafe(32)
    opts = _launch_options(a)
    panel = not (a.no_panel or a.headless)
    if panel:
        opts.extension_paths.append(str(stage_extension(a.port, token)))
    stack = build_stack(opts, site_dirs=a.site_dir)
    print(f"metabrowser: {len(stack.registry.list())} tools, sites={[p.id for p in stack.packs]}, "
          f"trace={stack.trace.path}", file=sys.stderr)
    print(f"MCP endpoint: http://127.0.0.1:{a.port}/mcp  (token in {paths.daemon_file()})", file=sys.stderr)
    try:
        asyncio.run(run_daemon(stack, a.port, token, enable_agent=not a.no_agent, open_panel=panel,
                               agent_library=Path(a.agentcore_lib) if a.agentcore_lib else None))
    except KeyboardInterrupt:
        pass
    return 0


def _daemon_alive(info: dict) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{info['port']}/health", timeout=1) as r:
            return r.status == 200
    except OSError:
        return False


def _wait_daemon(seconds: float):
    from .server import read_daemon_file

    deadline = time.time() + seconds
    while time.time() < deadline:
        info = read_daemon_file()
        if info and _daemon_alive(info):
            return info
        time.sleep(0.3)
    return None


# -- mcp -----------------------------------------------------------------------

def cmd_mcp(a) -> int:
    from .mcp import McpHandler, bridge_stdio_to_http, serve_stdio

    session = a.session or f"mcp-{os.getppid()}"
    layers = set(a.layers.split(",")) if a.layers else None
    if a.standalone:
        from .stack import build_stack

        stack = build_stack(_launch_options(a), site_dirs=a.site_dir)

        async def main():
            await stack.runtime.start()
            try:
                await serve_stdio(McpHandler(stack.registry, layers), session)
            finally:
                await stack.runtime.stop()

        asyncio.run(main())
        return 0
    from .server import read_daemon_file

    info = read_daemon_file()
    if not (info and _daemon_alive(info)):
        if a.no_autostart:
            print("metabrowser daemon not running", file=sys.stderr)
            return 1
        log = (paths.ensure(paths.home() / "logs") / "daemon.log").open("ab")
        browser_args = ["--profile", a.profile, "--engine", a.engine]
        if a.browser_path:
            browser_args.extend(["--browser-path", a.browser_path])
        if a.headless:
            browser_args.append("--headless")
        if a.no_humanize:
            browser_args.append("--no-humanize")
        if a.proxy:
            browser_args.extend(["--proxy", a.proxy])
        browser_args.extend(f"--browser-arg={flag}" for flag in a.browser_arg)
        for directory in a.site_dir:
            browser_args.extend(["--site-dir", str(directory)])
        subprocess.Popen([sys.executable, "-m", "metabrowser", "serve", *browser_args],
                         stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True)
        info = _wait_daemon(60)
        if not info:
            print(f"failed to start metabrowser daemon; see {log.name}", file=sys.stderr)
            return 1
    asyncio.run(bridge_stdio_to_http(f"http://127.0.0.1:{info['port']}/mcp", info["token"], session))
    return 0


# -- agent ---------------------------------------------------------------------

def cmd_browser(a) -> int:
    from .engine import install_browser, manifest, resolve_binary

    try:
        binary = install_browser(a.archive) if a.browser_cmd == "install" else resolve_binary(a.engine, a.browser_path)
        print(json.dumps({"engine": a.engine, "executable": str(binary) if binary else None,
                          "managed_version": manifest()["version"]}, indent=2))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as e:
        print(f"metabrowser: {e}", file=sys.stderr)
        return 1

def cmd_agent_build_core(a) -> int:
    from .agent import build_core, find_metacodes_src

    src = Path(a.metacodes_src) if a.metacodes_src else find_metacodes_src()
    if src is None:
        print("pass --metacodes-src <metacodes checkout> (or set METACODES_SRC)", file=sys.stderr)
        return 2
    build_core(src, optimize=a.optimize)
    return 0


def cmd_agent_status(a) -> int:
    from .agentcore import AgentConfig, AgentCoreUnavailable
    from .agentcore import abi

    try:
        lib, api = abi.load()
        print(f"AgentCore: ok (ABI {api.abi_version}.{api.abi_revision}) {lib._name}")
        ok = True
    except AgentCoreUnavailable as e:
        print(f"AgentCore: missing — {e}")
        ok = False
    cfg = AgentConfig.load()
    for k, v in cfg.public().items():
        print(f"  {k:<16} {v}")
    if not cfg.api_key:
        print("  -> run `metacodes login` (metask), or set METABROWSER_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY; "
              "model/provider/base_url go in ~/.metabrowser/config.json {\"agent\": {...}}")
    from .server import read_daemon_file

    info = read_daemon_file()
    print(f"daemon: {'running on port ' + str(info['port']) if info and _daemon_alive(info) else 'not running'}")
    return 0 if ok and cfg.api_key else 1


def cmd_agent_register_mcp(a) -> int:
    from .agent import plan_mcp_registration, write_mcp_registration

    path, old, new = plan_mcp_registration()
    if old == new:
        print(f"{path} already registers the `browser` MCP server")
        return 0
    print(f"will update {path}: mcp_servers += {json.dumps(new['mcp_servers'][-1], ensure_ascii=False)}")
    if not a.yes:
        if not sys.stdin.isatty() or input("apply? [y/N] ").strip().lower() != "y":
            print("skipped (re-run with --yes to apply)")
            return 1
    backup = write_mcp_registration(path, new)
    print(f"updated {path}" + (f" (backup: {backup})" if backup else ""))
    return 0


# -- tools / site / trace -----------------------------------------------------------

def cmd_tools(a) -> int:
    from .stack import build_stack

    reg = build_stack(site_dirs=a.site_dir, record=False).registry
    if a.json:
        print(json.dumps([{**s.describe(), "layer": s.layer, "risk": s.risk.label} for s in reg.list()],
                         ensure_ascii=False, indent=1))
    else:
        for s in reg.list():
            print(f"{s.layer}  {s.risk.label:<12} {s.wire_name:<40} {s.description[:70]}")
    return 0


def cmd_site(a) -> int:
    from .sites import discover, load_pack

    if a.site_cmd == "list":
        for d in discover(a.site_dir):
            p = load_pack(d)
            print(f"{p.id:<20} {p.name:<30} caps={','.join(p.capabilities)}  {d}")
        return 0
    if a.site_cmd == "validate":
        p = load_pack(Path(a.path))
        print(f"ok: {p.id} — {len(p.capabilities)} capabilities, {len(p.skill_dirs)} skills, "
              f"{len(p.meta.get('risks', []))} risks")
        return 0
    if a.site_cmd == "install":
        p = load_pack(Path(a.path))
        dst = paths.ensure(paths.sites_dir()) / Path(a.path).resolve().name
        if dst.exists() or dst.is_symlink():
            if dst.is_symlink():
                dst.unlink()
            else:
                shutil.rmtree(dst)
        if a.copy:
            shutil.copytree(Path(a.path).resolve(), dst)
        else:
            dst.symlink_to(Path(a.path).resolve(), target_is_directory=True)
        print(f"installed {p.id} -> {dst}. Restart MetaBrowser to load its tools and skills.")
        return 0
    pack = _find_pack(a.site, a.site_dir)
    from .kg import TinyKG, plan_for

    plan = plan_for(pack)
    if a.site_cmd == "kg-export":
        out = json.dumps(plan.to_json(), ensure_ascii=False, indent=1)
        (Path(a.out).write_text(out) if a.out else print(out))
        return 0
    if a.site_cmd == "kg-sync":
        store = Path(a.store or os.environ.get("METACODES_KG_STORE") or paths.home() / "kg" / "sites")
        paths.ensure(store.parent)
        stats = TinyKG(store, a.kg_bin).apply(plan)
        print(f"{pack.id} -> {store}: {stats}")
        return 0
    return 2


def _find_pack(site_id: str, extra):
    from .sites import discover, load_pack

    for d in discover(extra):
        p = load_pack(d)
        if p.id == site_id:
            return p
    raise SystemExit(f"unknown site pack {site_id!r}")


def cmd_trace(a) -> int:
    from .trace import read_events, verify

    if a.trace_cmd == "list":
        for f in sorted(paths.traces_dir().glob("*.ndjson")) if paths.traces_dir().is_dir() else []:
            print(f"{f.name}  {f.stat().st_size:>9} bytes")
        return 0
    path = Path(a.file) if Path(a.file).exists() else paths.traces_dir() / a.file
    if a.trace_cmd == "verify":
        ok, msg = verify(path)
        print(msg)
        return 0 if ok else 1
    for ev in read_events(path):
        if a.session and ev.get("session") != a.session:
            continue
        if ev.get("type") == "tool_call":
            flag = "✓" if ev.get("ok") else "✗"
            dec = (ev.get("decision") or {}).get("source", "")
            print(f"{ev['seq']:>5} {flag} {ev.get('session', ''):<14} {ev['tool']:<28} risk={ev.get('risk'):<12} "
                  f"{dec:<14} {ev.get('duration_ms', 0):>6}ms {ev.get('url_after') or ''}")
        else:
            print(f"{ev['seq']:>5} · {ev.get('type')} {json.dumps({k: v for k, v in ev.items() if k not in ('seq', 'ts', 'prev', 'hash', 'type')}, ensure_ascii=False)[:120]}")
    return 0


def cmd_record(a) -> int:
    from .recorder import list_recordings

    for r in list_recordings():
        print(f"{r['id']}  steps={r['steps']:<3} site={r['site'] or '-':<14} {r['start_url']}  {r['intent'][:60]}")
    return 0


def cmd_eval(a) -> int:
    from .evals import runner

    if a.eval_cmd == "run":
        cfg = runner.RunConfig(out=Path(a.out), suite=a.suite, tasks=a.tasks.split(",") if a.tasks else None,
                               repeat=a.repeat, label=a.label or a.model or "", engine=a.engine,
                               headless=not a.headed, chromium_path=a.chromium,
                               agent_overrides={k: v for k, v in (("model", a.model), ("provider", a.provider),
                                                                  ("base_url", a.base_url)) if v})
        summary = asyncio.run(runner.run_suite(cfg))
        print(runner.render_report(summary))
        print(f"results: {cfg.out}")
        return 0 if summary["pass_rate"] > 0 else 1
    if a.eval_cmd == "report":
        summary = json.loads((Path(a.dir) / "summary.json").read_text())
        print(runner.render_report(summary))
        return 0
    if a.eval_cmd == "compare":
        base = json.loads((Path(a.a) / "summary.json").read_text())
        cand = json.loads((Path(a.b) / "summary.json").read_text())
        print(runner.compare(base, cand))
        return 0
    if a.eval_cmd == "serve":
        from .evals.envs import EnvServer

        async def serve():
            env = EnvServer(a.port)
            url = await env.start()
            print(f"fixture sites on {url}: /shop/  /admin/ (login: /login)  /ads/ (login: /ads/login)  /erp  /widgets")
            print(f"site packs: export METABROWSER_SITE_EXAMPLE_SHOP_URL={url}")
            await asyncio.Event().wait()

        try:
            asyncio.run(serve())
        except KeyboardInterrupt:
            pass
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="metabrowser", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("serve", help="run MetaBrowser (browser + side panel + embedded agent)")
    _add_browser_args(p)
    p.add_argument("--port", type=int, default=int(os.environ.get("METABROWSER_PORT", 8765)))
    p.add_argument("--no-agent", action="store_true", help="do not start the embedded metacodes agent")
    p.add_argument("--no-panel", action="store_true", help="do not load/open the side panel")
    p.add_argument("--agentcore-lib", help="path to the AgentCore shared library")
    p.add_argument("--detach", action="store_true")
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("mcp", help="stdio MCP server")
    _add_browser_args(p)
    p.add_argument("--standalone", action="store_true", help="in-process browser instead of the shared daemon")
    p.add_argument("--session", help="session id for tab leases and traces")
    p.add_argument("--layers", help="comma list, e.g. L2,L3 to hide primitives")
    p.add_argument("--no-autostart", action="store_true")
    p.set_defaults(fn=cmd_mcp)

    p = sub.add_parser("browser", help="install/check the open browser engine (no subscription)")
    bsub = p.add_subparsers(dest="browser_cmd", required=True)
    s = bsub.add_parser("install", help="install a digest-pinned official macOS build")
    s.add_argument("--archive", type=Path, help="use an already downloaded DMG (SHA-256 is still checked)")
    s.set_defaults(fn=cmd_browser, engine="ungoogled", browser_path=None)
    s = bsub.add_parser("status")
    s.add_argument("--engine", default="ungoogled", choices=["ungoogled", "chromium"])
    s.add_argument("--browser-path")
    s.set_defaults(fn=cmd_browser)

    p = sub.add_parser("agent", help="embedded metacodes agent")
    asub = p.add_subparsers(dest="agent_cmd", required=True)
    s = asub.add_parser("build-core", help="build + install the AgentCore shared library")
    s.add_argument("--metacodes-src")
    s.add_argument("--optimize", default="ReleaseSafe")
    s.set_defaults(fn=cmd_agent_build_core)
    s = asub.add_parser("status")
    s.set_defaults(fn=cmd_agent_status)
    s = asub.add_parser("register-mcp", help="add the `browser` MCP server to ~/.metacodes/config.json")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_agent_register_mcp)

    p = sub.add_parser("tools", help="list tools")
    p.add_argument("--json", action="store_true")
    p.add_argument("--site-dir", action="append", type=Path, default=[])
    p.set_defaults(fn=cmd_tools)

    p = sub.add_parser("site", help="site packs")
    p.add_argument("--site-dir", action="append", type=Path, default=[])
    ssub = p.add_subparsers(dest="site_cmd", required=True)
    ssub.add_parser("list")
    s = ssub.add_parser("validate")
    s.add_argument("path")
    s = ssub.add_parser("install")
    s.add_argument("path")
    s.add_argument("--copy", action="store_true")
    s = ssub.add_parser("kg-export")
    s.add_argument("site")
    s.add_argument("--out")
    s = ssub.add_parser("kg-sync")
    s.add_argument("site")
    s.add_argument("--store")
    s.add_argument("--kg-bin")
    p.set_defaults(fn=cmd_site)

    p = sub.add_parser("trace", help="trajectories")
    tsub = p.add_subparsers(dest="trace_cmd", required=True)
    tsub.add_parser("list")
    s = tsub.add_parser("show")
    s.add_argument("file")
    s.add_argument("--session")
    s = tsub.add_parser("verify")
    s.add_argument("file")
    p.set_defaults(fn=cmd_trace)

    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-") and argv[0] not in ("-h", "--help"):
        argv = ["serve", *argv]  # bare `metabrowser` = start the product
    p = sub.add_parser("record", help="recorded demonstrations")
    p.add_argument("record_cmd", nargs="?", default="list", choices=["list"])
    p.set_defaults(fn=cmd_record)

    p = sub.add_parser("eval", help="evaluate the agent")
    esub = p.add_subparsers(dest="eval_cmd", required=True)
    s = esub.add_parser("run")
    s.add_argument("--suite", default="core")
    s.add_argument("--tasks", help="comma-separated task ids")
    s.add_argument("--repeat", type=int, default=1)
    s.add_argument("--out", default=str(paths.home() / "evals" / time.strftime("%Y%m%d-%H%M%S")))
    s.add_argument("--label")
    s.add_argument("--model")
    s.add_argument("--provider")
    s.add_argument("--base-url")
    s.add_argument("--engine", default="ungoogled", choices=["ungoogled", "chromium", "auto"],
                   help="auto is a compatibility alias for ungoogled; never chooses CloakBrowser")
    s.add_argument("--browser-path", "--chromium", dest="chromium", help="browser executable (legacy alias: --chromium)")
    s.add_argument("--headed", action="store_true")
    s = esub.add_parser("report")
    s.add_argument("dir")
    s = esub.add_parser("compare")
    s.add_argument("a")
    s.add_argument("b")
    s = esub.add_parser("serve")
    s.add_argument("--port", type=int, default=8899)
    p.set_defaults(fn=cmd_eval)

    a = ap.parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
