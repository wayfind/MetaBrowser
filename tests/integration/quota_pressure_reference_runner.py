"""Owned official-Chrome diagnostic; version mismatch cannot prove release parity."""
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
from quota_pressure_runner import QuotaHandler

HERE = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--ui-helper', type=Path, required=True)
    a = p.parse_args()
    app = a.app.resolve(strict=True)
    executable = app/'Contents/MacOS/Google Chrome'
    framework = app/'Contents/Frameworks/Google Chrome Framework.framework/Google Chrome Framework'
    assert executable.is_file() and framework.is_file()
    for port in (18877, 18878):
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('127.0.0.1', port))
    root = Path(tempfile.mkdtemp(prefix='metabrowser-quota-reference-')).resolve()
    (root/'.metabrowser-owned-fixture').write_text('quota-reference')
    env = {k:v for k,v in os.environ.items() if k in ('HOME','PATH','USER','LOGNAME','LANG','LC_CTYPE','TMPDIR','SHELL','__CF_USER_TEXT_ENCODING')}
    sources = [Path(__file__).resolve(), HERE/'quota_pressure_runner.py',
               HERE/'quota_pressure_probe.mjs', HERE/'quota_pressure_collector.js']
    report = {'root':str(root), 'completed':False, 'clean_shutdown':False,
              'reference_framework_sha256':digest(framework), 'paid_model_calls':0,
              'full_privacy_proven':False, 'same_version_baseline_proven':False,
              'probe_sha256':{str(f):digest(f) for f in sources}}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    server = http.server.ThreadingHTTPServer(('127.0.0.1',18878), QuotaHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    process = None
    try:
        with a.output.with_suffix('.runtime.log').open('w') as log:
            os.fchmod(log.fileno(), 0o600)
            process = subprocess.Popen([str(executable), '--user-data-dir='+str(root/'browser'),
                '--remote-debugging-port=18877', '--use-mock-keychain', '--no-first-run',
                '--no-default-browser-check', '--disable-component-update',
                '--disable-background-networking', 'about:blank'], env=env,
                stdout=log, stderr=log, start_new_session=True)
            report['pid'] = process.pid
            for _ in range(150):
                assert process.poll() is None
                try:
                    with urllib.request.urlopen('http://127.0.0.1:18877/json/version', timeout=.3) as response:
                        report['browser_version'] = json.load(response)['Browser']
                    break
                except OSError:
                    time.sleep(.1)
            else:
                raise TimeoutError('Owned reference browser readiness')
            result = subprocess.run(['node', str(HERE/'quota_pressure_probe.mjs'), '18877'],
                                    capture_output=True, text=True, timeout=300)
            write_private(root/'probe-process.private.json', {'exit_code':result.returncode,
                          'stdout':result.stdout, 'stderr':result.stderr})
            assert result.returncode == 0, result.stderr[-2000:]
            report['observations'] = json.loads(result.stdout.splitlines()[-1])
            assert report['observations']['completed'] is True
            subprocess.run([str(a.ui_helper),str(process.pid),'quit'],
                           env=dict(env,METABROWSER_UI_NO_ACTIVATE='1'),check=True,timeout=10)
            process.wait(timeout=20)
            assert process.returncode == 0
            report.update(completed=True, clean_shutdown=True)
            assert all(digest(Path(f)) == h for f,h in report['probe_sha256'].items())
    except BaseException as error:
        report['error'] = str(error)
        raise
    finally:
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=20)
        server.shutdown()
        server.server_close()
        write_private(a.output, report)
    print(json.dumps({'completed':True, 'browser_version':report['browser_version'],
                      'same_version_baseline_proven':False}))


if __name__ == '__main__':
    main()
