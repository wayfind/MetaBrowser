#!/usr/bin/env python3
"""Pinned native Battery/NetworkInformation policy; preview unless --apply.

Protected identities send the same device memory and network-quality values in
script, subresource Client Hints (renderer) and navigation Client Hints (browser).
"""
import argparse
import hashlib
import json
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('source',type=Path)
p.add_argument('--apply',action='store_true')
a=p.parse_args();root=a.source.resolve(strict=True)
assert (root/'chrome/VERSION').read_text().splitlines()==['MAJOR=154','MINOR=0','BUILD=8037','PATCH=97']
original,changes={},{}
prefix='third_party/blink/renderer/modules/'

def edit(name,old,new,previous=None,base=prefix):
    name=base+name;path=root/name
    assert not path.is_symlink() and path.resolve().is_relative_to(root)
    if name not in original:original[name]=path.read_text()
    text=changes.get(name,original[name])
    if new in text:
        assert text.count(new)==1
    elif previous is not None and previous in text:
        # An already staged earlier policy is migrated in place, never stacked.
        assert text.count(previous)==1;text=text.replace(previous,new,1)
    else:
        if text.count(old)!=1:raise SystemExit('Pinned passive-signals source drift: '+name+': '+old[:80])
        text=text.replace(old,new,1)
    changes[name]=text

runtime_include='#include "third_party/blink/public/common/user_agent/metabrowser_persona_runtime.h"'

edit('battery/battery_manager.h',
     '  using BatteryProperty = ScriptPromiseProperty<BatteryManager, DOMException>;',
     '''  // Snapshot policy: retained objects cannot reopen physical metadata.
  const bool metabrowser_protected_;
  using BatteryProperty = ScriptPromiseProperty<BatteryManager, DOMException>;''')
edit('battery/battery_manager.cc',
     '#include "third_party/blink/renderer/modules/battery/battery_manager.h"',
     '#include "third_party/blink/renderer/modules/battery/battery_manager.h"\n\n#include <limits>')
edit('battery/battery_manager.cc',
     '      PlatformEventController(*navigator.DomWindow()),',
     '''      PlatformEventController(*navigator.DomWindow()),
      metabrowser_protected_(navigator.DomWindow() &&
          navigator.DomWindow()->CanvasNoiseToken().has_value()),''')
edit('battery/battery_manager.cc',
     '    if (!GetExecutionContext() || GetExecutionContext()->IsContextDestroyed()) {',
     '''    if (metabrowser_protected_ || !GetExecutionContext() ||
        GetExecutionContext()->IsContextDestroyed()) {''')
for signature,statement,value in [('bool BatteryManager::charging()', 'battery_status_.Charging()', 'true'),
                                  ('double BatteryManager::chargingTime()', 'battery_status_.charging_time().InSecondsF()', '0.0'),
                                  ('double BatteryManager::dischargingTime()', 'battery_status_.discharging_time().InSecondsF()', 'std::numeric_limits<double>::infinity()'),
                                  ('double BatteryManager::level()', 'battery_status_.Level()', '1.0')]:
    edit('battery/battery_manager.cc',signature+' {\n  return '+statement+';',signature+' {\n  if (metabrowser_protected_) return '+value+';\n  return '+statement+';')
edit('battery/battery_manager.cc','void BatteryManager::DidUpdateData() {',
     '''void BatteryManager::DidUpdateData() {
  if (metabrowser_protected_) return;''')
edit('battery/battery_manager.cc',
     '    mojom::FrameLifecycleState state) {',
     '''    mojom::FrameLifecycleState state) {
  // Do not subscribe to system battery data, including before StartRequest.
  if (metabrowser_protected_) return;''')
edit('netinfo/network_information.h',
     '  // Touched only on context thread.\n  WebConnectionType type_;',
     '''  // Immutable owner policy; physical type and quality remain private.
  const bool metabrowser_protected_;
  // Touched only on context thread.
  WebConnectionType type_;''')
edit('netinfo/network_information.cc',
     '      ExecutionContextLifecycleObserver(navigator.GetExecutionContext()),',
     '''      ExecutionContextLifecycleObserver(navigator.GetExecutionContext()),
      metabrowser_protected_(navigator.GetExecutionContext() &&
          navigator.GetExecutionContext()->CanvasNoiseToken().has_value()),''')
