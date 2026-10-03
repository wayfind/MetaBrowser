import json

import pytest

from conftest import login
from metabrowser.tools.base import ToolError
from metabrowser.trace import read_events, verify

S = "s1"


async def call(stack, tool, session=S, **args):
    return await stack.registry.call(tool, args, session_id=session)


async def test_snapshot_refs_and_unchanged(stack, shop):
    await login(stack.runtime.context, shop)
    res = await call(stack, "page.navigate", url=shop + "/admin/orders/")
    assert "table rows=6" in res.text
    assert '[e' in res.text and 'link "A1000"' in res.text
    again = await call(stack, "page.snapshot")
    assert "unchanged" in again.text


async def test_click_by_ref_navigates(stack, shop):
    await login(stack.runtime.context, shop)
    res = await call(stack, "page.navigate", url=shop + "/admin/orders/")
    ref = next(line.split("]")[0][1:] for line in res.text.splitlines() if 'link "A1001"' in line)
    res = await call(stack, "page.click", ref=ref)
    assert "/admin/orders/A1001" in res.text


async def test_l2_extract_and_collect_pages(stack, shop):
    await login(stack.runtime.context, shop)
    await call(stack, "page.navigate", url=shop + "/admin/orders/", snapshot=False)
    one = await call(stack, "data.extract_table")
    assert one.data[0] == {"Order": "A1000", "Customer": "Alice Wang", "Total": "37.50", "Status": "paid", "Date": "2026-09-01"}
    allp = await call(stack, "data.collect_pages", max_pages=5)
    assert len(allp.data) == 8 and "from 2 page(s)" in allp.text


async def test_read_and_form_fill(stack, shop):
    await call(stack, "page.navigate", url=shop + "/login", snapshot=False)
    res = await call(stack, "form.fill", fields=[{"label": "Email", "value": "m@example.com"},
                                                {"label": "Password", "value": "hunter2", "secret": True}])
    assert "not submitted" in res.text
    text = await call(stack, "page.read")
    assert "# Sign in" in text.text
    # secret value never lands in the trace
    raw = stack.trace.path.read_text()
    assert "hunter2" not in raw and "m@example.com" in raw


async def test_net_capture(stack, shop):
    await login(stack.runtime.context, shop)
    res = await call(stack, "page.navigate", url=shop + "/admin/")
    await call(stack, "net.capture_start", url_glob="*/api/*")
    ref = next(line.split("]")[0][1:] for line in res.text.splitlines() if "Refresh stats" in line)
    await call(stack, "page.click", ref=ref, snapshot=False)
    await call(stack, "page.wait", text="12,345.00")
    out = await call(stack, "net.capture_read")
    assert "/api/stats" in out.text
    saved = json.loads(open(out.artifacts[0]).read())
    assert json.loads(saved[0]["body"])["revenue"] == "12,345.00"


async def test_submit_needs_approval_and_irreversible_escalation(stack, shop):
    await login(stack.runtime.context, shop)
    res = await call(stack, "page.navigate", url=shop + "/admin/orders/")
    ref = next(line.split("]")[0][1:] for line in res.text.splitlines() if "Refund selected" in line)
    with pytest.raises(ToolError) as e:
        await call(stack, "page.click", ref=ref)
    assert e.value.code == "approval_required"
    assert e.value.details["risk"] == "irreversible"  # site pack risk pattern + generic vocabulary

    answers = []

    async def approver(req):
        answers.append(req)
        return "allow_once"

    stack.gate.approver = approver
    res = await call(stack, "page.click", ref=ref)
    assert "Refund issued" in res.text
    assert answers[0].risk == "irreversible" and "refund" in answers[0].reason.lower()


async def test_system_risk_denied_by_default(stack, shop):
    await call(stack, "page.navigate", url=shop + "/login", snapshot=False)
    with pytest.raises(ToolError) as e:
        await call(stack, "page.evaluate", expression="document.cookie")
    assert e.value.code == "denied"


async def test_tab_leases_between_sessions(stack, shop):
    await call(stack, "tabs.open", session="a", url=shop + "/login")
    tab_a = stack.runtime.active["a"]
    with pytest.raises(ToolError) as e:
        await call(stack, "page.snapshot", session="b", tab=tab_a)
    assert e.value.code == "tab_leased"
    await call(stack, "tabs.claim", session="b", tab=tab_a)
    assert stack.runtime.tabs[tab_a].owner == "b"


async def test_trace_chain_and_tamper_detection(stack, shop):
    await call(stack, "page.navigate", url=shop + "/login", snapshot=False)
    await call(stack, "page.snapshot")
    ok, msg = verify(stack.trace.path)
    assert ok, msg
    events = [e for e in read_events(stack.trace.path) if e.get("type") == "tool_call"]
    assert [e["tool"] for e in events] == ["page.navigate", "page.snapshot"]
    assert events[1]["snapshot_hash"] and events[0]["url_after"].endswith("/login")
    lines = stack.trace.path.read_text().splitlines()
    lines[1] = lines[1].replace("page.navigate", "page.nav1gate")
    stack.trace.path.write_text("\n".join(lines) + "\n")
    ok, msg = verify(stack.trace.path)
    assert not ok and "tampered" in msg
