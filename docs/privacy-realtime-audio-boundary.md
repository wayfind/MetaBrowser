# 实时音频设备边界：实测、实现位置与验收条件

状态：缺口已实测；下述原生隔离方案尚未实现，不构成全量隐私通过。

## 当前实测

同一 H 候选，Mac ARM 三个独立进程：scalar、native、scalar +
`--audio-buffer-size=512`。每进程测试默认/44100/48000 Hz、五种 latencyHint、
两次重复，共 90 个 AudioContext、270 次运行采样，全部正常关闭。
采集仅用本地产生的音频，最终 gain=0；未申请麦克风权限。

scalar 与 native 的 30 组采样率及 baseLatency 一致。改变底层缓冲区后，
12 组 baseLatency 改变。默认 48000 Hz、interactive 的 baseLatency 从
256/48000 变为 512/48000；末次 outputLatency 从 0.024 变为 0.032 秒。
这证明底层缓冲配置仍可观测；不证明能唯一识别设备，也不证明所有设备如此。
动态时间戳不能逐值相等比较，不把采样调度波动当作确定性的身份差异。

复现分析：

```sh
python3 tests/integration/audio_context_comparison.py
python3 tests/integration/audio_context_contract_test.py out/evidence/audio-context-v20h-scalar-off.private.json
```

原始报告及输入/进程输出归档在 `out/evidence/privacy-v20h-context-archives/`。
分析会重新校验这些绑定，不仅检查报告中的 completed 字段。
13 种错误轨迹拒绝测试覆盖缺项、重复、参数偏离、关闭/暂停状态、非有限值、
负延迟、逆行时钟、未来 contextTime、未静音及无渲染输出。
短采样窗可能小于 numeric latencyHint 的回调周期，不能要求每两次采样 currentTime 必须增加。

## 已确认源码边界

固定 Chromium 154.0.8037.97 的
`content/renderer/media/renderer_webaudiodevice_impl.cc`：

- 构造函数从 AudioDeviceFactory 取得 original_sink_params_，默认采样率取物理设备参数。
- GetOutputBufferSize 使用物理设备的采样率、默认缓冲及 hardware_capabilities，按 hint 选择大小。
- SampleRate/FramesPerBuffer 读取 current_sink_params_；MaxChannelCount 直接读取 original_sink_params_。
- current_sink_params_ 同时传给真实 sink Initialize，不能只改变这些字段而假设物理驱动全部接受。
- Render 将真实 delay、delay_timestamp、glitch_info 直接传给 WebAudio 回调。
- silent sink 和无硬件 AUDIO_FAKE 回退不是正常有声输出的隐私实现。

Blink AudioContext 同时以目的端 buffer/rate 计算 baseLatency，以硬件输出延迟计算
outputLatency，并从 output_position_ 生成 getOutputTimestamp。
因此只固定 sampleRate、只改 getter 或只设置启动缓冲参数都不是完整修复。
源码快照：`out/evidence/privacy-v20h-device-implementation-source-v3.txt`。

## 待实现：公共图与私有物理输出分离

1. 由 profile 的统一音频描述符给出默认图采样率、声道能力、render quantum、
   各 latencyHint 的缓冲策略；显式 sampleRate 保留 Web Audio 语义。
2. 在设备适配层保留独立的物理设备参数，真实输出经格式/采样率转换与有界 FIFO 交付。
   已核查 AudioDeviceFactory：IsMixable 仅允许 MediaElement，WebAudio 的
   NewAudioRendererSink 直接创建 AudioOutputDevice，不经过 renderer mixer。
   因此不能假设现有 renderer mixer 会自动完成这项隔离；下一步核查浏览器端
   AudioOutputDevice 的实际转换边界，再决定独立适配器的位置。
   不覆盖 original_sink_params_ 后盲目交给驱动。
3. 公共 currentTime、输出位置、base/outputLatency 从同一时间线与实际公共缓冲导出；
   私有驱动 delay/timestamp 不直接成为网页可观测数据。暂停、恢复、设备切换、
   排空和 underrun 都必须维护同一个状态机。不得简单减常数导致负数或未来时间戳。
4. 默认设备、显式 sinkId、静音 sink、无设备、权限状态使用同一规则。
   只有用户授权的设备选择影响路由；不得绕开麦克风/设备权限。
5. 原生 passthrough 路径保持对照；profile 切换在清晰的上下文生命周期边界生效，
   不在活跃图中途更换采样率或身份。

## 原生实现后的门禁

- 实测默认与显式采样率、五档 hint、至少两种物理缓冲、至少两种设备/系统采样率。
- 同一 profile 的公共静态参数一致，显式率正确；时间单调、时间域一致，暂停/恢复正确。
- 实际有声音频路径单独测试频率、幅度、时长、声道、爆音和 underrun，不能用静音替代通过。
- AudioWorklet、MediaStream/MediaElement、设备切换与 WebRTC 独立覆盖；离线 918 个摘要相同不替代这些测试。
- Mac ARM 与 Linux x86 同补丁对照；Linux headless/software 测试不替代真实硬件。
- 完整 SDK/UI/账户/网站业务及原始 57 项/P1–P14/A–L 验收仍独立开放。

工厂源码快照：`out/evidence/privacy-v20h-audio-factory-source.txt`。

## v20i 实现增量（运行验收前）

