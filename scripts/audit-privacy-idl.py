#!/usr/bin/env python3
"""Validate the generated API inventory against its exact engine receipt.

Integrity is distinct from coverage: declarations remain unreviewed until a
separate runtime/policy evidence ledger establishes their behavior.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


def digest(data):
    return hashlib.sha256(data).hexdigest()


def audit(catalog, receipt, receipt_bytes):
    errors = []
    def check(condition, message):
        if not condition:
            errors.append(message)
    check(catalog.get('kind') == 'generated-Blink-potential-surface-catalog', 'Wrong catalog kind')
    check(catalog.get('schema_version') == 1, 'Unsupported schema')
    check(catalog.get('target') == '154.0.8037.97/mac-arm64', 'Wrong source target')
    check(receipt.get('target') == 'aarch64-macos.13.0', 'Wrong build target')
    check(catalog.get('build_receipt_sha256') == digest(receipt_bytes), 'Receipt digest mismatch')
    check(bool(catalog.get('framework_sha256')) and catalog.get('framework_sha256') == receipt.get('framework_sha256'), 'Engine mismatch')
    check(catalog.get('privacy_coverage_proven') is False, 'Inventory cannot prove protection')
    types, members, sources = catalog.get('types', []), catalog.get('members', []), catalog.get('source_sha256', {})
    check(bool(types) and bool(members) and bool(sources), 'Empty inventory')
    owners = {(t['kind'], t['name']) for t in types}
    check(len(owners) == len(types), 'Duplicate owner')
    counts = Counter(t['kind'] for t in types)
    counts.update(types=len(types), members=len(members), source_files=len(sources))
    check(dict(counts) == catalog.get('counts'), 'Count mismatch')
    for path, sha in sources.items():
        check(not Path(path).is_absolute() and '..' not in Path(path).parts, 'Unconfined source path')
        check(bool(re.fullmatch('[0-9a-f]{64}', sha)), 'Invalid source digest')
    ids = set()
    for row in [*types, *members]:
        check(row.get('source') in sources, 'Unbound declaration source')
    for row in members:
        check((row['owner_kind'], row['owner']) in owners, 'Missing owner')
        payload = {k: v for k, v in row.items() if k not in ('id', 'review_status')}
        check(row.get('id') == digest(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()), 'Member digest mismatch')
        check(row.get('id') not in ids, 'Duplicate member')
        ids.add(row.get('id'))
        check(row.get('review_status') == 'unclassified', 'Review status requires a separate evidence ledger')
    conditional = [m['id'] for m in members if m.get('exposure') and any(m['exposure'].get(k) for k in ('runtime_features', 'origin_trials', 'context_features', 'coi_or_runtime_features'))]
    return {'inventory_integrity_passed': not errors, 'errors': sorted(set(errors)),
            'counts': dict(counts), 'conditional_member_count': len(conditional),
            'unreviewed_members': len(members), 'privacy_coverage_proven': False,
            'framework_sha256': catalog.get('framework_sha256'),
            'note': 'Includes disabled features and dictionary schemas; does not establish runtime availability, policy or protection.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--catalog', type=Path, required=True)
    p.add_argument('--receipt', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    raw, receipt_raw = a.catalog.read_bytes(), a.receipt.read_bytes()
    result = audit(json.loads(raw), json.loads(receipt_raw), receipt_raw)
    result['catalog_sha256'] = digest(raw)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    # Create a private file atomically, including on the first write.
    import os
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=a.output.parent, prefix=a.output.name + '.')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        os.replace(tmp, a.output)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result['inventory_integrity_passed'] else 1)


if __name__ == '__main__':
    main()
