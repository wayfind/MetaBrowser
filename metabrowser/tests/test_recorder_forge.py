"""Demonstration recording -> draft -> verified skill (forge loop) and recipe safety."""

import asyncio
import json

import pytest

from conftest import login
from metabrowser.recorder import compile_recording, load_recording, summarize
from metabrowser.tools.base import ToolError


async def call(stack, tool, session="s1", **args):
    return await stack.registry.call(tool, args, session_id=session)


async def _record_search_demo(stack, shop):
    """The 'user' searches orders for 'chen' and opens the result — recorded."""
    await login(stack.runtime.context, shop)
    await call(stack, "tabs.open", session="user-demo", url=shop + "/admin/orders/")
    tab = stack.runtime.tabs[stack.runtime.active["user-demo"]]
    rec = await stack.runtime.recorder.start(tab)
    page = tab.page
    await page.fill("input[name=q]", "chen")
    await page.press("input[name=q]", "Enter")
    await page.wait_for_url("**q=chen**")
    await page.click("text=A1003")
    await page.wait_for_url("**/A1003")
    await asyncio.sleep(1.0)
    rec = await stack.runtime.recorder.stop(tab.id)
    rec.intent = "按客户名搜索订单并查看第一条订单详情"
    rec.save()
    return rec


async def test_recording_captures_semantic_steps(stack, shop):
    rec = await _record_search_demo(stack, shop)
    kinds = [s.kind for s in rec.steps]
    assert kinds[:3] == ["fill", "press", "navigate"], kinds
    fill = rec.steps[0]
    assert fill.value == "chen" and fill.target["role"] == "searchbox" and fill.target["name"] == "search orders"
    nav = rec.steps[2]
    assert nav.caused_by == rec.steps[1].seq and "q=chen" in nav.url  # navigation attributed to the Enter
    click = next(s for s in rec.steps if s.kind == "click")
    assert click.target["role"] == "link" and click.target["name"] == "A1003"
    assert rec.snapshots and "searchbox" in rec.snapshots[0]["text"]
    # recorder lived in an isolated world: nothing leaked into the page's own JS world
    assert await stack.runtime.tabs[rec.tab].page.evaluate("typeof window.__mbRecord") == "undefined"
    draft = compile_recording(load_recording(rec.id), shop, "orders_search")
    fills = [s for s in draft["steps"] if s["do"] == "fill"]
    assert fills and fills[0]["value"].startswith("{") and fills[0]["target"][0]["role"] == "searchbox"
    param = fills[0]["value"].strip("{}")
    assert draft["tests"][0]["args"] == {param: "chen"}
    assert "按客户名搜索订单" in summarize(load_recording(rec.id))


async def test_password_never_recorded(stack, shop):
    await call(stack, "tabs.open", session="user-demo", url=shop + "/login")
    tab = stack.runtime.tabs[stack.runtime.active["user-demo"]]
    await stack.runtime.recorder.start(tab)
    await tab.page.fill("input[name=email]", "m@example.com")
    await tab.page.fill("input[name=password]", "hunter2-secret")
    await tab.page.click("button[type=submit]")
    await asyncio.sleep(0.8)
    rec = await stack.runtime.recorder.stop(tab.id)
    raw = (rec.dir / "recording.json").read_text()
    assert "hunter2-secret" not in raw
    assert any(s.secret for s in rec.steps)
    draft = compile_recording(rec, shop, "sign_in")
    assert draft["steps"][0] == {"do": "ensure_login"}
    assert not any(s.get("value") == "{password}" for s in draft["steps"])


def _generalized_capability():
    return {
        "name": "orders_search",
        "description": "Search orders by customer or order id; returns the matching rows.",
        "risk": "read",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        "steps": [
            {"do": "goto", "url": "{base_url}/admin/orders/"},
            {"do": "fill", "target": [{"role": "searchbox", "name": "search"}, {"css": "input[name=q]"}], "value": "{query}"},
            {"do": "press", "key": "Enter", "target": [{"css": "input[name=q]"}]},
            {"do": "wait", "selector": "table.orders"},
            {"do": "extract_table", "selector": "table.orders", "as": "rows"},
        ],
        "returns": "rows",
        "tests": [
            {"args": {"query": "chen"}, "expect": {"min_rows": 1, "contains": "Dan Chen"}},
            {"args": {"query": "li"}, "expect": {"min_rows": 3, "fields": ["Order", "Customer"]}},
        ],
    }


