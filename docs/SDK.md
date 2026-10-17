# Browser SDK boundary

Build Chromium and its native adapters less frequently, and develop the
Zig/MetaCodes consumer independently against an explicitly versioned SDK.
The SDK is more than Chromium headers: it contains the browser runtime,
helper executables, resources, native bridge, protocol/schema, notices,
target-specific loader, manifest and an executable integration test.

## Coordinate and layout

A release coordinate is `(Chromium commit, bridge ABI, protocol revision,
target OS/architecture, build configuration, content hash)`. Complete manifests
pin every executable, native library and resource. The consumer rejects target
or ABI mismatches before loading anything.

```text
metabrowser-engine-sdk/<coordinate>/
  manifest.json
  include/metabrowser/browser_sdk.h
  schema/browser_agent.mojom
  lib/<platform native bridge>
  runtime/<browser + sandboxed helpers + resources>
  examples/<native test consumer>
  LICENSES/
```

The headers and schemas are portable; native runtime assets are not. Linux
`x86_64` libraries cannot be linked into this Mac's `aarch64` process. Sharing
the architecture name alone is also insufficient if operating systems differ.

## Operations

The browser SDK exposes lifecycle, profile/tab ownership, observation,
semantic actions, dialogs/uploads/downloads, recording, consent and journal
events. Agent orchestration and model APIs remain in MetaCodes. Keeping that
boundary makes agent builds cheap without pretending browser compilation is
unnecessary.

Every request carries SessionId, RunId and RequestId. Targeted actions also
carry the tab/frame/document/snapshot binding that produced the reference.
Native inspection computes the operation's risk; the model cannot select a
lower risk. Consent binds the exact action, observation and run. Navigation,
lease transfer, cancellation or document replacement invalidate it.

Results/events distinguish completed, rejected, stale, cancelled, crashed and
unsupported. No operation returns success before downstream native execution
has produced evidence. Stop propagates to native outstanding work as well as
the MetaCodes abort signal. An SDK that only returns canned answers is not an
engine implementation.

Native IPC is asynchronous. Chromium UI/render sequences must never block on
a model request or consent callback. Request arenas outlive all callbacks;
results are copied/owned across the ABI and have an explicit release method.
Session/Run identifiers have distinct Zig types. Production endpoints bind to
local process capabilities; remote transport, if selected, is a separate
authenticated deployment mode.

## Local and remote consumer models

| Model | H200 output | Mac usage |
|---|---|---|
| Linux local product | Linux browser/bridge SDK, headers, resources, integration evidence | Develop portable Zig code and inspect artifacts; run native Linux tests on H200 |
| macOS local product | Linux build/test evidence and portable headers/protocol | Needs a separate macOS engine SDK built with a compatible macOS/Xcode toolchain |
| Remote Linux engine | Linux browser/bridge plus explicitly secured remote protocol | Mac Zig/MetaCodes sends semantic commands; browser and login state live on H200 |

A remote engine is not the same product as a local native browser. UI/display,
login and browser ownership need an explicit design, not an implicit "copy the
SDK to Mac" step. The selected build has since demonstrated Linux-to-macOS ARM64 cross-compilation using the transferred Apple SDK; Linux runtime files are not substituted for macOS assets.

## MetaCodes

Use either the pinned `metacodes-core` Zig module or a complete validated
AgentCore SDK bundle. The caller keeps MetaCodes permission/budget/governance
boundaries and connects browser native capabilities as typed HostTools.
No copied headers, CLI subprocess wrapper, or direct calls bypassing AgentLoop.

The selected complete SDK is ABI 21, commit `e3a3b932db606d2f43d7ed3d3112768b3f0afa10`, built on the isolated `metabrowser-sdk-catalog` branch. It adds explicit route-catalogue discovery, idle reasoning controls, committed-context estimates, and bounded native-image metadata with provider serialization and budget accounting. Prompt controls and grounded browser images reach providers through AgentCore. The original installed SDK and MetaCodes main checkout remain unchanged. Native adapters are cross-compiled on H200 and returned as a macOS framework. The Zig consumer can be rebuilt locally without rebuilding Chromium.

The native reasoning menu consumes `describe.inference.reasoning_options`.
The SDK prefers the route catalogue's declared levels and vocabulary, then falls
back to provider profiles; the UI never invents a fixed number of levels.
Model changes reset the previous selection. `max`, `xhigh`, and provider thinking
states reach the appropriate request fields through SDK serialization.

