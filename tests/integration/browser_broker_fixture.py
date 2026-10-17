"""Loopback-only browser acceptance pages; no providers or user data.

Run directly to print the fixture URL, or use BrowserBrokerFixture as a context
manager. Two independently allocated ports provide genuinely distinct origins.
"""
import contextlib
import http.server
import json
import threading
import time
import urllib.parse


class BrowserBrokerFixture:
    def __init__(self):
        self.servers = []
        self.threads = []
        self.lock = threading.Lock()
        self.events = []
        self.geometry_reports = []
        self.command = {"revision": 0, "op": "idle", "delay_ms": 0}

    def __enter__(self):
        fixture = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                path = urllib.parse.urlsplit(self.path).path
                if path == '/control':
                    with fixture.lock:
                        body = json.dumps(fixture.command)
                    return self.send(body, 'application/json')
                if path == '/event':
                    query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                    with fixture.lock:
                        if 'geometry' in query:
                            report = json.loads(query['geometry'][0])
                            report['received_at'] = time.monotonic()
                            fixture.geometry_reports.append(report)
                            fixture.geometry_reports[:] = fixture.geometry_reports[-256:]
                        else:
                            fixture.events.append(query)
                    return self.send('{}', 'application/json')
                if path == '/frame':
                    origin = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get('origin', ['same'])[0]
                    return self.send('<!doctype html><title>Fixture frame</title><h2>' + origin +
                                     ' frame marker</h2><button onclick="this.textContent=\'Frame clicked\'">Frame action</button>')
                if path == '/next':
                    return self.send('<!doctype html><title>Fixture destination</title><h1>Navigation destination</h1><button>Destination action</button>')
                if path == '/covered-tail':
                    return self.send(fixture.covered_tail_page())
                if path == '/short':
                    return self.send(fixture.page(short=True))
                if path != '/':
                    self.send_error(404)
                    return
                self.send(fixture.page())

            def send(self, body, content_type='text/html; charset=utf-8'):
                data = body.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        for _ in range(2):
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            server.daemon_threads = True
            self.servers.append(server)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.threads.append(thread)
        self.url = 'http://127.0.0.1:%d/' % self.servers[0].server_port
        self.cross_url = 'http://127.0.0.1:%d/' % self.servers[1].server_port
        return self

    def __exit__(self, *_):
        for server in self.servers:
            server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join(timeout=2)

    def trigger(self, op, delay_ms=0):
        if op not in ('text', 'replace', 'navigate', 'child_navigate', 'reorder', 'overlay_on', 'overlay_off'):
            raise ValueError(op)
        with self.lock:
            self.command = {'revision': self.command['revision'] + 1,
                            'op': op, 'delay_ms': delay_ms}

    @staticmethod
    def covered_tail_page():
        # CSS distance, rather than hundreds of AX nodes, keeps LocalGoal's
        # complete observation small while guaranteeing an offscreen control.
        return """<!doctype html><html lang="en"><meta charset="utf-8">
<title>Covered offscreen activation fixture</title>
<h1>Covered tail fixture ready</h1><p id="result" role="status">No tail activation</p>
<div style="height:200vh" aria-hidden="true"></div>
<div style="position:relative;width:260px;height:48px;margin-bottom:32px">
<button style="width:100%;height:100%" onclick="document.querySelector('#result').textContent='Covered tail activated';fetch('/event?clicked=covered-tail')">Covered offscreen tail action</button>
<div role="button" aria-label="Permanent tail blocker" style="position:absolute;inset:0;z-index:10;background:white">Permanent overlay</div>
</div></html>"""

    def page(self, short=False):
        rows = ''.join('<li><button>Long row %04d</button></li>' % i for i in range(0 if short else 700))
        return '''<!doctype html><html lang="en"><meta charset="utf-8">
<title>Browser Broker isolated fixture</title>
<h1 id="section">Browser Broker fixture ready</h1>
<div id="reorder"><button>Order alpha</button><button>Order beta</button><button>Order gamma</button></div>
<div style="position:relative;width:220px;height:35px"><button id="guarded" onclick="record('guarded')">Guarded fixture action</button><div id="blocker" role="button" aria-label="Fixture blocker" style="display:none;position:absolute;inset:0;background:white;z-index:10">Blocker</div></div>
<section aria-label="Duplicate controls"><button onclick="record('first')">Duplicate action</button>
<button onclick="record('second')">Duplicate action</button></section>
<label>Fixture name<input id="name" aria-label="Fixture name"></label>
<button onclick="document.querySelector('#status').textContent='Applied '+document.querySelector('#name').value">Apply fixture</button>
<button disabled>Disabled action</button><button hidden>Hidden action</button>
<label>Fixture password<input type="password" value="fixture-password-do-not-expose"></label>
<p>fixture-plan globally already visible</p><button aria-label="UTF8_LABEL">Unicode action</button><p id="status" role="status">Waiting for update</p>
<section aria-label="Replacement scope" id="replacement"><button onclick="record('original')">Replaceable action</button></section>
<a href="/next">Fixture destination link</a>
<table aria-label="Fixture inventory"><thead><tr><th>Item</th><th>Count</th></tr></thead>
<tbody><tr><td>Apples</td><td>3</td></tr><tr><td>Pears</td><td>7</td></tr></tbody></table>
<iframe title="Same origin fixture" src="/frame?origin=same"></iframe>
<iframe title="Cross origin fixture" src="CROSS/frame?origin=cross"></iframe>
<section aria-label="Long fixture list"><ul>ROWS</ul><button onclick="record('tail')">Tail beyond 512</button></section>
<script>
function record(which) { fetch('/event?clicked='+which); document.querySelector('#status').textContent='Clicked '+which; }
let revision=REVISION, geometrySequence=0;
async function reportGeometry() {
 const rect=document.querySelector('#guarded').getBoundingClientRect();
 await fetch('/event?geometry='+encodeURIComponent(JSON.stringify({
  url:location.href,sequence:++geometrySequence,
  x:rect.x,y:rect.y,width:rect.width,height:rect.height,
  innerWidth,innerHeight,scrollX,scrollY,devicePixelRatio
 })));
}
async function poll() {
 try { await reportGeometry(); const c=await (await fetch('/control')).json();
 if(c.revision>revision) { revision=c.revision; setTimeout(()=>{
  if(c.op==='reorder') { const group=document.querySelector('#reorder'); group.insertBefore(group.lastElementChild,group.firstElementChild); }
  if(c.op==='overlay_on') { document.querySelector('#blocker').style.display='block'; document.querySelector('#status').textContent='Overlay enabled'; }
  if(c.op==='overlay_off') { document.querySelector('#blocker').style.display='none'; document.querySelector('#status').textContent='Overlay disabled'; }
  if(c.op==='text') document.querySelector('#status').textContent='Delayed fixture complete';
  if(c.op==='replace') document.querySelector('#replacement').innerHTML='<button onclick="record(\\'replacement\\')">Replaceable action</button>';
  if(c.op==='child_navigate') document.querySelector('iframe[title="Cross origin fixture"]').src='CROSS/next';
  if(c.op==='navigate') location.href='/next';
 },c.delay_ms); }
 } finally { setTimeout(poll,40); }
}
poll();
</script></html>'''.replace('REVISION', str(self.command['revision'])).replace('CROSS', self.cross_url.rstrip('/')).replace('ROWS', rows).replace('UTF8_LABEL', 'Short unicode control' if short else '多字节🙂' * 350)


if __name__ == '__main__':
    with BrowserBrokerFixture() as fixture:
        print(json.dumps({'url': fixture.url, 'cross_origin': fixture.cross_url}), flush=True)
        with contextlib.suppress(KeyboardInterrupt):
            threading.Event().wait()
