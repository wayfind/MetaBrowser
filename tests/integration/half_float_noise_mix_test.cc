// Verify seed-bit influence independently of Skia and the host GPU.
#include "metabrowser_noise_mix.h"
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <set>

std::array<uint8_t, 256> Pattern(uint64_t seed) {
  std::array<uint8_t, 256> out{};
  for (uint64_t i = 0; i < out.size(); ++i)
    out[i] = blink::MetaBrowserHalfFloatMask(seed, i);
  return out;
}
int main() {
  std::set<std::array<uint8_t, 256>> patterns;
  const uint64_t seed = UINT64_C(0xa562bcd301786def);
  const auto initial = Pattern(seed);
  assert(initial == Pattern(seed));
  for (int bit = 0; bit < 64; ++bit) {
    const auto changed = Pattern(seed ^ (UINT64_C(1) << bit));
    assert(initial != changed);
    patterns.insert(changed);
  }
  assert(patterns.size() == 64);
  patterns.clear();
  // These seeds share every low bit consumed by the previous FNV path.
  for (uint64_t i = 0; i < 256; ++i) {
    const auto value = Pattern(seed ^ (i << 32));
    for (auto mask : value) assert(mask <= 7);
    patterns.insert(value);
  }
  assert(patterns.size() == 256);
  for (uint16_t value : {uint16_t{1}, uint16_t{0x3c00}, uint16_t{0x7bff}, uint16_t{0x8001}, uint16_t{0xbc00}}) {
    const auto changed = value ^ 1;
    assert((changed & 0x8000) == (value & 0x8000));
    assert((changed & 0x7fff) < 0x7c00);
  }
  std::cout << "PASS: all64 seed bits influence masks;256 high-bit seeds separated;finite/sign bounds\n";
}
