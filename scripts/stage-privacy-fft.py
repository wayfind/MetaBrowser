#!/usr/bin/env python3
"""Stage profile-selected scalar RustFFT with shared fdlibm planning math."""
import argparse
import hashlib
import json
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args()
root=a.source.resolve(strict=True);project=Path(__file__).resolve().parents[1]
assert (root/'chrome/VERSION').read_text().splitlines()==['MAJOR=154','MINOR=0','BUILD=8037','PATCH=97']
original,changes={},{}
def read(name):
    path=root/name;assert not path.is_symlink() and path.resolve().is_relative_to(root)
    # Preserve upstream CRLF bytes too: text-mode universal newline conversion
    # would otherwise make unchanged dependency hashes disagree with the build.
    if name not in original:original[name]=path.read_bytes().decode('utf-8') if path.exists() else None
    return changes.get(name,original[name])
def edit(name,old,new,previous=None):
    text=read(name);assert text is not None
    if new in text:assert text.count(new)==1
    elif previous is not None and previous in text:
        assert text.count(previous)==1;text=text.replace(previous,new,1)
    else:
        assert text.count(old)==1,('Pinned FFT source drift',name,old[:100]);text=text.replace(old,new,1)
    changes[name]=text
audio='third_party/blink/renderer/platform/audio/'
vendor='third_party/rust/chromium_crates_io/vendor/rustfft-v6/'
for src,dest in [('fft_math.h',audio+'metabrowser_fft_math.h'),('fft_math.rs',vendor+'src/metabrowser_math.rs')]:
    read(dest);changes[dest]=(project/'chromium/identity'/src).read_text()
edit(vendor+'src/lib.rs','mod twiddles;','pub mod metabrowser_math;\nmod twiddles;')
edit(vendor+'src/twiddles.rs',
     '''    let result = Complex {
        re: T::from_f64(angle.cos()).unwrap(),
        im: T::from_f64(angle.sin()).unwrap(),
    };''',
     '''    let (sin, cos) = crate::metabrowser_math::sin_cos(angle);
    let result = Complex {
        re: T::from_f64(cos).unwrap(),
        im: T::from_f64(sin).unwrap(),
    };''')
edit('third_party/rust/rustfft/v6/BUILD.gn',
     '    "//'+vendor+'src/math_utils.rs",',
     '    "//'+vendor+'src/math_utils.rs",\n    "//'+vendor+'src/metabrowser_math.rs",')
name=audio+'rustfft_ffi.rs'
edit(name,'use rustfft::{Fft, FftPlanner};','use rustfft::{Fft, FftPlanner, FftPlannerScalar};')
edit(name,'type FftPair = (Arc<dyn Fft<f32>>, Arc<dyn Fft<f32>>);',
     '''type FftPair = (Arc<dyn Fft<f32>>, Arc<dyn Fft<f32>>);

fn portable_sin_cos(angle: f64) -> (f64, f64) {
    (ffi::metabrowser_fft_sin(angle), ffi::metabrowser_fft_cos(angle))
}''')
edit(name,'static CACHE: OnceLock<RwLock<HashMap<usize, FftPair>>> = OnceLock::new();',
     'static CACHE: OnceLock<RwLock<HashMap<(usize, bool), FftPair>>> = OnceLock::new();')
edit(name,"fn get_cache() -> &'static RwLock<HashMap<usize, FftPair>> {",
     "fn get_cache() -> &'static RwLock<HashMap<(usize, bool), FftPair>> {")
