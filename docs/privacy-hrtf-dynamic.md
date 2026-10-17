# 动态 HRTF 与当前跨 CPU 验收

Mac 引擎仍为 L2，framework SHA 为
`f46dc3e5ff57df7498af5f12beb3aaa987fc6c375876b6138b12dd3a480fdd00`。
没有修改日常应用，也没有将诊断后端标为生产 profile 已可用。

新增两种模式各 48 个动态图：三档采样率，静止、声源方位移动、仰角移动、监听者移动，
两档输入幅值与两次重复。合计 96 图、1572864 个完整采样值。
独立检查全部采样的半幅缩放关系、参数生效前的因果前缀、运动后的实际变化、重复输出、
两条读取路径及真实后端轨迹。两种模式最大缩放误差均为零；最小运动效果约 0.0197。
每模式八类错误被拒绝，包括完整 payload/摘要同时更新的冻结运动、非线性增益、提前生效
和常量假信号。此检查不能替代全部姿态、独立 HRIR 数值 oracle 或真实声音质量验收。

Linux 对照使用独立目录 `/data/metabrowser/source/linux-reference-v20l2`：
以普通 rsync 复制，未使用硬链接或原位写入；原 H 源码及其已验证二进制保留。
272 个 Mac 绑定的非输出源码逐项相同，额外绑定 256 个音频输入文件（含 240 个 WAV
及真正打包的 Composite.flac）。构建只使用 CPU，未启动 NVIDIA GPU 工作负载。
构建/执行最终状态以当前 `reference-evidence/status.json` 和实际进程检查为准。

GRIT 原生解析器已从 Mac 实际应用的 resources.pak 提取 HRTF FLAC，内容 SHA256：
`40bda2ad9170fa2bcdc2d5f20cdd98c70609ad33a94df49fe7d6007cacab2ada`，136404 字节。
该 pack 的摘要与 L2 完整应用清单一致。Linux 实际 headless_lib_data.pak 也已按生成的
资源头提取对应 payload，136404 字节逐字节相同；没有假定资源 ID 必然一致。

跨 CPU 检查会要求：完成构建的二进制、相同父 Mac receipt 与源码集合、真实 renderer
参数传输、相同 trial 源码、原始进程输出与输入摘要、独立功能校验，以及 HRTF 三个
实际 C++ 阶段均选择 portable 后端。完整声道摘要必须比较，不以“近似值看起来一样”
代替位级对照。实际 Linux L2 构建已完成（35245 个动作），二进制 SHA 为
`7fee77cf47719ae96b3e18c6b2d51afdcfa5edd6cf3df994ff4d349c4f002638`。
静态 72/72、动态 96/96 完整声道摘要一致，功能检查及原始进程/源码/父 receipt 绑定通过。
参见 `out/evidence/privacy-v20l2-cross-hrtf.json` 和 `privacy-v20l2-cross-dynamic-hrtf.json`。

同版本真实 AudioWorklet 对照发现未通过项：48 个声道仅 36 个相同，12 个失配均为
biquad-detune，不能计作整个音频管线通过。源码存在固定系数 Mac Accelerate 与 Linux
C++ 路径及中间历史精度分叉。新增统一双精度递归仅对 scalar persona 生效，原生路径
保持原样；直接编译生产片段的 Mac/Linux 96 组分块/原地读写测试通过，393216 字节
输出相同。该候选仍须在实际浏览器中重新验收，独立核测试不能代替引擎验证。

原始 57 项/P1–P14/A–L、生产 profile 激活与隔离、GPU/字体/平台、完整 SDK/UI/账户/
网站业务、100 次启动和 7 天稳定性范围保持不变。
