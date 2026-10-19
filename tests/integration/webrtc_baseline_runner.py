"""WebRTC ICE host-candidate exposure: official CfT vs MetaBrowser (privacy off / identity).

Each configuration gathers candidates on a fresh headless profile with no ICE servers,
once without media permission and once after getUserMedia on fake devices (the case
where official Chrome stops obfuscating host addresses with mDNS). Only candidate
type, protocol and address class are recorded; raw addresses never leave the page.
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

PAGE = r'''<!doctype html><script>
const classify = address => {
  if (address.endsWith('.local')) return 'mdns';
  if (address.includes(':')) {
    const a = address.toLowerCase();
    return a === '::1' ? 'ipv6-loopback' : a.startsWith('fe80') ? 'ipv6-linklocal'
      : /^f[cd]/.test(a) ? 'ipv6-ula' : 'ipv6-global';
  }
  const [x, y] = address.split('.').map(Number);
  return x === 127 ? 'ipv4-loopback' : x === 10 || (x === 172 && y >= 16 && y < 32) || (x === 192 && y === 168)
    ? 'ipv4-private' : x === 169 && y === 254 ? 'ipv4-linklocal' : x === 100 && y >= 64 && y < 128 ? 'ipv4-cgnat' : 'ipv4-public';
};
async function gather(withMedia) {
  if (withMedia) (await navigator.mediaDevices.getUserMedia({audio: true, video: true})).getTracks().forEach(t => t.stop());
  const pc = new RTCPeerConnection({iceServers: []}), found = [];
  pc.createDataChannel('probe');
  pc.onicecandidate = e => { if (e.candidate && e.candidate.candidate) found.push(e.candidate.candidate); };
  await pc.setLocalDescription(await pc.createOffer());
  await new Promise(done => {
    const finish = () => pc.iceGatheringState === 'complete' && done();
    pc.onicegatheringstatechange = finish; finish(); setTimeout(done, 6000);
  });
  pc.close();
  return found.map(line => {
    const p = line.split(' '), type = p[p.indexOf('typ') + 1], tcp = p.indexOf('tcptype');
    return {protocol: p[2].toLowerCase(), type, addressClass: classify(p[4]), tcptype: tcp > 0 ? p[tcp + 1] : null,
            relatedAddress: p.includes('raddr')};
  });
}
(async () => {
  const run = new URLSearchParams(location.search).get('run'), media = location.search.includes('media=1');
  let value;
  try { value = {candidates: await gather(media)}; } catch (e) { value = {error: String(e)}; }
  await fetch('/report?run=' + run, {method: 'POST', body: JSON.stringify(value)});
})();
</script>'''
COMMON = ['--headless=new', '--no-first-run', '--no-default-browser-check', '--disable-component-update',
          '--use-mock-keychain', '--accept-lang=en-US,en']
MEDIA = ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream']
IDENTITY = ['--metabrowser-persona-template=native-macos-arm64-v1', '--metabrowser-platform-version-policy=major',
            '--metabrowser-webrtc-policy=mdns_local_addresses']


class Fixture(http.server.ThreadingHTTPServer):
    def __init__(self):
        self.reports = {}
        super().__init__(('127.0.0.1', 0), Handler)
        self.origin = 'http://127.0.0.1:' + str(self.server_port)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if not self.path.startswith('/?run='):
            self.send_error(404)
            return
        body = PAGE.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        run = self.path.split('run=', 1)[1]
        self.server.reports[run] = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.send_response(204)
        self.end_headers()


def collect(fixture, executable, flags, media):
    run = str(uuid.uuid4())
    with tempfile.TemporaryDirectory(prefix='metabrowser-webrtc-baseline-') as profile:
        process = subprocess.Popen([str(executable), '--user-data-dir=' + profile, *flags,
                                    fixture.origin + '/?run=' + run + ('&media=1' if media else '')],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline and run not in fixture.reports:
            time.sleep(.2)
        process.terminate()
        try:
            process.wait(10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    return fixture.reports.get(run, {'error': 'no report'})


def summary(report):
    if 'candidates' not in report:
        return report
    shapes = sorted({json.dumps(c, sort_keys=True) for c in report['candidates']})
    return {'count': len(report['candidates']), 'shapes': [json.loads(s) for s in shapes],
            'classes': sorted({c['addressClass'] for c in report['candidates']}),
            'types': sorted({c['type'] for c in report['candidates']})}


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
    assert info['CFBundleIdentifier'] == 'com.google.chrome.for.testing'
    executables = {'official': official / 'Contents/MacOS' / info['CFBundleExecutable'],
                   'candidate': args.candidate.resolve(strict=True) / 'Contents/MacOS/Chromium'}
    configs = {'official': ('official', COMMON), 'candidate_off': ('candidate', COMMON + ['--metabrowser-privacy=off']),
               'candidate_identity': ('candidate', COMMON + IDENTITY)}
    fixture = Fixture()
    threading.Thread(target=fixture.serve_forever, daemon=True).start()
    results = {}
    try:
        for media in (False, True):
            condition = 'media_permission' if media else 'no_permission'
            for name, (build, flags) in configs.items():
                runs = [summary(collect(fixture, executables[build], flags + (MEDIA if media else []), media))
                        for _ in range(args.runs)]
                results.setdefault(condition, {})[name] = runs
                print(f'{condition:17} {name:20} ' + ' | '.join(
                    f"{r.get('count', 'ERR')} {','.join(r.get('classes', [r.get('error', '')]))}" for r in runs), flush=True)
    finally:
        fixture.shutdown()
    stable = {c: {n: all(json.dumps(r, sort_keys=True) == json.dumps(rs[0], sort_keys=True) for r in rs)
                  for n, rs in v.items()} for c, v in results.items()}
    matches = {c: {n: json.dumps(v[n][0].get('shapes'), sort_keys=True) == json.dumps(v['official'][0].get('shapes'), sort_keys=True)
                   for n in v} for c, v in results.items()}
    report = {'schema_version': 1, 'mode': 'headless=new', 'official_version': info['CFBundleShortVersionString'],
              'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'configs': {k: {'build': b, 'flags': f} for k, (b, f) in configs.items()},
              'results': results, 'stable_within_config': stable, 'shapes_match_official': matches,
              'raw_addresses_recorded': False, 'ice_servers': 'none (host candidates only)'}
    with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
        json.dump(report, stream, indent=1)
        stream.write('\n')
    print(json.dumps({'stable_within_config': stable, 'shapes_match_official': matches}))


if __name__ == '__main__':
    main()
