#!/usr/bin/env python3
"""Route the explicit scalar cohort through actual scalar oscillator processing."""
import argparse
import hashlib
import json
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args()
root=a.source.resolve(strict=True)
assert (root/'chrome/VERSION').read_text().splitlines()==['MAJOR=154','MINOR=0','BUILD=8037','PATCH=97']
before,after={},{}
def read(name):
    path=root/name;assert not path.is_symlink() and path.resolve().is_relative_to(root)
    if name not in before:before[name]=path.read_bytes().decode('utf-8')
    return after.get(name,before[name])
def edit(name,old,new,count=1):
    text=read(name)
    if new in text:assert text.count(new)==count
    else:
        assert text.count(old)==count,('Oscillator source drift',name,old[:100]);text=text.replace(old,new)
    after[name]=text
directory='third_party/blink/renderer/modules/webaudio/'
runtime='#include "third_party/blink/public/common/user_agent/metabrowser_persona_runtime.h"\n#include "third_party/fdlibm/ieee754.h"'
def setup(name,header,helper):
    edit(name,'#include "'+header+'"','#include "'+header+'"\n'+runtime)
    edit(name,'namespace blink {', '''namespace blink {
namespace {
bool '''+helper+'''() {
  if (!base::CommandLine::InitializedForCurrentProcess()) return false;
  static const bool scalar = [] {
    const auto* persona = metabrowser::EmulatedPersona();
    return persona && persona->audio_vector_backend ==
        metabrowser::PersonaAudioVectorBackend::kScalar;
  }();
  return scalar;
}
}  // namespace''')
name=directory+'oscillator_handler.cc';setup(name,name[:-3]+'.h','MetaBrowserScalarOscillator')
edit(name,'float DetuneToFrequencyMultiplier(float detune_value) {\n  return std::exp2(detune_value / 1200);\n}',
     '''float MetaBrowserOscillatorExp2(float value) {
  return MetaBrowserScalarOscillator() ? fdlibm::powf(2.0f, value) : std::exp2(value);
}

float DetuneToFrequencyMultiplier(float detune_value) {
  return MetaBrowserOscillatorExp2(detune_value / 1200);
}''')
edit(name,'detune_values[i] = std::exp2(detune_values[i]);','detune_values[i] = MetaBrowserOscillatorExp2(detune_values[i]);')
edit(name,'    int k;\n    double v_index = virtual_read_index;',
     '    int k = 0;\n    double v_index = virtual_read_index;')
edit(name,'''    std::tie(k, v_index) =
        ProcessKRateVector(n, destination, v_index, frequency, rate_scale);''',
     '''    if (!MetaBrowserScalarOscillator()) {
      std::tie(k, v_index) =
          ProcessKRateVector(n, destination, v_index, frequency, rate_scale);
    }''')
edit(name,'''  std::tie(frames_processed, virtual_read_index) =
      ProcessARateVector(n, destination, virtual_read_index, phase_increments);''',
     '''  if (!MetaBrowserScalarOscillator()) {
    std::tie(frames_processed, virtual_read_index) =
        ProcessARateVector(n, destination, virtual_read_index, phase_increments);
  }''')
name=directory+'periodic_wave.cc';setup(name,name[:-3]+'.h','MetaBrowserScalarPeriodicWave')
edit(name,'namespace {\n\n//',
     '''namespace {

float MetaBrowserPeriodicLog2(float value) {
  return MetaBrowserScalarPeriodicWave() ? static_cast<float>(fdlibm::log2(value))
                                       : log2f(value);
}

//''')
edit(name,'log2f(PeriodicWaveSize())','MetaBrowserPeriodicLog2(PeriodicWaveSize())')
edit(name,'log2f(ratio)','MetaBrowserPeriodicLog2(ratio)')
edit(name,'log2f(ratio[k])','MetaBrowserPeriodicLog2(ratio[k])',count=2)
head='''void PeriodicWaveImpl::WaveDataForFundamentalFrequency(
    const std::array<float, 4> fundamental_frequency,
    std::array<base::span<const float>, 4>& lower_wave_data,
    std::array<base::span<const float>, 4>& higher_wave_data,
    std::array<float, 4>& table_interpolation_factor) {'''
edit(name,head,head+'''
  if (MetaBrowserScalarPeriodicWave()) {
    for (int k = 0; k < 4; ++k) {
      WaveDataForFundamentalFrequency(fundamental_frequency[k], lower_wave_data[k],
                                      higher_wave_data[k], table_interpolation_factor[k]);
    }
    return;
  }''',count=3)
edit(name,'  float culling_scale = pow(2, -cents_to_cull / 1200);',
     '''  float culling_scale = MetaBrowserScalarPeriodicWave()
      ? fdlibm::pow(2, -cents_to_cull / 1200)
      : pow(2, -cents_to_cull / 1200);''')
for name,old in before.items():assert (root/name).read_bytes().decode('utf-8')==old
if a.apply:
    for name,text in after.items():
        if text!=before[name]:(root/name).write_bytes(text.encode('utf-8'))
print(json.dumps({'scope':'scalar-cohort-oscillator-and-periodic-wave-numerical-paths','applied':a.apply,
                  'all_files':{name:hashlib.sha256(text.encode()).hexdigest() for name,text in after.items()}}))
