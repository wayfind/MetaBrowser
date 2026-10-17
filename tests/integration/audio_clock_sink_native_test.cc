// Exercise the exact production adapter against a controlled physical sink.
#include <memory>
#include <utility>
#include <vector>
#include "base/check_op.h"
#include "base/memory/raw_ptr.h"
#include "base/memory/ref_counted.h"
#include "base/sequence_checker.h"
#include "base/synchronization/lock.h"
#include "base/task/sequenced_task_runner.h"
#include "base/at_exit.h"
#include "base/command_line.h"
#include "base/functional/bind.h"
#include "base/location.h"
#include "base/run_loop.h"
#include "base/task/single_thread_task_executor.h"
#include "base/task/single_thread_task_runner.h"
#include "base/time/time.h"
#include "media/audio/null_audio_sink.h"
#include "media/base/audio_bus.h"
#include "media/base/audio_fifo.h"
#include "media/base/audio_glitch_info.h"
#include "media/base/audio_parameters.h"
#include "media/base/audio_renderer_sink.h"
#include "media/base/output_device_info.h"
#include "testing/gtest/include/gtest/gtest.h"

namespace {
#include "adapter.inc"
void RunFor(base::TimeDelta duration) {
  base::RunLoop loop;
  base::SingleThreadTaskRunner::GetCurrentDefault()->PostDelayedTask(
      FROM_HERE, loop.QuitClosure(), duration);
  loop.Run();
}

class TestPhysicalSink final : public media::AudioRendererSink {
 public:
  void Initialize(const media::AudioParameters&, RenderCallback* cb) override { callback=cb; }
  void Start() override { started=true; }
  void Play() override { playing=true; }
  void Pause() override { playing=false; }
  void Stop() override { started=playing=false; callback=nullptr; }
  void Flush() override {}
  bool SetVolume(double v) override { volume=v;return true; }
  media::OutputDeviceInfo GetOutputDeviceInfo() override { return media::OutputDeviceInfo(media::OUTPUT_DEVICE_STATUS_OK); }
  void GetOutputDeviceInfoAsync(OutputDeviceInfoCB cb) override { std::move(cb).Run(GetOutputDeviceInfo()); }
  bool IsOptimizedForHardwareParameters() override { return true; }
  bool CurrentThreadIsRenderingThread() override { return true; }
  void Pull(media::AudioBus* bus) {
    ASSERT_TRUE(started && playing && callback);
    // Adversarial physical timing: never permitted to drive the graph clock.
    EXPECT_EQ(callback->Render(base::Seconds(100),base::TimeTicks()+base::Seconds(999),{},bus),bus->frames());
  }
  bool started=false,playing=false; double volume=1;
  raw_ptr<RenderCallback> callback=nullptr;
 private:
  ~TestPhysicalSink() override = default;
};

class Signal final : public media::AudioRendererSink::RenderCallback {
 public:
  int Render(base::TimeDelta delay,base::TimeTicks timestamp,
             const media::AudioGlitchInfo&,media::AudioBus* bus) override {
    delays.push_back(delay);timestamps.push_back(timestamp);
    for(int ch=0;ch<bus->channels();++ch)
      for(int i=0;i<bus->frames();++i)
        bus->channel(ch)[i]=static_cast<float>(frames+i+1)/4096;
    frames+=bus->frames();return bus->frames();
  }
  void OnRenderError() override { ++errors; }
  int frames=0,errors=0;
  std::vector<base::TimeDelta> delays;
  std::vector<base::TimeTicks> timestamps;
};

TEST(AudioClockSink, CarriesSignalAndRejectsPhysicalClockFeedback) {
  base::SingleThreadTaskExecutor executor;
  auto physical=base::MakeRefCounted<TestPhysicalSink>();
  auto sink=base::MakeRefCounted<MetaBrowserAudioClockSink>(physical,base::SingleThreadTaskRunner::GetCurrentDefault());
  media::AudioParameters params(media::AudioParameters::AUDIO_PCM_LOW_LATENCY,
    media::ChannelLayoutConfig::Stereo(),48000,256);
  Signal signal;sink->Initialize(params,&signal);sink->Start();sink->Play();
  for(int tries=0;signal.frames<768 && tries<200;++tries) RunFor(base::Milliseconds(2));
  ASSERT_GE(signal.frames,768);
  auto output=media::AudioBus::Create(2,256);physical->Pull(output.get());
  for(int ch=0;ch<2;++ch) for(int i=0;i<256;++i)
    EXPECT_FLOAT_EQ(output->channel(ch)[i],static_cast<float>(i+1)/4096);
  const auto count=signal.delays.size();
  for(int n=0;n<20;++n) physical->Pull(output.get());
  EXPECT_EQ(signal.delays.size(),count); // Physical callbacks do not render.
  EXPECT_TRUE(output->AreFramesZero()); // Bounded underflow, no stale repeat.
  for(auto delay:signal.delays) EXPECT_NEAR(delay.InSecondsF(),512.0/48000,1e-6);
  for(size_t n=1;n<signal.timestamps.size();++n)
    EXPECT_GE((signal.timestamps[n]-signal.timestamps[n-1]).InSecondsF(),256.0/48000-1e-6);
  EXPECT_TRUE(sink->SetVolume(.5));EXPECT_DOUBLE_EQ(physical->volume,.5);
  sink->Pause();const int paused=signal.frames;
  RunFor(base::Milliseconds(30));EXPECT_EQ(signal.frames,paused);
  sink->Flush();sink->Play();
  for(int tries=0;signal.frames<paused+768 && tries<200;++tries) RunFor(base::Milliseconds(2));
  ASSERT_GE(signal.frames,paused+768);
  physical->Pull(output.get());EXPECT_FALSE(output->AreFramesZero());
  sink->Stop();const int stopped=signal.frames;
  RunFor(base::Milliseconds(30));EXPECT_EQ(signal.frames,stopped);
  EXPECT_EQ(signal.errors,0);EXPECT_FALSE(physical->started);
}

TEST(AudioClockSink, OutputQueueIsBoundedAndKeepsRecentSignal) {
  base::SingleThreadTaskExecutor executor;
  auto physical=base::MakeRefCounted<TestPhysicalSink>();
  auto sink=base::MakeRefCounted<MetaBrowserAudioClockSink>(physical,base::SingleThreadTaskRunner::GetCurrentDefault());
  media::AudioParameters params(media::AudioParameters::AUDIO_PCM_LOW_LATENCY,
    media::ChannelLayoutConfig::Stereo(),48000,256);
  Signal signal;sink->Initialize(params,&signal);sink->Start();sink->Play();
  RunFor(base::Seconds(2)); // No physical consumption; exceed capacity.
  auto output=media::AudioBus::Create(2,256);physical->Pull(output.get());
  EXPECT_GT(output->channel(0)[0],10); // Old initial samples were discarded.
  EXPECT_LT(output->channel(0)[0],static_cast<float>(signal.frames)/4096);
  for(int i=1;i<256;++i) EXPECT_FLOAT_EQ(output->channel(0)[i]-output->channel(0)[i-1],1.f/4096);
  sink->Stop();
}
}  // namespace

int main(int argc,char** argv) {
  base::AtExitManager at_exit;
  base::CommandLine::Init(argc,argv);
  testing::InitGoogleTest(&argc,argv);
  return RUN_ALL_TESTS();
}
