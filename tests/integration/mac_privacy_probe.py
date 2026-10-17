"""Loopback-only macOS surface probe and synthetic STUN fixture.

No account data, browser launch, provider calls, permission grants or external
network. Accepts a caller-owned canary TTF and saves bounded reports at 0600.
STUN always advertises TEST-NET-3, never records the source endpoint/address.
"""
import argparse
import http.server
import json
import os
from pathlib import Path
import socket
import struct
import tempfile
import threading
import urllib.parse
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--font', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18842)
    parser.add_argument('--stun-port', type=int, default=18844)
    args = parser.parse_args()
    font = args.font.read_bytes()
    if not 1024 <= len(font) <= 1024 * 1024:
        parser.error('Require a small test font')
    args.output.mkdir(parents=True, exist_ok=True)
    page = (Path(__file__).resolve().parents[1] / 'fixtures/mac_privacy_probe.html').read_bytes()
    webgl = page.decode().split('// WEBGL_PROBE_BEGIN\n', 1)[1].split('// WEBGL_PROBE_END', 1)[0]
    count = [0]
    lock = threading.Lock()
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(('127.0.0.1', args.stun_port))

    def stun():
        while True:
            try:
                packet, address = udp.recvfrom(1024)
            except OSError:
                return
            if len(packet) < 20 or packet[:2] != b'\x00\x01' or packet[4:8] != b'\x21\x12\xa4\x42':
                continue
            with lock:
                count[0] += 1
            ip = int.from_bytes(socket.inet_aton('203.0.113.7'), 'big') ^ 0x2112a442
            attr = struct.pack('!HHBBHI', 0x0020, 8, 0, 1, 3478 ^ 0x2112, ip)
            response = struct.pack('!HH', 0x0101, len(attr)) + packet[4:20] + attr
            udp.sendto(response, address)

    threading.Thread(target=stun, daemon=True).start()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            url = urllib.parse.urlsplit(self.path)
            kind = url.path
            payload, mime = page, 'text/html; charset=utf-8'
            scripts = {
                '/worker.js': "onmessage=()=>postMessage(navigator.hardwareConcurrency)",
                '/nested.js': "onmessage=()=>{const w=new Worker('/worker.js');w.onmessage=e=>{postMessage(e.data);w.terminate()};w.postMessage('run')}",
                '/shared.js': "onconnect=e=>{const p=e.ports[0];p.onmessage=e=>{if(e.data==='close'){p.close();close()}else p.postMessage(navigator.hardwareConcurrency)};p.start()}",
                '/service.js': "oninstall=()=>skipWaiting();onmessage=e=>e.ports[0].postMessage(navigator.hardwareConcurrency)",
                '/audio-worklet.js': "registerProcessor('privacy-probe',class extends AudioWorkletProcessor{constructor(){super();this.port.postMessage({ok:true})}process(){return false}})",
                '/font-worker.js': "(async()=>{const family=new URL(location.href).searchParams.get('font');const local=new FontFace('LocalCanary',`local(\"${family}\")`);let localLoaded=false;try{await local.load();self.fonts.add(local);localLoaded=true}catch{};const remote=new FontFace('RemoteCanary','url(/font.ttf)');await remote.load();self.fonts.add(remote);const x=new OffscreenCanvas(64,32).getContext('2d');x.font='20px RemoteCanary';const remoteWidth=x.measureText('iiiiWWWW0123456789').width;x.font=`20px \"${family}\", monospace`;const directWidth=x.measureText('iiiiWWWW0123456789').width;x.font='20px monospace';const genericWidth=x.measureText('iiiiWWWW0123456789').width;x.font='20px serif';postMessage({localLoaded,remoteLoaded:remote.status==='loaded',remoteWidth,directWidth,genericWidth,privateGlyphFallbackWidth:x.measureText('\\ue9f1').width})})().catch(e=>postMessage({error:String(e)}))",
                '/webgl-worker.js': webgl + "onmessage=()=>webglProbe(true).then(r=>postMessage(r),e=>postMessage({error:String(e)}))",
                '/webgl-shared.js': webgl + "onconnect=e=>{const p=e.ports[0];p.onmessage=()=>webglProbe(true).then(r=>{p.postMessage(r);p.close();close()},e=>{p.postMessage({error:String(e)});p.close();close()});p.start()}",
                '/webgl-service.js': webgl + "oninstall=()=>skipWaiting();onmessage=e=>e.waitUntil(webglProbe(true).then(r=>e.ports[0].postMessage(r),error=>e.ports[0].postMessage({error:String(error)})))",
            }
            if kind in scripts:
                payload, mime = scripts[kind].encode(), 'text/javascript'
            elif kind == '/font.ttf':
                payload, mime = font, 'font/ttf'
            elif kind == '/display-only':
                payload = b'<!doctype html><meta charset=utf-8><title>Local display permission fixture</title><body>Display permission fixture</body>'
            elif kind == '/stun-count':
                with lock:
                    payload = json.dumps({'count': count[0]}).encode()
                mime = 'application/json'
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
            self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
            self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            tmp = None
            try:
                url = urllib.parse.urlsplit(self.path)
                length = int(self.headers.get('Content-Length', '0'))
                if url.path != '/report' or not 0 < length <= 65536:
                    raise ValueError('bounded report required')
                run = str(uuid.UUID(urllib.parse.parse_qs(url.query)['run'][0]))
                value = json.loads(self.rfile.read(length))
                data = json.dumps(value, indent=2).encode()
                with tempfile.NamedTemporaryFile(dir=args.output, delete=False) as stream:
                    tmp = Path(stream.name)
                    stream.write(data)
                # Atomic, immutable run IDs: restored tabs cannot replace evidence.
                os.link(tmp, args.output / (run + '.json'))
                self.send_response(204)
                self.end_headers()
            except FileExistsError:
                self.send_error(409, 'Run already collected')
            except (ValueError, KeyError, TypeError):
                self.send_error(400)
            finally:
                if tmp is not None:
                    tmp.unlink(missing_ok=True)

    server = http.server.ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(json.dumps({'http_port': args.port, 'stun_port': args.stun_port}), flush=True)
    try:
        server.serve_forever()
    finally:
        udp.close()
        server.server_close()


if __name__ == '__main__':
    main()
