# 外部 Agent 通讯与 MetaCodes 集成

2026-10-15。协议调研依据一手规范；运行验收记录见项目 evidence。

## 协议选择

| 协议 | 负责的关系 | MetaBrowser 选择 |
|---|---|---|
| [A2A](https://a2a-protocol.org/v1.0.0/specification/) | 独立 agent 的发现、任务、状态、消息与产物 | 浏览器对外任务接口采用 1.0 JSON-RPC 绑定 |
| [MCP](https://a2a-protocol.org/latest/topics/a2a-and-mcp/) | Agent 使用工具、数据与资源 | 复用 MetaCodes SDK 的协议协商与工具目录；宿主补 stdio / Streamable HTTP 传输 |
| [Agent Client Protocol](https://agentclientprotocol.com/get-started/introduction) | IDE/编辑器与 coding agent | 与浏览器任务委托不同，本次不增加第二种外部会话协议 |
| [Agent Communication Protocol](https://agentcommunicationprotocol.dev/introduction/welcome) | 原来的跨 agent 通讯协议 | 官方已声明并入 A2A，不单独实现 |

本地 Skill 沿用 MetaCodes，不设计远端包或 skills.* 工具。A2A 的 AgentSkill 是对外能力描述，不等于本地 SKILL.md 分发机制。

## 原生接口

设置 `METABROWSER_AGENT_PORT` 和至少 32 字符的 `METABROWSER_AGENT_TOKEN` 后启用本机端点。没有这两个配置时不开监听；仅绑定 127.0.0.1，不暴露外网。配置 provider、模型和工作目录后，外部任务进入与侧边栏相同的原生 MetaCodes Session。当前端点生命周期随该窗口的侧边栏宿主，不是独立常驻系统服务。

- `GET /.well-known/agent-card.json`：公开的能力及接口描述，不含凭据或工作目录。
- `POST /a2a`：Bearer 鉴权，并要求 `A2A-Version: 1.0`。
- JSON-RPC 方法：`SendMessage`、`GetTask`、`ListTasks`、`CancelTask`。
- 当前能力：新建纯文本任务、状态轮询、文本 Artifact；非流式，未声明推送通知。
- 当前限制：不接受 taskId/contextId 继续对话，不支持过滤列表、文件传输、订阅或 0.3 自动降级，不宣称完整 A2A 一致性认证。

任务状态由实际 SDK 事件更新。取消请求先记录 cancelRequested，等待 SDK 终止后才进入 canceled；不会把“已经请求停止”当成“执行已经停止”。同一 messageId 的相同内容复用已有任务，不同内容拒绝。当前单端点最多保留 64 个内存任务，任务列表不跨浏览器重启恢复。

副作用与 coding 权限仍由 MetaCodes 及原生浏览器宿主处理，外部消息不能自行扩大权限。需要用户回应时任务进入 input-required，在原生 UI 完成授权；协议请求不替用户批准操作。completed 表示 agent 本轮结束，metadata 明确 businessOutcomeVerified=false，不将模型回答等同于外部业务成功。

## MetaCodes 已接通的接口

- Anthropic、OpenAI Chat、OpenAI Responses、Gemini：选择 provider/protocol 后把 endpoint、model、key 交给 SDK；空闲时通过 SDK set_model 更新模型，不重建会话。
- 内置工具：Read、Write、Edit、Glob、Grep、Bash、BashOutput、KillShell、WebSearch、WebFetch、AskUserQuestion。具体模型/宿主条件不支持的工具由 SDK 决定是否可用，不伪造能力。WebSearch 的服务依赖仍由 SDK 配置决定。
- UI 事件、工具进度/结果、文件变化、权限请求、用户问题、取消；终端使用 SDK sandboxed shell policy，失败不退回 unrestricted。
- SDK durable journal / artifact CAS、检查点导出与恢复、上下文压缩。当前 UI 保留工作目录的最新检查点，尚无完整历史会话列表。
- SDK 本地 Skill 目录与 policy 控制接口保留在适配层；当前图标版 UI 未增加 Skill 管理页，不新增远端 Skill 生命周期。
- 原生浏览器工具以 `src/browser_tool_catalog.json` 的 12 项目录为准；内嵌 SDK 与外部 MCP 共用生成的 schema 和执行 Broker，详见 [TOOLS.md](TOOLS.md)。

当前 SDK ABI 21 的嵌入接口不等同于完整 CLI 的 Task/Cron/worktree 等进程级功能；这些不能仅通过把工具名加入列表而获得。Jev 网络决策适配尚未接入；browser_execute 当前使用唯一目标的确定性选择，歧义时返回 AgentCore。跨 frame 语义观察与绑定动作已由 Broker 实现；独立 utility 进程、媒体读取与动态游戏输入仍是目标架构的缺口。

## MCP 配置

`METABROWSER_MCP_CONFIG` 指向用户指定的配置文件。不会自动执行工作目录里由模型或项目写入的 MCP 配置。以下是宿主配置格式，不是对 MCP 线协议的扩展：

```json
{
  "revision": 1,
  "servers": [{
    "name": "knowledge",
    "command": "/absolute/path/to/server",
    "args": [],
    "tools": ["search"]
  }]
}
```

HTTP 服务用 `url` 替代 command/args，支持 HTTPS 或显式 127.0.0.1 测试地址；Bearer 通过 `token_env` 引用环境变量，不能把密钥写入工具 schema。`tools` 是显式选择的远端原始工具名；未选择工具不获得调用权限。连接参数改变时更新 revision。传输实现有 8 MiB 帧/响应上限和超时，支持取消、通知过滤、SSE 关联响应。不可确认的 tools/call 传输失败返回 indeterminate，不当作安全重试依据。

本机只读 KnowForge 配置位于用户私密目录 `~/.config/metabrowser/mcp.json`，不含 API Key；密钥仍由已安装的 MCP 服务读取其私密配置。产品运行时为 Chromium/C++ 与 Zig，MCP 子进程使用什么语言由用户配置。

## 验证口径

测试 provider、MCP fixture、Swift UI 驱动及 Python A2A 客户端均不打包进产品。组件验收检查真实 SDK 写文件、沙箱命令、拒绝权限、恢复后继续运行、各 provider 的实际协议以及 stdio/HTTP/SSE 工具往返。原生浏览器验收必须由内嵌 AgentCore 调用原生工具，外部 CDP 仅可用于布置 fixture 或独立读取结果，不能替代产品执行器。

本轮原生验收通过：官方 a2a-sdk 1.2.2 客户端提交/查询任务；真实 SDK 文件读写和 Bash；主 frame 观察/点击/观察；PNG 真正进入 provider 请求；有界步骤填值和点击后的两个条件；外部重复消息/冲突/实际取消；原生新会话与检查点恢复后 A2A 继续可用。验证使用明确标记的本地 provider 与网页 fixture，不代表真实模型的业务推理质量或成本。记录见 `out/evidence/native-integration-verification.json`。


## 外部 MCP Server（原生工具入口）

这与 `METABROWSER_MCP_CONFIG` 的出站 MCP client 是两个方向。外部 MCP
server 与 A2A 共用 `METABROWSER_AGENT_PORT`、`METABROWSER_AGENT_TOKEN` 和
127.0.0.1 监听器，路径为 `POST /mcp`。只有宿主同时传入 `Execute` 和
`CancelTool` 两个回调才启用；旧构造调用保持关闭，返回 404。无需 provider、模型、
API key 或另建 SDK Session。端点仍随窗口侧边栏生命周期关闭。

传输按 [MCP 2025-03-26 Streamable HTTP](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports)
实现 JSON 响应模式：`initialize` 返回协商版本和不可预测的 `Mcp-Session-Id`，
客户端随后发送 `notifications/initialized`。后续请求必须携带该 session header；
若发送 `MCP-Protocol-Version`，必须为协商版本。支持 `ping`、`tools/list`、
`tools/call`、`notifications/cancelled` 及 `DELETE /mcp`。POST 要求
`Content-Type: application/json` 和同时接受 JSON、SSE 的 Accept header；
本实现始终返回 JSON，不提供 SSE，GET 返回 405。不支持 batch、分页、资源、
prompt、服务端主动请求或旧 HTTP+SSE 端点，不声明这些能力。

所有 MCP 请求（包括初始化）要求同一个 Bearer token；拒绝 Origin header，
Host 必须精确为 `127.0.0.1:配置端口`。不提供 CORS。session 仅是协议与请求的
所有权标识，不是浏览器 profile、SDK session 或额外授权。最多 32 个 session，
初始化新 session 时回收超过 30 分钟未活动且不占用执行 lane 的 session。

工具 schema 原样来自完整 `BrowserTools::ToolCatalog()`，不保留 gateway 的第二份
名称白名单。当前 12 个工具包括 browser_execute 与 browser_inspect、browser_extract、
browser_wait；它们与其余原生工具共用 Broker。gateway 调用
`BrowserTools::ValidateArguments(tool, args)` 进行递归 schema 校验，与内部调用一致，
包括步骤数组及嵌套对象的长度、类型和未知参数检查。不增加任意 JS、profile/文件/
凭据 API。普通网页内容和截图仍可能包含用户信息；Bearer token 是读取这些数据的
本地能力，不能公开。Broker 仍负责 URL、受保护字段、实时 document 和 observation/ref
的二次校验。

宿主接线契约（已在 side_panel_hook.cc / browser_tools.* 实现；运行验收见 harness evidence）：

```cpp
using Execute = base::RepeatingCallback<void(
    std::string tool, std::string arguments,
    base::OnceCallback<void(uint32_t, std::string)> completion)>;
using CancelTool = base::RepeatingClosure;
// 原有四个参数之后增加可选 Execute、CancelTool。
AgentGateway(port, token, submit, cancel, execute, cancel_tool);
// catalogue 项包含 name、description、inputSchema。
static base::ListValue BrowserTools::ToolCatalog();
static bool BrowserTools::ValidateArguments(std::string_view tool,
                                           const base::DictValue& arguments);
```

Execute 在 UI sequence 运行，必须固定原生目标 view、沿用它的 BrowserTools、与
SDK 运行互斥；只读调用可直接进入 Broker，所有变更必须先进入原生 UI 确认。
原生确认应绑定具体参数与文档，变更后失效。外部协议不能批准自己。completion
必须只调用一次（包括拒绝、view 销毁、取消和错误），并在取消时完成清理后再回调。
状态 0 表示工具返回成功，非 0 映射为 MCP `isError: true`；Broker 的 dispatched /
verified=false 原样保留在文本 JSON 中，不等同业务完成。CancelTool 只能清理本次
直接工具及其待确认 UI，绝不能调用 SDK Stop 或取消用户/其他请求。

全 gateway 只有一个直接工具 lane；跨 session 调用在占用期间返回 busy。
待用户确认时 tools/call 保持未完成，最长 60 秒，不伪造 pending Task 或完成。
同 session、同 requestId 的取消通知才有效；断连、session DELETE、60 秒期限或
宿主关闭也请求取消。已派发操作可能产生副作用，取消/超时响应明确标为
`isError`，文本内容是 JSON 对象，`status` 为 cancelled / timeout（不可确认错误为 unknown），
`outcome` 为 unconfirmed，不声称已经停止或可以安全重试。
取消后 lane 持续保留到宿主 completion 确认清理；宿主失联时保持拒绝新操作，
不冒险复用。请求体上限 128 KiB，参数限制来自共享 schema。原生结果与序列化后的
MCP JSON 响应均有 5 MiB 上限，HTTP send buffer 相应有界扩大。native
`type=image`、`media_type`、`data` 转换为 MCP ImageContent（type=image、mimeType、
data）；文档、tab、viewport 等元数据另放一个 JSON TextContent，不重复 base64。
校验图像 MIME/base64 与 3 MiB 解码上限，避免截断或把图像误当普通文本。
输出溢出返回 `status=unknown`，不将输出丢失解释为可以安全重试。

完成回调先移走 pending 所有权再发送 HTTP 响应，避免发送时断连误取消已完成调用。
取消待确认和 session 终止保留 lane 直到原生清理确认。Close 停止唯一工具定时器，
在 IO sequence 使回调 target 失效，再关闭 transport；MCP completion 与 A2A update
仅持有该 target 的 weak_ptr，晚到回调被忽略，不延长 Server 生命周期或访问已销毁状态。

`tests/integration/mcp_gateway_test.py` 只连接主 agent 构建并启动的实际原生
packaged gateway；未提供 URL/token 时明确 skip，绝不以 Python 模拟产品 gateway。
测试需要 `METABROWSER_MCP_TEST_ISOLATED=1` 显式声明隔离 profile，测试自身不
启动/构建浏览器、不调用付费模型、不访问主 profile。覆盖鉴权/Origin/Host、
session 生命周期、typed schema、只读 Broker 往返、原生待确认不执行、跨 session
不能取消、拥有者取消后释放 lane，以及本地网页没有收到导航。若安装了官方
Python MCP SDK，还直接用其 Streamable HTTP client 验证 initialize/list/call。
取消测试假设无人点击允许，且所有变更均使用原生确认策略。

真实 60 秒期限测试默认不运行；设置 `METABROWSER_MCP_TEST_DEADLINE=1` 后同一测试
命令会执行，要求测试期间不批准原生 UI。尚未提供 packaged gateway URL/token
时，测试套件报告 skip；这不构成编译或原生运行通过的证据。

新增回归定义覆盖 keep-alive 多次调用、旧 requestId 不取消后继 execute、未批准 execute
的嵌套 steps 被接受、真正 pending 的断连清理、完整 catalogue 与生成源一致、共享递归
校验、parse error 和无响应通知。截图用已布置好的隔离 HTTP 页面验证 typed image；
未布置页面时明确 skip。设置 `METABROWSER_MCP_TEST_LARGE_IMAGE=1` 会要求图片超过
旧的 1 MiB 限制（主 agent 应预置噪声图 fixture），测试自身不导航或创建浏览器页面。
官方 Python SDK smoke 测试使用 `ClientSession` + `streamablehttp_client` 直接执行
initialize/list_tools/call_tool；SDK 未安装时明确 skip，不以 stdlib HTTP 测试代替该证据。
