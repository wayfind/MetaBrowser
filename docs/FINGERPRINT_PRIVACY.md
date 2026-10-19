# 指纹隐私实施规格

状态：**首版原生隐私引擎已交付；全局身份管理与时区配置已交付；完整跨平台/GPU 虚拟身份与目标网站业务验收仍未完成。** §6 的生命周期结论仅适用于首版隐私引擎，不包含后来新增的身份窗口启动与进程回收。身份回收补验发现的同步等待权限断言已修复并完成实际 macOS 生命周期验收，见 §9.3。首版引擎 framework SHA-256 为 `082a8ddf0fd449cfdfe88358c7d6fc894c2e4af85fc1ba8b2e716bdae9728dd3`，仅作该版历史标识；当前安装版本以完整应用 manifest 和对应交付收据为准。

## 1. 目标与边界

目标是降低跨站可关联性，同时保留用户登录、授权、网页功能与浏览器安全语义。账户登录、站点自有标识及出口 IP 仍可能关联用户；不能承诺匿名、不可检测或不触发风控。

实现采用 browser/embedder、Blink 及必要的原生读取路径；不注入页面 JS hooks，不补丁 `Function.prototype.toString`，不合成用户行为、验证码结果或站点安全 token。真实 Chromium 网络栈是基础，不等于与官方 Chrome 全字段相同。

## 2. 身份与生命周期契约

| 对象 | 必须满足的契约 |
|---|---|
| 普通 profile | 独立、随机、持久化的私密根密钥；禁止机器全局 seed、从硬件标识推导或跨 profile 复用。根密钥不得进入页面、日志或 probe 产物。 |
| Site key | 顶层 schemeful site，按 Chromium 的站点/公共后缀规则生成，不自行截取域名。用于划分隐私作用域，不表示同站 origin 可以互读存储。 |
| 派生域 | 设计形态为 `KDF(profile_secret, site_key, partition_context, api_domain, policy_version)`；使用无歧义编码和域分离。API 类别独立派生，禁止直接暴露 seed。 |
| 第三方上下文 | 使用浏览器验证的顶层 site 与存储分区上下文，并在需要时纳入调用 origin；同一第三方嵌于不同顶层站点不得共用身份。不得放宽 SOP 或现有存储分区。 |
| 普通重启 | 同 profile、同作用域、同策略版本的受保护静态输出稳定；不因请求、刷新、导航、IP 改变或风控响应轮换身份。 |
| OTR/无痕 | 与普通 profile 完全不同的内存根密钥；同一 OTR 生命周期内共享其正常分区语义。最终 OTR 上下文销毁时清除，重新创建后使用新根；不写回普通 profile。 |
| 显式重置/升级 | 不在运行中静默换身份。策略迁移需版本化、评估兼容性并明确生命周期；影响身份的重置由用户显式触发，不附带清除登录或权限。 |

密钥和作用域由 browser process 决定；renderer 只能获得最小派生材料，不能自行声明顶层 site。opaque origin、sandbox、worker、跨站导航与进程复用须单独定义映射和销毁规则；未定义前不得声称跨上下文覆盖完成。

用户通过 Storage Access API 授权的非分区 SharedWorker 遵循该共享 realm 的真实第一方 StorageKey，不能为每个嵌入站点提供不同身份或兼容性例外；这与手动关闭第三方分区一样，不属于逐顶层站点隔离的保证。保护不撤销或伪造已有授权。默认分区 worker、授权共享 worker 与手动关闭分区必须分别验收，不能互相替代证据。

新引擎默认使用 balanced 策略，受 profile 的 enabled 偏好控制；显式 `--metabrowser-privacy=off` 用于基线对照。browser 从 profile 私密根、顶层 site、请求 origin 与实际 storage partition 上下文进行 HMAC 派生，向 renderer 的隐私传输仅发送最小派生材料，开关不携带密钥。原生配置页的全局切换和当前网站兼容模式已通过重启及恢复验收。更改后需要重启浏览器，确保已有 SharedWorker/ServiceWorker 等也退出后采用新策略；不承诺仅刷新网页即可切换所有旧上下文。受保护的 opaque/nonce 上下文使用每上下文临时值，不继承父站身份。

根密钥不进入 renderer 是必须维持的边界，不能仅凭 settingsPrivate 未允许该偏好就宣称已满足。源码审查确认 `chrome://prefs-internals` 的全量及单键诊断原先会输出该注册偏好；现已编译仅针对 `metabrowser.privacy.root_secret` 的原生脱敏补丁，不清除或轮换存储的根、不禁用其他偏好诊断。最终构建的两个诊断 URL 已在隔离 profile 运行验收：单键返回固定 `[redacted]`，汇总中根键及其值均不存在，其他隐私偏好可见，磁盘原根仍保留。证据：`out/evidence/privacy-diagnostics-runtime.json`。这验证了已知诊断出口，不代替对未来新增出口的审查。

## 3. 用户状态与真实能力

- 保留 cookie、localStorage、IndexedDB、登录会话、passkey 和用户允许/拒绝记录；不得为“新设备”效果自动清理、迁移或伪造它们。新建 profile 正常隔离，不继承另一个 profile 的授权。
- 权限查询与实际能力使用同一权威状态，遵守安全上下文、Permissions Policy、用户选择和企业策略；不统一返回 `prompt`，不伪造 `granted`。
- 品牌如实标识产品；平台及版本与实际支持的构建一致。保留正常 reduced UA（例如 `Chrome/136.0.0.0`），完整版本与 UA-CH 同源；不恢复高熵字段来“修复”正常 reduction。
- 首版跟随原生 OS/GPU。后续按 §9 实现用户要求的跨平台/GPU 虚拟身份；不能仅修改字符串就声明实现。未安装/未授权的 DRM、编解码器、扩展和硬件能力不得声明可用。降级声明必须同时约束真实能力与调用结果。
- `webdriver` 遵守上游自动化状态与产品明确的控制模式；连接 CDP 不等于必然为 true，也不以强制 false 作为隐私验收。
- `maxTouchPoints` 取决于真实设备能力，不把 Windows=256、移动端固定触点数作为规则。Battery API 是否可用按构建、上下文和策略探测，不假定桌面 Chrome 已移除。
- 时区、语言、窗口和网络保持用户选择及正常变化；不因出口 IP 自动改动用户环境。跨国 IP 与时区不同不是必然错误。

## 4. 保护机制与支持状态

