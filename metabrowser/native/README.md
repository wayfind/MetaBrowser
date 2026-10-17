# Zig CDP feasibility proof

Built and run with Zig **0.16.0**, macOS arm64, ungoogled-chromium 154.
No Python/Node process, no socket debugging port, no external Zig dependency.

```sh
zig build test
zig build run -Doptimize=ReleaseSafe -- /absolute/path/to/chromium /temporary/profile
```

The second path must be a disposable profile, never a profile already opened by
another browser. This program owns and closes the child it starts. Native
Chromium sandbox stays enabled. It performs version, target/session attachment
and AX tree requests over inherited fd 3/4, and fails on timeout or CDP error.

This is a transport/perception proof on macOS/Linux, not the product daemon.
It deliberately has no agent, panel, permissions, MCP or business tools.
It processes requests sequentially and discards asynchronous CDP events.
Production migration is specified in [ENGINE_AND_ZIG.md](../docs/ENGINE_AND_ZIG.md).
