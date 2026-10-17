// Copyright 2026 MetaBrowser Authors. BSD-3-Clause.
#ifndef THIRD_PARTY_BLINK_PUBLIC_COMMON_USER_AGENT_METABROWSER_PERSONA_H_
#define THIRD_PARTY_BLINK_PUBLIC_COMMON_USER_AGENT_METABROWSER_PERSONA_H_

#include <string_view>

namespace metabrowser {
inline constexpr char kPersonaTemplateSwitch[] = "metabrowser-persona-template";
enum class PersonaGpuBackend { kNative, kSwiftShader };
// Vector math is one DSP layer; FFT, resampling and devices have separate work.
enum class PersonaAudioVectorBackend { kNative, kScalar };
enum class PersonaFftBackend { kNative, kScalarFdlibm };
struct Persona {
  const char* id;
  bool override_metadata;
  bool user_selectable;
  const char* ua_prefix;
  const char* ua_os_cpu;
  const char* ua_unified;
  const char* navigator_platform;
  const char* ch_platform;
  const char* ch_platform_version;
  const char* architecture;
  const char* bitness;
  unsigned cores;
  float memory_gib;
  PersonaGpuBackend gpu_backend;
  PersonaAudioVectorBackend audio_vector_backend;
  PersonaFftBackend fft_backend;
};

inline constexpr Persona kNativePersona{
    "native-macos-arm64-v1", false, true, "", "", "", "", "", "", "", "", 0, 0,
    PersonaGpuBackend::kNative, PersonaAudioVectorBackend::kNative,
    PersonaFftBackend::kNative};
// Linux UA-CH platformVersion is intentionally empty in the pinned source and
// real Linux reference. It is not a Linux kernel version or the Mac host OS.
// This is an executable metadata prototype, not a validated complete persona:
// fonts, Math, platform API surface and full media/rendering still need proof.
inline constexpr Persona kLinuxSoftwarePersona{
    "linux-x86_64-software-v1", true, false, "X11; ", "Linux x86_64",
    "X11; Linux x86_64", "Linux x86_64", "Linux", "", "x86", "64", 8, 8,
    PersonaGpuBackend::kSwiftShader, PersonaAudioVectorBackend::kScalar,
    PersonaFftBackend::kScalarFdlibm};

constexpr const Persona* FindPersona(std::string_view id) {
  if (id.empty() || id == "native" || id == kNativePersona.id)
    return &kNativePersona;
  if (id == kLinuxSoftwarePersona.id) return &kLinuxSoftwarePersona;
  return nullptr;
}
constexpr bool UserSelectablePersona(std::string_view id) {
  const auto* persona = FindPersona(id);
  return persona && id == persona->id && persona->user_selectable;
}
struct PersonaLaunchOptions {
  bool selector_present;
  std::string_view selector;
  bool child_process;
  bool custom_user_agent;
  bool software_angle;
  bool software_webgpu;
  bool software_video_decode;
  bool software_video_encode;
};
constexpr bool ValidPersonaLaunch(const PersonaLaunchOptions& options) {
  if (options.selector_present && options.selector.empty()) return false;
  const auto* persona = FindPersona(options.selector);
  if (!persona) return false;
  if (!persona->override_metadata) return true;
  if (options.custom_user_agent) return false;
  if (options.child_process) return true;  // Browser validates actual backends.
  return persona->gpu_backend == PersonaGpuBackend::kSwiftShader &&
         options.software_angle && options.software_webgpu &&
         options.software_video_decode && options.software_video_encode;
}
}  // namespace metabrowser
#endif
