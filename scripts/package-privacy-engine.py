#!/usr/bin/env python3
"""Build the complete engine app after its verified privacy framework build.

WebUI changes also require resource packs and the native bundle dependency
graph. This does not add the separately pinned AgentCore SDK or Zig plugin.
"""
import argparse
import hashlib
import json
import os
import pathlib
import struct
import subprocess
import sys

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('source', type=pathlib.Path)
p.add_argument('--out', default='out/metabrowser-mac-arm64')
p.add_argument('--jobs', type=int, default=128)
p.add_argument('--baseline-manifest', type=pathlib.Path,
               help='require every path/symlink from a previously verified engine bundle')
p.add_argument('--verify-only', action='store_true', help='verify a bundle already built by Ninja')
a = p.parse_args()
if not 1 <= a.jobs <= 128:
    p.error('jobs must be between 1 and 128')
root = a.source.resolve()
project = pathlib.Path(__file__).resolve().parents[1]
out = root / a.out
logs = out / 'metabrowser-privacy'
receipt_path = logs / 'receipt.json'
receipt_bytes = receipt_path.read_bytes()
receipt = json.loads(receipt_bytes)
baseline_bytes = a.baseline_manifest.read_bytes() if a.baseline_manifest else None


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def check_inputs():
    if receipt_path.read_bytes() != receipt_bytes:
        raise SystemExit('Framework receipt changed during app packaging')
    for relative, expected in receipt['sources'].items():
        if digest(root / relative) != expected:
            raise SystemExit('Engine source changed: ' + relative)
    for relative, expected in receipt['staging_scripts'].items():
        if digest(project / relative) != expected:
            raise SystemExit('Engine staging script changed: ' + relative)
    if a.baseline_manifest and a.baseline_manifest.read_bytes() != baseline_bytes:
        raise SystemExit('Baseline bundle manifest changed')


def loadable_sections(path):
    """Compare actual Mach-O sections while allowing bundle signing/stripping."""
    data = path.read_bytes()
    if struct.unpack_from('<I', data)[0] != 0xfeedfacf:
        raise SystemExit('Expected a thin little-endian 64-bit Mach-O framework')
    count = struct.unpack_from('<I', data, 16)[0]
    offset = 32
    sections = {}
    for _ in range(count):
        command, size = struct.unpack_from('<II', data, offset)
        if size < 8 or offset + size > len(data):
            raise SystemExit('Invalid Mach-O load command')
        if command == 0x19:
            nsects = struct.unpack_from('<I', data, offset + 64)[0]
            if 72 + 80 * nsects > size:
                raise SystemExit('Invalid Mach-O section table')
            for i in range(nsects):
                start = offset + 72 + i * 80
                section = data[start:start + 16].split(b'\0')[0].decode('ascii')
                segment = data[start + 16:start + 32].split(b'\0')[0].decode('ascii')
                address, length, file_offset = struct.unpack_from('<QQI', data, start + 32)
                flags = struct.unpack_from('<I', data, start + 64)[0]
                if segment == '__LINKEDIT' or flags & 0x02000000:
                    continue
                zero_fill = flags & 0xff in (1, 0xc, 0x12)
                if not zero_fill and file_offset + length > len(data):
                    raise SystemExit('Mach-O section escapes file')
                key = segment + '/' + section
                if key in sections:
                    raise SystemExit('Duplicate Mach-O section')
                sections[key] = {'address': address, 'size': length, 'flags': flags,
                                 'sha256': None if zero_fill else hashlib.sha256(
                                     data[file_offset:file_offset + length]).hexdigest()}
        offset += size
    if not sections:
        raise SystemExit('No Mach-O loadable sections')
    return sections


check_inputs()
tool_paths = [pathlib.Path(__file__).resolve(), project / 'scripts/app-manifest.py']
tool_hashes = {str(path.relative_to(project)): digest(path) for path in tool_paths}
linked = out / 'obj/chrome/chrome_framework_shared_library/Chromium Framework'
if digest(linked) != receipt['framework_sha256']:
    raise SystemExit('Linked framework differs from its receipt')
ninja = root / 'third_party/ninja/ninja'
if not a.verify_only:
    with (logs / 'app-package-build.log').open('wb') as stream:
        subprocess.run([str(ninja), '-C', str(out), '-j', str(a.jobs), 'chrome'],
                       cwd=root, stdout=stream, stderr=stream, check=True)
