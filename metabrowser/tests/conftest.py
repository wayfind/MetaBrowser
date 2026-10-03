"""Fixtures: a fake merchant back-office (the example_shop pack's target) and a
Playwright context injected into the runtime, so tests need no CloakBrowser
binary download. Set METABROWSER_TEST_CHROMIUM to use a specific executable."""

from __future__ import annotations

import html
import os
from pathlib import Path

import pytest
from aiohttp import web

ORDERS = [
    {"id": f"A{1000 + i}", "customer": name, "total": f"{(i + 1) * 37.5:.2f}", "status": status, "date": f"2026-09-{i + 1:02d}"}
    for i, (name, status) in enumerate([
        ("Alice Wang", "paid"), ("Bob Li", "shipped"), ("Carol Zhang", "refunded"), ("Dan Chen", "paid"),
        ("Eve Liu", "pending"), ("Frank Wu", "paid"), ("Grace Zhou", "shipped"), ("Heidi Sun", "paid"),
    ])
]
PAGE_SIZE = 5


def _layout(body: str, logged_in: bool) -> str:
    menu = '<div data-testid="account-menu">merchant@example</div>' if logged_in else ""
    return f"<!doctype html><html><head><title>Example Shop Admin</title></head><body>{menu}<main>{body}</main></body></html>"


