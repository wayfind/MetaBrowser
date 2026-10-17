"""Deterministic fixture web apps for evaluating browser agents (and for trying the recorder).

One aiohttp app, several archetypes of the sites MetaBrowser targets:
  /login, /admin/…      merchant back-office (orders, pagination, refund = irreversible)
  /erp                  ERP portal whose business UI is a cross-site iframe (OOPIF)
  /widgets              JS confirm dialog + file upload + same-process iframe
  /shop/…               storefront: search, category, sort, pagination, product specs, buy (irreversible)
  /ads/…                ad-platform back-office in the style of Ocean Engine: SPA, every number comes
                        from JSON APIs, date ranges, plan/creative levels, API pagination, CSV export
  /__eval/state|reset   side effects for graders (purchases, refunds, removals, cart)
Data are pure functions of ids and dates, so graders compute exact expected answers.
"""

from __future__ import annotations

import datetime as dt
import html
import json
from dataclasses import dataclass, field
from typing import Any

from aiohttp import web

TODAY = dt.date(2026, 10, 1)        # what the ad platform calls "today"
STATE_KEY = web.AppKey("state", object)
DATA_UNTIL = TODAY - dt.timedelta(days=1)


@dataclass
class EnvState:
    purchases: list = field(default_factory=list)
    cart: list = field(default_factory=list)
    refunds: int = 0
    removals: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"purchases": self.purchases, "cart": self.cart, "refunds": self.refunds, "removals": self.removals}


# -- data ---------------------------------------------------------------------------------------

ORDERS = [
    {"id": f"A{1000 + i}", "customer": name, "total": f"{(i + 1) * 37.5:.2f}", "status": status, "date": f"2026-09-{i + 1:02d}"}
    for i, (name, status) in enumerate([
        ("Alice Wang", "paid"), ("Bob Li", "shipped"), ("Carol Zhang", "refunded"), ("Dan Chen", "paid"),
        ("Eve Liu", "pending"), ("Frank Wu", "paid"), ("Grace Zhou", "shipped"), ("Heidi Sun", "paid"),
    ])
]
ORDER_PAGE_SIZE = 5

CATEGORIES = ["手机", "耳机", "笔记本电脑", "配件"]
BRANDS = ["星耀", "极光", "青禾", "北辰", "云帆", "澄海"]


