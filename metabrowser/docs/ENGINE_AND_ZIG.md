# 开源引擎与 Zig 宿主

## 已完成的引擎替换

默认引擎为 ungoogled-chromium，完整产品仍运行在已有 Python daemon 中。
浏览器侧边栏仍是原来的 MV3 `chrome.sidePanel`，其中运行嵌入的 MetaCodes AgentCore 会话；
没有新建 Electron 壳，没有改成单独的 MetaCodes 网页，也没有换掉录制、站点包、审批或审计。

`engine.py` 负责浏览器解析、启动和 Playwright driver 生命周期：

- `--engine ungoogled` 是默认值，找不到时明确失败，绝不按安装情况暗中选 CloakBrowser。
- `--browser-path` / `METABROWSER_BROWSER_PATH` 优先；允许可执行文件或 macOS `.app`。
- 其次查固定版本的托管目录、macOS 用户/系统 `Chromium.app`、PATH 上命名为 ungoogled 的可执行文件。
  用户安装的 `Chromium.app` 与显式路径属于用户选定来源，无法凭 Chromium 品牌字符串判断是不是 ungoogled；
  要获得明确来源保证请用托管安装。
- `metabrowser browser install` 显式安装：官方 macOS 项目、固定版本、固定 SHA-256、只读挂载、
  保留签名拷贝、临时目录完成后原子移入托管目录。`--archive` 允许离线 DMG，仍校验哈希。
- 首次安装可以联网下载；已安装浏览器的启动没有许可证验证、遥测或商业并发会话限制。
  “没有商业限流”不代表目标网站、模型 API 或本机资源没有限制。
- 自动安装目前支持 macOS arm64/x86_64；Linux/Windows 使用本机安装的 ungoogled-chromium。
  不把未经核实的社区构建自动写进发布清单。
- `--engine chromium` 为显式开发/测试选项，使用 Playwright 自带浏览器。
  eval 的旧 `auto` 现在只是 ungoogled 的别名；`--chromium` 是 `--browser-path` 的兼容别名。
- `mcp` 自动拉起 daemon 时传递 engine/path/profile/headless/proxy/humanize/browser flags/site dirs，
  避免 CLI 看似选中了内核但子进程没有使用它。
- Python 产品依赖仅为 Playwright/aiohttp；拟人化输入从 MIT wrapper 独立提取到 `human/`，
  许可证和快照来源保留在 `human/LICENSE` / `human/NOTICE.md`。

