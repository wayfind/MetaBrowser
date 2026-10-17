"""Verify bounded native-profile isolation; never declares full persona coverage."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import uuid

MARKER = 'identity-isolation-v1'
STORES = {'cookie', 'localStorage', 'indexedDB', 'cache', 'opfs'}
STEPS = ('a_first', 'b_first', 'a_live', 'a_restart')
# The engine sends the configured list over HTTP but exposes only the primary
# language to JavaScript (same as the v20m cold-stability evidence).
HTTP_ACCEPT_LANGUAGE = 'en-US,en;q=0.9'
JS_LANGUAGES = ['en-US']


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def hex_value(value, length):
    return isinstance(value, str) and re.fullmatch('[a-f0-9]{' + str(length) + '}', value) is not None


def verify(report, framework, *, probe_dir=None, fixture_root=None):
    assert type(report['schema_version']) is int and report['schema_version'] == 1
    assert report['completed'] is True and not report.get('error')
    assert report['forced_cleanup'] is False and report['parent_exit_code'] == 0
    assert type(report['parent_exit_code']) is int
    assert type(report['paid_model_calls']) is int and report['paid_model_calls'] == 0
    assert report['provider_posts'] == []
    assert type(report['refused_replays']) is list
    assert report['full_scope_complete'] is False and report['production_cross_os_verified'] is False
    assert report['framework_sha256'] == framework and hex_value(framework, 64)
    recorded_root = Path(report['root'])
    assert recorded_root.is_absolute() and not any(value.isspace() for value in str(recorded_root))
    root = Path(fixture_root if fixture_root is not None else recorded_root).resolve(strict=True)
    assert (root / '.metabrowser-owned-fixture').read_text() == MARKER
    assert set(report['probe_sha256']) == {
        'identity_isolation_runner.py', 'identity_isolation_probe.js', 'identity_isolation_acceptance.py',
        'panel_ui.swift'}
    source = Path(probe_dir) if probe_dir else Path(__file__).resolve().parent
    for name, value in report['probe_sha256'].items():
        assert digest(source / name) == value, 'Probe drift: ' + name
    assert hex_value(report['ui_helper_sha256'], 64)
    assert hex_value(report['bundle_manifest_sha256'], 64)
    assert set(report['profiles']) == {'a', 'b'}
    profiles = report['profiles']
    for entry in profiles.values():
        assert str(uuid.UUID(entry['id'])) == entry['id']
        config = entry['config']
        assert config['id'] == entry['id'] and type(config['schema']) is int and config['schema'] == 1
        assert config['template'] == 'native-macos-arm64-v1'
        assert config['languages'] == 'en-US,en' and config['timezone'] == 'America/New_York'
        assert hex_value(entry['root_secret_sha256'], 64)
        assert entry['native_quit_requested'] is True and entry['reaped'] is True
        assert entry['parent_survived'] is True
    assert profiles['a']['id'] != profiles['b']['id']
    assert profiles['a']['root_secret_sha256'] != profiles['b']['root_secret_sha256']
    assert profiles['a']['root_secret_sha256'] == report['restart_root_secret_sha256']
    assert report['clone_empty_directories'] == dict.fromkeys(
        ('browser', 'account', 'conversations', 'workspace'), True)
    assert all(value is True for value in report['clone_empty_directories'].values())
    copied = {k: v for k, v in profiles['a']['config'].items() if k not in ('id', 'revision', 'name')}
    assert copied == {k: v for k, v in profiles['b']['config'].items() if k not in ('id', 'revision', 'name')}
    rows = report['steps']
    assert [row['step'] for row in rows] == list(STEPS)
    assert len({row['run'] for row in rows}) == len(STEPS)
    assert set(report['refused_replays']) <= {row['run'] for row in rows}, 'Replay of an unknown run'
    assert rows[0]['pid'] == rows[2]['pid']
    assert len({rows[index]['pid'] for index in (0, 1, 3)}) == 3
    assert all(type(row['pid']) is int and row['pid'] > 0 for row in rows)
    tokens = report['tokens']
    assert set(tokens) == {'a', 'b'} and tokens['a'] != tokens['b']
    assert all(hex_value(value, 32) for value in tokens.values())
    origin = report['origin']
    assert re.fullmatch(r'http://127\.0\.0\.1:[1-9][0-9]{0,4}', origin)
    observations = {}
    for index, row in enumerate(rows):
        step = row['step']
        owner = 'b' if step == 'b_first' else 'a'
        assert row['profile'] == owner
        assert str(uuid.UUID(row['run'])) == row['run']
        raw_path = root / 'reports' / (row['run'] + '.json')
        assert digest(raw_path) == row['sha256']
        raw = json.loads(raw_path.read_text())
        assert raw['run'] == row['run'] and not raw.get('error')
        assert raw['host'] == origin.removeprefix('http://')
        observed = raw['report']
        assert observed == row['observations'], 'Raw/summary disagreement'
        assert raw['accept_language'] == row['accept_language'], 'Raw/summary disagreement'
        assert row['accept_language'] and all(
            value == HTTP_ACCEPT_LANGUAGE for value in row['accept_language']), step + ': HTTP Accept-Language'
        assert observed['run'] == row['run'] and observed['token'] == tokens[owner]
        assert observed['origin'] == origin
        assert row['parent_alive'] is True
        command = row['command']
        executable = report['executable']
        assert command.startswith(executable + ' ')
        arguments = command[len(executable) + 1:].split()
        assert '--user-data-dir=' + str(recorded_root / 'identities' / profiles[owner]['id'] / 'browser') in arguments
        assert '--metabrowser-persona-template=native-macos-arm64-v1' in arguments
        assert '--accept-lang=en-US,en' in arguments
        assert not any(arg.startswith(('--remote-debugging', '--metacodes-demo-prompt')) for arg in arguments)
        assert set(observed['before']) == STORES and set(observed['after']) == STORES
        expected = None if index < 2 else tokens['a']
        assert observed['before'] == dict.fromkeys(STORES, expected), step + ': existing data'
        assert observed['after'] == dict.fromkeys(STORES, tokens[owner])
        registrations = [] if index < 2 else [origin + '/']
        assert observed['registrations_before'] == registrations
        assert hex_value(observed['http_cache'], 32) and hex_value(observed['canvas'], 64)
        assert observed['timezone'] == 'America/New_York' and observed['languages'] == JS_LANGUAGES
        assert observed['platform'] == 'MacIntel'
        assert set(observed['workers']) == {'dedicated', 'shared', 'service'}
        for worker, kind in (('dedicated', 'DedicatedWorkerGlobalScope'),
                             ('shared', 'SharedWorkerGlobalScope'), ('service', 'ServiceWorkerGlobalScope')):
            result = observed['workers'][worker]
            assert not result.get('error') and result['kind'] == kind
            assert result['stores'] == dict.fromkeys(('indexedDB', 'cache', 'opfs'), tokens[owner])
        shared_before = observed['workers']['shared']['memory_before']
        assert shared_before in ((None, tokens['a']) if step == 'a_live' else (None,))
        observations[step] = observed
    first = observations['a_first']
    for step in ('a_live', 'a_restart'):
        assert observations[step]['http_cache'] == first['http_cache'], 'A HTTP cache changed'
        assert observations[step]['canvas'] == first['canvas'], 'A fingerprint drifted'
    assert observations['b_first']['http_cache'] != first['http_cache'], 'HTTP cache shared across identities'
    assert observations['b_first']['canvas'] != first['canvas'], 'Canvas identity collision'
    return {'passed': True, 'framework_sha256': framework, 'storage_surfaces': sorted(STORES),
            'worker_realms': 3, 'http_accept_language': HTTP_ACCEPT_LANGUAGE, 'js_languages': JS_LANGUAGES,
            'refused_replays': len(report['refused_replays']),
            'native_profile_launch': True, 'configuration_clone_only': True,
            'bounded_live_and_restart_isolation': True, 'production_cross_os_verified': False,
            'full_scope_complete': False,
            'scope': 'Two native macOS identities, one owned origin and one cold restart. '
                     'Not all partitions, storage APIs, profile combinations, cross-OS parity or seven days.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--probe-dir', type=Path)
    parser.add_argument('--fixture-root', type=Path, help='Restored fixture path; preserve original report and process paths')
    args = parser.parse_args()
    framework = args.app / 'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'
    print(json.dumps(verify(json.loads(args.report.read_text()), digest(framework),
                            probe_dir=args.probe_dir, fixture_root=args.fixture_root), indent=2))
