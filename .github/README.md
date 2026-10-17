# MetaBrowser

An agent browser built on [ungoogled-chromium](https://github.com/ungoogled-software/ungoogled-chromium) with the
[metacodes](https://github.com/metask-ai/metacodes) agent core embedded: a native side panel with multiple agent
sessions controls the whole browser through layered, risk-gated, fully audited tools — for e-commerce back-offices,
ERP/CRM and other SaaS that only have a web UI.

```bash
pip install -e ./metabrowser
metabrowser browser install                                # digest-pinned macOS build
metabrowser agent build-core --metacodes-src ../metacodes   # embed the AgentCore library (once)
export METABROWSER_API_KEY=...                              # model credentials (env only)
metabrowser                                                 # browser + side panel + agent
```

- Product docs: [metabrowser/README.md](../metabrowser/README.md) · architecture: [metabrowser/docs/ARCHITECTURE.md](../metabrowser/docs/ARCHITECTURE.md)
- Upstream CloakBrowser README (wrapper + binary): [README.md](../README.md)
- Engine and Zig host migration: [metabrowser/docs/ENGINE_AND_ZIG.md](../metabrowser/docs/ENGINE_AND_ZIG.md)
- Repository history remains an overlay fork: [metabrowser/docs/FORK_SYNC.md](../metabrowser/docs/FORK_SYNC.md)
