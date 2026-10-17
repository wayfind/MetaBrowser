#include <cassert>
#include <string>
#include <string_view>
#include "chromium/identity/persona.h"
#include "chromium/privacy/metabrowser_cpu_identity.h"

int main() {
  using namespace metabrowser;
  static_assert(FindPersona("") == &kNativePersona);
  static_assert(FindPersona("native") == &kNativePersona);
  static_assert(UserSelectablePersona("native-macos-arm64-v1"));
  static_assert(!UserSelectablePersona("native"));
  static_assert(!UserSelectablePersona("linux-x86_64-software-v1"));
  static_assert(FindPersona("windows-unvalidated") == nullptr);
  static_assert(FindPersona(" linux-x86_64-software-v1") == nullptr);
  static_assert(FindPersona("../native") == nullptr);
  static_assert(FindPersona(std::string_view("native\0junk", 11)) == nullptr);
  const auto* linux_persona = FindPersona("linux-x86_64-software-v1");
  assert(linux_persona && linux_persona->override_metadata && !linux_persona->user_selectable);
  assert(std::string(linux_persona->ua_prefix) + linux_persona->ua_os_cpu == linux_persona->ua_unified);
  assert(std::string_view(linux_persona->navigator_platform) == "Linux x86_64");
  assert(std::string_view(linux_persona->ch_platform) == "Linux");
  assert(std::string_view(linux_persona->ch_platform_version).empty());
  assert(std::string_view(linux_persona->architecture) == "x86" && std::string_view(linux_persona->bitness) == "64");
  assert(linux_persona->cores == 8 && linux_persona->memory_gib == 8);
  assert(linux_persona->gpu_backend == PersonaGpuBackend::kSwiftShader);
  static_assert(kNativePersona.audio_vector_backend == PersonaAudioVectorBackend::kNative);
  assert(linux_persona->audio_vector_backend == PersonaAudioVectorBackend::kScalar);
  static_assert(kNativePersona.fft_backend == PersonaFftBackend::kNative);
  assert(linux_persona->fft_backend == PersonaFftBackend::kScalarFdlibm);
  static_assert(blink::MetaBrowserCpuTierForPublicTemplate(8, false) == 3);
  static_assert(blink::MetaBrowserCpuTierForPublicTemplate(8, true) == 4);
  constexpr PersonaLaunchOptions valid{true, "linux-x86_64-software-v1", false,
                                     false, true, true, true, true};
  static_assert(ValidPersonaLaunch(valid));
  auto invalid = valid;
  invalid.selector = "unknown"; assert(!ValidPersonaLaunch(invalid));
  invalid = valid; invalid.selector = ""; assert(!ValidPersonaLaunch(invalid));
  invalid = valid; invalid.custom_user_agent = true; assert(!ValidPersonaLaunch(invalid));
  invalid = valid; invalid.software_angle = false; assert(!ValidPersonaLaunch(invalid));
  invalid = valid; invalid.software_webgpu = false; assert(!ValidPersonaLaunch(invalid));
  invalid = valid; invalid.software_video_decode = false; assert(!ValidPersonaLaunch(invalid));
  invalid = valid; invalid.software_video_encode = false; assert(!ValidPersonaLaunch(invalid));
}
