# MetaBrowser 换机交接

交接日期：2026-10-17。按用户要求，在当前验证节点停止功能开发，提交、推送并交接。
**原目标尚未完成，不得把此交接当作“全量匿名指纹覆盖通过”。**

## 1. 从哪里继续

仓库：`https://github.com/wayfind/MetaBrowser.git`

**使用 `main` 分支。** 2026-10-18 起 `main` 只包含原生项目：原生历史经无关历史合并并入，
CloakBrowser 叠加方案已放弃并从 `main` 删除，最后状态见 tag `overlay-final`。
`native-agent-browser` 分支保留原生项目的独立早期历史，不再作为开发入口。

```sh
git clone https://github.com/wayfind/MetaBrowser.git MetaBrowser
cd MetaBrowser
git log -1 --oneline
```

旧电脑工作树：`/Users/yuankun/prj/MetaBrowser/.claude/worktrees/metabrowser-native`。
不要把旧电脑主目录 `/Users/yuankun/prj/MetaBrowser` 当成当前原生项目。

先读本文件，再读：

- `docs/ANONYMITY_PLAN.md`：A–L 原始系统范围。
- `docs/privacy-requirements.json`：57 项、P1–P14 总账，仍为 active。
- `docs/privacy-biquad-matrix.md`：最新测试、SDK 集成和剩余缺口。
- `docs/BUILD.md`、`docs/HOST_INTEGRATION.md`、`docs/AGENT_PROTOCOL.md`。

## 2. 已实现与当前可信结论

产品是 Chromium 原生 Views 浏览器，右侧 icon 栏、原生对话与身份配置，Zig 插件内嵌
完整 MetaCodes AgentCore。Python 用于构建/测试，不是产品封装。

固定版本：Chromium `154.0.8037.97`，Zig `0.16.0`，AgentCore SDK
`e3a3b932db606d2f43d7ed3d3112768b3f0afa10`，ABI 1 / revision 21 / table size 64。
锁定信息见 `upstream.lock.json`，不要盲目升级。

最新 v20m：

| 项目 | 实测结论 |
| --- | --- |
| Mac ARM64 framework | `d18a79b5dcc1b68054e153e6d00fba5978d1b0dea385c492ac5ee29029e17b0d` |
| 同源 Linux headless | `d5e59babac65b2a7ba097be10351aadf022213ae21c4b7f69f0b42693b3fda04` |
| Biquad | 八类型，固定/定时变更 96 图、四类退化边界 192 图，288 个完整声道跨 CPU 相同 |
| 频率响应 | 96 组 magnitude/phase Float32 字节相同，包括无效频率 NaN；NaN payload 反例会被拒绝 |
| 平衡隐私元数据 | native 与诊断 Linux 模式各七个 realm 的 HTTP/JS/内存提示/保留对象检查通过 |
| 完整 SDK 候选 | 原生浏览器操作、授权、图片、文件/命令、MCP、Skill、附件、取消续跑、会话与历史恢复通过本地 fixture |
| SDK 合约 | 宿主、图片、Skill 目录、本地 OAuth PKCE/刷新/撤销/恢复通过；实际加载包内 SDK |
| 当前完整包稳定性 | native profile 100 次真实冷启动、正常退出、同身份稳定字段与独立 100 份原始记录复核通过；0 模型 POST、0 付费调用 |
| IDL | 当前构建 18489 个潜在成员，清单完整性通过；12 个成员部分映射，0 个宣称完整验证 |

L2 的静态/动态 HRTF 跨 CPU 72/72、96/96 证据为历史测试，不能冒充 v20m 的全音频验收。
首次完整 SDK fixture 曾快速重试 AX not_ready 而失败，失败证据保留；改为使用现有
有界 `browser_wait` 后通过，没有替换产品执行器或放宽行为断言。

**未验证：** 全参数/异常域/连续自动化、完整实时音频/媒体/WebRTC/设备与漂移、正式
跨系统 profile 激活/缓存隔离、字体/平台/Math/GPU 联合一致性、当前包真实 Metask
账户与网站业务、全部模板组合和七天观察。诊断 Linux template 仍不可供用户选择，
不要仅因音频测试通过就改 `user_selectable`。

## 3. 构建产物和证据在哪里

`out/` 故意不进 Git。仓库为公开仓库；没有上传用户数据、私钥、真实账户凭据或原始
测试档案到 Git。下面是 H200 上的私有交接目录：

