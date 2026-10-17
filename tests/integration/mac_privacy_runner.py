"""Collect five real Mac privacy modes in an explicitly owned SDK-free fixture.

Requires STATE_JSON with root/font/family/installed_font, the root marker
.metabrowser-owned-fixture containing mac-privacy, and a compiled panel_ui.swift
helper for graceful quit. Uses headed CDP navigation without viewport emulation
or a model run; native global-settings tests separately exercise AX navigation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import signal
import subprocess
import time
import urllib.error
import urllib.request
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('state', type=Path)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--reports', type=Path, required=True)
    parser.add_argument('--ui-helper', type=Path, required=True)
    args = parser.parse_args()
    state = json.loads(args.state.read_text())
    root = Path(state['root']).resolve(strict=True)
    assert (root / '.metabrowser-owned-fixture').read_text() == 'mac-privacy'
    app = args.app.resolve(strict=True)
    assert not (app / 'Contents/Frameworks/libmetabrowser_metacodes.dylib').exists(), 'SDK-free fixture required'
    executable = app / 'Contents/MacOS/Chromium'
    assert executable.is_file() and args.ui_helper.is_file()
    for port in (18841, 18842, 18844):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM if port == 18844 else socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('127.0.0.1', port))
    font = Path(state['font']).read_bytes()
    installed = Path(state['installed_font'])
    assert installed.parent == Path.home() / 'Library/Fonts'
    assert installed.name == state['family'] + '.ttf'
    assert state['family'].startswith('MetaBrowserPrivacyCanary') and not installed.exists()
    env = {k: v for k, v in os.environ.items() if k in (
        'HOME', 'PATH', 'TMPDIR', 'USER', 'LOGNAME', 'SHELL', 'LANG',
        'LC_CTYPE', '__CF_USER_TEXT_ENCODING')}
    env['METABROWSER_IDENTITY_HOME'] = str(root / 'identities')
    state.update(reports={}, completed=False, navigation='headed-CDP-no-emulation',
                 framework_sha256=hashlib.sha256((app / 'Contents/Frameworks/Chromium Framework.framework/Chromium Framework').read_bytes()).hexdigest())

    def save():
        temporary = args.state.with_name(args.state.name + '.tmp')
        with temporary.open('w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(state, stream)
        temporary.replace(args.state)

    def wait(check, label, seconds=180):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                result = check()
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                result = False
            if result:
                return result
            time.sleep(.2)
        raise AssertionError(label)

    def request(path):
        with urllib.request.urlopen('http://127.0.0.1:18842/' + path, timeout=2) as response:
            return json.load(response)

    def stop(process, require_clean=False):
        if process and process.poll() is None:
            if require_clean:
                subprocess.run([str(args.ui_helper), str(process.pid), 'quit'],
                               env=env, capture_output=True, timeout=10, check=True)
            else:
                process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                if require_clean:
                    raise AssertionError('Forced shutdown cannot prove clean cold restart')
        if require_clean:
            assert process.returncode == 0, 'Native browser did not exit cleanly'

    def interrupted(signum, frame):
        raise KeyboardInterrupt('Fixture interrupted')
    signal.signal(signal.SIGTERM, interrupted)

    server = browser = None
    installed_by_us = False
    args.reports.mkdir(parents=True, exist_ok=True)
    log = args.state.with_name(args.state.stem + '.runtime.log').open('w')
    os.fchmod(log.fileno(), 0o600)
    try:
        with installed.open('xb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            installed_by_us = True
            stream.write(font)
        state['font_installed_by_fixture'] = True
        save()
        server = subprocess.Popen(['python3', str(Path(__file__).with_name('mac_privacy_probe.py')),
            '--output', str(args.reports), '--font', state['font']], stdout=log, stderr=log)
        state['server_pid'] = server.pid
        wait(lambda: request('stun-count') if server.poll() is None else False, 'Probe server unavailable', 10)
        for name, profile, flags in (
            ('baseline', 'baseline', ['--metabrowser-privacy=off']), ('a', 'a', []),
            ('b', 'b', []), ('a_restart', 'a', []),
            ('strict', 'strict', ['--metabrowser-webrtc-policy=disable_non_proxied_udp'])):
            # These two fixture-only preferences prevent automatic restoration
            # of old probe pages. Their service-worker scopes would otherwise
            # race with the fresh capture. Keep keys, cookies and storage.
            for filename, section, key, setting in (
                    ('Default/Preferences', 'session', 'restore_on_startup', 5),
                    ('Local State', 'was', 'restarted', False)):
                target = root / profile / 'browser' / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                prefs = json.loads(target.read_text()) if target.exists() else {}
                prefs.setdefault(section, {})[key] = setting
                with target.open('w') as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    json.dump(prefs, stream)
            mode_env = dict(env, METABROWSER_CONVERSATION_HOME=str(root/profile/'conversations'),
                            METABROWSER_ACCOUNT_HOME=str(root/profile/'account'),
                            METABROWSER_WORKSPACE=str(root/profile/'workspace'))
            browser = subprocess.Popen([str(executable), '--user-data-dir='+str(root/profile/'browser'),
                '--remote-debugging-port=18841',
                '--window-size=1200,900', '--use-mock-keychain', '--no-first-run', '--no-default-browser-check',
                '--hide-crash-restore-bubble', '--autoplay-policy=no-user-gesture-required',
                '--disable-component-update', '--disable-background-networking',
                '--enable-blink-features=WebGPUDeveloperFeatures', *flags, 'about:blank'],
                env=mode_env, stdout=log, stderr=log, start_new_session=True)
            state.update(active_mode=name, active_pid=browser.pid)
            save()
            def ready():
                assert browser.poll() is None, 'Fixture browser exited'
                with urllib.request.urlopen('http://127.0.0.1:18841/json/version', timeout=1) as response:
                    return 'webSocketDebuggerUrl' in json.load(response)
            wait(ready, 'Native fixture window unavailable', 30)
            run = str(uuid.uuid4())
            report = args.reports / (run + '.json')
            before = request('stun-count')['count']
            navigation = subprocess.run(['node', str(Path(__file__).with_name('mac_probe_navigate.mjs')), '18841',
                f'http://127.0.0.1:18842/?run={run}&font={state["family"]}'],
                env=env, capture_output=True, text=True, timeout=30)
            assert navigation.returncode == 0, 'Fixture navigation failed: ' + navigation.stderr[-2000:]
            wait(report.exists, 'Probe report missing: ' + name)
            value = json.loads(report.read_text())
            errors = {k: v['error'] for k, v in value.items() if isinstance(v, dict) and 'error' in v}
            assert not errors, (name, errors)
            state['reports'][name] = {'file': report.name, 'stun_requests': request('stun-count')['count']-before}
            # Keep resumable fixture contents harmless before a clean exit.
            # macOS can restore blank windows independently of startup prefs.
            subprocess.run(['node', str(Path(__file__).with_name('mac_probe_navigate.mjs')),
                '18841', 'about:blank'], env=env, capture_output=True, timeout=30, check=True)
            stop(browser, require_clean=True)
            state['reports'][name]['clean_shutdown'] = True
            save()
            browser = None
            print(json.dumps({'collected': name, 'headed_no_emulation': True, 'clean_shutdown': True}), flush=True)
        state.update(completed=True, active_mode='completed', active_pid=None)
    finally:
        cleanup_errors = []
        for process in (browser, server):
            try:
                stop(process)
            except Exception as error:
                cleanup_errors.append(str(error))
        try:
            if installed_by_us and installed.exists():
                assert installed.read_bytes() == font, 'Owned canary font was replaced externally'
                installed.unlink()
            state['font_installed_by_fixture'] = False
        except Exception as error:
            cleanup_errors.append(str(error))
        state['cleanup_errors'] = cleanup_errors
        if cleanup_errors:
            state['completed'] = False
        try:
            save()
        finally:
            log.close()
        if cleanup_errors:
            raise RuntimeError('Fixture cleanup failed: ' + '; '.join(cleanup_errors))


if __name__ == '__main__':
    main()
