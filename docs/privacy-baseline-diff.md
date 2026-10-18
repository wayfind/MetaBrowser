# 同版本官方基线全表面对比（v20m vs CfT 154）

状态：2026-10-18 首次完成采集与逐项分类，找出 5 项需要改引擎的残差（R1–R5）。
**同日 v20n 候选修复了这 5 项，基线对比复测通过；v20n 尚未安装或交付**（见文末「v20n 修复」）。
这次对比只证明「和同版本官方 Chrome 的差异已列全并分类」；57 项总账、P1–P14、A–L 仍未完成。

## 方法

`tests/integration/baseline_surface_runner.py` 有界面运行三种配置，每种用全新 profile 跑两次，
都打开同一个本地自有 origin。三种配置是：

| 配置 | 程序 | 额外参数 |
| --- | --- | --- |
| official | Chrome for Testing 154.0.8037.92 | 无 |
| candidate_off | v20m（framework `d18a79b5…`） | `--metabrowser-privacy=off` |
| candidate_identity | v20m | 身份子进程参数：`native-macos-arm64-v1` 模板、版本策略 major、WebRTC 策略 |

三者都带 `--accept-lang=en-US,en`、`--window-size=1200,900`。

`baseline_surface_probe.js` 在 Window、iframe、Dedicated/Shared/Service Worker 五个上下文中采集：

- navigator 全部属性，UA-CH 全部高熵值；
- 全局对象，约 60 个接口的成员；
- JS 内建对象、Math、Intl；
- 硬件、权限、存储；
- WebGPU；
- 编解码器、MSE、MediaRecorder、MediaCapabilities、RTP 能力；
- 语音、字体、显示；
- 插件，Canvas/音频/WebGL。

fixture 按原始顺序记录导航请求头，以及主文档发出 Accept-CH 之后子请求的 Client Hints。

分类规则是机械的：

- 同一配置两次结果不同，记为 dynamic；
- 只差 .97/.92 版本号，记为 version_skew；
- official = off ≠ identity，记为 privacy_intended；
- official ≠ off = identity，记为 build_residual。

之后再逐项人工复核。

证据：`out/evidence/baseline-surface-v20m-cft154-r2.private.json`（runner `4d83726b…`，probe `a1806727…`）。
r1 的字体检测有误：单独写 `monospace` 时字号不同，导致所有字体都被判为存在。r1 原样保留，结论以 r2 为准。

## 结果

每次运行约 17 600 个表面值，其中 17 558 个三方完全相同。差异 35 行，复核结论如下。

### 一致，无残差

- navigator 其余属性、UA 字符串、brands（CfT 与 v20m 都只有 Chromium）；
- 插件与 MIME；
- 全部编解码器、MSE、MediaRecorder、MediaCapabilities 与 RTP 能力；
- 五个上下文的全局对象与约 60 个接口成员；
- JS 内建对象、Math 22 项、Intl 选项与可选值；
- 权限状态、存储配额；
- WebGL 参数、精度、扩展（调试扩展除外）；
- 导航请求头的顺序与取值，以及其余低/高熵 Client Hints；
- 字体：34 个 macOS 自带字体，没有任何 Windows/Linux 字体。

### 差异但无害

| 表面 | official / off / identity | 结论 |
| --- | --- | --- |
| uaFullVersion、full-version-list | .92 / .97 / .97 | 两个都是官方 Mac Stable 发布版本（chromiumdash）；目前 Stable 已到 .100，需要跟进版本 |
| platformVersion（JS 与 Sec-CH） | 26.5.0 / 26.0.0 / 26.0.0 | 默认 major 策略（SRC-1.4），关闭隐私时也生效；macOS 26.0 用户真实存在 |
| innerWidth、Viewport-Width | 1200 / 674 / 674 | 产品界面：原生侧边栏停靠约 526px；CfT 的提示栏占了约 48px 高度。不是引擎残差 |
| screen 1680×1050、availTop 24 | 真实 1920×1080 | 身份模板，DPR 保持 1，窗口尺寸能放进屏幕，合理 |
| hardwareConcurrency | 16 / 16 / 8 | 身份模板（8 核 M 系列），单独看合理 |
| Canvas、OfflineAudio 哈希 | 每个 profile 不同 | 按 profile 种子加噪；同一身份跨重启稳定（见隔离验收和 100 次冷启动） |
| connection.downlink/rtt（off） | 每次运行不同 | 真实网络估计，属于动态值 |

### 残差：需要改引擎

