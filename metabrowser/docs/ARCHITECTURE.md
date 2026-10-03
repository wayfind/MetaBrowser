# MetaBrowser 架构

> 状态：M0 已实现并实测（真实 CloakBrowser 145 二进制、内嵌 metacodes AgentCore、原生侧边栏容器）。
> 上手：[../README.md](../README.md) · 站点包：[SITE_PACK.md](SITE_PACK.md) · 上游同步：[FORK_SYNC.md](FORK_SYNC.md)

## 0. 前提与目标

**前提（决定架构的事实）**：CloakBrowser 仓库只包含包装库（Python/JS/.NET）；Chromium 内核是 CloakHQ 预编译、
签名分发的闭源二进制（`BINARY-LICENSE.md`，87 个 C++ 隐身补丁不公开）。因此本项目**不修改内核**：通过 CDP
pipe 控制浏览器，侧边栏挂在 Chromium 原生侧边栏容器里。执行层被抽象为接口，将来获得内核源码时可整体替换为
进程内原生 actor（§7），上层不变。

**目标**：让 metacodes agent loop 高效、低成本、可审计地完成只能在浏览器里做的业务（电商后台、ERP/CRM、传统 SaaS）。

| 需求 | 落点 |
|------|------|
| 分层应用级接口 | §2 L1–L4 工具 + Actuator 执行层 |
| 站点知识图谱、能力 CLI/Skill 化 | §4 Site Pack + TinyKG `metabrowser-site` schema |
| 计算机/磁盘/网络访问（授权） | §5 AgentCore 权限 + 浏览器风险门 |
| 以 MCP 暴露能力 | §3 |
| 浏览器内多 session 对话栏，控制整个浏览器 | §6 |
| 与上游同步 | §8 + FORK_SYNC.md |
| 轨迹可审计、可优化 | §9 |

## 1. 总体结构（一个进程拥有一切）

```
┌──────────────────── CloakBrowser Chromium（预编译二进制，有界面）────────────────────┐
│  标签页 …                                       │ 原生侧边栏容器（Chromium side panel） │
│                                                 │  Session 1 │ Session 2 │ ＋          │
└──────▲──────────────────────────────────────────┴──────────────▲──────────────────────┘
       │ CDP pipe（Playwright；不开端口）                         │ loopback HTTP/SSE + token
┌──────┴──────────────────── metabrowser daemon（Python，单进程）───┴────────────────────┐
│ Actuator(CDP: AX 树感知 / 坐标动作 / 隔离 world)   ToolRegistry(L1/L2/L3/L4)            │
│ PolicyGate(风险门)   TraceRecorder(哈希链)   SitePacks   /mcp(外部智能体)               │
│ AgentHost ──ctypes──► libmetask_agentcore (metacodes AgentCore C ABI v1 rev17)        │
│              host tools = 全部浏览器工具；on_ui_request → 侧边栏审批；多 Session         │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

`metabrowser`（无参数）= 启动浏览器 + 打开侧边栏 + 启动内嵌 agent。浏览器窗口关闭则 daemon 退出。

## 2. 工具分层与执行层

| 层 | 工具 | 说明 |
|----|------|------|
| L1 | `tabs_*`, `page_navigate/snapshot/click/type/select/press/scroll/wait/screenshot`, `page_dialog`, `file_upload`, `browser_permissions`, `page_evaluate`（默认禁用） | ref 寻址的原子动作 |
| L2 | `page_read`, `data_extract_table`, `data_collect_pages`, `form_fill`, `net_capture_start/read`, `file_download`, `auth_ensure_login` | 一个意图一次调用；大结果落盘返回路径 |
| L3 | `site_<pack>_<capability>` | 站点包配方，确定性回放，失败返回现场快照供降级 |
| L4 | `agent_run_task`（仅对外 MCP） | 委托内嵌 agent 完成整件事 |

**Actuator（`actuator/`）是唯一接触引擎的层**，`CdpActuator` 把 CDP 用到极致：

- **感知**：`Accessibility.getFullAXTree` 逐帧读取浏览器计算好的无障碍树。同进程 iframe 走页面 session，
  **跨进程（跨站）iframe 走独立 CDP session**（真实 CloakBrowser 对跨站 iframe 做进程隔离，已实测）。
  不向页面 JS 世界注入任何东西，**不改 DOM**（ref 由 actuator 以 backendDOMNodeId 维护）。
- **动作**：`DOM.getContentQuads` 取几何 → 页面 `mouse.click / keyboard.type`。在 CloakBrowser humanize 下这些是
  拟人轨迹与节奏，并经 CloakBrowser 打过补丁的 CDP 输入路径发出；不依赖选择器（humanize 不支持 role/组合选择器，实测发现）。
- **页面读取**（正文、表格）在私有 isolated world 执行，页面脚本不可见。
- **对话框**：agent 名下标签页的 alert/confirm/prompt 被挂起交给 `page_dialog`（确认文本命中风险词则需审批）；
  用户标签页保留原生对话框给人处理（避免 Playwright 默认自动关闭）。动作与对话框竞速，防止输入调用被对话框阻塞导致死锁。
- **上传**：只在 `file_upload` 调用期间拦截文件选择器（不影响人工上传）；`~/MetaBrowser` 以外的文件升级为 irreversible 审批。

## 3. 能力暴露

| 出口 | 消费者 |
|------|--------|
| 内嵌 AgentCore host tools（同一 Registry） | 侧边栏里的 metacodes agent |
| `POST /mcp`（Streamable HTTP，JSON，Bearer token） | 其他智能体 |
| `metabrowser mcp`（stdio 桥，自动拉起 daemon） | Claude Code / 独立 metacodes CLI / 任意 MCP 客户端 |
| `/api/*` | 侧边栏、脚本 |

所有出口共用 `validate → assess → PolicyGate → actuator → trace` 管线，不可绕过。

## 4. 站点知识：Site Pack + TinyKG

站点包 = `site.json`（功能地图、交互地图、数据实体、风险）+ `capabilities/*.json`（配方 → L3 工具）+
`skills/*/SKILL.md`（注册为 AgentCore skill source，按 skill_id 授权）。`site kg-sync` 幂等写入 TinyKG
（9 类节点、10 类关系，schema 已用 tinykg 校验并实测写入）。站点 `risks[].match_text` 在运行时把普通点击升级为
irreversible。详见 SITE_PACK.md。

## 5. 授权模型

- **agent 内核侧（AgentCore）**：permission mode + allow/ask/deny 规则（Claude Code 语法，`//abs` 为绝对路径，
  优先级 deny > ask > allow）。默认：浏览器工具与 Read 放行；输出目录内 Write/Edit 放行；Bash/WebFetch/其他写入询问；
  浏览器 profile、daemon token、`~/.ssh` 禁读。询问经 `on_ui_request` 到侧边栏卡片（allow_once/allow_session/deny…）。
  Shell 走 sandboxed 策略。
