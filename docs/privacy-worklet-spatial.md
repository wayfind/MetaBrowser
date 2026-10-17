# Worklet、滤波与空间音频的当前验收

状态：有限用例通过，完整音频与指纹隐私覆盖未完成。
当前候选 v20k2：`af73c22b66f67643c8d64f591cf9dff3c92e0d1d49d65c41aee78bd412bb2d61`。
它是未集成 SDK 的诊断应用，未替换日常浏览器。

原生修改仅针对显式 scalar cohort 的两处宿主数学调用：Biquad detune 换算的
exp2 改走 fdlibm pow(2,x)，Panner 方位角的 acos 改走 fdlibm。
这不代表 Biquad 的所有浮点处理、HRTF 或空间几何已经跨 CPU 一致。

第一版 v20k 被原生对照拒绝：Panner 包装函数将原来的 float 表达式提升为 double，
改变了 acos/Rad2deg 的重载精度，导致 12 个原生声道摘要变化。修正版本保留完整原生
表达式，仅在诊断分支使用 fdlibm。v20k2 的 24 个原生图、48 个完整声道输出摘要
已全部与 J 基线相同。旧应用、失败记录、源输入及原始测量均已保留，不能把它当作已通过版本。

当前实际浏览器测试：

- 两种模式各 24 个 OfflineAudioContext/AudioWorklet 图，三档采样率，identity、
  a-rate gain、allpass+detune、equalpower 空间声像，重复两次。
  当前共 48 图、768 个处理块、196608 个完整 float32 输出值。
- 由 Python 独立重建输入、增益、allpass 递推及声像系数，不信任页面给出的误差统计。
  identity/gain 必须逐值准确；滤波/声像最大误差预算 1e-7。
  同时验证 Worklet 全局 sampleRate/currentFrame/currentTime、AudioParam 数据、
  两条缓冲读取路径、重复输出和完成事件身份。每模式 10 类错误数据被拒绝，
  包括 payload/两个摘要同时更新的假信号和细小声像偏移。
- 六个真实 AudioContext 验证默认/44100/96000 Hz、恒定/a-rate 参数，
  共检查 12288 个完整捕获采样。异步采集相位通过独立构造的 257 帧周期匹配；
  当前误差为零。记录的 384 个 Worklet 块验证了作用域时钟与 Window 时间上界，
  暂停时冻结、恢复后推进；八类错误被拒绝，包括内部自洽但超前于 Window 的时钟。
  最终输出 gain=0，没有麦克风请求或有声硬件输出验收。

构建依赖及完整应用传输均核验；39 个作者输入已冻结。stager 的全新应用与已拒绝
初版迁移结果逐字节相同，并拒绝被改写的 helper。日常应用和近期 J/I/H 回退版本保留。
另核验并回收四个更旧的 SDK-free 测试应用备份，实测释放约 2.60 GiB；原始证据不删除。

仍待完成：更多滤波器/动态 detune/参数极值、HRTF 数据库与卷积、实时 Worklet 故障及
设备切换、Worklet realm 的其他可观测面、WebRTC、有声质量/漂移/视频同步、同补丁
Linux 完整浏览器对照，以及原始 57 项/P1–P14/A–L 的其余 GPU/字体/profile/SDK/UI/
账户/网站业务/100 次冷启动/7 天稳定性验收。没有将任何完整表面标为已完成。
