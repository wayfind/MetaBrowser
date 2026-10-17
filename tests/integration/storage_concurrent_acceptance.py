"""Replay raw normal/OTR samples; summaries cannot establish isolation."""
import argparse
import copy
import json
from pathlib import Path
from identity_surface_runner import digest
from storage_mutation_runner import validate, EXPECTED

PHASES = [
    ('regular_seed', 'regular', 'write', True),
    ('private_initial_empty', 'private', 'read', False),
    ('private_seed', 'private', 'write', True),
    ('regular_unchanged', 'regular', 'read', True),
    ('regular_clear', 'regular', 'delete', False),
    ('private_survives_regular_clear', 'private', 'read', True),
    ('regular_reseed', 'regular', 'write', True),
    ('private_clear', 'private', 'delete', False),
    ('regular_survives_private_clear', 'regular', 'read', True),
    ('private_reseed', 'private', 'write', True),
    ('recreated_private_empty', 'private', 'read', False),
    ('regular_survives_private_disposal', 'regular', 'read', True),
]
ORIGINS = {'firstA':'http://127.0.0.1:18878','aUnderB':'http://127.0.0.1:18878',
           'firstB':'http://localhost:18878','bUnderA':'http://localhost:18878'}


def verify(report, framework_sha256):
    assert report['completed'] is True and report['clean_shutdown'] is True
    assert report['framework_sha256'] == framework_sha256
    assert report['privacy'] in ('balanced', 'off')
    assert type(report['paid_model_calls']) is int and report['paid_model_calls'] == 0
    assert not report.get('error') and type(report['pid']) is int and report['pid'] > 0
    raw = report['observations']
    assert raw['completed'] is True and raw['disposedFirstContextHasNoTargets'] is True
    regular, first, second = [raw[k] for k in ('regularBrowserContextId', 'firstPrivateContextId', 'secondPrivateContextId')]
    assert all(isinstance(v, str) and v for v in (regular, first, second))
    assert len({regular, first, second}) == 3
    assert len(raw['records']) == len(PHASES)
    checks = 0
    regular_targets, private_targets = set(), set()
    for index, (row, (name, kind, operation, markers)) in enumerate(zip(raw['records'], PHASES)):
        assert (row['name'], row['prefix'], row['operation']) == (name, kind + ':', operation)
        expected_context = regular if kind == 'regular' else (second if index == 10 else first)
        assert row['browserContextId'] == expected_context
        assert isinstance(row['targetId'], str) and row['targetId']
        (regular_targets if kind == 'regular' else private_targets).add(row['targetId'])
        contexts = row['contexts']
        assert set(contexts) == set(EXPECTED)
        normalized = copy.deepcopy(contexts)
        for key, context in contexts.items():
            assert context['origin'] == ORIGINS[key] and context['operation'] == operation
            samples = [context, *context['workers'].values(),
                       *(sample for trace in context['mutationTrace'].values() for sample in trace.values())]
            normalized_context = normalized[key]
            normalized_samples = [normalized_context, *normalized_context['workers'].values(),
                                  *(sample for trace in normalized_context['mutationTrace'].values() for sample in trace.values())]
            for sample, target in zip(samples, normalized_samples):
                assert sample['origin'] == ORIGINS[key]
                assert sample['estimate']['quota'] - sample['estimate']['usage'] == 10 * 1024**3
                assert sample['bucketEstimate']['quota'] == 524288
                for store in target['stores'].values():
                    value = store.get('value')
                    # Strip only the expected namespace. A cross-profile marker
                    # retains the wrong prefix and fails the underlying checks.
                    if isinstance(value, str) and value.startswith(row['prefix']):
                        store['value'] = value[len(row['prefix']):]
        result = validate({'contexts': normalized}, markers)
        assert result['passed'], {k:v for k,v in result['checks'].items() if not v}
        checks += len(result['checks'])
    assert len(regular_targets) == 1 and len(private_targets) == 2
    assert not regular_targets.intersection(private_targets)
    return {'passed': True, 'checks': checks, 'privacy': report['privacy'],
            'framework_sha256': framework_sha256, 'real_browser_starts': 1,
            'scope': raw['scope'], 'full_storage_privacy_proven': False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('report', type=Path)
    p.add_argument('--app', type=Path, required=True)
    p.add_argument('--probe-dir', type=Path, help='Frozen capture sources for replay after a verifier update')
    args = p.parse_args()
    report = json.loads(args.report.read_text())
    for filename, sha in report['probe_sha256'].items():
        source = args.probe_dir / Path(filename).name if args.probe_dir else Path(filename)
        assert digest(source) == sha, 'Probe changed: ' + filename
    print(json.dumps(verify(report, digest(args.app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework')), indent=2))


if __name__ == '__main__':
    main()
