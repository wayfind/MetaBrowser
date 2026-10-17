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
from . import abi, profiles

log = logging.getLogger("metabrowser.agent")

BUILTIN_TOOLS = ("Read", "Write", "Edit", "Glob", "Grep", "Bash", "BashOutput", "KillShell", "WebFetch",
                 "AskUserQuestion")
TOOL_TIMEOUT_S = 900


# Provider presets on top of AgentCore's three wire kinds. metask (the metacodes gateway) speaks the
# Anthropic messages protocol with bearer auth, which is AgentCore's default auth scheme.
PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "metask": {"kind": "anthropic", "base_url": "https://napi.metask-ai.com/v1/messages", "model": "claude-sonnet-4-6"},
    "anthropic": {"kind": "anthropic"},
    "openai": {"kind": "openai"},
    "gemini": {"kind": "gemini"},
}
KEY_ENVS = {
    "metask": ["METASK_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"],
    "openai": ["OPENAI_API_KEY"],
    "gemini": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
}
OAUTH_SKEW_S = 120


def metacodes_auth_file() -> Path:
    """Where `metacodes login` keeps credentials: METACODES_AUTH_FILE, else <state root>/auth.json
    (METACODES_HOME or ~/.metacodes; installs with an etc/metacodes/install.json state root should set
    METACODES_HOME or METACODES_AUTH_FILE)."""
    explicit = os.environ.get("METACODES_AUTH_FILE")
    if explicit:
        return Path(explicit).expanduser()
    root = os.environ.get("METACODES_HOME") or str(Path.home() / ".metacodes")
    return Path(root).expanduser() / "auth.json"


def metacodes_credential(now: Optional[float] = None) -> tuple[str, str]:
    """(secret, description) from the user's metacodes login, or ("", reason). Read in-process only:
    never logged or shown. MetaBrowser does not refresh OAuth tokens itself — refresh rotates the
    refresh token and would break the metacodes CLI's login; any metacodes command refreshes it."""
    path = metacodes_auth_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "", f"no metacodes login at {path}"
    if isinstance(data.get("api_key"), str) and data["api_key"].strip():
        return data["api_key"].strip(), "metacodes login (api key)"
    oauth = data.get("oauth") or {}
    token, expires = oauth.get("access_token"), oauth.get("expires_at", 0)
    if not token:
        return "", f"metacodes login at {path} has no credential"
    remaining = int(expires) - int(now if now is not None else time.time())
    if remaining <= OAUTH_SKEW_S:
        return "", "metacodes OAuth token expired: run any metacodes command (e.g. `metacodes doctor`) to refresh it"
    return token, f"metacodes login (oauth, {remaining // 60} min left)"


