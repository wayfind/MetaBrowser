"""Embedded metacodes agent loop (AgentCore C ABI) inside the MetaBrowser daemon.

Threading model (AgentCore contract: synchronous Runs, callbacks without thread
affinity, concurrent Host tool calls):

  asyncio loop (daemon)     owns Playwright, the ToolRegistry, HTTP/SSE
  run threads (1/session)   call session.run_input, which blocks for the whole Run
  AgentCore worker threads  invoke Host tool execute / on_event / on_ui_request

Host tool callbacks hop onto the asyncio loop with run_coroutine_threadsafe
and block for the result, so every agent browser action goes through the same
ToolRegistry pipeline (PolicyGate + TraceRecorder) as MCP clients. The loop
thread never calls run_input, so there is no deadlock.
"""

from __future__ import annotations

import asyncio
import ctypes as C
import itertools
import json
import logging
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .. import paths
from ..tools.base import ToolError, ToolRegistry
from . import abi

log = logging.getLogger("metabrowser.agent")

BUILTIN_TOOLS = ("Read", "Write", "Edit", "Glob", "Grep", "Bash", "BashOutput", "KillShell", "WebFetch",
                 "AskUserQuestion")
TOOL_TIMEOUT_S = 900


@dataclass
class AgentConfig:
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-6"
    base_url: str = ""          # full endpoint (e.g. https://host/v1/messages); empty = provider default
    api_key: str = ""
    permission_mode: str = "default"
    shell: str = "sandboxed"
    max_turns: int = 80
    workspace_root: Path = field(default_factory=lambda: paths.workspace_dir())
    workspace_home: Path = field(default_factory=lambda: paths.home() / "agent")
    builtin_tools: tuple[str, ...] = BUILTIN_TOOLS

    @classmethod
    def load(cls) -> "AgentConfig":
        """~/.metabrowser/config.json {"agent": {...}} overlaid by environment variables.
        Secrets are only read from the environment (api_key_env), never stored in config."""
        cfg = cls()
        try:
            data = json.loads((paths.home() / "config.json").read_text()).get("agent", {})
        except (OSError, json.JSONDecodeError):
            data = {}
        for key in ("provider", "model", "base_url", "permission_mode", "shell", "max_turns"):
            if key in data:
                setattr(cfg, key, data[key])
        env = os.environ
        cfg.provider = env.get("METABROWSER_AGENT_PROVIDER", cfg.provider)
        cfg.model = env.get("METABROWSER_AGENT_MODEL", cfg.model)
        cfg.base_url = env.get("METABROWSER_AGENT_BASE_URL", cfg.base_url)
        key_envs = [data.get("api_key_env")] if data.get("api_key_env") else []
        key_envs += ["METABROWSER_API_KEY"] + {
            "anthropic": ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"],
            "openai": ["OPENAI_API_KEY"], "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"]}.get(cfg.provider, [])
        cfg.api_key = next((env[k] for k in key_envs if env.get(k)), "")
        if not cfg.base_url and cfg.provider == "anthropic" and env.get("ANTHROPIC_BASE_URL"):
            base = env["ANTHROPIC_BASE_URL"].rstrip("/")
            cfg.base_url = base if base.endswith("/v1/messages") else base + "/v1/messages"
        return cfg

    def public(self) -> dict[str, Any]:
        return {"provider": self.provider, "model": self.model, "base_url": self.base_url or "(provider default)",
                "api_key": "set" if self.api_key else "missing", "permission_mode": self.permission_mode,
                "shell": self.shell}


class _Arena:
    """Keeps borrowed input bytes alive for the duration of one ABI call."""

    def __init__(self):
        self._keep: list[Any] = []

    def view(self, data: "bytes | str | None") -> abi.BytesView:
        if not data:
            return abi.BytesView()
        if isinstance(data, str):
            data = data.encode()
        buf = C.create_string_buffer(data, len(data))
        self._keep.append(buf)
        return abi.BytesView(C.cast(buf, C.POINTER(C.c_uint8)), len(data))

    def views(self, items: list[str]):
        arr = (abi.BytesView * max(1, len(items)))(*[self.view(i) for i in items])
        self._keep.append(arr)
        return arr, len(items)

    def keep(self, obj):
        self._keep.append(obj)
        return obj


