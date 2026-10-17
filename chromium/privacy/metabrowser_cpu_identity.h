// Copyright 2026 MetaBrowser Authors. BSD-3-Clause.
#ifndef METABROWSER_CPU_IDENTITY_H_
#define METABROWSER_CPU_IDENTITY_H_

#include <cstdint>

namespace blink {

// Derive a coherent generic tier from the public profile, never the private CPU
// model string. Matches Chromium154's generic and Apple M-series cohort rules.
// The current Mac/ARM64 template represents the broad M-series desktop cohort;
// future emulated platforms must supply their own explicit template metadata.
constexpr uint16_t MetaBrowserCpuTierForPublicTemplate(unsigned cores,
                                                     bool apple_m_series) {
  if (cores == 0) return 0;
  if (cores <= 2) return 1;
  if (cores <= 4) return 2;
  if (apple_m_series && cores >= 8) return 4;
  if (cores <= 10) return 3;
  return 4;
}

}  // namespace blink
#endif  // METABROWSER_CPU_IDENTITY_H_
