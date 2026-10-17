"""Independent raw lifecycle replay; not complete storage/privacy acceptance."""
import argparse
import json
from pathlib import Path
from identity_surface_runner import digest
from storage_mutation_runner import validate


def verify(report, framework_sha256):
    assert report['incognito'] is True
    assert report['completed'] is True and report['passed'] is True
    assert not report.get('error') and report['paid_model_calls'] == 0
    assert report['framework_sha256'] == framework_sha256
    rows = report['iterations']
    phases = [('seed', 'a', 'write', True), ('restart_read', 'a', 'read', False),
              ('independent_profile', 'b', 'read', False), ('clear', 'a', 'delete', False),
              ('restart_after_clear', 'a', 'read', False)]
    assert len(rows) == len(phases)
    assert len({r['pid'] for r in rows}) == 5
    count = 0
    for row, (name, profile, operation, markers) in zip(rows, phases):
        assert row['name'] == name and row['profile'] == profile
        assert type(row['pid']) is int and row['pid'] > 0
        assert row['clean_shutdown'] is True
        raw = row['observations']
        assert raw['nonDefaultBrowserContext'] is True
        assert isinstance(raw['browserContextId'], str) and raw['browserContextId']
        assert isinstance(raw['regularBrowserContextId'], str) and raw['regularBrowserContextId']
        assert raw['browserContextId'] != raw['regularBrowserContextId']
        assert raw['phase'] == operation
        result = validate(raw, markers)
        assert result['passed'], result['checks']
        assert row['checks'] == result['checks'] and row['passed'] is True
        count += len(result['checks'])
        for context, origin in {'firstA': 'http://127.0.0.1:18878', 'aUnderB': 'http://127.0.0.1:18878',
                                'firstB': 'http://localhost:18878', 'bUnderA': 'http://localhost:18878'}.items():
            assert raw['contexts'][context]['origin'] == origin
            assert raw['contexts'][context]['operation'] == operation
            value = raw['contexts'][context]
            for realm in [value, *value['workers'].values(),
                          *(sample for records in value['mutationTrace'].values() for sample in records.values())]:
                estimate = realm['estimate']
                assert estimate['quota'] - estimate['usage'] == 10 * 1024**3
                assert realm['bucketEstimate']['quota'] == 524288
    return {'passed': True, 'framework_sha256': framework_sha256, 'checks': count,
            'real_browser_starts': 5, 'privacy': report['privacy'],
            'worker_mutations_proven': True, 'incognito_storage_lifecycle_proven': True,
            'scope': 'Window/iframe and Dedicated/Module/Nested/Shared/Service Worker read/write/delete with independent owning-window readback of IDB, CacheStorage, OPFS and bucket IDB; two sites/four contexts and five real incognito launches. Off-the-record storage is discarded between launches; not quota-pressure, permission transitions, concurrency, expiration or complete storage privacy.',
            'full_storage_privacy_proven': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('report', type=Path)
    p.add_argument('--app', type=Path, required=True)
    a = p.parse_args()
    report = json.loads(a.report.read_text())
    for path, sha in report['probe_sha256'].items():
        assert digest(Path(path)) == sha, 'Probe changed: ' + path
    framework = a.app / 'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'
    print(json.dumps(verify(report, digest(framework)), indent=2))


if __name__ == '__main__':
    main()
