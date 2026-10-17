#!/usr/bin/env python3
"""Separate experimental public WebAudio stream parameters from physical output.

This does not isolate hardware delay/timestamps and is not a full privacy gate.
"""
import argparse
import hashlib
import json
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('source',type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args()
root=a.source.resolve(strict=True)
assert (root/'chrome/VERSION').read_text().splitlines()==['MAJOR=154','MINOR=0','BUILD=8037','PATCH=97']
name='content/renderer/media/renderer_webaudiodevice_impl.cc'
path=root/name
assert not path.is_symlink() and path.resolve().is_relative_to(root)
original=path.read_text();text=original

def edit(old,new):
 global text
 if new in text:assert text.count(new)==1,('duplicate',new[:80])
 else:
  assert text.count(old)==1,('Audio device source drift',old[:100],text.count(old))
  text=text.replace(old,new)

edit('#include <algorithm>','#include <algorithm>\n#include <cmath>')
edit('#include "third_party/blink/public/common/features.h"',
 '#include "third_party/blink/public/common/features.h"\n#include "third_party/blink/public/common/user_agent/metabrowser_persona_runtime.h"')
helper='''// METABROWSER_PUBLIC_AUDIO_DEVICE_BEGIN
// Public experimental cohort parameters. Physical output parameters remain
// separate in AudioManagerBase / AudioOutputResampler. In particular, this is
// NOT hardware clock or output latency isolation.
bool MetaBrowserPublicAudioDevice() {
  if (!base::CommandLine::InitializedForCurrentProcess()) return false;
  static const bool enabled = [] {
    const auto* persona = metabrowser::EmulatedPersona();
    return persona && persona->audio_vector_backend ==
        metabrowser::PersonaAudioVectorBackend::kScalar;
  }();
  return enabled;
}

constexpr int kMetaBrowserAudioSampleRate = 48000;
constexpr int kMetaBrowserAudioChannels = 2;
constexpr int kMetaBrowserAudioQuantum = 128;

int MetaBrowserPublicAudioBufferSize(const WebAudioLatencyHint& hint,
                                   int sample_rate) {
  double seconds = 0;
  switch (hint.Category()) {
    case WebAudioLatencyHint::kCategoryInteractive:
      seconds = 256.0 / kMetaBrowserAudioSampleRate;
      break;
    case WebAudioLatencyHint::kCategoryBalanced:
      seconds = 0.01;
      break;
    case WebAudioLatencyHint::kCategoryPlayback:
      seconds = 1024.0 / kMetaBrowserAudioSampleRate;
      break;
    case WebAudioLatencyHint::kCategoryExact:
      seconds = hint.Seconds();
      break;
    case WebAudioLatencyHint::kLastValue:
      NOTREACHED();
  }
  // Bound before converting to int, including very large exact hints.
  // Negative exact hints follow the upstream minimum-buffer fallback. Avoid
  // adding a renderer crash for a web-controlled hint, even for internal
  // callers bypassing Web IDL's finite-double conversion.
  const double requested = std::isnan(seconds) ? 0.0 : seconds * sample_rate;
  const double frames = std::clamp(
      requested, static_cast<double>(kMetaBrowserAudioQuantum),
      static_cast<double>(kMaxWebAudioBufferSize));
  const int rounded = static_cast<int>(
      std::ceil(frames / kMetaBrowserAudioQuantum)) * kMetaBrowserAudioQuantum;
  return std::clamp(rounded, kMinWebAudioBufferSize, kMaxWebAudioBufferSize);
}
// METABROWSER_PUBLIC_AUDIO_DEVICE_END

'''
if '// METABROWSER_PUBLIC_AUDIO_DEVICE_BEGIN' in text:
 assert text.count(helper)==1, 'Public audio policy source drift'
edit('blink::WebAudioDeviceSourceType GetLatencyHintSourceType(',helper+'blink::WebAudioDeviceSourceType GetLatencyHintSourceType(')
head='''    const media::AudioParameters& hardware_params) {'''
edit(head,head+'''
  if (MetaBrowserPublicAudioDevice()) {
    return MetaBrowserPublicAudioBufferSize(latency_hint,
                                           resolved_context_sample_rate);
  }''')
edit('''    resolved_context_sample_rate = original_sink_params_.sample_rate();''',
 '''    resolved_context_sample_rate = MetaBrowserPublicAudioDevice()
        ? kMetaBrowserAudioSampleRate : original_sink_params_.sample_rate();''')
edit('''  return original_sink_params_.channels();''',
 '''  return MetaBrowserPublicAudioDevice() ? kMetaBrowserAudioChannels
                                       : original_sink_params_.channels();''')
# Guard the complete helper, not just its marker, against partially edited code.
assert text.count(helper)==1,'Public audio policy source drift'
assert path.read_text()==original
if a.apply and text!=original:path.write_text(text)
print(json.dumps({'scope':'experimental-public-audio-stream-parameters',
 'applied':a.apply,'hardware_clock_isolated':False,'full_scope_complete':False,
 'all_files':{name:hashlib.sha256(text.encode()).hexdigest()}}))