下表区分已构建并通过限定运行时验收的保护、上游基础与未完成工作。已通过项只适用于所列 API、上下文和测试条件，不代表全 API 指纹保护。

| 机制 | 上游能力/限制 | 本项目阶段与实施约束 |
|---|---|---|
| API 阻断 | 部分 API 有原生权限、内容设置或 policy 门控；不存在通用无损开关。 | 已实现下述 WebGL 扩展限制与 Canvas 预算拒绝；其他 API 不作通用阻断声明。拒绝结果须遵守规范，不能只隐藏 getter 而保留旁路。 |
| 信息最小化 | UA reduction、部分信息量化和能力限制已有上游机制。 | WebGL debug renderer 扩展限制已构建并通过限定运行时验收；扩展枚举与获取一致。其余新增最小化仍待逐项实施。 |
| Seed 噪声 | 上游 `NoisePixels` 可作 Canvas 处理基础，不等于完整站点隔离策略。 | Canvas 8-bit RGBA 与 OfflineAudio 已构建，browser 派生材料传输及限定生命周期矩阵已通过验收。精确算法与限制见下文。 |
| GPU/字体/音频 | 字符串、参数、实际渲染和读取结果有关联，但单个参数不能描述全部硬件行为。 | 不计划以改字符串、固定音频和值或字体度量表假冒平台。软件渲染也不承诺跨平台逐字节相同。 |
| WebRTC | mDNS 可隐藏部分 host 地址；权限和策略影响候选，STUN/public IP 与代理旁路另需处理。 | 默认公共接口、严格 UDP 限制及兼容策略已有受控 STUN 验收（§10）；v14 额外验证兼容策略下、无外部 STUN/TURN 的本地双 peer 视频传输。不能把 mDNS 当完整防泄漏。 |
| TLS/H2/H3 | 使用真实网络栈，但构建、特性、随机化、连接状态及代理会改变观测。 | 保留原生实现为目标，不伪造握手。按协议语义和规范化分布验收，不要求原始 JA3 或握手逐字节相同。 |

任何噪声不得逐调用随机，不得积累修改底层内容，也不得改变页面显示、音频播放或截图含义而不说明。立项时需覆盖部分读取、重复读取、复制/编码及离屏路径，防止不同 API 输出互相矛盾。原生实现仍需测试属性描述符、异常和副作用，不能以 `[native code]` 证明正确。

### 4.1 历史首版范围（Mac v10 的新增覆盖见 §10）

- **Canvas：**只覆盖已接入的 8-bit RGBA 路径。在完整图像副本上使用内容派生 seed 调用上游 `NoisePixels`，随后恢复原 alpha；先处理完整图像再裁剪，避免对同一图像的不同裁剪独立加噪。不得把噪声写回原始画布。
- **Canvas 预算：**完整图像最多 `4 Mi` 像素（4,194,304），每维不超过 16,384，scratch 预算小于 `21 MiB`。`getImageData` 对预算/可恢复分配失败返回 `NotSupportedError`，不以无噪声结果静默降级。可恢复分配使用 try-allocation；**上游逐行 `std::vector` 分配仍有 fatal OOM 残余**，不能声称全部内存失败均可恢复。
- **WebGL：**隐藏 debug renderer 扩展，并保持扩展枚举、获取及相关查询路径一致；不伪造 GPU 型号，保留真实 GPU 能力与正常渲染。此项是信息最小化，不能阻止其他参数或渲染结果推断硬件。
- **OfflineAudio：**对离线结果执行一次处理，不在每次读取时重复叠加；浮点改变量绝对值不超过 `1e-7`，零值保持，有限性保持。不以固定探针和值替代真实音频计算。

以上噪声为 **best-effort**：没有证明抵抗 chosen-content（攻击者选择输入）或多次测量平均/重建攻击。内容派生 seed、微小幅度或重复读取一致均不能单独证明这类抵抗能力。

### 4.2 历史首版边界（Mac v10 更新见 §10）

**未保护：**HDR/float16 Canvas、WebGL 原始 `readPixels`、字体及文字度量、实时 Audio、WebGPU、worklet 等未接入路径。不能从 Window、worker 或某个 consumer 的结果推导这些 API 已保护；第三方库、其他渲染/读取路径及硬件推断手段不在完整覆盖声明内。

**已验收的上下文与生命周期：**所测主 frame/子 frame、dedicated worker、默认分区 SharedWorker/ServiceWorker 与 OffscreenCanvas 的已接入路径；profile/site 分离、普通重启稳定、OTR 隔离及重建、显式 off、全局 UI 开关与站点兼容例外的重启/恢复。ServiceWorker 已覆盖缓存脚本禁止下载后的重启场景；不能仅凭重新使用 registration 就推导该项通过。SharedWorker/ServiceWorker 的范围仅指其可用且已接入的 API，不代表 worker 内全部 API 都受保护。

**仍未验收或不保证：**授权 Storage Access API 非分区 SharedWorker 的逐嵌入站点身份/例外、手动关闭第三方分区的行为、worklet、chosen-content/平均攻击抵抗、完整外部网站兼容性矩阵。六条原生 Chrome 隐私上下文单测已加入源码，但没有运行完整 native unit-test binary，不得将其记作六条已执行通过。首版仍是 best-effort 的有限保护，不是全 API 覆盖或“100% 匿名”。

## 5. Probe 契约（P4–P13）

统一输出：构建/策略版本、平台、上下文类型、普通/OTR、测试作用域的非敏感标签、字段结果、预期差异与断言。不得记录根密钥、真实账户 cookie/token；证据应脱敏。本地 P4–P13 探针及 §6 指定的隐私语义断言已运行；通过状态仅覆盖报告中的断言，不代表下表所有 API、动态行为、权限状态和网络防泄漏目标均已验收。不得仅因脚本存在标记通过。

