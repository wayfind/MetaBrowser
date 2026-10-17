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


from storage_mutation_runner import Handler, validate


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
    probes = [Path(__file__).resolve(), HERE / 'storage_mutation_collector.js', HERE / 'storage_otr_probe.mjs', HERE / 'storage_mutation_runner.py']
    report = {'root': str(root), 'framework_sha256': digest(app / 'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'),
              'privacy': a.privacy, 'incognito': True, 'probe_sha256': {str(f): digest(f) for f in probes},
              'completed': False, 'passed': False, 'iterations': [], 'paid_model_calls': 0,
              'full_storage_privacy_proven': False}
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 18878), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log = a.output.with_suffix('.runtime.log').open('w')
    os.fchmod(log.fileno(), 0o600)
    process = None
    phases = [('seed', 'a', 'write', True), ('restart_read', 'a', 'read', False),
              ('independent_profile', 'b', 'read', False), ('clear', 'a', 'delete', False),
              ('restart_after_clear', 'a', 'read', False)]
    try:
        for name, profile, operation, expected in phases:
            process = subprocess.Popen([str(app / 'Contents/MacOS/Chromium'), '--user-data-dir=' + str(root / profile),
                                        '--remote-debugging-port=18877', '--incognito', '--use-mock-keychain', '--no-first-run',
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
            result = subprocess.run(['node', str(HERE / 'storage_otr_probe.mjs'), '18877', operation], capture_output=True, text=True, timeout=120)
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
