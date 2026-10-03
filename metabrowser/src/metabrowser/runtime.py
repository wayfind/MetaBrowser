"""The single owner of the browser.

Wraps a CloakBrowser persistent context and adds what agents need on top:
stable tab ids, per-session active tab, tab leases between sessions, network
capture buffers, and snapshot memory for "unchanged" detection.
"""

from __future__ import annotations

import asyncio
import fnmatch
import itertools
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import paths
from .actuator import CdpActuator
from .tools.base import ToolError

USER = "user"  # owner of tabs the human opened


@dataclass
class Tab:
    id: str
    page: Any
    owner: str
    created: float = field(default_factory=time.time)
    last_snapshot: Optional[str] = None
    capture_pattern: Optional[str] = None
    captured: deque = field(default_factory=lambda: deque(maxlen=200))
    dialog: Any = None            # pending JS dialog in an agent-owned tab (see _on_dialog)

    @property
    def internal(self) -> bool:
        """MetaBrowser's own UI (side panel, launcher): never visible to or controllable by agents."""
        try:
            return self.page.url.startswith(("chrome-extension://", "chrome://", "devtools://"))
        except Exception:
            return False


@dataclass
class LaunchOptions:
    profile: str = "default"
    headless: bool = False
    humanize: bool = True
    proxy: Optional[str] = None
    extension_paths: list[str] = field(default_factory=list)
    args: list[str] = field(default_factory=list)
    locale: Optional[str] = None
    timezone: Optional[str] = None


class BrowserRuntime:
    def __init__(self, options: LaunchOptions | None = None, context: Any = None, actuator: Any = None):
        self.options = options or LaunchOptions()
        self.actuator = actuator or CdpActuator()
        self.context = context  # injectable for tests / external Playwright contexts
        self._owns_context = context is None
        self.tabs: dict[str, Tab] = {}
        self.active: dict[str, str] = {}  # session -> tab id
        self._ids = itertools.count(1)
        self._last_actor: tuple[str, float] = (USER, 0.0)
        # (compiled text regex, url glob or None, risk, reason) — generic + site-pack risks
        self.risk_patterns: list[tuple[Any, Optional[str], Any, str]] = []
        self.sites: dict[str, Any] = {}  # site id -> SitePack, filled by sites.load_all

    # -- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        if self.context is None:
            from cloakbrowser import launch_persistent_context_async

            o = self.options
            profile = paths.ensure(paths.profiles_dir() / o.profile)
            self.context = await launch_persistent_context_async(
                str(profile),
                headless=o.headless,
                humanize=o.humanize,
                proxy=o.proxy,
                args=o.args or None,
                extension_paths=o.extension_paths or None,
                locale=o.locale,
                timezone=o.timezone,
                accept_downloads=True,
            )
        for page in self.context.pages:
            self._register(page, owner=USER)
        self.context.on("page", lambda page: self._register(page))

    async def stop(self) -> None:
        if self.context is not None and self._owns_context:
            await self.context.close()
        self.context = None

    # -- tabs --------------------------------------------------------------
    def _register(self, page: Any, owner: Optional[str] = None) -> Tab:
        for tab in self.tabs.values():
            if tab.page is page:
                return tab
        if owner is None:  # popup / target=_blank: attribute to whoever acted just now
            actor, at = self._last_actor
            owner = actor if time.time() - at < 5 else USER
        tab = Tab(id=f"t{next(self._ids)}", page=page, owner=owner)
        self.tabs[tab.id] = tab
        page.on("close", lambda _p=None, tid=tab.id: self._forget(tid))
        page.on("response", lambda resp, t=tab: asyncio.ensure_future(self._on_response(t, resp)))
        page.on("dialog", lambda dialog, t=tab: self._on_dialog(t, dialog))
        page.on("framenavigated", lambda frame, t=tab: self.actuator.on_navigated(t))
        if owner != USER:
            self.active[owner] = tab.id
        return tab

    def _on_dialog(self, tab: Tab, dialog: Any) -> None:
        """Playwright auto-dismisses dialogs only when nobody listens. With this listener:
        user-owned tabs keep the native dialog for the human; agent tabs hold it for page_dialog."""
        if tab.owner != USER:
            tab.dialog = dialog

    def _forget(self, tab_id: str) -> None:
        self.actuator.forget(tab_id)
        self.tabs.pop(tab_id, None)
        for session, tid in list(self.active.items()):
            if tid == tab_id:
                del self.active[session]

    async def open_tab(self, session: str, url: Optional[str] = None) -> Tab:
        self._last_actor = (session, time.time())
        page = await self.context.new_page()
        tab = self._register(page, owner=session)
        tab.owner = session
        self.active[session] = tab.id
        if url:
            await page.goto(url, wait_until="domcontentloaded")
        return tab

    async def tab_for(self, session: str, tab_id: Optional[str] = None, *, create: bool = True) -> Tab:
        """Resolve the tab a session acts on, enforcing leases between agent sessions."""
        self._last_actor = (session, time.time())
        if tab_id is None:
            tab_id = self.active.get(session)
            if tab_id is None or tab_id not in self.tabs or self.tabs[tab_id].internal:
                if not create:
                    raise ToolError("no_tab", "this session has no active tab; call tabs.open first")
                return await self.open_tab(session)
        tab = self.tabs.get(tab_id)
        if tab is None or tab.internal:
            raise ToolError("no_such_tab", f"tab {tab_id} does not exist; call tabs.list")
        if tab.owner not in (session, USER):
            raise ToolError("tab_leased", f"tab {tab_id} is leased by session {tab.owner}; use tabs.claim to take it over",
                            owner=tab.owner)
        self.active[session] = tab.id
        return tab

    def claim(self, session: str, tab_id: str) -> Tab:
        tab = self.tabs.get(tab_id)
        if tab is None or tab.internal:
            raise ToolError("no_such_tab", f"tab {tab_id} does not exist")
        tab.owner = session
        self.active[session] = tab_id
        return tab

    def release(self, session: str) -> None:
        """End of a session: its tabs return to the user."""
        for tab in self.tabs.values():
            if tab.owner == session:
                tab.owner = USER
        self.active.pop(session, None)

    async def current_url(self, session: str) -> Optional[str]:
        tab = self.tabs.get(self.active.get(session, ""))
        try:
            return tab.page.url if tab else None
        except Exception:
            return None

    async def describe_tabs(self) -> list[dict[str, Any]]:
        out = []
        for tab in self.tabs.values():
            if tab.internal:
                continue
            try:
                title = await tab.page.title()
            except Exception:
                title = ""
            out.append({"tab": tab.id, "owner": tab.owner, "url": tab.page.url, "title": title})
        return out

    # -- network capture -----------------------------------------------------
    async def _on_response(self, tab: Tab, resp: Any) -> None:
        if not tab.capture_pattern:
            return
        try:
            if resp.request.resource_type not in ("xhr", "fetch"):
                return
            if not fnmatch.fnmatch(resp.url, tab.capture_pattern):
                return
            ctype = (resp.headers or {}).get("content-type", "")
            if "json" not in ctype:
                return
            tab.captured.append({"url": resp.url, "status": resp.status, "method": resp.request.method,
                                 "body": await resp.text()})
        except Exception:
            pass  # page navigated away / body evicted


def artifact_path(name: str) -> Path:
    return paths.ensure(paths.artifacts_dir()) / name
