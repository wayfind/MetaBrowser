"""Native global Profile acceptance with custom IANA timezones and display/RTC.

Usage: python3 mac_identity_settings_test.py PID FIXTURE_ROOT IDENTITY_HOME
Requires SDK-free app, explicit .browser-broker-fixture-profile marker, compiled
AX helpers, and loopback timezone probe on 18832. Never uses the real profile,
provider, permission grants or account data. Closes only its own identity child.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid


def main():
    pid, fixture, home = sys.argv[1], Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    command = subprocess.check_output(['ps', '-p', pid, '-o', 'command='], text=True)
    assert '--user-data-dir=' + str(fixture / 'profile') in command
    assert (fixture / 'profile/.browser-broker-fixture-profile').exists()
    assert home.is_relative_to(fixture) and not list(home.glob('*/identity.json'))
    env = dict(os.environ, METABROWSER_UI_NO_ACTIVATE='1')
    children = []

    def ui(*args):
        return subprocess.check_output(['/tmp/metabrowser-profile-ui', pid, *args], env=env, text=True, stderr=subprocess.PIPE)

    def wait(check, description, seconds=25):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            value = check()
            if value:
                return value
            time.sleep(.15)
        raise AssertionError(description)

    def records():
        return {p.parent.name: json.loads(p.read_text()) for p in home.glob('*/identity.json')}

    def choose(name, value):
        ui('press', name)
        time.sleep(.2)
        ui('press', value)
        wait(lambda: any(line.startswith('AXPopUpButton ' + name + ' ') and line.endswith(value)
                         for line in ui('dump').splitlines()), name + ' selection')

    def parent_alive():
        stat = subprocess.check_output(['ps', '-p', pid, '-o', 'stat='], text=True).strip()
        assert stat and not stat.startswith('Z'), 'Parent browser exited'

    def child(identity):
        token = '--user-data-dir=' + str(home / identity / 'browser')
        for line in subprocess.check_output(['ps', '-axo', 'pid=,stat=,command='], text=True).splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) == 3 and token in parts[2].split() and '--type=' not in parts[2] and not parts[1].startswith('Z'):
                return int(parts[0])
        return None

    def collect(identity, expected_offset, expected_language=None, system_language=False):
        ui('press', '打开身份')
        current = wait(lambda: child(identity), 'identity browser')
        children.append((current, identity))
        args = subprocess.check_output(['ps', '-p', str(current), '-o', 'command='], text=True)
        assert '--metabrowser-webrtc-policy=disable_non_proxied_udp' in args
        assert '--use-mock-keychain' in args, 'Owned identity child must not use the real credential store'
        version_policy=records()[identity].get('platform_version_policy','major')
        assert '--metabrowser-platform-version-policy='+version_policy in args
        actual_version=subprocess.check_output(['/usr/bin/sw_vers','-productVersion'],text=True).strip()
        expected_version='.'.join((actual_version.split('.')+['0','0'])[:3]) if version_policy=='system' else actual_version.split('.')[0]+'.0.0'
        for flag in ('--use-gl=angle', '--use-angle=swiftshader', '--use-webgpu-adapter=swiftshader',
                     '--disable-accelerated-video-decode', '--disable-accelerated-video-encode'):
            assert flag in args, 'Software GPU selection did not reach identity child'
        assert '--enable-unsafe-webgpu' not in args and '--disable-dawn-features' not in args
        language_arg = next((s.split('=', 1)[1] for s in args.split() if s.startswith('--accept-lang=')), None)
        if expected_language or system_language:
            assert language_arg, 'Identity omitted explicit language transition'
        if system_language:
            native = json.loads(subprocess.check_output(['swift', '-e',
                'import Foundation; print(String(data:try! JSONSerialization.data(withJSONObject:Locale.preferredLanguages),encoding:.utf8)!)'], text=True))
            assert language_arg.split(',')[0].lower() in {s.replace('_','-').lower() for s in native}, 'System language did not come from native preferences'
            expected_language = language_arg.split(',')[0]

        wait(lambda: 'AXTextField 地址和搜索栏' in subprocess.check_output(
            ['/tmp/metabrowser-profile-ui', str(current), 'dump'], text=True, env=env), 'child UI')
        run = str(uuid.uuid4())
        report = Path('out/evidence/identity-timezone-reports') / (run + '.json')
        navigation=subprocess.run(['/tmp/metabrowser-panel-ui', str(current), 'navigate',
                        'http://127.0.0.1:18832/?run=' + run], capture_output=True,text=True)
        if navigation.returncode:
            diagnostic=fixture/('navigation-helper-failure-'+run+'.log')
            diagnostic.write_text(navigation.stderr);diagnostic.chmod(0o600)
            dump=subprocess.check_output(['/tmp/metabrowser-profile-ui',str(current),'dump'],text=True,env=env)
            diagnostic=fixture/('navigation-helper-failure-'+run+'.txt');diagnostic.write_text(dump);diagnostic.chmod(0o600)
            raise AssertionError('Native navigation helper failed: '+navigation.stderr[:1200])
        try:
            wait(report.exists, 'native timezone report')
        except AssertionError:
            dump = subprocess.check_output(['/tmp/metabrowser-panel-ui', str(current), 'dump'], env=env, text=True)
            diagnostic = fixture / ('navigation-failure-' + run + '.txt')
            diagnostic.write_text(dump)
            diagnostic.chmod(0o600)
            raise
        value = json.loads(report.read_text())
        assert 'error' not in value
        assert json.loads(value['sec_ch_platform_version'])==expected_version
        assert all(value['report'][realm]['platformVersion']==expected_version for realm in ('window','iframe','dedicated','module','nested','shared','service'))
        for realm in ('window', 'iframe', 'dedicated', 'module', 'nested', 'shared', 'service'):
            assert value['report'][realm]['winter'] == value['report'][realm]['summer'] == expected_offset
        if expected_language:
            languages = value['report']['window']['languages']
            assert languages[0].lower() == expected_language.lower()
            for realm in ('iframe','dedicated','module','nested','shared','service'):
                assert value['report'][realm]['languages'] == languages
            assert value['accept_language'].lower().startswith(expected_language.lower()), 'HTTP and navigator language mismatch'
        for realm in ('window', 'iframe'):

            assert value['report'][realm]['screen'] == {'width': 1920, 'height': 1200}
        subprocess.run(['/tmp/metabrowser-panel-ui',str(current),'quit'],check=True,capture_output=True)
        wait(lambda: not subprocess.run(['ps', '-p', str(current), '-o', 'stat='],
                                       capture_output=True, text=True).stdout.strip(), 'identity child reaped')
        parent_alive()
        subprocess.run(['/tmp/metabrowser-panel-ui', pid, 'dump'], check=True, capture_output=True)
        time.sleep(.25)
        return report.name

    try:
        subprocess.run(['/tmp/metabrowser-panel-ui', pid, 'press', '登录 Metask'], check=True, capture_output=True)
        wait(lambda: 'AXButton 账户设置' in ui('dump'), 'account bubble')
        ui('press', '账户设置')
        wait(lambda: '尚未创建独立身份' in ui('dump'), 'empty catalog')
        ui('set', '浏览器身份名称', 'Mac 设置验收')
        choose('身份时区', '自定义 IANA 时区')
        wait(lambda: '自定义 IANA 时区名称' in ui('dump'), 'custom timezone field')
        ui('set', '自定义 IANA 时区名称', 'Asia/Kolkata')
        choose('身份显示区域', '1920 × 1200')
        choose('身份窗口尺寸', '1280 × 900')
        choose('身份 WebRTC 网络策略', '严格代理 · 禁止 UDP 直连')
        choose('身份 GPU 后端', '软件 GPU · 隔离硬件型号')
        ui('press', '新建身份')
        data = wait(lambda: records() or None, 'saved custom profile')
        identity = next(iter(data))
        assert data[identity]['timezone'] == 'Asia/Kolkata'
        assert data[identity]['display'] == '1920x1200'
        assert data[identity]['webrtc'] == 'disable_non_proxied_udp'
        assert data[identity]['gpu'] == 'software'
        assert data[identity]['platform_version_policy'] == 'major'
        wait(lambda: 'AXPopUpButton 浏览器身份列表 Mac 设置验收' in ui('dump'), 'selected created profile')
        india = collect(identity, -330)
        ui('set', '自定义 IANA 时区名称', ':/etc/passwd')
        previous = records()[identity]
        ui('press', '保存配置')
        wait(lambda: '无法识别此 IANA 时区' in ui('dump'), 'invalid timezone rejected')
        assert records()[identity] == previous
        ui('set', '自定义 IANA 时区名称', 'Asia/Kathmandu')
        ui('press', '保存配置')
        wait(lambda: records()[identity]['timezone'] == 'Asia/Kathmandu', 'quarter-hour timezone saved')
        wait(lambda: '正在读取' not in ui('dump') and '正在保存' not in ui('dump'), 'save complete')
        nepal = collect(identity, -345)
        choose('身份系统版本策略', '公开系统完整版本')
        choose('身份网页语言', '日本語 · ja-JP')
        ui('press', '保存配置')
        wait(lambda: records()[identity]['languages'] == 'ja-JP,ja', 'Japanese saved')
        wait(lambda: '正在读取' not in ui('dump') and '正在保存' not in ui('dump'), 'language save complete')
        japanese = collect(identity, -345, expected_language='ja-JP')
        choose('身份网页语言', '跟随系统')
        ui('press', '保存配置')
        wait(lambda: records()[identity]['languages'] == 'system', 'System language saved')
        wait(lambda: '正在读取' not in ui('dump') and '正在保存' not in ui('dump'), 'system save complete')
        system = collect(identity, -345, system_language=True)
        ui('press', '复制配置')
        copied = wait(lambda: records() if len(records()) == 2 else None, 'copy custom configuration')
        new_id = next(k for k in copied if k != identity)
        assert copied[new_id]['timezone'] == 'Asia/Kathmandu'
        assert copied[new_id]['display'] == '1920x1200'
        assert copied[new_id]['webrtc'] == 'disable_non_proxied_udp'
        assert copied[new_id]['gpu'] == 'software'
        assert copied[new_id]['platform_version_policy'] == 'system'
        assert not (home / new_id / 'browser').exists()
        assert not (home / new_id / 'account').exists()
        # Legacy profiles retain data and default to the new major-only policy.
        config=home/new_id/'identity.json';saved=config.read_text();legacy=json.loads(saved);legacy.pop('platform_version_policy');config.write_text(json.dumps(legacy));config.chmod(0o600)
        ui('press','刷新身份');wait(lambda:any(line.startswith('AXPopUpButton 身份系统版本策略 ') and line.endswith('仅公开主版本') for line in ui('dump').splitlines()),'legacy version policy default')
        legacy_report=collect(new_id,-345,system_language=True)
        assert 'platform_version_policy' not in json.loads(config.read_text()),'Opening legacy profile silently rewrote metadata'
        for invalid in ['unexpected',False,{}]:
            config.write_text(saved);config.chmod(0o600);ui('press','刷新身份')
            wait(lambda:any(line.startswith('AXPopUpButton 身份系统版本策略 ') and line.endswith('公开系统完整版本') for line in ui('dump').splitlines()),'valid copy before invalid policy')
            malformed=dict(legacy,platform_version_policy=invalid);encoded=json.dumps(malformed);config.write_text(encoded);config.chmod(0o600)
            ui('press','刷新身份');wait(lambda:any(line.startswith('AXTextField 浏览器身份名称 ') and line.endswith('Mac 设置验收') for line in ui('dump').splitlines()),'invalid version policy excluded')
            assert config.read_text()==encoded and child(new_id) is None
        config.write_text(saved);config.chmod(0o600);ui('press','刷新身份')
        wait(lambda:any(line.startswith('AXPopUpButton 身份系统版本策略 ') and line.endswith('公开系统完整版本') for line in ui('dump').splitlines()),'valid copy restored')
        print(json.dumps({'passed': True, 'global_ui_custom_iana': True,
                          'half_hour_and_quarter_hour_seven_realms': True,
                          'invalid_tz_path_rejected_without_overwrite': True,
                          'display_environment_reaches_renderer': True,
                          'rtc_policy_reaches_native_browser': True,
                          'software_gpu_saved_copied_and_child_flags': True,
                          'software_video_acceleration_disabled': True,
                          'no_unsafe_webgpu_flags': True,
                          'copy_configuration_only': True, 'child_reaped_parent_alive': True,
                          'language_fixed_to_system_transition': True,
                          'language_http_and_seven_realms': True,
                          'platform_version_ui_copy_child_http_seven_realms':True,
                          'legacy_version_policy_no_rewrite':True,
                          'invalid_version_policy_catalog_rejected_unchanged':True,
                          'reports': [india, nepal, japanese, system, legacy_report], 'paid_model_calls': 0}))
    finally:
        for current, identity in children:
            if child(identity) == current:
                os.kill(current, signal.SIGTERM)


if __name__ == '__main__':
    main()
