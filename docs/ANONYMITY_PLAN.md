# 全量匿名指纹覆盖：实施与检测计划

状态：进行中。当前用户安装版为 Mac v18b，候选为 v20h；当前构建的有限回归与缺口见文末，旧版本通过项不自动继承。目标保持完整，不以局部回归代替全量验收。

## 目标与完成条件

覆盖原始《浏览器指纹匿名化清单》§0.5、§1–13、§17–18，以及后续 GPU、媒体、Worker、权限生命周期入口；提供可切换、独立存储且内部一致的身份。在 Mac 完成实现、检测、集成，保留 Metask/MetaCodes 能力与当前用户数据。跨平台声明/GPU 模型模拟仍属于目标，不因当前只实现原生 Mac 与软件后端而移除。

“全量”按命名表面与出口逐项验收，不承诺数学意义的不可识别，也不能保证所有网站永远放行。任何未实现、失败、间接证据、授权未测、平台未测都保持未完成。网站登录门槛不能记成功；限流/账号策略与指纹结果分别报告。

每个表面必须记录：来源条目、暴露 API/网络出口、原生实现位置、profile 数据源、各 realm/权限生命周期、预期保护、兼容行为、探针、对照、证据与未解释差异。禁止只改 JS getter 或只改上报字符串就声称渲染/网络一致。

## 执行顺序

| 工作包 | 工作与产物 | 完成证据 | 当前状态 |
|---|---|---|---|
| A 范围与证据账本 | 对原始条目逐一建账，现有测试映射到实际断言；保留源文档哈希 | 可机器读取的覆盖账本；缺项/错误状态均阻断完成 | 初版扩展到 57 项；逐 API 映射仍进行中 |
| B 身份与构建差分 | HTTP UA/Client Hints 与 Window/iframe/Dedicated/Shared/ServiceWorker 对齐；Navigator、插件、DOM、原生绑定、版本/编解码/品牌差异 | P1/P4/P9/P11/P12；同版本官方基线；有意隐私差异明确登记 | 先增加原生采集，修复可复现差异 |
| C 全局 profile | 扩展身份 schema，平台/架构/触控/内存/显示/时区/语言/GPU/网络策略联动；配置验证、复制、重启、旧版本迁移；账户设置独立配置 | 正反例、跨 realm、HTTP/JS、一致性矩阵、原生 UI 实测 | 已有部分；跨平台/GPU 模型未完成 |
| D GPU 与渲染闭环 | WebGL1/2 参数/扩展/精度/渲染与 WebGPU 特征/limits/adapter/device 一致；真实 GPU 模型模拟需实现能力与渲染约束 | P6/P7；真实 shader/compute/readback、worker、越界与负例；平台基准库 | v16 部分通过；任意型号模拟未完成 |
| E Canvas/字体/Math | 完整出口清单、字形与度量、CSS/SVG/Offscreen/WebGL 媒体转移、alpha/F16/大图、统计重建与性能；跨系统字体/数学残差 | P6/P8/P11、图形/文本真渲染、固定内容/变化内容、平台差分 | 已有出口测试；统计与跨系统仍缺 |
| F 媒体与授权设备 | 音频 DSP/Worklet、设备标签/数量/能力/延迟、真实摄像头麦克风/输出选择/桌面采集；USB/HID/蓝牙/串口/定位/WebAuthn/传感器最小披露 | 合成自动化 + 原生授权/撤权/重授权/保留对象 + 真实硬件验收；拒绝路径不算支持成功 | v16 合成路径通过；真实授权与其他 API 待测 |
| G 网络与存储 | TLS ClientHello/H2/H3/头序/Client Hints、代理/WebRTC/DNS/连接信息；Cookie/Storage/配额/缓存/ServiceWorker 分区、持久化与清理 | P1/P2/P3/P12/P13；自有端点直测，不用会改握手的 MITM 证明终端 TLS 一致 | 网络实测与完整存储账本待补 |
| H 构建产品差异 | PDF/插件、codec/CDM、API 可用性、品牌、真实四段版本与 UA reduction、field trials、组件/字体 | P9/P10 与官方同版本差分，未解释差异为零；授权受限组件单列未完成 | AVC/AAC/ClearKey 已测；商业 DRM 与官方基线待补 |
| I 网站检测 | 原始名单小红书/淘宝/天猫/1688，另 B 站媒体业务；测试页与公开检测页分别记录 | P14 允许的正常页面采集；同网络/账号/节奏的官方对照；拒绝、验证码、登录、限流分别报告 | v16 公开流程已记录；登录态与站点指纹差分缺 |
| J 稳定与隔离 | 同身份 100 次正常冷重启、不同身份隔离、不同站点分区、保留对象/导航/BFCache/进程切换；七天观察 | 只比较声明稳定的字段，时间/网络/配额等动态字段单独建模；记录每次引擎/探针哈希 | v17c 原生身份已实测 100 次；完整表面/各模板与七天仍未完成 |
| K 集成回归与交付 | 完整 MetaCodes SDK、浏览器工具、多模态、MCP、账户、配置/会话恢复；保留真实登录与标签 | 当前框架哈希下全套原生/软件检查、证据反例、SDK contract、安装清单、真实会话语义快照 | v17c 已交付；后续每次引擎变更重跑 |
| L 终审 | 对全部账本要求逐项读证据；发布报告与缺口数；无遗漏再判完成 | 账本所有必需项通过、证据存在且指向当前构建；D/C/S/W 要求各自独立满足 | 待完成，目标保持 active |

## 统一检测设计

1. 本地自有 origin、独立无 SDK 测试 profile，真实有界面浏览器；不注入伪装脚本，不读取或复制真实账号 Cookie。
2. 原生采集 HTTP 与 JS；跨 realm、不同 origin、冷重启都执行。显式区分检查失败和采集成功，空值/空集合不能默认为通过。
3. 现有原生/SwiftShader 109 项 + 五模式 + 31 类损坏证据拒绝 + 显示/身份 UI + SDK 保持作为回归，不能替代新增条目。
4. 原生保护/关闭/例外/全局关闭/开发者为策略对照；同版本官方 Chrome 为发行基线。当前本机 Chrome 为 155.0.8059.82、引擎为 154.0.8037.97：可以辅助观察，不能冒充同版本通过。Brave 154 也不等同官方 Chrome 基线。
5. P1–P14 与十维一致性矩阵逐项建探针；每项输出 checks/details、差异、采集错误、构建/探针/来源哈希，写 0600 证据。出现失败先分类，再修正实现或错误的测试前提，保留失败原证据。
6. 外站仅执行正常导航和已有授权的只读业务；遇登录门槛/验证码/限流记录实际状态。真实设备与商业 CDM 不能由合成结果代证；需要的实际交互或凭据只在依赖到达时明确提出。
7. 100 次冷重启及七天观察按原始要求真实执行；持久任务记录开始/结束时间和每次采样，不能预填完成或压缩成快速循环。

## 原始报告需要核实的假设

原始材料是采集清单和线索，不是浏览器规范：不能把所有 Windows 设备假定为触屏、不能把 UA reduction 的零段号自动当缺陷、不能未经源码/实测断言桌面 Battery 不存在、不能凭 Chromium 网络栈相同便宣布 TLS/H2 全绿；也不能用代理重终结后的握手证明浏览器原始握手。逐项以固定版本源码、实际运行和官方对照验证。

## 下一步

先完成 A 的逐条账本与 B 的统一采集：把尚未检测的身份、网络提示、DOM/插件、权限/存储表面暴露出来，再按证据修引擎。完成一个工作包即更新账本和 TinyKG，父目标仅在 L 终审满足时关闭。


## 本轮实测进度（2026-10-17）

- 已建立 `docs/privacy-requirements.json` 初版 54 条来源/扩展要求账本；`scripts/audit-privacy-coverage.py` 会拒绝缺项、缺证据及未完成项。当前审计如预期返回未完成，不把初版账本视为已经穷尽所有 API。
- `identity_surface_runner.py` 已在 v16 原生保护/关闭模式完成五 realm 与 HTTP 采集。精确 OS 高熵、网络信息与配额仍可观察；Battery API 实际存在，源码原生直通，但本机当前返回标准满电默认值，不能凭这一样本宣称电池物理信息已保护。
- 受控慢/快/离线网络变化证实 v16 的保护模式仍向 Window、Worker、owner 销毁后的引用公开 RTT/吞吐及变化事件；严格新门禁拒绝 v16，同时关闭模式对照正常响应。
- v17 已在 H200 交叉编译、打包、352 项引擎文件校验并拷回。新 Battery 不订阅系统电池变化；NetworkInformation 固定公开类型/质量，保留 saveData 与真实 navigator.onLine。冻结对象策略，关闭保护仍走原生路径。
- v17 的身份/被动信号共 24 项检查通过，7 项证据契约负例通过；证据 `out/evidence/identity-passive-v17.private.json`、`identity-surface-contract-v17.log`。受控电池断言不能替代真实电池状态迁移实测。
- 完整 109 项 GPU/媒体回归已通过，五模式隐私回归正在运行，当前用户应用仍为 v16、PID 45437；新候选未替换真实用户会话。精确平台版本、存储配额及其余计划保持未完成。


## 第二轮审查与修复（v17c 候选）

