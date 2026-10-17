"""Native iframe, dedicated/module/nested/shared/service worker fixtures."""
import http.server
import json
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

HERE=Path(__file__).resolve().parent


class Handler(http.server.BaseHTTPRequestHandler):
    requests=[]

    def log_message(self,*args):pass

    def do_GET(self):
        self.requests.append(self.path)
        path=urlsplit(self.path).path
        trial=(HERE/'opfs_seven_trial.js').read_text()
        operation='ownedOpfsTrial(e.data.realm,e.data.kind,e.data.scenario)'
        reply=f'{operation}.then(result=>port.postMessage({{result}}),error=>port.postMessage({{error:String(error)}}))'
        mime='text/javascript'
        if path=='/opfs-trial.js':body=trial
        elif path=='/opfs-worker.js':
            body="importScripts('/opfs-trial.js');onmessage=e=>{const port=self;"+reply+'};'
        elif path=='/opfs-module.js':
            body=trial+'\nself.ownedModuleUrl=import.meta.url;onmessage=e=>{const port=self;'+reply+'};'
        elif path=='/opfs-nested.js':
            body="""onmessage=event=>{const child=new Worker('/opfs-worker.js');
            child.onmessage=e=>{if(e.data.result){e.data.result.nestedParentLocation=location.href;e.data.result.nestedParentGlobal=globalThis.constructor.name}postMessage(e.data);child.terminate()};
            child.onerror=e=>{postMessage({error:e.message});child.terminate()};child.postMessage(event.data)};"""
        elif path=='/opfs-shared.js':
            body="importScripts('/opfs-trial.js');onconnect=e=>{const port=e.ports[0];port.onmessage=e=>{"+reply+'};port.start()};'
        elif path=='/opfs-service.js':
            body="importScripts('/opfs-trial.js');oninstall=e=>e.waitUntil(skipWaiting());onactivate=e=>e.waitUntil(clients.claim());onmessage=e=>{const port=e.ports[0];e.waitUntil("+reply+')};'
        elif path in ('/','/opfs-frame.html'):
            mime='text/html';body='<!doctype html><title>Owned seven-realm OPFS</title><script src="/opfs-trial.js"></script>'
            if path=='/opfs-frame.html':
                params=parse_qs(urlsplit(self.path).query)
                args=[params[k][0] for k in ('realm','kind','scenario')]
                assert args[0]=='iframe'
                body+='<script>ownedOpfsTrial('+','.join(json.dumps(v) for v in args)+').then(result=>parent.postMessage({result},location.origin),error=>parent.postMessage({error:String(error)},location.origin));</script>'
        else:
            self.send_error(404);return
        data=body.encode();self.send_response(200)
        self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
