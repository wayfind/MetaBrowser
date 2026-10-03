"""ctypes projection of metacodes AgentCore C ABI v1, revision 17.

Revision 17 keeps revision 15's struct layouts and tables (16 was skipped); it adds the
`file_target` permission candidate scope for Write/Edit (see host.permission_response).

Mirrors sdk/metask/agentcore.h. Every struct size is asserted at import time
against the header's static asserts, and the discovered API root is checked for
ABI version, revision and table sizes before use (the header's
``metask_agentcore_api_v1_is_compatible``). A revision bump fails loudly here
instead of corrupting memory.
"""

from __future__ import annotations

import ctypes as C
import os
from pathlib import Path
from typing import Optional

ABI_VERSION = 1
ABI_REVISION = 17

# status / provider / permission / shell / callback codes (subset used by MetaBrowser)
STATUS_OK = 0
STATUS_NAMES = {
    0: "OK", 1: "INVALID_ARGUMENT", 2: "OUT_OF_MEMORY", 3: "BUSY", 4: "STALE_RUN", 5: "TOO_LATE",
    6: "INVALID_STATE", 7: "CORE_ERROR", 8: "CALLBACK_FAILED", 9: "INTERNAL_ERROR", 10: "RESOURCE_LIMIT",
    11: "SKILL_CATALOG_INVALID", 12: "STALE_CATALOG", 13: "SKILL_NOT_FOUND", 14: "INVALID_SKILL_ARGUMENTS",
    15: "SKILL_POLICY_VIOLATION", 16: "SKILL_UNAVAILABLE", 27: "SKILL_CATALOG_INCOMPLETE",
    28: "IMAGE_INPUT_UNSUPPORTED",
}
PROVIDERS = {"anthropic": 1, "openai": 2, "gemini": 3}
PERMISSION_MODES = {"default": 1, "accept_edits": 2, "auto": 3, "dont_ask": 4, "full_access": 5}
SHELL_POLICIES = {"disabled": 1, "sandboxed": 2, "unrestricted": 3}
RUN_JOURNAL_EPHEMERAL, RUN_JOURNAL_DURABLE_WORKSPACE = 0, 1
ABORT_USER_REQUEST = 1
STOP_REASONS = {1: "end_turn", 2: "max_turns", 3: "aborted", 4: "tool_error", 5: "api_error", 6: "tool_loop",
                7: "checkpoint_budget_exhausted", 8: "checkpoint_resource_limit"}
EVENT_CONTINUE = 0
UI_ANSWERED, UI_UNAVAILABLE, UI_FATAL, UI_CANCELLED = 0, 1, 2, 3
HOST_OK, HOST_FAILED, HOST_REJECTED, HOST_FATAL = 0, 1, 2, 3
RUN_INPUT_TEXT, RUN_INPUT_SKILL, RUN_INPUT_MULTIMODAL = 1, 2, 3
SKILL_SOURCE_USER, SKILL_SOURCE_WORKSPACE = 1, 2

u32, u64, vp = C.c_uint32, C.c_uint64, C.c_void_p


class BytesView(C.Structure):
    _fields_ = [("ptr", C.POINTER(C.c_uint8)), ("len", u64)]


class OwnedBytes(C.Structure):
    _fields_ = [("ptr", C.POINTER(C.c_uint8)), ("len", u64)]


class RunContext(C.Structure):
    _fields_ = [("struct_size", u32), ("reserved0", u32), ("session", vp), ("run_id", u64),
                ("session_id", BytesView), ("reserved", u64 * 2)]


HostExecuteFn = C.CFUNCTYPE(u32, vp, C.POINTER(RunContext), BytesView, C.POINTER(OwnedBytes))
HostReleaseFn = C.CFUNCTYPE(None, vp, C.POINTER(OwnedBytes))


class HostTool(C.Structure):
    _fields_ = [("struct_size", u32), ("reserved0", u32), ("ctx", vp), ("name", BytesView),
                ("description", BytesView), ("input_schema_json", BytesView), ("execute", HostExecuteFn),
                ("release_result", HostReleaseFn), ("reserved", u64 * 2)]


class RuntimeConfig(C.Structure):
    _fields_ = [("struct_size", u32), ("reserved0", u32), ("builtin_tools", C.POINTER(BytesView)),
                ("builtin_tool_count", u64), ("host_tools", C.POINTER(HostTool)), ("host_tool_count", u64),
                ("mcp_servers", vp), ("mcp_server_count", u64), ("mcp_catalog_limits", vp), ("reserved", u64 * 4)]


OnEventFn = C.CFUNCTYPE(u32, vp, C.POINTER(RunContext), BytesView)
OnUiRequestFn = C.CFUNCTYPE(u32, vp, C.POINTER(RunContext), BytesView, C.POINTER(OwnedBytes))
ReleaseResponseFn = C.CFUNCTYPE(None, vp, C.POINTER(OwnedBytes))