五模式验收拒绝了 v17：不同持久身份的 HDR Canvas 输出碰撞。固定版本 `NoiseHash` 使用 FNV 更新，三个半浮点扰动选择仅消费低位；原路径的整个模式只取决于 token 的少量低位。新混合器先对全部 64 位做 avalanche，再按像素选择 RGB 微扰。原生独立测试覆盖全部 64 个单比特变化及 256 组仅高位不同的种子，不将其表述为密码学 PRF。

首版修正 v17b 通过身份分离但未通过重启稳定性。固定源码与编译参数证明 `DCHECK_ALWAYS_ON=1`，`base::FastHash` 在这一配置下混入进程地址；8-bit 旧路径也使用这个不适合持久化的校验函数。v17c 两个出口均改用明确保证持久稳定的内容校验，8-bit 种子也先混合完整身份材料。两种噪声均不承诺抵抗 chosen-content/归一化重建，残差检测单列必需项。

同一对原先碰撞的持久 root secret 已复用验收，没有换身份来绕过失败：v17c 通过身份分离、正常冷重启和五模式验收；损坏证据拒绝增加为 32 类。最终框架下 109 项 GPU/媒体、原生显示授权与身份设置通过。失败候选及失败报告保留，尚未替换真实 v16 用户应用。

新增 `fingerprint_stability_runner.py` 与独立验收器，记录每次真实启动/正常原生退出、同一持久身份、HTTP/JS 五 realm、Canvas/字体度量/音频实际渲染、WebGL1/2 参数/扩展/精度/像素，以及原始证据哈希；严格拒绝仅填成功计数、99 次当 100 次、PID 复用、身份轮换和渲染漂移。动态时间/网络/配额/窗口位置保留原始观察但不当作固定身份字段。100 次与七天要求仍待实际证据，不因采集器实现而记完成。


## 当前已交付状态

v17c 已安装运行，PID 51272；保留四个网站标签、七个对话语义内容和 Metask 登录，旧完整应用备份 `out/macos-arm64/before-passive-v17c.app`。109 项 GPU/媒体、24 项身份/被动信号、五模式、32 类损坏证据拒绝、原生显示/身份及 SDK host contract 通过。新独立验收器复核 100 个不同进程的正常冷启动/退出、同一持久身份和所有原始记录，纳入本轮稳定签名的字段、Canvas/字体度量/音频/WebGL 无漂移；原始探针和验收器快照也已保存并重放验证。该结果限于本轮原生 Mac 身份和签名表面，不能代替所有配置/P4–P8 出口、不同 GPU 后端或七天网站观察。

汇总与内容哈希：`out/evidence/passive-v17c-review-result.json`。五个网站两后端均完成采集：B 站搜索/详情/实际播放都通过，1688 原生公开搜索/详情通过、软件模式登录门槛；小红书/淘宝/天猫都为登录门槛。

官方 CfT 目录未提供精确 `.97` 测试包；同分支 `.92` 下载内容通过官方 HTTPS 对象校验和及 ZIP CRC，但原包没有资源签名封套，深层资源签名检查失败，隔离启动还遇 Mach rendezvous 权限错误、导航超时。没有重签或关闭沙箱来把它写成通过，也不据此断言普通官方 Chrome 同版本包不存在。发行差分基线仍未完成。

下一工作包优先处理精确系统版本/Client Hints 与全局 profile 的统一数据源，再处理存储配额、分区和其余授权设备出口；跨平台/GPU 模拟、残差重建与七天检测继续保留为完成条件。目标保持 active。


## v18b 候选：系统版本策略与接口清单（未安装）

原生账户的全局身份设置增加“系统版本隐私”：默认仅公开主版本，可显式选择系统完整版本。元数据由共同的原生策略生成，HTTP Client Hints 与 Window、iframe、各类 Worker 采用同一来源；保护开关不擅自覆盖身份设置。旧配置缺字段默认主版本且不静默改写，非法配置被拒绝。当前仍是 Mac 原生平台模板，不等于跨平台或 GPU 仿真。

v18b 已在 H200 交叉编译并拷回，352 文件引擎清单已校验。原生/软件后端各五模式、各 70 项身份检查均通过，合计 140 项；12 模式 109 项 GPU/媒体、五模式隐私、32 类损坏证据拒绝、原生账户设置与七 realm/HTTP、显示授权撤销和 SDK host contract 均通过。100 次真实冷启动正在执行，完成前不使用历史 v17c 的 100 次结果代替。实际用户运行的仍为 v17c；四个标签、七个对话及 Metask 登录不在隔离测试中修改。

修正测试环境的系统凭据隔离：先前官方 CfT 隔离启动触发了“Chromium Safe Storage”钥匙串请求，系统弹窗阻塞焦点和导航。已只对该明确匹配请求选择拒绝，未输入密码或授权；所有自有 QA 启动使用 mock keychain，原生身份子进程仅在父进程显式携带此测试开关时继承。正常产品启动不添加此开关。之前的导航失败不能单凭事后 Mach rendezvous 日志认定为沙箱问题。

官方同分支 CfT .92 在隔离凭据后完成辅助对照；精确 .97 的发行对照仍未完成。前台激活后仍有两条深色模式偏好差异未解释，差分结果保留为待审查，未归零或当作通过。测试版、不同补丁的结果不能证明官方发行等价。

生成式 Blink 接口目录有 2,255 个类型、18,489 个成员，包含 1,075 个带条件启用的成员，全部保持 unclassified。独立完整性审计发现并修复了生成接口的虚拟路径未绑定实际文件问题：1,389 条声明补齐来源，实际绑定 2,182 个源文件。新审计校验成员定义、来源、计数、引擎和构建收据，拒绝删项、重复、条件篡改与虚构通过；清单本身不证明运行时存在或已保护。

证据入口：`out/evidence/identity-v18b-build-receipt.json`、`identity-version-v18b-{native,software}.private.json`、`mac-identity-ui-acceptance-v18.json`（实际在 v18b 上执行）、`display-permission-acceptance-v18b.json`、`idl-v18b-catalog-bound.private.json`、`idl-v18b-integrity.json`。下一步将条件启用接口（例如 cpuPerformance）、存储容量与分区、权限设备链路逐项关联运行时与保护证据；全量目标继续开放。

存储源码和当前 25 个估计值已交叉核实：固定版本的普通站点默认公开 `10 GiB + usage`，不是实际完整磁盘大小。见 `quota-source-audit-v18b.json`、`quota-observations-v18b.json`。低容量回退、特殊授权、Buckets、分区、写满错误和时序推断尚未验收；STORAGE 只记 partial。


## v18b 最终交付与下一轮入口

v18b 已替换安装并运行（交付时 PID 58083），完整 373 文件清单通过；四标签、七对话语义内容与 Metask 登录完整保留，旧完整应用为 `out/macos-arm64/before-identity-v18b.app`。140 项身份、109 项 GPU/媒体、五模式隐私、32 类损坏证据、原生身份/显示授权和 SDK host contract 通过。实际 100 个不同进程的冷启动/原生退出完成，独立逐原始记录验收与探针快照重放均通过；仍只覆盖本轮原生身份和采集表面。

最终五站两后端：B 站均完成搜索、详情和实际播放；1688 原生公开搜索/详情通过、软件模式登录门槛；小红书/淘宝/天猫均登录门槛。全部业务通过仍为 false。

内容哈希汇总：`out/evidence/identity-v18b-review-result.json`。下一轮先处理 `privacy-open-findings-v18b.json`：一是非法隐私模式/损坏 root 的源码返回空 token，需用隔离坏配置实测并实现明确的失败恢复，不能静默旋转身份或回退裸值；二是 `Navigator.cpuPerformance` 等条件启用接口的实际开启路径尚未验证。随后完成存储特殊分支、分区、全设备/API 映射、跨平台/GPU 和剩余完整计划。上述发现保留为 open，不以当前回归通过为由关闭。全量目标保持 active。


## v19b 在研：异常配置与 CPU 性能档位

隔离 Mac v18b 的实测确认：非法/空隐私模式、无效 Base64/短 root 均退回原生被动信息；后两者未覆写原 root。默认保护下 Window/iframe 的 `cpuPerformance` 可读并返回本机 Ultra=4；不能仅因 IDL 带条件注解就认为默认没有暴露。原始证据 `privacy-config-v18b-before.private.json`，保留对象对照 `privacy-cpu-retained-v18b-before.private.json`。

v19b 源码改为非法模式仍 balanced、CPU 档位 protected 固定 Mid=2；Navigator 创建时捕获所属上下文策略，供 CPU 档位和核心数 bucket 复用。损坏 root 在 ProfileImpl 初始化前显示明确错误并拒绝 async/sync 加载，缺失 root 才视为新身份；下层对绕过初始化的损坏状态拒绝返回裸 token。保留原值、不给网页根密钥、不自动重建身份。四种坏输入及显式恢复的原生 UI 验收仍待新包实测，不能把交叉编译成功记为功能通过。

H200 v19b 框架交叉编译已成功，完整打包进行中；当前用户应用仍 v18b PID58083，SDK-free v18b 另保留于 `out/mac-privacy-v18b-backup/MetaBrowser.app`。全量范围和其余未完成条件不变。


v19b Mac 实测进展：352 文件引擎传输校验通过；五模式验证 CPU/Malformed-mode 策略，Window/iframe/保留对象 protected=2、关闭对照原生=4，Worker 不新增暴露。四类损坏 root（Base64、长度、显式空值、错误 JSON 类型）均原生报错且没有访问所请求测试站点，原值未覆盖；同目录显式恢复密钥后均正常访问且恢复值不轮换。启动早期 Cocoa NSAlert 的 AX 树为空，已用限定 PID 的实际窗口截图与 Vision OCR 核实提示，失败的前三轮证据保留，未仅靠日志写成成功。原生截图已归档。

