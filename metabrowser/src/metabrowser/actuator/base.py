"""Actuator: the only layer that touches the browser engine.

Everything above it (L1/L2 tools, site recipes, PolicyGate, traces, the embedded
agent) talks to this interface, so the engine binding can be replaced — today
`CdpActuator` (CloakBrowser binary over the Playwright CDP pipe); with browser
source, a native in-process actor — without touching tools, site packs or audit.

Refs (`e12`) are actuator-issued handles to concrete elements. They are stable for
the element's lifetime in a tab and never written into the page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


@dataclass
class ElementInfo:
    ref: str
    role: str
    name: str
    frame_url: str = ""
    is_submit: bool = False
    tag: str = ""


@dataclass
class Snapshot:
    url: str
    title: str
    lines: list[str]
    hash: str
    truncated: bool = False
    scroll: dict[str, Any] = field(default_factory=dict)
    frames: int = 1


class Actuator(Protocol):
    # perception
    async def snapshot(self, tab: Any, max_items: int = 400) -> Snapshot: ...
    async def element(self, tab: Any, ref: str) -> ElementInfo: ...
    async def find(self, tab: Any, *, role: Optional[str] = None, name: Optional[str] = None,
                   text: Optional[str] = None, label: Optional[str] = None, placeholder: Optional[str] = None,
                   css: Optional[str] = None, timeout_ms: int = 0) -> Optional[str]: ...
    async def read_text(self, tab: Any, selector: Optional[str] = None) -> str: ...
    async def tables(self, tab: Any, selector: Optional[str] = None) -> list[dict[str, Any]]: ...
    # action
    async def click(self, tab: Any, ref: str, *, button: str = "left", double: bool = False) -> None: ...
    async def type(self, tab: Any, ref: str, text: str, *, clear: bool = True, submit: bool = False) -> None: ...
    async def select(self, tab: Any, ref: str, labels: list[str]) -> list[str]: ...
    async def set_checked(self, tab: Any, ref: str, checked: bool) -> None: ...
    async def press(self, tab: Any, key: str, ref: Optional[str] = None) -> None: ...
    async def scroll(self, tab: Any, *, dy: int = 0, ref: Optional[str] = None) -> None: ...
    async def screenshot(self, tab: Any, *, ref: Optional[str] = None, full_page: bool = False) -> bytes: ...
    def forget(self, tab_id: str) -> None: ...
