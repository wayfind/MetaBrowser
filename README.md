# MetaBrowser

换机或接续开发先读 [HANDOFF.md](HANDOFF.md)，并使用 `native-agent-browser` 分支。

An independent Chromium browser with a native Views sidebar and in-process Zig / MetaCodes AgentCore integration. No CloakBrowser code, Python application wrapper, extension, or external CDP controller is used by the product.

## Implemented

- Chromium 154.0.8037.97, cross-built for macOS ARM64 on Linux H200.
- Native Views sidebar with an icon rail: conversation, local Skill, connectors and configuration, with independent conversation tabs at the top.
- Full pinned MetaCodes AgentCore ABI 21; one real Session/AgentLoop for browser, coding and MCP tools.
- OpenAI Chat Completions/Responses, Anthropic and Gemini provider adapters; streamed output, Stop, context compaction, checkpoint/restore and model changes.
- SDK file/search/edit tools, managed shell/process tools and native permission requests; the bundled ripgrep is used without relying on Homebrew's PATH.
- Native tab/navigation, primary-frame live accessibility observation/actions, actual image tool results and bounded local goals with postcondition checks.
- Standard MCP stdio and Streamable HTTP transports, tool selection and cancellation. KnowForge is an optional read-only configuration, not a product dependency.
- Opt-in authenticated loopback A2A 1.0 JSON-RPC gateway to the same visible session. See [protocol scope](docs/AGENT_PROTOCOL.md).
- SDK manifest/file verification before loading, persistent Chromium profiles, masked in-memory model keys.

Privacy surfaces, current evidence and remaining limits are tracked in the [coverage matrix](docs/PRIVACY_COVERAGE.md).

This is an integration prototype. Native utility-process isolation, rich artifact/task history, cross-frame execution, media/video tools, timed game input, Jev model invocation and the three complete business scenarios remain open. A completed AgentCore turn is not proof of a business outcome.

## Build and run

Zig 0.16.0 is required. The pinned engine is built on H200; the local Mac builds the small Zig adapter and packages the returned app.

```sh
zig build test
zig build agentcore:plugin \
  -Dagentcore-sdk="$HOME/.local/opt/metacodes/sdk/agentcore-metabrowser-e3a3b932" \
  -Dtarget=aarch64-macos.13.0 -Doptimize=ReleaseSafe
bash scripts/package-mac.sh
bash scripts/run-mac.sh
```

The app is `out/macos-arm64/MetaBrowser.app`. Use the settings icon to configure provider, endpoint, model and key; configuration also selects the absolute local directory before a new session. Environment defaults are `METABROWSER_PROVIDER`, `METABROWSER_ENDPOINT`, `METABROWSER_MODEL`, `METACODES_API_KEY` and `METABROWSER_WORKSPACE`. The local provider fixture under `tests/integration/` is for acceptance testing only, is explicitly identified in its replies and is not shipped in the app.

The launcher uses Chromium's persistent `~/Library/Application Support/Chromium`
profile by default; build output does not hold the default browser login/session.
To use an isolated browser profile, set `METABROWSER_USER_DATA_DIR` to an absolute
path. Metask account, identity and conversation data retain their separate
Application Support locations.

See [tool system design](docs/TOOLS.md), [architecture](docs/ARCHITECTURE.md), [SDK boundary](docs/SDK.md), and [build receipts](docs/BUILD.md). This orphan worktree starts independently; earlier experiments remain untouched in their original worktrees.

Metask account integration uses authorization-server discovery, desktop PKCE S256 (with explicit device-grant fallback), macOS Keychain, userinfo identity, model endpoint capabilities, serialized rotating refresh and grant revocation. The SDK receives a random loopback capability instead of an account bearer. The native transport can refresh and retry one failed HTTP model request before streaming, preserving the AgentLoop and completed browser actions. No MetaCodes source checkout or CLI is required. See [account setup and protocol verification](docs/ACCOUNT.md).
