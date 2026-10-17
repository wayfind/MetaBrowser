// Copyright 2026 MetaBrowser Authors. BSD-3-Clause.
#ifndef THIRD_PARTY_BLINK_RENDERER_PLATFORM_AUDIO_METABROWSER_FFT_MATH_H_
#define THIRD_PARTY_BLINK_RENDERER_PLATFORM_AUDIO_METABROWSER_FFT_MATH_H_
#include "third_party/fdlibm/ieee754.h"
namespace blink::rust_fft {
inline double metabrowser_fft_sin(double angle) { return fdlibm::sin(angle); }
inline double metabrowser_fft_cos(double angle) { return fdlibm::cos(angle); }
}  // namespace blink::rust_fft
#endif
