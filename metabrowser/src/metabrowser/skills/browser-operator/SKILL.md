---
name: browser-operator
description: Operate the user's MetaBrowser (stealth Chromium) to do business tasks on websites, merchant back-offices, ERP/CRM and other SaaS — read data, fill forms, export reports. Use whenever a task needs a web UI that has no API.
model-activation: advisory
---

# Operating MetaBrowser

Browser tools come from the `browser` MCP server (`browser__*`). Load them with
`ToolSearch` (e.g. `select:browser__page_snapshot,browser__page_click`) before use.

## Pick the cheapest layer

1. **Site skills / L3 tools** `browser__site_<pack>_<capability>` — deterministic recipes for a
   known site. Check `browser__tabs_list` / available skills first. If an L3 tool fails with
   `recipe_failed`, it already returns the current page snapshot: continue with L2/L1.
2. **L2 semantic tools** — one call per intent:
   `page_read` (text), `data_extract_table`, `data_collect_pages` (pagination),
   `form_fill` (many fields, no submit), `net_capture_start` + `net_capture_read`
   (exact JSON behind SaaS dashboards — usually the cheapest and most accurate path),
   `file_download`, `auth_ensure_login`.
3. **L1 primitives** — `page_snapshot` then `page_click` / `page_type` / `page_select` by `[eN]` ref.
   Snapshots say `unchanged` when nothing moved: don't re-read. Use `page_screenshot` only for
   visual questions (charts, layout).

## Rules

- **Never ask for, read, or type the user's passwords or one-time codes.** Call
  `browser__auth_ensure_login`; if it returns `login_required`, tell the user to log in in the named
  tab, then call it again with `wait_seconds: 120`.
- Actions are risk-gated (read < navigate < input < submit < irreversible). If a tool returns
  `approval_required`, explain exactly what you are about to do and ask the user before retrying.
  Never try to get around a denial by using a different tool.
- Work in your own tabs (`tabs_open`). Tabs leased by another session return `tab_leased`; only
  `tabs_claim` one when the user asks you to.
- Large results come back as file paths (CSV/JSON under `~/.metabrowser/artifacts`). Read them with
  the Read tool instead of re-extracting. Write final deliverables to `~/MetaBrowser/outputs`.
- Every browser action is recorded in a tamper-evident trace. Be deliberate: no exploratory clicking
  on submit/irreversible controls.
