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
