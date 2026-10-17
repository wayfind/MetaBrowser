#include "chromium/privacy/metabrowser_cpu_identity.h"

#include <cassert>
#include <iostream>

int main() {
  using blink::MetaBrowserCpuTierForPublicTemplate;
  // Regression: Chromium154 classifies M-series 8+ core systems as Ultra.
  // The previously fixed Mid=2 produced an incoherent public identity.
  assert(MetaBrowserCpuTierForPublicTemplate(8, true) == 4);
  assert(MetaBrowserCpuTierForPublicTemplate(8, false) == 3);
  assert(MetaBrowserCpuTierForPublicTemplate(4, false) == 2);
  assert(MetaBrowserCpuTierForPublicTemplate(2, true) == 1);
  assert(MetaBrowserCpuTierForPublicTemplate(0, false) == 0);
  for (unsigned cores = 1; cores <= 128; ++cores) {
    for (bool apple : {false, true}) {
      const auto tier = MetaBrowserCpuTierForPublicTemplate(cores, apple);
      assert(tier >= 1 && tier <= 4);
      if (apple && cores >= 8) assert(tier == 4);
      if (cores > 10) assert(tier == 4);
    }
  }
  std::cout << "PASS: public-profile CPU tiers preserve Apple/generic cohort consistency\n";
}