证据汇总 `privacy-v19b-candidate-review.json`、`privacy-config-v19b-acceptance.json`。GPU/媒体完整回归正在运行；当前实际用户仍 v18b PID58083，未替换。Chromium 原生 unit_tests 仅修改注册了新断言，尚未执行，不算已过。完整 Preferences 文件 JSON 解析/读取失败等路径仍需单独测试，不能用四种字段错误的通过宣称所有配置损坏都已覆盖。

v19b 12 模式 109 项 GPU/媒体回归已实际完成并通过，绑定框架 `2c8cb802b1a2fc6af65f165323d579aa471f3525559a7945ce419260c3aead13`；原生五模式身份回归已启动。候选仍未安装，其他完整验收与完整偏好文件损坏边界仍开放。


v19b 原生五模式身份回归已完成，但全文件损坏检测又证实：确认上游偏好文件损坏提示后，会恢复网页运行并生成与原 fixture 不同的新 root；原文件被移动为 Preferences.bad。证据 `preferences-parse-v19b-before.private.json`、`preferences-parse-v19b-confirmed.json` 及原生提示截图。v19b 因此不交付。

v19c 已增加 PrefService 初始化状态验证：成功或确认为全新 store 才可创建身份；错误/未完成状态拒绝初始化。错误文案明确“无法读取或校验”，async/sync 载入及下层 guard 共用判断。交叉编译已通过，完整打包中；新增 JSON_PARSE/JSON_TYPE 两例，并保留六类原输入、站点请求记录及恢复验证。当前用户仍 v18b；v19b SDK-free 候选已保留，旧证据不修改。


v19c 已完整拷回并通过 352 项清单校验。六类损坏输入与显式恢复的原始检查和独立验收通过，证据已归档；但原测试在弹窗确认后过早 SIGTERM，实际仍有 NSAlert.runModal 栈和看门狗记录，因此不将这些结果当作错误流程正常退出的证明。新增更严格的 Profile Picker 实际就绪/原生正常退出门禁，目前失败，继续定位弹窗层级、激活及事件投递。所有失败轮次保留；不弱化前台和窗口所属校验来点击别的应用，也未将新候选安装。GPU/媒体 109 项仅 v19b 有实际新结果，v19c 的全量回归仍待做，不能借用。完整目标保持 active。

严格原生退出门禁的 round6 尚在观测；按钮命中检查实际拒绝了一次由 PID700、layer21、window22 覆盖的点，未投递点击。继续以进程/窗口元数据定位覆盖来源，不绕过校验，不使用这次失败完成验收。


## v19c 存储分区与七类执行环境实测

新增真实存储矩阵：两个 schemeful site（127.0.0.1 与 localhost），四种顶层/交叉嵌入上下文，IndexedDB、CacheStorage、OPFS 与显式 512 KiB Bucket IndexedDB。窗口和 iframe 实际写/读/删除；Dedicated、Module、Nested、Shared、Service Worker 从其原生存储环境读取并比对。保护开启/关闭两组各五个真实启动与正常退出，验证同身份重启持久化、独立 profile 不串数据及清除后重启不恢复旧值。450 项断言通过，12 类损坏证据被拒绝。当前采样所有 realm 原生 quota headroom 为 10 GiB，显式 bucket quota 保持512 KiB；没有把原生正确行为假称为新增虚拟化。

汇总 `out/evidence/storage-seven-realms-v19c-review.json`，探针快照 `storage-seven-realms-v19c-probes`。旧窗口版及三 Worker 阶段的结果/源码另保留，不能替代新矩阵。重新生成并校验了当前框架的18,489成员IDL清单；21个成员关联到 `docs/privacy-storage-api-evidence.json`，仅标 runtime partial，未把全API清单提升为已验证。

v19c 109项GPU/媒体回归也已实际通过。原生错误弹窗正常退出仍未通过；NotificationCenter PID700/layer21几何覆盖导致保守点击校验拒绝，未绕过校验或关闭用户通知中心。当前用户仍v18b，未替换。存储的Worker写入变体、无痕生命周期、权限切换、真实容量压力/低容量、Buckets枚举/过期/持久策略及其余全量范围继续开放。


## CPU 模板一致性复核（v19d 在建）

继续追到 `content/browser/cpu_performance/cpu_performance.cc` 后确认，当前选定的 Apple M-series、公开8核模板按上游规则归Ultra=4；v19b/c为隐藏字段统一返回Mid=2的做法，与该模板不一致。没有把“改成另一个值”继续当作正确保护。实际v19c受保护Window/iframe/保留对象是2，关闭对照为4，元数据为macOS/arm/8核，已记录 `cpu-template-v19c-inconsistency.json`；上游分类源码及哈希也已保存。该发现使v19c仍不可交付。

v19d改为依据公开核心数和当前模板推导档位，不读取私有CPU型号。当前Apple M-series模板8核得到4，generic 8核得到3，小核心数按公开分组归类；独立原生单元回归已过，实际新包运行验证尚待完成。未来跨平台模板必须提供显式模板元数据，不能把当前Mac编译平台假定用于尚未实现的伪装平台。H200交叉编译进行中；实际用户仍v18b，未替换。


v19d 已打包、拷回并通过352项文件清单校验。原生受控CPU测试先拒绝v19c，再在v19d验证公开核心数8→4→1→8对应档位4→2→1→4，Window/iframe和保留Navigator共15断言通过；关闭源暴露的CPU型号路径未用于受保护返回。这不是跨平台/完整CPU模拟的证明。当前候选汇总 `privacy-v19d-candidate-review.json`，其余完整回归正在继续，实际用户仍v18b。


## v19d 当前回归证据

v19d 已完成双后端身份/版本策略、GPU/媒体，以及 balanced/off 两模式七类执行环境的存储测试。存储共 10 次真实启动、450 项检查，独立重放及 12 种损坏证据拒绝通过。新引擎的 IDL 清单完整性通过，21 个存储 API 的有限运行证据映射见 `privacy-storage-api-evidence-v19d.json`；这不构成 API 完整隐私验收。五模式字体/Canvas 等回归继续执行。用户安装版保持 v18b；原生损坏配置错误窗口的干净退出、无痕/配额压力、跨平台及任意 GPU 等仍未完成。

五模式回归已完成并通过严格 review 门禁，32 类损坏证据全部拒绝。测试使用隔离目录和合成 canary 字体，字体已清理、各浏览器进程正常退出；不代表全量检测完成。


## v19d Worker 写入与无痕存储生命周期

新增专用 mutation/OTR 探针，不改写此前只读 Worker 的历史证据。四类存储（IDB、CacheStorage、OPFS、Bucket IDB）在 Dedicated、Module、Nested、Shared、Service Worker 中实际写入/删除，并由窗口独立读回。普通与原生无痕各两种保护模式，共 20 次正常启动退出、2,580 项检查；普通 32 类、无痕 33 类损坏证据均拒绝。无痕每次重启均为空，当前会话内功能可用。

首轮无痕探针错误地要求命令行 OTR 出现在 DevTools 创建的上下文列表中，失败记录保留。固定版本源码证明该列表只枚举 DevTools 管理的 OTR；最终门禁直接要求目标 context ID 与显式 original-profile context ID 不同，并保留两个原始 ID。未降低数据隔离与正常退出要求。

证据索引：`out/evidence/storage-worker-otr-v19d-review.json`。21 个命名 API 的有限运行证据各映射为 `privacy-storage-worker-api-evidence-v19d.json` 与 `privacy-storage-otr-api-evidence-v19d.json`；仍不认证完整 API 隐私。配额压力/低容量、授权变化、并发、过期/耐久策略及普通/无痕同时打开的交叉隔离待测。引擎本轮未改变，真实用户应用仍为 v18b。


## 同时打开普通/无痕窗口：v19d 阻断项

新增同进程普通窗口与 DevTools 创建的原生 OTR 窗口矩阵。v19d balanced/off 均在 OTR 销毁时触发 `WorkerWatcher::DisconnectSharedWorkerClient` 的 `IsServiceWorkerNode` 断言，不能交付为完整生命周期通过。off 组保留了崩溃前 10 个阶段的原始 checkpoint，但不以其代替整组通过。失败证据 `out/evidence/worker-stop-v19d-failure-review.json`。

固定源码中 `OnVersionStoppedRunning` 先把 service node 从 map 移出，再断开尚未送达移除通知的已死 Shared Worker 客户；类型校验正是遍历这个 map，故失败。v19e 补丁让 map 保持所有权直到断连完成，再删除节点；断言保留。新增 Chromium C++ 回归覆盖先失去 Shared Worker、Service Worker 停止后才收到 client removal 的顺序，尚未声称执行该 C++ 测试。

同时修复 staging 旧 replacement 是新值前缀时重复追加 CPU header 的问题；实际 helper 回归通过，H200 固定源码整套 staging 再次执行为零变更。最终引擎重建进行中；用户 v18b 不变。


