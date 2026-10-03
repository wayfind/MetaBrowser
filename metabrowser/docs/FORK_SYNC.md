# 与上游 CloakHQ/CloakBrowser 同步

目标：上游一有更新就能合并，git 尽量自动处理，人工介入只发生在真正的语义冲突上。

## 1. 接触面

MetaBrowser 与上游只在**包装层**接触（Chromium 内核是 CloakHQ 预编译二进制，不在仓库里）。对包装层的依赖只走公开 API：
`launch_persistent_context_async`、`binary_info`、`resolve_human_config`、`CLOAKBROWSER_BINARY_PATH` 等，
集中在 `metabrowser/src/metabrowser/runtime.py`。上游内部重构不影响我们；公开 API 变化只需改这一处。

## 2. 切入点（seams）设计

不是“绝不改上游文件”，而是“只在登记过的切入点改，且改得足够小、足够像追加”：

| 机制 | 作用 |
|------|------|
| `metabrowser/seams.txt` | 允许修改的上游文件清单 + 每个文件的改动行数预算（`-1` = fork 新增文件） |
| `scripts/fork_guard.py` | CI 强制：未登记的上游改动、超预算的切入点直接失败 |
| `.gitattributes` `merge=union` | 追加型文件（如 `.gitattributes` 本身）双方都往末尾加行时自动合并成并集 |
| `.gitattributes` `merge=ours` | fork 自有文件（如 `.github/README.md`）若上游也新建，保留 fork 版本 |
| `git rerere` | 人工解决过一次的冲突，下次同样冲突自动复用（`sync-upstream.sh` 自动开启） |
| 合并而非变基 | 保留 3-way merge 基线；每日小步合并，冲突面最小 |

当前切入点：`.gitattributes`（5 行，追加）、`.github/README.md`（fork 主页，GitHub 优先展示它）、两个 fork 专用工作流。

新增切入点的原则：
1. 先尝试在 `metabrowser/` 内通过公开 API 实现；
2. 其次向 CloakHQ 提 PR（例如 `bin/cloakserve` 写死的 `--disable-extensions` 若需要可配置）；
3. 必须改上游文件时：改动放在文件末尾或独立的块里、不重排上游代码、登记到 `seams.txt` 并说明原因。

已验证：在仓库副本里模拟“上游同时改 README 并向 `.gitattributes` 末尾追加”，`git merge` 全自动完成、fork-guard 通过；
不加 `merge=union` 时同样场景会冲突（这正是该规则存在的原因）。

## 3. 日常操作

```bash
metabrowser/scripts/sync-upstream.sh            # fetch + merge upstream/main + fork-guard
metabrowser/scripts/sync-upstream.sh v0.5.12    # 合并某个发布 tag
cd metabrowser && pytest && python tests/e2e/run_e2e.py
```

自动化：`.github/workflows/upstream-sync.yml` 每天检查上游，有新提交就推 `upstream-sync/<sha>` 分支并开 PR；
`.github/workflows/metabrowser.yml` 在 PR 上跑 metabrowser 测试与 fork-guard。

## 4. 注意

- 上游 `ci.yml` / `publish.yml` 原样保留；不要在 fork 上打 `v*` tag（会触发上游发布流程），MetaBrowser 用 `metabrowser-v*`。
- 上游升级浏览器二进制版本后跑一遍 e2e：侧边栏打开方式、跨站 iframe 隔离、humanize 行为都依赖二进制。