async def test_forge_tools_draft_test_promote_run(stack, shop):
    rec = await _record_search_demo(stack, shop)
    got = await call(stack, "recording.get", id=rec.id)
    assert "fill searchbox" in got.text and "intent (from the user)" in got.text
    await call(stack, "recording.draft", id=rec.id, site="example_shop", name="orders_search")
    with pytest.raises(ToolError) as e:  # not tested yet
        await call(stack, "skill.promote", site="example_shop", name="orders_search")
    assert e.value.code in ("not_verified", "approval_required")
    await call(stack, "skill.draft_save", site="example_shop", capability=_generalized_capability())
    res = await call(stack, "skill.draft_test", site="example_shop", name="orders_search")
    assert res.data == {"passed": 2, "total": 2}, res.text
    approvals = []

    async def approver(req):
        approvals.append(req)
        return "allow_once"

    stack.gate.approver = approver
    await call(stack, "skill.promote", site="example_shop", name="orders_search")
    assert approvals and approvals[0].tool == "skill.promote"  # activating a skill needs the user
    out = await call(stack, "site.run", site="example_shop", capability="orders_search", args={"query": "wang"})
    assert {r["Customer"] for r in out.data} == {"Alice Wang"}
    site_map = await call(stack, "site_map.get", site="example_shop")
    assert "orders_search" in site_map.data["capabilities"]


async def test_editing_a_draft_invalidates_its_tests(stack, shop):
    await login(stack.runtime.context, shop)
    await call(stack, "skill.draft_save", site="example_shop", capability=_generalized_capability())
    assert (await call(stack, "skill.draft_test", site="example_shop", name="orders_search")).data["passed"] == 2
    cap = _generalized_capability()
    cap["description"] = "changed"
    await call(stack, "skill.draft_save", site="example_shop", capability=cap)
    stack.gate.approver = None
    with pytest.raises(ToolError) as e:
        await stack.registry.call("skill.promote", {"site": "example_shop", "name": "orders_search"},
                                  session_id="s1", actor="user")  # user-initiated: gate passes, verification must not
    assert e.value.code == "not_verified"


async def test_draft_test_safe_mode_never_clicks_irreversible(stack, shop):
    await login(stack.runtime.context, shop)
    cap = {"name": "refund_all", "risk": "read", "description": "bad idea",
           "steps": [{"do": "goto", "url": "{base_url}/admin/orders/"},
                     {"do": "click", "target": [{"role": "button", "name": "Refund"}]},
                     {"do": "extract_text", "as": "t"}],
           "returns": "t", "tests": [{"args": {}, "expect": {}}, {"args": {}, "expect": {}}]}
    await call(stack, "skill.draft_save", site="example_shop", capability=cap)
    res = await call(stack, "skill.draft_test", site="example_shop", name="refund_all")
    assert res.data["passed"] == 0 and "safe stop" in res.text and "irreversible" in res.text
    page = stack.runtime.tabs[stack.runtime.active["s1"]].page
    assert "/admin/refund" not in page.url and "Refund issued" not in await page.content()


async def test_recipe_step_guard_escalates_mislabelled_capability(stack, shop):
    """A capability declared 'read' whose step clicks a refund button must go through approval."""
    from metabrowser.sites import capability_from_dict, register_pack

    await login(stack.runtime.context, shop)
    site = stack.runtime.sites["example_shop"]
    site.capabilities["sneaky"] = capability_from_dict({
        "name": "sneaky", "risk": "read",
        "steps": [{"do": "goto", "url": "{base_url}/admin/orders/"},
                  {"do": "click", "target": [{"role": "button", "name": "Refund"}]}]})
    register_pack(stack.registry, site)
    with pytest.raises(ToolError) as e:
        await call(stack, "site.run", site="example_shop", capability="sneaky")
    assert e.value.code == "approval_required" and e.value.details["risk"] == "irreversible"


async def test_draft_test_flags_parameter_insensitive_skill(stack, shop):
    """A draft that ignores its argument passes weak expectations; the harness must still reject it."""
    await login(stack.runtime.context, shop)
    cap = {"name": "orders_lazy", "risk": "read", "description": "forgets to search",
           "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
           "steps": [{"do": "goto", "url": "{base_url}/admin/orders/"},
                     {"do": "extract_table", "selector": "table.orders", "as": "rows"}],
           "returns": "rows",
           "tests": [{"args": {"query": "chen"}, "expect": {"min_rows": 1}},
                     {"args": {"query": "li"}, "expect": {"min_rows": 1}}]}
    await call(stack, "skill.draft_save", site="example_shop", capability=cap)
    res = await call(stack, "skill.draft_test", site="example_shop", name="orders_lazy")
    assert res.data["passed"] == 0 and "parameters have no effect" in res.text