v19e 已打包、拷回、352 项 manifest 和 receipt/source script 哈希链核验。相同探针源码下 balanced/off 同进程普通/DevTools-OTR 回归均正常退出，共 3,096 项检查，25 类损坏证据拒绝通过；旧 off 源码哈希与新探针逐字节一致。证据 `out/evidence/storage-concurrent-v19e-review.json`。这证明了指定原生 OTR 销毁场景修复，不将其扩大为命令行主无痕窗口关闭或同时在途写入均通过。新引擎其他回归继续，未替换用户 v18b。

新引擎 v19e 的受控 CPU 模板测试亦已实际完成：15 项检查及正常退出通过。GPU/媒体 12 模式回归继续；原生错误窗口的正常退出、真实设备授权、主无痕窗口关闭、配额压力等缺口保持开放。

GPU/媒体 12 模式、109 项在 v19e 上已全部完成并核对探针/fixture 哈希。保护/关闭/开发者/例外/全局偏好对照与原生/SwiftShader 均通过；这是合成媒体和指定 GPU 能力的回归，不代替真实设备、CDM 或任意 GPU 模型验收。


## 真实小容量卷与额度压力

v19e 的有限压力矩阵（窗口/Dedicated Worker 的 OPFS、IDB、CacheStorage，fresh-origin2MiB CDP override/显式2MiB bucket，8MiB 写入）72 项控制及48类负例通过，正常写入、失败回滚、解除限制恢复均验证。首轮64KiB小于部分元数据开销，且旧IDB上下文有缓存授权，测试被拒绝；原始失败留存，不将拒绝全部API当成成功。

独立2GiB APFS稀疏映像实测：卷实际total2147442688字节，image分配约18MiB；v19e保护开启仍上报2GiBheadroom，现代/旧式quota和隐式bucket均泄漏低卷容量。均正常退出和卸载。

原生修复冻结每个绑定的隐私策略，UI获取boolean后传IO，不把Profile/pref或身份秘密传给IO；统一公开额度为usage+10GiB，真实执行限制、错误和显式bucket额度保留。显式bucket估算前刷新数据库元数据，避免长期使用旧快照。v19f编译/拷回验证后，真实卷测试拒绝窗口/旧式API，发现它们使用独立frame binder；Worker与隐式bucket已归一化仍不能算全通过。v19g补齐frame binder正在构建，未有运行成功声明。

证据：`out/evidence/quota-pressure-v19e-review.json`、`out/evidence/storage-capacity-v19e-v19f-failure-review.json`。完整目标及实际磁盘耗尽、主无痕窗口关闭、权限/并发/过期、跨平台/GPU/设备等缺口保持开放。日常用户v18b未替换。


v19g已完成H200交叉编译/打包/拷回，352项manifest及receipt/script链核验。与失败v19e完全相同的低卷探针在balanced/off两模式均通过：各48个额度观测，8个显式bucket额度检查，正常退出并卸载实际APFS映像。保护开启统一公开headroom10GiB，关闭仍走原生约2GiB；旧式Temporary/Persistent查询和隐式bucket均覆盖。

新引擎的2MiB受控额度压力矩阵72项通过，回滚/正常数据以完整SHA256比对，16类低卷与54类压力证据损坏全部拒绝。CPU15、GPU/媒体12模式109项亦在v19g实际通过。证据 `out/evidence/storage-capacity-v19g-review.json`。这仍不证明实际磁盘写满、活动页面偏好切换/晚绑定、bucket政策变化/过期/任意参数或全API隐私。主无痕窗口关闭、配置错误UI正常退出、完整引擎其他回归及全量目标保持开放；用户v18b未替换。


## v19h：bucket 个数不再推算卷容量

v19g 新实测发现，尽管估算值已归一化，实际创建 bucket 的个数仍由真实 quota/20MiB 决定；2GiB 卷所有所测上下文均为总数61，仍泄漏容量。v19h 由浏览器 UI 生成保护标记，使用 C++内部 BucketInitParams 传到 IO；该标记不由 renderer options 提供，也不写入网站数据。受保护模式使用10GiB公开组对应的512总 bucket 上限；关闭保护、原有 unlimited 授权和真实字节限制保留。

2GiB/4GiB × balanced/off 四组真实 APFS 卷测试均通过，共320项：保护组均512（含默认bucket），关闭对照分别61/116；窗口、跨站iframe、DedicatedWorker 覆盖六种正额度（至MAX_SAFE_INTEGER）、重开保持既有额度、到上限后的清理与恢复。说明：源码确认 open() 不修改既有 quota，不能把8MiB重开参数误认成额度变更成功。

4GiB关闭组首轮因CDP端口已开但page尚未创建而退出，失败记录保留；等待真实page target后重跑通过，容量断言未放宽。前三组旧收集源码的完整快照保留并独立重放。19类损坏证据拒绝；新引擎实际字节压力72项（完整SHA回滚）、CPU15、GPU/媒体12模式109项通过。四个命名API仅映射有限运行证据，完整IDL清单仍全未分类，不计全覆盖。

证据 `out/evidence/bucket-policy-v19h-review.json`、`privacy-bucket-policy-api-evidence-v19h.json`。权限/活动偏好切换、其他Worker计数压力、过期/耐久、主无痕窗口关闭、实际磁盘耗尽及完整API仍未完成；用户v18b未替换。另已取得配置错误弹窗的启动顺序源码证据，`native-startup-error-source-audit-v19h.json` 仅为下一步假设，未实现或宣称修复。

原小容量卷现代/旧式/Worker/隐式bucket 48个额度观测×两模式及16类负例，也已在v19h重新实测通过；为该fixture同步修复page就绪等待，旧收集源码另存快照。不会以v19g旧数据替代新引擎的这组验证。


### v19i / v19j 原生身份拒绝路径（验证中）

v19i 的严格单例测试已通过原生警告确认和实际配置选择器就绪检查，但正常退出发生原生崩溃，因此不予验收。堆栈指向 ProfileManager 析构访问已释放 Profile：同步工厂提前返回空值时，先前登记的非拥有 ProfileInfo 尚未移除。证据：`out/evidence/privacy-root-v19i-lifecycle-review.json`。

v19j 将拒绝分支移到管理器接管所有权之后、最终初始化之前，安全移除登记，正在 H200 交叉编译。六类损坏输入、无网站请求、恢复原身份、配置选择器就绪及正常退出必须重新实测；目前未通过。全量 API、跨平台/GPU、真实媒体权限、网站业务验收及长期稳定性目标仍开放。


### v19j 六类原生生命周期通过，重复启动发现缺口

v19j `b8930dce3bda366d4a35451ae1c192532383fd8cb0ddafc8b624c0aaf66c77ad` 交叉编译、完整打包、352 文件传输校验及源码收据链通过。六类损坏输入均证明原生提示、无网站请求、真实选择器就绪、正常退出及显式恢复原身份后导航；独立回放和 10 类证据篡改拒绝通过。测试采集源码快照保留于 `out/evidence/privacy-root-v19j-six-round2-probes`，第一次遗漏 AX 上游提示处理的失败也保留。

但追加的“不修复直接第二次启动”测试失败：原始 JSON 已重命名为 Preferences.bad，缺失 Preferences 被当成新配置并生成替代身份。故 v19j 不满足完整恢复验收，不交付；证据 `out/evidence/privacy-root-v19j-repeat-failure-review.json`。v19k 在现有文件读取序列将“缺失 profile Preferences 且有 .bad”判为持续 JSON_REPEAT 错误，保留原备份；有效显式恢复仍允许。当前正在 H200 交叉编译，尚未实测。总目标仍开放。


### v19k 重复启动拒绝与恢复验证通过（未安装）

v19k `65947a3aac9a46165f76de8d0c78d553d7a509c119a3eec92955e9e5b250592f` 已完成 H200 macOS ARM64 交叉编译、完整打包、352 文件校验及 22 个构建输入收据链校验，重复 staging 无改动。先通过两次不修复 JSON 解析错误启动；再通过六类损坏输入各连续三次启动，共 18 次明确警告、无网站请求、原数据保留、实际配置选择器就绪及正常退出，最终六次显式恢复同一原身份后均可导航。独立验收与 18 类篡改记录拒绝通过。

原始证据 `out/evidence/privacy-root-v19k-six-repeat3.private.json`；采集/验收源码快照 `out/evidence/privacy-root-v19k-six-repeat3-probes`。第二次启动 JSON_REPEAT 对应另一条原生上游警告，首次测试遗漏该文案的失败保留，修正精确文案处理后重新完整采集。所有隐私断言保留。正常新配置的 CPU 一致性 15 项通过；GPU/媒体新版本回归进行中。

以上仅关闭受测损坏文件启动/恢复路径，不等于所有文件故障、异步配置加载或全量隐私验收。正常使用版本仍 v18b，尚未替换。其余 57 项范围、跨平台/GPU、真实设备权限、网络、网站业务验收、全 API 与长期稳定性保持开放。


v19k 后续回归已完成：GPU/媒体 12 模式 109 项、CPU 15 项、身份原生/软件 GPU 各 5 模式共 140 项、五种隐私配置独立验收通过，配置证据 12 类篡改被拒绝；身份与 GPU 证据合约各 8 测试通过。当前所有本轮任务均终态，没有后台编译或 GUI 测试遗留。审查记录 `out/evidence/privacy-v19k-candidate-review.json`。尚未重新验收当前版本存储、显示、SDK、100 冷启动、真实设备权限、网站业务及长期观察；仍未安装。


### v19k 存储扩大验证与后台联网缺口

