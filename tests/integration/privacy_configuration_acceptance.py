"""Replay the five healthy/invalid-mode controls; never full privacy proof."""
import argparse
import hashlib
import json
from pathlib import Path

from identity_surface_runner import validate, validate_passive


def verify(report, framework_sha256):
    assert report['completed'] is True and not report.get('error')
    assert type(report['paid_model_calls']) is int and report['paid_model_calls'] == 0
    assert report['full_privacy_proven'] is False
    assert report['framework_sha256'] == framework_sha256
    modes = {'protected', 'unknown_mode', 'empty_mode', 'cpu_enabled', 'cpu_enabled_off'}
    assert set(report['modes']) == modes
    for mode, row in report['modes'].items():
        observations = row['observations']
        assert validate(observations)['consistency_passed'] is True
        protected = mode != 'cpu_enabled_off'
        assert validate_passive(observations, protected)['passed'] is True
        assert validate_passive(observations, not protected)['passed'] is False
        realms = observations['realms']
        assert set(realms) == {'window', 'iframe', 'dedicated', 'shared', 'service'}
        for realm, data in realms.items():
            # This gate is explicitly for the current eight-core Apple cohort.
            # The separate controlled CPU gate tests multiple core counts.
            assert type(data['hardwareConcurrency']) is int
            assert data['hardwareConcurrency'] == 8
            expected = {'present': True, 'value': 4} if realm in ('window', 'iframe') else {'present': False}
            assert type(data['cpuPerformance']['present']) is bool
            assert data['cpuPerformance'] == expected
            if realm in ('window', 'iframe'):
                assert type(data['cpuPerformance']['value']) is int
        retained = observations['retainedCPU']
        assert retained['before'] == retained['after'] == {'hardwareConcurrency': 8, 'cpuPerformance': 4}
    return {'passed': True, 'modes': 5, 'full_privacy_proven': False,
            'scope': 'Five Mac Apple cohort mode controls; no malformed-file or cross-platform claim.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--app', type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    for path, expected in report['source_sha256'].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected, path
    framework = args.app / 'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'
    print(json.dumps(verify(report, hashlib.sha256(framework.read_bytes()).hexdigest()), indent=2))


if __name__ == '__main__':
    main()
