"""Owned, headed P1/P4/P9/P11/P12 collection; does not prove TLS or anonymity."""
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

BASE = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
HINTS = 'Sec-CH-UA-Full-Version, Sec-CH-UA-Full-Version-List, Sec-CH-UA-Platform-Version, Sec-CH-UA-Arch, Sec-CH-UA-Bitness, Sec-CH-UA-Model, Sec-CH-UA-WoW64, Sec-CH-UA-Form-Factors'


def digest(path):
    # The Mac harness also runs on the H200 host's Python 3.10.
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


def write_private(path, value):
    descriptor, tmp = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        collector = (HERE / 'identity_surface_collector.js').read_text()
        if self.path == '/echo':
            body = json.dumps({'protocol': self.request_version, 'headers': list(self.headers.raw_items())}).encode()
            content = 'application/json'
        elif self.path == '/collector.js':
            body, content = collector.encode(), 'text/javascript'
        elif self.path in ('/dedicated.js', '/shared.js', '/service.js'):
            action = "collectIdentitySurface().then(result=>port.postMessage({result})).catch(e=>port.postMessage({error:String(e)}))"
            if self.path == '/dedicated.js':
                code = 'onmessage=()=>{const port=self;' + action + '};'
            elif self.path == '/shared.js':
                code = 'onconnect=e=>{const port=e.ports[0];port.onmessage=()=>{' + action + '};port.start()};'
            else:
                code = "oninstall=e=>e.waitUntil(skipWaiting());onactivate=e=>e.waitUntil(clients.claim());onmessage=e=>{const port=e.ports[0];" + action + '};'
            body, content = (collector + '\n' + code).encode(), 'text/javascript'
        else:
            suffix = "<script>collectIdentitySurface().then(result=>parent.postMessage({result},location.origin)).catch(e=>parent.postMessage({error:String(e)},location.origin))</script>" if self.path == '/frame.html' else ''
            body, content = ('<!doctype html><title>Owned identity privacy probe</title><script src="/collector.js"></script>' + suffix).encode(), 'text/html'
        self.send_response(200)
        self.send_header('Content-Type', content)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Accept-CH', HINTS)
        self.end_headers()
        self.wfile.write(body)


def validate(data):
    """Only consistency gates; privacy exposure findings remain independent."""
    checks, details = {}, {}
    realms = data.get('realms', {})
    checks['all_five_realms_collected'] = set(realms) == {'window', 'iframe', 'dedicated', 'shared', 'service'} and data.get('errors') == {}
    expected = realms.get('window', {})
    stable = ('userAgent', 'appVersion', 'platform', 'language', 'languages', 'hardwareConcurrency', 'deviceMemory', 'uaData', 'time', 'math')
    differences = {name: [k for k in stable if value.get(k) != expected.get(k)] for name, value in realms.items()}
    checks['identity_realm_consistency'] = checks['all_five_realms_collected'] and not any(differences.values())
    details['identity_realm_consistency'] = differences
    headers = {k.lower(): v for k, v in data.get('headers', {}).get('headers', [])}
    checks['http_user_agent_matches_js'] = isinstance(expected.get('userAgent'), str) and headers.get('user-agent') == expected['userAgent']
    high = expected.get('uaData', {}).get('high', {})
    hints = {'platform':'platform', 'platform-version':'platformVersion', 'arch':'architecture', 'bitness':'bitness', 'model':'model', 'full-version':'uaFullVersion'}
    ch_diff = []
    for suffix, key in hints.items():
        try:
            if key not in (high if key != 'platform' else expected.get('uaData', {})) or json.loads(headers.get('sec-ch-ua-' + suffix, 'null')) != (expected['uaData']['platform'] if key == 'platform' else high[key]):
                ch_diff.append(key)
        except (ValueError, KeyError, TypeError):
            ch_diff.append(key)
    checks['http_client_hints_match_js'] = bool(high) and not ch_diff
    details['http_client_hints_match_js'] = ch_diff
    language = expected.get('language')
    checks['http_primary_language_matches_js'] = isinstance(language, str) and headers.get('accept-language', '').split(',')[0].lower() == language.lower()
    bindings = [value for realm in realms.values() for value in realm.get('nativeBindings', {}).values() if value is not None]
    checks['native_getters_preserved'] = checks['all_five_realms_collected'] and bool(bindings) and all('[native code]' in value for value in bindings)
    checks['no_node_process_global'] = checks['all_five_realms_collected'] and all(realm.get('globals', {}).get('process') is False for realm in realms.values())
    # Never describe observations as already mitigated. Native CH, storage and
    # timing information can be internally consistent while still identifying.
    findings = []
    if high.get('platformVersion'):
        findings.append({'id':'platform_version_observable', 'surface':'UA high-entropy/HTTP Client Hints', 'precision':'major' if high['platformVersion'].endswith('.0.0') else 'minor_patch', 'status':'requires_declared_profile_policy'})
    if isinstance(expected.get('battery'), dict) and 'level' in expected['battery']:
        findings.append({'id':'battery_observable', 'surface':'BatteryManager values and events', 'status':'requires_native_off_on_audit'})
    if not expected.get('connection', {}).get('absent'):
        findings.append({'id':'network_information_observable', 'surface':'NetworkInformation values and events', 'status':'requires_native_off_on_audit'})
    if isinstance(expected.get('storage', {}).get('quota'), (int, float)):
        findings.append({'id':'storage_quota_observable', 'surface':'StorageManager.estimate', 'status':'requires_quota_policy'})
    return {'checks': checks, 'details': details, 'consistency_passed': all(checks.values()), 'findings': findings, 'full_anonymity_passed': False}