当前版本普通/DevTools 无痕并存两组共 3096 项、配额压力两组共 72 个全内容哈希/回滚/恢复用例通过；分别拒绝 25/54 类篡改证据。真实 2 GiB APFS 卷开启/关闭保护各 48 个容量出口通过，低容量合约扩展后两组各拒绝 16 类篡改；此前关闭状态因脚本只允许 balanced 的前置限制失败，原日志保留。

Bucket 元数据当前 2 GiB 开启/关闭两组共 160 项实际采集与独立验收通过，开启状态 19 类篡改拒绝通过；关闭状态合约脚本仍只允许 balanced，前置限制失败，不宣称关闭状态篡改验收通过。当前 4 GiB 矩阵尚未执行。

优先处理新确认的网络缺口：全新 SDK-free 配置只打开 about:blank 30 秒，即使关闭后台联网/组件更新，NetLog 仍记录六个 Google 主机上的 14 个 URL 请求任务。包括账户列表、AIM 资格、搜索预热、网络时间、模型清单组件及 GCM checkin/register。原生响应头记录存在 200，但尚未逐请求归因/审查有效负载，不据此宣称个人数据泄露。下载组件 ceof... 为 OptimizationGuideModelsManifest（约 131KB），不是完整模型权重。

证据 `out/evidence/privacy-v19k-network-residual-review.json`，下一工作包 TinyKG 13161：原生限制浏览器内部未授权主动请求，同时保留用户主动访问 Google/Gmail 与明确权限允许的功能；不采用全域名封锁。AIM 源码注明仅关闭 UI/政策仍会发请求，必须验证真正请求路径。当前无后台编译/GUI 任务遗留；仍未替换日常版本，总目标开放。


### v19l → v19m：原生后台网络，不以零 HTTP 冒充零联网

v19l 交叉编译并实际验证后，60 秒空白启动 HTTP 请求已为零，但仍有 Google DNS 和 QUIC/UDP 发送，故验收失败，保留 `out/evidence/privacy-v19l-network-review.json`。诊断开关恢复后台服务时六个 Google 主机请求重新出现。

v19m 框架 `2caef772847daec436dbb3876a5b42e5d840d7473e923f98ade97b8d5261d186` 新增原生默认搜索预连接入口限制及浏览器 DICE/Mirror 账户一致性关闭；AIM、浏览器账户枚举、时间服务、Google 模型清单/执行/质量日志、非网站授权 GCM 已原生约束。网站导航未作域名封锁，网站推送仍沿用原权限和 wp: 订阅入口，实际兼容性待验收。

H200 完整打包取回后，352 文件、25 构建输入/收据链通过。实际四次正常退出：全新配置 60 秒、曾开启诊断后关闭的复用配置 60 秒、从 v19l 控制配置升级 60 秒，均无 HTTP/WebSocket 请求、DNS 请求、连接及原始 TCP/TLS/UDP/QUIC 发送事件；后两种已有身份保持不变。30 秒显式恢复内部服务的对照重新触发六个 Google 服务主机。独立原始 NetLog 重放和 27 类篡改/缺失证据拒绝通过。

采集器原版漏计 SOCKET_BYTES_SENT/SSL_SOCKET_BYTES_SENT 摘要，但原始日志完整；独立验收重算所有 *_BYTES_SENT，拒绝 TCP/TLS-only、UDP-only、QUIC-only、DNS-only 及空日志伪装安静。四次采集源冻结于 `out/evidence/background-network-v19m-probes`。随后已修正当前采集器摘要为 schema2；其尚未重新原生采集，不将源更新冒充新执行。当前独立验收/源码快照和全部证据见 `out/evidence/privacy-v19m-network-review.json`。

同时修复 Canvas/媒体 staging 的相同内容反复写入：实测重复构建 Ninja no work 且 v19l 框架哈希不变，v19m 仅编译两个新 C++ 文件。仍未替换日常 v18b；当前全部本轮编译/GUI 测试终态。后续须验收真实网站导航、推送权限/旧订阅、原生账户与网页 cookie 隔离、SDK/Metask 登录及当前引擎各回归门禁；57 项及 P1–P14、跨平台/任意 GPU、真实设备和七日观察保持开放。

### v19m：真实导航、网站推送与 schema2 网络回归

补充一次新配置原生 60 秒 schema2 采集，正常退出，独立原始 NetLog 回放确认 HTTP、DNS、TCP/TLS/UDP/QUIC 发送均为零；27 类负例仍拒绝。此结果补足前述“仅更新采集源码、未执行”的缺口，不扩展到所有浏览器状态。

真实 Google Accounts 和 Gmail 登录入口已通过：两处均能显示可交互的空白账号输入框和下一步按钮。未提交账号或使用真实登录信息。测试 Google cookie 由原生 Storage.getCookies 读回，浏览器没有自行删除；由测试显式清理后才导航公共站点。此前失败均保留，分别涉及 CLI 长会话名、about:blank 的 cookie 查询过滤，以及对输入框类型、中文文本长度、Gmail 落地页和无障碍名称的错误假设；未改内核绕过这些断言。

网站推送测试证明：拒绝权限时 NotAllowedError 且无外部数据发送；允许权限时真实订阅及取消成功。默认 30 秒第一次超时未通过，延长到 90 秒后两次成功；另有诊断对照和保留订阅采集。原生持久化测试权限下，重启浏览器仍取回同一 endpoint 及两个密钥的 SHA256，身份保持一致，随后取消成功。未发送任何推送消息；这是隔离配置的原生权限设置，不是系统权限弹窗验证，也未证明旧 Google 账户混合订阅兼容。无权限时出现的一次失败 UDP connect 为上游 IPv6 本地路由探测，未发送 UDP 负载，验收器仍拒绝任何 UDP 发送。

独立验收通过，拒绝 17 类推送记录篡改、4 类恢复关联错误及真实 30 秒超时；导航拒绝 12 类错误记录。源码版本、原始记录和回放摘要绑定于 `out/evidence/privacy-v19m-navigation-push-review.json`，失败记录保留。当前引擎 CPU/GPU/媒体等回归继续单独执行，不继承 v19k 的通过数字。未交付日常版本，总目标及完整 57 项保持开放。


### v19m 当前构建回归进展

CPU 模板 15 项、原生/软件 GPU 12 模式媒体矩阵 109 项、两后端各五种身份配置共 140 项通过；GPU 与身份合约各 8 个测试通过。普通窗口与 DevTools 原生无痕窗口并存的 balanced/off 两组共 3096 项通过；验收器补上 paid_model_calls 严格整数检查，两组各拒绝 26 类错误证据。旧采集源码冻结后按原哈希回放，不将新验收器冒充旧采集源码。五种健康/无效模式配置独立验收通过，12 类错误证据拒绝。源码及证据摘要见 `out/evidence/privacy-v19m-regression-review.json`。

本轮全部采集进程已正常终止，日常进程 58083 未替换。当前引擎的损坏身份恢复、配额/低容量/Bucket、原生界面与 SDK/账户/会话、100 冷启动和七日观察仍待验收；不继承旧候选版本的通过状态。全量 57 项与 P1–P14 仍开放。


### v19m：配置恢复、容量扩大矩阵与 OPFS 新失败

当前引擎六类损坏配置各连续拒绝三次，共 18 次拒绝和六次显式恢复导航通过，均正常退出；独立回放及 18 类错误证据拒绝通过。生成式 IDL 清单已刷新并绑定当前构建收据：2255 类型、18489 成员、2182 来源；完整性通过不代表保护完成。当前存储运行证据仅对 21 个成员建立 partial 映射，见 `docs/privacy-storage-api-evidence-v19m.json`，已验证成员仍为零。

2 GiB 真实 APFS 卷的保护开启/关闭两组各 48 个容量出口通过，两组各拒绝 16 类错误证据。Bucket 的 2/4 GiB × balanced/off 矩阵继续执行；已完成的结果单独归档，不能预填剩余组。修正 Bucket 负例脚本的 balanced 前置限制，关闭组改为在实际 quota 上加一，避免把合法 2 GiB 值当作负例。

压力回归原始 balanced/off 两组均出现一次 OPFS AbortError，严格 QuotaExceededError 门禁失败；正常写入、旧数据全内容哈希及重置恢复仍正确。新增诊断字段后五轮四次通过、一次在 write 阶段复现 Failed to write data to data pipe；上游 WriterHelper 在生产端中断时先返回 AbortError 的源码及哈希已归档。官方 Chrome155 四轮仅作为诊断，不能证明与当前154版本一致；原始失败不删除、压力里程碑保持失败，不能因偶发通过就关闭问题。

实际 SDK 适配器在临时 HOME、本地 mock provider 下的工具回调、取消/复用、多模态、Skill 和 checkpoint 测试通过，SDK 全包哈希检查及 Zig 核心测试通过；未改已有适配器，也未调用付费模型。这是组件证据，不是当前浏览器 UI/账户/OAuth/完整打包集成通过。新增直接 TLS 终止端点用于下一轮真实 ClientHello/HTTP2 采集，当前只有解析器和 Python TLS 客户端自测，尚不算浏览器网络指纹证明。


