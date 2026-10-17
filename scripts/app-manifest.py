#!/usr/bin/env python3
"""Hash application contents and preserve symlink identity across transfer."""
import argparse, hashlib, json, pathlib
p = argparse.ArgumentParser()
p.add_argument('app', type=pathlib.Path)
p.add_argument('--check', type=pathlib.Path)
a = p.parse_args()
items = []
for f in sorted(a.app.rglob('*')):
    name = f.relative_to(a.app).as_posix()
    if f.is_symlink():
        items.append({'path': name, 'symlink': str(f.readlink())})
    elif f.is_file():
        h = hashlib.sha256()
        with f.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''): h.update(chunk)
        items.append({'path': name, 'sha256': h.hexdigest()})
if a.check:
    assert items == json.loads(a.check.read_text())['files'], 'Application contents differ'
    print(f'Full application transport verified: {len(items)} files/symlinks')
else:
    print(json.dumps({'files': items}, indent=2))