edit('netinfo/network_information.cc',
     '#include "third_party/blink/renderer/modules/netinfo/network_information.h"',
     '#include "third_party/blink/renderer/modules/netinfo/network_information.h"\n'+runtime_include)
# RTT/downlink come from the shared cohort so script and Client Hints agree.
for signature,value,earlier in [('V8ConnectionType NetworkInformation::type() const','V8ConnectionType(V8ConnectionType::Enum::kUnknown)',None),
                                ('double NetworkInformation::downlinkMax() const','std::numeric_limits<double>::infinity()',None),
                                ('V8EffectiveConnectionType NetworkInformation::effectiveType()','V8EffectiveConnectionType(V8EffectiveConnectionType::Enum::k4G)',None),
                                ('uint32_t NetworkInformation::rtt()','metabrowser::kProtectedRttMs','0'),
                                ('double NetworkInformation::downlink()','metabrowser::kProtectedDownlinkMbps','10.0')]:
    edit('netinfo/network_information.cc',signature+' {',signature+' {\n  if (metabrowser_protected_) return '+value+';',
         previous=earlier and signature+' {\n  if (metabrowser_protected_) return '+earlier+';')
edit('netinfo/network_information.cc',
     '  DCHECK(GetExecutionContext()->IsContextThread());\n\n  const String host = Host();',
     '''  DCHECK(GetExecutionContext()->IsContextThread());
  if (metabrowser_protected_) {
    // Only the explicit data-saving preference remains observable. Physical
    // link, RTT and throughput changes must not produce a timing side channel.
    if (save_data_ != save_data) {
      save_data_ = save_data;
      DispatchEvent(*Event::Create(event_type_names::kChange));
    }
    return;
  }

  const String host = Host();''')

# Subresource Client Hints are added in the renderer from the requesting
# document. Use that document's browser-derived token, like NetworkInformation.
fetch='core/loader/frame_fetch_context.cc';core='third_party/blink/renderer/'
edit(fetch,'#include "third_party/blink/renderer/core/loader/frame_fetch_context.h"',
     '#include "third_party/blink/renderer/core/loader/frame_fetch_context.h"\n'+runtime_include,base=core)
edit(fetch,'''  const ClientHintsPreferences& hints_preferences = GetClientHintsPreferences();

  using network::mojom::blink::WebClientHintsType;
''','''  const ClientHintsPreferences& hints_preferences = GetClientHintsPreferences();

  using network::mojom::blink::WebClientHintsType;

  // Protected identities send the device class and network cohort that
  // navigator.deviceMemory and NetworkInformation expose to this document.
  const bool metabrowser_protected =
      document_->domWindow()->CanvasNoiseToken().has_value();
  const float metabrowser_device_memory = metabrowser_protected
      ? metabrowser::ProtectedDeviceMemory(
            ApproximatedDeviceMemory::GetApproximatedDeviceMemory())
      : ApproximatedDeviceMemory::GetApproximatedDeviceMemory();
''',base=core)
for header in ('kDeviceMemory_DEPRECATED','kDeviceMemory'):
    edit(fetch,'''        http_names::'''+header+''',
        AtomicString(String::Number(
            ApproximatedDeviceMemory::GetApproximatedDeviceMemory())));''','''        http_names::'''+header+''',
        AtomicString(String::Number(metabrowser_device_memory)));''',base=core)
edit(fetch,'''    uint32_t rtt = GetNetworkStateNotifier().RoundRtt(
        request.Url().Host().ToString(), http_rtt);''','''    uint32_t rtt = GetNetworkStateNotifier().RoundRtt(
        request.Url().Host().ToString(), http_rtt);
    if (metabrowser_protected) rtt = metabrowser::kProtectedRttMs;''',base=core)
edit(fetch,'''    double mbps = GetNetworkStateNotifier().RoundMbps(
        request.Url().Host().ToString(), throughput_mbps);''','''    double mbps = GetNetworkStateNotifier().RoundMbps(
        request.Url().Host().ToString(), throughput_mbps);
    if (metabrowser_protected) mbps = metabrowser::kProtectedDownlinkMbps;''',base=core)
edit(fetch,'''      holdback_ect = GetNetworkStateNotifier().EffectiveType();
    }''','''      holdback_ect = GetNetworkStateNotifier().EffectiveType();
    }
    if (metabrowser_protected) holdback_ect = WebEffectiveConnectionType::kType4G;''',base=core)

