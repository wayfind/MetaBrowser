# Native host integration

The browser embeds the source-free AgentCore SDK through a Zig adapter. Chromium
owns the window, account transport, browser operations and UI callbacks. AgentCore
owns planning, provider requests, coding tools, MCP, permission decisions, budgets,
Skill admission and checkpoints. No secondary agent loop is introduced.

## Conversation ownership

Each conversation has its own SDK Runtime/Session, ordered worker queue and
checkpoint. Different conversation tabs can run independently. The host persists
the visible transcript and draft separately from the SDK checkpoint; closing a tab
does not remove its history. Snapshot writes are atomic, ordered and private to the
user. Original SDK event envelopes retain session/run identities in an append-only
local journal. Unknown event types remain in that journal.

A poisoned Session is destroyed before a new user request. The host restores the
last committed checkpoint when available and never replays the failed request.
Provider/workspace changes establish a new context while retaining the transcript.
Read-only browser operations have explicit permission rules; mutations go through
AgentCore approval and live browser binding validation. Ordinary UI cancellation
returns UI_UNAVAILABLE and aborts the matching Run, preserving Session reuse.

## Browser tools

| Tool | Purpose |
|---|---|
| browser_tabs | Read the tab directory and stable tab identifiers |
| browser_tab_open | Open an HTTP(S) tab |
| browser_tab_activate | Explicitly select a tab |
| browser_tab_close | Close a tab, retaining last-tab/unsaved-change checks |
| browser_navigate | Navigate the selected tab |
| browser_status | Inspect loading and tab state |
| browser_observe | Obtain semantic references or a typed PNG observation |
| browser_act | Act on a fresh, document-bound reference |
| browser_execute | Execute a bounded local sequence with observed postconditions |

Semantic observation currently covers the primary frame. Loading readiness is not
a business-success assertion. Site actions still need observed postconditions.

## SDK controls and UI

The host uses typed text, multimodal and explicit Skill inputs. Image attachments
are actual image parts, not base64 prose. Local Skills are discovered and granted
in the same Runtime that invokes them. The current grant UI selects one Skill at a
time. Standard MCP configuration remains explicit and read-back shows the real SDK
catalogue. Permission mode, maximum turns, budget inspection and compaction use
real controls; controls do not manufacture assistant messages.

Before admitting another Run, expired MCP catalogues are refreshed while retaining
the explicit selectors. Fresh catalogues avoid another discovery round trip.
An admitted Run keeps its immutable SDK environment. External Agent messages enter
through the same typed input path and preserve the human's composer draft.

The dialogue uses selectable native message cards, basic Markdown blocks,
collapsible tool records, an inline approval card, multiline input, attachments,
model selection, conversation tabs and local history. Markdown support is a native
block renderer, not a complete HTML/Markdown engine.

## Model capabilities

The SDK extension opts into read-only model-catalogue discovery. OpenAI image
admission and serialization share the route declaration. The account relay keeps
real tokens in Keychain, authenticates local requests using an ephemeral
capability, normalizes metadata for the selected protocol, and forwards catalogue
requests only to the account's discovered models URL. It does not grant vision
support by renaming a model. The SDK remains ABI v1 revision 19; updated bundles
must be pinned by source commit and complete manifest hash.

## Verification

Local provider fixtures exercise the actual SDK rather than a replacement loop:
`host_contract_test.py`, `oauth_contract_test.py`, `account_catalog_test.py` and
`capabilities_test.c`. They cover lifecycle/poison recovery, committed checkpoints,
permission cancellation, Skill grant/invocation, images, account relay, coding,
sandbox execution and MCP transports without paid model calls. Native window and
browser-action acceptance must additionally run against the packaged app.
