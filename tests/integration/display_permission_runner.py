"""Drive display_permission_fixture.mjs against a fresh, owned profile.

The fixture checks ScreenDetailed color primaries and HDR headroom on retained
objects after revocation. Those attributes are behind the experimental CanvasHDR
runtime feature, so the browser starts with --enable-blink-features=CanvasHDR;
without it the attributes are absent and the revocation check cannot pass.
The probe server (mac_privacy_probe.py) serves /display-only on 18842. No real
profile, account or model provider is used.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--font', type=Path, required=True, help='Small test font served by the probe server')
    parser.add_argument('--ui-helper', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New private report; never overwritten')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Fresh output required')
    app = args.app.resolve(strict=True)
    root = Path(tempfile.mkdtemp(prefix='metabrowser-display-fixture-'))
    log = (root / 'runtime.log').open('w')
    os.fchmod(log.fileno(), 0o600)
    server = subprocess.Popen([sys.executable, str(HERE / 'mac_privacy_probe.py'), '--output', str(root / 'reports'),
                               '--font', str(args.font)], stdout=log, stderr=log)
    browser, result = None, {'completed': False}
    try:
        time.sleep(1.5)
        browser = subprocess.Popen([str(app / 'Contents/MacOS/Chromium'), '--user-data-dir=' + str(root / 'browser'),
            '--remote-debugging-port=18841', '--window-size=1200,900', '--use-mock-keychain', '--no-first-run',
            '--no-default-browser-check', '--hide-crash-restore-bubble', '--autoplay-policy=no-user-gesture-required',
            '--enable-blink-features=CanvasHDR', '--disable-component-update', '--disable-background-networking',
            'about:blank'], stdout=log, stderr=log, start_new_session=True)
        for _ in range(150):
            try:
                urllib.request.urlopen('http://127.0.0.1:18841/json/version', timeout=.5).read()
                break
            except OSError:
                time.sleep(.2)
        run = subprocess.run(['node', str(HERE / 'display_permission_fixture.mjs'), '18841', 'http://127.0.0.1:18842'],
                             capture_output=True, text=True, timeout=240)
        result.update(exit_code=run.returncode, stdout=run.stdout[-4000:], stderr=run.stderr[-3000:])
        subprocess.run([str(args.ui_helper), str(browser.pid), 'quit'],
                       env=dict(os.environ, METABROWSER_UI_NO_ACTIVATE='1'), timeout=10, check=True)
        browser.wait(20)
        result.update(browser_exit_code=browser.returncode, completed=run.returncode == 0 and browser.returncode == 0)
    finally:
        if browser and browser.poll() is None:
            result['forced_cleanup'] = True
            browser.terminate()
            browser.wait(20)
        server.terminate()
        server.wait(10)
        log.close()
        framework = app / 'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'
        result.update(root=str(root), framework_sha256=hashlib.sha256(framework.read_bytes()).hexdigest(),
                      runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), paid_model_calls=0)
        with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
            json.dump(result, stream, indent=1)
            stream.write('\n')
    print(json.dumps({k: result.get(k) for k in ('completed', 'exit_code', 'browser_exit_code')}))
    return 0 if result['completed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