class SessionCallbacks(C.Structure):
    _fields_ = [("struct_size", u32), ("reserved0", u32), ("ctx", vp), ("on_event", OnEventFn),
                ("on_ui_request", OnUiRequestFn), ("release_response", ReleaseResponseFn), ("reserved", u64 * 4)]


class SkillPolicy(C.Structure):
    _fields_ = [("struct_size", u32), ("reserved0", u32), ("granted_skill_ids", C.POINTER(BytesView)),
                ("granted_skill_id_count", u64), ("reserved", u64 * 4)]


class PermissionRuleSet(C.Structure):
    _fields_ = [("struct_size", u32), ("reserved0", u32), ("allow", C.POINTER(BytesView)), ("allow_count", u64),
                ("ask", C.POINTER(BytesView)), ("ask_count", u64), ("deny", C.POINTER(BytesView)),
                ("deny_count", u64), ("reserved", u64 * 4)]


class SessionHostConfig(C.Structure):
    _fields_ = [("struct_size", u32), ("provider_kind_code", u32), ("permission_mode_code", u32),
                ("shell_policy_code", u32), ("api_key", BytesView), ("base_url", BytesView),
                ("workspace_root", BytesView), ("workspace_home", BytesView),
                ("allowed_tools", C.POINTER(BytesView)), ("allowed_tool_count", u64), ("skill_catalog", vp),
                ("skill_policy", C.POINTER(SkillPolicy)), ("permission_rules", C.POINTER(PermissionRuleSet)),
                ("mcp_selection", vp), ("durable_budget", vp), ("run_journal_mode_code", u32),
                ("protocol_kind_code", u32), ("reserved", u64 * 3)]


class SessionCreateConfig(C.Structure):
    _fields_ = [("struct_size", u32), ("reserved0", u32), ("host", C.POINTER(SessionHostConfig)),
                ("model", BytesView), ("reserved", u64 * 4)]


class SkillSource(C.Structure):
    _fields_ = [("struct_size", u32), ("scope_code", u32), ("root", BytesView), ("source_instance_id", BytesView),
                ("reserved", u64 * 3)]


class SkillCatalogQuery(C.Structure):
    _fields_ = [("struct_size", u32), ("reserved0", u32), ("workspace_root", BytesView),
                ("workspace_home", BytesView), ("workspace_epoch", BytesView),
                ("additional_sources", C.POINTER(SkillSource)), ("additional_source_count", u64),
                ("reserved", u64 * 1)]


class RunInputPart(C.Structure):
    _fields_ = [("struct_size", u32), ("kind_code", u32), ("text", BytesView), ("media_type", BytesView),
                ("data", BytesView), ("reserved", u64 * 2)]


class RunInput(C.Structure):
    _fields_ = [("struct_size", u32), ("kind_code", u32), ("text", BytesView), ("skill_id", BytesView),
                ("catalog_revision", BytesView), ("arguments_json", BytesView),
                ("parts", C.POINTER(RunInputPart)), ("part_count", u64), ("reserved", u64 * 2)]


class RunOptions(C.Structure):
    _fields_ = [("struct_size", u32), ("max_turns", u32), ("reserved", u64 * 4)]


class RunResult(C.Structure):
    _fields_ = [("struct_size", u32), ("stop_reason_code", u32), ("turns", u32), ("tool_calls", u32),
                ("checkpoint_outcome_code", u32), ("result_flags", u32), ("durable_usage_bytes", u64),
                ("required_checkpoint_bytes", u64), ("reserved", u64 * 4)]


DIAG = C.POINTER(OwnedBytes)
RuntimeCreateFn = C.CFUNCTYPE(u32, C.POINTER(RuntimeConfig), vp, C.POINTER(vp), DIAG)
RuntimeDestroyFn = C.CFUNCTYPE(u32, vp, DIAG)
SessionCreateFn = C.CFUNCTYPE(u32, vp, C.POINTER(SessionCreateConfig), C.POINTER(SessionCallbacks),
                              C.POINTER(vp), DIAG)
SessionDestroyFn = C.CFUNCTYPE(u32, vp, DIAG)
SessionRunInputFn = C.CFUNCTYPE(u32, vp, u64, C.POINTER(RunInput), C.POINTER(RunOptions), C.POINTER(RunResult), DIAG)
SessionAbortFn = C.CFUNCTYPE(u32, vp, u64, u32, DIAG)
SessionDescribeFn = C.CFUNCTYPE(u32, vp, C.POINTER(OwnedBytes), DIAG)
SessionSetModelFn = C.CFUNCTYPE(u32, vp, BytesView, DIAG)
SessionUpdateRulesFn = C.CFUNCTYPE(u32, vp, C.POINTER(PermissionRuleSet), DIAG)
QuerySkillCatalogFn = C.CFUNCTYPE(u32, vp, C.POINTER(SkillCatalogQuery), C.POINTER(vp), C.POINTER(OwnedBytes), DIAG)
ReleaseCatalogFn = C.CFUNCTYPE(u32, vp, DIAG)
BufferReleaseFn = C.CFUNCTYPE(None, C.POINTER(OwnedBytes))


