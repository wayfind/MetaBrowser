# 音频隐私剩余工作与验收边界

当前振荡器补丁在诊断用 scalar persona 中统一 k-rate / a-rate 的实际计算，
并将 detune 与波形表选择中的数学调用路由至 fdlibm。原生 persona 保留原来的路径。
该变更需要以当前候选实际浏览器测试报告验收；源码已修改不代表测试通过。

后续工作按实际数值链路推进：

1. 压缩器：v20g 已将 `dynamics_compressor.cc` 的增益 sin 与 knee exp 在诊断 persona 下路由至 fdlibm。
   当前 450 图覆盖三档采样率、五种参数预设（含 k-rate 调度）、五种信号和重复对照；
   前视延迟前静音、共享立体声增益、无效非有限值 setter 与参数实际影响输出均有断言。
   ratio=1 时仍有检测器启动包络，不能错误地断言全程等于纯延迟。
   这批诊断模式 float32 输出与上一版相同，不证明整个压缩器跨 CPU 一致。
2. 重采样：v20h 在 `media/base/SincResampler` 增加实例级 MathBackend，
   经 MultiChannelResampler 由 Blink 的 AudioBus 与 MediaMultiChannelResampler 传入。
   公共后端使用显式禁止收缩/重排的标量卷积，InitializeKernel/SetRatio 的 sin/cos 使用 fdlibm。
   720 次 PCM16 WAV 解码（三进程），8 比率×5 长度×3 信号×2 重复，独立检查完整浮点缓冲区；
   同采样率对照、回调/Promise 身份、输入分离和三类坏格式有断言。另有 48 次实际静音图媒体播放，
   检查捕获信号的频率/幅度与 48 个上下文关闭。未证明实际硬件输出重采样分支均已触发。
   WebRTC 同名实现、BufferSource 播放插值、SetRatio 动态切换、更多编码器/网络/CORS/设备仍须独立验收。
3. 空间音频/HRTF、AudioWorklet、实时设备：独立检查系数生成、线程与设备采样率，
   补齐真实硬件及权限状态测试，不能从 OfflineAudioContext 的结果推断通过。
4. 同一补丁版本的完整 Linux / macOS 音频图跨 CPU 对照：H200 隔离 H 源码的 headless_shell 已完成构建。四类 Window 离线用例的 918 个完整输出摘要在 Mac ARM / Linux x86 上全部相同；Linux 原生后端 420 个解码声道摘要不同，仍通过功能检查。
   现有 FFT 核心字节一致性只证明该组件；官方未修改 Linux 浏览器不是等价基线。

整个项目仍需完成 GPU、字体、显示、媒体、网络/存储、profile 一致性，以及
完整 SDK/UI/账户/网站业务和稳定性验收。此文件不缩小原始覆盖清单，不将未验收项标为完成。

补充源码盘点见 `out/evidence/privacy-v20h-remaining-audio-math-audit.json`。
59 条是含注释和原生回退的文本候选，不是 59 个已确认缺口。
后续重点核查 Biquad detune 的 exp2、Panner 方位角 acos、更多 DSP 的 SIMD/浮点环境，
以及 Worklet/HRTF/真实输入输出设备。Linux 无界面对照不代表完整 Linux 产品/UI 已移植。

上述通过只对应有限离线用例；完整原始指纹配置、全部 DSP/异常值/实时/Worklet/HRTF/设备及当前完整产品仍需验收。详情见 `out/evidence/privacy-v20h-cross-platform-review.json`。
