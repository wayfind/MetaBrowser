// Copyright 2026 MetaBrowser Authors. BSD-3-Clause.
#ifndef THIRD_PARTY_BLINK_RENDERER_CORE_CANVAS_INTERVENTIONS_METABROWSER_NOISE_MIX_H_
#define THIRD_PARTY_BLINK_RENDERER_CORE_CANVAS_INTERVENTIONS_METABROWSER_NOISE_MIX_H_
#include <cstdint>

namespace blink {
// Avalanche all seed bits before selecting the small public perturbation.
// This is an entropy mixer, not a cryptographic PRF or an anonymity proof.
inline uint64_t MetaBrowserNoiseMix64(uint64_t value) {
  value ^= value >> 30;
  value *= UINT64_C(0xbf58476d1ce4e5b9);
  value ^= value >> 27;
  value *= UINT64_C(0x94d049bb133111eb);
  return value ^ (value >> 31);
}
inline uint8_t MetaBrowserHalfFloatMask(uint64_t seed, uint64_t pixel_index) {
  return static_cast<uint8_t>(MetaBrowserNoiseMix64(
      seed ^ ((pixel_index + 1) * UINT64_C(0x9e3779b97f4a7c15))) & 7);
}
}  // namespace blink
#endif
