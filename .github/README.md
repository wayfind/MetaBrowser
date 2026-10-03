# MetaBrowser

An agent browser built on [CloakBrowser](https://github.com/CloakHQ/CloakBrowser) (stealth Chromium) with the
[metacodes](https://github.com/metask-ai/metacodes) agent core embedded: a native side panel with multiple agent
sessions controls the whole browser through layered, risk-gated, fully audited tools — for e-commerce back-offices,
ERP/CRM and other SaaS that only have a web UI.

```bash
pip install -e . -e ./metabrowser
metabrowser agent build-core --metacodes-src ../metacodes   # embed the AgentCore library (once)
export METABROWSER_API_KEY=...                              # model credentials (env only)
metabrowser                                                 # browser + side panel + agent
```

- Product docs: [metabrowser/README.md](../metabrowser/README.md) · architecture: [metabrowser/docs/ARCHITECTURE.md](../metabrowser/docs/ARCHITECTURE.md)
- Upstream CloakBrowser README (wrapper + binary): [README.md](../README.md)
- This fork is an overlay that merges CloakBrowser daily: [metabrowser/docs/FORK_SYNC.md](../metabrowser/docs/FORK_SYNC.md)
