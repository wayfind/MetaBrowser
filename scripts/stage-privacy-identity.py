#!/usr/bin/env python3
"""Stage one native platform-version policy shared by UI and UA/CH source."""
import argparse
import hashlib
import json
import re
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('--apply',action='store_true');a=p.parse_args()
root=a.source.resolve(strict=True);project=Path(__file__).resolve().parents[1]
assert (root/'chrome/VERSION').read_text().splitlines()==['MAJOR=154','MINOR=0','BUILD=8037','PATCH=97']
original,changes={},{}

def read(name):
    path=root/name
    assert not path.is_symlink() and path.resolve().is_relative_to(root)
    if name not in original:original[name]=path.read_text() if path.exists() else None
    return changes.get(name,original[name])

def edit(name,old,new,previous=None):
    text=read(name);assert text is not None
    if new in text:assert text.count(new)==1
    elif previous is not None and previous in text:
        assert text.count(previous)==1;text=text.replace(previous,new,1)
    else:
        if text.count(old)!=1:raise SystemExit('Pinned identity source drift: '+name+': '+old[:80])
        text=text.replace(old,new,1)
    changes[name]=text

for filename in ['BUILD.gn','platform_version_policy.h']:
    name='components/metabrowser_identity/'+filename;read(name);changes[name]=(project/'chromium/identity'/filename).read_text()
for filename,public_name in [('persona.h','metabrowser_persona.h'),('persona_runtime.h','metabrowser_persona_runtime.h')]:
    name='third_party/blink/public/common/user_agent/'+public_name;read(name)
    changes[name]=(project/'chromium/identity'/filename).read_text()
edit('third_party/blink/public/common/BUILD.gn',
     '    "user_agent/user_agent_metadata.h",',
     '''    "user_agent/user_agent_metadata.h",
    "user_agent/metabrowser_persona.h",
    "user_agent/metabrowser_persona_runtime.h",''')
name='components/embedder_support/BUILD.gn';text=read(name);start=text.index('static_library("user_agent") {');end=text.index('\n}\n',start)+2;block=text[start:end]
old='  deps = [\n    ":embedder_support",';new='  deps = [\n    "//components/metabrowser_identity:metadata",\n    ":embedder_support",'
if new not in block:
    assert block.count(old)==1;block=block.replace(old,new,1)
assert block.count(new)==1;changes[name]=text[:start]+block+text[end:]
edit('components/embedder_support/user_agent_utils.cc',
     '#include "components/embedder_support/user_agent_utils.h"',
     '#include "components/embedder_support/user_agent_utils.h"\n#include "components/metabrowser_identity/platform_version_policy.h"')
runtime_include='#include "third_party/blink/public/common/user_agent/metabrowser_persona_runtime.h"'
def include(name,line):
    text=read(name)
    if line in text.splitlines():assert text.splitlines().count(line)==1;return
    anchor=next(s for s in text.splitlines() if s.startswith('#include "'))
    edit(name,anchor,anchor+'\n'+line)

include('components/embedder_support/user_agent_utils.cc',runtime_include)
include('chrome/app/chrome_main_delegate.cc',runtime_include)
edit('chrome/app/chrome_main_delegate.cc',
     'std::optional<int> ChromeMainDelegate::BasicStartupComplete() {',
     '''std::optional<int> ChromeMainDelegate::BasicStartupComplete() {
  // Reject incompatible public identity arguments before profile/site startup.
  if (!metabrowser::ValidPersonaCommandLine(
          *base::CommandLine::ForCurrentProcess())) {
    LOG(ERROR) << "Invalid identity template configuration.";
    return CHROME_RESULT_CODE_UNSUPPORTED_PARAM;
  }''')
edit('components/embedder_support/user_agent_utils.cc','std::string GetUserAgent() {',
     '''std::string GetUserAgent() {
  // Validate the public selector before even a custom UA can be emitted.
  (void)metabrowser::EmulatedPersona();''')
for signature,field in [
    ('std::string GetUserAgentPlatform() {','ua_prefix'),
    ('std::string GetUnifiedPlatform() {','ua_unified'),
    ('std::string GetPlatformForUAMetadata() {','ch_platform'),
    ('std::string GetPlatformVersion() {','ch_platform_version'),
    ('std::string GetCpuArchitecture() {','architecture'),
    ('std::string GetCpuBitness() {','bitness')]:
    edit('components/embedder_support/user_agent_utils.cc',signature,
         signature+'\n  if (const auto* persona = metabrowser::EmulatedPersona())\n    return persona->'+field+';')
signature='''std::string BuildOSCpuInfoFromOSVersionAndCpuType(const std::string& os_version,
                                                  const std::string& cpu_type) {'''
edit('components/embedder_support/user_agent_utils.cc',signature,
     signature+'\n  if (const auto* persona = metabrowser::EmulatedPersona())\n    return persona->ua_os_cpu;')
edit('components/embedder_support/user_agent_utils.cc',
     'std::string BuildModelInfo() {',
     '''std::string BuildModelInfo() {
  if (metabrowser::EmulatedPersona()) return {};''')