```text
/data/metabrowser/handoffs/2026-10-17-v20m/
  handoff-v20m-evidence.tar.gz
  handoff-v20m-sdk-macos-arm64.tar.gz
  handoff-v20m-checksums.json
```

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| handoff-v20m-evidence.tar.gz | 7269729 | `1431225d7c14bcbaa9148ce91390759874a3c22dc6b7d359732f1cfea609d796` |
| handoff-v20m-sdk-macos-arm64.tar.gz | 251194270 | `b041ce2cb438b03c2b68fea8266d79b4af6bb594f1a71354b2b5202a26284afe` |

证据包包含最新 `out/evidence/privacy-v20m-matrix-sdk-review.json` 及其绑定的 479 项。
包括测试输入、原始进程输出、100 次启动记录、SDK fixture 会话和生成的 IDL 清单。
它不等于旧电脑全部约 600 MiB 历史 evidence；更早 review 的递归依赖没有全部打包。
旧报告里的绝对 `/Users/...` 和临时 root 是当时运行位置，不是新机器可直接依赖的路径。
跨平台检查支持显式 archive/probe 路径；重新运行测试须创建新 fixture。

应用包是 **macOS ARM64** 完整 SDK 候选，不是 Linux GUI 或 Intel Mac 应用。
旧电脑位置是 `out/mac-privacy-v20m-sdk-candidate/MetaBrowser.app`。
原有日常 `out/macos-arm64/MetaBrowser.app` 未替换，framework 仍为
`4c6213f10bec9564cac68ef53c8a806251b24f82db378789c2deb8c5cc0356f2`。

## 4. 新机器恢复

`scripts/h200.sh` 已保存可工作的路由，支持 `METABROWSER_SSH_KEY` 等环境覆盖。
新机器的密钥必须已获 H200 和跳板机授权；私钥不会出现在仓库或交接包。

先验证只读 SSH：

```sh
bash scripts/h200.sh 'uname -sm'
```

从任意新 checkout 创建 rsync transport；不要复用旧电脑含绝对路径的 `/tmp` 脚本：

```sh
export METABROWSER_HANDOFF_CHECKOUT="$PWD"
cat > /tmp/metabrowser-handoff-ssh <<'SH'
#!/bin/sh
shift
exec bash "$METABROWSER_HANDOFF_CHECKOUT/scripts/h200.sh" "$@"
SH
chmod 700 /tmp/metabrowser-handoff-ssh
mkdir -p out/handoff-download
rsync -a -e /tmp/metabrowser-handoff-ssh \
  h200:/data/metabrowser/handoffs/2026-10-17-v20m/ out/handoff-download/
```

校验后再解包。Python 3.12+：

```sh
python3 - <<'PY'
import hashlib, json, shutil, tarfile
from pathlib import Path
p = Path('out/handoff-download')
checks = json.loads((p/'handoff-v20m-checksums.json').read_text())
for name, record in checks.items():
    data = (p/name).read_bytes()
    assert len(data) == record['bytes']
    assert hashlib.sha256(data).hexdigest() == record['sha256'], name
with tarfile.open(p/'handoff-v20m-evidence.tar.gz') as t:
    t.extractall('out/handoff-restored', filter='data')
shutil.copytree('out/handoff-restored/out/evidence', 'out/evidence', dirs_exist_ok=True)
with tarfile.open(p/'handoff-v20m-sdk-macos-arm64.tar.gz') as t:
    t.extractall('out/mac-privacy-v20m-sdk-candidate', filter='data')
PY
python3 scripts/app-manifest.py out/mac-privacy-v20m-sdk-candidate/MetaBrowser.app \
  --check out/evidence/privacy-v20m-sdk-app-manifest.json
python3 scripts/check-agentcore-bundle.py \
  out/mac-privacy-v20m-sdk-candidate/MetaBrowser.app/Contents/Resources/agentcore
```

macOS ARM64 可用 `open out/mac-privacy-v20m-sdk-candidate/MetaBrowser.app` 打开候选。
先按需要设置独立 `--user-data-dir`，避免把新候选和真实默认 profile 混为测试 fixture。
新机器重新登录真实 Metask 账户；此交接没有迁移旧机器 Keychain 或登录态。

## 5. H200 构建现场，勿误覆盖

```text
/data/metabrowser/project                                构建脚本副本，不等于 Git 最新分支
/data/metabrowser/source/unpacked/chromium-154.0.8037.97   Mac 交叉编译源码
  out/metabrowser-mac-arm64                              当前 v20m Mac 构建
/data/metabrowser/source/linux-reference-v20h             历史 H，保留
/data/metabrowser/source/linux-reference-v20l2            历史 L2，保留
/data/metabrowser/source/linux-reference-v20m             当前同源 Linux headless，保留
/data/metabrowser/reference/qa-v20m-biquad-response        最终响应字节 Linux 抓取
/data/metabrowser/reference/qa-v20m-biquad-boundary        边界 Linux 抓取
```