固定版本 `154.0.8037.97-1.1` 的来源：
[官方 macOS 发布](https://github.com/ungoogled-software/ungoogled-chromium-macos/releases/tag/154.0.8037.97-1.1)。
ungoogled 项目允许保留许可条件下的再分发，见
[BSD 3-Clause LICENSE](https://github.com/ungoogled-software/ungoogled-chromium/blob/master/LICENSE)。
分发完整 Chromium 时还须随附 Chromium 及其第三方组件的 notices，不仅是 ungoogled 的 LICENSE。

## 指纹与自动化的实际边界

移除 `--enable-automation`，启用 `--disable-blink-features=AutomationControlled`，原生 sandbox 保持开启；
不自动添加随机指纹、平台伪装、不加载 CloakBrowser license/fingerprint 参数。
拟人化输入保留。`locale/timezone` 是标准 Playwright context 配置，不是隐身内核原生 persona。

真实验收中 `navigator.webdriver` 为 false，证明的是这个标志不存在。
这不等于修复了 `Runtime.enable` 等 CDP 信号、不等于 Patchright，也不承诺通过 Cloudflare/平台反机器人测试。
未默认加入 Patchright，以免未经验证的驱动改动影响录制绑定与 CDP session 生命周期。
Zig CDP 宿主将能控制哪些 CDP 域被启用，但是否规避特定检测仍需实测。

## Zig 可以直接承担宿主

建议最终使用 **Zig MetaBrowser daemon + MetaCodes agent core + ungoogled-chromium 子进程**。
侧边栏 HTML/CSS/JS 继续作为浏览器扩展；移除的是 Python/Playwright/Node 宿主运行时。
Chromium/Blink/V8 仍由上游 C++ 浏览器提供，不用 Zig 重写浏览器内核。

MetaCodes 有两条可用集成边界：

1. **源码嵌入**：固定 MetaCodes commit，以 `metacodes-core` module 和 `agent_session.RuntimeHost`
   组合静态 host tools；与 MetaCodes 的 Zig 类型、allocator 和内核治理保持一致。
   上游 `example/main.zig` 已展示 RuntimeHost、静态插件与会话使用方法。
   发布构建必须固定源码依赖，不能依赖开发机相邻 checkout 的隐式发现。
2. **完整 AgentCore SDK bundle**：通过官方 `sdk/zig` 绑定，链接静态库或经过验证的动态库。
   bundle manifest、哈希、目标、ABI revision、root 与五个 mandatory table 必须一起验证；
   不复制零散头文件，不绕过 Host callback/UI request/permission 边界。

当前 Python host 精确固定 **ABI v1 revision 18**，本机 MetaCodes 源码 SDK 为 **revision 19**。
此次引擎替换继续使用已验证的 rev18 库。Zig 完整宿主应选一个固定坐标，显式迁移并验证，
尤其是 SessionControl 增加 permission mode 更新后表布局变化；不能只改版本数字通过检查。
本文方案没有声称已完成 rev19 AgentCore 集成。

## 已运行的直接 CDP 原型

`native/` 是独立 Zig 0.16.0、libc 的可行性原型（macOS/Linux）：

```bash
cd metabrowser/native
zig build test
zig build run -Doptimize=ReleaseSafe -- /absolute/path/to/chromium /temporary/profile
```

原型直接用 `posix_spawn` 启动浏览器，映射专用 fd 3/4 的 CDP pipe，不开调试端口，不调用 Python/Node。
请求经 null-delimited JSON 编码和有界缓冲；读取支持拆包/粘包，按 request id 匹配，带超时。
它实际执行 Browser.getVersion、Target.createTarget、Target.attachToTarget、Accessibility.getFullAXTree，
从真实网页 AX 树中找到 `MetaBrowser Zig CDP`；最后关闭并回收自己启动的浏览器。

这是传输与感知的可行性证据，不是完整产品。它顺序处理请求并丢弃异步事件；没有 AgentCore、HTTP/SSE、
审批、工具注册、侧边栏服务、跨站 iframe、下载或录制。生产 CDP 层必须保留/分发异步事件，支持多 session
并行请求。Windows 需要独立的 named pipe/继承 handle 实现，不能宣称这个 POSIX 原型已支持 Windows。

## 迁移次序与验收

| 阶段 | 工作 | 验收条件 |
|---|---|---|
| 已完成：换引擎 | 独立启动/安装、保留输入、去商业依赖 | 原产品侧边栏 e2e 与完整工具测试 |
| 已完成：CDP 原型 | Zig 拥有浏览器与私有 pipe、Target/AX | 真实 ungoogled-chromium AX 读取，正常退出，无 Python/Node |
| Zig L0/L1 | 请求路由、target/frame/session 生命周期、导航、AX refs、Input、OOPIF、dialog/upload/download、profile lock、Windows handles | 与 Python actuator 逐项对照，跨站 iframe、导航失效、进程退出、取消与泄漏测试 |
| Zig 宿主 | 固定 MetaCodes 集成、typed host tools、HTTP/SSE/MCP、多会话、审批、Stop、预算、审计 | 同一侧边栏端到端场景、拒绝不可逆动作、异步权限与取消一致 |
| Zig 业务层 | Site Pack、L2/L3 配方、录制 binding、Skill 锻造、TinyKG 与 eval | 既有录制/锻造测试及真实 held-out 参数成功，审计链可验 |
| 完整打包 | native executable + 固定 AgentCore/依赖资产 + Chromium.app + 扩展/站点包/notices | 干净机器离线启动、更新/回滚、签名验证、无 Python/Node 运行时 |

Zig 生产宿主的重要生命周期：

- CDP IO dispatcher 持续运行；AgentCore 每个 Run 在 worker 中执行。同步 host tool callback 通过队列
  向 dispatcher 发请求再等待结果，不能阻塞处理 CDP 响应或侧边栏审批的线程。
- SessionId / TabId / FrameId / RequestId / ApprovalId 使用独立类型；审批绑定 Run generation，
  防止 Stop/导航/会话销毁之后迟到的 UI 响应作用于新任务。
- allocator 按 daemon / session / run / request 分层；跨 callback 数据拥有者明确，取消后仍需先回收
  pending 请求、CDP session、临时 artifact，再释放对应内存。
- 同一个工具 registry、风险门和审计管线服务嵌入 HostTools、侧边栏 API 与 MCP；迁移不改变权限语义，
  不让 UI 或扩展直接绕过风险门发任意 CDP 请求。

暂不修改内核 C++。以后若要原生 WebUI 或进程内 actor，独立评估 Chromium fork 的编译与维护成本；
这与去掉 Python 宿主是不同阶段。

## 本次验证证据

2026-10-14，macOS arm64，官方固定构建 154.0.8037.97-1.1：

- SHA-256 与清单一致，`spctl` 接受、公证来源为 Developer ID。
- `tests/e2e/run_e2e.py`：21 个检查全通过，包括真实 Chromium 原生侧边栏、嵌入 AgentCore、
  多会话、Bash 审批、不可逆退款拒绝、报告写入、录制、Skill held-out 参数验证与审计链。
  模型服务为本地 mock，没有付费模型调用。
- 持久 profile 测试验证显式有效期的登录 cookie 重启仍在；session-only cookie 按 Chromium 正常规则
  处理，不把“持久 profile”解释为所有 session cookie 都必须永久保留。
- 原有 ERP iframe fixture 用 URL token 认证，但详情/翻页/搜索没带 token，第三方 cookie 被阻止后掉回
  登录页。修复的是测试站点的 token 传递，不是放宽真实浏览器第三方 cookie 策略。
- Zig ReleaseSafe 原型通过真实 CDP pipe/AX 检查；有界 framing 的拆包/粘包和超长输入单测通过。
- 完整 Python 工具回归：60 passed / 1 skipped。跳过项为缺少 TinyKG 二进制的 site/kg 同步测试，不能视为已覆盖。
- 独立 wheel 构建包含扩展、站点包、浏览器版本/哈希清单和 MIT notices；全新 Python 3.12 环境只安装
  该 wheel 及其依赖，确认 `cloakbrowser` 不存在、默认路径解析仍正常。
- 在上述无 CloakBrowser 的全新 wheel 环境（Python 3.12 / Playwright 1.64）再次运行完整侧边栏 e2e，
  21 项检查全部通过。这验证了已安装的独立发行包，而不只是 checkout 中源码可运行。

完整产品移除 Python、Zig AgentCore 集成和 native 安装包仍是上述后续阶段，不能把原型当作已经迁移完成。