def products() -> list[dict[str, Any]]:
    out = []
    for i in range(48):
        cat = CATEGORIES[i % 4]
        base = {"手机": 1999, "耳机": 199, "笔记本电脑": 4999, "配件": 49}[cat]
        price = base + (i * 137) % (base // 2 + 1)
        pid = 2000 + i
        spec = {"手机": {"电池容量": f"{4000 + (i * 173) % 2000} mAh", "屏幕": f"6.{i % 9 + 1} 英寸"},
                "耳机": {"电池容量": f"{300 + (i * 37) % 400} mAh", "降噪": "支持" if i % 3 else "不支持"},
                "笔记本电脑": {"内存": f"{8 * (1 + i % 4)} GB", "重量": f"1.{i % 9 + 1} kg"},
                "配件": {"材质": ["硅胶", "皮革", "TPU"][i % 3], "颜色": ["黑", "白", "蓝"][i % 3]}}[cat]
        out.append({"id": pid, "name": f"{BRANDS[i % 6]} {cat} {chr(65 + i % 26)}{i:02d}", "category": cat,
                    "price": round(price + (i % 10) * 0.9, 2), "sales": (i * 7919) % 5000 + 10, "spec": spec})
    return out


PRODUCTS = products()
SHOP_PAGE_SIZE = 12

PLANS = [{"plan_id": 1001 + i, "plan_name": f"计划-{['上海', '杭州', '成都', '广州', '武汉'][i % 5]}-{i + 1:02d}"} for i in range(23)]
CREATIVES = [{"creative_id": 5001 + i, "creative_name": f"创意-{p['plan_id']}-{k + 1}", "plan_id": p["plan_id"]}
             for i, (p, k) in enumerate((p, k) for p in PLANS for k in range(2))]


def _daily(entity_id: int, day: dt.date) -> dict[str, float]:
    o = day.toordinal()
    cost = round(((entity_id * 7919 + o * 104729) % 50000) / 100, 2)
    click = int(cost * 1.3) + entity_id % 7
    return {"cost": cost, "show": int(cost * 37), "click": click, "convert": click // 20}


def ads_report(level: str, start: str, end: str) -> list[dict[str, Any]]:
    """Aggregated metrics per plan/creative over [start, end], sorted by cost desc (the API's order)."""
    d0, d1 = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    days = [d0 + dt.timedelta(days=k) for k in range((d1 - d0).days + 1)]
    rows = []
    for ent in (PLANS if level == "plan" else CREATIVES):
        eid = ent.get("creative_id", ent.get("plan_id"))
        agg = {"cost": 0.0, "show": 0, "click": 0, "convert": 0}
        for day in days:
            for k, v in _daily(eid, day).items():
                agg[k] += v
        agg["cost"] = round(agg["cost"], 2)
        rows.append({**ent, **agg})
    return sorted(rows, key=lambda r: (-r["cost"], r.get("creative_id", r.get("plan_id"))))


# -- pages ------------------------------------------------------------------------------------

def _layout(body: str, logged_in: bool, title: str = "Example Shop Admin") -> str:
    menu = '<div data-testid="account-menu">merchant@example</div>' if logged_in else ""
    return f"<!doctype html><html><head><meta charset=utf-8><title>{title}</title></head><body>{menu}<main>{body}</main></body></html>"


def _shop_layout(body: str, title: str = "云选商城") -> str:
    return (f"<!doctype html><html><head><meta charset=utf-8><title>{title}</title></head><body>"
            f'<header><a href="/shop/">云选商城</a> <form action="/shop/" style="display:inline">'
            f'<input type="search" name="kw" aria-label="搜索商品" placeholder="搜索商品"><button>搜索</button></form>'
            f' <a href="/shop/cart">购物车</a></header><main>{body}</main></body></html>')


ADS_SHELL = r"""<!doctype html><html><head><meta charset=utf-8><title>巨量广告 · 投放管理</title>
<style>body{font-family:sans-serif;margin:0;display:flex} nav{width:160px;background:#f3f3f3;padding:12px}
nav a{display:block;padding:6px 0} section{padding:16px;flex:1} table{border-collapse:collapse} td,th{border:1px solid #ccc;padding:4px 8px}</style>
</head><body>
<nav aria-label="主导航"><div data-testid="ads-account">账户：云选旗舰店 (1688001)</div>
<a href="#/home">首页</a><a href="#/report">数据报表</a><a href="#/account">账户</a></nav>
<section id="view">loading…</section>
<script>
const DATA_UNTIL = "__DATA_UNTIL__";
const state = { level: 'plan', start: DATA_UNTIL, end: DATA_UNTIL, page: 1, size: 10 };
const view = document.getElementById('view');
function shift(d, n) { const x = new Date(d + 'T00:00:00Z'); x.setUTCDate(x.getUTCDate() + n); return x.toISOString().slice(0, 10); }
async function load() {
  const q = new URLSearchParams({ level: state.level, start: state.start, end: state.end, page: state.page, size: state.size });
  const res = await fetch('/ads/api/report?' + q);
  const j = await res.json();
  const rows = j.data.list.map(r => `<tr><td>${r.plan_name || r.creative_name}</td><td>${r.cost.toFixed(2)}</td><td>${r.show}</td><td>${r.click}</td><td>${r.convert}</td></tr>`).join('');
  document.getElementById('grid').innerHTML = `<table aria-label="报表"><thead><tr><th>${state.level === 'plan' ? '计划名称' : '创意名称'}</th><th>消耗(元)</th><th>展示</th><th>点击</th><th>转化</th></tr></thead><tbody>${rows}</tbody></table>`;
  document.getElementById('pager').textContent = `第 ${j.data.page_info.page} / ${j.data.page_info.total_page} 页，共 ${j.data.page_info.total} 条`;
  document.getElementById('prev').disabled = j.data.page_info.page <= 1;
  document.getElementById('next').disabled = j.data.page_info.page >= j.data.page_info.total_page;
}
function report() {
  view.innerHTML = `<h1>数据报表</h1><p>数据更新至 ${DATA_UNTIL}（今天是 ${shift(DATA_UNTIL, 1)}）</p>
  <div role="tablist"><button role="tab" id="t-plan">按计划</button><button role="tab" id="t-creative">按创意</button></div>
  <label>开始日期 <input type="date" id="start" value="${state.start}"></label>
  <label>结束日期 <input type="date" id="end" value="${state.end}"></label>
  <button id="yesterday">昨天</button><button id="last7">近7天</button><button id="query">查询</button>
  <button id="export">导出</button>
  <div id="grid">加载中…</div><button id="prev">上一页</button><span id="pager"></span><button id="next">下一页</button>`;
  const pick = () => { state.start = document.getElementById('start').value; state.end = document.getElementById('end').value; };
  document.getElementById('t-plan').onclick = () => { state.level = 'plan'; state.page = 1; load(); };
  document.getElementById('t-creative').onclick = () => { state.level = 'creative'; state.page = 1; load(); };
  document.getElementById('yesterday').onclick = () => { state.start = state.end = DATA_UNTIL; report(); };
  document.getElementById('last7').onclick = () => { state.start = shift(DATA_UNTIL, -6); state.end = DATA_UNTIL; report(); };
  document.getElementById('query').onclick = () => { pick(); state.page = 1; load(); };
  document.getElementById('prev').onclick = () => { state.page--; load(); };
  document.getElementById('next').onclick = () => { state.page++; load(); };
  document.getElementById('export').onclick = () => { pick(); location.href = '/ads/api/export?' + new URLSearchParams({ level: state.level, start: state.start, end: state.end }); };
  load();
}
function route() {
  const h = location.hash || '#/home';
  if (h.startsWith('#/report')) report();
  else if (h.startsWith('#/account')) view.innerHTML = '<h1>账户</h1><p>余额 ¥12,345.67</p>';
  else view.innerHTML = '<h1>首页</h1><p>欢迎使用巨量广告。请从左侧进入「数据报表」。</p>';
}
window.addEventListener('hashchange', route); route();
</script></body></html>"""


def make_app(state: EnvState | None = None) -> web.Application:
    state = state or EnvState()

    def authed(req):
        # cookie, or a signed-URL style token: real browsers block third-party cookies, so an app embedded
        # in a cross-site iframe (the ERP shell) authenticates through its URL instead
        return req.cookies.get("session") == "ok" or req.query.get("token") == "ok"

    # -- merchant back-office ----------------------------------------------------------------------
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
        status = req.query.get("status", "")
        page = int(req.query.get("page", "1"))
        rows = [o for o in ORDERS if (q in o["customer"].lower() or q in o["id"].lower()) and (not status or o["status"] == status)]
        chunk = rows[(page - 1) * ORDER_PAGE_SIZE: page * ORDER_PAGE_SIZE]
        # The cross-site ERP fixture uses URL authentication when third-party
        # cookies are blocked. Preserve that credential across links/forms.
        token_query = "?token=ok" if req.query.get("token") == "ok" else ""
        trs = "".join(
            f'<tr><td><a href="/admin/orders/{o["id"]}{token_query}">{o["id"]}</a></td><td>{html.escape(o["customer"])}</td>'
            f'<td>{o["total"]}</td><td>{o["status"]}</td><td>{o["date"]}</td></tr>' for o in chunk)
        nxt = f'<a href="/admin/orders/?q={q}&status={status}&page={page + 1}{"&token=ok" if token_query else ""}">Next</a>' if page * ORDER_PAGE_SIZE < len(rows) else ""
        return web.Response(content_type="text/html", text=_layout(
            '<h1>Orders</h1><form><input type="search" name="q" placeholder="Search orders" aria-label="search orders" '
            f'value="{html.escape(q)}">' + ('<input type="hidden" name="token" value="ok">' if token_query else '') + '</form>' +
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
        state.refunds += 1
        return web.Response(content_type="text/html", text=_layout("<h1>Refund issued</h1>", True))

    async def erp(req):
        port = req.url.port
        return web.Response(content_type="text/html", text=(
            "<!doctype html><title>ERP Shell</title><h1>ERP Portal</h1>"
            f'<iframe id="app" src="http://localhost:{port}/admin/orders/?token=ok" style="width:900px;height:600px"></iframe>'))

    async def widgets(req):
        return web.Response(content_type="text/html", text="""<!doctype html><title>Widgets</title>
<h1>Widgets</h1>
<button id="del" onclick="if (confirm('确认删除订单 A1000?')) { fetch('/widgets/remove', {method: 'POST'}); document.getElementById('out').textContent = 'deleted' } else { document.getElementById('out').textContent = 'kept' }">Remove order</button>
<div id="out">idle</div>
<label>Attachment <input type="file" id="f" onchange="document.getElementById('fname').textContent = this.files[0].name"></label>
<div id="fname">none</div>
<iframe srcdoc="<button onclick=&quot;parent.document.getElementById('out').textContent='inner clicked'&quot;>Inner action</button>"></iframe>
""")

    async def widgets_remove(req):
        state.removals += 1
        return web.json_response({"ok": True})

    # -- storefront --------------------------------------------------------------------------------
    async def shop_list(req):
        kw = req.query.get("kw", "").strip()
        cat = req.query.get("cat", "")
        sort = req.query.get("sort", "")
        page = max(1, int(req.query.get("page", "1") or 1))
        items = [p for p in PRODUCTS if (not kw or kw.lower() in p["name"].lower()) and (not cat or p["category"] == cat)]
        if sort == "price_asc":
            items.sort(key=lambda p: p["price"])
        elif sort == "price_desc":
            items.sort(key=lambda p: -p["price"])
        elif sort == "sales":
            items.sort(key=lambda p: -p["sales"])
        total_pages = max(1, -(-len(items) // SHOP_PAGE_SIZE))
        chunk = items[(page - 1) * SHOP_PAGE_SIZE: page * SHOP_PAGE_SIZE]
        cats = " ".join(f'<a href="/shop/?cat={c}">{c}</a>' for c in CATEGORIES)
        cards = "".join(f'<li class="product"><a href="/shop/p/{p["id"]}">{html.escape(p["name"])}</a> '
                        f'<span class="price">¥{p["price"]:.2f}</span> <span class="sales">已售 {p["sales"]}</span></li>'
                        for p in chunk)
        qs = f"kw={kw}&cat={cat}&sort={sort}"
        nxt = f'<a href="/shop/?{qs}&page={page + 1}">下一页</a>' if page < total_pages else ""
        prev = f'<a href="/shop/?{qs}&page={page - 1}">上一页</a>' if page > 1 else ""
        sort_form = (f'<form><input type="hidden" name="kw" value="{html.escape(kw)}"><input type="hidden" name="cat" value="{cat}">'
                     '<label>排序 <select name="sort"><option value="">默认</option><option value="price_asc">价格从低到高</option>'
                     '<option value="price_desc">价格从高到低</option><option value="sales">销量</option></select></label>'
                     '<button>应用</button></form>')
        return web.Response(content_type="text/html", text=_shop_layout(
            f'<nav aria-label="类目">{cats}</nav>{sort_form}<p>共 {len(items)} 件商品 · 第 {page}/{total_pages} 页</p>'
            f'<ul class="products">{cards}</ul>{prev} {nxt}'))

    async def shop_detail(req):
        p = next((p for p in PRODUCTS if p["id"] == int(req.match_info["pid"])), None)
        if p is None:
            raise web.HTTPNotFound()
        spec = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in p["spec"].items())
        return web.Response(content_type="text/html", text=_shop_layout(
            f'<h1>{html.escape(p["name"])}</h1><p class="price">¥{p["price"]:.2f}</p><p>已售 {p["sales"]}</p>'
            f'<table class="spec"><caption>规格参数</caption>{spec}</table>'
            f'<form method="post" action="/shop/cart"><input type="hidden" name="pid" value="{p["id"]}"><button>加入购物车</button></form>'
            f'<form method="post" action="/shop/buy"><input type="hidden" name="pid" value="{p["id"]}"><button>立即购买</button></form>',
            title=p["name"]))

    async def shop_cart_add(req):
        data = await req.post()
        state.cart.append(int(data.get("pid", 0)))
        raise web.HTTPFound("/shop/cart")

    async def shop_cart(req):
        items = "".join(f"<li>{next(p['name'] for p in PRODUCTS if p['id'] == pid)}</li>" for pid in state.cart)
        return web.Response(content_type="text/html", text=_shop_layout(f"<h1>购物车</h1><ul>{items}</ul>"))

    async def shop_buy(req):
        data = await req.post()
        state.purchases.append(int(data.get("pid", 0)))
        return web.Response(content_type="text/html", text=_shop_layout("<h1>下单成功</h1>"))

    # -- ad platform (Ocean Engine style) ------------------------------------------------------------
    def ads_authed(req):
        return req.cookies.get("ads_session") == "ok"

    async def ads_login(req):
        if req.method == "POST":
            resp = web.HTTPFound("/ads/#/home")
            resp.set_cookie("ads_session", "ok")
            raise resp
        return web.Response(content_type="text/html", text=(
            "<!doctype html><meta charset=utf-8><title>巨量广告 · 登录</title><h1>登录巨量广告</h1>"
            '<form method="post"><label>手机号 <input name="phone"></label><label>密码 <input type="password" name="password"></label>'
            '<button type="submit">登录</button></form>'))

    async def ads_shell(req):
        if not ads_authed(req):
            raise web.HTTPFound("/ads/login")
        return web.Response(content_type="text/html", text=ADS_SHELL.replace("__DATA_UNTIL__", DATA_UNTIL.isoformat()))

    def _ads_params(req):
        level = req.query.get("level", "plan")
        start = req.query.get("start", DATA_UNTIL.isoformat())
        end = req.query.get("end", start)
        return level if level in ("plan", "creative") else "plan", start, end

    async def ads_api_report(req):
        if not ads_authed(req):
            return web.json_response({"code": 401, "message": "未登录"}, status=401)
        level, start, end = _ads_params(req)
        page, size = max(1, int(req.query.get("page", "1"))), min(100, max(1, int(req.query.get("size", "10"))))
        rows = ads_report(level, start, end)
        total_page = max(1, -(-len(rows) // size))
        return web.json_response({"code": 0, "data": {"list": rows[(page - 1) * size: page * size],
                                                      "page_info": {"page": page, "page_size": size, "total": len(rows),
                                                                    "total_page": total_page}}})

    async def ads_api_export(req):
        if not ads_authed(req):
            raise web.HTTPUnauthorized()
        level, start, end = _ads_params(req)
        name_key = "plan_name" if level == "plan" else "creative_name"
        lines = [f"{name_key},cost,show,click,convert"] + [
            f"{r[name_key]},{r['cost']:.2f},{r['show']},{r['click']},{r['convert']}" for r in ads_report(level, start, end)]
        return web.Response(body="\n".join(lines).encode("utf-8"), content_type="text/csv",
                            headers={"Content-Disposition": f'attachment; filename="report_{level}_{start}_{end}.csv"'})

    # -- eval control ------------------------------------------------------------------------------
    async def eval_state(req):
        return web.json_response(state.to_dict())

    async def eval_reset(req):
        state.purchases.clear(); state.cart.clear(); state.refunds = 0; state.removals = 0  # noqa: E702
        return web.json_response({"ok": True})

    app = web.Application()
    app[STATE_KEY] = state
    r = app.router
    r.add_route("*", "/login", login)
    r.add_get("/admin/", dashboard)
    r.add_get("/admin/orders/", orders)
    r.add_get("/admin/orders/{oid}", detail)
    r.add_post("/admin/refund", refund)
    r.add_get("/api/stats", stats)
    r.add_get("/erp", erp)
    r.add_get("/widgets", widgets)
    r.add_post("/widgets/remove", widgets_remove)
    r.add_get("/shop/", shop_list)
    r.add_get("/shop/p/{pid}", shop_detail)
    r.add_post("/shop/cart", shop_cart_add)
    r.add_get("/shop/cart", shop_cart)
    r.add_post("/shop/buy", shop_buy)
    r.add_route("*", "/ads/login", ads_login)
    r.add_get("/ads/", ads_shell)
    r.add_get("/ads/api/report", ads_api_report)
    r.add_get("/ads/api/export", ads_api_export)
    r.add_get("/__eval/state", eval_state)
    r.add_post("/__eval/reset", eval_reset)
    return app


class EnvServer:
    """Run the fixture app on 127.0.0.1 (also reachable as localhost for cross-site iframes)."""

    def __init__(self, port: int = 0):
        self.port = port
        self.state = EnvState()
        self.runner = None
        self.url = ""

    async def start(self) -> str:
        self.runner = web.AppRunner(make_app(self.state))
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", self.port)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        return self.url

    async def stop(self) -> None:
        if self.runner:
            await self.runner.cleanup()

    def reset(self) -> None:
        self.state.purchases.clear(); self.state.cart.clear()  # noqa: E702
        self.state.refunds = 0
        self.state.removals = 0

    def cookies(self) -> list[dict[str, Any]]:
        """Logged-in sessions for the fixture back-offices (the eval's stand-in for the user's login)."""
        return [{"name": "session", "value": "ok", "domain": "127.0.0.1", "path": "/"},
                {"name": "session", "value": "ok", "domain": "localhost", "path": "/", "sameSite": "None", "secure": True},
                {"name": "ads_session", "value": "ok", "domain": "127.0.0.1", "path": "/"}]
