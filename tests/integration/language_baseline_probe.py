"""HTTP Accept-Language and JS navigator.languages against a same-version official Chrome.

Both builds run headless on fresh temporary profiles with identical flags and load one
owned loopback page; no model, account or external network is involved. Every case must
report, and the candidate must equal the official build case by case.
"""
import argparse
import hashlib
import http.server
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import uuid

HERE = Path(__file__).resolve().parent
CASES = (('en-US,en', ()), ('zh-CN,zh', ()), ('ja-JP,ja,en-US,en', ()),
         ('en-US,en', ('--metabrowser-persona-template=native-macos-arm64-v1',)))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Fixture(http.server.ThreadingHTTPServer):
    def __init__(self):
        self.results = {}
        super().__init__(('127.0.0.1', 0), Handler)
        self.origin = 'http://127.0.0.1:' + str(self.server_port)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def run_id(self):
        return str(uuid.UUID(self.path.split('run=', 1)[1]))

    def do_GET(self):
        if 'run=' not in self.path:  # favicon and other incidental requests
            self.send_error(404)
            return
        run = self.run_id()
        self.server.results.setdefault(run, {})['http_accept_language'] = self.headers.get('Accept-Language')
        body = ('<!doctype html><script>fetch("/report?run=' + run + '",{method:"POST",body:JSON.stringify('
                '{language:navigator.language,languages:[...navigator.languages]})});</script>').encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        run = self.run_id()
        self.server.results.setdefault(run, {}).update(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
        self.send_response(204)
        self.end_headers()


def collect(fixture, executable, accept, extra):
    run = str(uuid.uuid4())
    with tempfile.TemporaryDirectory(prefix='metabrowser-language-baseline-') as profile:
        process = subprocess.Popen([str(executable), '--headless=new', '--user-data-dir=' + profile, '--no-first-run',
                                    '--no-default-browser-check', '--disable-background-networking',
                                    '--disable-component-update', '--use-mock-keychain', '--accept-lang=' + accept,
                                    *extra, fixture.origin + '/?run=' + run],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and 'languages' not in fixture.results.get(run, {}):
            time.sleep(.2)
        process.terminate()
        try:
            process.wait(10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    return fixture.results.get(run, {})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--official', type=Path, required=True, help='Official Chrome for Testing executable')
    parser.add_argument('--candidate', type=Path, required=True, help='MetaBrowser Chromium executable')
    parser.add_argument('--output', type=Path, required=True, help='New private report; never overwritten')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Fresh output required')
    fixture = Fixture()
    threading.Thread(target=fixture.serve_forever, daemon=True).start()
    builds = {'official': args.official.resolve(strict=True), 'candidate': args.candidate.resolve(strict=True)}
    rows = []
    for accept, extra in CASES:
        row = {'accept_lang': accept, 'extra_flags': list(extra)}
        for name, executable in builds.items():
            # Product-only switches are meaningless to official Chrome; compare against its plain run.
            flags = extra if name == 'candidate' else ()
            row[name] = collect(fixture, executable, accept, flags)
        rows.append(row)
    fixture.shutdown()
    complete = all('languages' in row[name] and row[name].get('http_accept_language')
                   for row in rows for name in builds)
    equal = complete and all(row['official'] == row['candidate'] for row in rows)
    versions = {name: subprocess.check_output([str(path), '--version'], text=True).strip() for name, path in builds.items()}
    report = {'schema_version': 1, 'mode': 'headless=new', 'versions': versions,
              'executables_sha256': {name: digest(path) for name, path in builds.items()},
              'probe_sha256': digest(__file__), 'cases': rows,
              'all_cases_reported': complete, 'candidate_equals_official': equal}
    with os.fdopen(os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'all_cases_reported': complete, 'candidate_equals_official': equal, 'versions': versions}))
    return 0 if equal else 1


if __name__ == '__main__':
    raise SystemExit(main())
