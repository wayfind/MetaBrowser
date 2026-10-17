# 隐私出口覆盖与验收边界

覆盖按实际出口、身份和权限生命周期统计。一个探针通过，只证明其断言；
合成设备不替代真实设备/TCC，公开网页不替代登录态业务，软件渲染不替代任意硬件模拟。
当前实现细节见 [引擎记录](FINGERPRINT_PRIVACY.md)。完整实施和检测顺序见 [全量计划](ANONYMITY_PLAN.md)，逐项状态见 [要求账本](privacy-requirements.json)。最新版本以安装收据为准。

| 类别 | 已接入的保护或约束 | 验收与仍需补齐的部分 |
|---|---|---|
| 身份与上下文 | profile/site/origin 派生材料，Worker/Worklet 传播；分离账户、Cookie、对话目录 | 五模式、七 realm、重启及原生身份窗口；不能推导所有第三方存储授权组合均通过 |
| CPU | 原生并发桶，Window 与 Worker 一致 | 七 realm；任意计算/计时仍可能推断硬件 |
| GPU 标识 | adapter/device 一致隐藏细节，保留真实 vendor/fallback 状态 | 真计算、渲染和校验；不伪造任意 NVIDIA/AMD 型号 |
| GPU 可选能力 | 受保护上下文不提供时间戳、subgroup 和对应实验能力；申请与枚举共用功能集合 | 主线程、Worker、owner 销毁，以及开启/关闭/开发者/例外/全局偏好对照 |
| GPU 限额 | 保留原生能力与限制校验，不伪造可用资源 | 七类越界申请被拒绝，合法申请成功；实际限额仍可形成粗粒度指纹 |
| 软件后端 | ANGLE/Dawn SwiftShader；软件身份禁用视频硬件编解码 | WebGL/WebGPU 与实际媒体；不代表操作系统合成器整体虚拟化 |
| Canvas/媒体出口 | 完整私有快照先保护后裁剪；Bitmap/VideoFrame/PNG/Worker/WebGPU/capture 路径 | U8/F16、污染、裁剪、克隆、录制、RTP；4 Mi-pixel 预算、alpha 形状与统计重建仍有边界 |
| 音频/语音 | 离线/Analyser 出口保护，Worklet 上下文传播，语音别名 | 实时业务信号保持原样；实际设备延迟、采样能力及所有 DSP 路径未被统一虚拟化 |
| 本地设备名称 | 枚举、JSON、本地输入轨道及扬声器选择结果使用公开 ID 派生的通用别名 | 枚举/输入/克隆/停止/owner 销毁受控验收；真实扬声器选择交互仍需验收 |
| 电池/网络信息 | v17c 冻结通用电池与链路质量，不订阅系统电池变化，过滤物理网络变化事件；保留 saveData/真实在线状态 | 原生 Window/Worker/保留对象与关闭对照；实际电池迁移、全部网络入口仍需单独验证 |
| 设备选择与能力 | 保留已有站点 ID、group ID、权限和真实约束，不凭空制造设备 | 精确 ID 路由与动态约束；授权后数量/能力仍真实，真实摄像头/麦克风 TCC 尚需实测 |
| 显示 | 默认虚拟区域；明确授权后提供原生详细信息，撤销恢复保护 | 原生窗口/CSS/iframe、授权/撤销/再授权；受控标签页共享不等于任意桌面/窗口采集验收 |
| 字体 | 限制隐式本机字体发现；保留下载字体与实际字形渲染 | 用户字体 canary、CSS/SVG/WebGL 相关出口；不是跨系统统一字体/排版引擎 |
| WebRTC | 原生 ICE 策略，包括严格禁止 UDP 直连模式 | 受控 STUN 与无外部服务器的真实 RTP；网页仍可看到正常网络连接的公网地址 |
| 编解码/DRM | 实际 AVC/AAC/VP8/Opus 与临时 ClearKey MSE；拒绝不支持的持久标识能力 | 真实解码/呈帧/CDM 读回限制；不含 Widevine/FairPlay 商业授权服务 |
| OS/UA/网络 | v18b 全局身份设置控制系统版本主版本/完整版本；HTTP 与原生网页/Worker 统一来源，平台仍是 macOS/ARM64 | 140 项双后端身份检查与七 realm UI 通过；跨平台/GPU、TLS/IP 及全部高熵表面仍未完成 |
| 其他授权设备 API | 沿用浏览器权限边界 | USB/HID/蓝牙/串口/定位/WebAuthn 等没有完整的独立虚拟化及真实授权验收 |
| 网站业务 | 隔离身份的只读公开搜索/详情/播放采集 | 登录态、风控结果及财务→ERP→CRM→BI 需要具体站点、测试身份和预期结果 |

GPU/设备新增验收入口：

```sh
python3 tests/integration/gpu_media_runner.py \
  --app out/mac-privacy-candidate/MetaBrowser.app \
  --extended-media --policy-controls \
  --output out/evidence/hardware-privacy-current.private.json
```

该命令只给自有 loopback 测试身份授予浏览器层的摄像头/麦克风权限，
设备输入来自假设备，不修改真实用户 profile 或系统 TCC。关闭和例外对照应恢复
原生能力与名称，不能将缺失权限、空集合或所有 API 一律失败当作保护通过。

当前交付 v18b 的完整证据与范围见 `out/evidence/identity-v18b-review-result.json`。生成清单 18,489 个成员全部未完成逐项隐私审查；清单完整性通过不等于保护覆盖。异常配置保护行为与条件启用接口见 `privacy-open-findings-v18b.json`。
