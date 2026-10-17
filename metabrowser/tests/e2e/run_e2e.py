"""End-to-end acceptance run of the real product (not collected by pytest).

    python metabrowser/tests/e2e/run_e2e.py [--out DIR] [--real-llm]

What runs for real:
  * `python -m metabrowser serve` — the actual daemon, headed ungoogled-chromium binary
    (managed build, or METABROWSER_BROWSER_PATH), native side panel opened at startup
  * the embedded metacodes AgentCore (METABROWSER_AGENTCORE_LIB / ~/.metabrowser/agentcore)
  * the side panel UI, driven like a user over CDP: new session, type a task, click approvals
What is simulated:
  * the merchant back-office (local fixture site)
  * the LLM, unless --real-llm (then the provider/key from the environment are used)

Scenario: "summarise orders into a report, then try to refund" —
  L3 site recipe -> AgentCore permission prompt (Bash, approved in the panel) -> Write report to
  outputs -> L1 navigate -> irreversible click escalated by the site risk map -> denied in the panel.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from conftest import make_app  # noqa: E402
from mock_llm import MockLLM, last_tool_result, scripted, tool_result_containing  # noqa: E402

from aiohttp import web  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def script_for(outputs: Path, shop: str):
    report = outputs / "orders-report.md"

    def write_report(body):
        rows = tool_result_containing(body, "A1000")
        return [{"text": "已拿到订单，写报告。"},
                {"tool_use": {"name": "Write", "input": {"file_path": str(report),
                                                         "content": "# 订单报告\n\n" + rows[:4000] + "\n"}}}]

    def click_refund(body):
        snap = last_tool_result(body)
        ref = next(l.split("]")[0][1:] for l in snap.splitlines() if "Refund selected" in l)
        return [{"tool_use": {"name": "page_click", "input": {"ref": ref}}}]

    turns = [
        [{"text": "先用站点能力查询订单。"},
         {"tool_use": {"name": "site_example_shop_orders_list", "input": {"query": ""}}}],
        [{"tool_use": {"name": "Bash", "input": {"command": f"mkdir -p {outputs} && echo ready",
                                                 "description": "prepare outputs folder"}}}],
        write_report,
        [{"tool_use": {"name": "page_navigate", "input": {"url": shop + "/admin/orders/"}}}],
        click_refund,
        lambda body: [{"text": "报告已保存到 " + str(report) + "。退款操作被用户拒绝：" +
                       ("[denied]" if "[denied]" in last_tool_result(body) else last_tool_result(body)[:120])}],
    ]
    # forge session (after the operator scenario): read the recording, draft a generalized skill with
    # discriminating tests, verify it live, ask to promote (approved in the panel)
    def read_recording(body):
        rid = re.search(r"id=([0-9A-Za-z-]+)", json.dumps(body["messages"][0], ensure_ascii=False)).group(1)
        return [{"tool_use": {"name": "recording_get", "input": {"id": rid}}}]

    cap = {"name": "orders_search", "description": "按客户名或订单号搜索订单，返回匹配行", "risk": "read",
           "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
           "steps": [{"do": "goto", "url": "{base_url}/admin/orders/"},
                     {"do": "fill", "target": [{"role": "searchbox", "name": "search"}, {"css": "input[name=q]"}], "value": "{query}"},
                     {"do": "press", "key": "Enter", "target": [{"css": "input[name=q]"}]},
                     {"do": "wait", "selector": "table.orders"},
                     {"do": "extract_table", "selector": "table.orders", "as": "rows"}],
           "returns": "rows",
           "tests": [{"args": {"query": "chen"}, "expect": {"min_rows": 1, "all_rows_match": {"Customer": "(?i)chen"}}},
                     {"args": {"query": "li"}, "expect": {"min_rows": 3, "all_rows_match": {"Customer": "(?i)li"}}}]}
    turns += [
        read_recording,
        [{"tool_use": {"name": "skill_draft_save", "input": {"site": "example_shop", "capability": cap}}}],
        [{"tool_use": {"name": "skill_draft_test", "input": {"site": "example_shop", "name": "orders_search"}}}],
        [{"tool_use": {"name": "skill_promote", "input": {"site": "example_shop", "name": "orders_search"}}}],
        lambda body: [{"text": "skill orders_search: " + last_tool_result(body)[:160]}],
    ]
    return scripted(turns), report


async def poll(check, timeout=10.0, what="condition"):
    """Python-side polling: the extension page's CSP forbids wait_for_function's string eval."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if await check():
            return True
        await asyncio.sleep(0.15)
    raise TimeoutError(f"timed out waiting for {what}")


