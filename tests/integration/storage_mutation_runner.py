"""Owned persistent profile/storage matrix; no user data or paid calls."""
import argparse
import hashlib
import http.server
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from identity_surface_runner import digest, write_private

HERE = Path(__file__).resolve().parent
EXPECTED = {'firstA': 'first-a', 'firstB': 'first-b',
            'aUnderB': 'a-under-b', 'bUnderA': 'b-under-a'}
STORES = {'indexedDB', 'cacheStorage', 'opfs', 'bucketIndexedDB'}


def validate(data, expect_markers):
    checks = {}
    contexts = data.get('contexts', {})
    checks['four_first_and_third_party_contexts'] = set(contexts) == set(EXPECTED)
    for name in EXPECTED:
        context = contexts.get(name, {})
        stores = context.get('stores', {})
        checks[name + '_secure'] = context.get('secureContext') is True
        checks[name + '_all_real_stores_usable'] = set(stores) == STORES and all(v.get('completed') is True for v in stores.values())
        marker = EXPECTED[name] if expect_markers else None
        checks[name + '_isolated_value'] = checks[name + '_all_real_stores_usable'] and all(v.get('value') == marker for v in stores.values())
        estimate = context.get('estimate')
        checks[name + '_valid_estimate'] = isinstance(estimate, dict) and type(estimate.get('quota')) is int and type(estimate.get('usage')) is int and 0 <= estimate['usage'] <= estimate['quota']
        checks[name + '_explicit_bucket_quota'] = context.get('bucketEstimate', {}).get('quota') == 524288
        workers = context.get('workers', {})
        checks[name + '_five_workers'] = set(workers) == {'dedicated', 'shared', 'service', 'module', 'nested'}
        for realm in ('dedicated', 'shared', 'service', 'module', 'nested'):
            worker = workers.get(realm, {})
            stores = worker.get('stores', {})
            checks[name + '_' + realm + '_real_storage_key'] = (
                worker.get('secureContext') is True and worker.get('origin') == context.get('origin')
                and worker.get('operation') == 'read' and set(stores) == STORES
                and all(s.get('completed') is True and s.get('value') == marker for s in stores.values()))
    for name in EXPECTED:
        context = contexts.get(name, {})
        trace = context.get('mutationTrace', {})
        checks[name + '_all_worker_mutations'] = set(trace) == {'dedicated', 'shared', 'service', 'module', 'nested'}
        for realm in ('dedicated', 'shared', 'service', 'module', 'nested'):
            records = trace.get(realm, {})
            for phase, operation, expected in [('write', 'write', EXPECTED[name] + ':' + realm),
                                               ('windowAfterWrite', 'read', EXPECTED[name] + ':' + realm),
                                               ('delete', 'delete', None), ('windowAfterDelete', 'read', None)]:
                observed = records.get(phase, {})
                stores = observed.get('stores', {})
                checks[name + '_' + realm + '_' + phase] = (
                    observed.get('operation') == operation and observed.get('origin') == context.get('origin')
                    and observed.get('secureContext') is True and set(stores) == STORES
                    and all(v.get('completed') is True and v.get('value') == expected for v in stores.values()))
    return {'checks': checks, 'passed': all(checks.values())}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == '/storage-module.js':
            collector = (HERE / 'storage_mutation_collector.js').read_text()
            body = (collector + "\nself.onmessage=e=>storageOperation(e.data.operation,e.data.value).then(result=>postMessage({result})).catch(error=>postMessage({error:error.name}));").encode()
            mime = 'text/javascript'
        elif self.path == '/storage-nested.js':
            body = b"onmessage=event=>{const child=new Worker('/storage-worker.js');child.onmessage=e=>{postMessage(e.data);child.terminate()};child.onerror=e=>{postMessage({error:e.message});child.terminate()};child.postMessage(event.data)};"
            mime = 'text/javascript'
        elif self.path in ('/storage-worker.js', '/storage-shared.js', '/storage-service.js'):
            start = "importScripts('/storage.js');\n"
            read = "storageOperation(e.data.operation,e.data.value).then(result=>port.postMessage({result})).catch(error=>port.postMessage({error:error.name}))"
            if self.path == '/storage-worker.js':
                code = "onmessage=e=>{const port=self;" + read + "};"
            elif self.path == '/storage-shared.js':
                code = "onconnect=e=>{const port=e.ports[0];port.onmessage=e=>{" + read + "};port.start()};"
            else:
                code = "oninstall=e=>e.waitUntil(skipWaiting());onactivate=e=>e.waitUntil(clients.claim());onmessage=e=>{const port=e.ports[0];e.waitUntil(" + read + ")};"
            body, mime = (start + code).encode(), 'text/javascript'
        elif self.path == '/storage.js':
            body = (HERE / 'storage_mutation_collector.js').read_bytes()
            mime = 'text/javascript'
        else:
            code = ''
            if self.path.startswith('/frame.html?'):
                code = """<script>
                const q=new URL(location).searchParams;
                collectStorageRealms(q.get('operation'),q.get('value')).then(
                  result=>parent.postMessage({result},new URL(document.referrer).origin),
                  error=>parent.postMessage({error:error.name},new URL(document.referrer).origin));
                </script>"""
            body = ('<!doctype html><title>Owned storage isolation probe</title><script src="/storage.js"></script>' + code).encode()
            mime = 'text/html'
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app', type=Path, required=True)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--ui-helper', type=Path, required=True)
    p.add_argument('--privacy', choices=['balanced', 'off'], default='balanced')
    a = p.parse_args()
    app = a.app.resolve(strict=True)
    project = HERE.parents[1]
    subprocess.run(['python3', str(project / 'scripts/app-manifest.py'), str(app), '--check', str(a.manifest)], check=True)
    assert not (app / 'Contents/Resources/agentcore').exists()
    assert not (app / 'Contents/Frameworks/libmetabrowser_metacodes.dylib').exists()
    for port in (18877, 18878):
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('127.0.0.1', port))
    root = Path(tempfile.mkdtemp(prefix='metabrowser-storage-surfaces-')).resolve()
    (root / '.metabrowser-owned-fixture').write_text('storage-surfaces')
    env = {k: v for k, v in os.environ.items() if k in ('HOME', 'PATH', 'USER', 'LOGNAME', 'LANG', 'LC_CTYPE', 'TMPDIR', 'SHELL', '__CF_USER_TEXT_ENCODING')}
    env.update(METABROWSER_IDENTITY_HOME=str(root / 'identities'), METABROWSER_ACCOUNT_HOME=str(root / 'account'), METABROWSER_CONVERSATION_HOME=str(root / 'conversations'), METABROWSER_WORKSPACE=str(root / 'workspace'))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    probes = [Path(__file__).resolve(), HERE / 'storage_mutation_collector.js', HERE / 'storage_mutation_probe.mjs']
    report = {'root': str(root), 'framework_sha256': digest(app / 'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'),
              'privacy': a.privacy, 'probe_sha256': {str(f): digest(f) for f in probes},
              'completed': False, 'passed': False, 'iterations': [], 'paid_model_calls': 0,
              'full_storage_privacy_proven': False}
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 18878), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log = a.output.with_suffix('.runtime.log').open('w')
    os.fchmod(log.fileno(), 0o600)
    process = None
    phases = [('seed', 'a', 'write', True), ('restart_read', 'a', 'read', True),
              ('independent_profile', 'b', 'read', False), ('clear', 'a', 'delete', False),
              ('restart_after_clear', 'a', 'read', False)]
    try:
        for name, profile, operation, expected in phases:
            process = subprocess.Popen([str(app / 'Contents/MacOS/Chromium'), '--user-data-dir=' + str(root / profile),
                                        '--remote-debugging-port=18877', '--use-mock-keychain', '--no-first-run',
                                        '--no-default-browser-check', '--disable-component-update', '--disable-background-networking',
                                        '--metabrowser-privacy=' + a.privacy, 'about:blank'],
                                       env=env, stdout=log, stderr=log, start_new_session=True)
            for _ in range(150):
                assert process.poll() is None, 'Owned storage browser exited'
                try:
                    urllib.request.urlopen('http://127.0.0.1:18877/json/version', timeout=.3).close()
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise TimeoutError('Owned storage browser readiness timeout')
            result = subprocess.run(['node', str(HERE / 'storage_mutation_probe.mjs'), '18877', operation], capture_output=True, text=True, timeout=120)
            if result.returncode:
                raise RuntimeError(result.stderr[-2000:])
            raw = json.loads(result.stdout)
            row = {'name': name, 'profile': profile, 'pid': process.pid, 'observations': raw, **validate(raw, expected)}
            report['iterations'].append(row)
            subprocess.run([str(a.ui_helper), str(process.pid), 'quit'], env=dict(env, METABROWSER_UI_NO_ACTIVATE='1'), check=True, timeout=10)
            process.wait(timeout=20)
            row['clean_shutdown'] = process.returncode == 0
            assert row['clean_shutdown']
            pref = json.loads((root / profile / 'Default/Preferences').read_text())
            secret = pref.get('metabrowser', {}).get('privacy', {}).get('root_secret')
            row['root_secret_sha256'] = hashlib.sha256(secret.encode()).hexdigest() if secret else None
            process = None
            write_private(a.output, report)
            print(json.dumps({'phase': name, 'passed': row['passed'], 'failed_checks': [k for k, v in row['checks'].items() if not v]}), flush=True)
        assert all(digest(Path(f)) == sha for f, sha in report['probe_sha256'].items())
        report['completed'] = True
        report['passed'] = all(row['passed'] for row in report['iterations'])
        if a.privacy == 'balanced':
            roots = {row['root_secret_sha256'] for row in report['iterations'] if row['profile'] == 'a'}
            assert len(roots) == 1 and None not in roots, 'Profile identity rotated during storage test'
    except BaseException as error:
        report['error'] = str(error)
        raise
    finally:
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=20)
        server.shutdown()
        server.server_close()
        log.close()
        write_private(a.output, report)
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