| 编号 | 表面 | 现象 | 修复方向 | 总账 |
| --- | --- | --- | --- | --- |
| R1 | deviceMemory 与 Device-Memory/Sec-CH-Device-Memory | 身份模式仍报真实的 32，而模板是 8 核；8 核 Apple 芯片（M1/M2/M3）最大 16/24/24 GB，这个组合不存在 | 从模板推导一个一致的值，JS 与 HTTP 同源 | SRC-4.4 |
| R2 | NetworkInformation 与 ECT/RTT/Downlink | 身份模式 JS 固定为 rtt 0、downlink 10，HTTP 却发真实估计（100、1.5），两层能被交叉比对；rtt 0 配 4g 也不常见 | JS、Worker 与 Client Hints 共用同一份按 Chrome 规则取整的值 | SRC-13、SRC-1.4 |
| R3 | speechSynthesis.getVoices() | 身份模式只剩 1 个语音，真实 macOS Chrome 约 180 个 | 按模板系统暴露一份 macOS 原装的语音清单 | FINGERPRINT-RESIDUALS |
| R4 | WEBGL_debug_renderer_info（WebGL1/2） | 身份模式直接删掉这个扩展；官方 Chrome 一直提供，缺失本身就是特征 | 保留扩展，返回与模板一致的 ANGLE Metal 字符串 | SRC-2.2、SRC-2.3、GPU |
| R5 | WebGPU adapter | 身份模式去掉 subgroups、timestamp-query，architecture 为空，subgroup 尺寸为 0；真实 154 在所有 Apple Silicon 上都是 metal-3、32、两个特性都有 | 报告 M 系列通用值（这些值本来就区分不出具体芯片） | GPU |

## 未覆盖

- CfT 不是带品牌的 Google Chrome：真实 Stable 的 brands 有 "Google Chrome"，还带 Widevine 等组件。v20m 和 CfT 一样只报 Chromium，要不要冒充 Google Chrome 品牌，需要产品决定。
- 只测了 native-macos 模板、这台 Mac、一个窗口尺寸、有界面单窗口。
- 用户自装字体会不会被屏蔽，这次测不出来（本机没有额外字体），需要装测试字体后再验（SRC-7.1）。
- 没有覆盖真实权限授予、设备、媒体采集、WebRTC 候选地址、跨系统模板，以及 GPU 实际渲染能力。

## v20n 修复

v20n 是在 v20m 源码上增量编译的候选：framework 从 `d18a79b5…` 变为 `4523e8bc…`，只改了下面 9 个 Chromium 文件。
引擎应用 352 项中只有 framework 不同；完整候选 `out/mac-privacy-v20n-sdk-candidate` 共 373 项，SDK 与插件沿用 v20m 的同一份。
构建前，H200 上的 v20m 构建现场已备份到 `/data/metabrowser/backups/v20m-pre-v20n`。
新脚本放在 `/data/metabrowser/staging-v20n/project`，原有的 `/data/metabrowser/project` 和各个历史 reference 都没有改动。

| 编号 | 修复（受保护身份） | 实现位置 |
| --- | --- | --- |
| R1 | `deviceMemory = min(真实值, 2 GiB × 核心档位)`，JS、子资源 Client Hints、导航 Client Hints 同源 | `NavigatorBase::deviceMemory`、`FrameFetchContext`、`client_hints.cc`；规则在 `metabrowser_persona_runtime.h` |
| R2 | NetworkInformation 与 ECT/RTT/Downlink 统一为 4g / 50 ms / 10 Mbps（按 Chrome 取整规则的常见快速网络） | `network_information.cc`、`FrameFetchContext`、`client_hints.cc` |
| R3 | 保留系统语音的真实名称和 URI，只隐藏用户下载的 Enhanced/Premium 语音 | `speech_synthesis.cc` |
| R4 | 保留 `WEBGL_debug_renderer_info`，renderer 按 GPU 家族归并（M1、M2、M3 及以后报 M3，去掉 Pro/Max/Ultra）；识别不出 Apple Silicon 时仍隐藏扩展 | `webgl_rendering_context_base.cc` |
| R5 | 保留 `timestamp-query`、`subgroups`、subgroup 宽度；Apple 返回 `metal-3`；只隐藏两个开发者开关特性 | `gpu_adapter.cc` |

复测证据：`out/evidence/baseline-surface-v20n-cft154-r2.private.json`。runner 新增了 Accept-CH 之后的第二次导航，用来覆盖浏览器进程的 Client Hints；同一 runner 复测的 v20m 对照是 `-v20m-cft154-r3`。

- 语音、WebGL 扩展清单与 vendor、WebGPU 特性和 adapter 信息：三方完全一致。
- 身份模式下 `deviceMemory` 为 16，JS、子资源和导航三处一致；rtt 50、downlink 10、ect 4g，三处一致。
- v20m 的导航 Client Hints 仍发真实值（32 / 100 / 1.5），v20n 已修正。
- 关闭隐私时两版都照常发真实值。
- renderer 为 `ANGLE (Apple, ANGLE Metal Renderer: Apple M3, Unspecified Version)`，真实设备是 M4 Max。
- 其余差异与修复前相同，均已分类为无害。
