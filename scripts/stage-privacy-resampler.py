#!/usr/bin/env python3
"""Explicit portable media resampling backend, selected by Blink scalar persona."""
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
 if new in text:assert text.count(new)==count,(name,'duplicate staged fragment')
 else:
  assert text.count(old)==count,('Resampler source drift',name,old[:100],text.count(old))
  text=text.replace(old,new)
 after[name]=text
h='media/base/sinc_resampler.h';cc='media/base/sinc_resampler.cc'
edit(h,'class MEDIA_EXPORT SincResampler {\n public:', '''class MEDIA_EXPORT SincResampler {
 public:
  // Explicit instance policy: media never depends on Blink identity internals.
  enum class MathBackend { kNative, kScalarFdlibm };''')
edit(h,'                const ReadCB read_cb);','                const ReadCB read_cb,\n                MathBackend math_backend = MathBackend::kNative);')
edit(h,'  const size_t kernel_size_;','  const MathBackend math_backend_;\n  const size_t kernel_size_;')
edit(h,'  void InitializeKernel();', '''  void InitializeKernel();
  double KernelSin(double value) const;
  double KernelCos(double value) const;''')
old='''  static float Convolve_C(const base::span<const float>& input_ptr,
                          const base::span<const float>& k1,
                          const base::span<const float>& k2,
                          double kernel_interpolation_factor);'''
edit(h,old,old+'\n'+old.replace('Convolve_C','Convolve_Portable'))
edit(cc,'#include "media/base/sinc_resampler.h"','#include "media/base/sinc_resampler.h"\n#include "third_party/fdlibm/ieee754.h"')
edit(cc,'void SincResampler::InitializeCPUSpecificFeatures() {', '''void SincResampler::InitializeCPUSpecificFeatures() {
  if (math_backend_ == MathBackend::kScalarFdlibm) {
    convolve_proc_ = Convolve_Portable;
    return;
  }''')
edit(cc,'''                             const ReadCB read_cb)
    : kernel_size_(KernelSizeFromRequestFrames(request_frames)),''', '''                             const ReadCB read_cb,
                             MathBackend math_backend)
    : math_backend_(math_backend),
      kernel_size_(KernelSizeFromRequestFrames(request_frames)),''')
edit(cc,'void SincResampler::InitializeKernel() {', '''double SincResampler::KernelSin(double value) const {
  return math_backend_ == MathBackend::kScalarFdlibm ? fdlibm::sin(value) : sin(value);
}

double SincResampler::KernelCos(double value) const {
  return math_backend_ == MathBackend::kScalarFdlibm ? fdlibm::cos(value) : cos(value);
}

void SincResampler::InitializeKernel() {''')
edit(cc,'cos(2.0 * std::numbers::pi * x)','KernelCos(2.0 * std::numbers::pi * x)')
edit(cc,'cos(4.0 * std::numbers::pi * x)','KernelCos(4.0 * std::numbers::pi * x)')
edit(cc,'sin(sinc_scale_factor * pre_sinc)','KernelSin(sinc_scale_factor * pre_sinc)',count=2)
text=read(cc)
start=text.index('float SincResampler::Convolve_C(');brace=text.index('{',start);level=1;end=brace+1
while level:
 level += (text[end]=='{')-(text[end]=='}');end+=1
original=text[start:end]
portable=original.replace('Convolve_C','Convolve_Portable',1).replace('{','''{
  // Specify scalar rounding and accumulation order independently of host SIMD.
#if defined(__clang__)
#pragma clang fp contract(off)
#pragma clang fp reassociate(off)
#endif''',1)
if 'float SincResampler::Convolve_Portable(' in text:
 assert text.count(portable)==1, 'Portable convolution source drift'
 assert text.count('float SincResampler::Convolve_Portable(')==1
 after[cc]=text
else:
 edit(cc,original,original+'\n\n'+portable)
mh='media/base/multi_channel_resampler.h';mc='media/base/multi_channel_resampler.cc'
edit(mh,'                        const ReadCB read_cb);', '''                        const ReadCB read_cb,
                        SincResampler::MathBackend math_backend =
                            SincResampler::MathBackend::kNative);''')
edit(mc,'                                             const ReadCB read_cb)', '''                                             const ReadCB read_cb,
                                             SincResampler::MathBackend math_backend)''')
edit(mc,'base::Unretained(this), i)));','base::Unretained(this), i), math_backend));')
# Restrict the added fdlibm dependency to media/base's production base target.
gn='media/base/BUILD.gn';text=read(gn)
start=text.index('source_set("base") {');end=text.index('\nsource_set(',start+1)
block=text[start:end]
if '    "//third_party/fdlibm",' not in block:
 assert block.count('  deps = [\n')==1
 replacement=block.replace('  deps = [\n','  deps = [\n    "//third_party/fdlibm",\n',1)
 edit(gn,block,replacement)
else:after[gn]=text
runtime='#include "third_party/blink/public/common/user_agent/metabrowser_persona_runtime.h"'
helper='''namespace blink {
namespace {
media::SincResampler::MathBackend MetaBrowserResamplerBackend() {
  using Backend = media::SincResampler::MathBackend;
  if (!base::CommandLine::InitializedForCurrentProcess()) return Backend::kNative;
  static const Backend backend = [] {
    const auto* persona = metabrowser::EmulatedPersona();
    return persona && persona->audio_vector_backend ==
        metabrowser::PersonaAudioVectorBackend::kScalar
        ? Backend::kScalarFdlibm : Backend::kNative;
  }();
  return backend;
}
}  // namespace'''
for name in ['third_party/blink/renderer/platform/audio/audio_bus.cc','third_party/blink/renderer/platform/audio/media_multi_channel_resampler.cc']:
 header=name[:-3]+'.h';edit(name,'#include "'+header+'"','#include "'+header+'"\n'+runtime)
 edit(name,'namespace blink {',helper)
 if name.endswith('/audio_bus.cc'):
  edit(name,'            std::ref(source)));','            std::ref(source)), MetaBrowserResamplerBackend());')
 else:
  edit(name,'                          base::Unretained(this)));','                          base::Unretained(this)), MetaBrowserResamplerBackend());')
for name,old in before.items():assert (root/name).read_bytes().decode('utf-8')==old
if a.apply:
 for name,text in after.items():
  if text!=before[name]:(root/name).write_bytes(text.encode('utf-8'))
print(json.dumps({'scope':'explicit-scalar-fdlibm-media-resampler-Blink-entrypoints','applied':a.apply,
 'all_files':{name:hashlib.sha256(text.encode('utf-8')).hexdigest() for name,text in after.items()},
 'limits':'Does not yet select a portable backend for separate WebRTC resampler or BufferSource playback interpolation.'}))