edit('components/embedder_support/user_agent_utils.cc',
     '  metadata.platform_version = GetPlatformVersion();',
     '''  metadata.platform_version = GetPlatformVersion();
#if BUILDFLAG(IS_MAC)
  // METABROWSER_IDENTITY_VERSION_V1: shared HTTP/renderer/worker metadata.
  metadata.platform_version = metabrowser::ApplyPlatformVersionPolicy(
      metadata.platform_version,
      base::CommandLine::ForCurrentProcess()->GetSwitchValueASCII(
          metabrowser::kPlatformVersionPolicySwitch));
#endif''')
edit('chrome/browser/chrome_content_browser_client.cc',
     '  static const char* const kCommonSwitchNames[] = {\n      embedder_support::kUserAgent,',
     '''  static const char* const kCommonSwitchNames[] = {
      // Public identity choice only; never a root secret or derived token.
      "metabrowser-platform-version-policy",
      "metabrowser-persona-template",
      embedder_support::kUserAgent,''',previous='''  static const char* const kCommonSwitchNames[] = {
      // Public identity choice only; never a root secret or derived token.
      "metabrowser-platform-version-policy",
      embedder_support::kUserAgent,''')
name='third_party/blink/renderer/core/frame/navigator_id.cc';include(name,runtime_include)
edit(name,'String NavigatorID::platform() const {',
     '''String NavigatorID::platform() const {
  if (const auto* persona = metabrowser::EmulatedPersona())
    return String(persona->navigator_platform);''')
name='third_party/blink/renderer/core/execution_context/navigator_base.cc';include(name,runtime_include)
edit(name,'String NavigatorBase::platform() const {',
     '''String NavigatorBase::platform() const {
  // UA reduction bypasses NavigatorID::platform on desktop and workers.
  if (const auto* persona = metabrowser::EmulatedPersona())
    return String(persona->navigator_platform);''')
edit(name,'''  unsigned int hardware_concurrency =
      NavigatorConcurrentHardware::hardwareConcurrency();''',
     '''  const auto* persona = metabrowser::EmulatedPersona();
  unsigned int hardware_concurrency = persona ? persona->cores :
      NavigatorConcurrentHardware::hardwareConcurrency();''')
name='third_party/blink/common/device_memory/approximated_device_memory.cc';include(name,runtime_include)
edit(name,'float ApproximatedDeviceMemory::GetApproximatedDeviceMemory() {',
     '''float ApproximatedDeviceMemory::GetApproximatedDeviceMemory() {
  if (const auto* persona = metabrowser::EmulatedPersona()) return persona->memory_gib;''')
name='third_party/blink/renderer/platform/audio/vector_math.cc'
include(name,runtime_include)
edit(name,'#include "base/compiler_specific.h"',
     '''#include "base/compiler_specific.h"
// Explicit scalar backend is needed even on platforms with native SIMD/vDSP.
#include "third_party/blink/renderer/platform/audio/vector_math_scalar.h"''')
audio_backend_helper='''namespace {
bool MetaBrowserScalarAudioVectorMath() {
  // A pre-init library call must not permanently cache a native fallback.
  if (!base::CommandLine::InitializedForCurrentProcess()) return false;
  // Process command line is immutable. Cache selection to avoid allocating
  // strings or consulting platform settings on the realtime audio thread.
  static const bool scalar = [] {
    const auto* persona = metabrowser::EmulatedPersona();
    return persona && persona->audio_vector_backend ==
        metabrowser::PersonaAudioVectorBackend::kScalar;
  }();
  return scalar;
}
#if BUILDFLAG(IS_MAC)'''
edit(name,'namespace {\n#if BUILDFLAG(IS_MAC)',audio_backend_helper,
     previous=audio_backend_helper.replace(
         '  // A pre-init library call must not permanently cache a native fallback.\n'
         '  if (!base::CommandLine::InitializedForCurrentProcess()) return false;\n',''))
# Each existing wrapper has one implementation call; Vclip has two overloads.
# Keep native defaults and signatures intact, including aliasing and prepared
# convolution storage. This dispatches actual DSP, never a readback facade.
text=read(name)
calls=re.findall(r'impl::(\w+)\(([^;]+)\);',text)
expected=['Conv','Vadd','Vsub','Vclip','Vclip','Vmaxmgv','Vmul','Vsma','Vsmul','Vsadd','Vsvesq','Zvmul']
assert [method for method,args in calls]==expected,'Pinned audio vector call drift'
for method,args in calls:
    old='impl::'+method+'('+args+');'
    new='if (MetaBrowserScalarAudioVectorMath()) {\n    scalar::'+method+'('+args+');\n  } else {\n    '+old+'\n  }'
    if new not in read(name):edit(name,old,new)
# Inline production implementations must be bound by the build receipt too.
# They are read-only upstream dependencies, not authored replacement DSP.
for name in ('third_party/blink/renderer/platform/audio/vector_math.h',
             'third_party/blink/renderer/platform/audio/vector_math_scalar.h',
             'third_party/blink/renderer/platform/audio/mac/vector_math_mac.h'):
    changes[name]=read(name)
for name,before in original.items():
    path=root/name;assert (path.read_text() if path.exists() else None)==before,'Source changed during preflight'
if a.apply:
    for name,text in changes.items():
        if text!=original[name]:
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
print(json.dumps({'scope':'native-platform-version-source-and-child-propagation','applied':a.apply,'all_files':{n:hashlib.sha256(t.encode()).hexdigest() for n,t in changes.items()}}))