`stage-privacy-audio-device.py` 已修改真实 RendererWebAudioDeviceImpl：
仅显式 scalar 诊断 cohort 采用默认 48000 Hz、双声道上限及独立于物理设备的
latencyHint 缓冲策略，显式 sampleRate 仍沿用上游功能开关/重采样语义。
缓冲按 128 帧上取整，范围遵循上游 128–8192 帧；numeric hint 的负值回退下限，
极大值在转整数前限幅。未改写物理 original_sink_params_，也未用静音 sink 替代播放。

后续源码核查补足了转换依据：AudioManagerBase 为低延迟请求取得物理设备偏好输出参数，
用 AudioOutputResampler 分别接收请求参数与实际输出参数；其中 OnMoreDataConverter
使用 AudioConverter 做采样率、缓冲和声道转换。此事实支持请求图参数与物理参数分离，
不意味着物理回调节奏已经隔离。

当前修改尚不处理 Render 的 delay/delay_timestamp/glitch_info，因此 outputLatency、
getOutputTimestamp 与调度时序仍须继续实现和验收；不得把静态参数通过写成全音频隐私通过。
60 个 hint/rate 数值边界用例已运行实际 helper 的 C++ 编译结果并通过 UBSan；
这是策略单元验证，不是浏览器实测或有声输出验收。

### v20i 本机实际运行结果

Mac ARM 候选已交叉编译、打包、拷回，352 项文件/符号链接校验通过；
framework SHA256 为 `95382c201f83e4b663e5699dc1ce3aa91a01d2eaafd19c3535e8767869df4d62`。
三种模式 90 个上下文/270 次采样正常关闭；scalar 默认缓冲与强制 512 帧的
30 组 rate/baseLatency 全部相同，并符合公共缓冲策略；native 的 30 组静态参数
与 H 版本相同。每组 13 类错误轨迹均被拒绝。
另有 16 个 MediaElement→WebAudio 静音输出图通过完整 32768 个采样值的独立频率/幅度检查；
六个原始指纹图的完整输出摘要与 H 相同，10 类签名错误被拒绝。
这未验证有声音频输出、声道能力、设备切换或硬件时钟隔离，也未在新 Linux 版本运行。

H 完整应用已保留并通过原 352 项清单；本轮候选没有 SDK，未替换日常应用。
所有原始范围仍在 requirements ledger，未把任一完整表面升级为已完成。

## v20j：公共调度与私有物理输出适配层

状态：已在原生引擎实现并完成以下有限验收，不等于全部实时音频或计时隐私通过。
候选 framework `d0460ff08042ab96d264c8a70946fbe8b8e0932a71ba364345aea5c0355d89b0`，
仍无 SDK、未安装到日常应用。I 完整备份按原 352 项清单验证通过。

`MetaBrowserAudioClockSink` 仅用于显式 scalar cohort 的有声 sink。公共任务调度器
按请求图参数驱动 Render；所得采样进入有界 AudioFifo，由真实物理 sink 消费。
NullAudioSink 在此仅作为调度器，采样没有被直接丢弃或拿静音 sink 替代真实输出。
物理 delay/timestamp/glitch_info 不传入公共图；物理格式转换继续由浏览器输出层处理。
私有缓冲初次启动填充两块，耗尽时补零并重新预填；超容量时丢弃最旧的输出，
避免无限内存或无限增加输出延迟。暂停/停止先终止公共生产，再操作物理输出；
等待回调时不持有 FIFO 锁。该策略还需实际硬件的音质、延迟和漂移验收。

实际验收：

- Mac 三模式 90 个上下文、270 次采样通过原功能检查；诊断两模式 60 组
  输出延迟符合公共双缓冲与上游无麦克风授权时 8ms 量化策略。动态时间戳只检查
  时间域/单调等不变量，不比较两次运行的绝对时间。原生静态参数 30 组与 I 相同。
- 8 个真实/显式静音 sink 用例验证 maxChannelCount=2、单/双声道设置及超限拒绝，
  negative/zero/huge hint、暂停冻结/恢复；NaN 与正负 Infinity 在 Web IDL 层拒绝。
- 约 34 秒的浏览器静音测试：33.6267 秒图进度，36 次观察，Tracing 捕获真实
  SilentSinkSuspender 进入/离开静音模式两个事件；恢复非零图信号和暂停/恢复通过。
  启动器强制 `--mute-audio`，不是有声硬件输出验收。六种错误长时轨迹被拒绝。
- 16 个媒体播放图完整采样独立频率/幅度检查通过；六个原始指纹图完整摘要与 I 相同。
- 原生 Linux 独立测试使用 Chromium 实际媒体库和与 Mac 完全相同的 adapter body，
  验证数据进入物理消费者、私有输入时间戳不驱动公共渲染、队列溢出/耗尽及暂停/恢复/停止。
  它是受控物理 sink 测试，不是 Linux 浏览器或真实声卡验收。

测试构建的两次失败已保留：最初 test_support 拉入缺失的字体测试资源，后改为该音频
测试实际所需的 base/media/gtest；第二次因将生产 .cc 中的类当 header 编译而触发
Chromium 的 header 内联风格检查，后按生产方式将相同 body 展开进 .cc，未关闭编译检查。

仍开放：调度/CPU/系统时钟侧信道、有声硬件质量/漂移/回声与视频同步、设备切换/断连、
麦克风权限改变、renderSizeHint、Worklet/HRTF/WebRTC 与其余 DSP、完整 Linux 浏览器，
以及原始 57 项/P1–P14/A–L 的 GPU/字体/profile/SDK/UI/账户/网站业务/稳定性验收。