- **浏览器侧（PolicyGate）**：read/navigate/input 放行，submit 询问，irreversible 每次询问，system 禁止；
  站点风险图谱与通用风险词表提升等级。
- **凭据**：模型 API key 只从环境变量读取；网站密码永不进入 agent（`auth_ensure_login` 只检测，由人登录）。

## 6. 侧边栏与多 Session

- **位置**：Chromium 原生侧边栏容器（与阅读清单、书签、Gemini 侧边栏同一位置；Chrome 自己的侧边栏内容同样是 HTML/WebUI）。
  因内核闭源，以 MV3 扩展的 `side_panel` 注入；daemon 启动时用带用户手势的 CDP 调用 `chrome.sidePanel.open` 自动打开。
  扩展无 content script、无 web_accessible_resources，页面无法探测（实测 `navigator.webdriver=false`）。
- **Session**：每个对话 = 一个 AgentCore Session（运行于独立线程，`run_input` 同步阻塞）；可随时新建；
  Run 期间的新消息排队；Stop = `session_abort`。
- **控制范围 = 整个浏览器**，Tab Lease 防互踩：session 打开的标签归其所有，操作他人标签需 `tabs_claim`；
  扩展自身页面对 agent 不可见、不可操作。
- ABI rev17 没有系统提示词槽位（已提 metask-ai/metacodes#184）：浏览器操作规范随每个 session 首条输入注入（`<metabrowser-context>`）。

## 7. 将来的原生路线（获得内核源码时）

Chromium 145 分支已有 Gemini 代理浏览用的 `chrome/browser/actor`（click/type/navigate/scroll 等 20+ 工具、
ExecutionEngine、ToolController）与 Blink `content_extraction`（Annotated Page Content），以及 `SIDE_PANEL_ENTRY_IDS`
侧边栏注册。替换方式：实现一个 `NativeActuator`（进程内 actor + APC 感知）、侧边栏改为 WebUI 原生条目、AgentCore 静态库直接链接进浏览器进程。
工具契约、站点包、风险门、轨迹、AgentCore 集成全部复用。内核补丁按 Brave `chromium_src` 覆盖 + 独立目录方式分层以便跟随 Chromium 版本。

## 8. 与上游同步

overlay fork：fork 代码全部在 `metabrowser/`；对上游文件的修改只允许登记在 `metabrowser/seams.txt` 的少量“切入点”，
每个有行数预算；追加型文件用 `merge=union`、fork 自有文件用 `merge=ours`，`git rerere` 复用人工解决过的冲突。
`fork_guard.py` 在 CI 强制。每日工作流合并上游并开 PR。已在副本中模拟上游提交验证合并全自动。详见 FORK_SYNC.md。

## 9. 轨迹：记录 → 审计 → 优化

- 每次工具调用一条 NDJSON：session、actor、tool、脱敏参数、风险、决策来源、tab、URL 前后、快照 hash、结果摘要、耗时；
  `hash = sha256(prev + event)` 防篡改，`trace verify` 校验。agent run 结束、审批也入链。
- AgentCore 侧：durable workspace journal（`<workspace_home>/.metacodes/agentcore/sessions/<id>`）+ `permission_provenance` 事件。
- 优化闭环（M2）：成功轨迹编译为配方，失败配方的降级轨迹作为修复样本，成功率写回 TinyKG。

## 10. 验证

- 单元/集成：`cd metabrowser && pytest`（35 项；测试浏览器启用 humanize 与 site-per-process，与产品一致）。
- 真机验收：`python metabrowser/tests/e2e/run_e2e.py`——真实 CloakBrowser 有界面、原生侧边栏、内嵌 AgentCore；
  通过 CDP 像用户一样操作侧边栏（新建 session、输入任务、点击审批），覆盖 L3 配方、AgentCore 权限询问、
  不可逆动作升级拒绝、写报告、多 session、轨迹校验。模型默认用 mock，`--real-llm` 使用环境中的真实凭据。

## 11. 已知限制 / 后续

- 侧边栏打开依赖 CDP 用户手势特性；`--load-extension` 在未来 Chromium 版本可能受限（届时改用策略安装）。
- HTTP Basic 认证、客户端证书、系统钥匙串弹窗属于浏览器/系统原生 UI，CDP 无法代答，需人工。
- 封闭 shadow DOM 内容在 AX 树中可见、但隔离 world 的表格/正文提取看不到。
- 尚未用真实模型跑完整任务（需要你提供 API key）；M1：侧边栏体验打磨、Tab Lease 可视化；M2：站点探索 agent、轨迹→配方编译；M3：飞书等 skill。