编译仅使用 CPU，不能停止或占用 H200 上模型/GPU 服务。上次增量 job 数为 64。
修改前确认远端真实进程，不以旧 status 文件判断任务仍在运行；交接时本轮任务均已终止。
不要原位改动历史 Linux reference 或冻结 QA epoch。构建新引擎前保存当前源码、receipt
和应用基线，使用 GN/Ninja 依赖传播，不手工链接旧 archive。

Zig 插件上次用独立前缀 `out/privacy-v20m-sdk-plugin` 构建。旧 `zig-out` dylib 存在
共享硬链接，禁止原位写入。SDK 可从恢复后的应用 `Contents/Resources/agentcore` 获取。
不要直接运行会覆盖日常应用的 `scripts/package-mac.sh`；先生成独立候选并做用户数据
语义备份。Chromium、账户、身份、对话分别有持久目录，不能只备份 `.app`。

## 6. 下一个 agent 的入口

1. 确认正确分支和本交接；恢复证据/产物，读最新 479 项 review 和 57 项总账。
2. 优先推进正式 profile 激活/隔离与跨系统字体/API/Math/GPU 联合一致性，避免继续
   无限扩展单一音频样例来替代完整产品目标；IIR/连续自动化/实时设备链仍是明确缺口。
3. 继续以真实浏览器验证新改动；保留失败原始证据，严禁把重试/超时或空采集算通过。
4. 真实账户/网站和七天观察按实际时间与授权执行，不能由 loopback fixture 或快速
   循环代证。所有 SDK/模型测试默认本地 fixture，禁止偷偷使用付费模型。
5. 本轮源码和候选不需要重新从零编译。先复用已校验构建，必要时再增量构建。

新机器接手补充：原生 profile 的全新 fixture 验收入口见
`docs/privacy-profile-isolation.md`。2026-10-17 已在新 Mac 上恢复并校验 v20m 交接包；
真实浏览器首轮失败（记录保留），修正 fixture 重放与语言断言后第二轮和独立重验通过。
范围仅为两个 native macOS 身份、一个 origin、一次冷重启，不代表正式跨系统激活。
本机跑原生 UI 验收前，须给 Claude Code 的 `claude` 进程开启辅助功能权限。
2026-10-18 同版本官方基线对比见 `docs/privacy-baseline-diff.md`：列出了下一轮引擎要修的
5 项身份残差 R1–R5（deviceMemory、网络信息 JS/HTTP、语音、WebGL 调试扩展、WebGPU）。
同日 v20n 候选已修复这 5 项（framework `4523e8bc…`，未安装）：Mac 候选在
`out/mac-privacy-v20n-sdk-candidate`，审查记录是 `out/evidence/privacy-v20n-review.json`。
H200 上的 v20m 构建现场备份在 `/data/metabrowser/backups/v20m-pre-v20n`；v20n 脚本在
`/data/metabrowser/staging-v20n/project`，原 `/data/metabrowser/project` 未动，H200 构建目录现在是 v20n。
基线对比、身份表面五模式、GPU/媒体 109 项、隔离验收和 100 次冷启动（含独立重验）都已通过；
字体 fixture 五模式和显示授权 fixture 尚未重跑。
2026-10-19 v20o 候选（framework `54cf8f09…`，未安装）修复了 WebRTC 零候选的问题（R6），候选在
`out/mac-privacy-v20o-sdk-candidate`，审查记录是 `out/evidence/privacy-v20o-review.json`；v20n 构建现场备份在
`/data/metabrowser/backups/v20n-pre-v20o`。v20o 的基线对比、WebRTC 对比、身份表面、GPU/媒体 109 项、
Mac 五模式、显示授权、隔离验收和 100 次冷启动全部通过。五模式要用 1 em 合成金丝雀字体；显示授权用
`tests/integration/display_permission_runner.py`（会开启 CanvasHDR）。
2026-10-19 v20o 已安装为日常版 `out/macos-arm64/MetaBrowser.app`（`scripts/run-mac.sh` 启动它，使用默认数据目录）。
原日常版 v18b 和数据备份在 `~/Library/Application Support/MetaBrowser-backups/before-v20o-20261019-152759`，
附逐文件哈希清单；钥匙串条目不在备份范围内（当时未发现 MetaBrowser 条目）。

TinyKG（若新机器已配置）：项目 13068，主范围 13125，分支 13147，当前任务 13161，
最新开发验证 13185。使用 canonical TinyKG，不创建项目级 `.kg`，不要仅依赖旧记忆
而跳过当前文件/进程核验。没有 TinyKG 时，本文件及 Git/证据包足以恢复工作。
