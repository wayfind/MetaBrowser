#include "platform_version_policy.h"
#include <cassert>
#include <iostream>
int main() {
  using metabrowser::ApplyPlatformVersionPolicy;
  assert(ApplyPlatformVersionPolicy("26.6.2", "major") == "26.0.0");
  assert(ApplyPlatformVersionPolicy("26.6.2", "") == "26.0.0");
  assert(ApplyPlatformVersionPolicy("26.6.2", "invalid") == "26.0.0");
  assert(ApplyPlatformVersionPolicy("26.6.2", "system") == "26.6.2");
  assert(ApplyPlatformVersionPolicy("10.15.7", "major") == "10.0.0");
  assert(ApplyPlatformVersionPolicy("", "major").empty());
  assert(ApplyPlatformVersionPolicy("private-name", "major").empty());
  assert(metabrowser::ValidPlatformVersionPolicy("major"));
  assert(metabrowser::ValidPlatformVersionPolicy("system"));
  for (auto bad : {"", "MAJOR", "26.0.0", "system --no-sandbox", "../system"})
    assert(!metabrowser::ValidPlatformVersionPolicy(bad));
  std::cout << "PASS: canonical major/system choices, explicit native restoration, invalid input cannot reveal details\n";
}
