#!/usr/bin/env python3
"""Stage guarded native 8-bit Canvas export protection into pinned Chromium."""
import argparse
import pathlib
import shutil

p = argparse.ArgumentParser()
p.add_argument('source', type=pathlib.Path)
a = p.parse_args()
root = a.source.resolve()
project = pathlib.Path(__file__).resolve().parents[1]
header = 'third_party/blink/renderer/core/canvas_interventions/metabrowser_canvas_noise.h'
if not (root / header).exists() or (root / header).read_bytes() != (project / 'chromium/privacy/metabrowser_canvas_noise.h').read_bytes():
    shutil.copy2(project / 'chromium/privacy/metabrowser_canvas_noise.h', root / header)
helper = 'third_party/blink/renderer/core/canvas_interventions/metabrowser_noise_mix.h'
if not (root / helper).exists() or (root / helper).read_bytes() != (project / 'chromium/privacy/metabrowser_noise_mix.h').read_bytes():
    (root / helper).write_bytes((project / 'chromium/privacy/metabrowser_noise_mix.h').read_bytes())
build = root / 'third_party/blink/renderer/core/canvas_interventions/build.gni'
text = build.read_text()
helper_entry = '  "metabrowser_noise_mix.h",\n'
if text.count(helper_entry) > 1:
    raise SystemExit('Duplicate Canvas helper ownership')
# Do not split the adjacent mac/display staging marker and its exact block.
without_helper = text.replace(helper_entry, '')
anchor = '  "noise_hash.cc",\n'
if without_helper.count(anchor) != 1:
    raise SystemExit('Privacy Canvas helper source-list anchor changed')
text = without_helper.replace(anchor, helper_entry + anchor, 1)
if text != build.read_text():
    build.write_text(text)
entry = '  "metabrowser_canvas_noise.h",\n'
if entry not in text:
    anchor = 'blink_core_sources_canvas_interventions = [\n'
    if text.count(anchor) != 1:
        raise SystemExit('Privacy Canvas source-list anchor changed')
    build.write_text(text.replace(anchor, anchor + entry, 1))


def patch(path, edits):
    f = root / path
    text = f.read_text()
    include = '#include "' + header + '"'
    if include not in text:
        at = text.index('\n', text.index('#include "'))
        text = text[:at] + '\n' + include + text[at:]
    for old, new in edits:
        if new in text:
            continue
        if text.count(old) != 1:
            raise SystemExit('Privacy Canvas anchor changed: ' + path + ': ' + old[:80])
        text = text.replace(old, new)
    if f.read_text() != text:
        f.write_text(text)


patch('third_party/blink/renderer/core/html/canvas/html_canvas_element.cc', [
    ('scoped_refptr<StaticBitmapImage> image_bitmap = Snapshot(source_buffer);',
     'scoped_refptr<StaticBitmapImage> image_bitmap =\n      MetaBrowserProtectCanvasExport(Snapshot(source_buffer), GetExecutionContext());'),
    ('scoped_refptr<StaticBitmapImage> image_bitmap = Snapshot(kBackBuffer);',
     'scoped_refptr<StaticBitmapImage> image_bitmap =\n      MetaBrowserProtectCanvasExport(Snapshot(kBackBuffer), GetExecutionContext());'),
])
patch('third_party/blink/renderer/core/offscreencanvas/offscreen_canvas.cc', [
    ('scoped_refptr<StaticBitmapImage> image_bitmap = context_->GetImage();',
     'scoped_refptr<StaticBitmapImage> image_bitmap =\n      MetaBrowserProtectCanvasExport(context_->GetImage(), ExecutionContext::From(script_state));'),
])
patch('third_party/blink/renderer/modules/canvas/canvas2d/base_rendering_context_2d.cc', [
    ('  scoped_refptr<StaticBitmapImage> snapshot = GetImage();',
     '''  scoped_refptr<StaticBitmapImage> snapshot = GetImage();
  if (snapshot && GetTopExecutionContext() &&
      GetTopExecutionContext()->CanvasNoiseToken()) {
    auto protected_snapshot =
        MetaBrowserProtectCanvasExport(snapshot, GetTopExecutionContext());
    if (!protected_snapshot) {
      exception_state.ThrowDOMException(DOMExceptionCode::kNotSupportedError,
          "Canvas privacy readback exceeds the protection budget or allocation failed.");
      return nullptr;
    }
    snapshot = std::move(protected_snapshot);
  }'''),
])
print('Staged native Canvas readback/export privacy')
