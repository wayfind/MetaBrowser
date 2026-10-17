#!/usr/bin/env python3
"""Validate the complete SDK before compiling a native consumer."""
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
m = json.loads((root / 'manifest.json').read_text())
assert (m['schema_version'], m['vendor'], m['name']) == (1, 'metask', 'agentcore')
assert m['target']['id'] == 'aarch64-macos'
c = m['contract']
assert (c['binary_abi_version'], c['binary_abi_revision'], c['binary_abi_table_size']) == (1, 21, 64)
lock = json.loads((pathlib.Path(__file__).resolve().parents[1] / 'upstream.lock.json').read_text())
assert m['source']['commit'] == lock['metacodes']['sdk_commit'], 'Unpinned SDK commit'
assert hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest() == lock['metacodes']['sdk_manifest_sha256'], 'Unpinned SDK manifest'
assert m['files'], 'Empty SDK manifest'
for f in m['files']:
    p = (root / f['path']).resolve()
    assert p.is_relative_to(root), 'Path escapes bundle'
    assert hashlib.sha256(p.read_bytes()).hexdigest() == f['sha256'], f['path']
print('Complete AgentCore SDK validated:', m['source']['commit'])
