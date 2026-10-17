---
name: oceanengine-adapt
description: Work in Ocean Engine (巨量广告/巨量千川) back-offices — read report data (消耗/展示/点击/转化 by plan, ad or creative and date range), and turn the user's recorded demonstrations into reusable oceanengine skills.
model-activation: advisory
---

# Ocean Engine (巨量)

- The user must be logged in in their own MetaBrowser profile. Call `auth_ensure_login` with `{"site": "oceanengine"}`; if it says login_required, ask the user to log in (QR/SMS) in that tab — never handle credentials or verification codes.
- Report data comes from JSON APIs behind the SPA: start `net_capture_start` with a narrow glob (e.g. `*report*`) before switching dates/tabs, then `net_capture_read`. Prefer that over reading the rendered grid; use `data_collect_pages` when you must read the grid.
- Always state the date range and account you actually saw. Totals: use the API's summary or the tool's column totals, never hand arithmetic.
- Money and delivery controls (充值, 提交审核, 修改预算/出价, 启用/暂停, 删除) are irreversible and gated: never click them unless the user explicitly asked for that exact change.
- No capability yet for a task? Ask the user to record it once (side panel ● 录制), say what it does, and run the forge flow; check `site_map_get("oceanengine")` for what exists.
