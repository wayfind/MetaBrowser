"""Assemble runtime + registry + policy + trace (shared by daemon and standalone MCP)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from . import paths, sites
from .policy import PolicyGate
from .runtime import BrowserRuntime, LaunchOptions
from .tools import l1, l2
from .tools.base import ToolRegistry
from .trace import TraceRecorder


@dataclass
class Stack:
    runtime: BrowserRuntime
    registry: ToolRegistry
    gate: PolicyGate
    trace: TraceRecorder
    packs: list


def build_stack(options: Optional[LaunchOptions] = None, *, context: Any = None,
                trace_path: Optional[Path] = None, site_dirs: Optional[list[Path]] = None,
                load_sites: bool = True, record: bool = True) -> Stack:
    runtime = BrowserRuntime(options, context=context)
    gate = PolicyGate.from_file(paths.home() / "policy.json")
    if trace_path is None and record:
        trace_path = paths.ensure(paths.traces_dir()) / time.strftime("%Y%m%d-%H%M%S.ndjson")
    trace = TraceRecorder(trace_path if record else None)
    registry = ToolRegistry(runtime, gate, trace)
    l1.register(registry)
    l2.register(registry)
    packs = sites.load_all(registry, site_dirs) if load_sites else []
    return Stack(runtime, registry, gate, trace, packs)
