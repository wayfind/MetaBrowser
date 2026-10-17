#!/usr/bin/env python3
"""Pinned native Battery/NetworkInformation policy; preview unless --apply."""
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

def edit(name,old,new):
    path=root/(prefix+name)
    assert not path.is_symlink() and path.resolve().is_relative_to(root)
    if name not in original:original[name]=path.read_text()
    text=changes.get(name,original[name])
    if new in text:
        assert text.count(new)==1
    else:
        if text.count(old)!=1:raise SystemExit('Pinned passive-signals source drift: '+name+': '+old[:80])
        text=text.replace(old,new,1)
    changes[name]=text

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
for signature,value in [('V8ConnectionType NetworkInformation::type() const','V8ConnectionType(V8ConnectionType::Enum::kUnknown)'),
                         ('double NetworkInformation::downlinkMax() const','std::numeric_limits<double>::infinity()'),
                         ('V8EffectiveConnectionType NetworkInformation::effectiveType()','V8EffectiveConnectionType(V8EffectiveConnectionType::Enum::k4G)'),
                         ('uint32_t NetworkInformation::rtt()','0'),
                         ('double NetworkInformation::downlink()','10.0')]:
    edit('netinfo/network_information.cc',signature+' {',signature+' {\n  if (metabrowser_protected_) return '+value+';')
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
for name,before in original.items():assert (root/(prefix+name)).read_text()==before,'Source changed during preflight'
if a.apply:
    for name,text in changes.items():
        if text!=original[name]:(root/(prefix+name)).write_text(text)
print(json.dumps({'scope':'battery-network-passive-signals','applied':a.apply,'all_files':{prefix+n:hashlib.sha256(t.encode()).hexdigest() for n,t in changes.items()}}))
