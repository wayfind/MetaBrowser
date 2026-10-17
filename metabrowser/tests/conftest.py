"""Fixtures: a fake merchant back-office (the example_shop pack's target) and a
Playwright context injected into the runtime, so tests need no commercial
binary download. Set METABROWSER_TEST_CHROMIUM to use a specific executable."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from aiohttp import web

from metabrowser.evals.envs import ORDERS, make_app  # noqa: E402,F401  (fixture sites shared with the eval suite)


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
            from metabrowser.engine import patch_context

            patch_context(ctx)
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
