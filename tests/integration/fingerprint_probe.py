"""Loopback P4–P13 native evidence collector, standard library only.

  python3 tests/integration/fingerprint_probe.py serve --output /tmp/fp-evidence
  # Open a printed URL manually in each browser/profile; optionally append &ice=1.
  python3 tests/integration/fingerprint_probe.py diff baseline.json candidate.json

Two IPv4 listeners expose localhost and 127.0.0.1 at two ephemeral ports, giving
four origins. GET /reports lists reports; GET /reports/ID returns JSON. POST
/report accepts bounded probe objects only. No browser/CDP/model is invoked.
For cached ServiceWorker evidence: use fixed --port/--secondary-port and
?persist_sw=1, collect once, close browser, restart this server on those ports
with --deny-service-worker-script, then reopen the SAME browser profile/URL.
Require serviceWorker.reusedRegistration=true and canvas parity; source checks
alone are insufficient. Persistent mode preserves only its exact fixture scope.
No cookies, authorization, storage values, media devices or account data are
collected. Optional local ICE candidates can contain native network addresses.
The report is diagnostic evidence, never an anonymization/security verdict.
P1–P3 TLS/HTTP2 capture and P14 site instrumentation are outside this harness.
"""
import argparse
import copy
import http.server
import ipaddress
import json
import pathlib
import re
import secrets
import tempfile
import threading
import urllib.parse
import uuid

PAGE = pathlib.Path(__file__).resolve().parents[1] / 'fixtures/fingerprint_probe.html'
MAX_BYTES = 1024 * 1024
MAX_REPORTS = 64
MAX_DIFFS = 4096


def worker_bundle(kind='dedicated'):
    """Serve the exact canonical helpers serialized by blob workers as well."""
    page = PAGE.read_text()
    functions = []
    entry = {'dedicated': 'workerMain', 'shared': 'sharedWorkerMain', 'service': 'serviceWorkerMain'}[kind]
    for name in ('hash', 'navigatorSnapshot', 'canonicalDraw', 'canvasReadback', entry):
        pattern = r'/\* worker-shared:' + name + r':start \*/(.*?)/\* worker-shared:' + name + r':end \*/'
        match = re.search(pattern, page, flags=re.S)
        if not match:
            raise ValueError('Missing shared worker helper: ' + name)
        functions.append(match.group(1))
    return ('\n'.join(functions) + '\n' + entry + '();\n').encode()


def differences(before, after, path='', output=None):
    """JSON pointer paths, explicit additions/removals and bounded full values."""
    if output is None:
        output = []
    if len(output) >= MAX_DIFFS:
        return output
    if type(before) is not type(after):
        output.append({'path': path or '/', 'kind': 'type', 'before': before, 'after': after})
    elif isinstance(before, dict):
        for key in sorted(before.keys() | after.keys()):
            child = path + '/' + key.replace('~', '~0').replace('/', '~1')
            if len(output) >= MAX_DIFFS:
                break
            if key not in before:
                output.append({'path': child, 'kind': 'added', 'after': after[key]})
            elif key not in after:
                output.append({'path': child, 'kind': 'removed', 'before': before[key]})
            else:
                differences(before[key], after[key], child, output)
    elif isinstance(before, list):
        for index in range(max(len(before), len(after))):
            if len(output) >= MAX_DIFFS:
                break
            child = path + '/' + str(index)
            if index >= len(before):
                output.append({'path': child, 'kind': 'added', 'after': after[index]})
            elif index >= len(after):
                output.append({'path': child, 'kind': 'removed', 'before': before[index]})
            else:
                differences(before[index], after[index], child, output)
    elif before != after:
        output.append({'path': path or '/', 'kind': 'changed', 'before': before, 'after': after})
    return output


def load_report(path):
    if pathlib.Path(path).stat().st_size > MAX_BYTES:
        raise ValueError('Report exceeds 1 MiB')
    with open(path, encoding='utf-8') as stream:
        value = json.load(stream)
    if isinstance(value, dict) and 'report' in value:
        value = value['report']
    if not isinstance(value, dict):
        raise ValueError('Expected JSON report object')
    return value