# Navigation Client Hints are added in the browser. Ask the embedder for the
# same browser-derived context decision the committed document will receive.
hints='client_hints/client_hints.cc';browser='content/browser/'
edit(hints,'#include "content/public/common/content_switches.h"',
     '#include "content/public/common/content_switches.h"\n'
     '#include "content/browser/renderer_host/render_frame_host_impl.h"\n'
     '#include "content/public/browser/storage_partition_config.h"\n'
     '#include "third_party/blink/public/common/storage_key/storage_key.h"\n'+runtime_include,base=browser)
edit(hints,'''void AddDeviceMemoryHeader(net::HttpRequestHeaders* headers,
                           bool use_deprecated_version = false) {
  DCHECK(headers);
  blink::ApproximatedDeviceMemory::Initialize();
  const float device_memory =
      blink::ApproximatedDeviceMemory::GetApproximatedDeviceMemory();''','''void AddDeviceMemoryHeader(net::HttpRequestHeaders* headers,
                           bool use_deprecated_version = false,
                           bool metabrowser_protected = false) {
  DCHECK(headers);
  blink::ApproximatedDeviceMemory::Initialize();
  float device_memory =
      blink::ApproximatedDeviceMemory::GetApproximatedDeviceMemory();
  if (metabrowser_protected)
    device_memory = metabrowser::ProtectedDeviceMemory(device_memory);''',base=browser)
edit(hints,'// The main logic of adding Client Hints headers to `headers`. `frame_tree_node`',
     '''// MetaBrowser: navigation hints follow the protected identity that the
// destination document will commit with (navigator.deviceMemory and
// NetworkInformation). The token itself is never sent.
bool MetaBrowserProtectedClientHints(BrowserContext* context,
                                     const url::Origin& origin,
                                     FrameTreeNode* frame_tree_node) {
  if (!context || origin.opaque()) return false;
  const url::Origin top_frame_origin =
      frame_tree_node && !frame_tree_node->IsOutermostMainFrame()
          ? frame_tree_node->current_frame_host()
                ->GetOutermostMainFrame()->GetLastCommittedOrigin()
          : origin;
  return GetContentClient()->browser()->GetMetaBrowserPrivacyToken(
      context, blink::StorageKey::CreateFirstParty(origin),
      StoragePartitionConfig::CreateDefault(context), top_frame_origin)
      .has_value();
}

// The main logic of adding Client Hints headers to `headers`. `frame_tree_node`''',base=browser)
edit(hints,'''      data, container_policy);

  GURL url = origin.GetURL();''','''      data, container_policy);

  GURL url = origin.GetURL();
  const bool metabrowser_protected =
      MetaBrowserProtectedClientHints(context, origin, frame_tree_node);''',base=browser)
edit(hints,'    AddDeviceMemoryHeader(headers, /*use_deprecated_version*/ true);',
     '    AddDeviceMemoryHeader(headers, /*use_deprecated_version*/ true,\n'
     '                          metabrowser_protected);',base=browser)
edit(hints,'    AddDeviceMemoryHeader(headers);',
     '    AddDeviceMemoryHeader(headers, /*use_deprecated_version*/ false,\n'
     '                          metabrowser_protected);',base=browser)
for call,protected_header in [
        ('AddRttHeader(headers, network_quality_tracker, url);',
         '''SetHeaderToInt(headers, WebClientHintsType::kRtt_DEPRECATED,
                     metabrowser::kProtectedRttMs);'''),
        ('AddDownlinkHeader(headers, network_quality_tracker, url);',
         '''SetHeaderToDouble(headers, WebClientHintsType::kDownlink_DEPRECATED,
                        metabrowser::kProtectedDownlinkMbps);'''),
        ('AddEctHeader(headers, network_quality_tracker, url);',
         '''SetHeaderToString(headers, WebClientHintsType::kEct_DEPRECATED,
        network::kWebEffectiveConnectionTypeMapping[
            net::EFFECTIVE_CONNECTION_TYPE_4G]);''')]:
    edit(hints,'    '+call,'''    if (metabrowser_protected) {
      '''+protected_header+'''
    } else {
      '''+call+'''
    }''',base=browser)

for name,before in original.items():assert (root/name).read_text()==before,'Source changed during preflight'
if a.apply:
    for name,text in changes.items():
        if text!=original[name]:(root/name).write_text(text)
print(json.dumps({'scope':'battery-network-passive-signals','applied':a.apply,'all_files':{n:hashlib.sha256(t.encode()).hexdigest() for n,t in changes.items()}}))