def make_app() -> web.Application:
    def authed(req):
        return req.cookies.get("session") == "ok"

    async def login(req):
        if req.method == "POST":
            resp = web.HTTPFound("/admin/")
            resp.set_cookie("session", "ok")
            raise resp
        return web.Response(content_type="text/html", text=_layout(
            '<h1>Sign in</h1><form method="post"><label>Email <input name="email"></label>'
            '<label>Password <input type="password" name="password"></label><button type="submit">Sign in</button></form>', False))

    async def dashboard(req):
        if not authed(req):
            raise web.HTTPFound("/login")
        return web.Response(content_type="text/html", text=_layout(
            '<h1>Dashboard</h1><a href="/admin/orders/">Orders</a><div id="kpi">loading</div>'
            '<button id="refresh" onclick="fetch(\'/api/stats\').then(r=>r.json()).then(j=>{document.getElementById(\'kpi\').innerText=j.revenue})">Refresh stats</button>',
            True))

    async def orders(req):
        if not authed(req):
            raise web.HTTPFound("/login")
        q = req.query.get("q", "").lower()
        page = int(req.query.get("page", "1"))
        rows = [o for o in ORDERS if q in o["customer"].lower() or q in o["id"].lower()]
        chunk = rows[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
        trs = "".join(
            f'<tr><td><a href="/admin/orders/{o["id"]}">{o["id"]}</a></td><td>{html.escape(o["customer"])}</td>'
            f'<td>{o["total"]}</td><td>{o["status"]}</td><td>{o["date"]}</td></tr>' for o in chunk)
        nxt = f'<a href="/admin/orders/?q={q}&page={page + 1}">Next</a>' if page * PAGE_SIZE < len(rows) else ""
        return web.Response(content_type="text/html", text=_layout(
            '<h1>Orders</h1><form><input type="search" name="q" placeholder="Search orders" aria-label="search orders" '
            f'value="{html.escape(q)}"></form>'
            '<table class="orders"><thead><tr><th>Order</th><th>Customer</th><th>Total</th><th>Status</th><th>Date</th></tr></thead>'
            f'<tbody>{trs}</tbody></table>{nxt}'
            '<form method="post" action="/admin/refund"><button type="submit">Refund selected</button></form>', True))

    async def detail(req):
        if not authed(req):
            raise web.HTTPFound("/login")
        o = next((o for o in ORDERS if o["id"] == req.match_info["oid"]), None)
        if o is None:
            raise web.HTTPNotFound()
        return web.Response(content_type="text/html", text=_layout(
            f'<h1>Order {o["id"]}</h1><div id="order-detail">Customer: {o["customer"]}<br>Total: {o["total"]}<br>'
            f'Status: {o["status"]}</div>', True))

    async def stats(req):
        return web.json_response({"revenue": "12,345.00", "orders": len(ORDERS)})

    async def refund(req):
        return web.Response(content_type="text/html", text=_layout("<h1>Refund issued</h1>", True))

    async def erp(req):
        # ERP-style shell: the business UI lives in a cross-site iframe (127.0.0.1 page, localhost frame)
        port = req.url.port
        return web.Response(content_type="text/html", text=(
            "<!doctype html><title>ERP Shell</title><h1>ERP Portal</h1>"
            f'<iframe id="app" src="http://localhost:{port}/admin/orders/" style="width:900px;height:600px"></iframe>'))

    async def widgets(req):
        return web.Response(content_type="text/html", text="""<!doctype html><title>Widgets</title>
<h1>Widgets</h1>
<button id="del" onclick="document.getElementById('out').textContent = confirm('确认删除订单 A1000?') ? 'deleted' : 'kept'">Remove order</button>
<div id="out">idle</div>
<label>Attachment <input type="file" id="f" onchange="document.getElementById('fname').textContent = this.files[0].name"></label>
<div id="fname">none</div>
<iframe srcdoc="<button onclick=&quot;parent.document.getElementById('out').textContent='inner clicked'&quot;>Inner action</button>"></iframe>
""")

    app = web.Application()
    app.router.add_get("/erp", erp)
    app.router.add_get("/widgets", widgets)
    app.router.add_route("*", "/login", login)
    app.router.add_get("/admin/", dashboard)
    app.router.add_get("/admin/orders/", orders)
    app.router.add_get("/admin/orders/{oid}", detail)
    app.router.add_post("/admin/refund", refund)
    app.router.add_get("/api/stats", stats)
    return app


@pytest.fixture
async def shop():
    runner = web.AppRunner(make_app())
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    await runner.cleanup()


@pytest.fixture(autouse=True)
def mb_home(tmp_path, monkeypatch):
    monkeypatch.setenv("METABROWSER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("METABROWSER_OUTPUTS", str(tmp_path / "outputs"))
    return tmp_path


@pytest.fixture
async def context():
    from playwright.async_api import async_playwright

    exe = os.environ.get("METABROWSER_TEST_CHROMIUM")
    async with async_playwright() as p:
        # site-per-process: cross-site iframes become out-of-process like in the real CloakBrowser binary
        browser = await p.chromium.launch(executable_path=exe or None, args=["--site-per-process"])
        ctx = await browser.new_context(accept_downloads=True)
        if os.environ.get("METABROWSER_TEST_HUMANIZE", "1") == "1":
            # Same humanized page methods as the product (launch(humanize=True)); they restrict which
            # selector kinds actions accept, so tests must exercise them.
            from cloakbrowser.human import patch_context_async
            from cloakbrowser import resolve_human_config  # public API

            patch_context_async(ctx, resolve_human_config("default"))
        yield ctx
        await ctx.close()
        await browser.close()


@pytest.fixture
async def stack(context, shop, monkeypatch, tmp_path):
    from metabrowser.stack import build_stack

    monkeypatch.setenv("METABROWSER_SITE_EXAMPLE_SHOP_URL", shop)
    s = build_stack(context=context, trace_path=tmp_path / "trace.ndjson")
    await s.runtime.start()
    yield s
    await s.runtime.stop()


async def login(context, shop: str) -> None:
    await context.add_cookies([{"name": "session", "value": "ok", "domain": shop.split("//")[1].split(":")[0], "path": "/"}])
    # the ERP fixture embeds localhost in a cross-site iframe: third-party cookies need SameSite=None; Secure
    await context.add_cookies([{"name": "session", "value": "ok", "domain": "localhost", "path": "/",
                                "sameSite": "None", "secure": True}])


SITES = Path(__file__).resolve().parents[1] / "sites"
