#!/usr/bin/env python3
"""Protect canvas-to-media handoffs before crop, codec, clone or transfer.

Copies synthetic canvas images only. Direct camera/video/image/PCM sources,
permission checks and compositor canvas storage remain unchanged.
"""
import argparse
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=Path)
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()
root = args.source.resolve(strict=True)
assert (root / 'chrome/VERSION').read_text().splitlines() == ['MAJOR=154', 'MINOR=0', 'BUILD=8037', 'PATCH=97']
changes = {}
prefix = 'third_party/blink/renderer/'


def edit(relative, old, new):
    relative = prefix + relative
    path = root / relative
    assert not path.is_symlink()
    text = changes.get(relative, path.read_text())
    changes.setdefault(relative, text)
    if new in text:
        assert text.count(new) == 1
        return
    if text.count(old) != 1:
        raise SystemExit('Pinned media boundary drift: ' + relative + ': ' + old[:70])
    changes[relative] = text.replace(old, new, 1)


header = '#include "third_party/blink/renderer/core/canvas_interventions/metabrowser_canvas_noise.h"'
for relative in ('core/imagebitmap/image_bitmap.cc', 'modules/webcodecs/video_frame.cc'):
    name = relative.rsplit('/', 1)[-1].replace('.cc', '.h')
    own = '#include "' + prefix + relative.rsplit('/', 1)[0] + '/' + name + '"'
    edit(relative, own, own + '\n' + header)

for kind, variable, raw in [('HTMLCanvasElement', 'canvas', 'image_input'), ('OffscreenCanvas', 'offscreen_canvas', 'raw_input')]:
    # Only these two constructors take synthetic canvases. Protect the complete
    # bitmap before ParseOptions applies crop/resize/flip/alpha transformations.
    if kind == 'HTMLCanvasElement':
        old = '''  scoped_refptr<StaticBitmapImage> input =
      To<StaticBitmapImage>(image_input.get());

  const ParsedOptions parsed_options = ParseOptions(options, crop_rect, input);'''
        new = '''  scoped_refptr<StaticBitmapImage> input =
      To<StaticBitmapImage>(image_input.get());
  // METABROWSER_MEDIA_V1: synthetic canvas handoff, before transforms.
  input = MetaBrowserProtectCanvasExport(input, canvas->GetExecutionContext());
  if (!input) return;

  const ParsedOptions parsed_options = ParseOptions(options, crop_rect, input);'''
    else:
        old = '''  raw_input = nullptr;

  if (status != kNormalSourceImageStatus)
    return;

  const ParsedOptions parsed_options = ParseOptions(options, crop_rect, input);'''
        new = '''  raw_input = nullptr;

  if (status != kNormalSourceImageStatus)
    return;
  // METABROWSER_MEDIA_V1: protect the full worker canvas before transforms.
  input = MetaBrowserProtectCanvasExport(input, offscreen_canvas->GetTopExecutionContext());
  if (!input) return;

  const ParsedOptions parsed_options = ParseOptions(options, crop_rect, input);'''
    edit('core/imagebitmap/image_bitmap.cc', old, new)

edit('modules/webcodecs/video_frame.cc',
     '  const auto paint_image = image->PaintImageForCurrentFrame();',
     '''  // METABROWSER_MEDIA_V1: protect synthetic canvas once at the handoff.
  // Descendant VideoFrame clones, transfers, copyTo and codecs use these same
  // pixels. Direct video, camera, decoded image and caller buffers stay native.
  if (image_source->IsCanvasElement() || image_source->IsOffscreenCanvas()) {
    image = MetaBrowserProtectCanvasExport(
        To<StaticBitmapImage>(image.get()), ExecutionContext::From(script_state));
    if (!image) {
      exception_state.ThrowDOMException(DOMExceptionCode::kNotSupportedError,
          "Canvas media export exceeds the privacy protection budget.");
      return nullptr;
    }
  }
  const auto paint_image = image->PaintImageForCurrentFrame();''')