def validate_passive(data, protected):
    trace=data.get('passiveSignalTrace', [])
    checks={'four_controlled_network_states':False,'native_online_state_preserved':False,
            'network_policy_window_worker_retained':False,'network_event_policy':False,
            'battery_snapshot_and_identity':False}
    if not isinstance(trace,list) or [x.get('phase') for x in trace if isinstance(x,dict)]!=['before','slow','fast','offline']:
        return {'checks':checks,'passed':False}
    observations=[x.get('observed',{}) for x in trace]
    checks['four_controlled_network_states']=all(isinstance(x,dict) and all(k in x for k in ['window','worker','retained','events','online','battery','retainedBattery','batteryEvents','batteryPromiseIdentity']) for x in observations)
    if not checks['four_controlled_network_states']:return {'checks':checks,'passed':False}
    checks['native_online_state_preserved']=[x['online'] for x in observations]==[True,True,True,False] and all(type(x['online']) is bool for x in observations)
    def values(obj):
        if not isinstance(obj,dict) or not all(k in obj for k in ['effectiveType','rtt','downlink']):return None
        if type(obj['effectiveType']) is not str or type(obj['rtt']) not in (int,float) or type(obj['downlink']) not in (int,float):return None
        return [obj[k] for k in ['effectiveType','rtt','downlink']]
    if protected:
        checks['network_policy_window_worker_retained']=all(values(x[k])==['4g',0,10] for x in observations for k in ['window','worker','retained'])
        checks['network_event_policy']=all(type(x['events']) is int and x['events']==0 for x in observations)
        canonical={'charging':True,'level':1,'chargingTime':0,'dischargingTime':'Infinity'}
        def battery_valid(b):
            return b==canonical and type(b.get('charging')) is bool and type(b.get('level')) in (int,float) and type(b.get('chargingTime')) in (int,float)
        checks['battery_snapshot_and_identity']=all(battery_valid(x['battery']) and battery_valid(x['retainedBattery']) and x['batteryPromiseIdentity'] is True and type(x['batteryEvents']) is int and x['batteryEvents']==0 for x in observations)
    else:
        slow=observations[1]
        checks['network_policy_window_worker_retained']=all(isinstance(slow[k],dict) and type(slow[k].get('rtt')) in (int,float) and slow[k]['rtt']>=700 for k in ['window','worker','retained']) and observations[2]['window']['rtt']<100
        checks['network_event_policy']=type(observations[-1]['events']) is int and observations[-1]['events']>=2
        checks['battery_snapshot_and_identity']=all(isinstance(x['battery'],dict) and x['battery']==x['retainedBattery'] and x['batteryPromiseIdentity'] is True for x in observations)
    return {'checks':checks,'passed':all(checks.values())}


