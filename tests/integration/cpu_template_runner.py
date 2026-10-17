"""Controlled native CPU-template consistency; healthy isolated profile only."""
import argparse
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


def validate(data):
    checks = {}
    identity = data['identity']
    checks['current_native_apple_template'] = identity.get('platform') == 'macOS' and identity.get('architecture') == 'arm' and identity.get('bitness') == '64'
    checks['four_control_states'] = [r['requestedCores'] for r in data['samples']] == [8, 4, 1, 8]
    # Independent reference cases from pinned Chromium154 classification, not
    # "the protected answer must differ from native" or an arbitrary constant.
    reference = {8: 4, 4: 2, 1: 1}
    for index, row in enumerate(data['samples']):
        checks[f'state_{index}_main_override_applied'] = row['observed']['window']['cores'] == row['requestedCores']
        for realm in ('window', 'iframe'):
            v = row['observed'][realm]
            checks[f'state_{index}_{realm}_coherent_tier'] = v['present'] is True and v['cores'] in reference and v['tier'] == reference[v['cores']]
    checks['retained_owner_policy_coherent'] = data['retained']['before'] == data['retained']['after'] == {'cores': 8, 'tier': 4}
    return {'checks': checks, 'passed': all(checks.values())}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app', type=Path, required=True)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--ui-helper', type=Path, required=True)
    a = p.parse_args(); app = a.app.resolve(strict=True)
    project = Path(__file__).resolve().parents[2]
    subprocess.run(['python3', str(project / 'scripts/app-manifest.py'), str(app), '--check', str(a.manifest)], check=True)
    assert not (app / 'Contents/Resources/agentcore').exists() and not (app / 'Contents/Frameworks/libmetabrowser_metacodes.dylib').exists()
    for port in (18879, 18880):
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); s.bind(('127.0.0.1', port))
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            body = b'<!doctype html><title>Owned CPU template control</title>'
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
    root = Path(tempfile.mkdtemp(prefix='metabrowser-cpu-template-')).resolve()
    env = {k: v for k, v in os.environ.items() if k in ('HOME','PATH','USER','LOGNAME','LANG','LC_CTYPE','TMPDIR','SHELL','__CF_USER_TEXT_ENCODING')}
    env.update(METABROWSER_IDENTITY_HOME=str(root/'identities'), METABROWSER_ACCOUNT_HOME=str(root/'account'), METABROWSER_CONVERSATION_HOME=str(root/'conversations'), METABROWSER_WORKSPACE=str(root/'workspace'))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    files = [Path(__file__).resolve(), Path(__file__).with_name('cpu_template_probe.mjs')]
    report = {'root': str(root), 'framework_sha256': digest(app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'), 'probe_sha256': {str(f): digest(f) for f in files}, 'completed': False, 'paid_model_calls': 0, 'full_privacy_proven': False}
    server = http.server.ThreadingHTTPServer(('127.0.0.1',18880), Handler); threading.Thread(target=server.serve_forever, daemon=True).start()
    log = a.output.with_suffix('.runtime.log').open('w'); os.fchmod(log.fileno(), 0o600); process = None
    try:
        process = subprocess.Popen([str(app/'Contents/MacOS/Chromium'), '--user-data-dir='+str(root/'browser'), '--remote-debugging-port=18879', '--use-mock-keychain', '--no-first-run', '--no-default-browser-check', '--disable-component-update', '--disable-background-networking', 'about:blank'], env=env, stdout=log, stderr=log, start_new_session=True)
        for _ in range(150):
            assert process.poll() is None
            try: urllib.request.urlopen('http://127.0.0.1:18879/json/version',timeout=.3).close(); break
            except OSError: time.sleep(.1)
        else: raise TimeoutError('Owned CPU readiness timeout')
        r = subprocess.run(['node', str(files[1]), '18879'], capture_output=True, text=True, timeout=90)
        if r.returncode: raise RuntimeError(r.stderr[-2000:])
        raw = json.loads(r.stdout); report.update(observations=raw, **validate(raw))
        subprocess.run([str(a.ui_helper),str(process.pid),'quit'],env=dict(env,METABROWSER_UI_NO_ACTIVATE='1'),check=True,timeout=10)
        process.wait(timeout=20); assert process.returncode == 0; process = None
        assert all(digest(Path(f)) == sha for f, sha in report['probe_sha256'].items())
        report.update(completed=True,clean_shutdown=True)
    except BaseException as error: report['error'] = str(error); raise
    finally:
        if process and process.poll() is None: process.terminate(); process.wait(timeout=20)
        server.shutdown(); server.server_close(); log.close(); write_private(a.output, report)
    print(json.dumps({'completed': report['completed'], 'passed': report['passed'], 'checks': report['checks']}))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__': main()