后续实测已完成：Bucket 2/4 GiB × balanced/off 四组共 320 项全部通过，四组各拒绝 19 类错误证据；所有 APFS 卷已实际卸载。真实浏览器 TLS1.3/h2 两组已采集，直接在自有 TLS 端点记录原始 ClientHello、SNI、ALPN、密码套件/扩展/群组/签名算法/key share 长度及 HTTP2 SETTINGS/窗口；归一化字段在开启/关闭两组一致，页面实际加载，两个不同进程正常退出，两组各拒绝 12 类错误证据。保留原始扩展顺序及 JA3，不把顺序随机化后的归一化值冒称原始 JA3 相同；HelloRetryRequest 不覆盖首次握手。仅为隔离浏览器设置临时叶证书 SPKI 例外和自有 .test 域名映射，没有修改系统信任或通过代理重签。HTTP3、HPACK 解码后的头序、同版本官方发行差分仍未证明。

汇总 `out/evidence/privacy-v19m-storage-transport-review.json` 绑定当前框架、原始记录及采集/验收源码；SDK 仅组件本地 mock 证据、当前浏览器完整集成仍未通过。OPFS 原始压力失败及间歇复现继续保持开放，不能用其余通过项覆盖。当前本轮全部采集和构建测试均终态，无后台 GUI/H200 作业，日常浏览器仍未替换。


### v19n：原生修复 OPFS 配额错误的回调竞争

