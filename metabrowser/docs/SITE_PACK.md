# 编写站点包（Site Pack）

一个站点包把"某个网站/SaaS 怎么用"沉淀为三样东西：**知识**（site.json → TinyKG）、
**能力**（capabilities → L3 工具）、**用法**（skills → metacodes Skill）。新增一个 SaaS 的支持只需新增一个包。
参考实现：[`sites/example-shop`](../sites/example-shop)。

## 推荐流程

1. **探索（只读）**：让 agent 用 L1/L2 工具逛一遍，`metabrowser trace show` 回看轨迹。
2. **功能地图**：模块 → 页面（`modules`, `pages`, `links`）。
3. **交互地图**：每页的动作（`pages[].actions`：表单、按钮、分页、导出），以及跳转关系。
4. **数据与风险**：实体与字段（`entities`，标注 `pii`），风险点（`risks`：资金、删除、审批、PII、限流）。
5. **能力化**：把高频任务写成 `capabilities/*.json` 配方；把业务约束写进 `skills/*/SKILL.md`。
6. `metabrowser site validate` → `site install` → 重启 MetaBrowser（工具与 skill 自动注册）→ `site kg-sync`。

## site.json

```jsonc
{
  "id": "my_erp",                       // [a-z][a-z0-9_]*，工具名前缀 site_my_erp_*
  "name": "My ERP",
  "base_url": "https://erp.example.com",  // 租户可用 METABROWSER_SITE_MY_ERP_URL 覆盖
  "login": {                            // auth_ensure_login 使用；从不输入凭据
    "check_url": "{base_url}/home",
    "logged_out_url": "/sso/login",     // URL 正则，命中即视为未登录
    "logged_in_selector": "#user-avatar"
  },
  "modules":  [{"id": "purchase", "name": "采购"}],
  "entities": [{"id": "po", "fields": ["no", "vendor", "amount"], "pii": [], "risks": ["po_amount"]}],
  "pages": [{
    "id": "po_list", "module": "purchase", "url": "{base_url}/po",
    "entities": ["po"], "links": ["po_detail"],
    "actions": [{"id": "approve_po", "kind": "button", "writes": ["po"], "risks": ["po_approve"]}]
  }],
  "risks": [{
    "id": "po_approve", "level": "irreversible",          // read|navigate|input|submit|irreversible|system
    "match_text": "审批通过|Approve", "url_glob": "*/po/*", // 让 L1 page_click 命中时也升级为 irreversible
    "reason": "approving a PO commits spend"
  }]
}
```

`risks[].match_text` 是**运行时生效**的：agent 即使不用 L3、直接 `page_click` 到"审批通过"按钮，
PolicyGate 也会按 irreversible 处理并请求审批。

## capabilities/<name>.json

```jsonc
{
  "name": "po_search",
  "description": "按供应商/单号查询采购单",
  "risk": "read",                       // 整个能力的风险等级（审批粒度 = 一次能力调用）
  "reads": ["po"], "writes": [],
  "input_schema": {"type": "object", "properties": {"vendor": {"type": "string"}}},
  "steps": [
    {"do": "goto", "url": "{base_url}/po"},
    {"do": "ensure_login"},
    {"do": "fill", "target": [{"label": "供应商"}, {"placeholder": "vendor"}, {"css": "#vendor"}], "value": "{vendor}"},
    {"do": "click", "target": [{"role": "button", "name": "查询|Search"}]},
    {"do": "wait", "selector": "table.po-list"},
    {"do": "extract_table", "selector": "table.po-list", "as": "rows"}
  ],
  "returns": "rows"
}
```

步骤：`goto, ensure_login, click, fill, select, press, wait(text|selector|url|ms|state), assert(selector|text),
extract_table, extract_text, capture_start(url_glob), capture_read(as, wait_ms)`。

- **target** 是候选列表，按顺序尝试：`role+name`、`label`、`placeholder`、`text`、`css`。
  `name/label/placeholder/text` 是不区分大小写的正则；插入的参数值会被自动转义。
- 参数用 `{arg}` 引用；未提供的可选参数渲染为空串。字面量花括号写 `{{ }}`。
- 优先用 `capture_start/capture_read` 抓 SaaS 前端调用的 JSON 接口——比解析 DOM 稳定得多。
- 失败时工具返回 `recipe_failed`（含失败步骤 + 当前页面快照），agent 自动降级到 L1/L2 继续；
  那条成功的降级轨迹就是修复配方的素材。

## skills/<name>/SKILL.md

metacodes skill 格式（frontmatter：`name`, `description`, 可选 `allowed-tools`, `model-activation` 等）。
写清楚：什么时候用、先调用哪些工具、业务约束（哪些动作必须让用户确认、数据保存位置）。
MetaBrowser 启动时把每个站点包的 `skills/` 注册为内嵌 AgentCore 的 skill source（按 skill_id 默认拒绝、显式授权）。
注意 AgentCore 不接受 skill 目录里的符号链接，文件需为普通文件。

## TinyKG 映射

| site.json | TinyKG 节点 | 关系 |
|-----------|-------------|------|
| 包本身 | `site` | `has_module`, `provides`, `has_risk` |
| modules[] | `site_module` | `has_page` |
| pages[] | `site_page` | `has_page`(from module), `navigates_to`, `reads_entity`, `exposes_action` |
| pages[].actions[] | `ui_action` | `navigates_to`, `writes_entity`, `has_risk` |
| entities[] | `data_entity` | `has_risk` |
| risks[] | `site_risk` | — |
| capabilities/* | `capability` + `recipe` | `implements`, `reads_entity`, `writes_entity` |

节点名为 `<site>/<kind>/<id>`，同步是幂等的（id 映射保存在 store 旁的 `.metabrowser-ids.json`）。
schema：[`kg/metabrowser-site.schema.json`](../src/metabrowser/kg/metabrowser-site.schema.json)。