edit('core/offscreencanvas/offscreen_canvas.cc',
     '''  if (!image) {
    // Undocumented exception (not in spec).''',
     '''  // METABROWSER_MEDIA_V1: TransferToImageBitmap already resets the source;
  // protect a private copy without changing origin-clean state or the source.
  if (image && GetTopExecutionContext() &&
      GetTopExecutionContext()->CanvasNoiseToken()) {
    const bool clean = image->OriginClean();
    auto protected_image = MetaBrowserProtectCanvasExport(
        image->BitmapImage(), GetTopExecutionContext());
    image->close();
    if (!protected_image) {
      exception_state.ThrowDOMException(DOMExceptionCode::kNotSupportedError,
          "Canvas media export exceeds the privacy protection budget.");
      return nullptr;
    }
    protected_image->SetOriginClean(clean);
    image = MakeGarbageCollected<ImageBitmap>(std::move(protected_image));
  }
  if (!image) {
    // Undocumented exception (not in spec).''')

edit('core/html/canvas/html_canvas_element.cc',
     '''    if (context_ && (context_color_is_opaque || can_discard_alpha) &&
        base::FeatureList::IsEnabled(kOneCopyCanvasCapture)) {''',
     '''    // METABROWSER_MEDIA_V1: protected capture must use the private image
    // path; a direct GPU-to-video copy would bypass canvas export protection.
    if (!(GetExecutionContext() && GetExecutionContext()->CanvasNoiseToken()) &&
        context_ && (context_color_is_opaque || can_discard_alpha) &&
        base::FeatureList::IsEnabled(kOneCopyCanvasCapture)) {''')
edit('core/html/canvas/html_canvas_element.cc',
     '''      source_image = GetSourceImageForCanvasInternal(&status);
      if (status != kNormalSourceImageStatus)
        continue;''',
     '''      source_image = GetSourceImageForCanvasInternal(&status);
      if (status != kNormalSourceImageStatus)
        continue;
      // METABROWSER_MEDIA_V1: same protected pixels feed every capture listener,
      // MediaRecorder, track processor and WebRTC sender for this canvas frame.
      source_image = MetaBrowserProtectCanvasExport(source_image, GetExecutionContext());
      if (!source_image) continue;''')

# WebGPU's external-image copy is also a script-readable canvas export:
# copyTextureToBuffer/mapAsync otherwise recovers the original unprotected
# pixels. Patch only synthetic canvas hosts, after upstream taint validation
# and before the queue crops/uploads the snapshot. Caller ImageData, decoded
# images, video and already protected ImageBitmap/VideoFrame stay unchanged.
relative = 'modules/webgpu/external_image_utils.cc'
own = '#include "third_party/blink/renderer/modules/webgpu/external_image_utils.h"'
edit(relative, own, own + '\n' + header)
edit(relative,
     '''  return GetExternalImageSourceFromCanvasImageSource(canvas, dst_info,
                                                     exception_state);''',
     '''  // METABROWSER_MEDIA_WEBGPU_V1: protect the complete canvas before crop.
  auto result = GetExternalImageSourceFromCanvasImageSource(
      canvas, dst_info, exception_state);
  if (!result) return {};
  result->image = MetaBrowserProtectCanvasExport(
      result->image, canvas->GetTopExecutionContext());
  if (!result->image) {
    exception_state.ThrowDOMException(DOMExceptionCode::kNotSupportedError,
        "Canvas GPU export exceeds the privacy protection budget.");
    return {};
  }
  return result;''')
edit(relative,
     '''#else
  bool forceReadback = false;
#endif
  if (forceReadback) {''',
     '''#else
  // METABROWSER_MEDIA_WEBGPU_CPU_V1: software adapters cannot import the
  // platform GPU mailbox reliably. Upload the private CPU pixels explicitly.
  wgpu::AdapterInfo metabrowser_adapter_info = {};
  device.GetAdapter().GetInfo(&metabrowser_adapter_info);
  bool forceReadback =
      metabrowser_adapter_info.adapterType == wgpu::AdapterType::CPU;
#endif
  if (forceReadback) {''')

if args.apply:
    for relative, text in changes.items():
        if (root / relative).read_text() != text:
            (root / relative).write_text(text)
print(json.dumps({'scope': 'synthetic-canvas-media-handoffs', 'applied': args.apply,
                  'all_files': {relative: hashlib.sha256(text.encode()).hexdigest() for relative, text in changes.items()}}))
