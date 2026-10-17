#!/usr/bin/env python3
"""Pinned private-scratch WebGL color readback, including PBO transfers.

Preview by default; stages only the two WebGL implementation files and one
class header. All writes follow a complete preflight; no network/build actions.
"""
import argparse
import hashlib
import json
from pathlib import Path


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
    directory = 'third_party/blink/renderer/modules/webgl/'

    def edit(name, old, new, label):
        path = directory + name
        if path not in before:
            p = root / path
            if p.is_symlink() or not p.resolve().is_relative_to(root):
                raise ValueError('Path escapes checkout')
            before[path] = p.read_text()
            after[path] = before[path]
        text = after[path]
        marker = '// METABROWSER_WEBGL_READBACK_V1: ' + label + '\n'
        value = marker + new
        if value in text:
            if text.count(value) != 1:
                raise ValueError('Duplicate patch: ' + label)
            return
        if marker in text or text.count(old) != 1:
            raise ValueError('Pinned WebGL source drift: ' + label)
        after[path] = text.replace(old, value, 1)

    edit('webgl_rendering_context_base.h',
         '  // Helper implementing readPixels for WebGL 1.0 and 2.0.',
         '''  bool MetaBrowserReadPixels(GLint x, GLint y, GLsizei width,
      GLsizei height, GLenum format, GLenum type,
      base::span<uint8_t> destination, GLuint pixel_pack_buffer,
      GLintptr pixel_pack_offset);
  // Helper implementing readPixels for WebGL 1.0 and 2.0.''', 'declaration')
    edit('webgl_rendering_context_base.cc',
         '#include "third_party/blink/renderer/modules/webgl/webgl_rendering_context_base.h"',
         '''#include "third_party/blink/renderer/modules/webgl/webgl_rendering_context_base.h"
#include <array>
#include "third_party/blink/renderer/core/canvas_interventions/metabrowser_surface_privacy.h"
#include "third_party/skia/include/core/SkBitmap.h"''', 'dependencies')
    implementation = (Path(__file__).resolve().parents[1] /
                      'chromium/privacy/metabrowser_webgl_readback.inc').read_text()
    old = 'void WebGLRenderingContextBase::readPixels(\n'
    path = directory + 'webgl_rendering_context_base.cc'
    text = after[path]
    legacy_versions = {
        'private-scratch': '9f0b57e1debce8bcf57149e35e048207a32f30740cd5545a4425a96de3b48caf',
        'private-scratch-v2': '5f315537a308b75b40adf575baa938cac6be98377875d235880ea20f02b36c54',
    }
    for version, digest in legacy_versions.items():
        legacy_marker = '// METABROWSER_WEBGL_READBACK_V1: ' + version + '\n'
        if legacy_marker not in text:
            continue
        if text.count(legacy_marker) != 1:
            raise ValueError('Duplicate legacy readback implementation')
        begin = text.index(legacy_marker)
        body_start = begin + len(legacy_marker)
        end = text.index(old, body_start)
        legacy = text[body_start:end]
        if not legacy.endswith('\n') or hashlib.sha256(legacy[:-1].encode()).hexdigest() != digest:
            raise ValueError('Legacy readback implementation drift')
        after[path] = (text[:begin] +
                       '// METABROWSER_WEBGL_READBACK_V1: private-scratch-v3\n' +
                       implementation + '\n' + text[end:])
        break
    edit('webgl_rendering_context_base.cc', old, implementation + '\n' + old, 'private-scratch-v3')
    old = '    ContextGL()->ReadPixels(x, y, width, height, format, type, data);'
    edit('webgl_rendering_context_base.cc', old, '''    const auto output = UNSAFE_BUFFERS(base::span(data,
        static_cast<size_t>(buffer_size.ValueOrDie())));
    if (MetaBrowserReadPixels(x, y, width, height, format, type, output, 0, 0))
      return;
''' + old, 'array-boundary')
    old = '''    ContextGL()->ReadPixels(x, y, width, height, format, type,
                            reinterpret_cast<void*>(offset));'''
    edit('webgl2_rendering_context_base.cc', old,
         '''    if (MetaBrowserReadPixels(x, y, width, height, format, type,
            {}, buffer->Object(), static_cast<GLintptr>(offset))) return;
''' + old, 'pbo-boundary')
    for path, value in before.items():
        if (root / path).read_text() != value:
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