| Probe | 覆盖 | 稳定与动态断言 |
|---|---|---|
| P4 | Navigator、UA-CH、plugins、connection、Battery、touch | 品牌/版本及静态策略一致；高熵提示遵守上下文/委派。网络、电量、硬件连接变化允许动态，不要求重启恒定。 |
| P5 | screen/window/DPR、resize、缩放与多显示器 | 与实际窗口及用户动作联动；不能为稳定指纹冻结几何。 |
| P6 | Canvas 导出/像素读取/文字度量，含 OffscreenCanvas | 验证 8-bit RGBA 完整图像处理后裁剪、重复读取不累积、alpha 保持、预算边界及 `NotSupportedError`；比较解码像素。HDR/float16、字体度量标记未保护；上下文覆盖分别报告。 |
| P7 | WebGL/WebGL2 参数、扩展与实际读取 | 验证 debug renderer 扩展隐藏的一致性与真实能力保留；原始 `readPixels` 标记未保护。GPU/context loss 与重建单独测试。 |
| P8 | OfflineAudioContext 与多条缓冲读取路径 | 验证只处理一次、改变量绝对值 ≤ `1e-7`、零值及有限性保持、作用域稳定；实时 Audio 标记未保护，不硬编码单探针和值。 |
| P9 | DOM/API 面、属性描述符、各 realm 可见性 | 安全上下文、平台、策略差异符合预期；不要求所有 API 存在，也不把 window 键数量当常量。 |
| P10 | MediaSource/canPlayType/EME 与真实媒体操作 | 能力查询与实际解码/密钥系统一致；不假 DRM，不强求与官方品牌功能完全相同。 |
| P11 | Intl/Date/时区、Math、stack | 用户配置和夏令时变化合法；版本、架构依赖登记，不宣称 Math 结果只能由硬件决定。 |
| P12 | permissions、storage.estimate 与授权/拒绝流程 | 查询与实际访问一致；授权、撤销和配额变化正常；跨 profile/OTR 隔离且普通用户状态保留。 |
| P13 | ICE candidates、mDNS、STUN、代理、权限前后 | 同时检查脚本可见信息与实际出口，覆盖 IPv4/IPv6；策略禁止的泄漏失败，预期限制不得冒充连通成功。 |

跨上下文矩阵：主 frame、同/跨 origin iframe、sandbox/opaque frame、dedicated/shared/service worker、worklet、OffscreenCanvas（仅测支持的 API）。dedicated 及默认分区 shared/service worker 的已接入路径已纳入本轮验收，worklet 仍未保护；授权非分区 SharedWorker 单独标记为限制及未验证项。比较同作用域一致、不同顶层 site 隔离、不同 profile 隔离、普通/OTR 隔离；刷新、进程重建、重启、导航、BFCache 与多标签是完整回归矩阵要求，未在报告中验证的组合仍不能标记通过。worker 共享和生命周期须跟随实际 storage partition，不能随意改协议语义。

“稳定”仅适用于已定义的静态受保护输出；同输入重复读取不得漂移。不同作用域要求无共享派生身份，不要求每个低熵公开字段都不同，也不保证每次像素输出必然不同。动态项按真实事件验证，禁止 P4–P8 全量逐字节恒定的总断言。

网络补充 P1–P3：记录 HTTP/UA-CH、TLS 与 H2/H3；使用受控服务端或不重终结 TLS 的抓取方法。MITM 服务端侧观测不能代表浏览器握手；跨连接比较需区分 GREASE、扩展排列、恢复与协议协商。

## 6. 阶段与发布证据

| 阶段 | 完成条件 | 当前状态 |
|---|---|---|
| S0 契约与 probes | 作用域规则、威胁模型、P4–P13 harness 与原生基线归档 | 本规格及本地探针/基线已有证据；不代表所有 probe 契约完成 |
| S1 原生策略与隔离 | profile/OTR 生命周期、用户状态保留、跨上下文隔离回归通过 | profile/site/OTR、重启、off、默认分区 worker 的限定矩阵已通过；其他用户状态及未测组合不扩大声明 |
| S2 逐 API 最小化/限制 | 每项有实现位置、能力契约、兼容测试、回退策略及测量证据 | 全依赖 framework 与完整 app 已构建回传；§4.1 的运行时验收及 UI 开关/例外恢复通过 |
| S3 Seed 噪声与扩展 | 首版范围先验证读取一致性、资源预算和正常功能；更强抗重建另行证明 | Canvas/OfflineAudio 首版 best-effort 保护已有运行证据；chosen-content/平均攻击抵抗未证明，其他路径见 §4.2 |
| S4 发布 | 隔离、稳定、动态行为和权限语义均通过；预期差异及残余泄漏公开记录 | 首版本地安装与限定验收完成，保留用户状态；未作全网站兼容或全 API 匿名发布声明 |

### 6.1 本轮构建与验收记录

H200 使用真实 GN/Ninja 依赖图交叉构建 macOS ARM64 引擎及完整 app，包含 WebUI 所需资源包；不是手工链接旧 ABI 对象。最终 [framework 构建收据](../out/evidence/privacy-engine-build-receipt-final.json)记录 84 个源码哈希，[完整 app 收据](../out/evidence/privacy-engine-app-receipt-final.json)与 [352 条引擎产物清单](../out/evidence/privacy-engine-app-manifest-final.json)记录回传包。framework 与包内 framework 的完整字节哈希一致：

```text
082a8ddf0fd449cfdfe88358c7d6fc894c2e4af85fc1ba8b2e716bdae9728dd3
```

| 证据 | 已通过范围 |
|---|---|
| [privacy-lifecycle-acceptance.json](../out/evidence/privacy-lifecycle-acceptance.json) | 16,426 项检查、零失败；本地 profile/site/OTR、普通及 OTR 重启、off 与所测 frame/worker 隐私语义矩阵 |
| [privacy-site-exception-verification.json](../out/evidence/privacy-site-exception-verification.json) | 四个测试 origin 的站点例外策略通过；验证例外站点与非例外站点的 Canvas、Audio、WebGL 行为 |
| [privacy-global-ui-off-verification.json](../out/evidence/privacy-global-ui-off-verification.json) | 全局 UI 关闭并重启后的四个测试 origin 验证通过 |
| [privacy-restored-acceptance.json](../out/evidence/privacy-restored-acceptance.json) | 恢复设置并重启后 6,906 项检查、零失败 |
| [privacy-post-diagnostics-acceptance.json](../out/evidence/privacy-post-diagnostics-acceptance.json) | 诊断脱敏构建后的隐私语义回归 6,906 项检查、零失败；不是诊断 URL 脱敏专项 QA |

默认分区 dedicated/shared worker 与 ServiceWorker 缓存禁下载重启已完成本轮专项覆盖；授权非分区共享仍按 §2 的限制处理。部分自动报告中的 cached-worker 字段仍为 `not_verified`，不能把该字段或 registration 复用本身当作缓存启动证据；专项重启覆盖与报告中的一般断言须分别解释。完整原生 unit-test binary 未运行。