class _HostBuffers:
    """Host-owned output buffers (tool results, UI responses) until AgentCore releases them."""

    def __init__(self):
        self._live: dict[int, Any] = {}
        self._lock = threading.Lock()

    def fill(self, out: Any, data: bytes) -> None:
        if not data:
            out.contents.ptr, out.contents.len = None, 0
            return
        buf = C.create_string_buffer(data, len(data))
        with self._lock:
            self._live[C.addressof(buf)] = buf
        out.contents.ptr = C.cast(buf, C.POINTER(C.c_uint8))
        out.contents.len = len(data)

    def release(self, ob: Any) -> None:
        addr = C.cast(ob.contents.ptr, C.c_void_p).value
        if addr:
            with self._lock:
                self._live.pop(addr, None)
        ob.contents.ptr, ob.contents.len = None, 0


def _bytes(view: abi.BytesView) -> bytes:
    return C.string_at(view.ptr, view.len) if view.len else b""


def _diag(api: abi.Api, d: abi.OwnedBytes) -> str:
    if not d.len:
        return ""
    text = C.string_at(d.ptr, d.len).decode("utf-8", "replace")
    api.buffer_release(C.byref(d))
    return text


class AgentCoreError(RuntimeError):
    def __init__(self, op: str, status: int, diagnostic: str = ""):
        super().__init__(f"{op}: {abi.STATUS_NAMES.get(status, status)}{' — ' + diagnostic if diagnostic else ''}")
        self.status = status


@dataclass
class AgentSession:
    id: str                       # UI id (stable, used in URLs)
    label: str
    handle: int
    core_session_id: str = ""
    run_id: int = 0
    running: bool = False
    queue: deque = field(default_factory=deque)
    journal: list = field(default_factory=list)   # [(seq, event dict)]
    seq: itertools.count = field(default_factory=lambda: itertools.count(1))
    created: float = field(default_factory=time.time)


# ui_handler(session_ui_id, request dict) -> response dict | None (None = unavailable). Called on AgentCore threads.
UiHandler = Callable[[str, dict], Optional[dict]]


