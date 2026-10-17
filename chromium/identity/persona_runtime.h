// Copyright 2026 MetaBrowser Authors. BSD-3-Clause.
#ifndef THIRD_PARTY_BLINK_PUBLIC_COMMON_USER_AGENT_METABROWSER_PERSONA_RUNTIME_H_
#define THIRD_PARTY_BLINK_PUBLIC_COMMON_USER_AGENT_METABROWSER_PERSONA_RUNTIME_H_

#include "base/check.h"
#include "base/command_line.h"
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
}  // namespace metabrowser
#endif