def validate_version_policy(data, native_version, policy):
    parts=native_version.split('.')
    native='.'.join((parts+['0','0'])[:3])
    expected=native if policy=='system' else parts[0]+'.0.0'
    realms=data.get('realms',{})
    checks={'five_realm_platform_version_policy':False,'http_platform_version_policy':False}
    checks['five_realm_platform_version_policy']=set(realms)=={'window','iframe','dedicated','shared','service'} and all(v.get('uaData',{}).get('high',{}).get('platformVersion')==expected for v in realms.values())
    headers={k.lower():v for k,v in data.get('headers',{}).get('headers',[])}
    try:checks['http_platform_version_policy']=json.loads(headers.get('sec-ch-ua-platform-version','null'))==expected
    except (ValueError,TypeError):pass
    return {'checks':checks,'passed':all(checks.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--require-passive-policy', action='store_true')
    parser.add_argument('--identity-controls', action='store_true')
    parser.add_argument('--gpu',choices=('native','software'),default='native')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    app = args.app.resolve(strict=True)
    assert not (app/'Contents/Resources/agentcore').exists(), 'Use the SDK-free fixture app'
    assert not (app/'Contents/Frameworks/libmetabrowser_metacodes.dylib').exists()
    for port in (18860, 18861):
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('127.0.0.1', port))
    root = Path(tempfile.mkdtemp(prefix='metabrowser-identity-surfaces-')).resolve()
    env = {k: v for k, v in os.environ.items() if k in ('HOME', 'PATH', 'USER', 'LOGNAME', 'LANG', 'LC_CTYPE', 'TMPDIR', 'SHELL', '__CF_USER_TEXT_ENCODING')}
    env.update(METABROWSER_IDENTITY_HOME=str(root/'identities'), METABROWSER_ACCOUNT_HOME=str(root/'accounts'), METABROWSER_CONVERSATION_HOME=str(root/'conversations'), METABROWSER_WORKSPACE=str(root/'workspace'))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sources = {str(p.relative_to(BASE)): digest(p) for p in [Path(__file__).resolve(), HERE/'identity_surface_collector.js', HERE/'identity_surface_probe.mjs']}
    report = {'app':str(app), 'root':str(root), 'framework_sha256':digest(app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'), 'probe_sha256':sources, 'completed':False, 'paid_model_calls':0, 'modes':{}, 'full_anonymity_passed':False, 'scope':'P1/P4/P9/P11/P12 partial collection; HTTP/1 loopback, not TLS/H2/H3 or official-release parity'}
    server = http.server.ThreadingHTTPServer(('127.0.0.1',18861), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log = args.output.with_suffix('.runtime.log').open('w');os.fchmod(log.fileno(),0o600)
    process = None
    modes=[('protected', []), ('off', ['--metabrowser-privacy=off'])]
    native_version=None
    if args.identity_controls:
        native_version=subprocess.check_output(['/usr/bin/sw_vers','-productVersion'],text=True).strip()
        assert all(x.isdigit() for x in native_version.split('.'))
        report['native_platform_version']=native_version
        modes += [('identity_system',['--metabrowser-platform-version-policy=system']),('identity_invalid',['--metabrowser-platform-version-policy=invalid']),('native_control',['--metabrowser-privacy=off','--metabrowser-platform-version-policy=system'])]
    gpu_flags=[] if args.gpu=='native' else ['--use-gl=angle','--use-angle=swiftshader','--use-webgpu-adapter=swiftshader','--disable-accelerated-video-decode','--disable-accelerated-video-encode']
    report.update(gpu=args.gpu,identity_controls=args.identity_controls)
    try:
        for mode, flags in modes:
            process = subprocess.Popen([str(app/'Contents/MacOS/Chromium'), '--user-data-dir='+str(root/mode), '--remote-debugging-port=18860', '--use-mock-keychain', '--no-first-run', '--no-default-browser-check', '--disable-component-update', '--disable-background-networking', '--hide-crash-restore-bubble', *gpu_flags, *flags, 'about:blank'], env=env, stdout=log, stderr=log, start_new_session=True)
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                assert process.poll() is None, 'Fixture exited'
                try:
                    with urllib.request.urlopen('http://127.0.0.1:18860/json/version', timeout=.3) as response:json.load(response)
                    break
                except (OSError, ValueError):time.sleep(.15)
            else:raise TimeoutError('Owned CDP readiness timeout')
            try:
                result=subprocess.run(['node',str(HERE/'identity_surface_probe.mjs'),'18860','http://127.0.0.1:18861'],capture_output=True,text=True,timeout=100)
                if result.returncode:raise RuntimeError(result.stderr[-2500:])
                data=json.loads(result.stdout);report['modes'][mode]={'observations':data,**validate(data),'passive_policy':validate_passive(data,mode not in ('off','native_control'))}
                if args.identity_controls:
                    report['modes'][mode]['version_policy']=validate_version_policy(data,native_version,'system' if mode in ('identity_system','native_control') else 'major')
                write_private(args.output,report)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=20)
                    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5);raise RuntimeError('Owned fixture required force stop')
                process=None
        for name,h in sources.items():assert digest(BASE/name)==h,'Probe changed while collecting'
        report['completed']=True
        report['consistency_passed']=all(m['consistency_passed'] for m in report['modes'].values())
        report['passive_policy_passed']=all(m['passive_policy']['passed'] for m in report['modes'].values())
        report['version_policy_passed']=all(m.get('version_policy',{}).get('passed') is True for m in report['modes'].values()) if args.identity_controls else None
    except Exception as error:
        report['error']=str(error)
        raise
    finally:
        if process and process.poll() is None:process.terminate();process.wait(timeout=20)
        server.shutdown();server.server_close();log.close();write_private(args.output,report)
    print(json.dumps({'completed':True,'consistency_passed':report['consistency_passed'],'full_anonymity_passed':False,'modes':{k:{'checks':v['checks'],'findings':v['findings'],'passive_policy':v['passive_policy'],'version_policy':v.get('version_policy')} for k,v in report['modes'].items()}}))

    if args.identity_controls and report['version_policy_passed'] is not True:
        raise SystemExit(1)
    if args.require_passive_policy and not (report['consistency_passed'] and report['passive_policy_passed']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