edit(name,'fn get_fft(size: usize) -> FftPair {','fn get_fft(size: usize, portable: bool) -> FftPair {')
edit(name,'cache.read().unwrap().get(&size)','cache.read().unwrap().get(&(size, portable))')
edit(name,'''    let mut planner = FftPlanner::new();
    let forward = planner.plan_fft_forward(size);
    let inverse = planner.plan_fft_inverse(size);''',
     '''    let (forward, inverse) = if portable {
        rustfft::metabrowser_math::with_twiddle_provider(portable_sin_cos, || {
            let mut planner = FftPlannerScalar::<f32>::new();
            (planner.plan_fft_forward(size), planner.plan_fft_inverse(size))
        })
    } else {
        rustfft::metabrowser_math::with_native_twiddle_math(|| {
            let mut planner = FftPlanner::new();
            (planner.plan_fft_forward(size), planner.plan_fft_inverse(size))
        })
    };''',previous='''    let (forward, inverse) = if portable {
        rustfft::metabrowser_math::with_twiddle_provider(portable_sin_cos, || {
            let mut planner = FftPlannerScalar::<f32>::new();
            (planner.plan_fft_forward(size), planner.plan_fft_inverse(size))
        })
    } else {
        let mut planner = FftPlanner::new();
        (planner.plan_fft_forward(size), planner.plan_fft_inverse(size))
    };''')
edit(name,'cache_write.entry(size).or_insert(pair).clone()',
     'cache_write.entry((size, portable)).or_insert(pair).clone()')
edit(name,'pub fn rustfft_new(size: usize) -> Box<RustFft> {',
     '''pub fn rustfft_new(size: usize) -> Box<RustFft> {
    build_fft(size, false)
}

pub fn rustfft_new_portable(size: usize) -> Box<RustFft> {
    build_fft(size, true)
}

fn build_fft(size: usize, portable: bool) -> Box<RustFft> {''')
edit(name,'get_fft(half_size);','get_fft(half_size, portable);')
edit(name,'get_fft(size);','get_fft(size, portable);')
edit(name,'let (sin, cos) = angle.sin_cos();',
     'let (sin, cos) = if portable { portable_sin_cos(angle) } else { angle.sin_cos() };')
edit(name,'pub mod ffi {',
     '''pub mod ffi {
    unsafe extern "C++" {
        include!("third_party/blink/renderer/platform/audio/metabrowser_fft_math.h");
        fn metabrowser_fft_sin(angle: f64) -> f64;
        fn metabrowser_fft_cos(angle: f64) -> f64;
    }''')
edit(name,'        fn rustfft_new(size: usize) -> Box<RustFft>;',
     '        fn rustfft_new(size: usize) -> Box<RustFft>;\n        fn rustfft_new_portable(size: usize) -> Box<RustFft>;')
name='third_party/blink/renderer/platform/BUILD.gn'
edit(name,'rust_static_library("rustfft_ffi") {',
     '''source_set("metabrowser_fft_math") {
  sources = [ "audio/metabrowser_fft_math.h" ]
  deps = [ "//third_party/fdlibm" ]
}

rust_static_library("rustfft_ffi") {''')
edit(name,'  deps = [ "//third_party/rust/rustfft/v6:lib" ]',
     '''  deps = [
    ":metabrowser_fft_math",
    "//third_party/rust/rustfft/v6:lib",
  ]''')
name=audio+'fft_frame.cc'
edit(name,'#include "third_party/blink/renderer/platform/audio/fft_frame.h"',
     '#include "third_party/blink/renderer/platform/audio/fft_frame.h"\n#include "third_party/blink/public/common/user_agent/metabrowser_persona_runtime.h"')
edit(name,'namespace blink {',
     '''namespace blink {
namespace {
bool MetaBrowserPortableFft() {
  if (!base::CommandLine::InitializedForCurrentProcess()) return false;
  static const bool portable = [] {
    const auto* persona = metabrowser::EmulatedPersona();
    return persona && persona->fft_backend ==
        metabrowser::PersonaFftBackend::kScalarFdlibm;
  }();
  return portable;
}
}  // namespace''')
text=read(name);old='if (RuntimeEnabledFeatures::WebAudioRustFftEnabled()) {';new='if (MetaBrowserPortableFft() || RuntimeEnabledFeatures::WebAudioRustFftEnabled()) {'
if new in text:assert text.count(new)==5
else:assert text.count(old)==5;changes[name]=text.replace(old,new)
edit(name,'    rust_fft_ = blink::rust_fft::rustfft_new(fft_size_);',
     '''    rust_fft_ = MetaBrowserPortableFft()
        ? blink::rust_fft::rustfft_new_portable(fft_size_)
        : blink::rust_fft::rustfft_new(fft_size_);''')
