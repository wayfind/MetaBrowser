// Copyright 2026 MetaBrowser Authors. BSD-3-Clause.
#ifndef THIRD_PARTY_BLINK_PUBLIC_COMMON_USER_AGENT_METABROWSER_PERSONA_RUNTIME_H_
#define THIRD_PARTY_BLINK_PUBLIC_COMMON_USER_AGENT_METABROWSER_PERSONA_RUNTIME_H_

#include "base/check.h"
#include "base/command_line.h"
#include "base/system/sys_info.h"
#include "third_party/blink/public/common/user_agent/metabrowser_persona.h"

namespace metabrowser {
inline bool ValidPersonaCommandLine(const base::CommandLine& command) {
  const auto selector = command.GetSwitchValueASCII(kPersonaTemplateSwitch);
  return ValidPersonaLaunch({command.HasSwitch(kPersonaTemplateSwitch), selector,
      !command.GetSwitchValueASCII("type").empty(), command.HasSwitch("user-agent"),
      command.GetSwitchValueASCII("use-gl") == "angle" &&
          command.GetSwitchValueASCII("use-angle") == "swiftshader",
      command.GetSwitchValueASCII("use-webgpu-adapter") == "swiftshader",
      command.HasSwitch("disable-accelerated-video-decode"),
      command.HasSwitch("disable-accelerated-video-encode")});
}
// All values are public cohort choices, never an identity root or a site token.
// No implicit native fallback for a nonempty invalid selector. Profile UI only
// launches user_selectable templates; experimental selectors are explicit QA.
inline const Persona* EmulatedPersona() {
  if (!base::CommandLine::InitializedForCurrentProcess()) return nullptr;
  const auto* command = base::CommandLine::ForCurrentProcess();
  CHECK(ValidPersonaCommandLine(*command)) << "Invalid identity template configuration";
  const auto selector = command->GetSwitchValueASCII(kPersonaTemplateSwitch);
  const auto* persona = FindPersona(selector);
  CHECK(persona) << "Unsupported identity template";
  if (!persona->override_metadata) return nullptr;
  return persona;
}

// Protected identities expose one device class to script and to Client Hints.
// hardwareConcurrency is bucketed down to 1/2/4/8 cores (navigator_base.cc);
// device memory follows that class at 2 GiB per bucketed core and never exceeds
// the host's approximated value, so 8 cores pair with at most 16 GiB.
constexpr unsigned ProtectedCoreBucket(unsigned cores) {
  return cores >= 8 ? 8 : cores >= 4 ? 4 : cores >= 2 ? 2 : 1;
}
inline float ProtectedDeviceMemory(float approximated) {
  const auto* persona = EmulatedPersona();
  const unsigned cores = persona ? persona->cores
      : static_cast<unsigned>(base::SysInfo::NumberOfProcessors());
  const float cap = 2.0f * ProtectedCoreBucket(cores);
  return approximated < cap ? approximated : cap;
}
// NetworkInformation and the ECT/RTT/Downlink hints of protected identities: a
// common fast-connection cohort after Chrome's own rounding (RTT to 50 ms,
// downlink capped at 10 Mbps), never the physical estimate or its changes.
inline constexpr unsigned kProtectedRttMs = 50;
inline constexpr double kProtectedDownlinkMbps = 10.0;
}  // namespace metabrowser
#endif
