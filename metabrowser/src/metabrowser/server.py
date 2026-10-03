"""The MetaBrowser daemon: one browser, one embedded agent runtime, many clients.

  POST /mcp                               MCP Streamable HTTP (JSON) — other agents / `metabrowser mcp` bridge
  GET  /api/tools | /api/tabs             side panel / scripts
  POST /api/call                          run a tool as the user (actor=user)
  GET  /api/events?token=                 SSE: trace events, browser approvals, agent events + requests
  POST /api/approvals/<id>                browser PolicyGate decision {"answer": allow_once|allow_session|deny}
  GET  /api/agent/status                  embedded metacodes AgentCore state + config (no secrets)
  GET|POST /api/agent/sessions            list / create agent sessions
  DELETE /api/agent/sessions/<sid>
  POST /api/agent/sessions/<sid>/message  {"text"} (queued while a Run is active)
  POST /api/agent/sessions/<sid>/interrupt
  GET  /api/agent/sessions/<sid>/history?since=N
  POST /api/agent/requests/<id>           AgentCore UI answer {"choice"} | {"answers": [...]}

Security: binds 127.0.0.1, bearer token (~/.metabrowser/daemon.json, 0600, also
baked into the side-panel extension copy), and rejects browser Origins other
than our extension — pages open in this same browser cannot drive it.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import secrets
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from aiohttp import web

from . import paths
from .mcp import McpHandler
from .policy import ApprovalRequest
from .stack import Stack
from .tools.base import ToolError, ToolResult, schema

log = logging.getLogger("metabrowser.daemon")
APPROVAL_TIMEOUT = 180
AGENT_UI_TIMEOUT = 300


class Daemon:
    def __init__(self, stack: Stack, token: str, *, enable_agent: bool = True, agent_library: Optional[Path] = None):
        self.stack = stack
        self.token = token
        self.enable_agent = enable_agent
        self.agent_library = agent_library
        self.agent = None               # AgentHost once started
        self.agent_error: Optional[str] = None if enable_agent else "disabled (--no-agent)"
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.subscribers: set[asyncio.Queue] = set()
        self.approvals: dict[str, tuple[ApprovalRequest, asyncio.Future]] = {}
        self.agent_requests: dict[str, tuple[str, dict, concurrent.futures.Future]] = {}
        self.mcp = McpHandler(stack.registry, extra_tools=self._extra_tools())
        stack.gate.approver = self._approve
        stack.trace.subscribe(lambda ev: self._broadcast_threadsafe({"kind": "trace", "event": ev}))

    # -- embedded agent ------------------------------------------------------------------
    def start_agent(self) -> None:
        """Create the AgentCore runtime (blocking ABI call; run in an executor)."""
        if not self.enable_agent:
            return
        from .agentcore import AgentConfig, AgentCoreUnavailable, AgentHost

        try:
            skill_dirs = [("builtin", Path(__file__).with_name("skills"))]
            skill_dirs += [(f"site.{p.id}", p.root / "skills") for p in self.stack.packs]
            host = AgentHost(self.stack.registry, self.loop, AgentConfig.load(), ui_handler=self._agent_ui,
                             skill_dirs=skill_dirs, library=self.agent_library)
            host.start()
            host.subscribe(self._on_agent_event)
            self.agent, self.agent_error = host, None
            if not host.config.api_key:
                self.agent_error = ("no model API key: set METABROWSER_API_KEY (or ANTHROPIC_API_KEY / "
                                    "OPENAI_API_KEY) and restart; see `metabrowser agent status`")
        except AgentCoreUnavailable as e:
            self.agent_error = str(e)
        except Exception as e:
            log.exception("agent runtime failed")
            self.agent_error = f"{type(e).__name__}: {e}"

    def _on_agent_event(self, sid: str, seq: int, event: dict) -> None:
        self._broadcast_threadsafe({"kind": "agent_event", "session": sid, "seq": seq, "event": event})

    def _agent_ui(self, sid: str, request: dict) -> Optional[dict]:
        """AgentCore on_ui_request (runs on an AgentCore thread; blocks until the panel answers)."""
        if not self.subscribers:
            return None  # UI_UNAVAILABLE: metacodes renders it as an ordinary deny
        aid = uuid.uuid4().hex[:12]
        fut: concurrent.futures.Future = concurrent.futures.Future()
        self.agent_requests[aid] = (sid, request, fut)
        self._broadcast_threadsafe({"kind": "agent_request", "id": aid, "session": sid, "request": request})
        try:
            return fut.result(AGENT_UI_TIMEOUT)
        except concurrent.futures.TimeoutError:
            return None
        finally:
            self.agent_requests.pop(aid, None)
            self._broadcast_threadsafe({"kind": "agent_request_done", "id": aid})

    def _extra_tools(self) -> dict:
        desc = {"name": "agent_run_task",
                "description": "[L4] Delegate a whole browser task to MetaBrowser's embedded metacodes agent "
                               "(site skills, approvals in the side panel). Returns the agent's final answer.",
                "inputSchema": schema({"task": {"type": "string"},
                                       "session": {"type": "string", "description": "existing agent session id"}},
                                      ["task"])}

        async def run(args, _session):
            if self.agent is None:
                raise ToolError("agent_unavailable", self.agent_error or "agent not started")
            loop = asyncio.get_running_loop()
            sid = args.get("session")
            if not sid or sid not in self.agent.sessions:
                sid = (await loop.run_in_executor(None, self.agent.create_session, "MCP task")).id
            done = asyncio.Event()
            chunks: list[str] = []
            start_seq = len(self.agent.sessions[sid].journal)

            def listen(s, seq, ev):
                if s != sid or seq <= start_seq:
                    return
                core = ev.get("core_event") or {}
                if isinstance(core.get("text_chunk"), str):
                    chunks.append(core["text_chunk"])
                if "run_done" in ev:
                    loop.call_soon_threadsafe(done.set)

            self.agent.subscribe(listen)
            try:
                self.agent.send(sid, args["task"])
                await asyncio.wait_for(done.wait(), 1800)
            finally:
                self.agent._listeners.remove(listen)
            return ToolResult(text="".join(chunks).strip() or "(no text output)", data={"session": sid})

        return {"agent_run_task": (desc, run)}

    # -- browser approvals (PolicyGate) --------------------------------------------------
    async def _approve(self, req: ApprovalRequest) -> str:
        if not self.subscribers:
            raise ToolError("approval_required",
                            f"{req.tool} ({req.risk}) needs approval and no MetaBrowser side panel is open. "
                            "Ask the user to confirm in chat or open the side panel, then retry.", risk=req.risk)
        aid = uuid.uuid4().hex[:12]
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self.approvals[aid] = (req, fut)
        self._broadcast({"kind": "approval", "id": aid, "request": asdict(req)})
        try:
            answer = await asyncio.wait_for(fut, APPROVAL_TIMEOUT)
        finally:
            self.approvals.pop(aid, None)
            self._broadcast({"kind": "approval_done", "id": aid})
        self.stack.trace.note(req.session, "approval", tool=req.tool, risk=req.risk, answer=answer)
        return answer

    def _broadcast(self, msg: dict[str, Any]) -> None:
        for q in list(self.subscribers):
            if q.qsize() < 5000:
                q.put_nowait(msg)

    def _broadcast_threadsafe(self, msg: dict[str, Any]) -> None:
        loop = self.loop
        if loop is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._broadcast(msg)
        else:
            loop.call_soon_threadsafe(self._broadcast, msg)

    # -- http plumbing -------------------------------------------------------------------
    @web.middleware
    async def guard(self, request: web.Request, handler):
        if request.path == "/health":
            return await handler(request)
        origin = request.headers.get("Origin")
        if origin and not origin.startswith("chrome-extension://"):
            return web.json_response({"error": "forbidden origin"}, status=403)
        supplied = request.headers.get("Authorization", "").removeprefix("Bearer ").strip() \
            or request.query.get("token", "")
        if not secrets.compare_digest(supplied, self.token):
            return web.json_response({"error": "unauthorized"}, status=401)
        return await handler(request)

    def app(self) -> web.Application:
        app = web.Application(middlewares=[self.guard], client_max_size=16 * 1024 * 1024)
        app.on_startup.append(self._bind_loop)
        r = app.router
        r.add_get("/health", _health)
        r.add_post("/mcp", self.mcp_post)
        r.add_get("/mcp", _no_stream)
        r.add_get("/api/tools", self.tools)
        r.add_get("/api/tabs", self.tabs)
        r.add_post("/api/call", self.call)
        r.add_get("/api/events", self.events)
        r.add_post("/api/approvals/{aid}", self.answer)
        r.add_get("/api/agent/status", self.agent_status)
        r.add_get("/api/agent/sessions", self.agent_sessions)
        r.add_post("/api/agent/sessions", self.agent_create)
        r.add_delete("/api/agent/sessions/{sid}", self.agent_delete)
        r.add_post("/api/agent/sessions/{sid}/message", self.agent_message)
        r.add_post("/api/agent/sessions/{sid}/interrupt", self.agent_interrupt)
        r.add_get("/api/agent/sessions/{sid}/history", self.agent_history)
        r.add_post("/api/agent/requests/{aid}", self.agent_answer)
        return app

    async def _bind_loop(self, _app):
        self.loop = asyncio.get_running_loop()

    async def mcp_post(self, request: web.Request) -> web.StreamResponse:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"jsonrpc": "2.0", "id": None,
                                      "error": {"code": -32700, "message": "parse error"}}, status=400)
        mcp_session = request.headers.get("Mcp-Session-Id") or uuid.uuid4().hex
        session = request.headers.get("X-MetaBrowser-Session") or f"mcp-{mcp_session[:8]}"
        msgs = body if isinstance(body, list) else [body]
        responses = [r for r in await asyncio.gather(*(self.mcp.handle(m, session) for m in msgs)) if r]
        headers = {"Mcp-Session-Id": mcp_session}
        if not responses:
            return web.Response(status=202, headers=headers)
        return web.json_response(responses if isinstance(body, list) else responses[0], headers=headers,
                                 dumps=lambda o: json.dumps(o, ensure_ascii=False))

    async def tools(self, _request):
        return web.json_response([{**s.describe(), "layer": s.layer, "risk": s.risk.label}
                                  for s in self.stack.registry.list()])

    async def tabs(self, _request):
        return web.json_response(await self.stack.runtime.describe_tabs())

    async def call(self, request):
        body = await request.json()
        try:
            res = await self.stack.registry.call(body["tool"], body.get("args"),
                                                 session_id=body.get("session", "panel"), actor="user")
            return web.json_response({"ok": True, "text": res.text, "image": res.image_b64, "artifacts": res.artifacts})
        except ToolError as e:
            return web.json_response({"ok": False, **e.to_dict()})

    async def events(self, request):
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
        await resp.prepare(request)
        q: asyncio.Queue = asyncio.Queue()
        self.subscribers.add(q)
        try:
            for aid, (req, _) in list(self.approvals.items()):  # replay pending decisions to a new panel
                await resp.write(_sse({"kind": "approval", "id": aid, "request": asdict(req)}))
            for aid, (sid, req, _) in list(self.agent_requests.items()):
                await resp.write(_sse({"kind": "agent_request", "id": aid, "session": sid, "request": req}))
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), 15)
                    await resp.write(_sse(msg))
                except asyncio.TimeoutError:
                    await resp.write(b": keepalive\n\n")
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self.subscribers.discard(q)
        return resp

    async def answer(self, request):
        aid = request.match_info["aid"]
        answer = (await request.json()).get("answer")
        if answer not in ("allow_once", "allow_session", "deny"):
            return web.json_response({"error": "bad answer"}, status=400)
        entry = self.approvals.get(aid)
        if entry is None:
            return web.json_response({"error": "no such approval"}, status=404)
        if not entry[1].done():
            entry[1].set_result(answer)
        return web.json_response({"ok": True})

    # -- agent endpoints -----------------------------------------------------------------------
    def _agent(self):
        if self.agent is None:
            raise web.HTTPServiceUnavailable(text=json.dumps({"error": self.agent_error}),
                                             content_type="application/json")
        return self.agent

    async def agent_status(self, _request):
        info: dict[str, Any] = {"enabled": self.agent is not None, "error": self.agent_error}
        if self.agent is not None:
            info["config"] = self.agent.config.public()
            info["sessions"] = len(self.agent.sessions)
            info["skills"] = [s.get("invocation_name") for s in self.agent.skill_descriptor.get("skills", [])]
        return web.json_response(info)

    async def agent_sessions(self, _request):
        return web.json_response(self.agent.list_sessions() if self.agent else [])

    async def agent_create(self, request):
        agent = self._agent()
        label = (await request.json() if request.can_read_body else {}).get("label")
        try:
            sess = await asyncio.get_running_loop().run_in_executor(None, agent.create_session, label)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)
        return web.json_response({"id": sess.id, "label": sess.label})

    async def agent_delete(self, request):
        await asyncio.get_running_loop().run_in_executor(None, self._agent().destroy_session, request.match_info["sid"])
        return web.json_response({"ok": True})

    async def agent_message(self, request):
        agent, sid = self._agent(), request.match_info["sid"]
        if sid not in agent.sessions:
            raise web.HTTPNotFound()
        return web.json_response({"ok": True, "state": agent.send(sid, (await request.json())["text"])})

    async def agent_interrupt(self, request):
        await asyncio.get_running_loop().run_in_executor(None, self._agent().abort, request.match_info["sid"])
        return web.json_response({"ok": True})

    async def agent_history(self, request):
        since = int(request.query.get("since", "0"))
        events = self._agent().events_since(request.match_info["sid"], since)
        return web.json_response([{"seq": n, "event": e} for n, e in events])

    async def agent_answer(self, request):
        from .agentcore import permission_response

        entry = self.agent_requests.get(request.match_info["aid"])
        if entry is None:
            return web.json_response({"error": "no such request"}, status=404)
        _sid, req, fut = entry
        body = await request.json()
        if req.get("type") == "permission":
            choice = body.get("choice")
            if choice not in req.get("responses", ["allow_once", "deny_once"]):
                return web.json_response({"error": f"choice must be one of {req.get('responses')}"}, status=400)
            response = permission_response(req, choice)
        else:
            response = {"answers": body.get("answers", [])}
        if not fut.done():
            fut.set_result(response)
        return web.json_response({"ok": True})


async def _health(_request):
    return web.json_response({"ok": True})


async def _no_stream(_request):
    """No server-initiated MCP stream: JSON-response mode only."""
    return web.Response(status=405)


def _sse(msg: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(msg, ensure_ascii=False, default=str)}\n\n".encode()


def write_daemon_file(port: int, token: str) -> Path:
    path = paths.daemon_file()
    paths.ensure(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump({"port": port, "token": token, "pid": os.getpid()}, fh)
    return path


def read_daemon_file() -> Optional[dict[str, Any]]:
    try:
        return json.loads(paths.daemon_file().read_text())
    except (OSError, json.JSONDecodeError):
        return None


def stage_extension(port: int, token: str) -> Path:
    """Copy the side-panel extension and bake in the daemon address + token."""
    src = paths.bundled_extension_dir()
    dst = paths.home() / "extension-runtime"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    (dst / "config.json").write_text(json.dumps({"port": port, "token": token}))
    return dst


async def run_daemon(stack: Stack, port: int, token: str, *, enable_agent: bool = True, open_panel: bool = True,
                     agent_library: Optional[Path] = None, ready: Optional[asyncio.Event] = None) -> None:
    from .panel import open_side_panel

    daemon = Daemon(stack, token, enable_agent=enable_agent, agent_library=agent_library)
    runner = web.AppRunner(daemon.app())
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    loop = asyncio.get_running_loop()
    await stack.runtime.start()
    await loop.run_in_executor(None, daemon.start_agent)
    if open_panel:
        await open_side_panel(stack.runtime.context)
    write_daemon_file(port, token)
    stack.trace.note("daemon", "daemon_start", port=port, tools=len(stack.registry.list()),
                     sites=[p.id for p in stack.packs], agent=daemon.agent is not None, agent_error=daemon.agent_error)
    log.info("ready: agent=%s %s", daemon.agent is not None, daemon.agent_error or "")
    if ready is not None:
        ready.set()
    try:
        closed = asyncio.Event()
        stack.runtime.context.on("close", lambda *_: closed.set())  # user quit the browser -> stop daemon
        await closed.wait()
    finally:
        stack.trace.note("daemon", "daemon_stop")
        paths.daemon_file().unlink(missing_ok=True)
        if daemon.agent is not None:
            await loop.run_in_executor(None, daemon.agent.stop)
        await stack.runtime.stop()
        await runner.cleanup()
