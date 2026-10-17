"""One owned browser with regular and native DevTools-created OTR windows."""
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
from storage_mutation_runner import Handler
from quota_pressure_acceptance import verify

HERE = Path(__file__).resolve().parent


class QuotaHandler(Handler):
    def do_GET(self):
        if self.path not in ('/', '/quota.js', '/quota-worker.js'):
            return super().do_GET()
        if self.path == '/':
            body=b'<!doctype html><title>Owned quota pressure probe</title><script src="/quota.js"></script>'
            mime='text/html'
        else:
            body=(HERE/'quota_pressure_collector.js').read_bytes()
            if self.path == '/quota-worker.js':
                body += b"\nself.onmessage=e=>ownedQuotaTrial(e.data).then(result=>postMessage({result})).catch(error=>postMessage({error:String(error)}));"
            mime='text/javascript'
        self.send_response(200)
        self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.end_headers();self.wfile.write(body)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app', type=Path, required=True)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--ui-helper', type=Path, required=True)
    p.add_argument('--privacy', choices=['balanced', 'off'], default='balanced')
    args = p.parse_args()
    app = args.app.resolve(strict=True)
    subprocess.run(['python3', str(HERE.parents[1]/'scripts/app-manifest.py'), str(app), '--check', str(args.manifest)], check=True)
    assert not (app/'Contents/Resources/agentcore').exists()
    assert not (app/'Contents/Frameworks/libmetabrowser_metacodes.dylib').exists()
    for port in (18877, 18878):
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('127.0.0.1', port))
    root = Path(tempfile.mkdtemp(prefix='metabrowser-quota-pressure-')).resolve()
    (root/'.metabrowser-owned-fixture').write_text('quota-pressure')
    env = {k:v for k,v in os.environ.items() if k in ('HOME','PATH','USER','LOGNAME','LANG','LC_CTYPE','TMPDIR','SHELL','__CF_USER_TEXT_ENCODING')}
    env.update(METABROWSER_IDENTITY_HOME=str(root/'identities'), METABROWSER_ACCOUNT_HOME=str(root/'account'),
               METABROWSER_CONVERSATION_HOME=str(root/'conversations'), METABROWSER_WORKSPACE=str(root/'workspace'))
    probes = [Path(__file__).resolve(), HERE/'quota_pressure_probe.mjs', HERE/'quota_pressure_acceptance.py',
              HERE/'storage_mutation_runner.py', HERE/'quota_pressure_collector.js']
    report = {'root':str(root), 'framework_sha256':digest(app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'),
              'privacy':args.privacy, 'paid_model_calls':0, 'completed':False, 'clean_shutdown':False,
              'probe_sha256':{str(f):digest(f) for f in probes}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    server = http.server.ThreadingHTTPServer(('127.0.0.1',18878), QuotaHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    process = None
    try:
        with args.output.with_suffix('.runtime.log').open('w') as log:
            os.fchmod(log.fileno(), 0o600)
            process = subprocess.Popen([str(app/'Contents/MacOS/Chromium'), '--user-data-dir='+str(root/'browser'),
                '--remote-debugging-port=18877', '--use-mock-keychain', '--no-first-run', '--no-default-browser-check',
                '--disable-component-update', '--disable-background-networking', '--metabrowser-privacy='+args.privacy, 'about:blank'],
                env=env,stdout=log,stderr=log,start_new_session=True)
            report['pid'] = process.pid
            for _ in range(150):
                assert process.poll() is None, 'Owned browser exited'
                try:
                    urllib.request.urlopen('http://127.0.0.1:18877/json/version',timeout=.3).close()
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise TimeoutError('Owned browser not ready')
            result = subprocess.run(['node',str(HERE/'quota_pressure_probe.mjs'),'18877'],capture_output=True,text=True,timeout=300)
            outputs = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            report['checkpoints'] = [row['checkpoint'] for row in outputs if 'checkpoint' in row]
            write_private(args.output, report)
            assert result.returncode == 0, result.stderr[-4000:]
            report['observations'] = outputs[-1]
            assert report['observations'].get('completed') is True
            subprocess.run([str(args.ui_helper),str(process.pid),'quit'],env=dict(env,METABROWSER_UI_NO_ACTIVATE='1'),check=True,timeout=10)
            process.wait(timeout=20)
            assert process.returncode == 0, 'Owned browser did not quit cleanly'
            report.update(completed=True,clean_shutdown=True)
            assert all(digest(Path(f)) == sha for f,sha in report['probe_sha256'].items())
            report['acceptance'] = verify(report, report['framework_sha256'])
            print(json.dumps(report['acceptance']),flush=True)
    except BaseException as error:
        report['error'] = str(error)
        raise
    finally:
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=20)
        server.shutdown(); server.server_close()
        write_private(args.output, report)


if __name__ == '__main__':
    main()