class RuntimeApi(C.Structure):
    _fields_ = [("struct_size", u32), ("reserved0", u32), ("create", RuntimeCreateFn), ("destroy", RuntimeDestroyFn)]


class SessionApi(C.Structure):
    _fields_ = [("struct_size", u32), ("reserved0", u32), ("create", SessionCreateFn), ("destroy", SessionDestroyFn),
                ("run_input", SessionRunInputFn), ("abort", SessionAbortFn)]


class SessionControlApi(C.Structure):
    _fields_ = [("struct_size", u32), ("reserved0", u32), ("restore", vp), ("describe", SessionDescribeFn),
                ("set_model", SessionSetModelFn), ("update_permission_rules", SessionUpdateRulesFn),
                ("compact", vp), ("abort_compact", vp), ("export_checkpoint", vp)]


class SkillApi(C.Structure):
    _fields_ = [("struct_size", u32), ("reserved0", u32), ("resolve_catalog", QuerySkillCatalogFn),
                ("release_catalog", ReleaseCatalogFn), ("bind_policy", vp)]


class McpApi(C.Structure):
    _fields_ = [("struct_size", u32), ("reserved0", u32), ("apply_configuration", vp), ("refresh", vp),
                ("describe", vp), ("update_selection", vp)]


class Api(C.Structure):
    _fields_ = [("struct_size", u32), ("abi_version", u32), ("abi_revision", u32), ("reserved0", u32),
                ("buffer_release", BufferReleaseFn), ("runtime", C.POINTER(RuntimeApi)),
                ("session", C.POINTER(SessionApi)), ("session_control", C.POINTER(SessionControlApi)),
                ("skill", C.POINTER(SkillApi)), ("mcp", C.POINTER(McpApi))]


_EXPECTED_SIZES = {
    BytesView: 16, OwnedBytes: 16, RunContext: 56, HostTool: 96, RuntimeConfig: 96, SessionCallbacks: 72,
    SkillPolicy: 56, PermissionRuleSet: 88, SessionHostConfig: 168, SessionCreateConfig: 64, SkillSource: 64,
    SkillCatalogQuery: 80, RunInputPart: 72, RunInput: 104, RunOptions: 40, RunResult: 72, RuntimeApi: 24,
    SessionApi: 40, SessionControlApi: 64, SkillApi: 32, McpApi: 40, Api: 64,
}
for _t, _n in _EXPECTED_SIZES.items():
    assert C.sizeof(_t) == _n, f"AgentCore ABI layout mismatch: {_t.__name__} is {C.sizeof(_t)} bytes, header says {_n}"


def sized(t, **fields):
    """Construct a struct with struct_size set and reserved words zeroed."""
    return t(struct_size=C.sizeof(t), **fields)


class AgentCoreUnavailable(RuntimeError):
    pass


def library_candidates() -> list[Path]:
    env = os.environ.get("METABROWSER_AGENTCORE_LIB")
    home = Path(os.environ.get("METABROWSER_HOME", Path.home() / ".metabrowser")).expanduser()
    name = {"darwin": "libmetask_agentcore.dylib", "win32": "metask_agentcore.dll"}.get(
        __import__("sys").platform, "libmetask_agentcore.so")
    out = [Path(env)] if env else []
    out += [home / "agentcore" / "lib" / name, Path(__file__).with_name(name)]
    return out


def load(path: Optional[Path] = None) -> tuple[C.CDLL, Api]:
    for cand in [path] if path else library_candidates():
        if cand and Path(cand).is_file():
            lib = C.CDLL(str(cand))
            break
    else:
        raise AgentCoreUnavailable(
            "AgentCore library not found. Build it with `metabrowser agent build-core --metacodes-src <path>` "
            "or set METABROWSER_AGENTCORE_LIB.")
    get_api = lib.metask_agentcore_get_api
    get_api.restype, get_api.argtypes = vp, [u32]
    raw = get_api(ABI_VERSION)
    if not raw:
        raise AgentCoreUnavailable("metask_agentcore_get_api(1) returned NULL")
    api = Api.from_address(raw)
    ok = (api.struct_size == C.sizeof(Api) and api.abi_version == ABI_VERSION and api.abi_revision == ABI_REVISION
          and api.runtime.contents.struct_size == C.sizeof(RuntimeApi)
          and api.session.contents.struct_size == C.sizeof(SessionApi)
          and api.session_control.contents.struct_size == C.sizeof(SessionControlApi)
          and api.skill.contents.struct_size == C.sizeof(SkillApi)
          and api.mcp.contents.struct_size == C.sizeof(McpApi))
    if not ok:
        raise AgentCoreUnavailable(
            f"incompatible AgentCore: abi {api.abi_version}.{api.abi_revision}, expected {ABI_VERSION}.{ABI_REVISION}")
    return lib, api