@dataclass
class AgentConfig:
    provider: str = "anthropic"     # anthropic | openai | gemini | metask
    model: str = "claude-sonnet-4-6"
    base_url: str = ""          # full endpoint (e.g. https://host/v1/messages); empty = provider default
    api_key: str = ""
    credential_source: str = ""
    permission_mode: str = "default"
    shell: str = "sandboxed"
    max_turns: int = 80
    computer_access: bool = False   # Bash/Grep/Glob/Edit/WebFetch for every session (user opt-in)
    workspace_root: Path = field(default_factory=lambda: paths.workspace_dir())
    workspace_home: Path = field(default_factory=lambda: paths.home() / "agent")
    builtin_tools: tuple[str, ...] = BUILTIN_TOOLS

    @property
    def provider_kind(self) -> str:
        return PROVIDER_PRESETS.get(self.provider, {"kind": self.provider})["kind"]

    @classmethod
    def load(cls) -> "AgentConfig":
        """~/.metabrowser/config.json {"agent": {...}} overlaid by environment variables. Secrets come from
        the environment (api_key_env / provider variables) or, for metask, the user's metacodes login —
        never from config files. With nothing configured, a metacodes login selects metask."""
        cfg = cls()
        try:
            data = json.loads((paths.home() / "config.json").read_text()).get("agent", {})
        except (OSError, json.JSONDecodeError):
            data = {}
        env = os.environ
        explicit_provider = data.get("provider") or env.get("METABROWSER_AGENT_PROVIDER")
        for key in ("model", "base_url", "permission_mode", "shell", "max_turns", "computer_access"):
            if key in data:
                setattr(cfg, key, data[key])
        if env.get("METABROWSER_COMPUTER_ACCESS"):
            cfg.computer_access = env["METABROWSER_COMPUTER_ACCESS"] not in ("0", "false", "")
        custom_env = [data["api_key_env"]] if data.get("api_key_env") else []

        def env_key(provider: str) -> tuple[str, str]:
            for k in custom_env + ["METABROWSER_API_KEY"] + KEY_ENVS.get(provider, []):
                if env.get(k):
                    return env[k], f"env {k}"
            return "", ""

        if explicit_provider:
            cfg.provider = explicit_provider
        else:  # auto: a provider key in the environment wins, else the metacodes login (metask)
            cfg.provider = next((p for p in ("anthropic", "openai", "gemini") if env_key(p)[0]), None) or "metask"
        cfg.api_key, cfg.credential_source = env_key(cfg.provider)
        if not cfg.api_key and cfg.provider == "metask":
            cfg.api_key, cfg.credential_source = metacodes_credential()
        preset = PROVIDER_PRESETS.get(cfg.provider, {})
        if "model" not in data and preset.get("model"):
            cfg.model = preset["model"]
        if not cfg.base_url and preset.get("base_url"):
            cfg.base_url = preset["base_url"]
        if not cfg.base_url and cfg.provider == "anthropic" and env.get("ANTHROPIC_BASE_URL"):
            base = env["ANTHROPIC_BASE_URL"].rstrip("/")
            cfg.base_url = base if base.endswith("/v1/messages") else base + "/v1/messages"
        cfg.model = env.get("METABROWSER_AGENT_MODEL", cfg.model)
        cfg.base_url = env.get("METABROWSER_AGENT_BASE_URL", cfg.base_url)
        return cfg

    def public(self) -> dict[str, Any]:
        return {"provider": self.provider, "model": self.model, "base_url": self.base_url or "(provider default)",
                "api_key": f"set ({self.credential_source or 'configured'})" if self.api_key
                else f"missing{' — ' + self.credential_source if self.credential_source else ''}",
                "permission_mode": self.permission_mode, "shell": self.shell, "computer_access": self.computer_access}


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
    mode: str = "operator"                        # prompt profile: operator | forge
    session_context: list = field(default_factory=list)  # [(label, text)] context blocks for every Run
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

    def _prompt_profile(self, arena: "_Arena", mode: str):
        """Build the revision-18 prompt profile for a session mode (see profiles.py)."""
        edits = profiles.profile(mode)
        arr = (abi.PromptSection * len(edits))()
        codes = {profiles.ADD: abi.PROMPT_OP_ADD, profiles.REPLACE: abi.PROMPT_OP_REPLACE,
                 profiles.REMOVE: abi.PROMPT_OP_REMOVE}
        for i, e in enumerate(edits):
            arr[i] = abi.sized(abi.PromptSection, op_code=codes[e.op], id=arena.view(e.id),
                               order=e.order if e.op == profiles.ADD else 0,
                               text=arena.view(e.text) if e.op != profiles.REMOVE else abi.BytesView(),
                               interpolate=1 if e.interpolate else 0)
        arena.keep(arr)
        return arena.keep(abi.sized(abi.PromptProfile, sections=arr, section_count=len(edits)))

    def create_session(self, label: Optional[str] = None, mode: str = "operator",
                       session_context: Optional[list[tuple[str, str]]] = None) -> AgentSession:
        if not self.runtime:
            raise RuntimeError("agent runtime not started")
        c = self.config
        for p in (c.workspace_root, c.workspace_home, paths.outputs_dir()):
            paths.ensure(Path(p))
        arena = _Arena()
        allowed = profiles.session_tools(mode, self._tool_names, list(self._builtins), c.computer_access)
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
            abi.SessionHostConfig, provider_kind_code=abi.PROVIDERS[c.provider_kind],
            permission_mode_code=abi.PERMISSION_MODES[c.permission_mode], shell_policy_code=abi.SHELL_POLICIES[c.shell],
            api_key=arena.view(c.api_key), base_url=arena.view(c.base_url),
            workspace_root=arena.view(str(Path(c.workspace_root).resolve())),
            workspace_home=arena.view(str(Path(c.workspace_home).resolve())),
            allowed_tools=aarr, allowed_tool_count=acount, skill_catalog=catalog,
            skill_policy=C.pointer(policy) if policy is not None else None, permission_rules=C.pointer(rules),
            run_journal_mode_code=abi.RUN_JOURNAL_DURABLE_WORKSPACE))
        profile = self._prompt_profile(arena, mode)
        create = abi.sized(abi.SessionCreateConfig, host=C.pointer(host), model=arena.view(c.model),
                           prompt_profile=C.pointer(profile))
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
        sess = AgentSession(id=uuid.uuid4().hex[:12], label=label or f"Session {next(self._labels)}", handle=out.value,
                            mode=mode, session_context=list(session_context or []))
        sess.core_session_id = self._describe(sess).get("session_id", "")
        with self._lock:
            self.sessions[sess.id] = sess
            self._by_handle[sess.handle] = sess
        self._emit(sess, {"session_created": {"label": sess.label, "model": c.model, "mode": mode}})
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
            arena = _Arena()
            inp = abi.sized(abi.RunInput, kind_code=abi.RUN_INPUT_TEXT, text=arena.view(text))
            blocks = self._context_blocks(sess)
            barr = (abi.ContextBlock * max(1, len(blocks)))()
            for i, (label, body) in enumerate(blocks):
                barr[i] = abi.sized(abi.ContextBlock, label=arena.view(label), text=arena.view(body))
            arena.keep(barr)
            opts = abi.sized(abi.RunOptions, max_turns=int(self.config.max_turns),
                             context_blocks=barr if blocks else None, context_block_count=len(blocks))
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

    # -- per-Run context ------------------------------------------------------------------------
    def _context_blocks(self, sess: AgentSession) -> list[tuple[str, str]]:
        """Revision-18 context blocks: session facts + a fresh browser-state block for every Run."""
        blocks = list(sess.session_context)
        try:
            fut = asyncio.run_coroutine_threadsafe(self._browser_state(sess.id), self.loop)
            blocks.append(("browser", fut.result(10)))
        except Exception as e:  # never block a Run on observation
            log.debug("browser context unavailable: %s", e)
        return blocks[: abi.MAX_CONTEXT_BLOCKS]

    async def _browser_state(self, sid: str) -> str:
        rt = self.registry.runtime
        tabs = await rt.describe_tabs()
        active = rt.active.get(sid)
        lines = []
        for t in tabs:
            mark = "*" if t["tab"] == active else ("mine" if t["owner"] == sid else t["owner"])
            lines.append(f"{t['tab']} [{mark}] {t['title'][:60]!r} {t['url'][:120]}")
        skills = []
        for site in rt.sites.values():
            caps = ", ".join(f"{c.name}({', '.join(c.input_schema.get('properties', {}))})"
                             for c in site.capabilities.values())
            skills.append(f"{site.id} ({site.base_url}): {caps or 'no capabilities yet'}")
        return ("tabs (* = your active tab):\n" + ("\n".join(lines) or "(none)")
                + "\nsite skills (call with site_run or site_<id>_<capability>):\n" + ("\n".join(skills) or "(none)"))

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
                event = json.loads(_bytes(view))
                self._emit(sess, {"core_event": event})
                if "prompt_manifest" in event:  # audit: which system prompt this Run actually sent
                    self.registry.trace.note(sess.id, "prompt_manifest", mode=sess.mode, **event["prompt_manifest"])
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
