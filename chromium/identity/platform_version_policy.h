// Copyright 2026 MetaBrowser Authors. BSD-3-Clause.
#ifndef COMPONENTS_METABROWSER_IDENTITY_PLATFORM_VERSION_POLICY_H_
#define COMPONENTS_METABROWSER_IDENTITY_PLATFORM_VERSION_POLICY_H_
#include <string>
#include <string_view>

namespace metabrowser {
inline constexpr std::string_view kPlatformVersionPolicySwitch =
    "metabrowser-platform-version-policy";
inline bool ValidPlatformVersionPolicy(std::string_view value) {
  return value == "major" || value == "system";
}
// Identity metadata is separate from pixel/noise policy, like language/TZ.
// Empty/unknown command-line input retains the privacy-preserving default.
inline std::string ApplyPlatformVersionPolicy(std::string_view native,
                                               std::string_view policy) {
  if (policy == "system") return std::string(native);
  const auto major = native.substr(0, native.find('.'));
  if (major.empty() || major.size() > 9 ||
      major.find_first_not_of("0123456789") != std::string_view::npos)
    return std::string();
  return std::string(major) + ".0.0";
}
}  // namespace metabrowser
#endif
