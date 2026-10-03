"""Open the MetaBrowser side panel in Chromium's native side-panel container at startup.

chrome.sidePanel.open() requires a user gesture. Playwright's evaluate runs with
CDP Runtime.evaluate(userGesture=true), so the daemon opens the extension's
launcher page, calls openPanel() there, and closes the page again.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger("metabrowser.panel")


async def extension_id(context: Any, timeout_ms: int = 15000) -> Optional[str]:
    for sw in context.service_workers:
        if sw.url.startswith("chrome-extension://"):
            return sw.url.split("/")[2]
    try:
        sw = await context.wait_for_event("serviceworker", timeout=timeout_ms)
        return sw.url.split("/")[2]
    except Exception:
        return None


async def open_side_panel(context: Any) -> Optional[str]:
    """Returns the extension id when the panel was opened, None otherwise (never raises)."""
    try:
        ext = await extension_id(context)
        if not ext:
            log.warning("side panel extension did not start")
            return None
        page = await context.new_page()
        try:
            await page.goto(f"chrome-extension://{ext}/launcher.html")
            await page.evaluate("openPanel()")
        finally:
            await page.close()
        return ext
    except Exception as e:  # headless shells and old binaries have no side panel
        log.warning("could not open side panel: %s", e)
        return None
