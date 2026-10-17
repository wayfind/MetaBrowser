"""Exercise native identity UI in an explicitly isolated operator fixture.

Usage: python3 identity_profiles_test.py PID FIXTURE_ROOT IDENTITY_HOME
Never starts a provider, uses the main profile, grants permissions, or sends an
agent prompt. Opening identities is an actual native browser operation.
"""
import json
import pathlib
import subprocess
import sys
import time

pid, fixture, home = sys.argv[1], pathlib.Path(sys.argv[2]).resolve(), pathlib.Path(sys.argv[3]).resolve()
assert home.is_relative_to(fixture)
command = subprocess.check_output(['ps', '-p', pid, '-o', 'command='], text=True)
assert '--user-data-dir=' + str(fixture / 'profile') in command
assert (fixture / 'profile/.browser-broker-fixture-profile').exists()


def ui(*args):
    return subprocess.check_output(['/tmp/metabrowser-panel-ui', pid, *args], text=True)


def wait(check, description, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(.1)
    raise AssertionError(description)


def records():
    return {p.parent.name: json.loads(p.read_text()) for p in home.glob('*/identity.json')}


ui('press', '登录 Metask')
wait(lambda: 'AXButton 账户设置' in ui('dump'), 'browser account menu')
ui('press', '账户设置')
wait(lambda: '浏览器身份名称' in ui('dump'), 'identity page')
wait(lambda: '尚未创建独立身份' in ui('dump'), 'initial catalogue loaded')
assert not records(), 'Use a fresh fixture identity home'
ui('set', '浏览器身份名称', '研究身份 A')
ui('press', '身份网页语言')
ui('press', 'English · en-US')
wait(lambda: 'AXPopUpButton 身份网页语言 English · en-US' in ui('dump'), 'language selection committed')
ui('press', '身份时区')
ui('press', '美国东部 · America/New_York')
wait(lambda: 'AXPopUpButton 身份时区 美国东部 · America/New_York' in ui('dump'), 'timezone selection committed')
ui('press', '新建身份')
first = wait(lambda: records() if len(records()) == 1 else None, 'create identity')
first_id = next(iter(first))
assert first[first_id]['languages'] == 'en-US,en'
assert first[first_id]['timezone'] == 'America/New_York'
assert first[first_id]['template'] == 'native-macos-arm64-v1'
wait(lambda: 'AXPopUpButton 浏览器身份列表 研究身份 A' in ui('dump'), 'selected identity')
ui('set', '浏览器身份名称', '研究身份 A · 已保存')
ui('press', '保存配置')
wait(lambda: records()[first_id]['name'] == '研究身份 A · 已保存', 'rename')
ui('press', '复制配置')
second = wait(lambda: records() if len(records()) == 2 else None, 'copy configuration')
second_id = next(k for k in second if k != first_id)
assert second[second_id]['languages'] == first[first_id]['languages']
assert second[second_id]['timezone'] == 'America/New_York'
assert not (home / second_id / 'browser').exists(), 'copy must not copy browser data'
assert not (home / second_id / 'account').exists(), 'copy must not copy credentials'
ui('press', '检查配置')
wait(lambda: '配置检查通过' in ui('dump'), 'constrained configuration check')
ui('press', '打开身份')


def child():
    processes = subprocess.check_output(['ps', '-axo', 'pid,command'], text=True)
    for line in processes.splitlines():
        if '--user-data-dir=' + str(home / second_id / 'browser') in line and '--type=' not in line:
            return int(line.strip().split(None, 1)[0])
    return None


child_pid = wait(child, 'real independent browser process')
args = subprocess.check_output(['ps', '-p', str(child_pid), '-o', 'command='], text=True)
assert '--accept-lang=en-US,en' in args
assert '--metacodes-demo-prompt' not in args and '--remote-debugging' not in args
assert '--metabrowser-privacy=off' not in args
for part in ('browser', 'account', 'conversations', 'workspace'):
    path = home / second_id / part
    assert path.is_dir() and path.stat().st_mode & 0o777 == 0o700
for path in (home / second_id / 'conversations').glob('*.json'):
    record = json.loads(path.read_text())
    assert not [m for m in record.get('messages', []) if m.get('role') in ('user', 'assistant')]
print(json.dumps({'passed': True, 'create': True, 'rename': True, 'copy_configuration_only': True,
                  'independent_browser_process': True, 'language_launch_option': True,
                  'fresh_agent_and_account_directories': True, 'child_pid': child_pid,
                  'scope': 'identity management, not cross-platform/GPU simulation'}))
