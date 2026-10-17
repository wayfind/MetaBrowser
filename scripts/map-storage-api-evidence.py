#!/usr/bin/env python3
"""Join partial runtime evidence to exact generated IDL IDs, never certify all APIs."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--catalog', type=Path, required=True)
    p.add_argument('--protected', type=Path, required=True)
    p.add_argument('--off', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    catalog = json.loads(a.catalog.read_text())
    evidence = []
    worker_mutations = []
    incognito_lifecycle = []
    for path, mode in [(a.protected, 'balanced'), (a.off, 'off')]:
        data = json.loads(path.read_text())
        assert data['passed'] is True and data['privacy'] == mode
        assert data['framework_sha256'] == catalog['framework_sha256']
        assert data['full_storage_privacy_proven'] is False
        worker_mutations.append(data.get('worker_mutations_proven') is True)
        incognito_lifecycle.append(data.get('incognito_storage_lifecycle_proven') is True)
        evidence.append({'path': str(path), 'sha256': sha(path), 'pointer': '/passed',
                         'framework_sha256': data['framework_sha256'], 'scope': data['scope']})
    assert worker_mutations[0] == worker_mutations[1], 'Unequal execution scope across privacy controls'
    assert incognito_lifecycle[0] == incognito_lifecycle[1], 'Unequal lifecycle scope across privacy controls'
    # Different bound receipts cover different realm sets. In particular the
    # quota-pressure fixture is Window/DedicatedWorker, not the seven-realm
    # lifecycle fixture. Do not invent iframe/five-worker coverage from the
    # absence of a worker_mutations_proven flag.
    limits = 'Partial runtime evidence covers only the realm, argument and lifecycle classes described by each bound receipt.'
    limits += ' No unlisted realms, overloads, physical storage inference, permissions or all-failure-path coverage is implied.'
    methods = {
        'StorageManager': ['estimate', 'getDirectory'],
        'StorageBucketManager': ['open'],
        'StorageBucket': ['estimate', 'indexedDB'],
        'IDBFactory': ['open'],
        'IDBDatabase': ['createObjectStore', 'transaction', 'close'],
        'IDBObjectStore': ['get', 'put', 'delete'],
        'CacheStorage': ['open'],
        'Cache': ['match', 'put', 'delete'],
        'FileSystemDirectoryHandle': ['getFileHandle', 'removeEntry'],
        'FileSystemFileHandle': ['createWritable', 'getFile'],
        'FileSystemWritableFileStream': ['write'],
    }
    rows = []
    for owner, names in methods.items():
        for name in names:
            members = [m for m in catalog['members'] if m['owner'] == owner and m['name'] == name]
            assert members, 'Unknown IDL member: ' + owner + '.' + name
            for member in members:
                rows.append({'member_id': member['id'], 'owner': owner, 'name': name,
                             'declaration_source': member['source'],
                             'declaration_sha256': catalog['source_sha256'][member['source']],
                             'review_status': 'partial_runtime_evidence', 'evidence': evidence,
                             'implementation_privacy_review': 'pending',
                             'limits': limits})
    out = {'schema_version': 1, 'catalog_sha256': sha(a.catalog),
           'framework_sha256': catalog['framework_sha256'], 'members': rows,
           'worker_mutations_proven': all(worker_mutations),
           'incognito_storage_lifecycle_proven': all(incognito_lifecycle),
           'partially_mapped_member_count': len(rows), 'verified_member_count': 0,
           'full_privacy_coverage_proven': False,
           'note': 'A separate evidence overlay; the generated catalog remains immutable and unclassified.'}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'partially_mapped_members': len(rows), 'verified_members': 0, 'full_privacy_coverage_proven': False}))


if __name__ == '__main__':
    main()