name='third_party/blink/renderer/modules/webaudio/realtime_analyser.cc'
edit(name,'#include "third_party/blink/renderer/modules/webaudio/realtime_analyser.h"',
     '''#include "third_party/blink/renderer/modules/webaudio/realtime_analyser.h"
#include "third_party/blink/public/common/user_agent/metabrowser_persona_runtime.h"
#include "third_party/fdlibm/ieee754.h"''')
edit(name,'  const size_t n = p.size();',
     '''  const auto* persona = metabrowser::EmulatedPersona();
  const bool portable = persona && persona->fft_backend ==
      metabrowser::PersonaFftBackend::kScalarFdlibm;
  const size_t n = p.size();''')
edit(name,'''        a0 - a1 * cos(kTwoPiDouble * x) + a2 * cos(kTwoPiDouble * 2.0 * x);''',
     '''        portable
            ? a0 - a1 * fdlibm::cos(kTwoPiDouble * x) +
                  a2 * fdlibm::cos(kTwoPiDouble * 2.0 * x)
            : a0 - a1 * cos(kTwoPiDouble * x) + a2 * cos(kTwoPiDouble * 2.0 * x);''')
name=audio+'audio_utilities.cc'
edit(name,'#include "third_party/blink/renderer/platform/audio/audio_utilities.h"',
     '''#include "third_party/blink/renderer/platform/audio/audio_utilities.h"
#include "third_party/blink/public/common/user_agent/metabrowser_persona_runtime.h"
#include "third_party/fdlibm/ieee754.h"''')
edit(name,'namespace blink::audio_utilities {',
     '''namespace blink::audio_utilities {
namespace {
bool MetaBrowserPortableAudioMath() {
  if (!base::CommandLine::InitializedForCurrentProcess()) return false;
  static const bool portable = [] {
    const auto* persona = metabrowser::EmulatedPersona();
    return persona && persona->fft_backend ==
        metabrowser::PersonaFftBackend::kScalarFdlibm;
  }();
  return portable;
}
}  // namespace''')
edit(name,'  return powf(10, 0.05f * decibels);',
     '''  if (MetaBrowserPortableAudioMath()) return fdlibm::powf(10, 0.05f * decibels);
  return powf(10, 0.05f * decibels);''')
edit(name,'  return 20 * log10f(linear);',
     '''  if (MetaBrowserPortableAudioMath())
    return 20 * static_cast<float>(fdlibm::log10(linear));
  return 20 * log10f(linear);''')
# Bind actual math kernels and planner sources, not only routing wrappers.
for folder in [root/vendor/'src',root/'third_party/fdlibm']:
    for path in sorted(folder.rglob('*')):
        if path.is_file() and path.suffix in ('.rs','.cc','.h'):
            name=path.relative_to(root).as_posix();changes[name]=read(name)
for name in ['third_party/fdlibm/BUILD.gn','build/config/compiler/BUILD.gn']:
    changes[name]=read(name)
for name,before in original.items():
    path=root/name;assert (path.read_bytes().decode('utf-8') if path.exists() else None)==before,'Source changed during preflight'
if a.apply:
    for name,text in changes.items():
        if text!=original[name]:
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
print(json.dumps({'scope':'profile-scalar-fft-fdlibm-scoped-planning-and-backend-cache','applied':a.apply,
                  'all_files':{n:hashlib.sha256(t.encode()).hexdigest() for n,t in changes.items()}}))