async def answer_cards(panel, decisions, until_done_timeout=240):
    """Click approvals like a user: deny irreversible page clicks, allow everything else."""
    deadline = time.time() + until_done_timeout
    while time.time() < deadline:
        for c in await panel.query_selector_all(".approval"):
            # textContent, not innerText: the card title is CSS-uppercased
            title = await c.eval_on_selector(".risk", "e => e.textContent")
            if "page.click" in title:
                await (await c.query_selector("button:text('Deny')")).click()
                decisions.append(("browser", title, "deny"))
            else:
                await (await c.query_selector("button:text('Allow once')")).click()
                decisions.append(("browser" if "·" in title and title.split("·")[0].strip() in
                                  ("submit", "irreversible", "system") else "agentcore", title, "allow_once"))
            await asyncio.sleep(0.3)
        if await panel.query_selector_all(".msg.done"):
            return True
        await asyncio.sleep(0.3)
    return False


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--real-llm", action="store_true")
    ap.add_argument("--keep-open", type=float, default=0, help="seconds to leave the browser open at the end")
    ap.add_argument("--browser-path", help="override the installed ungoogled-chromium executable")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    home = out / "home"
    outputs = out / "outputs"
    results: dict = {"checks": {}}

    def check(name, ok, detail=""):
        results["checks"][name] = {"ok": bool(ok), "detail": detail}
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail}")

    shop_runner = web.AppRunner(make_app())
    await shop_runner.setup()
    shop_port = free_port()
    await web.TCPSite(shop_runner, "127.0.0.1", shop_port).start()
    shop = f"http://127.0.0.1:{shop_port}"

    script, report = script_for(outputs, shop)
    llm = MockLLM(script)
    llm_url = await llm.start()

    port, cdp_port = free_port(), free_port()
    env = {**os.environ, "METABROWSER_HOME": str(home), "METABROWSER_OUTPUTS": str(outputs),
           "METABROWSER_WORKSPACE": str(out / "workspace"), "METABROWSER_SITE_EXAMPLE_SHOP_URL": shop}
    # Resolve before changing METABROWSER_HOME to the isolated test home.
    from metabrowser.engine import resolve_binary

    env["METABROWSER_BROWSER_PATH"] = resolve_binary("ungoogled", a.browser_path)
    env["METABROWSER_COMPUTER_ACCESS"] = "1"  # the scenario exercises an AgentCore Bash permission prompt
    if not a.real_llm:
        env.update(METABROWSER_AGENT_BASE_URL=llm_url, METABROWSER_API_KEY="mock-key")
    lib = os.environ.get("METABROWSER_AGENTCORE_LIB") or str(Path.home() / ".metabrowser/agentcore/lib/libmetask_agentcore.dylib")
    env["METABROWSER_AGENTCORE_LIB"] = lib
    log = (out / "daemon.log").open("wb")
    daemon = subprocess.Popen([sys.executable, "-m", "metabrowser", "serve", "--port", str(port), "--profile", "e2e",
                               f"--browser-arg=--remote-debugging-port={cdp_port}"],
                              env=env, stdout=log, stderr=subprocess.STDOUT)
    t0 = time.time()
    try:
        info = None
        for _ in range(240):
            try:
                info = json.loads((home / "daemon.json").read_text())
                break
            except (OSError, json.JSONDecodeError):
                if daemon.poll() is not None:
                    raise RuntimeError(f"daemon exited {daemon.returncode}; see {out / 'daemon.log'}")
                await asyncio.sleep(0.25)
        check("daemon starts (browser + agent + panel)", info is not None, f"{time.time() - t0:.1f}s")

        import urllib.request

        def get(path):
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                         headers={"Authorization": f"Bearer {info['token']}"})
            return json.loads(urllib.request.urlopen(req, timeout=10).read())

        status = get("/api/agent/status")
        check("embedded AgentCore runtime up", status["enabled"], json.dumps(status.get("config", {}), ensure_ascii=False))
        check("site skills in AgentCore catalog", "example-shop-orders" in (status.get("skills") or []),
              str(status.get("skills")))

        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
            ctx = browser.contexts[0]
            ua = await ctx.pages[0].evaluate("navigator.userAgent") if ctx.pages else ""
            version = browser.version
            check("selected ungoogled-chromium binary", True, f"Chromium {version}; {env['METABROWSER_BROWSER_PATH']}")
            panel = None
            for _ in range(40):
                panel = next((pg for pg in ctx.pages if pg.url.endswith("/sidepanel.html")), None)
                if panel:
                    break
                await asyncio.sleep(0.25)
            check("native side panel opened at startup", panel is not None, panel.url if panel else "")
            webdriver = await ctx.pages[0].evaluate("navigator.webdriver")
            check("webdriver flag absent with extension loaded", webdriver is False, f"webdriver={webdriver} UA={ua[:60]}")

            await ctx.add_cookies([{"name": "session", "value": "ok", "domain": "127.0.0.1", "path": "/"}])
            await panel.wait_for_selector("#status:text('connected')", timeout=15000)
            await panel.wait_for_function("document.querySelectorAll('#sessions button').length >= 1", timeout=15000)
            first = await panel.eval_on_selector("#sessions button[aria-selected=true]", "e => e.textContent")
            await panel.click("#new-session")  # second session: multi-session UI
            await panel.wait_for_function(
                "f => { const b = document.querySelector('#sessions button[aria-selected=true]');"
                " return b && b.textContent !== f && document.querySelectorAll('#sessions button').length === 2; }",
                arg=first, timeout=15000)
            await panel.fill("#input", "汇总 Example Shop 的订单写成报告，然后把选中的订单退款")
            await panel.press("#input", "Enter")

            decisions = []
            await answer_cards(panel, decisions)
            await asyncio.sleep(0.5)
            log_text = await panel.inner_text("#log")
            await panel.screenshot(path=str(out / "side-panel.png"))
            check("AgentCore permission prompt answered in panel", any(d[0] == "agentcore" and "Bash" in d[1] for d in decisions),
                  str(decisions))
            check("irreversible browser action escalated + denied in panel",
                  any(d[0] == "browser" and "irreversible" in d[1] for d in decisions))
            check("run finished, final answer streamed to panel", "退款操作被用户拒绝：[denied]" in log_text,
                  log_text.strip().splitlines()[-1] if log_text.strip() else "")
            check("report written to outputs by agent", report.exists() and "A1000" in report.read_text(),
                  str(report))
            sessions = get("/api/agent/sessions")
            check("multiple agent sessions", len(sessions) >= 2, str([s["label"] for s in sessions]))

            # --- the user records a demonstration, says what it is, and asks for a skill ---------
            demo = await ctx.new_page()
            await demo.goto(shop + "/admin/orders/")
            await demo.bring_to_front()
            await panel.click("#record")
            await poll(lambda: panel.eval_on_selector("#record", "e => e.classList.contains('on')"), what="recording on")
            await demo.fill("input[name=q]", "chen")
            await demo.press("input[name=q]", "Enter")
            await demo.wait_for_url("**q=chen**")
            async def stepped():
                return " 0 步" not in (await panel.text_content("#record") or " 0 步")
            await poll(stepped, what="live step count")
            live = await panel.text_content("#record")
            await panel.click("#record")
            await panel.wait_for_selector("#record-card:not([hidden])", timeout=10000)
            suggested = await panel.input_value("#rec-site")
            check("recording streamed live to the panel and stopped", "步" in live, f"{live!r}, site suggested {suggested!r}")
            check("site recognized from the recorded tab", suggested == "example_shop", suggested)
            await panel.fill("#rec-intent", "按客户名搜索订单，拿到匹配的订单列表")
            await panel.fill("#rec-name", "orders_search")
            await panel.click("#rec-forge")

            async def forge_selected():
                label = await panel.eval_on_selector("#sessions button[aria-selected=true]", "e => e.textContent")
                return label.startswith("Forge")
            await poll(forge_selected, timeout=20, what="forge session selected")
            forge_decisions: list = []
            forged = await answer_cards(panel, forge_decisions, 240)
            forge_log = await panel.inner_text("#log")
            await panel.screenshot(path=str(out / "side-panel-forge.png"))
            recs = get("/api/recordings")
            check("recording saved with the user's intent", recs and recs[0]["intent"].startswith("按客户名搜索订单"),
                  f"{recs[0]['steps'] if recs else 0} steps")
            check("forge session verified the draft live (2/2)", forged and "2/2 pass" in json.dumps(
                [l for l in (home / "traces").glob("*.ndjson")][-1].read_text()), forge_log.strip().splitlines()[-1][:160])
            check("skill promotion approved by the user in the panel",
                  any("skill.promote" in d[1] and d[2] == "allow_once" for d in forge_decisions), str(forge_decisions))
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/call", method="POST",
                                         data=json.dumps({"tool": "site.run", "args": {
                                             "site": "example_shop", "capability": "orders_search",
                                             "args": {"query": "zhang"}}}).encode(),
                                         headers={"Authorization": f"Bearer {info['token']}", "Content-Type": "application/json"})
            # in a worker thread: a blocking call here would freeze this harness's own CDP client, which
            # auto-attaches new tabs paused-on-start and must keep serving them
            run = json.loads(await asyncio.get_running_loop().run_in_executor(
                None, lambda: urllib.request.urlopen(req, timeout=90).read()))
            check("forged skill generalizes to a new argument (zhang -> Carol Zhang only)",
                  run.get("ok") and "Carol Zhang" in run.get("text", "") and "Dan Chen" not in run.get("text", ""),
                  run.get("text", str(run))[:120])
            await browser.close()  # disconnect CDP client only

        try:
            subprocess.run(["screencapture", "-x", str(out / "screen.png")], timeout=10, check=True)
            results["screen"] = str(out / "screen.png")
        except Exception as e:
            results["screen"] = f"unavailable: {e}"

        trace_file = sorted((home / "traces").glob("*.ndjson"))[-1]
        ver = subprocess.run([sys.executable, "-m", "metabrowser", "trace", "verify", str(trace_file)],
                             capture_output=True, text=True, env=env)
        check("trace hash chain verifies", ver.returncode == 0, ver.stdout.strip())
        events = [json.loads(l) for l in trace_file.read_text().splitlines()]
        calls = [e for e in events if e.get("type") == "tool_call"]
        recipe = [c for c in calls if c["tool"] == "site.example_shop.orders_list"]
        check("L3 site recipe succeeded (humanized, real binary)", recipe and recipe[0]["ok"],
              recipe[0].get("result", "")[:80] if recipe else "not called")
        check("agent browser calls audited", {"site.example_shop.orders_list", "page.navigate", "page.click"}
              <= {c["tool"] for c in calls}, f"{len(calls)} tool calls")
        check("LLM saw browser tools as native host tools",
              "site_example_shop_orders_list" in [t["name"] for t in llm.requests[0].get("tools", [])])
        if a.keep_open:
            await asyncio.sleep(a.keep_open)
    finally:
        daemon.send_signal(signal.SIGINT)
        try:
            daemon.wait(20)
        except subprocess.TimeoutExpired:
            daemon.kill()
        await llm.stop()
        await shop_runner.cleanup()
    ok = all(c["ok"] for c in results["checks"].values())
    results["ok"] = ok
    (out / "result.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    print(("ALL PASS" if ok else "FAILURES") + f" — {out / 'result.json'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
