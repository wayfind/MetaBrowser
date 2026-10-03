"""Tool contract shared by every exit (MCP stdio, MCP HTTP, side panel, AgentCore).

Every call goes through one pipeline so policy and audit cannot be skipped:

    validate -> assess (effective risk) -> PolicyGate -> handler -> TraceRecorder
"""

from __future__ import annotations

import asyncio
import enum
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from ..policy import PolicyGate
    from ..runtime import BrowserRuntime
    from ..trace import TraceRecorder


class Risk(enum.IntEnum):
    """Ordered so that max() picks the stricter level."""

    READ = 0          # read page content, list tabs
    NAVIGATE = 1      # change URL / open tabs
    INPUT = 2         # type / select without committing
    SUBMIT = 3        # commit a form, save, send
    IRREVERSIBLE = 4  # pay, delete, approve, ship
    SYSTEM = 5        # arbitrary JS, cookie export, profile access

    @classmethod
    def parse(cls, value: "str | Risk") -> "Risk":
        if isinstance(value, Risk):
            return value
        return cls[str(value).upper()]

    @property
    def label(self) -> str:
        return self.name.lower()


class ToolError(Exception):
    """Model-visible failure: becomes an MCP isError result / metacodes structured_error."""

    def __init__(self, code: str, message: str, **details: Any):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            body["details"] = self.details
        return {"error": body}


@dataclass
class ToolResult:
    """Inline text/JSON, optional image (base64), optional artifact files on disk."""

    text: str = ""
    data: Any = None
    image_b64: Optional[str] = None
    image_mime: str = "image/png"
    artifacts: list[str] = field(default_factory=list)

    def summary(self, limit: int = 300) -> str:
        """Short form for the trace (never the full payload)."""
        s = self.text or ("" if self.data is None else repr(self.data))
        if self.image_b64:
            s = f"[image {len(self.image_b64) * 3 // 4} bytes] " + s
        return s if len(s) <= limit else s[:limit] + "…"


@dataclass
class ToolContext:
    session_id: str
    runtime: "BrowserRuntime"
    actor: str = "agent"  # agent | user | recipe
    registry: Optional["ToolRegistry"] = None
    # Filled by assess(); read by the gate and the trace.
    notes: dict[str, Any] = field(default_factory=dict)


Handler = Callable[[ToolContext, dict[str, Any]], Awaitable[ToolResult]]
Assessor = Callable[[ToolContext, dict[str, Any]], Awaitable[tuple[Risk, str]]]


@dataclass
class ToolSpec:
    name: str                    # dotted, e.g. "page.click"
    layer: str                   # L1 | L2 | L3 | L4
    risk: Risk
    description: str
    input_schema: dict[str, Any]
    handler: Handler
    assess: Optional[Assessor] = None   # may escalate risk per call (e.g. a "Pay" button)
    secret_args: tuple[str, ...] = ()   # redacted in traces

    @property
    def wire_name(self) -> str:
        """MCP / metacodes tool names allow [A-Za-z0-9_-] only."""
        return self.name.replace(".", "_")

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.wire_name,
            "description": f"[{self.layer}·risk={self.risk.label}] {self.description}",
            "inputSchema": self.input_schema,
        }