def compare_reports(before, after, ignore=()):
    left, right = copy.deepcopy(before), copy.deepcopy(after)
    # These envelope fields identify a collection, not browser API behavior.
    # Explicitly disclose them; no origin, API error, timing or stack difference
    # is silently normalized away.
    omitted = ['/run']
    for report in (left, right):
        report.pop('run', None)
        for pointer in ignore:
            parts = pointer.lstrip('/').split('/')
            node = report
            for key in parts[:-1]:
                key = key.replace('~1', '/').replace('~0', '~')
                node = node.get(key, {}) if isinstance(node, dict) else {}
            if isinstance(node, dict):
                node.pop(parts[-1].replace('~1', '/').replace('~0', '~'), None)
    changes = differences(left, right)
    return {'purpose': 'native evidence diff; equality is not an anonymity verdict',
            'omittedEnvelopePaths': omitted, 'explicitlyIgnoredPaths': list(ignore),
            'differenceCount': len(changes), 'possiblyTruncated': len(changes) >= MAX_DIFFS,
            'differences': changes}


class ProbeServer:
    def __init__(self, output, ports=(0, 0), deny_service_worker_script=False):
        self.ports = ports
        self.deny_service_worker_script = deny_service_worker_script
        self.service_worker_script_requests = 0
        self.output = pathlib.Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.servers, self.threads = [], []
        self.lock = threading.Lock()
        self.ids = []
        # Unpredictable per-run route token prevents unrelated local web pages
        # from posting into the collector, independent of CORS.
        self.token = secrets.token_urlsafe(24)

    def __enter__(self):
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.0'

            def log_message(self, *_):
                pass

            def allowed(self):
                try:
                    host = urllib.parse.urlsplit('http://' + self.headers.get('Host', ''))
                    return (ipaddress.ip_address(self.client_address[0]).is_loopback
                            and host.hostname in ('localhost', '127.0.0.1')
                            and host.port == self.server.server_port)
                except ValueError:
                    return False

            def send(self, value, status=200, html=False, javascript=False):
                data = value if html or javascript else json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'text/javascript; charset=utf-8' if javascript else 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Referrer-Policy', 'no-referrer')
                if html:
                    origins = ' '.join(owner.origins)
                    self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; worker-src 'self' blob:; frame-src 'self' about: " + origins + '; img-src data:')
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if not self.allowed():
                    return self.send({'error': 'Loopback host required'}, 403)
                parsed = urllib.parse.urlsplit(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                if parsed.path == '/':
                    # Only the report upload URL carries this token, never API
                    # observations or the JSON displayed by the page.
                    page = PAGE.read_text().replace("fetch('/report',", "fetch('/report?token=" + owner.token + "',")
                    return self.send(page.encode(), html=True)
                if parsed.path == '/privacy-worker-shared.js':
                    return self.send(worker_bundle('shared'), javascript=True)
                if parsed.path == '/privacy-worker-service.js':
                    with owner.lock:
                        owner.service_worker_script_requests += 1
                    if owner.deny_service_worker_script:
                        return self.send({'error': 'Fixture service-worker script intentionally unavailable for cached-startup validation'}, 503)
                    return self.send(worker_bundle('service'), javascript=True)
                if parsed.path == '/worker.js':
                    return self.send(worker_bundle(), javascript=True)
                if parsed.path == '/config':
                    return self.send({'origins': owner.origins, 'denyServiceWorkerScript': owner.deny_service_worker_script, 'serviceWorkerScriptRequests': owner.service_worker_script_requests})
                if parsed.path == '/reports':
                    with owner.lock:
                        return self.send({'reports': list(owner.ids), 'limit': MAX_REPORTS})
                if parsed.path.startswith('/reports/'):
                    ident = parsed.path.removeprefix('/reports/')
                    with owner.lock:
                        if ident not in owner.ids:
                            return self.send({'error': 'Unknown report'}, 404)
                        return self.send(json.loads((owner.output / (ident + '.json')).read_text()))
                return self.send({'error': 'Unknown route'}, 404)

            def do_POST(self):
                parsed = urllib.parse.urlsplit(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                expected_origin = 'http://' + self.headers.get('Host', '')
                if (not self.allowed() or self.headers.get('Origin') not in (None, expected_origin)
                        or parsed.path != '/report' or query.get('token') != [owner.token]):
                    return self.send({'error': 'Loopback same-origin probe upload required'}, 403)
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= MAX_BYTES:
                        return self.send({'error': 'Report must be 1 byte to 1 MiB'}, 413)
                    if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                        return self.send({'error': 'JSON required'}, 415)
                    report = json.loads(self.rfile.read(length), parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Non-finite JSON')))
                    if (not isinstance(report, dict) or report.get('schema') != 1
                            or not isinstance(report.get('probes'), dict)
                            or not isinstance(report.get('run'), str)):
                        return self.send({'error': 'Probe schema 1 required'}, 400)
                    if len(report['run']) > 128 or report.get('origin') != expected_origin:
                        return self.send({'error': 'Invalid run or report origin'}, 400)
                    report['collector'] = {'requestHeaders': {k.lower(): v for k, v in self.headers.items()
                        if k.lower() in ('user-agent', 'accept-language', 'sec-ch-ua', 'sec-ch-ua-platform', 'sec-ch-ua-mobile')},
                        'excluded': ['cookies', 'authorization', 'storage contents'], 'maxReports': MAX_REPORTS}
                    encoded = json.dumps(report, ensure_ascii=False, allow_nan=False).encode()
                    if len(encoded) > MAX_BYTES:
                        return self.send({'error': 'Stored report exceeds 1 MiB'}, 413)
                    ident = uuid.uuid4().hex
                    with owner.lock:
                        path = owner.output / (ident + '.json')
                        with path.open('xb') as stream:
                            path.chmod(0o600)
                            stream.write(encoded)
                        owner.ids.append(ident)
                        while len(owner.ids) > MAX_REPORTS:
                            (owner.output / (owner.ids.pop(0) + '.json')).unlink()
                    return self.send({'id': ident, 'path': '/reports/' + ident}, 201)
                except (ValueError, UnicodeDecodeError, RecursionError):
                    return self.send({'error': 'Invalid bounded JSON'}, 400)

        try:
            for port in self.ports:
                server = http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler)
                server.daemon_threads = True
                self.servers.append(server)
            self.origins = ['http://%s:%d' % (host, server.server_port)
                            for server in self.servers for host in ('127.0.0.1', 'localhost')]
            for server in self.servers:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                self.threads.append(thread)
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        for server, thread in zip(self.servers, self.threads):
            server.shutdown()
            thread.join(timeout=2)
        for server in self.servers:
            server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    serve = sub.add_parser('serve', help='serve local probe; never launches browser')
    serve.add_argument('--port', type=int, default=0, help='first IPv4 port; fixed ports support same-origin restart comparisons')
    serve.add_argument('--deny-service-worker-script', action='store_true', help='503 only the fixture ServiceWorker script; validate cached startup after browser restart with same profile, origin and ?persist_sw=1')
    serve.add_argument('--secondary-port', type=int, default=0, help='second IPv4 port')
    serve.add_argument('--output', help='report directory (default: new private temporary directory)')
    diff = sub.add_parser('diff', help='compare two stored JSON reports')
    diff.add_argument('baseline')
    diff.add_argument('candidate')
    diff.add_argument('--ignore', action='append', default=[], metavar='/JSON/POINTER', help='explicit object field exclusion, recorded in output')
    diff.add_argument('--output', help='write JSON diff to this file instead of stdout')
    args = parser.parse_args()
    if args.command == 'diff':
        result = compare_reports(load_report(args.baseline), load_report(args.candidate), args.ignore)
        data = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
        if args.output:
            pathlib.Path(args.output).write_text(data)
        else:
            print(data, end='')
        return
    directory = args.output or tempfile.mkdtemp(prefix='metabrowser-fingerprint-evidence-')
    with ProbeServer(directory, (args.port, args.secondary_port), args.deny_service_worker_script) as server:
        print(json.dumps({'origins': server.origins, 'urls': [o + '/?run=' + uuid.uuid4().hex for o in server.origins],
                          'output': str(server.output), 'reports': server.origins[0] + '/reports',
                          'note': 'Open manually; optional &ice=1 uses no STUN/TURN. No anonymization verdict.'}), flush=True)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
