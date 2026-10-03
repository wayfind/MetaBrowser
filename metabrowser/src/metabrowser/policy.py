"""Browser-side risk gate.

metacodes treats every MCP tool as one permission category, which is too coarse
for "click Pay" vs "click Next". The gate decides per call from the effective
risk (base risk escalated by assess(), e.g. via site-pack risk patterns):

    allow  -> run
    ask    -> route to an approver (side panel); no approver -> approval_required error
    deny   -> refuse
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from .tools.base import Risk, ToolContext, ToolError, ToolSpec, redact_args

DEFAULT_RULES: dict[Risk, str] = {
    Risk.READ: "allow",
    Risk.NAVIGATE: "allow",
    Risk.INPUT: "allow",
    Risk.SUBMIT: "ask",
    Risk.IRREVERSIBLE: "ask",
    Risk.SYSTEM: "deny",
}


@dataclass
class Decision:
    allowed: bool
    verdict: str            # allow | deny
    source: str             # rule | session_grant | approver | no_approver
    reason: str = ""
    approver: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = {"verdict": self.verdict, "source": self.source}
        if self.reason:
            d["reason"] = self.reason
        if self.approver:
            d["approver"] = self.approver
        return d


@dataclass
class ApprovalRequest:
    session: str
    tool: str
    risk: str
    reason: str
    args: dict[str, Any]
    url: Optional[str]


# approver(request) -> "allow_once" | "allow_session" | "deny"
Approver = Callable[[ApprovalRequest], Awaitable[str]]


@dataclass
class PolicyGate:
    rules: dict[Risk, str] = field(default_factory=lambda: dict(DEFAULT_RULES))
    approver: Optional[Approver] = None
    # (session, tool) pairs granted "allow_session"
    _grants: set[tuple[str, str]] = field(default_factory=set)

    @classmethod
    def from_file(cls, path: Path) -> "PolicyGate":
        """{"rules": {"submit": "allow", "system": "ask"}} overrides defaults."""
        gate = cls()
        if path.exists():
            for risk, verdict in json.loads(path.read_text()).get("rules", {}).items():
                gate.set_rule(risk, verdict)
        return gate

    def set_rule(self, risk: "str | Risk", verdict: str) -> None:
        if verdict not in ("allow", "ask", "deny"):
            raise ValueError(f"invalid verdict {verdict!r}")
        self.rules[Risk.parse(risk)] = verdict

    async def check(self, ctx: ToolContext, spec: ToolSpec, risk: Risk, reason: str, args: dict[str, Any]) -> Decision:
        verdict = self.rules.get(risk, "ask")
        if verdict == "allow":
            return Decision(True, "allow", "rule")
        if verdict == "deny":
            return Decision(False, "deny", "rule", reason or f"{risk.label} actions are disabled")
        if ctx.actor == "user":  # the human clicked it in the side panel themselves
            return Decision(True, "allow", "user_initiated")
        if (ctx.session_id, spec.name) in self._grants and risk < Risk.IRREVERSIBLE:
            return Decision(True, "allow", "session_grant")
        if self.approver is None:
            raise ToolError(
                "approval_required",
                f"{spec.name} is a {risk.label} action and needs human approval"
                + (f" ({reason})" if reason else "")
                + ". Ask the user to confirm, or open the MetaBrowser side panel.",
                risk=risk.label,
            )
        req = ApprovalRequest(ctx.session_id, spec.name, risk.label, reason,
                              redact_args(spec, args),
                              await ctx.runtime.current_url(ctx.session_id))
        try:
            answer = await self.approver(req)
        except asyncio.TimeoutError:
            return Decision(False, "deny", "approver", "approval timed out")
        if answer == "allow_session":
            # Irreversible actions are never remembered: each one is confirmed.
            self._grants.add((ctx.session_id, spec.name))
            return Decision(True, "allow", "approver", reason, approver="user")
        if answer == "allow_once":
            return Decision(True, "allow", "approver", reason, approver="user")
        return Decision(False, "deny", "approver", "rejected by user", approver="user")
