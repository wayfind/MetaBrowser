"""CDP actuator: accessibility perception across frames, coordinate actions, dialogs, uploads, stealth hygiene."""

import pytest

from conftest import login
from metabrowser.tools.base import ToolError


async def call(stack, tool, session="s1", **args):
    return await stack.registry.call(tool, args, session_id=session)


def ref_of(text: str, needle: str) -> str:
    return next(line.split("]")[0][1:] for line in text.splitlines() if needle in line and line.startswith("["))


async def test_cross_origin_iframe_is_perceived_and_actionable(stack, shop):
    await login(stack.runtime.context, shop)
    snap = await call(stack, "page.navigate", url=shop + "/erp")
    assert "frames=2" in snap.text and "(cross-origin)" in snap.text, snap.text
    assert 'link "A1003"' in snap.text
    table = await call(stack, "data.extract_table")
    assert table.data[0]["Order"] == "A1000"  # table lives inside the cross-site iframe
    res = await call(stack, "page.click", ref=ref_of(snap.text, 'link "A1003"'))
    assert "Dan Chen" in (await call(stack, "page.read")).text


async def test_same_process_iframe_and_no_dom_mutation(stack, shop):
    snap = await call(stack, "page.navigate", url=shop + "/widgets")
    await call(stack, "page.click", ref=ref_of(snap.text, 'button "Inner action"'), snapshot=False)
    page = stack.runtime.tabs[stack.runtime.active["s1"]].page
    assert await page.evaluate("document.getElementById('out').textContent") == "inner clicked"
    # refs live in the actuator: nothing was written into the page
    assert await page.evaluate("document.querySelectorAll('[data-mb-ref]').length") == 0
    assert await page.evaluate("document.documentElement.hasAttribute('data-mb-counter')") is False


async def test_confirm_dialog_is_held_risk_gated_and_accepted(stack, shop):
    snap = await call(stack, "page.navigate", url=shop + "/widgets")
    res = await call(stack, "page.click", ref=ref_of(snap.text, 'button "Remove order"'))
    assert "dialog confirm" in res.text and "确认删除订单" in res.text
    with pytest.raises(ToolError) as e:
        await call(stack, "page.snapshot") and await call(stack, "page.type", ref="e1", text="x")
    assert e.value.code == "dialog_open"
    with pytest.raises(ToolError) as e:
        await call(stack, "page.dialog", accept=True)
    assert e.value.code == "approval_required" and e.value.details["risk"] == "irreversible"
    asked = []

    async def approver(req):
        asked.append(req)
        return "allow_once"

    stack.gate.approver = approver
    await call(stack, "page.dialog", accept=True, snapshot=False)
    page = stack.runtime.tabs[stack.runtime.active["s1"]].page
    assert await page.evaluate("document.getElementById('out').textContent") == "deleted"
    assert asked[0].tool == "page.dialog"


async def test_upload_inside_outputs_needs_submit_approval(stack, shop, mb_home):
    outputs = mb_home / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "invoice.pdf").write_bytes(b"%PDF-1.4 test")
    snap = await call(stack, "page.navigate", url=shop + "/widgets")
    ref = ref_of(snap.text, '"Attachment"')
    risks = []

    async def approver(req):
        risks.append(req.risk)
        return "allow_once"

    stack.gate.approver = approver
    await call(stack, "file.upload", ref=ref, paths=[str(outputs / "invoice.pdf")])
    page = stack.runtime.tabs[stack.runtime.active["s1"]].page
    assert await page.evaluate("document.getElementById('fname').textContent") == "invoice.pdf"
    assert risks == ["submit"]
    secret = mb_home / "elsewhere.txt"
    secret.write_text("x")
    risks.clear()
    await call(stack, "file.upload", ref=ref, paths=[str(secret)])
    assert risks == ["irreversible"]  # files outside ~/MetaBrowser escalate


async def test_collect_pages_on_client_rendered_grid_with_totals(stack, shop):
    """Ad-platform SPA: rows load via fetch after each next click; totals come from the tool, not the model."""
    from metabrowser.evals import envs

    await stack.runtime.context.add_cookies([{"name": "ads_session", "value": "ok", "domain": "127.0.0.1", "path": "/"}])
    await call(stack, "page.navigate", url=shop + "/ads/#/report", snapshot=False)
    await call(stack, "page.wait", text="共 23 条")
    res = await call(stack, "data.collect_pages", table_selector="table")
    assert len(res.data) == 23 and "stopped: last page" in res.text, res.text[:300]
    day = envs.DATA_UNTIL.isoformat()
    expected = round(sum(r["cost"] for r in envs.ads_report("plan", day, day)), 2)
    assert f"消耗(元)={expected:g}" in res.text


async def test_extract_table_flags_partial_page(stack, shop):
    await login(stack.runtime.context, shop)
    await call(stack, "page.navigate", url=shop + "/admin/orders/", snapshot=False)
    res = await call(stack, "data.extract_table")
    assert "PARTIAL" in res.text and len(res.data) == 5


async def test_orders_recipe_collects_all_pages_and_filters_by_url(stack, shop):
    await login(stack.runtime.context, shop)
    res = await call(stack, "site.run", site="example_shop", capability="orders_list", args={"status": "paid"})
    assert sorted(r["Order"] for r in res.data) == ["A1000", "A1003", "A1005", "A1007"], res.text[:200]
    assert "PARTIAL" not in res.text


async def test_date_inputs_are_set_in_one_call_and_totals_include_integer_metrics(stack, shop):
    from metabrowser.evals import envs

    await stack.runtime.context.add_cookies([{"name": "ads_session", "value": "ok", "domain": "127.0.0.1", "path": "/"}])
    await call(stack, "page.navigate", url=shop + "/ads/#/report", snapshot=False)
    await call(stack, "page.wait", text="共 23 条")
    snap = (await call(stack, "page.snapshot", force=True)).text
    assert 'Date "开始日期' in snap and "(type YYYY-MM-DD)" in snap and 'spinbutton "年' not in snap, snap[:800]
    await call(stack, "page.type", ref=ref_of(snap, 'Date "开始日期'), text="2026-09-01")
    await call(stack, "page.type", ref=ref_of(snap, 'Date "结束日期'), text="2026-09-07")
    await call(stack, "page.click", ref=ref_of(snap, 'button "查询"'), snapshot=False)
    await call(stack, "page.wait", text="共 23 条")
    res = await call(stack, "data.collect_pages", table_selector="table")
    clicks = sum(r["click"] for r in envs.ads_report("plan", "2026-09-01", "2026-09-07"))
    assert len(res.data) == 23 and f"点击={clicks}" in res.text, res.text[:300]
    with pytest.raises(ToolError) as e:
        await call(stack, "page.type", ref=ref_of(snap, 'Date "开始日期'), text="9/1")
    assert e.value.code == "invalid_value"