def schema(properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    """JSON Schema subset accepted by metacodes (root object/properties/required)."""
    s: dict[str, Any] = {"type": "object", "properties": properties or {}}
    if required:
        s["required"] = required
    return s


def redact_args(spec: ToolSpec, args: dict[str, Any]) -> dict[str, Any]:
    """Static secret args, plus per-call `secret: true` on a value or on list items."""
    out: dict[str, Any] = {}
    secret_call = bool(args.get("secret"))
    for k, v in args.items():
        if k in spec.secret_args or (secret_call and k in ("text", "value")):
            out[k] = "***"
        elif isinstance(v, list):
            out[k] = [{**i, "value": "***"} if isinstance(i, dict) and i.get("secret") else i for i in v]
        elif isinstance(v, dict):
            out[k] = {kk: ("***" if isinstance(vv, dict) and vv.get("secret") else vv) for kk, vv in v.items()}
        else:
            out[k] = v
    return out


class ToolRegistry:
    def __init__(self, runtime: "BrowserRuntime", gate: "PolicyGate", trace: "TraceRecorder"):
        self.runtime = runtime
        self.gate = gate
        self.trace = trace
        self._tools: dict[str, ToolSpec] = {}
        # One call at a time per session: a model's parallel tool calls on the same page would race
        # (click before navigate settles). Different sessions still run concurrently.
        self._session_locks: dict[str, asyncio.Lock] = {}

    # -- registration ------------------------------------------------------
    def add(self, spec: ToolSpec) -> None:
        self._tools[spec.wire_name] = spec

    def remove_prefix(self, prefix: str) -> None:
        for key in [k for k, v in self._tools.items() if v.name.startswith(prefix)]:
            del self._tools[key]

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name) or self._tools.get(name.replace(".", "_"))

    def list(self, layers: Optional[set[str]] = None) -> list[ToolSpec]:
        specs = sorted(self._tools.values(), key=lambda s: (s.layer, s.name))
        return [s for s in specs if layers is None or s.layer in layers]

    # -- invocation --------------------------------------------------------
    async def call(self, name: str, args: dict[str, Any] | None, *, session_id: str, actor: str = "agent") -> ToolResult:
        if actor == "recipe":  # nested call from inside a running L3 recipe: lock already held
            return await self._call(name, args, session_id=session_id, actor=actor)
        lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            return await self._call(name, args, session_id=session_id, actor=actor)

    async def _call(self, name: str, args: dict[str, Any] | None, *, session_id: str, actor: str) -> ToolResult:
        args = dict(args or {})
        spec = self.get(name)
        if spec is None:
            raise ToolError("unknown_tool", f"no such tool: {name}")
        missing = [k for k in spec.input_schema.get("required", []) if k not in args]
        if missing:
            raise ToolError("invalid_arguments", f"missing required argument(s): {', '.join(missing)}")

        ctx = ToolContext(session_id=session_id, runtime=self.runtime, actor=actor, registry=self)
        risk, reason = spec.risk, ""
        started = time.monotonic()
        url_before = await self.runtime.current_url(session_id)
        decision = None
        try:
            if spec.assess is not None:
                assessed, reason = await spec.assess(ctx, args)
                risk = max(risk, assessed)
            decision = await self.gate.check(ctx, spec, risk, reason, args)
            if not decision.allowed:
                raise ToolError("denied", f"policy denied {spec.name} (risk={risk.label}): {decision.reason}",
                                risk=risk.label)
            result = await spec.handler(ctx, args)
        except ToolError as e:
            await self._record(ctx, spec, args, risk, decision, url_before, started, error=e)
            raise
        except Exception as e:  # surface as a model-visible error, keep the daemon alive
            err = ToolError("tool_failed", f"{type(e).__name__}: {e}")
            await self._record(ctx, spec, args, risk, decision, url_before, started, error=err)
            raise err from e
        await self._record(ctx, spec, args, risk, decision, url_before, started, result=result)
        return result

    async def _record(self, ctx, spec, args, risk, decision, url_before, started, result=None, error=None):
        redacted = redact_args(spec, args)
        self.trace.record(
            session=ctx.session_id,
            actor=ctx.actor,
            tool=spec.name,
            layer=spec.layer,
            args=redacted,
            risk=risk.label,
            decision=None if decision is None else decision.to_dict(),
            tab=ctx.notes.get("tab"),
            url_before=url_before,
            url_after=await self.runtime.current_url(ctx.session_id),
            snapshot_hash=ctx.notes.get("snapshot_hash"),
            ok=error is None,
            result=None if result is None else result.summary(),
            artifacts=None if result is None else result.artifacts or None,
            error=None if error is None else error.to_dict()["error"],
            duration_ms=int((time.monotonic() - started) * 1000),
        )
