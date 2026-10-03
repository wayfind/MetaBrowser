"""Embedded metacodes AgentCore driving the browser through the same ToolRegistry.

Requires the AgentCore shared library (`metabrowser agent build-core`), located via
METABROWSER_AGENTCORE_LIB or ~/.metabrowser/agentcore/lib. Uses a scripted mock LLM, so
no credentials are needed; everything else (ABI, agent loop, host tools, permission
callbacks, Playwright) is real.
"""

import asyncio
import json
import os
from pathlib import Path

import pytest

from conftest import SITES, login
from mock_llm import MockLLM, last_tool_result, scripted, tool_names

abi = pytest.importorskip("metabrowser.agentcore.abi")


def _lib():
    for c in abi.library_candidates():
        if c.is_file():
            return c
    real_home = Path.home() / ".metabrowser" / "agentcore" / "lib" / "libmetask_agentcore.dylib"
    return real_home if real_home.is_file() else None


LIB = _lib()
pytestmark = pytest.mark.skipif(LIB is None, reason="AgentCore library not built")


async def _wait_idle(host, sid, timeout=60):
    for _ in range(int(timeout * 20)):
        if not host.sessions[sid].running:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("run did not finish")


def _events(host, sid):
    return [e for _, e in host.events_since(sid)]


@pytest.fixture
async def agent(stack, shop, tmp_path):
    from metabrowser.agentcore import AgentConfig, AgentHost

    llm_holder = {}

    async def make(turns, ui_handler=None):
        llm = MockLLM(scripted(turns))
        url = await llm.start()
        cfg = AgentConfig(provider="anthropic", model="claude-sonnet-4-6", base_url=url, api_key="test-key",
                          workspace_root=tmp_path / "ws", workspace_home=tmp_path / "agent-home")
        host = AgentHost(stack.registry, asyncio.get_running_loop(), cfg, ui_handler=ui_handler,
                         skill_dirs=[("builtin", Path(__file__).parents[1] / "src/metabrowser/skills"),
                                     ("site.example_shop", SITES / "example-shop" / "skills")],
                         library=LIB)
        host.start()
        llm_holder.update(llm=llm, host=host)
        return host, llm

    yield make
    if "host" in llm_holder:
        await asyncio.get_running_loop().run_in_executor(None, llm_holder["host"].stop)
        await llm_holder["llm"].stop()


async def test_agent_loop_uses_browser_tools(agent, stack, shop):
    await login(stack.runtime.context, shop)
    host, llm = await agent([
        [{"text": "Opening the orders list."},
         {"tool_use": {"name": "site_example_shop_orders_list", "input": {"query": "chen"}}}],
        lambda body: [{"text": "Found: " + ("Dan Chen" if "Dan Chen" in last_tool_result(body) else "nothing")}],
    ])
    sess = host.create_session()
    assert host.send(sess.id, "列出客户名含 chen 的订单") == "started"
    await _wait_idle(host, sess.id)
    evs = _events(host, sess.id)
    done = [e["run_done"] for e in evs if "run_done" in e][-1]
    assert done["status"] == "OK" and done["stop_reason"] == "end_turn" and done["tool_calls"] == 1, done
    text = "".join(e["core_event"].get("text_chunk", "") for e in evs if "core_event" in e)
    assert "Found: Dan Chen" in text
    # browser operating contract injected into the first user turn (no system-prompt slot in the ABI)
    first_user = json.dumps(llm.requests[0]["messages"][0], ensure_ascii=False)
    assert "<metabrowser-context>" in first_user and "auth_ensure_login" in first_user
    # the model saw our browser tools as first-class host tools
    names = tool_names(llm.requests[0])
    assert {"page_snapshot", "data_extract_table", "site_example_shop_orders_list"} <= set(names)
    # the browser action went through the same audited pipeline, attributed to the agent session
    tool_calls = [json.loads(l) for l in stack.trace.path.read_text().splitlines() if '"tool_call"' in l]
    assert any(t["tool"] == "site.example_shop.orders_list" and t["session"] == sess.id for t in tool_calls)


