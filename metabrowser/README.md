# metabrowser

ungoogled-chromium（开源 Chromium）+ 内嵌 metacodes AgentCore：浏览器右侧原生侧边栏里的多 session agent，
通过分层、带风险门、全程可审计的工具控制整个浏览器，用来操作电商后台、ERP/CRM 等只有网页界面的业务系统。

- 架构：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · harness（录制→锻造→评估）：[docs/HARNESS.md](docs/HARNESS.md) · 站点包：[docs/SITE_PACK.md](docs/SITE_PACK.md) · 上游同步：[docs/FORK_SYNC.md](docs/FORK_SYNC.md)

![side panel](docs/images/side-panel.png)

## 安装与启动

```bash
pip install -e ./metabrowser                                    # 不再安装或依赖 cloakbrowser
metabrowser browser install                                     # macOS：固定版本 + SHA-256 校验
metabrowser browser status                                      # 显示实际解析的浏览器路径
metabrowser agent build-core --metacodes-src ~/prj/metacodes     # 构建并安装 AgentCore 动态库（需要 Zig 0.16）
metacodes login                                                  # 模型：默认走 metask（复用 metacodes 登录）
metabrowser agent status                                         # 检查：库、provider、凭据来源
metabrowser                                                      # 启动：浏览器 + 侧边栏 + agent
```

已安装 ungoogled-chromium 可直接使用 `metabrowser --browser-path /path/to/chromium`（macOS 可传
`Chromium.app`），或设置 `METABROWSER_BROWSER_PATH`。Linux/Windows 当前使用本机安装的二进制；
自动安装器暂支持 macOS Apple Silicon / Intel，版本与哈希固定在 `src/metabrowser/browser-builds.json`。
启动时不联网校验授权、不自动下载，也不会回退到 CloakBrowser。开发测试可显式选择 `--engine chromium`。

拟人化输入独立保留原 MIT 许可证；不包含 CloakBrowser 的闭源指纹补丁，不承诺通过反机器人检测。
Zig 宿主可行性、真实 CDP 原型和分阶段迁移见 [docs/ENGINE_AND_ZIG.md](docs/ENGINE_AND_ZIG.md)。

凭据来源（按顺序）：`METABROWSER_API_KEY` / provider 环境变量（`METASK_API_KEY`、`ANTHROPIC_API_KEY`、`OPENAI_API_KEY`…）→
metacodes 登录（`METACODES_AUTH_FILE` 或 `$METACODES_HOME`/`~/.metacodes` 的 `auth.json`，只在进程内使用、不刷新、不记录）。
未配置 provider 时：有 provider 环境变量就用它，否则用 metask（`https://napi.metask-ai.com/v1/messages`，bearer）。

模型配置（可选）写在 `~/.metabrowser/config.json`：

```json
{"agent": {"provider": "metask", "model": "claude-sonnet-4-6", "api_key_env": "MY_KEY_VAR",
           "permission_mode": "default", "shell": "sandboxed", "computer_access": false}}
```

`metabrowser serve` 的选项：`--no-agent`、`--no-panel`、`--headless`、`--profile NAME`、`--proxy URL`、`--port N`、
`--site-dir DIR`、`--browser-arg FLAG`。

## 给其他智能体用（MCP）

```bash
metabrowser mcp                       # stdio；连接（或自动拉起）正在运行的 MetaBrowser
metabrowser agent register-mcp        # 让独立的 metacodes CLI 也能用这个浏览器（改 ~/.metacodes/config.json，先确认再写，自动备份）
# HTTP: POST http://127.0.0.1:8765/mcp   Authorization: Bearer <~/.metabrowser/daemon.json 的 token>
```

外部 MCP 额外提供 `agent_run_task`：把整件任务交给内嵌 agent。

## 工具

`metabrowser tools` 列出全部工具（不启动浏览器）。

| 层 | 工具 |
|----|------|
| L1 | `tabs_*`, `page_navigate/snapshot/click/type/select/press/scroll/wait/screenshot`, `page_dialog`, `file_upload`, `browser_permissions`, `page_evaluate`（默认禁用） |
| L2 | `page_read`, `data_extract_table`, `data_collect_pages`, `form_fill`, `net_capture_start/read`, `file_download`, `auth_ensure_login` |
| L3 | `site_run(site, capability, args)`（含新锻造的 skill）、`site_<pack>_<capability>` |
| 锻造 | `recording_list/get/draft`, `site_map_get/update`, `skill_draft_save/test`, `skill_promote`（锻造模式） |

感知基于浏览器无障碍树（含跨站 iframe），动作走 CloakBrowser 拟人化鼠标键盘，不注入页面脚本、不改 DOM。

## 录制 → 生成 skill

侧边栏 **● 录制** → 在页面上操作一遍 → **■ 停止** → 写"这段操作是在做什么？"、站点、skill 名 → **生成 skill**。
锻造会话会参考录制、意图和站点地图起草 skill，在浏览器里用演示参数和变体验证（安全模式，不执行提交/不可逆步骤），
通过后由你在侧边栏批准启用。`metabrowser record list` 查看录制。详见 [docs/HARNESS.md](docs/HARNESS.md)。

## 评估

```bash
metabrowser eval run [--tasks shop.cheapest,ads.yesterday] [--repeat 3] [--model …]   # 真实模型、真实 CloakBrowser
metabrowser eval compare ~/.metabrowser/evals/A ~/.metabrowser/evals/B                # A/B 成对对比
metabrowser eval serve                                                                  # 启动评估用的模拟站点
```

## 站点包、TinyKG、审计

```bash
metabrowser site list | validate DIR | install DIR | kg-export ID | kg-sync ID --store PATH --kg-bin BIN
metabrowser trace list | show FILE [--session S] | verify FILE
```

## 数据位置

| 路径 | 内容 |
|------|------|
| `~/.metabrowser/profiles/<name>` | 浏览器 profile（登录态）；agent 禁读 |
| `~/.metabrowser/agentcore/` | AgentCore 动态库、rg、manifest |
| `~/.metabrowser/traces/*.ndjson` | 哈希链轨迹 |
| `~/.metabrowser/agent/` | AgentCore 工作区 home（会话 journal、artifact） |
| `~/.metabrowser/policy.json` | 浏览器风险规则覆盖，如 `{"rules": {"submit": "allow"}}` |
| `~/MetaBrowser/outputs/` | 报告与下载；agent 默认唯一免询问可写目录 |

## 测试

```bash
cd metabrowser && pytest                      # 需 AgentCore 库的用例在缺库时自动跳过
python tests/e2e/run_e2e.py [--real-llm]       # 真机验收：真实 CloakBrowser + 侧边栏 + 内嵌 agent
```
