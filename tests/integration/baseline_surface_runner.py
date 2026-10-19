"""Same-version official baseline surface diff: official CfT vs MetaBrowser (privacy off / identity).

Each configuration runs headed on fresh profiles, twice, against one owned loopback origin.
Surfaces come from baseline_surface_probe.js in five realms plus raw request headers,
including high-entropy Client Hints requested with Accept-CH on a subresource (renderer)
and on a second navigation (browser). Differences are classified as
dynamic, version skew, intended privacy change, build/product residual, privacy masking a
build difference, or mixed. Classification is mechanical; residual review is separate.
"""
import argparse
import hashlib
import http.server
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
import threading
import time
import uuid

HERE = Path(__file__).resolve().parent
OFFICIAL_VERSION, ENGINE_VERSION = '154.0.8037.92', '154.0.8037.97'
LANGUAGE = '--accept-lang=en-US,en'
COMMON = ['--no-first-run', '--no-default-browser-check', '--disable-component-update', '--use-mock-keychain',
          '--hide-crash-restore-bubble', '--window-size=1200,900', LANGUAGE]
# Flags a native identity child receives from the parent (identity_profiles.cc), minus profile paths.
IDENTITY = ['--metabrowser-persona-template=native-macos-arm64-v1', '--metabrowser-platform-version-policy=major',
            '--metabrowser-webrtc-policy=mdns_local_addresses']
ACCEPT_CH = ('Sec-CH-UA-Arch, Sec-CH-UA-Bitness, Sec-CH-UA-Full-Version, Sec-CH-UA-Full-Version-List, Sec-CH-UA-Model, '
             'Sec-CH-UA-Platform-Version, Sec-CH-UA-WoW64, Sec-CH-UA-Form-Factors, Sec-CH-Device-Memory, Device-Memory, '
             'Sec-CH-DPR, DPR, Sec-CH-Viewport-Width, Viewport-Width, ECT, RTT, Downlink, Sec-CH-Prefers-Color-Scheme, '
             'Sec-CH-Prefers-Reduced-Motion')
