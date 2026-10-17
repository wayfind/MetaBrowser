// Copyright 2026 MetaBrowser Authors. BSD-3-Clause.
#ifndef THIRD_PARTY_BLINK_RENDERER_CORE_CANVAS_INTERVENTIONS_METABROWSER_SURFACE_PRIVACY_H_
#define THIRD_PARTY_BLINK_RENDERER_CORE_CANVAS_INTERVENTIONS_METABROWSER_SURFACE_PRIVACY_H_

#include <cmath>
#include <bit>
#include <cstdint>
#include <cstring>

#include "build/build_config.h"
#include "third_party/blink/renderer/core/execution_context/execution_context.h"
#include "third_party/blink/renderer/platform/wtf/text/wtf_string.h"

namespace blink {

inline bool MetaBrowserSurfaceProtected(const ExecutionContext* context) {
  return context && context->CanvasNoiseToken().has_value();
}

inline uint64_t MetaBrowserSurfaceMix(uint64_t value) {
  value ^= value >> 30;
  value *= UINT64_C(0xbf58476d1ce4e5b9);
  value ^= value >> 27;
  value *= UINT64_C(0x94d049bb133111eb);
  return value ^ (value >> 31);
}

// A stock macOS font visibility set, not a fabricated font-metrics table.
// Web fonts are resolved before this filter. Actual font rendering/metrics are
// preserved; installed third-party font names are not implicitly web-visible.
// System glyph fallback and OS-version differences remain separate surfaces.
inline bool MetaBrowserFontVisible(const ExecutionContext* context,
                                   const String& family) {
#if BUILDFLAG(IS_MAC)
  if (MetaBrowserSurfaceProtected(context)) {
    static constexpr const char* kFamilies[] = {
        "Arial", "ArialMT", "Arial Black", "Arial Narrow", "Arial Unicode MS",
        "Helvetica", "Helvetica Neue", "HelveticaNeue", "Times",
        "Times New Roman", "TimesNewRomanPSMT", "Courier", "Courier New",
        "CourierNewPSMT", "Verdana", "Georgia", "Tahoma", "Trebuchet MS",
        "Impact", "Comic Sans MS", "Menlo", "Monaco", "Apple Color Emoji",
        "Apple Symbols", "Symbol", "Zapf Dingbats", "LastResort", "Geneva",
        "Lucida Grande", "LucidaGrande", "Palatino", "Optima", "Avenir",
        "Avenir Next", "AvenirNext", "American Typewriter", "Baskerville",
        "Didot", "Futura", "Gill Sans", "Herculanum", "Hoefler Text",
        "Noteworthy", "Papyrus", "Savoye LET", "Snell Roundhand",
        "PingFang SC", "PingFang TC", "PingFang HK", "PingFangSC-Regular",
        "PingFangTC-Regular", "PingFangHK-Regular", "Songti SC", "Songti TC",
        "Heiti SC", "Heiti TC", "STHeiti", "STSong", "STKaiti",
        "STFangsong", "Kaiti SC", "Kaiti TC", "Hiragino Sans",
        "Hiragino Kaku Gothic ProN", "Hiragino Mincho ProN", "Apple SD Gothic Neo",
        ".AppleSystemUIFont", ".SF NS", ".SFNS", ".SFNS-Regular",
        ".SF NS Text", ".SF NS Display", "SF Pro", "SF Pro Text", "SF Pro Display"};
    for (const auto* item : kFamilies) {
      if (EqualIgnoringAsciiCase(family, item)) return true;
    }
    // Explicit styles only: a prefix match could expose arbitrary custom fonts.
    static constexpr const char* kStyles[] = {
        "-Regular", "-Bold", "-Italic", "-Oblique", "-BoldItalic",
        "-BoldOblique", "-Medium", "-Light", "-Thin", "-Semibold",
        " Regular", " Bold", " Italic", " Bold Italic", " Medium", " Light"};
    for (const auto* style : kStyles) {
      if (family.EndsWithIgnoringAsciiCase(style)) {
        const auto base = family.substr(0,
            family.length() - static_cast<unsigned>(std::strlen(style)));
        for (const auto* item : kFamilies) {
          if (EqualIgnoringAsciiCase(base, item)) return true;
        }
      }
    }
    return false;
  }
#endif
  return true;
}

// Perturb only copies returned to script. Same token/input/index/domain gives
// the same result; neither the audio graph nor playback samples are mutated.
inline float MetaBrowserAnalyserSample(float sample, uint64_t token,
                                      uint64_t index, bool frequency) {
  if (!std::isfinite(sample) || sample == 0.0f) return sample;
  const uint32_t bits = std::bit_cast<uint32_t>(sample);
  const auto key = MetaBrowserSurfaceMix(token ^ UINT64_C(0x4d42414e414c3031));
  const auto random = MetaBrowserSurfaceMix(key ^ index ^
      (static_cast<uint64_t>(bits) << 16) ^ (frequency ? UINT64_C(0xf1) : UINT64_C(0x71)));
  const double unit = static_cast<double>(random >> 11) * 0x1.0p-53;
  const double bound = frequency ? 1.0e-4 : 5.0e-8;
  const float result = static_cast<float>(sample + (unit * 2.0 - 1.0) * bound);
  return std::isfinite(result) &&
      std::abs(static_cast<double>(result) - sample) <= bound * 2 ? result : sample;
}

}  // namespace blink
#endif
