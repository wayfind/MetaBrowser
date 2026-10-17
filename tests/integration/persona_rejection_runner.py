"""Invalid diagnostic personas must exit before making a site request."""
import argparse
import http.server
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from identity_surface_runner import digest, write_private


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    app = a.app.resolve(strict=True)
    assert not (app/'Contents/Resources/agentcore').exists()
    root = Path(tempfile.mkdtemp(prefix='metabrowser-persona-rejection-')).resolve()
    (root/'.metabrowser-owned-fixture').write_text('persona-rejection')
    requests = []
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            requests.append(self.path)
            self.send_response(200); self.end_headers()
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    software = ['--use-gl=angle', '--use-angle=swiftshader', '--use-webgpu-adapter=swiftshader',
                '--disable-accelerated-video-decode', '--disable-accelerated-video-encode']
    selector = '--metabrowser-persona-template=linux-x86_64-software-v1'
    cases = {'unknown': ['--metabrowser-persona-template=unknown'],
             'empty': ['--metabrowser-persona-template='],
             'custom-ua': [selector, *software, '--user-agent=owned-invalid'],
             'empty-process-type': [selector, '--type=']}
    for missing in software:
        cases['missing-'+missing.split('=')[0][2:]] = [selector, *[s for s in software if s != missing]]
    report = {'framework_sha256': digest(app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'),
              'root': str(root), 'cases': [], 'completed': False, 'paid_model_calls': 0,
              'full_scope_complete': False, 'source_sha256': digest(Path(__file__))}
    try:
        for name, flags in cases.items():
            owned = root/name
            env = {k:v for k,v in os.environ.items() if k in ('HOME','PATH','USER','LOGNAME','LANG','LC_CTYPE','TMPDIR','SHELL','__CF_USER_TEXT_ENCODING')}
            env.update({k: str(owned/v) for k,v in [('METABROWSER_IDENTITY_HOME','identities'),
                ('METABROWSER_ACCOUNT_HOME','account'), ('METABROWSER_CONVERSATION_HOME','conversations'),
                ('METABROWSER_WORKSPACE','workspace')]})
            command = [str(app/'Contents/MacOS/Chromium'), '--user-data-dir='+str(owned/'browser'),
                '--use-mock-keychain', '--no-first-run', '--no-default-browser-check',
                '--disable-background-networking', '--disable-component-update', *flags,
                f'http://127.0.0.1:{server.server_port}/{name}']
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20)
            row = {'name':name, 'command':command, 'exit_code':result.returncode,
                   'stdout':result.stdout, 'stderr':result.stderr}
            report['cases'].append(row)
            assert 0 < result.returncode < 128, row
            assert 'Invalid identity template configuration.' in result.stderr, row
            assert not requests, requests
        report.update(completed=True, site_requests=requests)
    finally:
        server.shutdown(); server.server_close()
        a.output.parent.mkdir(parents=True, exist_ok=True)
        write_private(a.output, report)
    print('Invalid persona startup rejection passed:', len(cases))


if __name__ == '__main__': main()
