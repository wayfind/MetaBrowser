"""Synthetic verifier and real loopback server tests; no browser coverage claim."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid

from identity_isolation_acceptance import HTTP_ACCEPT_LANGUAGE, MARKER, STEPS, STORES, digest, verify
from identity_isolation_runner import Fixture, HERE, write_private


class IsolationEvidence(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='metabrowser-isolation-contract-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        (self.root / '.metabrowser-owned-fixture').write_text(MARKER)
        self.framework = '1' * 64
        origin = 'http://127.0.0.1:18899'
        config = {'schema': 1, 'template': 'native-macos-arm64-v1',
                  'languages': 'en-US,en', 'timezone': 'America/New_York', 'window': 'system'}
        profiles = {}
        for index, owner in enumerate(('a', 'b')):
            identity = str(uuid.uuid4())
            profiles[owner] = {'id': identity, 'config': dict(config, id=identity, name=owner),
                               'root_secret_sha256': str(index + 4) * 64, 'native_quit_requested': True,
                               'reaped': True, 'parent_survived': True}
        self.report = {'schema_version': 1, 'root': str(self.root), 'completed': True,
                       'forced_cleanup': False, 'parent_exit_code': 0, 'paid_model_calls': 0,
                       'provider_posts': [], 'framework_sha256': self.framework,
                       'probe_sha256': {name: digest(HERE / name) for name in
                          ('identity_isolation_runner.py', 'identity_isolation_probe.js',
                           'identity_isolation_acceptance.py', 'panel_ui.swift')},
                       'ui_helper_sha256': '2' * 64, 'bundle_manifest_sha256': '3' * 64,
                       'production_cross_os_verified': False, 'full_scope_complete': False,
                       'profiles': profiles, 'restart_root_secret_sha256': '4' * 64,
                       'clone_empty_directories': dict.fromkeys(('browser', 'account', 'conversations', 'workspace'), True),
                       'tokens': {'a': 'a' * 32, 'b': 'b' * 32}, 'origin': origin,
                       'executable': '/synthetic fixture/MetaBrowser.app/Contents/MacOS/Chromium', 'steps': []}
        for index, step in enumerate(STEPS):
            owner = 'b' if step == 'b_first' else 'a'
            token = self.report['tokens'][owner]
            run = str(uuid.uuid4())
            observation = {'run': run, 'token': token, 'origin': origin,
                           'before': dict.fromkeys(STORES, None if index < 2 else 'a' * 32),
                           'after': dict.fromkeys(STORES, token),
                           'registrations_before': [] if index < 2 else [origin + '/'],
                           'http_cache': ('d' if owner == 'a' else 'e') * 32,
                           'canvas': ('d' if owner == 'a' else 'e') * 64,
                               'timezone': 'America/New_York', 'languages': ['en-US'], 'platform': 'MacIntel',
                           'workers': {name: {'kind': kind, 'stores': dict.fromkeys(('indexedDB', 'cache', 'opfs'), token)}
                              for name, kind in (('dedicated', 'DedicatedWorkerGlobalScope'),
                                                 ('shared', 'SharedWorkerGlobalScope'), ('service', 'ServiceWorkerGlobalScope'))}}
            observation['workers']['shared']['memory_before'] = None
            command = self.report['executable'] + ' --user-data-dir=' + str(
                self.root / 'identities' / profiles[owner]['id'] / 'browser') + \
                ' --metabrowser-persona-template=native-macos-arm64-v1 --accept-lang=en-US,en about:blank'
            self.report['steps'].append({'step': step, 'profile': owner, 'run': run,
                                         'pid': (100, 101, 100, 102)[index], 'parent_alive': True,
                                         'command': command, 'observations': observation,
                                         'accept_language': [HTTP_ACCEPT_LANGUAGE]})
        # The restored a_live tab is refused before the restart observation.
        self.report['refused_replays'] = [self.report['steps'][2]['run']]
        self.persist(self.report)

    def persist(self, report):
        for row in report['steps']:
            path = self.root / 'reports' / (row['run'] + '.json')
            write_private(path, {'run': row['run'], 'host': report['origin'].removeprefix('http://'),
                                 'accept_language': row['accept_language'], 'report': row['observations']})
            row['sha256'] = digest(path)

    def test_synthetic_valid_record_exercises_verifier(self):
        result = verify(self.report, self.framework)
        self.assertTrue(result['passed'])
        self.assertFalse(result['full_scope_complete'])
        self.assertFalse(result['production_cross_os_verified'])

    def test_aligned_semantic_mutations_are_rejected(self):
        def observation(report, index=1):
            return report['steps'][index]['observations']
        mutations = {
            'paid boolean': lambda r: r.update(paid_model_calls=False),
            'paid call': lambda r: r.update(paid_model_calls=1),
            'provider request': lambda r: r.update(provider_posts=['/v1/chat/completions']),
            'forced cleanup': lambda r: r.update(forced_cleanup=True),
            'parent failed': lambda r: r.update(parent_exit_code=-15),
            'boolean exit': lambda r: r.update(parent_exit_code=False),
            'cross OS overclaim': lambda r: r.update(production_cross_os_verified=True),
            'full scope overclaim': lambda r: r.update(full_scope_complete=True),
            'boolean schema': lambda r: r.update(schema_version=True),
            'probe missing': lambda r: r['probe_sha256'].pop('identity_isolation_probe.js'),
            'probe drift': lambda r: r['probe_sha256'].update({'identity_isolation_probe.js': '0' * 64}),
            'cloned browser data': lambda r: r['clone_empty_directories'].update(browser=False),
            'boolean clone count': lambda r: r['clone_empty_directories'].update(browser=1),
            'profile configuration changed': lambda r: r['profiles']['b']['config'].update(window='1280,900'),
            'experimental template': lambda r: r['profiles']['b']['config'].update(template='linux-x86_64-software-v1'),
            'secret copied': lambda r: r['profiles']['b'].update(root_secret_sha256='4' * 64),
            'secret rotated': lambda r: r.update(restart_root_secret_sha256='6' * 64),
            'parent exited': lambda r: r['steps'][1].update(parent_alive=False),
            'restart PID reused': lambda r: r['steps'][3].update(pid=100),
            'wrong real profile': lambda r: r['steps'][1].update(command=r['steps'][0]['command']),
            'debug launch': lambda r: r['steps'][0].update(command=r['steps'][0]['command'] + ' --remote-debugging-port=1'),
            'cookie leaks': lambda r: observation(r)['before'].update(cookie='a' * 32),
            'IDB leaks': lambda r: observation(r)['before'].update(indexedDB='a' * 32),
            'OPFS missing': lambda r: observation(r)['after'].update(opfs=None),
            'cache omitted': lambda r: observation(r)['after'].pop('cache'),
            'restart data lost': lambda r: observation(r, 3)['before'].update(localStorage=None),
            'service registration copied': lambda r: observation(r).update(registrations_before=[r['origin'] + '/']),
            'worker is window': lambda r: observation(r)['workers']['service'].update(kind='Window'),
            'worker storage leaks': lambda r: observation(r)['workers']['dedicated']['stores'].update(indexedDB='a' * 32),
            'shared worker leaks': lambda r: observation(r)['workers']['shared'].update(memory_before='a' * 32),
            'HTTP cache leaks': lambda r: observation(r).update(http_cache='d' * 32),
            'HTTP cache lost': lambda r: observation(r, 3).update(http_cache='f' * 32),
            'canvas collision': lambda r: observation(r).update(canvas='d' * 64),
            'canvas drift': lambda r: observation(r, 3).update(canvas='f' * 64),
            'wrong timezone': lambda r: observation(r).update(timezone='UTC'),
            'JS full language list': lambda r: observation(r).update(languages=['en-US', 'en']),
            'JS system language': lambda r: observation(r).update(languages=['zh-CN']),
            'HTTP primary language only': lambda r: r['steps'][1].update(accept_language=['en-US']),
            'HTTP language missing': lambda r: r['steps'][1].update(accept_language=[None]),
            'HTTP navigation not observed': lambda r: r['steps'][1].update(accept_language=[]),
            'HTTP mixed languages': lambda r: r['steps'][1].update(
                accept_language=[HTTP_ACCEPT_LANGUAGE, 'en-US']),
            'replay of unknown run': lambda r: r.update(refused_replays=[str(uuid.uuid4())]),
            'replays omitted': lambda r: r.pop('refused_replays'),
            'restored page reran probe': lambda r: observation(r, 3)['workers']['shared'].update(memory_before='a' * 32),
            'empty capture': lambda r: observation(r).clear(),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                report = copy.deepcopy(self.report)
                mutate(report)
                self.persist(report)  # Recompute raw bytes and all digests, avoiding hash-only rejection.
                with self.assertRaises((AssertionError, KeyError, TypeError, ValueError)):
                    verify(report, self.framework)

    def test_raw_disagreement_even_with_updated_hash(self):
        row = self.report['steps'][0]
        path = self.root / 'reports' / (row['run'] + '.json')
        raw = json.loads(path.read_text())
        raw['report']['after']['cookie'] = None
        write_private(path, raw)
        row['sha256'] = digest(path)
        with self.assertRaisesRegex(AssertionError, 'Raw/summary disagreement'):
            verify(self.report, self.framework)

    def test_raw_language_disagreement_even_with_updated_hash(self):
        row = self.report['steps'][1]
        path = self.root / 'reports' / (row['run'] + '.json')
        raw = json.loads(path.read_text())
        raw['accept_language'] = ['en-US']
        write_private(path, raw)
        row['sha256'] = digest(path)
        with self.assertRaisesRegex(AssertionError, 'Raw/summary disagreement'):
            verify(self.report, self.framework)

    def test_missing_step_and_wrong_engine(self):
        with self.assertRaises(AssertionError):
            verify(self.report, '0' * 64)
        self.report['steps'].pop()
        with self.assertRaises(AssertionError):
            verify(self.report, self.framework)

    def test_relocated_fixture_preserves_original_process_evidence(self):
        with tempfile.TemporaryDirectory(prefix='metabrowser-isolation-restored-') as temporary:
            restored = Path(temporary)
            shutil.copytree(self.root / 'reports', restored / 'reports')
            shutil.copyfile(self.root / '.metabrowser-owned-fixture', restored / '.metabrowser-owned-fixture')
            snapshot = restored / 'probes'
            snapshot.mkdir()
            for name in self.report['probe_sha256']:
                shutil.copyfile(HERE / name, snapshot / name)
            original = copy.deepcopy(self.report)
            self.assertTrue(verify(self.report, self.framework, fixture_root=restored, probe_dir=snapshot)['passed'])
            self.assertEqual(self.report, original)
            (snapshot / 'identity_isolation_probe.js').write_text('changed snapshot')
            with self.assertRaisesRegex(AssertionError, 'Probe drift'):
                verify(self.report, self.framework, fixture_root=restored, probe_dir=snapshot)

    def test_missing_app_never_produces_a_browser_pass(self):
        output = self.root / 'must-not-exist.json'
        result = subprocess.run([sys.executable, str(HERE / 'identity_isolation_runner.py'),
                                 '--app', str(self.root / 'missing.app'), '--manifest', str(self.root / 'missing.json'),
                                 '--ui-helper', str(self.root / 'missing-helper'), '--output', str(output)],
                                text=True, capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('"passed": true', result.stdout)
        self.assertFalse(output.exists())


class LoopbackFixture(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='metabrowser-isolation-http-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.server = Fixture(self.root)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.run = str(uuid.uuid4())
        self.token = 'a' * 32
        self.server.expected[self.run] = self.token

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=3)

    def request(self, path, *, data=None, headers=None):
        request = urllib.request.Request(self.server.origin + path, data=data, headers=headers or {})
        return urllib.request.urlopen(request, timeout=3)

    def test_cache_marker_and_persistent_owned_cookie(self):
        with self.request('/cache-marker.js') as first, self.request('/cache-marker.js') as second:
            self.assertNotEqual(first.read(), second.read())
            self.assertIn('max-age=31536000', first.headers['Cache-Control'])
        with self.request('/cookie/set?token=' + self.token) as response:
            self.assertIn('HttpOnly', response.headers['Set-Cookie'])
            self.assertIn('Max-Age=86400', response.headers['Set-Cookie'])
        with self.request('/cookie/read', headers={'Cookie': 'metabrowser_owned_isolation=' + self.token}) as response:
            self.assertEqual(json.load(response), {'marker': self.token})

    def test_unknown_run_and_duplicate_report_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request('/?run=' + str(uuid.uuid4()) + '&token=' + self.token)
        self.assertEqual(caught.exception.code, 400)
        body = json.dumps({'run': self.run, 'report': {'token': self.token}}).encode()
        headers = {'Content-Type': 'application/json', 'Origin': self.server.origin}
        with self.request('/report', data=body, headers=headers) as response:
            self.assertEqual(response.status, 200)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request('/report', data=body, headers=headers)
        self.assertEqual(caught.exception.code, 400)
        self.assertEqual((self.root / 'reports' / (self.run + '.json')).stat().st_mode & 0o777, 0o600)

    def test_navigation_language_recorded_and_reported_run_never_served_again(self):
        page = '/?run=' + self.run + '&token=' + self.token
        with self.request(page, headers={'Accept-Language': HTTP_ACCEPT_LANGUAGE}) as response:
            self.assertEqual(response.status, 200)
        body = json.dumps({'run': self.run, 'report': {'token': self.token}}).encode()
        headers = {'Content-Type': 'application/json', 'Origin': self.server.origin}
        with self.request('/report', data=body, headers=headers) as response:
            self.assertEqual(response.status, 200)
        raw = json.loads((self.root / 'reports' / (self.run + '.json')).read_text())
        self.assertEqual(raw['accept_language'], [HTTP_ACCEPT_LANGUAGE])
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request(page, headers={'Accept-Language': HTTP_ACCEPT_LANGUAGE})
        self.assertEqual(caught.exception.code, 410)
        self.assertEqual(self.server.refused_replays, [self.run])
        self.assertEqual(self.server.accept_languages[self.run], [HTTP_ACCEPT_LANGUAGE])

    def test_model_requests_are_recorded_and_denied(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request('/v1/chat/completions', data=b'{}')
        self.assertEqual(caught.exception.code, 403)
        self.assertEqual(self.server.provider_posts, ['/v1/chat/completions'])


if __name__ == '__main__':
    unittest.main()