PAGES = {
    '/frame.html': ('text/html', '<!doctype html><script src="/probe.js"></script><script>collectBaselineSurface().then('
                    'r=>parent.postMessage({result:r},location.origin),e=>parent.postMessage({error:String(e)},location.origin))</script>'),
    '/dedicated.js': ('text/javascript', 'importScripts("/probe.js");onmessage=()=>collectBaselineSurface().then('
                      'r=>postMessage({result:r}),e=>postMessage({error:String(e)}));'),
    '/shared.js': ('text/javascript', 'importScripts("/probe.js");onconnect=c=>{const p=c.ports[0];p.onmessage=()=>'
                   'collectBaselineSurface().then(r=>p.postMessage({result:r}),e=>p.postMessage({error:String(e)}));p.start()};'),
    '/service.js': ('text/javascript', 'importScripts("/probe.js");addEventListener("install",e=>e.waitUntil(skipWaiting()));'
                    'addEventListener("activate",e=>e.waitUntil(clients.claim()));addEventListener("message",e=>e.waitUntil('
                    'collectBaselineSurface().then(r=>e.ports[0].postMessage({result:r}),x=>e.ports[0].postMessage({error:String(x)}))));'),
    '/driver.js': ('text/javascript', r'''(async()=>{
const run=new URLSearchParams(location.search).get('run'),realms={},errors={};
const bounded=p=>Promise.race([p,new Promise((_,no)=>setTimeout(()=>no(Error('realm timeout')),40000))]);
const collect=async(name,fn)=>{try{realms[name]=await bounded(fn())}catch(e){errors[name]=String(e)}};
const reply=(ok,no)=>e=>e.data.error?no(Error(e.data.error)):ok(e.data.result);
await collect('window',()=>collectBaselineSurface());
await collect('iframe',()=>new Promise((ok,no)=>{const f=document.createElement('iframe');f.src='/frame.html';
 addEventListener('message',function m(e){if(e.source!==f.contentWindow)return;removeEventListener('message',m);f.remove();reply(ok,no)(e)});document.body.append(f)}));
await collect('dedicated',()=>new Promise((ok,no)=>{const w=new Worker('/dedicated.js');w.onmessage=e=>{w.terminate();reply(ok,no)(e)};
 w.onerror=e=>{w.terminate();no(Error(e.message))};w.postMessage(0)}));
await collect('shared',()=>new Promise((ok,no)=>{const w=new SharedWorker('/shared.js');w.port.onmessage=reply(ok,no);
 w.onerror=e=>no(Error(e.message));w.port.start();w.port.postMessage(0)}));
await collect('service',async()=>{const r=await navigator.serviceWorker.register('/service.js');await navigator.serviceWorker.ready;
 return new Promise((ok,no)=>{const c=new MessageChannel();c.port1.onmessage=reply(ok,no);r.active.postMessage(0,[c.port2])})});
await fetch('/echo?run='+run);
await fetch('/report?run='+run,{method:'POST',body:JSON.stringify({realms,errors})});
// A second navigation carries the browser-added (navigation) Client Hints.
location.replace('/nav?run='+run);})();'''),
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Fixture(http.server.ThreadingHTTPServer):
    def __init__(self):
        self.reports, self.headers = {}, {}
        super().__init__(('127.0.0.1', 0), Handler)
        self.origin = 'http://127.0.0.1:' + str(self.server_port)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, content_type, body, extra=()):
        body = body.encode() if isinstance(body, str) else body
        self.send_response(200)
        self.send_header('Content-Type', content_type + '; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        for name, value in extra:
            self.send_header(name, value)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def record(self, kind):
        run = self.path.split('run=', 1)[1] if 'run=' in self.path else None
        if run:
            # Order and values separately; run ids and the fixture port are not browser properties.
            items = [(k, v.replace(run, '<run>').replace(str(self.server.server_port), '<port>')) for k, v in self.headers.items()]
            self.server.headers.setdefault(run, {})[kind] = {'order': ', '.join(k for k, _ in items), 'values': dict(items)}

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/':
            self.record('document')
            self.reply('text/html', '<!doctype html><title>baseline</title><body><script src="/probe.js"></script>'
                       '<script src="/driver.js"></script></body>', [('Accept-CH', ACCEPT_CH)])
        elif path == '/probe.js':
            self.reply('text/javascript', (HERE / 'baseline_surface_probe.js').read_bytes())
        elif path == '/echo':
            self.record('subresource_after_accept_ch')
            self.reply('application/json', '{}')
        elif path == '/nav':
            self.record('navigation_after_accept_ch')
            self.reply('text/html', '<!doctype html><title>done</title>')
        elif path in PAGES:
            self.reply(*PAGES[path])
        else:
            self.send_error(404)

    def do_POST(self):
        run = self.path.split('run=', 1)[1]
        self.server.reports[run] = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.send_response(204)
        self.end_headers()


def observe(fixture, executable, flags, log):
    run = str(uuid.uuid4())
    with tempfile.TemporaryDirectory(prefix='metabrowser-baseline-surface-') as profile:
        started = time.monotonic()
        process = subprocess.Popen([str(executable), '--user-data-dir=' + profile, *flags, fixture.origin + '/?run=' + run],
                                   stdout=log, stderr=log, start_new_session=True)
        while (time.monotonic() - started < 120 and process.poll() is None and not (
                run in fixture.reports and 'navigation_after_accept_ch' in fixture.headers.get(run, {}))):
            time.sleep(.25)
        process.terminate()
        try:
            process.wait(20)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    report = fixture.reports.get(run)
    return {'run': run, 'flags': flags, 'seconds': round(time.monotonic() - started, 1), 'reported': report is not None,
            'realms': (report or {}).get('realms', {}), 'realm_errors': (report or {}).get('errors', {}),
            'headers': fixture.headers.get(run, {})}


def flatten(value, path, out):
    if isinstance(value, dict):
        for key in sorted(value):
            flatten(value[key], path + '.' + str(key), out)
    elif isinstance(value, list) and value and all(isinstance(item, str) for item in value) and not path.endswith('languages'):
        for item in value:  # Name inventories compare as sets; additions/removals become separate rows.
            out[path + '{' + item + '}'] = True
    elif isinstance(value, list):
        out[path + '#len'] = len(value)
        for index, item in enumerate(value):
            flatten(item, path + '[' + str(index) + ']', out)
    else:
        out[path] = value


def surfaces(observation):
    out = {}
    for realm, data in observation['realms'].items():
        flatten(data, realm, out)
    for realm, error in observation['realm_errors'].items():
        out[realm + '.realm_error'] = error
    for kind, headers in observation['headers'].items():
        flatten(headers, 'http.' + kind, out)
    return out


def normalize(value):
    return value.replace(ENGINE_VERSION, OFFICIAL_VERSION) if isinstance(value, str) else value


def classify(runs):
    flat = {name: [surfaces(o) for o in observations] for name, observations in runs.items()}
    paths = sorted(set().union(*(f for flats in flat.values() for f in flats)))
    missing = '<missing>'
    rows, counts = [], {}
    for path in paths:
        values = {name: [f.get(path, missing) for f in flats] for name, flats in flat.items()}
        if any(len({json.dumps(v) for v in vs}) > 1 for vs in values.values()):
            category = 'dynamic'
        else:
            o, f, p = (values[name][0] for name in ('official', 'candidate_off', 'candidate_identity'))
            if o == f == p:
                counts['identical'] = counts.get('identical', 0) + 1
                continue
            no, nf, np_ = normalize(o), normalize(f), normalize(p)
            if no == nf == np_:
                category = 'version_skew'
            elif no == nf:
                category = 'privacy_intended'
            elif nf == np_:
                category = 'build_residual'
            elif no == np_:
                category = 'privacy_masks_build_difference'
            else:
                category = 'mixed'
        counts[category] = counts.get(category, 0) + 1
        realm, _, rest = path.partition('.')
        rows.append({'category': category, 'surface': rest if realm in ('window', 'iframe', 'dedicated', 'shared', 'service') else path,
                     'realm': realm, 'values': {k: (v if len({json.dumps(x) for x in v}) > 1 else v[0]) for k, v in values.items()}})
    grouped = {}
    for row in rows:
        key = (row['category'], row['surface'], json.dumps(row['values'], sort_keys=True))
        grouped.setdefault(key, {**row, 'realms': []})['realms'].append(row['realm'])
    for entry in grouped.values():
        entry.pop('realm')
    return counts, sorted(grouped.values(), key=lambda r: (r['category'], r['surface']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--official', type=Path, required=True, help='Official Chrome for Testing .app')
    parser.add_argument('--candidate', type=Path, required=True, help='MetaBrowser .app')
    parser.add_argument('--output', type=Path, required=True, help='New private report; never overwritten')
    parser.add_argument('--runs', type=int, default=2)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Fresh output required')
    official = args.official.resolve(strict=True)
    info = plistlib.loads((official / 'Contents/Info.plist').read_bytes())
    assert info['CFBundleIdentifier'] == 'com.google.chrome.for.testing', 'Require the official testing variant'
    candidate = args.candidate.resolve(strict=True)
    executables = {'official': official / 'Contents/MacOS' / info['CFBundleExecutable'],
                   'candidate': candidate / 'Contents/MacOS/Chromium'}
    configs = {'official': ('official', COMMON), 'candidate_off': ('candidate', COMMON + ['--metabrowser-privacy=off']),
               'candidate_identity': ('candidate', COMMON + IDENTITY)}
    fixture = Fixture()
    threading.Thread(target=fixture.serve_forever, daemon=True).start()
    log = args.output.with_suffix('.runtime.log').open('w')
    os.fchmod(log.fileno(), 0o600)
    runs = {name: [] for name in configs}
    try:
        for index in range(args.runs):
            for name, (build, flags) in configs.items():
                observation = observe(fixture, executables[build], flags, log)
                runs[name].append(observation)
                print(f'{name:20} run {index + 1}: reported={observation["reported"]} realms={sorted(observation["realms"])} '
                      f'errors={list(observation["realm_errors"])} {observation["seconds"]}s', flush=True)
    finally:
        fixture.shutdown()
        log.close()
    complete = all(o['reported'] and len(o['realms']) == 5 and 'navigation_after_accept_ch' in o['headers']
                   for observations in runs.values() for o in observations)
    counts, rows = classify(runs) if complete else ({}, [])
    frameworks = {'official': next((official / 'Contents/Frameworks').glob('*.framework')),
                  'candidate': candidate / 'Contents/Frameworks/Chromium Framework.framework'}
    report = {'schema_version': 1, 'mode': 'headed', 'official_version': info['CFBundleShortVersionString'],
              'framework_sha256': {k: digest(v / v.stem) for k, v in frameworks.items()},
              'probe_sha256': {'runner': digest(__file__), 'probe': digest(HERE / 'baseline_surface_probe.js')},
              'configs': {k: {'build': b, 'flags': f} for k, (b, f) in configs.items()}, 'complete': complete,
              'counts': counts, 'differences': rows, 'runs': runs, 'paid_model_calls': 0,
              'exact_release_parity_proven': False}
    with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=1)
        stream.write('\n')
    print(json.dumps({'complete': complete, 'counts': counts}))
    return 0 if complete else 1


if __name__ == '__main__':
    raise SystemExit(main())
