"""Loopback-only native timezone probe; no browser launch or model invocation.

Collects Date/Intl/languages in window, iframe, dedicated/module/nested/shared/
service workers. Only a fixture Canvas digest is collected, never user data.
"""
import argparse
import http.server
import json
import pathlib
import uuid

SNAPSHOT = """async function snapshot(){const high=await navigator.userAgentData.getHighEntropyValues(['platformVersion','architecture','bitness']);return {platformVersion:high.platformVersion,uaPlatform:high.platform,architecture:high.architecture,bitness:high.bitness,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,
winter:new Date('2026-01-15T12:00:00Z').getTimezoneOffset(),
summer:new Date('2026-07-15T12:00:00Z').getTimezoneOffset(),languages:[...navigator.languages],
screen:typeof screen==='undefined'?null:{width:screen.width,height:screen.height},hardwareConcurrency:navigator.hardwareConcurrency}}"""
PAGE = """<!doctype html><meta charset=utf-8><title>Local identity timezone probe</title>
<pre id=result>Collecting native timezone evidence…</pre><script>
SNAPSHOT
const limited=(promise)=>Promise.race([promise,new Promise((_,reject)=>setTimeout(()=>reject(Error('timeout')),12000))]);
function worker(url,options){return limited(new Promise((resolve,reject)=>{const w=new Worker(url,options);w.onmessage=e=>{w.terminate();resolve(e.data)};w.onerror=e=>{w.terminate();reject(Error(e.message))};w.postMessage('snapshot')}))}
async function run(){
 const result={window:await snapshot()};
 result.iframe=await limited(new Promise(resolve=>{const f=document.createElement('iframe');window.addEventListener('message',function receive(e){if(e.source!==f.contentWindow)return;window.removeEventListener('message',receive);f.remove();resolve(e.data)});f.srcdoc='<script>'+snapshot.toString()+';snapshot().then(value=>parent.postMessage(value,"*"))<'+ '/script>';document.body.append(f)}));
 result.dedicated=await worker('/dedicated.js');result.module=await worker('/dedicated.js',{type:'module'});result.nested=await worker('/nested.js');
 result.shared=await limited(new Promise((resolve,reject)=>{const w=new SharedWorker('/shared.js');w.onerror=e=>reject(Error(e.message));w.port.onmessage=e=>{resolve(e.data);w.port.postMessage('close');w.port.close()};w.port.start();w.port.postMessage('snapshot')}));
 const registration=await navigator.serviceWorker.register('/service.js',{scope:'/identity-timezone-scope/'});
 try {const active=registration.active||registration.waiting||registration.installing;if(active.state!=='activated')await limited(new Promise(resolve=>active.addEventListener('statechange',()=>{if(active.state==='activated')resolve()})));result.service=await limited(new Promise(resolve=>{const channel=new MessageChannel();channel.port1.onmessage=e=>{channel.port1.close();resolve(e.data)};registration.active.postMessage('snapshot',[channel.port2])}))}
 finally{await registration.unregister()}
 const canvas=document.createElement('canvas');canvas.width=240;canvas.height=60;const ctx=canvas.getContext('2d');ctx.fillStyle='#f3ecfb';ctx.fillRect(0,0,240,60);ctx.font='19px sans-serif';ctx.fillStyle='#8a4ed1';ctx.fillText('Identity isolation · 0123456789',3,35);const bytes=ctx.getImageData(0,0,240,60).data;result.canvas=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(x=>x.toString(16).padStart(2,'0')).join('');return result;
}
run().then(report=>submit({report})).catch(error=>submit({error:String(error)}));
async function submit(value){value.run=new URL(location.href).searchParams.get('run');document.querySelector('#result').textContent=JSON.stringify(value,null,2);await fetch('/report',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)})}
</script>""".replace('SNAPSHOT', SNAPSHOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=18832)
    parser.add_argument('--output', required=True, type=pathlib.Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = self.path.split('?', 1)[0]
            payload, mime = PAGE, 'text/html; charset=utf-8'
            if path == '/dedicated.js':
                payload, mime = SNAPSHOT + ';onmessage=async()=>postMessage(await snapshot())', 'text/javascript'
            elif path == '/nested.js':
                payload, mime = SNAPSHOT + ";onmessage=()=>{const w=new Worker('/dedicated.js');w.onmessage=e=>{postMessage(e.data);w.terminate()};w.postMessage('snapshot')}", 'text/javascript'
            elif path == '/shared.js':
                payload, mime = SNAPSHOT + ";onconnect=e=>{const p=e.ports[0];p.onmessage=async e=>{if(e.data==='close'){p.close();close()}else p.postMessage(await snapshot())};p.start()}", 'text/javascript'
            elif path == '/service.js':
                payload, mime = SNAPSHOT + ';oninstall=()=>skipWaiting();onmessage=e=>e.waitUntil(snapshot().then(value=>e.ports[0].postMessage(value)))', 'text/javascript'
            data = payload.encode()
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Accept-CH', 'Sec-CH-UA-Platform-Version, Sec-CH-UA-Arch, Sec-CH-UA-Bitness')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if self.path != '/report' or not 0 < size <= 16384:
                    raise ValueError('bounded report required')
                value = json.loads(self.rfile.read(size))
                run = str(uuid.UUID(value['run']))
                value['accept_language'] = self.headers.get('Accept-Language', '')
                value['sec_ch_platform_version'] = self.headers.get('Sec-CH-UA-Platform-Version', '')
                target = args.output / (run + '.json')
                target.write_text(json.dumps(value, indent=2))
                target.chmod(0o600)
                self.send_response(204)
                self.end_headers()
            except (ValueError, KeyError, TypeError):
                self.send_error(400)

    server = http.server.ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(json.dumps({'port': server.server_port, 'output': str(args.output.resolve())}), flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