async def test_permission_callback_and_browser_gate(agent, stack, shop):
    await login(stack.runtime.context, shop)
    asked = []

    def ui(sid, request):
        asked.append(request)
        from metabrowser.agentcore import permission_response
        return permission_response(request, "deny_once")

    browser_asked = []

    async def approver(req):
        browser_asked.append(req)
        return "deny"

    stack.gate.approver = approver

    def click_refund(body):
        snap = last_tool_result(body)
        ref = next(l.split("]")[0][1:] for l in snap.splitlines() if "Refund selected" in l)
        return [{"tool_use": {"name": "page_click", "input": {"ref": ref}}}]

    host, llm = await agent([
        [{"tool_use": {"name": "Bash", "input": {"command": "echo hi", "description": "say hi"}}}],
        [{"tool_use": {"name": "page_navigate", "input": {"url": shop + "/admin/orders/"}}}],
        click_refund,
        lambda body: [{"text": "result: " + last_tool_result(body)[:200]}],
    ], ui_handler=ui)
    sess = host.create_session()
    host.send(sess.id, "试试")
    await _wait_idle(host, sess.id)
    # AgentCore asked the host UI about Bash (ask rule) and honoured the denial
    assert asked and asked[0]["type"] == "permission" and asked[0]["tool"]["name"] == "Bash"
    # the browser PolicyGate escalated the refund click to irreversible and the denial reached the model
    assert browser_asked and browser_asked[0].risk == "irreversible"
    assert "[denied]" in last_tool_result(llm.requests[-1])
    provenance = [e["core_event"]["permission_provenance"] for e in _events(host, sess.id)
                  if "core_event" in e and "permission_provenance" in e["core_event"]]
    assert any(p["tool"]["name"] == "Bash" and p["decision"] == "deny" for p in provenance)


async def test_write_inside_outputs_is_preapproved(agent, stack, shop, mb_home):
    outputs = mb_home / "outputs"
    asked = []

    def ui(sid, request):
        asked.append(request["tool"]["name"])
        from metabrowser.agentcore import permission_response
        return permission_response(request, "deny_once")

    host, llm = await agent([
        [{"tool_use": {"name": "Write", "input": {"file_path": str(outputs / "ok.md"), "content": "fine"}}}],
        [{"tool_use": {"name": "Write", "input": {"file_path": str(mb_home / "elsewhere.md"), "content": "no"}}}],
        [{"text": "done"}],
    ], ui_handler=ui)
    sess = host.create_session()
    host.send(sess.id, "write")
    await _wait_idle(host, sess.id)
    assert (outputs / "ok.md").read_text() == "fine"      # allow rule: no prompt
    assert asked == ["Write"]                              # only the write outside outputs asked
    assert not (mb_home / "elsewhere.md").exists()


async def test_file_target_session_grant_rev17(agent, stack, shop, mb_home):
    """Revision 17: one allow_session on a Write covers later writes to the same file only."""
    notes = mb_home / "notes"
    notes.mkdir()
    target, other = notes / "plan.md", notes / "other.md"
    asked = []

    def ui(sid, request):
        asked.append(request)
        from metabrowser.agentcore import permission_response
        return permission_response(request, "allow_session")

    host, llm = await agent([
        [{"tool_use": {"name": "Write", "input": {"file_path": str(target), "content": "v1"}}}],
        [{"tool_use": {"name": "Write", "input": {"file_path": str(target), "content": "v2"}}}],
        [{"tool_use": {"name": "Write", "input": {"file_path": str(other), "content": "x"}}}],
        [{"text": "done"}],
    ], ui_handler=ui)
    sess = host.create_session()
    host.send(sess.id, "write notes")
    await _wait_idle(host, sess.id)
    assert target.read_text() == "v2" and other.read_text() == "x"
    # asked for plan.md once (file grant covers the second write), then again for other.md
    assert [Path(r["candidate"]["target"]).name for r in asked] == ["plan.md", "other.md"]
    assert all(r["candidate"]["scope"] == "file_target" for r in asked)


async def test_parallel_sessions_have_separate_tabs(agent, stack, shop):
    host, llm = await agent([
        [{"tool_use": {"name": "tabs_open", "input": {"url": shop + "/login"}}}],
        [{"text": "ok"}],
        [{"tool_use": {"name": "tabs_open", "input": {"url": shop + "/login"}}}],
        [{"text": "ok"}],
    ])
    a, b = host.create_session(), host.create_session()
    host.send(a.id, "open")
    await _wait_idle(host, a.id)
    host.send(b.id, "open")
    await _wait_idle(host, b.id)
    owners = {t.owner for t in stack.runtime.tabs.values()}
    assert {a.id, b.id} <= owners