check_inputs()
for relative, expected in tool_hashes.items():
    if digest(project / relative) != expected:
        raise SystemExit('App packaging tool changed: ' + relative)
if digest(linked) != receipt['framework_sha256']:
    raise SystemExit('App packaging unexpectedly changed the linked engine')
app = out / 'Chromium.app'
packaged = app / 'Contents/Frameworks/Chromium Framework.framework/Versions/154.0.8037.97/Chromium Framework'
# Require byte identity, including runtime load commands, fixups and CPU type.
# If a future bundle rule signs/strips the image, stop for explicit review rather
# than treating section equality as proof of runtime equivalence.
if digest(packaged) != receipt['framework_sha256']:
    raise SystemExit('Packaged framework differs byte-for-byte; inspect signing/stripping before release')
framework_root = app / 'Contents/Frameworks/Chromium Framework.framework'
version_root = framework_root / 'Versions/154.0.8037.97'
required = [app / 'Contents/Info.plist', app / 'Contents/MacOS/Chromium', packaged,
            version_root / 'Resources/Info.plist']
required.extend(version_root / 'Resources' / name for name in (
    'resources.pak', 'chrome_100_percent.pak', 'chrome_200_percent.pak',
    'icudtl.dat', 'snapshot_blob.bin'))
executables = [app / 'Contents/MacOS/Chromium']
for suffix in ('', ' (Renderer)', ' (GPU)', ' (Alerts)'):
    helper = 'Chromium Helper' + suffix
    executable = version_root / 'Helpers' / (helper + '.app') / 'Contents/MacOS' / helper
    required.append(executable)
    executables.append(executable)
for path in required:
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit('Missing required bundle artifact: ' + str(path.relative_to(app)))
for executable in executables:
    if not executable.stat().st_mode & 0o111 or not os.access(executable, os.X_OK):
        raise SystemExit('Non-executable bundle launcher/helper: ' + str(executable.relative_to(app)))
for link in app.rglob('*'):
    if link.is_symlink() and (not link.exists() or not link.resolve().is_relative_to(app.resolve())):
        raise SystemExit('Broken or external bundle symlink: ' + str(link.relative_to(app)))
for relative, expected in {
    'Chromium Framework': packaged, 'Resources': version_root / 'Resources',
    'Helpers': version_root / 'Helpers', 'Libraries': version_root / 'Libraries',
    'Versions/Current': version_root,
}.items():
    if not (framework_root / relative).is_symlink() or (framework_root / relative).resolve() != expected.resolve():
        raise SystemExit('Unexpected runtime framework symlink: ' + relative)
if baseline_bytes:
    for entry in json.loads(baseline_bytes)['files']:
        path = app / entry['path']
        if not path.resolve().is_relative_to(app.resolve()) or not path.exists():
            raise SystemExit('Missing baseline engine artifact: ' + entry['path'])
        if 'symlink' in entry and (not path.is_symlink() or str(path.readlink()) != entry['symlink']):
            raise SystemExit('Changed baseline engine symlink: ' + entry['path'])
        if 'sha256' in entry and (path.is_symlink() or not path.is_file() or path.stat().st_size == 0):
            raise SystemExit('Invalid baseline engine regular file: ' + entry['path'])
sections = loadable_sections(linked)
if loadable_sections(packaged) != sections:
    raise SystemExit('Packaged framework loadable sections differ from the verified link')
manifest = subprocess.check_output([sys.executable, str(project / 'scripts/app-manifest.py'), str(app)])
(logs / 'engine-app-manifest.json').write_bytes(manifest)
value = {'kind': 'complete-native-privacy-engine-app',
         'verification_only': a.verify_only,
         'framework_build_receipt_sha256': hashlib.sha256(receipt_bytes).hexdigest(),
         'linked_framework_sha256': receipt['framework_sha256'],
         'packaged_framework_sha256': digest(packaged),
         'byte_identical_framework': True,
         'baseline_manifest_sha256': hashlib.sha256(baseline_bytes).hexdigest() if baseline_bytes else None,
         'loadable_sections_sha256': hashlib.sha256(json.dumps(sections, sort_keys=True).encode()).hexdigest(),
         'loadable_section_count': len(sections),
         'engine_app_manifest_sha256': hashlib.sha256(manifest).hexdigest(),
         'packaging_tools': tool_hashes}
(logs / 'app-package-receipt.json').write_text(json.dumps(value, indent=2) + '\n')
print('Complete engine app packaged and verified:', logs / 'app-package-receipt.json')
