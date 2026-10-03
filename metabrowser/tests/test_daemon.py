import asyncio
import json
import subprocess
import sys

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from conftest import login
from metabrowser.server import Daemon

TOKEN = "t0ken"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


async def _client(stack):
    daemon = Daemon(stack, TOKEN)
    client = TestClient(TestServer(daemon.app()))
    await client.start_server()
    return daemon, client


async def test_auth_and_origin_guard(stack):
    _, c = await _client(stack)
    try:
        assert (await c.get("/health")).status == 200
        assert (await c.get("/api/tools")).status == 401
        r = await c.get("/api/tools", headers={**AUTH, "Origin": "https://evil.example"})
        assert r.status == 403  # pages inside the same browser cannot drive the daemon
        r = await c.get("/api/tools", headers={**AUTH, "Origin": "chrome-extension://abc"})
        assert r.status == 200 and any(t["name"] == "page_snapshot" for t in await r.json())
    finally:
        await c.close()


async def test_mcp_over_http(stack, shop):
    _, c = await _client(stack)
    try:
        r = await c.post("/mcp", headers=AUTH, json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                                     "params": {"protocolVersion": "2025-06-18"}})
        sid = r.headers["Mcp-Session-Id"]
        assert (await r.json())["result"]["serverInfo"]["name"] == "metabrowser"
        r = await c.post("/mcp", headers={**AUTH, "Mcp-Session-Id": sid},
                         json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert r.status == 202
        r = await c.post("/mcp", headers={**AUTH, "Mcp-Session-Id": sid}, json=[
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "page_navigate", "arguments": {"url": shop + "/login", "snapshot": False}}},
        ])
        body = await r.json()
        assert isinstance(body, list) and body[0]["result"]["isError"] is False
    finally:
        await c.close()


async def test_side_panel_approval_flow(stack, shop):
    daemon, c = await _client(stack)
    await login(stack.runtime.context, shop)
    try:
        events = await c.get(f"/api/events?token={TOKEN}")
        await asyncio.sleep(0.05)
        nav = await stack.registry.call("page.navigate", {"url": shop + "/admin/orders/"}, session_id="agent")
        ref = next(line.split("]")[0][1:] for line in nav.text.splitlines() if "Refund selected" in line)
        click = asyncio.create_task(stack.registry.call("page.click", {"ref": ref}, session_id="agent"))

        approval = None
        while approval is None:
            line = (await events.content.readline()).decode()
            if line.startswith("data:"):
                msg = json.loads(line[5:])
                if msg["kind"] == "approval":
                    approval = msg
        assert approval["request"]["risk"] == "irreversible"
        r = await c.post(f"/api/approvals/{approval['id']}", headers=AUTH, json={"answer": "deny"})
        assert r.status == 200
        try:
            await click
            raise AssertionError("expected denial")
        except Exception as e:
            assert getattr(e, "code", None) == "denied"
        events.close()
    finally:
        await c.close()


async def test_stdio_bridge_end_to_end(stack, shop):
    daemon = Daemon(stack, TOKEN)
    runner = web.AppRunner(daemon.app())
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    code = ("import asyncio,sys; from metabrowser.mcp import bridge_stdio_to_http as b; "
            f"asyncio.run(b('http://127.0.0.1:{port}/mcp', '{TOKEN}', 'bridge-test'))")
    proc = await asyncio.create_subprocess_exec(sys.executable, "-c", code, stdin=subprocess.PIPE,
                                                stdout=subprocess.PIPE)
    try:
        reqs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2026-07-28"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "tabs_open", "arguments": {"url": shop + "/login"}}},
        ]
        out = {}
        for req in reqs:
            proc.stdin.write((json.dumps(req) + "\n").encode())
            await proc.stdin.drain()
            if "id" in req:
                resp = json.loads(await asyncio.wait_for(proc.stdout.readline(), 20))
                out[resp["id"]] = resp
        assert out[1]["result"]["protocolVersion"] == "2026-07-28"
        assert "opened" in out[2]["result"]["content"][0]["text"]
        assert any(t.owner == "bridge-test" for t in stack.runtime.tabs.values())
    finally:
        proc.stdin.close()
        await proc.wait()
        await runner.cleanup()