class AgentHost:
    def __init__(self, registry: ToolRegistry, loop: asyncio.AbstractEventLoop, config: Optional[AgentConfig] = None,
                 ui_handler: Optional[UiHandler] = None, skill_dirs: Optional[list[tuple[str, Path]]] = None,
                 library: Optional[Path] = None):
        self.registry = registry
        self.loop = loop
        self.config = config or AgentConfig.load()
        self.ui_handler = ui_handler
        self.skill_dirs = skill_dirs or []
        self.lib, self.api = abi.load(library)
        self.runtime: Optional[int] = None
        self.sessions: dict[str, AgentSession] = {}
        self._by_handle: dict[int, AgentSession] = {}
        self._labels = itertools.count(1)
        self._buffers = _HostBuffers()
        self._listeners: list[Callable[[str, int, dict], None]] = []
        self._lock = threading.Lock()
        self._tool_names: list[str] = []
        self._keep: list[Any] = []   # ctypes callbacks + runtime config buffers (must outlive Runtime)
        self.skill_descriptor: dict[str, Any] = {}
        self.preamble = load_preamble()
        self._builtins: list[str] = []
        self._rg_env()

    # -- runtime ------------------------------------------------------------------
    def _rg_env(self) -> None:
        if "RG_BIN" not in os.environ:
            for cand in (paths.home() / "agentcore" / "bin" / "rg",):
                if cand.is_file():
                    os.environ["RG_BIN"] = str(cand)

    def start(self) -> None:
        arena = _Arena()
        specs = self.registry.list()
        self._tool_names = [s.wire_name for s in specs]
        execute = abi.HostExecuteFn(self._execute)
        release = abi.HostReleaseFn(lambda _ctx, ob: self._buffers.release(ob))
        self._keep += [execute, release, arena]
        tools = (abi.HostTool * len(specs))()
        for i, s in enumerate(specs):
            d = s.describe()
            tools[i] = abi.sized(abi.HostTool, ctx=C.c_void_p(i + 1), name=arena.view(d["name"]),
                                 description=arena.view(d["description"]),
                                 input_schema_json=arena.view(json.dumps(d["inputSchema"])),
                                 execute=execute, release_result=release)
        arena.keep(tools)
        builtins = [t for t in self.config.builtin_tools if t not in ("Glob", "Grep") or os.environ.get("RG_BIN")]
        barr, bcount = arena.views(builtins)
        cfg = abi.sized(abi.RuntimeConfig, builtin_tools=barr, builtin_tool_count=bcount,
                        host_tools=tools, host_tool_count=len(specs))
        out, d = C.c_void_p(), abi.OwnedBytes()
        st = self.api.runtime.contents.create(C.byref(cfg), None, C.byref(out), C.byref(d))
        if st != abi.STATUS_OK:
            raise AgentCoreError("runtime.create", st, _diag(self.api, d))
        self.runtime = out.value
        self._builtins = builtins
        self.refresh_skills()
        log.info("AgentCore runtime: %d host tools, builtins=%s", len(specs), builtins)

    def stop(self) -> None:
        for sid in list(self.sessions):
            self.destroy_session(sid)
        if self.runtime:
            d = abi.OwnedBytes()
            self.api.runtime.contents.destroy(self.runtime, C.byref(d))
            _diag(self.api, d)
            self.runtime = None

    # -- host tool bridge -------------------------------------------------------------
    def _execute(self, ctx, run_ctx, args_view, out) -> int:
        try:
            name = self._tool_names[(ctx or 0) - 1]
            sess = self._by_handle.get(run_ctx.contents.session or 0)
            sid = sess.id if sess else _bytes(run_ctx.contents.session_id).decode() or "agent"
            args = json.loads(_bytes(args_view) or b"{}")
            fut = asyncio.run_coroutine_threadsafe(
                self.registry.call(name, args, session_id=sid, actor="agent"), self.loop)
            result = fut.result(TOOL_TIMEOUT_S)
            if result.image_b64:
                # Exact image envelope: metacodes serializes it as a native image block for every provider.
                payload = json.dumps({"type": "image", "media_type": result.image_mime, "data": result.image_b64})
            else:
                payload = result.text or "ok"
            self._buffers.fill(out, payload.encode())
            return abi.HOST_OK
        except ToolError as e:
            # AgentCore wraps this detail in its own error envelope: keep it plain text, not nested JSON.
            detail = f"[{e.code}] {e.message}"
            if e.details:
                detail += " " + json.dumps(e.details, ensure_ascii=False)
            self._buffers.fill(out, detail.encode())
            return abi.HOST_FAILED
        except Exception as e:  # never let an exception cross the C boundary
            self._buffers.fill(out, f"{type(e).__name__}: {e}".encode())
            return abi.HOST_FAILED

    # -- sessions -------------------------------------------------------------------------
    def _skill_catalog(self, arena: _Arena):
        """Resolve a catalog from site-pack/builtin skill dirs; grant every valid skill (default-deny ABI)."""
        sources = [(sid, p) for sid, p in self.skill_dirs if Path(p).is_dir()]
        if not sources:
            return None, None
        srcs = (abi.SkillSource * len(sources))()
        for i, (sid, p) in enumerate(sources):
            srcs[i] = abi.sized(abi.SkillSource, scope_code=abi.SKILL_SOURCE_WORKSPACE,
                                root=arena.view(str(Path(p).resolve())), source_instance_id=arena.view(sid))
        arena.keep(srcs)
        q = abi.sized(abi.SkillCatalogQuery, workspace_root=arena.view(str(self.config.workspace_root)),
                      workspace_home=arena.view(str(self.config.workspace_home)),
                      additional_sources=srcs, additional_source_count=len(sources))
        cat, desc, d = C.c_void_p(), abi.OwnedBytes(), abi.OwnedBytes()
        st = self.api.skill.contents.resolve_catalog(self.runtime, C.byref(q), C.byref(cat), C.byref(desc), C.byref(d))
        if st != abi.STATUS_OK:
            log.warning("skill catalog unavailable: %s", AgentCoreError("skill.resolve_catalog", st, _diag(self.api, d)))
            return None, None
        descriptor = json.loads(_diag(self.api, desc) or "{}")
        ids = [s["skill_id"] for s in descriptor.get("skills", [])]
        arr, n = arena.views(ids)
        policy = arena.keep(abi.sized(abi.SkillPolicy, granted_skill_ids=arr, granted_skill_id_count=n))
        self.skill_descriptor = descriptor
        return cat, policy

    def refresh_skills(self) -> dict[str, Any]:
        """Resolve the catalog once so status/UI can list skills before any session exists."""
        for p in (self.config.workspace_root, self.config.workspace_home):
            paths.ensure(Path(p))
        catalog, _policy = self._skill_catalog(_Arena())
        if catalog is not None:
            d = abi.OwnedBytes()
            self.api.skill.contents.release_catalog(catalog, C.byref(d))
            _diag(self.api, d)
        return self.skill_descriptor

    def create_session(self, label: Optional[str] = None) -> AgentSession:
        if not self.runtime:
            raise RuntimeError("agent runtime not started")
        c = self.config
        for p in (c.workspace_root, c.workspace_home, paths.outputs_dir()):
            paths.ensure(Path(p))
        arena = _Arena()
        allowed = list(self._builtins) + self._tool_names
        aarr, acount = arena.views(allowed)
        # Browser tools carry their own risk gate (PolicyGate); don't double-prompt in AgentCore.
        # Claude-Code rule syntax: `//abs/path` is filesystem-absolute (a single `/` is project-relative).
        outputs = abs_rule_path(paths.outputs_dir())
        allow_rules = self._tool_names + ["Read", "Glob", "Grep", f"Write({outputs}/**)", f"Edit({outputs}/**)"]
        # deny > ask > allow: a bare "Write" ask rule would override the outputs allow rule; writes
        # elsewhere already ask through the default permission mode.
        ask_rules = ["Bash", "WebFetch"]
        deny_rules = ["Read(~/.ssh/**)", f"Read({abs_rule_path(paths.profiles_dir())}/**)",
                      f"Read({abs_rule_path(paths.daemon_file())})", f"Edit({abs_rule_path(paths.home())}/**)"]
        al, aln = arena.views(allow_rules)
        ak, akn = arena.views(ask_rules)
        dn, dnn = arena.views(deny_rules)
        rules = arena.keep(abi.sized(abi.PermissionRuleSet, allow=al, allow_count=aln, ask=ak, ask_count=akn,
                                     deny=dn, deny_count=dnn))
        catalog, policy = self._skill_catalog(arena)
        host = arena.keep(abi.sized(
            abi.SessionHostConfig, provider_kind_code=abi.PROVIDERS[c.provider],
            permission_mode_code=abi.PERMISSION_MODES[c.permission_mode], shell_policy_code=abi.SHELL_POLICIES[c.shell],
            api_key=arena.view(c.api_key), base_url=arena.view(c.base_url),
            workspace_root=arena.view(str(Path(c.workspace_root).resolve())),
            workspace_home=arena.view(str(Path(c.workspace_home).resolve())),
            allowed_tools=aarr, allowed_tool_count=acount, skill_catalog=catalog,
            skill_policy=C.pointer(policy) if policy is not None else None, permission_rules=C.pointer(rules),
            run_journal_mode_code=abi.RUN_JOURNAL_DURABLE_WORKSPACE))
        create = abi.sized(abi.SessionCreateConfig, host=C.pointer(host), model=arena.view(c.model))
        callbacks = abi.sized(abi.SessionCallbacks, ctx=None, on_event=self._on_event_cb,
                              on_ui_request=self._on_ui_cb, release_response=self._release_ui_cb)
        out, d = C.c_void_p(), abi.OwnedBytes()
        st = self.api.session.contents.create(self.runtime, C.byref(create), C.byref(callbacks), C.byref(out), C.byref(d))
        if catalog is not None:
            d2 = abi.OwnedBytes()
            self.api.skill.contents.release_catalog(catalog, C.byref(d2))
            _diag(self.api, d2)
        if st != abi.STATUS_OK:
            raise AgentCoreError("session.create", st, _diag(self.api, d))
        sess = AgentSession(id=uuid.uuid4().hex[:12], label=label or f"Session {next(self._labels)}", handle=out.value)
        sess.core_session_id = self._describe(sess).get("session_id", "")
        with self._lock:
            self.sessions[sess.id] = sess
            self._by_handle[sess.handle] = sess
        self._emit(sess, {"session_created": {"label": sess.label, "model": c.model}})
        return sess

    def _describe(self, sess: AgentSession) -> dict[str, Any]:
        desc, d = abi.OwnedBytes(), abi.OwnedBytes()
        st = self.api.session_control.contents.describe(sess.handle, C.byref(desc), C.byref(d))
        _diag(self.api, d)
        if st != abi.STATUS_OK:
            return {}
        try:
            return json.loads(_diag(self.api, desc))
        except json.JSONDecodeError:
            return {}

    def destroy_session(self, sid: str) -> None:
        sess = self.sessions.pop(sid, None)
        if sess is None:
            return
        if sess.running:
            self.abort(sid)
            while sess.running:
                time.sleep(0.05)
        d = abi.OwnedBytes()
        self.api.session.contents.destroy(sess.handle, C.byref(d))
        _diag(self.api, d)
        self._by_handle.pop(sess.handle, None)
        asyncio.run_coroutine_threadsafe(self._release_tabs(sid), self.loop)

    async def _release_tabs(self, sid: str) -> None:
        self.registry.runtime.release(sid)

    # -- runs -------------------------------------------------------------------------------
    def send(self, sid: str, text: str) -> str:
        """Queue user text; starts a Run thread if idle. Returns 'started' or 'queued'."""
        sess = self.sessions[sid]
        with self._lock:
            sess.queue.append(text)
            if sess.running:
                return "queued"
            sess.running = True
        threading.Thread(target=self._run_loop, args=(sess,), name=f"agent-run-{sid}", daemon=True).start()
        return "started"

    def _run_loop(self, sess: AgentSession) -> None:
        while True:
            with self._lock:
                if not sess.queue or sess.id not in self.sessions:
                    sess.running = False
                    return
                text = sess.queue.popleft()
            self._emit(sess, {"user_message": text})
            sess.run_id += 1
            if sess.run_id == 1 and self.preamble:
                # Revision 17 has no system-prompt slot (metask-ai/metacodes#184): the browser operating contract rides on the first input.
                text = f"<metabrowser-context>\n{self.preamble}\n</metabrowser-context>\n\n{text}"
            arena = _Arena()
            inp = abi.sized(abi.RunInput, kind_code=abi.RUN_INPUT_TEXT, text=arena.view(text))
            opts = abi.sized(abi.RunOptions, max_turns=int(self.config.max_turns))
            res, d = abi.sized(abi.RunResult), abi.OwnedBytes()
            started = time.time()
            st = self.api.session.contents.run_input(sess.handle, sess.run_id, C.byref(inp), C.byref(opts),
                                                     C.byref(res), C.byref(d))
            diag = _diag(self.api, d)
            done = {"run_id": sess.run_id, "status": abi.STATUS_NAMES.get(st, st),
                    "stop_reason": abi.STOP_REASONS.get(res.stop_reason_code, res.stop_reason_code),
                    "turns": res.turns, "tool_calls": res.tool_calls, "elapsed_ms": int((time.time() - started) * 1000)}
            if diag:
                done["diagnostic"] = diag
            self._emit(sess, {"run_done": done})
            self.registry.trace.note(sess.id, "agent_run", **done)

    def abort(self, sid: str) -> None:
        sess = self.sessions.get(sid)
        if sess is None or not sess.running or not sess.run_id:
            return
        sess.queue.clear()
        d = abi.OwnedBytes()
        self.api.session.contents.abort(sess.handle, sess.run_id, abi.ABORT_USER_REQUEST, C.byref(d))
        _diag(self.api, d)

    # -- callbacks -----------------------------------------------------------------------------
    def subscribe(self, cb: Callable[[str, int, dict], None]) -> None:
        self._listeners.append(cb)

    def _emit(self, sess: AgentSession, event: dict) -> None:
        seq = next(sess.seq)
        sess.journal.append((seq, event))
        if len(sess.journal) > 5000:
            del sess.journal[:1000]
        for cb in list(self._listeners):
            try:
                cb(sess.id, seq, event)
            except Exception:
                log.exception("event listener failed")

    def _session_from_ctx(self, run_ctx) -> Optional[AgentSession]:
        return self._by_handle.get(run_ctx.contents.session or 0)

    def _on_event(self, _ctx, run_ctx, view) -> int:
        try:
            sess = self._session_from_ctx(run_ctx)
            if sess is not None:
                self._emit(sess, {"core_event": json.loads(_bytes(view))})
        except Exception:
            log.exception("on_event failed")
        return abi.EVENT_CONTINUE  # observation failures must not poison the Session

    def _on_ui(self, _ctx, run_ctx, view, out) -> int:
        try:
            sess = self._session_from_ctx(run_ctx)
            request = json.loads(_bytes(view))
            if sess is None or self.ui_handler is None:
                return abi.UI_UNAVAILABLE
            self._emit(sess, {"ui_request": request})
            response = self.ui_handler(sess.id, request)
            self._emit(sess, {"ui_request_done": {"answered": response is not None}})
            if response is None:
                return abi.UI_UNAVAILABLE
            self._buffers.fill(out, json.dumps(response).encode())
            return abi.UI_ANSWERED
        except Exception:
            log.exception("on_ui_request failed")
            return abi.UI_UNAVAILABLE

    @property
    def _on_event_cb(self):
        return self._cb("_ev", abi.OnEventFn, self._on_event)

    @property
    def _on_ui_cb(self):
        return self._cb("_ui", abi.OnUiRequestFn, self._on_ui)

    @property
    def _release_ui_cb(self):
        return self._cb("_rel", abi.ReleaseResponseFn, lambda _ctx, ob: self._buffers.release(ob))

    def _cb(self, attr: str, ftype, fn):
        if not hasattr(self, attr):
            setattr(self, attr, ftype(fn))
        return getattr(self, attr)

    # -- views -------------------------------------------------------------------------------
    def list_sessions(self) -> list[dict[str, Any]]:
        return [{"id": s.id, "label": s.label, "running": s.running, "queued": len(s.queue),
                 "core_session_id": s.core_session_id} for s in self.sessions.values()]

    def events_since(self, sid: str, since: int = 0) -> list[tuple[int, dict]]:
        sess = self.sessions.get(sid)
        return [] if sess is None else [(n, e) for n, e in sess.journal if n > since]


