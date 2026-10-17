# Biquad 跨平台一致性：v20m

此次解决真实检测发现的差异，没有将有限测试标为全量完成。

L2 对照中，AudioWorklet 48 个完整声道仅 36 个相同；12 个失配均为
biquad-detune。Mac 固定系数走 Accelerate，Linux 走 C++，递归历史精度不同。
v20m 在不可变 scalar persona 下使用统一双精度递归，禁止乘加融合及重关联；
固定与逐样本系数共享历史，输出时才转 float。保留原生平台路径。
状态保存未调用只接受 float 的原生 flush helper，避免每个 quantum 隐式降精度。

实际 Mac framework 为
`d18a79b5dcc1b68054e153e6d00fba5978d1b0dea385c492ac5ee29029e17b0d`，
Linux 二进制为
`d5e59babac65b2a7ba097be10351aadf022213ae21c4b7f69f0b42693b3fda04`。
新同源浏览器对照 48/48 个完整声道逐字节相同；独立 allpass 数值检查最大误差为零。
Mac 原生 48 个完整声道与 K2 控制相同，scalar 输出也与 L2 相同。
两模式各十类错误被拒绝，包括更新摘要后的假信号与空间偏置。

直接编译实际生产片段，在两平台分别验证 96 个分块、原地读写及系数模式切换情况，
对照独立 extended precision 递归，393216 字节输出完全一致，UBSan 无报告。
将历史保存故意改成 float 后，分块不变性检查失败，说明检查能识别本次缺陷。
这些核测试不代替 WebAudio API、所有滤波器或所有异常值的验收。

证据：`out/evidence/privacy-v20m-biquad-review.json`、
`out/evidence/privacy-v20m-cross-worklet.json`。L2 静态/动态 HRTF 的跨 CPU
72/72 与 96/96 成功记录保留；不能据此声称 v20m 全音频管线已通过。
H、L2 Linux 源码和二进制独立保留；Mac L2 完整应用备份已校验 352 项。
v20m 为 SDK-free 诊断候选，尚未替换日常应用。

接下来的覆盖顺序保持原始 57 项、P1–P14、A–L 范围：

1. 八种 Biquad 的固定/动态系数、边界参数和退化条件；接着核对 IIR、实时
   Worklet、媒体/WebRTC、真实设备切换、时钟漂移与音画同步。
2. 将已验证后端接入用户 profile 的正式激活链路，验证重启、切换、缓存与
   Window/Worker/iframe 隔离。诊断命令行可用不等于正式配置已接通。
3. GPU/WebGPU/WebGL 的参数与真实计算结果、字体/排版/Canvas、平台/时区/语言/
   屏幕/媒体能力联合一致性，按清单补齐权限、设备与网络泄露测试。
4. 新引擎完整 SDK、账户、对话与跨站业务回归，100 次冷启动及七天稳定性观察。

各项只有完成对应真实环境断言才能提升状态。源码修改、核级测试、浏览器实测和
网站验收分别记录，不能互相替代，也不承诺任意网站必然接受某个 profile。

后续八类型、固定/定时切换与四类退化边界实测已补充，见 `privacy-biquad-matrix.md`。
最初的全通测试保留为历史证据；新矩阵仍不涵盖任意参数、连续 ramp 或全部 realm。
