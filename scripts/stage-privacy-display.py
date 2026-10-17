#!/usr/bin/env python3
"""Stage a coherent web-visible macOS virtual display without changing compositing.

Normal viewport/rendering dimensions and DPR retain real rendering semantics.
Screen/CSS device geometry, position, depth/gamut/HDR and orientation use the
same virtual contract until browser-authoritative Window Management permission
is granted. Permission observation is quiet and revocation restores protection.
Preview by default. Preflights all files before writing; no build or network.
"""
import argparse
import hashlib
import json
from pathlib import Path

CORE = 'third_party/blink/renderer/core/'
MODULES = 'third_party/blink/renderer/modules/'
HEADER = CORE + 'canvas_interventions/metabrowser_display_privacy.h'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    root = args.source.resolve(strict=True)
    if (root / 'chrome/VERSION').read_text().splitlines() != [
            'MAJOR=154', 'MINOR=0', 'BUILD=8037', 'PATCH=97']:
        raise SystemExit('Expected pinned Chromium 154.0.8037.97')
    before, after = {}, {}

    def read(path):
        if path not in before:
            p = root / path
            if p.is_symlink() or not p.resolve().is_relative_to(root):
                raise ValueError('Path escapes source checkout')
            before[path] = p.read_text()
            after[path] = before[path]
        return after[path]

    def edit(path, old, new, label):
        text = read(path)
        marker = ('#' if path.endswith('.gni') else '//') + ' METABROWSER_DISPLAY_V1: ' + label + '\n'
        value = marker + new
        if value in text:
            if text.count(value) != 1:
                raise ValueError('Duplicate display patch: ' + label)
            return
        if marker in text or text.count(old) != 1:
            raise ValueError('Pinned display source drift: ' + path + ': ' + label)
        after[path] = text.replace(old, value, 1)

    def include(path):
        text = read(path)
        line = '#include "' + HEADER + '"'
        if line in text.splitlines():
            if text.splitlines().count(line) != 1:
                raise ValueError('Duplicate display dependency')
            return
        old = next(l for l in text.splitlines()
                   if l.startswith('#include "') and text.count(l) == 1)
        edit(path, old, old + '\n' + line, 'dependency')

    path = CORE + 'frame/screen.cc'
    include(path)
    old = '    : ExecutionContextClient(window), display_id_(display_id) {}'
    edit(path, old, '''    : ExecutionContextClient(window), display_id_(display_id) {
  // Establish the initial virtual screen state even when the page only adds
  // an event listener and has not read any screen property yet.
  (void)MetaBrowserDisplayProtected(window);
}''', 'initial-event-state')
    old = '  gfx::Rect rect = available ? screen_info.available_rect : screen_info.rect;'
    edit(path, old, old + '''
  if (MetaBrowserDisplayProtected(DomWindow())) {
    rect = MetaBrowserVirtualDisplay(*frame);
    if (available) rect = gfx::Rect(0, 24, rect.width(), rect.height() - 24);
  }''', 'screen-rect')
    edit(path, '  return GetScreenInfo().depth == 0',
         '  if (MetaBrowserDisplayProtected(DomWindow())) return 24;\n'
         '  return GetScreenInfo().depth == 0', 'screen-depth')
    edit(path, '  return GetScreenInfo().is_extended;',
         '  if (MetaBrowserDisplayProtected(DomWindow())) return false;\n'
         '  return GetScreenInfo().is_extended;', 'screen-extended')

    path = CORE + 'frame/local_dom_window.cc'
    include(path)
    edit(path, '  int screenX = chrome_client.RootWindowRect(*frame).x();',
         '  int screenX = MetaBrowserDisplayProtected(const_cast<LocalDOMWindow*>(this))\n'
         '      ? 0 : chrome_client.RootWindowRect(*frame).x();', 'window-x')
    edit(path, '  int screenY = chrome_client.RootWindowRect(*frame).y();',
         '  int screenY = MetaBrowserDisplayProtected(const_cast<LocalDOMWindow*>(this))\n'
         '      ? 24 : chrome_client.RootWindowRect(*frame).y();', 'window-y')

    path = CORE + 'css/media_values.cc'
    include(path)
    for dimension in ('width', 'height'):
        old = f'  int device_{dimension} = screen_info.rect.{dimension}();'
        edit(path, old,
             f'  int device_{dimension} = MetaBrowserDisplayProtected(frame->DomWindow())\n'
             f'      ? MetaBrowserVirtualDisplay(*frame).{dimension}() : screen_info.rect.{dimension}();',
             'css-device-' + dimension)
    old = '''bool MediaValues::CalculateDeviceSupportsHDR(LocalFrame* frame) {
  DCHECK(frame);
  DCHECK(frame->GetPage());'''
    edit(path, old, old + '\n  if (MetaBrowserDisplayProtected(frame->DomWindow())) return false;', 'css-hdr')
    old = '''int MediaValues::CalculateColorBitsPerComponent(LocalFrame* frame) {
  DCHECK(frame);
  DCHECK(frame->GetPage());'''
    edit(path, old, old + '\n  if (MetaBrowserDisplayProtected(frame->DomWindow())) return 8;', 'css-depth')
    old = '''int MediaValues::CalculateMonochromeBitsPerComponent(LocalFrame* frame) {
  DCHECK(frame);
  DCHECK(frame->GetPage());'''
    edit(path, old, old + '\n  if (MetaBrowserDisplayProtected(frame->DomWindow())) return 0;', 'css-monochrome')
    old = '''  return override_value.value_or(color_space_utilities::GetColorSpaceGamut(
      frame->GetPage()->GetChromeClient().GetScreenInfo(*frame)));'''
    edit(path, old, '''  return override_value.value_or(MetaBrowserDisplayProtected(frame->DomWindow())
      ? ColorSpaceGamut::SRGB : color_space_utilities::GetColorSpaceGamut(
          frame->GetPage()->GetChromeClient().GetScreenInfo(*frame)));''', 'css-gamut')

    path = MODULES + 'screen_details/window_screen_details.cc'
    include(path)
    old = '  if (status->status != mojom::blink::PermissionStatus::GRANTED) {'
    edit(path, old, '''  MetaBrowserScreenPermissionInquiry(*GetSupplementable(),
      status->status == mojom::blink::PermissionStatus::GRANTED);
''' + old, 'native-permission-result')

    path = MODULES + 'screen_orientation/screen_orientation.cc'
    include(path)
    old = '  return V8OrientationType(OrientationTypeToV8Enum(type_));'
    edit(path, old, '''  if (MetaBrowserDisplayProtected(GetExecutionContext()
          ? To<LocalDOMWindow>(GetExecutionContext()) : nullptr))
    return V8OrientationType(V8OrientationType::Enum::kLandscapePrimary);
''' + old, 'orientation-type')
    old = '  return angle_;'
    edit(path, old, '''  if (MetaBrowserDisplayProtected(GetExecutionContext()
          ? To<LocalDOMWindow>(GetExecutionContext()) : nullptr)) return 0;
''' + old, 'orientation-angle')
    path = MODULES + 'screen_orientation/screen_orientation_controller.cc'
    include(path)
    old = '  UpdateOrientation();\n  GetExecutionContext()'
    edit(path, old, '  UpdateOrientation();\n'
         '  if (MetaBrowserDisplayProtected(DomWindow())) return;\n'
         '  GetExecutionContext()', 'orientation-event')

    # Retained detailed objects are live wrappers. Revoking permission must
    # protect base Screen getters too, not only ScreenDetailed's own fields.
    path = CORE + 'frame/screen.h'
    edit(path, '  const display::ScreenInfo& GetScreenInfo() const;',
         '  virtual const display::ScreenInfo& GetScreenInfo() const;',
         'detailed-screen-boundary')
    path = MODULES + 'screen_details/screen_detailed.h'
    old = '#include "third_party/blink/renderer/core/frame/screen.h"'
    edit(path, old, old + '\n#include "ui/display/screen_info.h"', 'detailed-info-type')
    edit(path, '  float whitePointY() const;', '''  float whitePointY() const;

 protected:
  const display::ScreenInfo& GetScreenInfo() const override;

 private:
  mutable display::ScreenInfo protected_info_;''', 'retained-detailed-boundary')
    path = MODULES + 'screen_details/screen_detailed.cc'
    include(path)
    old = '// static\nbool ScreenDetailed::AreWebExposedScreenDetailedPropertiesEqual('
    edit(path, old, '''const display::ScreenInfo& ScreenDetailed::GetScreenInfo() const {
  if (MetaBrowserDetailedDisplayBlocked(DomWindow())) {
    protected_info_ = display::ScreenInfo();
    if (auto* frame = DomWindow()->GetFrame()) {
      protected_info_.rect = MetaBrowserVirtualDisplay(*frame);
      protected_info_.available_rect = gfx::Rect(0, 24,
          protected_info_.rect.width(), protected_info_.rect.height() - 24);
      // DPR remains a public real rendering property, shared with basic Screen.
      protected_info_.device_scale_factor =
          frame->GetChromeClient().GetScreenInfo(*frame).device_scale_factor;
    }
    protected_info_.depth = 24;
    protected_info_.is_primary = true;
    protected_info_.is_internal = false;
    protected_info_.is_extended = false;
    protected_info_.label.clear();
    return protected_info_;
  }
  return Screen::GetScreenInfo();
}

''' + old, 'retained-detailed-source')
    for name, value in (('hdrHeadroom', '0.f'), ('highDynamicRangeHeadroom', '1.f'),
                        ('redPrimaryX', '.64f'), ('redPrimaryY', '.33f'),
                        ('greenPrimaryX', '.30f'), ('greenPrimaryY', '.60f'),
                        ('bluePrimaryX', '.15f'), ('bluePrimaryY', '.06f'),
                        ('whitePointX', '.3127f'), ('whitePointY', '.3290f')):
        old = f'float ScreenDetailed::{name}() const {{'
        edit(path, old, old + '\n  if (MetaBrowserDetailedDisplayBlocked(DomWindow())) return ' + value + ';',
             'retained-' + name)
    path = MODULES + 'screen_details/screen_details.h'
    edit(path, '  HeapVector<Member<ScreenDetailed>> screens_;',
         '  HeapVector<Member<ScreenDetailed>> screens_;\n'
         '  HeapVector<Member<ScreenDetailed>> revoked_screens_;', 'empty-revoked-list')
    old = '  display::ScreenInfos prev_screen_infos_;'
    edit(path, old, '''  void RefreshMetaBrowserPermissionSnapshot() const;
  mutable uint64_t metabrowser_permission_generation_ = 0;
''' + old, 'permission-generation-state')
    path = MODULES + 'screen_details/screen_details.cc'
    include(path)
    edit(path, '  return screens_;',
         '  if (MetaBrowserDetailedDisplayBlocked(DomWindow())) return revoked_screens_;\n'
         '  return screens_;', 'retained-list')
    signature = 'ScreenDetailed* ScreenDetails::currentScreen() const {'
    body = signature + '\n  RefreshMetaBrowserPermissionSnapshot();\n  if (MetaBrowserDetailedDisplayBlocked(DomWindow())) return nullptr;'
    # Migrate only exact v11/v12 bodies. A later header insertion used to
    # split the first patch's marker/body and broke a second staging pass.
    legacy = '// METABROWSER_DISPLAY_V1: retained-current\n'
    for previous in (
            legacy + '// METABROWSER_DISPLAY_V1: current-regrant-refresh\n' + body,
            legacy + signature + '\n  if (MetaBrowserDetailedDisplayBlocked(DomWindow())) return nullptr;'):
        text = read(path)
        if previous in text:
            if text.count(previous) != 1:
                raise ValueError('Duplicate retained-screen migration')
            after[path] = text.replace(previous, '// METABROWSER_DISPLAY_V1: retained-current-v2\n' + body, 1)
    edit(path, signature, body, 'retained-current-v2')
    edit(path, '  visitor->Trace(screens_);',
         '  visitor->Trace(screens_);\n  visitor->Trace(revoked_screens_);', 'revoked-list-trace')
    old = '  // Expect that all updates contain a non-zero set of screens.'
    edit(path, old, '  if (MetaBrowserDetailedDisplayBlocked(window)) return;\n' + old,
         'revoked-physical-updates')
    for signature, tag in (
            ('const HeapVector<Member<ScreenDetailed>>& ScreenDetails::screens() const {', 'list-regrant-refresh'),):
        edit(path, signature, signature + '\n  RefreshMetaBrowserPermissionSnapshot();', tag)
    old = 'const AtomicString& ScreenDetails::InterfaceName() const {'
    edit(path, old, '''void ScreenDetails::RefreshMetaBrowserPermissionSnapshot() const {
  auto* window = DomWindow();
  if (!window || !window->CanvasNoiseToken()) return;
  auto* privacy = MetaBrowserDisplayPermission::From(*window);
  if (privacy->generation() == metabrowser_permission_generation_) return;
  metabrowser_permission_generation_ = privacy->generation();
  if (!privacy->allowed()) return;
  if (auto* frame = window->GetFrame()) {
    // Regrant via browser settings need not involve another getScreenDetails()
    // call. Refresh once per permission generation, before any retained getter.
    const_cast<ScreenDetails*>(this)->UpdateScreenInfosImpl(window,
        frame->GetChromeClient().GetScreenInfos(*frame), /*dispatch_events=*/false);
  }
}

''' + old, 'observer-regrant-snapshot')
    path = MODULES + 'screen_details/window_screen_details.cc'
    old = '  resolver->Resolve(screen_details_);'
    edit(path, old, '''  if (auto* frame = GetSupplementable()->GetFrame())
    screen_details_->UpdateScreenInfos(GetSupplementable(),
        frame->GetChromeClient().GetScreenInfos(*frame));
''' + old, 'regrant-current-snapshot')
    include(path)
    old = '#include "third_party/blink/renderer/core/frame/local_frame.h"'
    edit(path, old, old + '\n#include "third_party/blink/renderer/core/page/chrome_client.h"',
         'regrant-chrome-client')
    path = CORE + 'frame/web_frame_widget_impl.cc'
    include(path)
    edit(path, '        if (window_screen_has_changed)\n',
         '        if (MetaBrowserShouldDispatchScreenChange(\n'
         '                *local_frame->GetFrame()->DomWindow(), window_screen_has_changed))\n',
         'effective-screen-events')
    old = '''  return device_emulator_ != nullptr;
}

void WebFrameWidgetImpl::EnqueueMoveEvent() {'''
    edit(path, old, '''  if (local_root_ && widget_base_->WindowScreenRect().size() != window_screen_rect.size()) {
    // UpdateScreenRects runs before WidgetBase commits the new rect. Observe
    // it in a posted task, including fixed-size child frames controlled here.
    local_root_->GetTaskRunner(TaskType::kInternalDefault)->PostTask(FROM_HERE,
        BindOnce(&WebFrameWidgetImpl::MetaBrowserNotifyVirtualScreenChange,
                 WrapWeakPersistent(this)));
  }
  return device_emulator_ != nullptr;
}

void WebFrameWidgetImpl::MetaBrowserNotifyVirtualScreenChange() {
  if (!local_root_ || !local_root_->GetFrame()) return;
  ForEachLocalFrameControlledByWidget(LocalRootImpl()->GetFrame(),
      [](WebLocalFrameImpl* local_frame) {
        auto* window = local_frame->GetFrame()->DomWindow();
        auto* document = local_frame->GetFrame()->GetDocument();
        if (!window || window->IsContextDestroyed() || !document || !document->IsActive()) return;
        if (!MetaBrowserDisplayProtected(window) ||
            !MetaBrowserShouldDispatchScreenChange(*window, false)) return;
        local_frame->GetFrame()->GetDocument()->MediaQueryAffectingValueChanged(
            MediaValueChange::kOther);
        window->screen()->EnqueueEvent(*Event::Create(event_type_names::kChange),
                                     TaskType::kMiscPlatformAPI);
      });
}

void WebFrameWidgetImpl::EnqueueMoveEvent() {''', 'committed-window-size-events')
    path = CORE + 'frame/web_frame_widget_impl.h'
    edit(path, '  void EnqueueMoveEvent();',
         '  void EnqueueMoveEvent();\n  void MetaBrowserNotifyVirtualScreenChange();',
         'committed-window-event-helper')

    path = CORE + 'canvas_interventions/build.gni'
    edit(path, '  "metabrowser_canvas_noise.h",',
         '  "metabrowser_canvas_noise.h",\n'
         '  "metabrowser_display_privacy.h",', 'header-owner')
    p = root / HEADER
    before[HEADER] = p.read_text() if p.exists() else None
    after[HEADER] = (Path(__file__).resolve().parents[1] / 'chromium/privacy/metabrowser_display_privacy.h').read_text()
    for path, old in before.items():
        current = (root / path).read_text() if (root / path).exists() else None
        if current != old:
            raise SystemExit('Source changed during preflight: ' + path)
    changed = [p for p in after if before[p] != after[p]]
    if args.apply:
        for path in changed:
            (root / path).write_text(after[path])
    print(json.dumps({'applied': args.apply, 'changed': changed,
                      'all_files': {p: hashlib.sha256(t.encode()).hexdigest()
                                    for p, t in after.items()}}, indent=2))


if __name__ == '__main__':
    main()