最终收据：[privacy-final-verification.json](../out/evidence/privacy-final-verification.json)。[诊断页专项](../out/evidence/privacy-diagnostics-runtime.json)与[设置页专项](../out/evidence/privacy-settings-runtime.json)均通过。27 项浏览器工具、5 项 MCP、7 项验收器单测，以及最终引擎上的原生功能、界面和官方 A2A 客户端/取消回归通过。正式应用在原 profile 启动后，核对会话消息、草稿、模型、4 个网页标签和账户恢复成功，默认隐私开启；没有调用付费推理服务。完整应用 manifest 为 `out/macos-arm64/metabrowser-app-manifest.json`，前版应用保留在 `out/macos-arm64/before-privacy.app` 以便回退。

未实现、未覆盖、不支持、预期拒绝和测试失败必须分别报告。浏览器升级或策略改变需重跑相关 probes；回退不得删除用户状态。站点返回码/验证码率只能作为兼容性观察，不能证明隐私或实现正确，也不能推导固定安全速率。

## 7. 一手资料

- [Chromium UA reduction](https://www.chromium.org/updates/ua-reduction/)；[UA Client Hints](https://wicg.github.io/ua-client-hints/)。
- [Chromium Navigator 实现](https://chromium.googlesource.com/chromium/src/+/main/third_party/blink/renderer/core/frame/navigator.cc)；[WebDriver 标准](https://www.w3.org/TR/webdriver/)。
- [Battery Status](https://www.w3.org/TR/battery-status/)；[Chromium Battery IDL](https://chromium.googlesource.com/chromium/src/+/main/third_party/blink/renderer/modules/battery/navigator_battery.idl)；[Pointer Events](https://www.w3.org/TR/pointerevents/)。
- [Permissions](https://www.w3.org/TR/permissions/)；[Permissions Policy](https://www.w3.org/TR/permissions-policy-1/)；[Storage Standard](https://storage.spec.whatwg.org/)。
- [RFC 8828：WebRTC IP handling](https://www.rfc-editor.org/rfc/rfc8828.html)；[Chromium TLS extension permutation](https://groups.google.com/a/chromium.org/g/blink-dev/c/bYZK81WxYBo/m/CCl6Y2qLBAAJ)。
- [Brave fingerprinting defenses 设计](https://brave.com/privacy-updates/4-fingerprinting-defenses-2.0/)：仅作按站点派生的参考；其会话轮换不属于本文普通 profile 契约。

实现时应将上游源码链接固定到项目实际 Chromium revision；`main` 链接只用于定位，不能替代目标构建的验证。

## 8. 检测兼容与隐私的双重验收（后续工作）

用户明确的目标是：先兼容首批网站，再持续扩大范围，同时保护用户未主动提供的个人与设备信息。首批暂按两份报告中的小红书、淘宝准备，完整域名与业务流程仍待确认。不能用减少 API 数量、伪造成功返回、删除登录状态或暴露原始硬件指纹来换取“通过”。单个公开检测页的分数也不能证明通过网站风控。

每个业务用例须分别记录：页面和功能结果、实际 HTTP/业务结果、权限提示、隐私暴露与兼容例外。登录墙属于身份前提，验证码属于用户交互，不能与引擎错误混为一谈。公开浏览、登录、搜索、详情、视频等流程分别验收；需要用户账号的用例不从公开首页推导成功。

2026-10-16 的独立 profile 初步对照：当前引擎与同版本 `--metabrowser-privacy=off` 为 Chromium 154.0.8037.97，官方 Chrome 为 155.0.8059.79。三组均连接固定端口 CDP，不能将测试连接下的结果当作无调试状态结果；版本差异须另列。CreepJS 三组均显示 `31% like headless / 0% headless / 0% stealth`，故不能把该启发式分数归因于本项目。当前引擎另显示 Canvas RGBA noise，未修改基线及 Chrome 未显示；该观察证明扰动可识别，不证明网站会拒绝，也不证明扰动能满足检测兼容目标。WebGL debug 信息被限制，其他 GPU 路径仍需一致性与隐私审查。

当前引擎的小红书公开信息流已显示内容和交互控件；未验证其登录、搜索、风控或完整业务流程。淘宝公开页亦开始对照，动态加载和完整业务结果不能仅用 body 字数判断。原始检测文本仅保留在权限为 0600 的本地 evidence 文件，不记录账户 cookie/token；没有将真实用户 profile 交给检测网站。

出口 IP、用户主动登录的账号及提交的业务资料属于连接或业务必需信息，不能承诺对目标网站不可见。设备高熵特征、局域网地址、额外枚举的字体/语音/设备等需逐项明确保护策略与残余暴露。数学意义的所有网站不可关联与零信息暴露并非本项目可验证的发布承诺。

## 9. 虚拟设备身份 Profile 契约（管理底座已交付，完整模拟未完成）

用户明确要求两者同时成立：宿主的隐私特征不泄漏；向网站探测提供拟真且系统性一致的回应。Profile 不是单纯的不同存储目录，也不是随机替换几个字符串，而是一个版本化的 web-visible 虚拟设备环境。

模板分为宿主环境、虚拟身份声明、实际执行能力、隔离数据、验收证据五部分。宿主环境不直接成为对外高熵标识；虚拟声明必须由可实现的执行能力支撑，不能广告不存在的解码器、GPU 扩展或权限。OS、UA/UA-CH、CPU 架构、GPU 参数与扩展、shader 精度/渲染、Canvas、字体及文字排版、音频、媒体、语言/时区/窗口、权限与存储规则应由同一模板约束。

页面、同/跨源 frame、opaque frame、dedicated/shared/service worker、worklet、离屏读回须分别核查；不能让某个旁路回落到宿主身份。模板字段须登记来源为固定模板、受约束动态值或用户授权数据，并记录不支持的行为。浏览器原生函数形态不等于数据一致性，更不等于通过某个站点的业务验收。

同一身份必须跨刷新、重启稳定，合法的窗口变化、设备插拔、权限授权等仍按统一规则更新。不同身份使用不同的 browser user-data-dir、Cookie/权限/存储/指纹根，以及明确隔离的 Agent 会话与工作区。复制配置不能复制密钥、网站登录或历史；切换以独立进程/窗口进行，不热改旧文档的环境。

验收分为宿主泄漏检查、模板内部一致性、跨 realm 一致性、实际渲染与能力一致性、首批网站逐业务流程兼容。每个模板要独立维护构建版本与证据，未验证的组合不得因字段可编辑而标成可用。Windows/Linux 与任意 NVIDIA/AMD/Intel GPU 的完整行为模拟尚未实现；原生身份管理页面和独立目录仅是底座，不代表上述虚拟设备契约已完成。

### 9.1 全局配置归属

用户要求 Profile 与 MetaCodes 集成界面分离。身份目录、模板、配置检查与窗口切换属于浏览器全局设置，入口为工具栏 Metask 账户菜单的“账户设置”，以及 Chromium 设置里的 Metask 账户卡片；独立原生窗口不占 Agent 侧边栏，不要求创建对话或初始化 AgentCore Session。`identity_profiles` 构建目标仅依赖原生 views/base/共享视觉定义，不依赖 SDK、模型目录、Skill 或 MCP。Agent 集成只是当前浏览器身份的消费者，不拥有模板或身份生命周期。

### 9.2 身份时区

原生身份配置已包含时区，支持跟随系统、UTC、上海、东京、伦敦、纽约和洛杉矶，以及 ICU 数据库内的自定义 IANA 命名时区；旧配置缺省为跟随系统。拒绝 POSIX TZ 表达式和文件路径。配置修改后须完整关闭并重新打开对应身份。启动器为独立身份进程设置原生 `TZ`，不注入网页 JavaScript，不修改宿主系统时区或当前时间。

本地实际页面验证纽约时区在 window、iframe、dedicated/module/nested/shared/service worker 七个上下文的 Date/Intl 输出一致，2026 年冬季偏移 300 分钟、夏季 240 分钟。报告位于 `out/evidence/identity-timezone-reports/`。独立 SDK 缺省测试应用上的新建、保存、复制配置与独立浏览器启动验证亦通过。这些验证不代表跨平台/GPU 模拟已实现，也不代表目标网站业务验收通过。

### 9.3 进展复核

2026-10-16 补验发现身份进程回收任务调用 `Process::WaitForExit` 时，只有 `MayBlock`，缺少 `WithBaseSyncPrimitives`，导致父浏览器触发同步等待断言。已补齐 task trait，必须在实际 macOS 构建中验证父进程存活、子进程退出后被回收、身份冷重启及七上下文时区/夏令时与 Canvas 输出稳定。编译通过不能替代这些运行时结果。

修正版已在 H200 完成完整 GN 引擎与应用构建，回传后对完整包及作者源码哈希校验通过。SDK-free 应用上运行 `tests/integration/identity_lifecycle_test.py` 最终通过：父进程在关闭子身份后存活、子进程被回收、两身份 Canvas 输出不同、同身份冷重启输出稳定、七上下文时区及夏令时一致。证据为 `out/evidence/identity-global-final-verification.json`；没有调用模型服务。

剩余主线包括虚拟 OS/UA/UA-CH 一致性、GPU 参数与实际渲染一致性、字体/度量与其他未保护读取路径，以及首批网站的具体业务流程验收。§4.2 未保护路径仍然有效；不能把 Profile 页面或时区功能交付解释成全量隐私保护完成。


## 10. Mac v10 本地引擎覆盖与证据（2026-10-16）

此版本由 Linux H200 对 macOS arm64 完整交叉构建，回传后核对 352 项引擎文件/符号链接、26 项本地作者源码与 14 项 staging 输入。MetaCodes SDK 仍为固定 e3a3b932 / ABI21；原生身份配置不依赖 SDK。当前证据只支持以下明确范围，不能推广成所有 Mac 指纹路径或所有网站验收通过。

| 表面 | 实现与实际验证 |
| --- | --- |
| CPU | 原生 hardwareConcurrency 向下分档；window、iframe、五类 worker 共七上下文一致，不宣称性能基准不可推断。 |
| 字体 | 限制额外系统字体家族，并在真实字体源、CSS/SVG、离屏与字形 fallback 边界过滤用户字体；保留系统受保护字体资源与网页字体。测试额外字体 local()、CSS 直接指定、SVG、私用字形直接读取；中文/日文/韩文/Emoji/阿拉伯语/希伯来语度量不变。自动 fallback 的基线没有选择 canary，不能把该探针算作成功复现并阻断自动 fallback。 |
| Canvas | 新增 float16 HDR 完整副本保护、裁剪、PNG/Blob/Offscreen 导出；保留 alpha 和色彩格式，F16 scratch 上限 32 MiB。既有 U8 输出算法不变。 |
| WebGL | typed array（含可用的共享内存）和 PBO 都先走私有 scratch；打包、偏移、间隙、旧错误保持；整数业务 attachment 精确保留。五上下文测试 U8/F32、受支持的 packed/half/normalized 格式，alpha/shared exponent 不变。RGB9_E5 在本机原生 framebuffer 即不支持，不记作通过该格式读回。 |
| Audio | 实时 Analyser 浮点数据及 byte 转换一致，保持尾部和真实音频图；AudioWorklet owner token 继承。未宣称所有 worklet/API 均受到保护。 |
| WebGPU | adapter/device 高熵型号、驱动、架构与 heap 元数据收敛；真实 compute 测试通过。vendor、能力和实际运算保留，并不等于 GPU 模拟。 |
| 显示 | 常用 Mac 虚拟尺寸、可用区域、位置、色深、方向与 CSS 查询一致；真实 viewport/DPR/渲染不改。原生 Window Management 授权后尊重真实详细信息，撤销后恢复保护，CSS 事件同步。 |
| 语音 | 最多暴露当前语言与 en-US 的实际 voice，每语言一个，公开通用名称；原生私有名称仅用于底层路由，不向 JS 暴露。实际静音 utterance 正常完成。 |
| WebRTC | v20o 起默认「隐藏本机地址 · mDNS」：主机候选与官方 Chrome 无权限时相同（mDNS 名称），授予媒体权限后也不暴露内网地址；另有仅公共接口、禁止 UDP 直连的严格代理、沿用浏览器策略三种选项。受控 STUN 验证普通模式可连接、严格模式无 UDP；不承诺隐藏网站直接连接的出口 IP。见 `docs/privacy-baseline-diff.md` R6。 |
| 全局身份 | 账户设置独立窗口提供语言、IANA 时区、窗口、显示区域和 WebRTC 策略；独立目录/进程，复制配置不复制账户或浏览数据。Kolkata/Kathmandu 七上下文和非法配置拒绝测试通过。 |

主要运行证据：`out/evidence/mac-privacy-acceptance-v10.json`、`display-permission-acceptance-v10.json`、原生身份 UI 验收文件。测试均使用隔离本地配置、受控 HTTP/STUN 与真实 Mac 图形后端，付费模型调用为零；保留基线、身份 A/B、A 冷重启和严格模式的独立原始报告。元数据断言不能替代业务验收。

尚未实现或未证明：Windows/Linux 与指定 GPU 全行为模拟、任意 shader/compute/性能推断的统一虚拟硬件、chosen-content/统计重建抵抗、原始媒体/VideoFrame/captureStream 的全链路保护、所有授权设备 API 的隐私矩阵、首批网站逐业务流程验收。用户授权的设备/详细显示信息依旧按权限提供；不伪造权限成功或替换业务计算结果。WebGL debug 扩展仍隐藏，尚未变为带通用型号的完整扩展。


### 10.1 Mac 复查修订 v13

本轮针对已交付 Mac 引擎及其验收工具反复审查，修复了以下具体问题：

- **详细显示撤权：**保留的 `ScreenDetails` 列表、`currentScreen` 及单独保存的 `ScreenDetailed` 引用均停止提供实时物理显示元数据；真实拓扑更新不再进入撤权对象。基本屏幕兼容模式不能绕过详细显示权限检查。
- **重新授权：**权限 generation 改变时，旧对象的 getter 在返回前刷新当前快照；不要求页面再调用一次 `getScreenDetails()`。测试直接读取保留对象。
- **显示事件：**隐藏的物理变化不再仅凭原始 ScreenInfo 触发事件。窗口外框更新提交后按有效虚拟尺寸和公开 DPR 比较，档位扩大/缩小同步 CSS 与 `screen.change`，含固定尺寸 iframe。
- **系统语言恢复：**`system` 从 CoreFoundation 读取有序语言列表，按 Chromium 的 BCP47 和 Accept-Language 规则处理，始终显式传给子身份；避免固定语言残留。UI 实测日本语切回系统语言，HTTP 与七上下文一致。
- **语音去重：**语言标签大小写归一后去重，避免 `en-US` 与 `EN-us` 重复暴露；继续使用真实原生语音路由。
- **HDR 浮点读回：**WebGL fractional float32 采用 token 选择的至多一个相邻可表示步长，修复较大 HDR 值的绝对 epsilon 被舍入掉的问题；整数、非有限值、零值、符号和 alpha 契约保持。仍不保证任意浮点业务的逐位兼容，保留站点兼容出口。
- **可重复 staging：**精确识别旧补丁后迁移，修复两个相邻编辑互相拆分 marker 导致第二次执行失败的问题。重复执行实际返回无变更。

SDK 的图片预检失败已定位并修正为**测试配置问题**：独立 fixture 未开启 `METACODES_MODEL_CATALOG_PROBE=1`，模型能力目录未被读取。浏览器原有集成已开启；测试对齐后完整 host contract（含 GLM/MiniMax 图片、权限取消、Skill、checkpoint）通过。SDK 与插件二进制未变。

新的 `mac_privacy_runner.py` 使用独立目录和 headed CDP 导航，不进行设备/viewport emulation。每次退出前确认 `about:blank` 主 frame 与 loader 已提交，再请求原生正常退出；强制终止不能算冷重启成功。只允许清除多余空白 fixture 页，拒绝恢复中的旧探针；保留身份密钥、Cookie 与存储。测试清理分别处理进程、STUN/HTTP 与临时字体，任一失败使整个采集失败。

验收器补齐样本长度、真实布尔类型、必测格式集合、原始结果拒绝、浮点误差/alpha、跨 realm、冷重启与清理证据检查。`mac_privacy_acceptance_regression.py --require-review` 实际验证有效集合通过，31 类损坏证据被拒绝；不是只检查源码文本。

新增主要证据为 `out/evidence/mac-review-acceptance-v13.json`、`mac-review-negative-acceptance-v13.json`、`display-permission-acceptance-v13.json`、`mac-identity-ui-acceptance-v13.json` 与 `mac-review-host-contract.log`。范围仍服从 §10：alpha 的原始形状/渲染、任意计算与性能推断、所有媒体路径及网站业务矩阵不因这次复查而获得全覆盖保证。

### 10.2 GPU 与媒体扩展 v14 / v14.1（已本地交付，登录态验收待完成）

身份配置增加 `gpu: native | software`，旧文件缺少该字段时保持原生后端；未知值拒绝载入。软件模式为 ANGLE WebGL 与 Dawn WebGPU 选择随包附带的 SwiftShader，使用真实的软件渲染、计算、功能集合和限制，仍公开真实的 fallback 状态。不承诺模拟任意 NVIDIA/AMD 型号、硬件性能或整个操作系统的 GPU；浏览器合成与系统媒体解码也不是显卡型号模拟器。

`stage-privacy-gpu.py` 只在明确选择 SwiftShader 且实际适配器为 CPU、vendor `0x1AE0`、device `0xC0DE` 时豁免 `CPUAdapter` 策略，其他 blocklist 原因保留。正式软件模式不使用 `--enable-unsafe-webgpu`，不全局关闭 adapter blocklist，不启用实验 WebGPU/WGSL 功能。SDK-free 的 Mac 实测已覆盖主线程/Worker、WebGL shader/raster、WebGPU compute/render/readback 和真实 validation error；候选版本的检查结果保存在 `gpu-media-matrix-v14*.private.json`。

`stage-privacy-media.py` 把保护放在合成 Canvas 交给其他对象的出口：

- HTMLCanvasElement/OffscreenCanvas → ImageBitmap，在裁剪、缩放及 alpha 转换前处理完整私有快照。
- Canvas → VideoFrame，在原生帧构造前处理；clone、跨 Worker transfer、copyTo 和编解码沿用该帧的像素。
- OffscreenCanvas.transferToImageBitmap，在原生源重置后复制保护，并保留 origin-clean 状态。
- Canvas.captureStream，保护模式绕过直接 GPU→VideoFrame 快速路径，所有监听器从同一份私有快照采集；后续 MediaRecorder/WebRTC 不另行扰动。

原生 taint/权限检查保留；直接相机、已有 video/解码图像、调用者提供的 RGBA 与 PCM 不因上述 Canvas 出口而改写。大图/分配失败不退回未保护的 Canvas 内容：沿用 4 Mi-pixel 预算，抛出异常或不发出采集帧。此限制会影响超过预算的 Canvas 采集，不能当作任意分辨率媒体全覆盖。实时相机/麦克风授权、屏幕采集、DRM 和所有 codec/profile 的兼容性仍需各自验收。

新增 `gpu_media_runner.py` / `gpu_media_probe.mjs` 使用隔离身份、loopback、无 SDK 的原生浏览器测试保护像素一致性、跨域污染、Worker 转移、原始媒体保真、VP8/Opus、录制回放及本地双 peer RTP。AVC/AAC 测试使用合成样本，要求 MSE 真正呈现帧与时间推进、AAC 真正解码为有限 PCM，不以能力字符串代替播放验证。Mac 构建配置启用 `proprietary_codecs` 与 Chrome FFmpeg codec 配置；不改变产品账户/品牌。

U8 Canvas 输出改用 `MBCANV02`：完整私有副本的内容 checksum 参与 token 派生，RGB 改变量最多三个 8-bit 等级，同色区域保持同色，alpha 与全透明像素保留。处理仍在裁剪前执行，不修改源画布。去掉首版的 alpha 备份、逐行向量与逐像素外部 PRNG 调用，U8 私有像素 scratch 上限降至 16 MiB；F16 的格式与 32 MiB 预算保持。输出仅承诺同一固定构建内稳定；这不是抗 chosen-content 重建的密码学方案。当前 Mac 单次 1080p 合成 VideoFrame 导出从旧路径约 252ms 降至原生 15.9ms、软件 21.7ms，不等于所有场景或持续编码的吞吐保证。

最终候选的原生/软件矩阵共 39 项检查通过，证据 `gpu-media-matrix-v14-final.private.json`。五模式隐私采集、31 类损坏证据拒绝、显示授权/撤销/重新授权及原生全局身份 UI 回归通过。UI 测试工具现等待应用真正激活并核对 omnibox 焦点后发送 Return，防止把 AX 编辑当成导航；身份子进程遵从父进程显式禁用组件更新的参数，避免离线测试下载大体积语音组件。SDK host contract 再次通过，未调用付费模型。

网站验收使用 `site_business_acceptance.py`，每项记录引擎哈希、实际步骤、失败或登录门槛。公开搜索/详情通过不等于登录态业务通过；B 站搜索/详情能加载但旧构建缺少 AVC/AAC，播放器明确失败，此问题触发本轮 codec 修复。不会把登录弹层、空页面或未验证的播放器记成成功，也不会自动执行购买、发信或其他外部写操作。

交付后的 v14.1 修正账户设置的深浅主题混搭：背景、标签和按钮使用原生 ColorProvider 语义色，实拍深色窗口通过检查。对照构建收据，只有 `identity_profiles.cc` 的七处主题编辑改变；反向去掉这些编辑可精确还原已验收 v14 的源码哈希，GPU/媒体/codec 源码、staging 与构建参数一致。v14.1 重新通过 39 项 GPU/媒体检查和完整原生身份 UI 回归；1080p 单次样本为原生 20.3ms、软件 19.0ms。此前五模式隐私、显示权限及网站证据保留原始 v14 引擎哈希，不冒充在新二进制重新采集。

实际网站结果见 `out/evidence/site-business-review-v14.json`：B 站在原生与软件两种模式均完成攻略搜索、详情和真实视频时间推进；1688 软件模式完成公开搜索与商品详情，后续原生匿名身份跳转登录，不能据此断言 GPU 是原因。小红书、淘宝、天猫均遇到登录门槛；登录态搜索/详情与财务、ERP、CRM、BI 跨站流程仍需测试身份、站点和业务目标。

最终安装证据 `gpu-media-delivery-v14p1.json` 核对 352 项引擎与 373 项完整应用文件/符号链接，保留登录账户、四个网站标签的完整原生可访问性名称，以及七个对话全部字段（仅 `updated_at` 可因正常启动更新）。SDK/plugin 未变。原生账户设置窗口已打开；v13 和主题修正前 v14 应用保留用于回退。

### 10.3 v14.1 交付后的循环复查

本轮复查 GPU 安全例外、Canvas 私有副本与媒体出口、身份校验/启动隔离，以及验收证据。引擎与身份源码保持已安装收据的哈希。本轮修复集中在验收器：严格要求完整的 18 项探针检查与对应详情、真实布尔值、零模型调用和一致的汇总状态，拒绝空集合或缺项产生的假阳性；失败报告以 0600 临时文件原子替换，保留错误原因；明确报告 CDP 启动超时，超时退出时回收本测试启动的进程。框架哈希改为分块读取，避免一次读入约 619 MiB；端口预检与 HTTP 服务使用一致的地址复用策略，避免连续测试将 TIME_WAIT 误报为活动监听器。

6 项证据契约测试（含多种缺项、类型和矛盾结果反例及符号链接写入隔离）、原有 7 项隐私验收单测通过。真实原生/SwiftShader 矩阵两次完整通过，每次共 39 项；最后一轮证据为 `out/evidence/gpu-media-review-v14p1-round3.private.json`，复查摘要为 `gpu-media-postdelivery-review.json`。最后一轮范围内未发现新增问题；§10.2 的已知边界和登录态业务待验收状态不变。

### 10.4 v15 媒体出口扩展与构建恢复

本轮实际发现并修复 Canvas → WebGPU 纹理 → 可映射缓冲区的保护绕过。`external_image_utils.cc` 的 Canvas 专用入口在原生跨域污染检查之后、裁剪/纹理上传之前调用统一的完整私有快照保护；ImageBitmap、VideoFrame、解码图片及调用者 ImageData 不重复处理。预算失败抛出 `NotSupportedError`，小范围 GPU 裁剪也不能绕过完整源图预算。软件适配器不再尝试导入系统 GPU 共享纹理，改为显式 CPU 像素上传，修复读回全零；硬件适配器路径保持。

扩展矩阵以 `gpu_media_runner.py --extended-media` 运行，只有该显式选项启用合成摄像头/麦克风和按标题精确选定的自有测试标签页共享，不授权采集真实桌面或设备。新增验收包括设备帧与约束更新、轨道克隆/停止、音视频录制和实际双轨解码、iframe 权限拒绝、离线 Worklet 完成后的保护与实时原始信号保真、PNG/透明度/F16、Worker 导出，以及 WebGPU 完整/裁剪像素、污染检查、预算与调用者像素保真。

ClearKey 验收使用合成的 CENC 分片、公开测试密钥与临时 EME 会话，禁止 distinctive identifier 和持久状态。`fragment_cenc.py` 保留 FFmpeg 已加密样本，把辅助加密数据移入 MSE 分片；独立 FFmpeg 解密验证通过。测试要求实际视频帧回调与时间推进，并确认 CDM 视频拒绝 `VideoFrame` 读取；固定源码 `WebMediaPlayerImpl::GetCurrentFrameFromCompositor()` 对 CDM 返回空帧，由构造器转为 `InvalidStateError`。直接设置非分片加密 MP4 的 src 或仅检查密钥可用/播放时间，均不足以证明成功。此项不代表 Widevine/FairPlay 或外部商业授权服务已验收。

恢复后的证据 `out/evidence/media-restored-v15-final.private.json` 记录原生 33 项、软件 34 项共 67 项通过，以及引擎、探针和媒体夹具哈希。五模式隐私结果、31 类损坏证据拒绝分别记录为 `media-restored-privacy-acceptance.json`、`media-restored-negative-acceptance.json`；固定 SDK 本地 host contract 通过，无付费模型调用。清理期间旧 `out/` 整体被移除，前述 v14/v14.1 证据路径现为历史引用；本次从 H200 收据与完整引擎重新恢复并采集，不把不存在的旧文件当作当前证明。

启动脚本默认使用持久系统 profile，取消默认 `out/metabrowser-profile`。显式测试目录可通过绝对路径 `METABROWSER_USER_DATA_DIR` 指定；启动器三项契约测试验证默认目录、带空格路径/参数及拒绝相对路径。真实硬件/TCC 授权、任意 GPU/OS 一致性、alpha/计时推断与登录态跨站业务仍是各自独立范围，不能由本轮受控矩阵推导为全覆盖。


### 10.5 v16 GPU 可选能力与本地媒体设备名称

受保护的 WebGPU adapter 使用统一功能集合过滤时间戳查询、subgroup 及对应实验功能，`features` 枚举、`has` 与 `requestDevice(requiredFeatures)` 共同遵守；adapter/device 的 subgroup 宽度归零。保护在构造时固定，Worker、保留对象和 owner 销毁后的行为一致，开发者开关不能重新开放。底层 vendor、fallback、真实限制和验证器保留原生值，不把任意 GPU 型号伪装成已实现。七类超限申请与合法限额请求的检查确认原生验证已有效，未改写这些限制。

软件身份除 ANGLE/Dawn SwiftShader 外，显式禁用视频硬件编码和解码；能力请求与实际 AVC/AAC、VP8/Opus 路径共同验收。对外媒体名称在枚举、JSON、本地物理输入轨道和扬声器选择结果中改为通用别名，后缀只取已向该来源公开的设备 ID，不增加原生硬件标识。未授权的空标签保持为空；设备 ID、权限、group ID 和路由不变。本地轨道构造时保存不可变别名，克隆、停止及 iframe 销毁后保持，合成轨道、远程轨道与明确桌面共享保留应用本身的名称。

`out/evidence/hardware-privacy-v16-final.private.json` 记录原生 39 项、软件 40 项，以及两个后端各五组策略对照的 30 项，共 109 项检查通过。对照覆盖 balanced、关闭、开发者、站点例外与全局禁用，防止将权限缺失或全部 API 失败误判为成功。合成设备测试在独立 loopback 身份显式授予浏览器层权限；fake UI 自动接受本身不授予枚举标签权限，首轮缺失授权的失败已定位为测试条件问题，并非已证实的轨道生命周期漏洞。

同一最终引擎重新通过五模式隐私、31 类损坏证据拒绝、原生显示授权/撤销/再授权、全局身份与软件视频启动参数回归。18 项证据/隐私/启动器单测及固定 SDK host contract 通过，无付费模型调用。构建收据、135 项源码输入、staging 脚本哈希和重复 staging 输出均核对，传回的 352 项引擎文件及完整 SDK 应用 373 项文件/链接分别校验。

范围与已知缺口统一见 [覆盖表](PRIVACY_COVERAGE.md)。合成输入和受控 ClearKey 不代替真实 TCC、任意桌面共享或商业 CDM；公开网站结果不代替登录态业务。原始硬件限制、授权设备数量/能力、UA/Client Hints、网络与跨系统身份并未全部虚拟化，因此本轮结果不能表述为所有网站或全部指纹已通过。


v16 最终安装记录见 `out/evidence/hardware-privacy-v16-delivery.json`，运行 PID 45437，保留四个原生网页标签、七个对话的语义哈希及 Metask 登录，旧完整应用保留在 `out/macos-arm64/before-hardware-v16.app`。汇总与各证据哈希见 `hardware-privacy-v16-review-result.json`。B 站两个 GPU 模式均通过公开搜索、详情及实际播放；1688 原生模式通过搜索/详情，软件模式遇到登录；小红书、淘宝、天猫两种模式均遇登录门槛。未提供登录态业务测试数据，跨站流程仍未验证。

本轮还修正网站验收器的端口预检，允许已结束连接的 TIME_WAIT 而仍拒绝活动监听，并将大体积框架哈希改为分块读取；软件模式随即重新运行完成。该变动不修改已通过矩阵的引擎或 GPU/媒体探针。


### 10.6 v17c 被动信号保护与跨进程 Canvas 稳定性

保护上下文的 Battery 对象冻结策略，直接返回通用满电/接电状态、不启动系统电池订阅，停止和 owner 销毁后不恢复原生值。NetworkInformation 冻结公开通用类型/质量，过滤物理链路质量变化事件，保留真实联网状态和明确的 saveData 偏好；原生关闭对照仍响应受控慢/快/离线变化。两条路径不改变权限语义或通过 JS 覆盖绑定。

五模式门禁实际拒绝 v17 的跨身份 HDR 碰撞，以及 v17b 的重启漂移。前者由 FNV 低位取样导致，后者由当前构建 `DCHECK_ALWAYS_ON=1` 下 `FastHash` 的进程地址扰动导致。v17c 改用持久内容校验并先混合完整种子；HDR 使用新的逐像素混合，8-bit 也移除临时校验和的依赖。复用原先碰撞的同一对 root secret 确认分离与重启稳定，不靠换身份规避失败。种子位影响测试覆盖 64 个单比特变化和 256 组高位变化，仍非密码学抗重建保证。

最终框架重新通过 109 项 GPU/媒体和 24 项身份/被动信号、五模式、32 类损坏证据拒绝、原生显示授权与身份设置、固定 SDK host contract。真实 100 次原生冷启动独立验收通过，原始记录与探针快照可重放；它不等于所有 profile/出口的 100 次覆盖，更不等于七天网站观察。实际网站门槛与发行基线缺口见全量计划。完整 373 项文件/链接核验后安装，PID 51272，四标签/七对话/账户均保留。汇总证据 `out/evidence/passive-v17c-review-result.json`；旧版保留 `before-passive-v17c.app`。