def abs_rule_path(path: Path) -> str:
    """Absolute path in metacodes permission-rule syntax (`//` prefix)."""
    return "/" + str(Path(path).expanduser().resolve())


def load_preamble() -> str:
    """Body of the builtin browser-operator skill (frontmatter stripped) + environment facts."""
    skill = Path(__file__).resolve().parents[1] / "skills" / "browser-operator" / "SKILL.md"
    try:
        body = skill.read_text(encoding="utf-8").split("---", 2)[-1].strip()
    except OSError:
        body = ""
    body = body.replace("`browser__", "`").replace("browser__", "")  # embedded: tools are native, no MCP prefix
    return (f"You are the MetaBrowser agent. You control the user's browser through the browser tools below; "
            f"deliverables go to {paths.outputs_dir()}.\n\n{body}")


def permission_response(request: dict, choice: str) -> dict:
    """Build the exact Revision 17 permission response: echo request_id and policy_generation;
    session choices also echo candidate.rule_id. The candidate's scope decides what a session
    answer covers: `exact_arguments` (same call) or `file_target` (any later Write/Edit of
    candidate.target)."""
    resp = {"permission": choice, "request_id": request["request_id"],
            "policy_generation": request["policy_generation"]}
    if choice.endswith("_session") and request.get("candidate"):
        resp["rule_id"] = request["candidate"]["rule_id"]
    return resp
