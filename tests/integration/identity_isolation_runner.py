"""Fresh native UI profile/clone/storage acceptance; local fixture and no prompts."""
import argparse
import hashlib
from http.cookies import SimpleCookie
import http.server
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit
import uuid

from identity_isolation_acceptance import MARKER, digest, hex_value, verify

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]


def write_private(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w') as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    os.replace(temporary, path)


class Fixture(http.server.ThreadingHTTPServer):
    def __init__(self, root):
        self.root = root
        self.expected = {}
        self.reports = {}
        self.accept_languages = {}
        self.refused_replays = []
        self.provider_posts = []
        self.lock = threading.Lock()
        super().__init__(('127.0.0.1', 0), Handler)
        self.origin = 'http://127.0.0.1:' + str(self.server_port)


class Handler(http.server.BaseHTTPRequestHandler):
    timeout = 5

    def log_message(self, *_):
        pass

    def reply(self, payload, content_type='application/json', *, cache='no-store', cookie=None):
        body = payload.encode() if isinstance(payload, str) else payload
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', cache)
        self.send_header('Content-Length', str(len(body)))
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        if url.path == '/':
            run = query.get('run', [''])[0]
            token = query.get('token', [''])[0]
            # A restored tab must not rerun the probe and rewrite the stores
            # that the next observation reads as persisted state.
            with self.server.lock:
                expected = self.server.expected.get(run)
                replay = run in self.server.reports
                if replay:
                    self.server.refused_replays.append(run)
                elif expected == token and hex_value(token, 32):
                    self.server.accept_languages.setdefault(run, []).append(self.headers.get('Accept-Language'))
            if replay:
                self.send_error(410, 'Reported run is never served again')
                return
            if expected != token or not hex_value(token, 32):
                self.send_error(400, 'Registered owned run required')
                return
            self.reply('<!doctype html><meta charset=utf-8><title>Owned identity isolation</title>'
                       '<pre>Collecting native profile evidence...</pre>'
                       '<script src="/cache-marker.js"></script><script src="/probe.js"></script>',
                       'text/html; charset=utf-8')
        elif url.path == '/probe.js':
            self.reply((HERE / 'identity_isolation_probe.js').read_bytes(), 'text/javascript')
        elif url.path == '/cache-marker.js':
            self.reply('globalThis.ownedHttpCache=' + json.dumps(secrets.token_hex(16)) + ';',
                       'text/javascript', cache='private, max-age=31536000, immutable')
        elif url.path == '/cookie/read':
            cookies = SimpleCookie(self.headers.get('Cookie', ''))
            item = cookies.get('metabrowser_owned_isolation')
            self.reply(json.dumps({'marker': item.value if item else None}))
        elif url.path == '/cookie/set':
            token = query.get('token', [''])[0]
            with self.server.lock:
                allowed = token in self.server.expected.values()
            if not allowed or not hex_value(token, 32):
                self.send_error(400, 'Owned marker required')
                return
            self.reply('{}', cookie='metabrowser_owned_isolation=' + token +
                       '; HttpOnly; SameSite=Lax; Path=/; Max-Age=86400')
        elif url.path == '/v1/models':
            self.reply('{"data":[]}')
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != '/report':
            with self.server.lock:
                self.server.provider_posts.append(self.path)
            self.send_error(403, 'No model requests permitted')
            return
        try:
            assert self.headers.get('Origin') == self.server.origin
            assert self.headers.get('Host') == self.server.origin.removeprefix('http://')
            size = int(self.headers.get('Content-Length', '0'))
            assert 0 < size <= 65536
            value = json.loads(self.rfile.read(size))
            run = str(uuid.UUID(value['run']))
            with self.server.lock:
                assert run in self.server.expected and run not in self.server.reports
                assert value.get('error') or value['report']['token'] == self.server.expected[run]
                value['host'] = self.headers['Host']
                value['accept_language'] = list(self.server.accept_languages.get(run, []))
                write_private(self.server.root / 'reports' / (run + '.json'), value)
                self.server.reports[run] = value
            self.reply('{}')
        except (AssertionError, KeyError, TypeError, ValueError):
            self.send_error(400, 'Invalid or duplicate owned report')


def processes():
    rows = []
    text = subprocess.check_output(['ps', '-axo', 'pid=,stat=,command='], text=True)
    for line in text.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3:
            rows.append((int(parts[0]), parts[1], parts[2]))
    return rows


def wait(check, description, seconds=35):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(.15)
    raise TimeoutError(description)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True, help='Complete application transport manifest')
    parser.add_argument('--ui-helper', type=Path, required=True, help='Compiled panel_ui.swift with Accessibility access')
    parser.add_argument('--output', type=Path, required=True, help='New private report; existing runs are never overwritten')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('Native macOS profile acceptance requires a macOS host')
    if args.output.exists() or args.output.is_symlink():
        parser.error('Fresh output required; preserve and inspect the existing run')
    if not args.app.is_dir():
        parser.error('Application not found; restore and validate the handoff candidate first')
    app = args.app.resolve(strict=True)
    helper = args.ui_helper.resolve(strict=True)
    assert helper.is_file() and os.access(helper, os.X_OK), 'Executable native UI helper required'
    executable = app / 'Contents/MacOS/Chromium'
    framework = app / 'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'
    manifest_command = [sys.executable, str(BASE / 'scripts/app-manifest.py'), str(app), '--check', str(args.manifest)]
    subprocess.run(manifest_command, check=True)
    if (app / 'Contents/Resources/agentcore').exists():
        subprocess.run([sys.executable, str(BASE / 'scripts/check-agentcore-bundle.py'),
                        str(app / 'Contents/Resources/agentcore')], check=True)
    root = Path(tempfile.mkdtemp(prefix='metabrowser-profile-isolation-')).resolve()
    assert not any(character.isspace() for character in str(root)), 'Unambiguous owned process paths required'
    (root / '.metabrowser-owned-fixture').write_text(MARKER)
    home = root / 'identities'
    fixture = Fixture(root)
    thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    thread.start()
    report = {'schema_version': 1, 'root': str(root), 'executable': str(executable),
              'framework_sha256': digest(framework), 'bundle_manifest_sha256': digest(args.manifest),
              'ui_helper_sha256': digest(helper), 'probe_sha256': {name: digest(HERE / name) for name in
                  ('identity_isolation_runner.py', 'identity_isolation_probe.js',
                   'identity_isolation_acceptance.py', 'panel_ui.swift')},
              'origin': fixture.origin, 'tokens': {name: secrets.token_hex(16) for name in ('a', 'b')},
              'profiles': {}, 'steps': [], 'completed': False, 'forced_cleanup': False,
              'parent_exit_code': None, 'provider_posts': [], 'refused_replays': [], 'paid_model_calls': 0,
              'production_cross_os_verified': False, 'full_scope_complete': False}
    env = {key: value for key, value in os.environ.items() if key in
           ('HOME', 'PATH', 'USER', 'LOGNAME', 'LANG', 'LC_CTYPE', 'TMPDIR', 'SHELL', '__CF_USER_TEXT_ENCODING')}
    env.update(METABROWSER_IDENTITY_HOME=str(home), METABROWSER_ACCOUNT_HOME=str(root / 'operator-account'),
               METABROWSER_CONVERSATION_HOME=str(root / 'operator-conversations'),
               METABROWSER_WORKSPACE=str(root / 'operator-workspace'), METABROWSER_API_KEY='fixture',
               METABROWSER_PROVIDER='openai', METABROWSER_MODEL='deny-only',
               METABROWSER_ENDPOINT=fixture.origin + '/v1/chat/completions')
    parent = None
    children = {}
    log = (root / 'runtime.private.log').open('w')
    os.fchmod(log.fileno(), 0o600)

    def ui(pid, *arguments, activate=False):
        return subprocess.check_output([str(helper), str(pid), *arguments], text=True, timeout=15,
                                       env=env if activate else dict(env, METABROWSER_UI_NO_ACTIVATE='1'),
                                       stderr=log)

    def activate_parent():
        # Activate once before opening a menu. Activating again between an
        # opener and its item can dismiss the native menu (see panel_ui.swift).
        ui(parent.pid, 'dump', activate=True)
        time.sleep(.3)

    def alive():
        assert parent.poll() is None, 'Parent browser exited during native identity acceptance'
        return True

    def records():
        return {path.parent.name: json.loads(path.read_text()) for path in home.glob('*/identity.json')}

    def owned_command(status, command, identity):
        if not status.startswith('Z') and command.startswith(str(executable) + ' '):
            arguments = command[len(str(executable)) + 1:].split()
            if '--user-data-dir=' + str(home / identity / 'browser') in arguments and not any(
                    value.startswith('--type=') for value in arguments):
                return command
        return None

    def child_command(pid, identity):
        for actual_pid, status, command in processes():
            if actual_pid == pid:
                return owned_command(status, command, identity)
        return None

    def open_identity(identity):
        alive()
        ui(parent.pid, 'press', '打开身份')
        def find():
            alive()
            for pid, status, command in processes():
                if owned_command(status, command, identity):
                    return pid
        pid = wait(find, 'Native identity browser did not start')
        children[pid] = identity
        wait(lambda: any(label in ui(pid, 'dump') for label in ('地址和搜索栏', 'Address and search bar')),
             'Native identity address bar not ready')
        return pid

    def observe(step, owner, pid):
        alive()
        run = str(uuid.uuid4())
        with fixture.lock:
            fixture.expected[run] = report['tokens'][owner]
        command = child_command(pid, report['profiles'][owner]['id'])
        assert command, 'Actual identity process not found'
        ui(pid, 'navigate', fixture.origin + '/?run=' + run + '&token=' + report['tokens'][owner], activate=True)
        raw = wait(lambda: fixture.reports.get(run), 'Native browser probe did not report', seconds=45)
        assert not raw.get('error'), raw.get('error')
        report['steps'].append({'step': step, 'profile': owner, 'run': run, 'pid': pid,
                                'command': command, 'parent_alive': alive(), 'observations': raw['report'],
                                'accept_language': raw['accept_language'],
                                'sha256': digest(root / 'reports' / (run + '.json'))})
        write_private(args.output, report)

    def quit_child(pid, owner):
        assert child_command(pid, report['profiles'][owner]['id']), 'Owned child process changed'
        ui(pid, 'quit')
        wait(lambda: alive() and all(actual != pid for actual, _, _ in processes()), 'Native child was not reaped')
        del children[pid]
        preferences = json.loads((home / report['profiles'][owner]['id'] / 'browser/Default/Preferences').read_text())
        secret = preferences['metabrowser']['privacy']['root_secret']
        assert isinstance(secret, str) and secret, 'Persistent root missing'
        report['profiles'][owner].update(native_quit_requested=True, reaped=True, parent_survived=True)
        return hashlib.sha256(secret.encode()).hexdigest()

    def interrupted(signum, frame):
        raise KeyboardInterrupt('Owned identity fixture interrupted')

    signal.signal(signal.SIGTERM, interrupted)

    try:
        write_private(args.output, report)
        parent = subprocess.Popen([str(executable), '--user-data-dir=' + str(root / 'operator-browser'),
                                   '--use-mock-keychain', '--no-first-run', '--no-default-browser-check',
                                   '--disable-component-update', '--disable-background-networking',
                                   '--hide-crash-restore-bubble', 'about:blank'],
                                  env=env, stdout=log, stderr=log, start_new_session=True)
        wait(lambda: alive() and '登录 Metask' in ui(parent.pid, 'dump'), 'Native parent not ready')
        activate_parent()
        ui(parent.pid, 'press', '登录 Metask')
        wait(lambda: 'AXButton 账户设置' in ui(parent.pid, 'dump'), 'Native account menu not ready')
        ui(parent.pid, 'press', '账户设置')
        wait(lambda: '尚未创建独立身份' in ui(parent.pid, 'dump'), 'Fresh identity settings not ready')
        ui(parent.pid, 'set', '浏览器身份名称', 'Owned isolation A')
        ui(parent.pid, 'press', '身份网页语言'); ui(parent.pid, 'press', 'English · en-US')
        wait(lambda: 'AXPopUpButton 身份网页语言 English · en-US' in ui(parent.pid, 'dump'), 'Language not committed')
        ui(parent.pid, 'press', '身份时区'); ui(parent.pid, 'press', '美国东部 · America/New_York')
        wait(lambda: 'AXPopUpButton 身份时区 美国东部 · America/New_York' in ui(parent.pid, 'dump'), 'Timezone not committed')
        ui(parent.pid, 'press', '新建身份')
        first = wait(lambda: records() if len(records()) == 1 else None, 'Native identity not saved')
        a_id = next(iter(first))
        report['profiles']['a'] = {'id': a_id, 'config': first[a_id]}
        wait(lambda: 'AXPopUpButton 浏览器身份列表 Owned isolation A' in ui(parent.pid, 'dump'), 'Created selection not ready')
        a_pid = open_identity(a_id)
        observe('a_first', 'a', a_pid)
        activate_parent()
        ui(parent.pid, 'press', '复制配置')
        copied = wait(lambda: records() if len(records()) == 2 else None, 'Native clone not saved')
        b_id = next(identity for identity in copied if identity != a_id)
        report['profiles']['b'] = {'id': b_id, 'config': copied[b_id]}
        report['clone_empty_directories'] = {name: not (home / b_id / name).exists()
                                             for name in ('browser', 'account', 'conversations', 'workspace')}
        assert all(report['clone_empty_directories'].values()), 'Native clone copied persistent data'
        wait(lambda: 'AXPopUpButton 浏览器身份列表 Owned isolation A · 副本' in ui(parent.pid, 'dump'), 'Cloned selection not ready')
        b_pid = open_identity(b_id)
        observe('b_first', 'b', b_pid)
        observe('a_live', 'a', a_pid)
        report['profiles']['b']['root_secret_sha256'] = quit_child(b_pid, 'b')
        report['profiles']['a']['root_secret_sha256'] = quit_child(a_pid, 'a')
        activate_parent()
        ui(parent.pid, 'press', '浏览器身份列表'); ui(parent.pid, 'press', 'Owned isolation A')
        wait(lambda: 'AXTextField 浏览器身份名称 Owned isolation A' in ui(parent.pid, 'dump').splitlines(), 'A selection not committed')
        a_pid = open_identity(a_id)
        observe('a_restart', 'a', a_pid)
        report['restart_root_secret_sha256'] = quit_child(a_pid, 'a')
        ui(parent.pid, 'quit'); parent.wait(timeout=25)
        report['parent_exit_code'] = parent.returncode
        subprocess.run(manifest_command, check=True)
        assert digest(framework) == report['framework_sha256'], 'Engine changed during run'
        assert digest(helper) == report['ui_helper_sha256'], 'UI helper changed during run'
        assert digest(args.manifest) == report['bundle_manifest_sha256'], 'Manifest changed during run'
        fixture.shutdown(); fixture.server_close(); thread.join(timeout=5)
        report['provider_posts'] = list(fixture.provider_posts)
        report['refused_replays'] = list(fixture.refused_replays)
        report['completed'] = True
        report['acceptance'] = verify(report, report['framework_sha256'])
        print(json.dumps(report['acceptance'], indent=2), flush=True)
    except BaseException as error:
        report.update(completed=False, error=str(error) or type(error).__name__)
        raise
    finally:
        for pid, identity in list(children.items()):
            if child_command(pid, identity):
                report['forced_cleanup'] = True
                subprocess.run(['kill', '-TERM', str(pid)], check=False)
                try:
                    wait(lambda: all(actual != pid for actual, _, _ in processes()),
                         'Failed child cleanup', seconds=10)
                except TimeoutError:
                    if child_command(pid, identity):
                        subprocess.run(['kill', '-KILL', str(pid)], check=False)
        if parent and parent.poll() is None:
            report['forced_cleanup'] = True
            parent.terminate()
            try:
                parent.wait(timeout=15)
            except subprocess.TimeoutExpired:
                parent.kill(); parent.wait(timeout=5)
        fixture.shutdown(); fixture.server_close(); thread.join(timeout=5)
        report['provider_posts'] = list(fixture.provider_posts)
        report['refused_replays'] = list(fixture.refused_replays)
        if report['provider_posts'] or report['forced_cleanup']:
            report['completed'] = False
            report.pop('acceptance', None)
        log.close()
        write_private(args.output, report)


if __name__ == '__main__':
    main()
