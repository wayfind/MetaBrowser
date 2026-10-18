# 原生 profile 激活与隔离验收入口

状态：采集器、验收器和本地合约检查已实现。**v20m 首轮真实运行（2026-10-17）未通过**，
记录见 `out/evidence/identity-isolation-v20m-first-analysis.json`，fixture 已保全：
`navigator.languages` 实测仅主语言（与 v20m 冷启动证据一致，验收器预期写成了完整列表）；
A 正常退出后重开会恢复上次标签页，旧页面重跑 probe，污染了重启前的存储与 SharedWorker
观测。两者均为同一身份内问题，未见 A/B 串号。之后按下文修正了 fixture 和语言断言，
首轮记录原样保留，不按新规则重新判定。

**v20m 第二轮（同日）通过**，runner 与独立重验（原路径和保全副本）均为 0 退出，
记录见 `out/evidence/identity-isolation-v20m-second-review.json`。重启时恢复出来的
`a_live` 旧页面被拒绝 1 次，重启后的 A 从空的 SharedWorker 内存开始，持久存储读回 A。
结论仅限下文的有限范围。
这不是正式跨系统 persona 激活的实现，也不改变 Linux 模板的 `user_selectable=false`。
57 项、P1–P14、A–L 总范围继续开放。

旧 `identity_lifecycle_test.py` 依赖旧电脑的 evidence、fixture 和 `/tmp` 可执行文件，
主要验证时区、Canvas 和进程回收。新入口每次创建全新私密 fixture，显式接收应用、
完整 transport manifest 和原生 AX helper，不复用旧电脑绝对路径。

验收从浏览器账户设置原生 UI 创建 A，设置英语和纽约时区，打开 A 写入仅属于测试的
随机标记；再通过同一 UI 复制配置生成 B。在同一 loopback origin 上执行：

1. A 首次访问：Cookie、localStorage、IndexedDB、CacheStorage、OPFS 条目为空，写入并读回 A。
2. B 首次访问：上述条目和 ServiceWorker 注册为空；三个 Worker 读取 B 的存储。
3. A 与 B 同时运行后重访 A：A 的原标记、HTTP 缓存资源和 Canvas 输出保持一致。
4. 原生退出并观察子进程被父进程回收，再重新打开 A：持久数据、注册、缓存资源、
   Canvas 和隐私 root 摘要保持一致。B 的 root、缓存资源、Canvas 与 A 不同。

Dedicated/Shared/ServiceWorker 分别读取自身上下文的 IndexedDB、CacheStorage 和 OPFS；
SharedWorker 还检查 B 没有加入 A 的内存状态，重启后的 A 也必须从空内存开始。

语言按引擎既有行为分层断言：每次导航的 HTTP `Accept-Language` 必须是完整的
`en-US,en;q=0.9`（由 fixture 记录并写入原始报告），JS `navigator.languages` 只暴露主语言
`['en-US']`。这与 v20m 冷启动证据一致。2026-10-18 用
`tests/integration/language_baseline_probe.py` 对照官方 Chrome for Testing 154.0.8037.92：
四组语言设置下 HTTP 与 JS 取值和 v20m 完全相同，列表长度不同是官方 154 的既有行为，
不是隐私残差（证据 `out/evidence/language-baseline-v20m-cft154.private.json`，仅 headless）。

身份正常退出后重开会恢复上次的标签页。每个 run 上报后，fixture 不再提供该页面
（返回 410），并在 `refused_replays` 中记录，避免旧页面重跑 probe、在重启观测前改写
存储。被拒绝的 run 必须是本次已上报的步骤；是否发生恢复不作为通过条件。

复制时单独确认 B 尚无 browser、account、
conversations、workspace 数据目录。整个流程不打开 Agent 对话或发送提示；父窗口的模型
端点指向拒绝服务，任何模型 POST 都使验收失败。

子身份不是 Python 的直接子进程：证据记录原生退出请求、实际进程消失、父进程存活和
重启后的数据；不虚构子身份退出码。父浏览器退出码必须为 0，强制清理不能计作通过。
失败原始报告保留，现有输出拒绝覆盖。验收器逐份重读原始报告、核对摘要并独立检查
语义；仅修改摘要、同时篡改原始与汇总、空采集、模板越权和完整覆盖声明均不能通过。

## 执行

先依照 [HANDOFF.md](../HANDOFF.md) 恢复并校验应用与证据。需要 macOS ARM64 和原生
Accessibility 操作权限；未恢复应用时命令明确失败，不生成浏览器通过记录。

```sh
mkdir -p out/qa-tools
xcrun swiftc tests/integration/panel_ui.swift -o out/qa-tools/profile-ui
uv run --no-project --python 3.12 python tests/integration/identity_isolation_runner.py \
  --app out/mac-privacy-v20m-sdk-candidate/MetaBrowser.app \
  --manifest out/evidence/privacy-v20m-sdk-app-manifest.json \
  --ui-helper out/qa-tools/profile-ui \
  --output out/evidence/identity-isolation-v20m-first.private.json
```

独立重验：

```sh
uv run --no-project --python 3.12 python tests/integration/identity_isolation_acceptance.py \
  out/evidence/identity-isolation-v20m-first.private.json \
  --app out/mac-privacy-v20m-sdk-candidate/MetaBrowser.app
```

跨机转移时，保留私密 fixture 原始文件，使用 `--fixture-root` 指向恢复后的目录，
`--probe-dir` 指向冻结的 probe 源码快照。原报告、摘要及进程路径保持原样，不得把
重新定位误写成新执行。

本地检查仅验证校验器的反例拒绝和真实 loopback 服务，不产生产品运行证据：

```sh
uv run --no-project --python 3.12 python tests/integration/identity_isolation_contract_test.py -v
```

本入口范围有限：两个 native macOS 身份、一个测试 origin、一次冷重启和列出的存储出口。
跨站分区、全部权限/API/模板组合、跨系统字体/Math/GPU、真实账户业务、100 次重启及
七天观察仍须分别执行，不由此入口代证。
