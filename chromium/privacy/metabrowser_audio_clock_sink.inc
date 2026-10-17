// Copyright 2026 MetaBrowser Authors. BSD-3-Clause.
// Included inside content's anonymous namespace. Only the explicit experimental
// audio cohort uses this adapter. The NullAudioSink is a metronome, NOT an
// output replacement: every rendered bus is queued for the real audio sink.
class MetaBrowserAudioClockSink final
    : public media::AudioRendererSink,
      private media::AudioRendererSink::RenderCallback {
 public:
  MetaBrowserAudioClockSink(
      scoped_refptr<media::AudioRendererSink> physical_sink,
      scoped_refptr<base::SequencedTaskRunner> clock_runner)
      : physical_sink_(std::move(physical_sink)),
        clock_sink_(base::MakeRefCounted<media::NullAudioSink>(clock_runner)),
        physical_callback_(this) {}

  void Initialize(const media::AudioParameters& params,
                  RenderCallback* callback) override {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    CHECK(!initialized_);
    callback_ = callback;
    block_frames_ = params.frames_per_buffer();
    // Bounded allocation, made before either realtime callback starts. The
    // extra capacity absorbs independent clock drift; it is not a public
    // hardware capability or a delay returned to the graph.
    fifo_ = std::make_unique<media::AudioFifo>(
        params.channels(), std::max(params.sample_rate() / 2,
                                    block_frames_ * 4));
    discard_bus_ = media::AudioBus::Create(params);
    clock_sink_->Initialize(params, this);
    physical_sink_->Initialize(params, &physical_callback_);
    initialized_ = true;
  }

  void Start() override {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    CHECK(initialized_);
    physical_sink_->Start();
    clock_sink_->Start();
  }
  void Play() override {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    clock_sink_->Play();
    physical_sink_->Play();
  }
  void Pause() override {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    // Stop graph production first; no audio graph or FIFO lock is held while
    // waiting for that callback to finish.
    clock_sink_->Pause();
    physical_sink_->Pause();
    ClearFifo();
  }
  void Stop() override {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    if (!initialized_) return;
    clock_sink_->Stop();
    physical_sink_->Stop();
    // Both callback sources are now stopped. In particular FakeAudioWorker's
    // callback lock makes Stop wait for any in-progress producer callback.
    callback_ = nullptr;
    ClearFifo();
    initialized_ = false;
  }
  void Flush() override {
    DCHECK_CALLED_ON_VALID_SEQUENCE(sequence_checker_);
    clock_sink_->Flush();
    physical_sink_->Flush();
    ClearFifo();
  }
  bool SetVolume(double volume) override {
    return physical_sink_->SetVolume(volume);
  }
  media::OutputDeviceInfo GetOutputDeviceInfo() override {
    return physical_sink_->GetOutputDeviceInfo();
  }
  void GetOutputDeviceInfoAsync(OutputDeviceInfoCB callback) override {
    physical_sink_->GetOutputDeviceInfoAsync(std::move(callback));
  }
  bool IsOptimizedForHardwareParameters() override { return false; }
  bool CurrentThreadIsRenderingThread() override {
    return clock_sink_->CurrentThreadIsRenderingThread();
  }

 private:
  ~MetaBrowserAudioClockSink() override { Stop(); }

  int Render(base::TimeDelta public_delay, base::TimeTicks public_timestamp,
             const media::AudioGlitchInfo& public_glitches,
             media::AudioBus* bus) override {
    // NullAudioSink/FakeAudioWorker derives delay (two public buffers), ideal
    // timestamps and cadence solely from the public stream. No physical
    // delay, timestamp, FIFO occupancy or private glitch count is forwarded.
    const int rendered = callback_->Render(public_delay, public_timestamp,
                                            public_glitches, bus);
    CHECK_GE(rendered, 0);
    CHECK_LE(rendered, bus->frames());
    if (!rendered) return 0;
    base::AutoLock lock(fifo_lock_);
    // Never allocate, call the graph or wait for a callback while holding this
    // lock. On a long device stall drop oldest private output, retaining the
    // bounded queue and newest audio rather than growing latency indefinitely.
    while (fifo_->max_frames() - fifo_->frames() <
           static_cast<size_t>(rendered)) {
      fifo_->Consume(discard_bus_.get(), 0,
                     std::min(static_cast<size_t>(block_frames_), fifo_->frames()));
    }
    fifo_->Push(bus, rendered);
    return rendered;
  }
  void OnRenderError() override { callback_->OnRenderError(); }

  void ClearFifo() {
    base::AutoLock lock(fifo_lock_);
    if (fifo_) fifo_->Clear();
    primed_ = false;
  }
  int Consume(media::AudioBus* bus) {
    bus->Zero();
    base::AutoLock lock(fifo_lock_);
    // Prefill two public blocks before starting/restarting private playback.
    // The consumer can request a different size; never overread the queue.
    if (!primed_) {
      if (fifo_->frames() < static_cast<size_t>(
              std::max(block_frames_ * 2, bus->frames()))) return bus->frames();
      primed_ = true;
    }
    const int available = std::min(static_cast<size_t>(bus->frames()),
                                    fifo_->frames());
    if (available) fifo_->Consume(bus, 0, available);
    if (available < bus->frames()) primed_ = false;
    return bus->frames();
  }

  class PhysicalCallback final : public RenderCallback {
   public:
    explicit PhysicalCallback(MetaBrowserAudioClockSink* owner) : owner_(owner) {}
    int Render(base::TimeDelta, base::TimeTicks,
               const media::AudioGlitchInfo&, media::AudioBus* bus) override {
      return owner_->Consume(bus);
    }
    void OnRenderError() override { owner_->OnRenderError(); }
   private:
    raw_ptr<MetaBrowserAudioClockSink> owner_;
  };

  scoped_refptr<media::AudioRendererSink> physical_sink_;
  scoped_refptr<media::NullAudioSink> clock_sink_;
  PhysicalCallback physical_callback_;
  raw_ptr<RenderCallback> callback_ = nullptr;
  std::unique_ptr<media::AudioFifo> fifo_;
  std::unique_ptr<media::AudioBus> discard_bus_;
  int block_frames_ = 0;
  bool initialized_ = false;
  base::Lock fifo_lock_;
  bool primed_ GUARDED_BY(fifo_lock_) = false;
  SEQUENCE_CHECKER(sequence_checker_);
};