依据 [WHATWG File System write-a-chunk](https://fs.spec.whatwg.org/#write-a-chunk)，配额写入失败应返回 QuotaExceededError 并保留原缓冲内容，因此保留原严格门禁。v19m 的生产端数据管道先关闭时，WriterHelper 会先返回 AbortError，掩盖随后到达的真实后端配额结果。v19n 改为生产端错误等待后端结果；后端错误优先，后端成功时保留真实生产端错误。Mojo 回调在写入端断连时有默认完成值，避免因等待后端结果增加悬挂路径；本轮未实际触发该默认回调，仍单列未验证。未提高字节配额，也未放宽错误断言。

H200 macOS ARM64 交叉编译、完整打包、352 文件传输及 25 个构建输入收据链通过；仅重编译一个文件写入 C++ 单元。重复 staging 无改动。框架 50b957c0465ef7f301e94554df96fa39ee2416d2ac266a09491a09bc26f90b66，旧 M hardlink 备份哈希仍正确，日常 v18b 未替换。

原先失败的完整压力矩阵在 balanced/off 各三轮共 216 项通过，六次真实正常启动/退出，两种模式各拒绝 54 类错误证据。新增 Window/DedicatedWorker 的 ArrayBufferView、Blob、字符串配额、取消回滚及写入中删除 Bucket 两组共 20 案例通过，共检查 36 个完整内容哈希；13 类反例同时修改原始记录与摘要后仍被拒绝，避免仅由两者不相等而误以为错误语义已验证。M 原始失败、间歇诊断与新扩展基线全部保留。

当前 N 直接 TLS1.3/h2 两组实际正常启动/退出与归一化一致性回归通过，两组各拒绝 12 类错误证据；仍不证明 H3、完整头序或官方同版本对齐。N 的 IDL 清单重新生成、收据完整性通过，21 成员仅 partial 映射、零完整验证；修正映射器不应凭缺少 worker_mutations 标志就声称 iframe/五类 Worker 已测。

汇总 out/evidence/privacy-v19n-error-fix-review.json。N 未继承 M 的其他回归通过状态；完整七类执行环境、实际断连、原生 UI/当前 SDK/账户/会话、100 冷启动和七日、跨平台/完整 GPU、真实硬件权限及全部 57 项继续开放。当前本轮全部编译/GUI/传输任务已终态。


### v19n：七类环境、六种载荷、HTTP1 头序与 Linux 诊断环境

OPFS 扩展到 Window、真实 iframe、Dedicated/Module/Nested/Shared/Service Worker；实际原生全局类型/地址、模块 import.meta、嵌套父级、Service Worker scope 与 HTTP 脚本加载记录独立核对。六种载荷为 Uint8Array、纯 ArrayBuffer、非零偏移 Uint8Array、DataView、Blob 和字符串；失败前先做 64 KiB 正常写入并验证完整内容，偏移视图 backing buffer 的额外字节用不同哨兵填充。balanced/off 共 112 案例、322 个完整内容哈希通过；两组各拒绝 26 类对齐原始记录/摘要后的语义错误及四类缺失 Worker 脚本来源。实际 Mojo 默认断连回调仍未触发，未提升为已证明。

新增直接 TLS 终止端点的 HTTP/1.1 模式，实际主导航原始头序在开启/关闭两组一致；favicon 等子请求独立保留。逐字节解析验证头名大小写及顺序，两组各拒绝 12 类通用篡改和四类原始/解码同时对齐的头伪造。首次负例迁移因 Mac 临时路径别名未 resolve 导致前置失败，原日志和源码保留后修正；未修改原生捕获或放宽路径校验。新增 H2 默认采集控制通过，旧 H2 捕获也按冻结源码重放通过。仍不证明 H2 HPACK 头序、H3 或官方发行对齐。

通过 agent-reach 阅读 [CfT 官方清单](https://googlechromelabs.github.io/chrome-for-testing/known-good-versions.json)（快照时间 2026-10-16T15:18:36.863Z），其中没有154.0.8037.97，版本元数据地址返回404；这不证明生产版不存在。同一build清单最高.92，已在H200独立目录下载/校验/解压官方Linux154.0.8037.92，未安装系统包或修改PATH。H200 Python3.10 首次在启动浏览器前因 file_digest API 缺失失败，已保留；共享哈希函数改为兼容的流式SHA256后，实际五类环境及HTTP/JS身份一致性、SwiftShader渲染、正常退出通过。独立验收拒绝九类错把不同补丁/强制软件/无界面配置当作精确版本、默认配置或真实GPU的声明。所有报告记录两版本差异、headless/no-sandbox/强制软件参数，不当作官方同配置验收。参考浏览器退出后未遗留自有Chrome进程；没有启动NVIDIA渲染负载。H200八卡常驻约140GiB/张，采样利用率从100%变到0%，不能据此推断机器已空闲。

源码核对确认全局身份页仍只支持 native-macos-arm64-v1，跨平台和任意GPU模拟未实现。Linux软件队列提供后续跨平台实现的诊断数据，不代替Windows/Linux profile、字体/Math/媒体/完整GPU一致性。新OPFS稀疏API证据表 docs/privacy-opfs-seven-api-evidence-v19n.json 仅新增九成员 partial 映射，继承 WritableStream.close/abort 限于文件流接收者，不声称通用流完整覆盖。

汇总 out/evidence/privacy-v19n-seven-realms-http1-review.json；框架未改变、日常v18b未替换。全量57项与全部原始工作包保持开放。


## v20b：原生统一身份模板（有限验证，未交付）

当前候选框架 `4c9e3ad444d2a521a8caeb4754f2295796d0373c99e318338b0a6268e92163f4`。H200 交叉编译、完整打包、29 项作者输入与构建收据链、352 项应用传输清单已核对。用户安装版仍为 v18b。证据：`out/evidence/privacy-v20b-persona-review.json`；v20a 失败记录单独保留。

新增共享的原生 Persona 数据源，连接 HTTP UA/Client Hints、Navigator 平台、CPU、内存和内存请求提示。启动时验证软件 ANGLE/WebGPU/视频后端参数，错误配置在站点启动前退出。Linux 模板仅供显式诊断，`user_selectable=false`，账户设置仍只开放原生 Mac 模板。它不是完整跨平台身份。

v20a 实测发现 UA reduction 绕过 NavigatorID，使七类环境的 platform 泄漏 MacIntel；v20b 在 NavigatorBase 修复该路径。Linux balanced/off、原生 Mac balanced 三个隔离进程均正常退出；每次检查 Window、iframe、Dedicated、Module、Nested、Shared、Service 七类元数据、HTTP/JS、内存提示、四种 CPU 覆盖状态及移除 iframe 的保留对象。Linux 两组各 18 个原始采集/汇总同时改写的语义反例被拒绝。9 组非法启动参数均返回 13，站点请求为零。通过自有 CDP SystemInfo 验证真实 SwiftShader 后端；保护模式隐藏 debug renderer 的行为不被误判为缺少软件后端。

跨平台差分仍有缺口：保护模式 15 个、关闭模式 9 个采样字段不同；字体度量、音频 DSP、蓝牙 API 可用性以及 SwiftShader LLVM/Subzero 实现差异尚未解释/解决。Linux 参照是不同补丁版本、headless 的诊断包，不能作为同版本默认发布版等价证明。采样 Math 相同不代表全数学表面。下一步优先完成字体/音频/平台 API 与软件渲染配置一致性，再开放模板；随后补当前引擎全套 GPU/媒体/存储/传输、完整 SDK/账户/UI、站点业务和稳定性验收。不继承 v19n/v19m 的旧通过结论，全部 57 项与 P1–P14 完成门保持未通过。


## v20d：身份模板接入实际音频向量计算（有限验证，未交付）

候选框架 `ee65493ebe3ba1fc491af6475e5205f4a9550c4fdf6902cec04d8720e3c01689`。证据 `out/evidence/privacy-v20d-audio-review.json`；用户安装版仍为 v18b。共享 Persona 新增 audio_vector_backend，Linux 诊断模板选择上游公共 scalar 向量实现；原生 Mac 仍使用原后端。实际连接 vector_math.cc 的 12 个既有调用点，包含两个 Vclip 重载，未宣称全部调用点已获运行覆盖。公共数据源与计算路径已更接近目标，但完整 Linux 模板仍不对用户开放。

当前 D 在三个新进程内完成 96 次实际音频图渲染、192 个完整声道哈希：四采样率、立体声、增益/混音/128 抽头非整系数卷积/振荡器压缩器；检查解析计算误差、非静音/有限值、事件/Promise 缓冲区身份、读取与复制一致、进程内重复稳定。Linux balanced/off 两组各拒绝 15 个原始/汇总同时改写的语义反例。原生 B/C/D 的非整系数矩阵全部相同；Linux 模板的 16 个卷积声道哈希变化，C/D 配置计算结果相同。复查发现早于命令行初始化的调用可能永久缓存原生后端；直接编译实际暂存函数，以 readiness/persona mock 复现旧逻辑失败并验证修复。没有宣称真实浏览器启动中已观察到该早期调用。

在 H200 已有官方 CfT 154.0.8037.92 的纯软件/headless 路径运行同一非整系数矩阵，32 次渲染/64 个声道哈希的功能断言通过；与 D 比较 36 个相同、28 个不同（卷积 16、压缩器 12）。它是不同补丁版本、环境和构建的诊断参照，不能作为同版本默认基线。原始 44100Hz 指纹的 4500:4510 和值仍有差异；不能根据有限图形相等声称音频已覆盖。当前 D 的 Linux balanced/off 七类元数据与 HTTP/CPU/保留对象检查通过，18 个语义反例被拒；9 组非法启动均退出 13、站点请求为零。

重新生成并审计绑定当前 D 构建的 18489 成员 IDL 目录；12 个确实调用的音频 API 加入 `docs/privacy-audio-api-evidence-v20d.json`，仅部分运行证据，完整验证成员仍为 0。AudioBuffer.length 没有直接断言，未据硬编码 fixture 帧数误标为覆盖。

下一实现顺序：为共享 Persona 增加 FFT 后端选择，优先复用现有 RustFFT 接口；须区分规划器/缓存键与确定性 twiddle，现有 FftPlanner 自动选择 CPU 且 angle.sin_cos 仍依赖宿主，单开 RuntimeEnabledFeatures 开关不构成可移植性。之后补剩余 DSP/重采样/HRTF/实时与 Worklet、统一字体后端和固定字体集、平台 API/GPU 一致性，再做当前引擎完整 SDK/账户/UI、站点业务、100 次重启与七天观察。原始 57 项、P1–P14 和 A–L 完整目标保持不变；不继承旧版本回归结论。


## v20e：统一 FFT 数值内核与跨 CPU 验证（有限验证，未交付）

候选框架 `21408a7e2bfcb9d3a857c807d2da5775ec8b84e9dc90bee576c60fef6abfff2b`，用户安装版仍为 v18b。证据 `out/evidence/privacy-v20e-fft-review.json`。Persona 增加 scalar/fdlibm FFT 后端，贯通内部规划 twiddle、实数 FFT 重组、Analyser Blackman 窗以及增益/分贝换算。规划器与缓存显式区分原生/公共后端，线程局部 provider 可嵌套、撤销并恢复，原生工厂不继承外层公共 provider。四个实际模块单元用例在 Mac/Linux 分别通过。此版本上游 RustFFT 已为 stable 默认启用，额外强制旧平台 FFT 对照，避免把同一路径误当两个对照。

同一份生产 Rust FFT 实现以固定编译器构建 Linux x86 与 Mac ARM 测试组件，仅将 CXX 传输声明替换为调用同一生产 fdlibm 头的薄 C ABI；Mac 使用实际生产 fdlibm 对象。110 组、22 种长度、1049270 个完整浮点值逐字节相同，含全部 Analyser 合法长度及若干奇数/质数。逆变换最大误差 `9.5367431640625e-7`；后端缓存隔离、嵌套原生计划及八线程冷规划检查通过。12 个“文件相同但数字语料错误”的反例均被拒绝。这证明有限内核语料的一致性，不等价于浏览器实时浮点模式或完整 DSP 链已一致。

当前 Mac 浏览器在 Linux off/balanced、原生默认、原生旧平台、Linux 关闭 Blink RustFFT 开关五组中完成 150 次真实 FFT 图渲染：32–32768 共 11 个 Analyser 长度、独立直接 DFT、4096 抽头稀疏卷积和自定义周期波；每组十个非法长度验证保留状态。原生两条路径与 D 完整观测一致；Linux 的 30 个图输出哈希发生实际变化，关闭 Blink 开关也不能退回宿主路径。Linux 两组各 21 个语义反例被拒。另有当前 E 的 96 个向量/DSP 图、两组七类身份元数据和九个非法启动检查通过。

验收中修正并保留失败证据：频谱接近 float32 抵消噪声地板时使用线性绝对误差，已解析信号仍用 dB 相对误差；独立 Python DFT 和时域参考交叉检查，合法零幅度 -Infinity 与 NaN/+Infinity 分开。组件使用生产 Mac sysroot，保留 Cargo 默认缺 core 的失败。终审修复暂存摘要对 CRLF 的归一化，构建原始字节摘要本已正确；新收据与暂存摘要一致且框架字节未变。清理六个已替代的早期生成应用备份，保留当前使用版、近期待对照/失败版本及所有原始证据。

重建并审计当前 E 的 18489 成员目录，关联 12 个音频和 12 个 FFT API 的部分运行证据，完整验证成员仍为 0。原始 44100Hz 音频指纹与不同补丁的未改造 Linux 官方诊断仍不同；应验证同一改造后的 Linux 全链路，不能据这一参照直接归因为宿主泄漏，也不能把共享 FFT 的一致性扩成完整音频保护。下一步检查并统一剩余振荡器/压缩器/自动化/重采样/HRTF/实时/Worklet/设备路径，再处理字体、平台 API、GPU 和当前完整 SDK/账户/UI/网站/100 次重启/七天观察。Linux 模板仍不开放用户选择。原始 57 项、P1–P14、A–L 全部保留为未完成；旧引擎回归不自动继承。


## v20f：振荡器实际数值路径（有限验证，未交付）

候选框架 `7f00b12db61821a631040b98a953bb75bb4f9ea6bf19af077d1ecb7ff54cd8b2`。证据 `out/evidence/privacy-v20f-oscillator-review.json`。诊断 persona 的 k-rate / a-rate 振荡器改用已有 scalar 处理，detune 使用 fdlibm powf，周期波形表的 log2 / culling pow 使用 fdlibm；原生模式保留原路径。H200 完成 Mac ARM 交叉编译和打包，33 个作者输入及 352 个应用文件/链接传输检查通过，二次暂存与编译源码摘要一致。旧 E 备份完整；用户 v18b 未替换。

当前 F 的三个隔离进程完成 324 次振荡器图渲染，覆盖三个采样率、恒定/逐采样频率/逐采样 detune、零/低/正/负频率与整/非整音分，并检查解析正弦参考、事件缓冲区身份、复制、有限性及重复一致。原生 E/F 108 组完整观测相同；Linux off 有 16 个实际输出哈希变化。每组 15 个反例同时修改原始输出与汇总后仍被语义检查拒绝。另有 F 的 60 个 FFT 图、64 个 DSP 图通过；原生两组与 E 完整观测相同。

这些有限图不覆盖全部波形/自动化/异常或完整跨 CPU 音频管线。压缩器仍有 sin/exp 系统调用，重采样存在平台分支；后续任务见 `docs/privacy-audio-followup.md`。F 尚未重建完整 IDL 目录，亦未运行完整 SDK/UI/账户/站点业务、100 次重启或七天观察。GPU/媒体/字体及原始 57 项、P1–P14、A–L 目标保持未完成；不继承旧版本回归结论。


## v20g：压缩器数学路径与实际重采样入口（有限验证，未交付）

候选框架 `524a88764f7448b02e4815acef0355e97528a4a2696f0cdb662f203b80934594`，用户安装版仍为 v18b。`stage-privacy-compressor.py` 将诊断 persona 中最后两处压缩器 sin/exp 调用切换到 fdlibm，原生模式保留原调用。H200 完成 Mac ARM 交叉编译、打包与拷回，34 个作者输入/352 个应用条目及重复暂存摘要检查通过。F 对照备份完整。

当前 G 在原生 off、Linux 诊断 off/balanced 三组共完成 450 次压缩器渲染/900 个完整声道摘要；三个采样率、五类输入、五类参数预设（含 k-rate 调度）各重复两次。检查静音、前视延迟前静音、共享立体声增益、完整复制、事件、参数对输出的实际影响；每组 15 次非法非有限值 setter 与 19 类原始/汇总同步修改的语义反例均通过。基线测试发现 ratio=1 仍有检测器启动包络，不能把它误判成从第一帧即为纯延迟；已保留原始 fixture，并将该差值标为诊断项。

原生 F/G 压缩器完整观测相同；诊断 off 的 300 个声道摘要本批也相同，不声称浮点结果改变或整个管线已跨平台一致。当前 G 另有 90 个 FFT 图/96 个 DSP 图通过，原生完整观测与 F 一致；Linux 两种隐私设置各 21/15 个相应语义反例被拒绝。balanced/off 压缩器有 240 个声道摘要不同，仍满足上述有限功能断言，不将隐私保护开关误报为同一输出。

重新生成并审计当前 G 的 18489 成员 IDL 目录，关联 24 个既有音频/FFT API 和 9 个新增压缩器/AudioParam API 的部分运行证据，完整验证仍为 0。归档 11 组原始传输/fixture 标记，五组压缩器可使用固定 probe 与归档原始数据重放验收，减少对 /tmp 生命周期的依赖。证据 `out/evidence/privacy-v20g-compressor-review.json`。

源码追踪确认 AudioBus 解码转换、AudioDestination 输出及 MediaElementAudioSource 走 media::SincResampler / MultiChannelResampler；WebRTC 同名实现与 AudioBufferSource 播放转换须分开处理。下一步在 media 层显式传递公共后端选择，由 Blink 策略驱动，统一卷积和系数 sin/cos，补非整数采样比/冲激/边界/媒体播放验收，再推进 HRTF/实时/Worklet/硬件及同补丁 Linux 全管线。当前 UI 包含 Mac 专有 CoreFoundation 调用，Linux 完整构建尚未具备，不能把官方不同补丁包当等价基线。字体/平台/GPU/profile 与完整 SDK/UI/账户/网站/100 次重启/七天观察及原始 57 项/P1–P14/A–L 均未完成。


## v20h：媒体重采样公共后端与实际播放验证（有限验证，未交付）

候选框架 `9e7ddb445b1b0a4b9516fedfb4b2ff7d9bb382bf52b1912a8647f6d83224ddbe`。`stage-privacy-resampler.py` 给 media::SincResampler 增加实例 MathBackend，经 MultiChannelResampler 由 Blink AudioBus/MediaMultiChannelResampler 传入；公共后端禁止卷积浮点收缩/重排，滤波系数 sin/cos 使用 fdlibm，SetRatio 保留同一实例策略。原生后端保持默认。H200 完成 Mac ARM 依赖构建、打包与传输，35 个作者输入/352 个应用条目通过。

当前 H 三个隔离进程共完成 720 次 PCM16 WAV 解码：8 比率、5 长度、DC/正弦/冲激、重复对照。Python 独立重建完整输入 WAV 摘要、读取 3189852 个完整 float32 值并检查输出摘要/幅度/相位/冲激面积和峰位置/同采样率 PCM 对照；校验 Promise/回调身份、ArrayBuffer 分离和三类坏格式。每组 19 个反例同时改原始记录与汇总后仍被拒；数值反例会重算完整载荷摘要和统计，不能只靠旧摘要差异拒绝。诊断 off 相对 G 的 420 个重采样声道摘要变化，60 个同采样率对照保持一致；原生 G/H 完整观测一致。

另有 48 次实际 Blob WAV 媒体播放，覆盖四来源采样率/两上下文采样率/重复，HTMLMediaElement→WebAudio→Analyser→零增益输出。显式测试用户手势、独立验算 98304 个捕获样本的频率/幅度，48 个 AudioContext 正常关闭，全程静音、不请求麦克风；每组 13 类语义反例被拒。未证明所有硬件输出重采样分支被触发，未覆盖网络/CORS/更多编码格式/输入设备。

当前 H 还完成 90 个 FFT 图、96 个向量/DSP 图、450 个压缩器图；原生三类完整观测与 G 一致。重新生成并审计最终构建的 18489 成员 IDL 目录，49 个 API 有部分运行证据，完整验证仍为 0。归档 17 组原始传输/fixture，八组解码/媒体验收可从固定 probe 和归档重放。终审发现暂存重复执行仅检查卷积函数存在的漂移缺口，已改为核对完整函数体；隔离真实源码 fixture 证明旧脚本放过 double 累加漂移、新脚本拒绝。再次依赖构建/打包核验后编译源码与框架字节均未变，目录与 API 证据绑定最终收据。

清理前逐包核对完整清单、无 SDK 和无活动进程，移除十个 v19c–v19l 早期生成测试应用，保留日常版、近期对照、源码及全部检测证据；观察本地剩余空间约 5.2GiB。证据 `out/evidence/privacy-v20h-resampler-review.json`。

为同补丁完整 WebAudio 对照，H200 已复制隔离 H 源码，269 个绑定文件一致，GN 通过，headless_shell 的 39117 项 Ninja 构建已启动，尚未完成或跑过 Linux 运行验收。隔离副本在编译时保持不变；只使用 CPU，不启用 NVIDIA。它是数值对照工具，不等于完整 Linux 产品/UI。后续先完成该构建及实际跨 CPU 音频图比较，再处理 WebRTC/BufferSource/动态 SetRatio/默认 AudioContext 与延迟暴露、Biquad detune/Panner 方位角候选、HRTF/Worklet/真实硬件。剩余 59 条宿主数学文本候选包含注释和原生回退，不能当作 59 个已证实缺口。字体/平台/GPU/profile/完整 SDK/UI/账户/网站/100 次重启/七天及原始 57 项/P1–P14/A–L 目标均保持未完成。

H 验算终审补强：对极短音频没有内部样本的情况，增加独立的连续相位 Blackman-sinc 参考，逐点检查全部边界输出；生产实现使用 33 相位表插值，两者的近似误差另设 2.5e-4 预算，原有内部正弦/DC 的 1e-4 与同采样率 PCM 的 1e-7 标准保留。当前最大完整响应误差 1.4361e-4。旧验收器会放过原始/汇总/双重复同时改写的短片段边界，新验收器拒绝；已独立复现并归档，五组新旧采集重新验收/归档重放均通过。此变更只加强测试，不改变引擎二进制。

Linux 对照准备补充：新增 `patched_linux_audio_runner.py`，只接受已完成构建及匹配二进制/源码收据，支持原生与公共后端，公共模式必须核对实际 renderer 的 /proc 可执行文件和参数；GPU 禁用，测试仅访问自身回环页。H200 原生 stub 的 exec/proc 验证、伪造参数与失效进程反例通过，这不是实际浏览器后端证明。12 个 QA 输入已固定在 `/data/metabrowser/reference/qa-v20h`，Node v24.12.0 的 WebSocket 已确认可用；Linux 实际浏览器未测试。另在 Mac 当前 H 补采 108 组振荡器图，功能与 15 类语义反例通过，为后续数值对照准备当前构建基线。证据 `out/evidence/privacy-v20h-linux-runner-supplement.json`。Linux 编译最后观察为 34266/39117，仍须等待真实构建完成再运行对照。


## H 同补丁 Linux 实际跨平台离线音频对照（有限通过）

Linux headless_shell 构建完成，摘要 `d3ba6bb5b67485febf51ad3e85fff4b9be03f7547b9819edf7d01b38a89afc13`，269 个父 Mac 构建绑定源码一致。两端公共后端的解码/向量DSP/FFT/压缩器四类各 452 组用例，918 个完整输出摘要全部一致；两侧独立功能验算通过。Linux 原生后端解码功能也通过，但其中 420 个声道摘要与公共后端不同，证明切换影响实际数值处理。

实际 Chromium 会将 /proc cmdline 改写为单条进程标题，R2/R3 首次采集因此被原严格 argv 验真拒绝，未当作通过。R4 只接受与已验证启动 argv 完全相等、且所有 token 无空白歧义的标题；保留真实可执行文件验证，并测试伪造/歧义/失效记录。跨平台验收另拒绝八类绑定/传输反例、相同但无效的空信号；对双重复、原始与统计一起更新的单 ULP 变化，仍报告摘要不一致。证据 `out/evidence/privacy-v20h-cross-platform-review.json`。

结论仅适用于本批 Window 离线用例；Linux 为无界面、GPU禁用/软件选择、sandbox关闭的受控本地测试配置，不是完整 Linux 产品/默认配置/硬件对照。尚未证明全部 WebAudio API、输入、realm、实时/Worklet/HRTF/设备及整个音频保护，亦未验证字体/GPU/profile/完整SDK/UI/账户/网站/100次重启/七天和原始完整目标。当前所有 reference 构建/浏览器采集已终止，不再等待已完成的 Ninja；下一步应推进余下真实缺口。


## H 原始两类音频指纹配置对照（有限通过）

源码复查纠正配置归属：identity_surface_collector.js 为 44100 帧/默认压缩器，原始 fingerprint_probe.html 的 P8 为 5000 帧/threshold=-50/knee=40/ratio=12/attack=0/release=.25；两者均为 44100Hz、triangle、10000Hz。新用例同时保留两套配置，各重复三次，核对完整浮点缓冲区及两次 getChannelData / 两次 copyFromChannel，Promise/事件身份和输出信号频率。

Mac ARM 与同补丁 Linux x86 公共后端六个完整输出摘要全部一致；Linux 原生后端六个摘要均不同，同时通过功能检查。P8 公共后端末 500 点绝对和值为 124.04345203586126，原生 Linux 为 124.04347776696522；这些是观测结果，验收代码没有填死该数值。独立反例检查拒绝十类错误，含所有载荷/四路摘要/统计同时更新的常量伪信号。此前四类离线用例的 918 摘要结果保持原有限范围，不据此合并成全音频通过。证据 `out/evidence/privacy-v20h-original-signature-review.json`；跨平台验收器旧版本按摘要冻结以保留历史证据。

默认 AudioContext 源码进一步定位：未指定采样率时继续走目的设备选择，baseLatency 从目的缓冲帧数计算，outputLatency 从硬件延迟量化；这说明仍需检查该硬件路径，尚不证明独特设备信息实际泄漏或保护已经完成。后续应先实际采集默认/显式采样率和不同 latencyHint 的行为，并结合剩余 Biquad/Panner/DSP、实时/Worklet/HRTF/设备、字体/GPU/profile 和完整产品要求继续推进。全部原始 57 项/P1–P14/A–L 及最终整体验收保持未完成。