The context ring uses a gray track and Metask purple for estimated used input
capacity. The number also means used percent; a positive value below one percent
shows `<1`. The tooltip exposes used tokens, effective input budget, raw model
window and output reserve, with the estimate basis and exclusion of unsent drafts.
OpenAI routes honor catalogue limits before their 128K offline fallback. An
unknown limit stays unknown. The indicator's menu contains only compaction.

## Implemented native MetaCodes adapter (2026-10-15)

`metacodes_plugin.h` defines the small Session-scoped C boundary actually used
by the Views panel: create, run, abort, control, free and destroy (host adapter ABI 2). The Zig library consumes the
complete pinned AgentCore SDK's supplied bindings; `Api.discover` validates its
revision and all mandatory tables. It does not call a CLI or bypass AgentLoop.
The older global runtime-host registration interface remains an unused prototype.

The app contains the complete SDK in `Contents/Resources/agentcore` and the Zig
adapter in `Contents/Frameworks`. Chromium verifies the pinned manifest and every
listed file before `dlopen`. The adapter's loader-relative rpath uses the bundled
SDK; a live Mac process inspection confirmed this path. Both adapter and engine
use a macOS 13.0 deployment target, tested here on the development Mac only.

Each conversation owns a Runtime/Session. Blocking SDK calls use a pool of four
16 MiB workers with ordered work per conversation; UI events are copied and posted
through weak callbacks. Different conversations can run independently. Abort uses the SDK's thread-safe API;
close/hide requests cancellation before animation, and destroy is sequenced after
outstanding runs. Owned handles are cleared before freeing SDK state so Chromium's
checked pointers do not dangle. Provider credentials and workspace become editable after New
Session; the model can change between turns. Keys are masked and not persisted by this prototype.

The Session explicitly selects the SDK's Read/Write/Edit/Glob/Grep/Bash/BashOutput/KillShell/WebSearch/WebFetch/AskUserQuestion capabilities. Availability still depends on SDK configuration (declaring WebSearch does not supply a search service). Shell mode is sandboxed, with no unrestricted fallback. Permissions are answered by the native UI using the exact request id and policy generation.

Nine HostTools call the native browser broker: `browser_tabs`, `browser_tab_open`, `browser_tab_activate`, `browser_tab_close`, `browser_navigate`, `browser_status`, `browser_observe`, `browser_act`, `browser_execute`. Tab listing is read-only. Stable tab/document identifiers bind observations, and the broker revalidates live primary-frame AX references before dispatch. The visual tool returns typed PNG image data to AgentCore, not a path or base64 prose. `browser_execute` is a deterministic, bounded policy with observed postconditions; no Jev service is called yet. See [HOST_INTEGRATION.md](HOST_INTEGRATION.md) for lifecycle, history and controls.

Standard MCP uses SDK catalog/selection with native posix_spawn stdio and system libcurl Streamable HTTP, including correlated SSE results, session headers, cancellation and unknown-outcome handling. Configuration is supplied explicitly through `METABROWSER_MCP_CONFIG`; model-created workspace files do not automatically become executable connector configuration.

Checkpoint files are written through a private temporary file and atomically replaced in the selected workspace. They may contain task data and should be treated as private. Keys remain masked and are not stored by the panel. The local provider/MCP fixtures and accessibility drivers under tests are acceptance tooling only, not product dependencies.

## Native account UI and conversation tabs

The right edge has four native entries (conversation, local Skill, connectors, configuration). Conversation tabs each own an SDK Session, draft, message state, browser observation state and UUID-named checkpoint. A single opt-in A2A endpoint routes new work to the selected tab and cancellation back to the originally submitted tab. Switching tabs preserves a running session; closing the whole sidebar requests cancellation. Worker execution is still serialized.

The keyless skills_catalog Runtime operation discovers local Skill metadata without a model Session. The native list renders actual SDK catalog descriptors.

Native account authentication is independent of the MetaCodes source tree. A small Objective-C OS transport called through Zig handles Foundation JSON, system randomness and macOS Keychain. Native PKCE/state validation, metadata-driven device grants, identity/models, refresh and revocation implement the supplied Metask contract. The bounded local relay also projects current route capabilities to the pinned SDK extension. OAuth renewal remains at the HTTP request boundary, so SDK Sessions and completed tool calls are never replayed to refresh a token. Account events stay on the private account worker/UI channel, outside model and A2A output. See [ACCOUNT.md](ACCOUNT.md).
