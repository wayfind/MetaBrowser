import json
import os
import shutil
from pathlib import Path

import pytest

from conftest import SITES, login
from metabrowser.kg import TinyKG, plan_for
from metabrowser.mcp import McpHandler
from metabrowser.sites import load_pack
from metabrowser.tools.base import ToolError


async def test_l3_recipe_list_and_detail(stack, shop):
    await login(stack.runtime.context, shop)
    res = await stack.registry.call("site_example_shop_orders_list", {"query": "li"}, session_id="s")
    customers = {r["Customer"] for r in res.data}
    assert customers == {"Alice Wang", "Bob Li", "Eve Liu"}
    det = await stack.registry.call("site.example_shop.order_detail", {"order_id": "A1002"}, session_id="s")
    assert "Carol Zhang" in det.text


async def test_l3_failure_returns_snapshot_for_fallback(stack, shop):
    # not logged in -> the recipe's assert fails, error carries the current page for L1/L2 fallback
    with pytest.raises(ToolError) as e:
        await stack.registry.call("site.example_shop.orders_list", {}, session_id="s")
    assert e.value.code == "recipe_failed"
    assert "Sign in" in e.value.message and "[e" in e.value.message


async def test_ensure_login_detects_logged_out(stack, shop):
    with pytest.raises(ToolError) as e:
        await stack.registry.call("auth.ensure_login", {"site": "example_shop"}, session_id="s")
    assert e.value.code == "login_required"
    await login(stack.runtime.context, shop)
    await stack.registry.call("page.navigate", {"url": shop + "/admin/", "snapshot": False}, session_id="s")
    ok = await stack.registry.call("auth.ensure_login", {"site": "example_shop"}, session_id="s")
    assert ok.data == {"logged_in": True}


async def test_mcp_handshake_list_call(stack, shop):
    h = McpHandler(stack.registry)
    init = await h.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2025-11-25", "capabilities": {}}}, "m")
    assert init["result"]["protocolVersion"] == "2025-11-25"
    assert await h.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, "m") is None
    tools = (await h.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, "m"))["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"page_snapshot", "data_extract_table", "site_example_shop_orders_list"} <= names
    assert all("." not in n for n in names)
    for t in tools:  # metacodes schema subset
        assert t["inputSchema"]["type"] == "object"
    res = await h.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                          "params": {"name": "page_navigate", "arguments": {"url": shop + "/login"}}}, "m")
    assert res["result"]["isError"] is False and "Sign in" in res["result"]["content"][0]["text"]
    err = await h.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                          "params": {"name": "page_evaluate", "arguments": {"expression": "1"}}}, "m")
    assert err["result"]["isError"] is True
    assert json.loads(err["result"]["content"][0]["text"])["error"]["code"] == "denied"


async def test_mcp_screenshot_is_image_content(stack, shop):
    h = McpHandler(stack.registry)
    await stack.registry.call("page.navigate", {"url": shop + "/login", "snapshot": False}, session_id="m")
    res = await h.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "page_screenshot", "arguments": {}}}, "m")
    kinds = [c["type"] for c in res["result"]["content"]]
    assert "image" in kinds


def test_pack_validation_rejects_unknown_step(tmp_path):
    pack = tmp_path / "bad"
    shutil.copytree(SITES / "example-shop", pack)
    cap = pack / "capabilities" / "orders_list.json"
    data = json.loads(cap.read_text())
    data["steps"].append({"do": "rm_rf"})
    cap.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="unknown 'do'"):
        load_pack(pack)


def test_kg_plan_covers_feature_interaction_risk_maps():
    plan = plan_for(load_pack(SITES / "example-shop"))
    kinds = {k for k, _ in plan.nodes}
    assert kinds == {"site", "site_module", "site_page", "ui_action", "data_entity", "site_risk", "capability", "recipe"}
    edges = set(plan.edges)
    assert ("example_shop/action/refund_order", "has_risk", "example_shop/risk/refund_money") in edges
    assert ("example_shop/recipe/orders_list", "implements", "example_shop/capability/orders_list") in edges
    assert ("example_shop/module/orders", "has_page", "example_shop/page/orders_list") in edges


TINYKG = os.environ.get("METACODES_KG_BIN") or shutil.which("tinykg")


@pytest.mark.skipif(not TINYKG, reason="tinykg binary not available (set METACODES_KG_BIN)")
def test_kg_sync_into_tinykg_is_idempotent(tmp_path):
    plan = plan_for(load_pack(SITES / "example-shop"))
    kg = TinyKG(tmp_path / "store", TINYKG)
    first = kg.apply(plan)
    assert first["nodes_added"] == len(plan.nodes) and first["edges_added"] == len(plan.edges)
    again = TinyKG(tmp_path / "store", TINYKG).apply(plan)
    assert again == {"nodes_added": 0, "edges_added": 0}
