#!/usr/bin/env python3
"""Stage pinned, token-gated macOS privacy surfaces; preview by default.

No page JS, provider configuration, seed generation, network or build actions.
All edits are preflighted before writing. Existing patches must match exactly.
"""
import argparse
import hashlib
import json
from pathlib import Path

HEADER = 'third_party/blink/renderer/core/canvas_interventions/metabrowser_surface_privacy.h'
CORE = 'third_party/blink/renderer/core/'
MODULES = 'third_party/blink/renderer/modules/'
MARKER = '// METABROWSER_MAC_PRIVACY_V1: '


def make_plan(root):
    original, result = {}, {}

    def read(path):
        target = root / path
        if target.is_symlink() or not target.resolve().is_relative_to(root):
            raise ValueError('Source path escapes checkout: ' + path)
        if path not in original:
            original[path] = target.read_text()
            result[path] = original[path]
        return result[path]

    def edit(path, anchor, replacement, tag, previous=None):
        text = read(path)
        marker = MARKER.replace('//', '#', 1) if path.endswith(('.gn', '.gni')) else MARKER
        value = marker + tag + '\n' + replacement
        # A legacy replacement may be a prefix of the current value. Check the
        # complete current form first or every staging pass appends it again.
        if value in text:
            if text.count(value) != 1:
                raise ValueError('Duplicate patch: ' + tag)
            return
        for prior in ((previous,) if isinstance(previous, str) else (previous or ())):
            if marker + tag + '\n' + prior in text:
                old = marker + tag + '\n' + prior
                if text.count(old) != 1:
                    raise ValueError('Duplicate previous patch: ' + tag)
                result[path] = text.replace(old, value, 1)
                return
        legacy = MARKER + tag + '\n' + replacement
        if marker != MARKER and legacy in text:
            if text.count(legacy) != 1:
                raise ValueError('Duplicate legacy marker: ' + tag)
            result[path] = text.replace(legacy, value, 1)
            return
        if marker + tag in text or text.count(anchor) != 1:
            raise ValueError('Pinned source drift: ' + path + ': ' + tag)
        result[path] = text.replace(anchor, value, 1)

    def include(path):
        text = read(path)
        line = '#include "' + HEADER + '"'
        if line in text.splitlines():
            if text.splitlines().count(line) != 1:
                raise ValueError('Duplicate surface header: ' + path)
            return
        anchor = next(line for line in text.splitlines() if line.startswith('#include "'))
        edit(path, anchor, anchor + '\n#include "' + HEADER + '"', 'surface-header')

    # Both Navigator and WorkerNavigator share this implementation. Preserve
    # inspector overrides after reducing the unmodified platform value.
    path = CORE + 'execution_context/navigator_base.cc'
    include(path)
    old_cpu = '''  if (MetaBrowserSurfaceProtected(GetExecutionContext())) {
    // Bucket down; never advertise a greater scheduling capacity than the host.
    hardware_concurrency = hardware_concurrency >= 8 ? 8 :
        hardware_concurrency >= 4 ? 4 : hardware_concurrency >= 2 ? 2 : 1;
  }
  probe::ApplyHardwareConcurrencyOverride('''
    edit(path, '  probe::ApplyHardwareConcurrencyOverride(',
         old_cpu.replace('MetaBrowserSurfaceProtected(GetExecutionContext())',
                         'MetaBrowserProtectedIdentity()'),
         'cpu-buckets', previous=old_cpu)
    edit(path,
         '    : NavigatorLanguage(context), ExecutionContextClient(context) {}',
         '''    : NavigatorLanguage(context), ExecutionContextClient(context),
      metabrowser_protected_identity_(MetaBrowserSurfaceProtected(context)) {}''',
         'navigator-owner-policy')
    path = CORE + 'execution_context/navigator_base.h'
    edit(path, '  unsigned int hardwareConcurrency() const override;',
         '''  unsigned int hardwareConcurrency() const override;
  // Capture the owning context's policy before it can be detached. Retained
  // Navigator objects must not reopen native CPU information after teardown.
  bool MetaBrowserProtectedIdentity() const {
    return metabrowser_protected_identity_;
  }''', 'navigator-owner-policy-api')
    edit(path, '  UserAgentMetadata GetUserAgentMetadata() const override;',
         '''  UserAgentMetadata GetUserAgentMetadata() const override;

 private:
  const bool metabrowser_protected_identity_;''', 'navigator-owner-policy-state')
    # Hides NavigatorDeviceMemory::deviceMemory for Navigator and WorkerNavigator
    # bindings, like hardwareConcurrency above, so both report one device class.
    edit(path, '  void Trace(Visitor* visitor) const override;',
         '''  float deviceMemory() const;
  void Trace(Visitor* visitor) const override;''', 'navigator-device-memory-api')
    path = CORE + 'execution_context/navigator_base.cc'
    edit(path, 'ExecutionContext* NavigatorBase::GetUAExecutionContext() const {',
         '''float NavigatorBase::deviceMemory() const {
  const float memory = NavigatorDeviceMemory::deviceMemory();
  // Same device class as hardwareConcurrency; never above the host.
  return MetaBrowserProtectedIdentity()
      ? metabrowser::ProtectedDeviceMemory(memory) : memory;
}

ExecutionContext* NavigatorBase::GetUAExecutionContext() const {''',
         'navigator-device-memory-class')
    path = CORE + 'frame/navigator_cpu_performance.cc'
    edit(path,
         '#include "third_party/blink/renderer/core/frame/navigator_cpu_performance.h"',
         '#include "third_party/blink/renderer/core/frame/navigator_cpu_performance.h"\n'
         '#include "build/build_config.h"\n'
         '#include "third_party/blink/renderer/core/canvas_interventions/metabrowser_cpu_identity.h"\n'
         '#include "third_party/blink/public/common/user_agent/metabrowser_persona_runtime.h"',
         'cpu-template-policy-include',previous=
         '#include "third_party/blink/renderer/core/frame/navigator_cpu_performance.h"\n'
         '#include "build/build_config.h"\n'
         '#include "third_party/blink/renderer/core/canvas_interventions/metabrowser_cpu_identity.h"')
    edit(path,
         'uint16_t NavigatorCPUPerformance::cpuPerformance(Navigator& navigator) {',
         '''uint16_t NavigatorCPUPerformance::cpuPerformance(Navigator& navigator) {
  if (metabrowser::EmulatedPersona())
    return MetaBrowserCpuTierForPublicTemplate(navigator.hardwareConcurrency(), false);
  // Use the public core bucket and the current native template, not a private
  // CPU model probe. A fixed Mid tier contradicts the Apple M-series cohort.
  if (navigator.MetaBrowserProtectedIdentity()) {
#if BUILDFLAG(IS_MAC) && defined(ARCH_CPU_ARM64)
    constexpr bool apple_m_series_template = true;
#else
    constexpr bool apple_m_series_template = false;
#endif
    return MetaBrowserCpuTierForPublicTemplate(
        navigator.hardwareConcurrency(), apple_m_series_template);
  }''',
         'cpu-performance-tier', previous=('''uint16_t NavigatorCPUPerformance::cpuPerformance(Navigator& navigator) {
  // Use the public core bucket and the current native template, not a private
  // CPU model probe. A fixed Mid tier contradicts the Apple M-series cohort.
  if (navigator.MetaBrowserProtectedIdentity()) {
#if BUILDFLAG(IS_MAC) && defined(ARCH_CPU_ARM64)
    constexpr bool apple_m_series_template = true;
#else
    constexpr bool apple_m_series_template = false;
#endif
    return MetaBrowserCpuTierForPublicTemplate(
        navigator.hardwareConcurrency(), apple_m_series_template);
  }''','''uint16_t NavigatorCPUPerformance::cpuPerformance(Navigator& navigator) {
  // Generic middle tier, independent of the device, platform probe and
  // optional feature activation. Explicit unprotected contexts stay native.
  if (navigator.MetaBrowserProtectedIdentity()) return 2;'''))

    path = 'chrome/browser/renderer_preferences_util.cc'
    edit(path, '#include "base/logging.h"',
         '#include "base/logging.h"\n#include "base/command_line.h"\n'
         '#include "metabrowser/privacy_context.h"', 'webrtc-policy-includes')
    anchor = '''  prefs->webrtc_ip_handling_policy = blink::ToWebRTCIPHandlingPolicy(
      pref_service->GetString(prefs::kWebRTCIPHandlingPolicy));'''
    edit(path, anchor, anchor + '''
  // Native allocator policy: this controls actual ICE gathering, not just the
  // candidate strings delivered to JS. Respect managed/explicit upstream prefs.
  const auto* command = base::CommandLine::ForCurrentProcess();
  if (pref_service->GetBoolean(metabrowser::kPrivacyEnabledPref) &&
      command->GetSwitchValueASCII("metabrowser-privacy") != "off" &&
      pref_service->FindPreference(prefs::kWebRTCIPHandlingPolicy)->IsDefaultValue()) {
    auto policy = command->GetSwitchValueASCII("metabrowser-webrtc-policy");
    if (policy.empty()) policy = "default_public_interface_only";
    if (policy == "default_public_interface_only" ||
        policy == "disable_non_proxied_udp") {
      prefs->webrtc_ip_handling_policy = blink::ToWebRTCIPHandlingPolicy(policy);
    }
  }''', 'webrtc-allocator-policy')

    # Keep downloaded/ArrayBuffer web fonts usable. Restrict only the implicit
    # system-family lookup after the web-font cache has been consulted.
    for path in (CORE + 'css/css_font_selector.cc', CORE + 'css/offscreen_font_selector.cc'):
        include(path)
        edit(path, '  if (settings_family_name.empty()) {',
             '  if (settings_family_name.empty() ||\n'
             '      !MetaBrowserFontVisible(GetExecutionContext(), settings_family_name)) {',
             'system-font-visibility')
    path = CORE + 'css/css_font_selector_base.cc'
    include(path)
    edit(path, '  return FontCache::Get().IsPlatformFamilyMatchAvailable(font_description,',
         '  if (!MetaBrowserFontVisible(GetExecutionContext(), family)) return false;\n'
         '  return FontCache::Get().IsPlatformFamilyMatchAvailable(font_description,',
         'font-check-visibility')
    path = CORE + 'css/local_font_face_source.cc'
    include(path)
    edit(path, '  // TODO(crbug.com/1025945): Properly handle Windows prior to 10 and Android.',
         '  if (!MetaBrowserFontVisible(font_selector_->GetExecutionContext(), font_name_))\n'
         '    return false;\n'
         '  // TODO(crbug.com/1025945): Properly handle Windows prior to 10 and Android.',
         'local-font-visibility')

    # The adapter and GPUDevice.adapterInfo use the same factory. Developer
    # flags must not reopen driver/device/memory identifiers for protected sites.
    path = MODULES + 'webgpu/gpu_adapter.cc'
    include(path)
    edit(path, '  wgpu::AdapterInfo info = {};',
         '  metabrowser_protected_ = MetaBrowserSurfaceProtected(gpu_->GetExecutionContext());\n'
         '  wgpu::AdapterInfo info = {};', 'gpu-policy-lifetime')
    # Filter the canonical feature set, not just its JS iterator. requestDevice
    # validates requiredFeatures against this same set, including developer
    # flags; retained adapters keep the policy captured at their creation.
    edit(path, 'GPUSupportedFeatures* MakeFeatureNameSet(wgpu::Adapter adapter) {',
         'GPUSupportedFeatures* MakeFeatureNameSet(wgpu::Adapter adapter,\n'
         '                                          bool protected_context) {',
         'gpu-feature-policy-parameter')
    # timestamp-query and subgroups ship on every Apple Silicon Chrome 154, so
    # hiding them marks the browser. Only developer-flag features stay hidden.
    old_features = '''  for (const auto& f : features_span) {
    if (protected_context &&
        (f == wgpu::FeatureName::TimestampQuery ||
         f == wgpu::FeatureName::ChromiumExperimentalTimestampQueryInsidePasses ||
         f == wgpu::FeatureName::Subgroups ||
         f == wgpu::FeatureName::ChromiumExperimentalSubgroupMatrix)) {
      continue;
    }'''
    edit(path, '  for (const auto& f : features_span) {', '''  for (const auto& f : features_span) {
    if (protected_context &&
        (f == wgpu::FeatureName::ChromiumExperimentalTimestampQueryInsidePasses ||
         f == wgpu::FeatureName::ChromiumExperimentalSubgroupMatrix)) {
      continue;
    }''', 'gpu-sensitive-optional-features', previous=old_features)
    edit(path, '  features_ = MakeFeatureNameSet(GetHandle());',
         '  features_ = MakeFeatureNameSet(GetHandle(), metabrowser_protected_);',
         'gpu-feature-policy-capture')
    # Subgroup widths travel with the restored subgroups feature (32 on all
    # Apple Silicon); the tag keeps its name so earlier staging migrates.
    edit(path, '  subgroup_max_size_ = info.subgroupMaxSize;',
         '  subgroup_max_size_ = info.subgroupMaxSize;\n'
         '  // Widths are a GPU-family constant and stay with the subgroups feature.',
         'gpu-no-disabled-subgroup-widths', previous=(
             '  subgroup_max_size_ = info.subgroupMaxSize;\n'
             '  if (metabrowser_protected_) {\n'
             '    subgroup_min_size_ = 0;\n'
             '    subgroup_max_size_ = 0;\n'
             '  }'))
    edit(path, '  GPUAdapterInfo* info;\n', '''  if (metabrowser_protected_) {
    // Every Apple Silicon GPU reports one architecture ("metal-3"); other
    // vendors keep it empty until a template supplies a cohort value.
    return MakeGarbageCollected<GPUAdapterInfo>(
        vendor_, vendor_ == "apple" ? architecture_ : String(),
        subgroup_min_size_, subgroup_max_size_, is_fallback_adapter);
  }
  GPUAdapterInfo* info;
''', 'gpu-adapter-identifiers', previous='''  if (metabrowser_protected_) {
    return MakeGarbageCollected<GPUAdapterInfo>(
        vendor_, String(), subgroup_min_size_, subgroup_max_size_,
        is_fallback_adapter);
  }
  GPUAdapterInfo* info;
''')
    # Freeze policy at creation. A detached owning context must not reopen info.
    path = MODULES + 'webgpu/gpu_adapter.h'
    edit(path, '  Member<GPU> gpu_;',
         '  bool metabrowser_protected_ = false;\n  Member<GPU> gpu_;',
         'gpu-policy-field')

    # Inherit the owning context's browser-derived token, including null/off.
    # Never mint a global token for worklets with no owning document.
    path = CORE + 'workers/threaded_worklet_messaging_proxy.cc'
    edit(path, '  // Worklets share the pre-initialized backing thread so that we don\'t have to',
         '  if (window->CanvasNoiseToken())\n'
         '    global_scope_creation_params->metabrowser_privacy_token =\n'
         '        window->CanvasNoiseToken()->Value();\n\n'
         '  // Worklets share the pre-initialized backing thread so that we don\'t have to',
         'threaded-worklet-inherit')
    path = MODULES + 'csspaint/paint_worklet_global_scope_proxy.cc'
    edit(path, '  global_scope_ = PaintWorkletGlobalScope::Create(',
         '  if (window->CanvasNoiseToken())\n'
         '    creation_params->metabrowser_privacy_token = window->CanvasNoiseToken()->Value();\n'
         '  global_scope_ = PaintWorkletGlobalScope::Create(', 'main-worklet-inherit')
    path = CORE + 'workers/worklet_global_scope.cc'
    edit(path, '  DCHECK((thread_type_ == ThreadType::kMainThread && frame_) ||',
         '  SetCanvasNoiseToken(creation_params->metabrowser_privacy_token\n'
         '      ? std::make_optional(NoiseToken(*creation_params->metabrowser_privacy_token))\n'
         '      : std::nullopt);\n'
         '  DCHECK((thread_type_ == ThreadType::kMainThread && frame_) ||',
         'worklet-consume')

    # Analyse copies only, with matching float/byte conversions. Untouched tails,
    # non-finite values and silence retain upstream behavior. The graph, playback
    # and live microphone samples are not modified.
    path = MODULES + 'webaudio/analyser_node.cc'
    include(path)
    edit(path, '#include "third_party/blink/renderer/modules/webaudio/analyser_node.h"',
         '#include "third_party/blink/renderer/modules/webaudio/analyser_node.h"\n'
         '#include <algorithm>\n#include <cmath>', 'analyser-stdlib')
    for frequency, method in ((True, 'Frequency'), (False, 'TimeDomain')):
        original_call = ('  GetAnalyserHandler().GetFloatFrequencyData(array.Get(),\n'
                         '                                             context()->currentTime());' if frequency else
                         '  GetAnalyserHandler().GetFloatTimeDomainData(array.Get());')
        replacement = original_call + '''
  auto* execution_context = context()->GetExecutionContext();
  if (MetaBrowserSurfaceProtected(execution_context)) {
    auto values = array->AsSpan();
    const size_t count = std::min<size_t>(values.size(), ''' + ('frequencyBinCount()' if frequency else 'fftSize()') + ''');
    for (size_t i = 0; i < count; ++i)
      values[i] = MetaBrowserAnalyserSample(values[i],
          execution_context->CanvasNoiseToken()->Value(), i, ''' + ('true' if frequency else 'false') + ''');
  }'''
        edit(path, original_call, replacement, 'analyser-float-' + method)
        byte_call = ('  GetAnalyserHandler().GetByteFrequencyData(array.Get(),\n'
                     '                                            context()->currentTime());' if frequency else
                     '  GetAnalyserHandler().GetByteTimeDomainData(array.Get());')
        conversion = ('''      const double scaled = 255.0 * (values[i] - minDecibels()) /
          (maxDecibels() - minDecibels());''' if frequency else
                      '''      const double scaled = 128.0 * (1.0 + values[i]);''')
        replacement = '''  if (MetaBrowserSurfaceProtected(context()->GetExecutionContext())) {
    const size_t count = std::min<size_t>(array->length(), ''' + ('frequencyBinCount()' if frequency else 'fftSize()') + ''');
    auto floats = NotShared<DOMFloat32Array>(DOMFloat32Array::Create(count));
    getFloat''' + method + '''Data(floats);
    const auto values = floats->AsSpan();
    auto output = array->AsSpan();
    for (size_t i = 0; i < count; ++i) {
''' + conversion + '''
      // Comparisons also map -infinity/silence to zero, like upstream.
      output[i] = scaled > 0.0 ? static_cast<uint8_t>(std::min(255.0, scaled)) : 0;
    }
    return;
  }
''' + byte_call
        edit(path, byte_call, replacement, 'analyser-byte-' + method)

    # Keep the service node registered until every client has disconnected.
    # Missing shared/dedicated clients verify its type through this very map.
    path = 'components/performance_manager/worker_watcher.cc'
    edit(path, '''  auto service_worker_node = std::move(it->second);

  // First, disconnect all current clients of this service worker.
  DisconnectAllServiceWorkerClients(service_worker_node.get(), version_id);

#if DCHECK_IS_ON()
  DCHECK(!detached_frame_count_per_worker_.contains(service_worker_node.get()));
#endif  // DCHECK_IS_ON()
  PerformanceManagerImpl::DeleteNode(std::move(service_worker_node));''',
         '''  // Keep map ownership while disconnecting: late client removal checks
  // IsServiceWorkerNode(), including during off-the-record profile teardown.
  WorkerNodeImpl* service_worker_node = it->second.get();

  // First, disconnect all current clients of this service worker.
  DisconnectAllServiceWorkerClients(service_worker_node, version_id);

#if DCHECK_IS_ON()
  DCHECK(!detached_frame_count_per_worker_.contains(service_worker_node));
#endif  // DCHECK_IS_ON()
  PerformanceManagerImpl::DeleteNode(std::move(it->second));''',
         'service-worker-stop-ownership')
    path = 'components/performance_manager/worker_watcher_unittest.cc'
    tests = read(path)
    start = tests.index('TEST_F(WorkerWatcherTest, SharedWorkerDiesAsServiceWorkerClient) {')
    end = tests.index('\n}\n\n', start) + 4
    regression = tests[start:end].replace(
        'SharedWorkerDiesAsServiceWorkerClient',
        'SharedWorkerDiesBeforeServiceWorkerStopsWithRegisteredClient', 1)
    removal = '''  // Issue the trailing service worker client removal.
  service_worker_factory()->RemoveClient(service_worker_version_id,
                                         service_worker_client_uuid);

'''
    if regression.count(removal) != 1:
        raise ValueError('Pinned service worker test drift')
    regression = regression.replace(removal, '')
    stop = '  service_worker_factory()->StopServiceWorker(service_worker_version_id);'
    regression = regression.replace(stop, stop + '\n' + removal, 1)
    edit(path, 'TEST_F(WorkerWatcherTest, OneSharedWorkerTwoClients)',
         regression + 'TEST_F(WorkerWatcherTest, OneSharedWorkerTwoClients)',
         'service-worker-stop-regression')

    # Header ownership remains in core; no platform -> core dependency is added.
    path = CORE + 'canvas_interventions/build.gni'
    # Repair the exact consecutive duplication produced by the old prefix
    # migration. Do not silently normalize unrelated source drift.
    text = read(path)
    cpu_line = '  "metabrowser_cpu_identity.h",\n'
    while cpu_line + cpu_line in text:
        text = text.replace(cpu_line + cpu_line, cpu_line, 1)
    if text.count(cpu_line) > 1:
        raise ValueError('Nonconsecutive CPU header ownership drift')
    result[path] = text
    edit(path, 'blink_core_sources_canvas_interventions = [',
         'blink_core_sources_canvas_interventions = [\n'
         '  "metabrowser_surface_privacy.h",\n'
         '  "metabrowser_cpu_identity.h",', 'surface-header-owner',
         previous='blink_core_sources_canvas_interventions = [\n  "metabrowser_surface_privacy.h",')
    header = Path(__file__).resolve().parents[1] / 'chromium/privacy/metabrowser_surface_privacy.h'
    target = root / HEADER
    original[HEADER] = target.read_text() if target.exists() else None
    result[HEADER] = header.read_text()
    cpu_header = header.with_name('metabrowser_cpu_identity.h')
    cpu_target = CORE + 'canvas_interventions/metabrowser_cpu_identity.h'
    target = root / cpu_target
    original[cpu_target] = target.read_text() if target.exists() else None
    result[cpu_target] = cpu_header.read_text()
    return original, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = args.source.resolve(strict=True)
    if (root / 'chrome/VERSION').read_text().splitlines() != [
            'MAJOR=154', 'MINOR=0', 'BUILD=8037', 'PATCH=97']:
        raise SystemExit('Expected exact Chromium 154.0.8037.97')
    before, after = make_plan(root)
    changed = [path for path in after if before[path] != after[path]]
    for path in after:
        current = (root / path).read_text() if (root / path).exists() else None
        if current != before[path]:
            raise SystemExit('Source changed during preflight: ' + path)
    if args.apply:
        for path in changed:
            (root / path).write_text(after[path])
    print(json.dumps({'applied': args.apply, 'changed': changed,
                      'all_files': {p: hashlib.sha256(t.encode()).hexdigest()
                                    for p, t in after.items()}}, indent=2))


if __name__ == '__main__':
    main()
