#!/usr/bin/env python3
"""Stage native token-gated labels without modifying device IDs or permissions."""
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
prefix = 'third_party/blink/renderer/modules/mediastream/'
header = prefix + 'metabrowser_media_labels.h'
original, changes = {}, {}


def edit(name, old, new, previous=None):
    name = prefix + name
    path = root / name
    assert not path.is_symlink() and path.resolve().is_relative_to(root)
    if name not in original:
        original[name] = path.read_text()
    text = changes.get(name, original[name])
    if new not in text:
        anchor = previous if previous is not None and previous in text else old
        if text.count(anchor) != 1:
            raise SystemExit('Pinned media label drift: ' + name + ': ' + old[:80])
        text = text.replace(anchor, new, 1)
    else:
        assert text.count(new) == 1
    changes[name] = text


for name in ('media_devices.cc', 'media_stream_track_impl.cc'):
    own = '#include "' + prefix + name.replace('.cc', '.h') + '"'
    edit(name, own, own + '\n#include "' + header + '"')

edit('BUILD.gn', 'blink_modules_sources("mediastream") {\n  sources = [',
     'blink_modules_sources("mediastream") {\n  sources = [\n    "metabrowser_media_labels.h",')
edit('media_devices.cc',
     '      String device_label = String::FromUtf8(device_info.label);',
     '''      // METABROWSER_MEDIA_LABELS_V1: snapshot aliases in the JS objects.
      const char* alias_kind =
          device_type == mojom::blink::MediaDeviceType::kMediaVideoInput ? "Camera" :
          device_type == mojom::blink::MediaDeviceType::kMediaAudioInput ? "Microphone" : "Speaker";
      String device_label = MetaBrowserMediaLabel(
          GetExecutionContext(), String::FromUtf8(device_info.label),
          String::FromUtf8(device_info.device_id), alias_kind);''')
edit('media_devices.cc',
     '        String::FromUtf8(result->device_info.label),',
     '''        MetaBrowserMediaLabel(GetExecutionContext(),
            String::FromUtf8(result->device_info.label),
            String::FromUtf8(result->device_info.device_id), "Speaker"),''')
edit('media_stream_track_impl.h',
     '  const Member<MediaStreamComponent> component_;',
     '''  // Null means native; a captured alias survives stop, clone and detach.
  String metabrowser_label_;
  const Member<MediaStreamComponent> component_;''', previous=
     '''  // Freeze policy; cache the public alias once the capture source is ready.
  bool metabrowser_protected_ = false;
  mutable String metabrowser_label_;
  const Member<MediaStreamComponent> component_;''')
edit('media_stream_track_impl.cc',
     '''  const std::optional<const MediaStreamDevice> source_device = device();
  if (source_device && source_device->display_media_info) {''',
     '''  const std::optional<const MediaStreamDevice> source_device = device();
  // METABROWSER_MEDIA_LABELS_V1: capture policy before the owner can disappear.
  // Synthetic/remote tracks and explicit desktop capture keep their own labels.
  if (context && context->CanvasNoiseToken() && !component_->Remote() &&
      source_device &&
      (source_device->type == mojom::blink::MediaStreamType::DEVICE_AUDIO_CAPTURE ||
       source_device->type == mojom::blink::MediaStreamType::DEVICE_VIDEO_CAPTURE)) {
    MediaStreamTrackPlatform::Settings label_settings;
    component_->GetSettings(label_settings);
    metabrowser_label_ = MetaBrowserMediaAlias(
        source_device->type == mojom::blink::MediaStreamType::DEVICE_AUDIO_CAPTURE
            ? "Microphone" : "Camera", label_settings.device_id);
  }
  if (source_device && source_device->display_media_info) {''', previous=
     '''  // METABROWSER_MEDIA_LABELS_V2: device/platform details may arrive after
  // construction. Freeze protection now and derive the label lazily from the
  // same public Source::Id used by getSettings(), never a native device name.
  metabrowser_protected_ = context && context->CanvasNoiseToken().has_value();
  const std::optional<const MediaStreamDevice> source_device = device();
  if (source_device && source_device->display_media_info) {''')
edit('media_stream_track_impl.cc',
     '''String MediaStreamTrackImpl::label() const {
  return component_->GetSourceName();
}''',
     '''String MediaStreamTrackImpl::label() const {
  return metabrowser_label_.IsNull() ? component_->GetSourceName() : metabrowser_label_;
}''', previous=
     '''String MediaStreamTrackImpl::label() const {
  if (!metabrowser_label_.IsNull()) return metabrowser_label_;
  if (metabrowser_protected_ && !component_->Remote()) {
    const auto source_device = device();
    // Known synthetic/desktop sources preserve their application-provided
    // labels. Missing/stopped sources fail closed to a public-ID alias.
    if (!source_device ||
        source_device->type == mojom::blink::MediaStreamType::DEVICE_AUDIO_CAPTURE ||
        source_device->type == mojom::blink::MediaStreamType::DEVICE_VIDEO_CAPTURE) {
      metabrowser_label_ = MetaBrowserMediaAlias(
          component_->GetSourceType() == MediaStreamSource::kTypeAudio
              ? "Microphone" : "Camera", component_->Source()->Id());
      return metabrowser_label_;
    }
  }
  return component_->GetSourceName();
}''')
edit('media_stream_track_impl.cc',
     '''void MediaStreamTrackImpl::CloneInternal(MediaStreamTrackImpl* cloned_track) {
  DCHECK(cloned_track);''',
     '''void MediaStreamTrackImpl::CloneInternal(MediaStreamTrackImpl* cloned_track) {
  DCHECK(cloned_track);
  if (!metabrowser_label_.IsNull())
    cloned_track->metabrowser_label_ = metabrowser_label_;''', previous=
     '''void MediaStreamTrackImpl::CloneInternal(MediaStreamTrackImpl* cloned_track) {
  DCHECK(cloned_track);
  cloned_track->metabrowser_protected_ |= metabrowser_protected_;
  if (!metabrowser_label_.IsNull())
    cloned_track->metabrowser_label_ = metabrowser_label_;''')

path = root / header
assert not path.is_symlink() and path.resolve().is_relative_to(root)
original[header] = path.read_text() if path.exists() else None
changes[header] = (Path(__file__).resolve().parents[1] / 'chromium/privacy/metabrowser_media_labels.h').read_text()
for name, before in original.items():
    current = (root / name).read_text() if (root / name).exists() else None
    assert current == before, 'Source changed during media label preflight'
if args.apply:
    for name, text in changes.items():
        if original[name] != text:
            (root / name).write_text(text)
print(json.dumps({'scope': 'native-media-device-and-local-track-labels', 'applied': args.apply,
                  'all_files': {name: hashlib.sha256(text.encode()).hexdigest() for name, text in changes.items()}}))
