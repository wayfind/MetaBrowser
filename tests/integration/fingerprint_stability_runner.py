"""Real headed cold starts of one owned profile; no user data or paid calls."""
import argparse
import hashlib
import http.server
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request

from identity_surface_runner import Handler, digest, validate, validate_passive, write_private

HERE=Path(__file__).resolve().parent
BASE=HERE.parents[1]


def signature(data):
    if set(data.get('realms',{}))!={'window','iframe','dedicated','shared','service'}:
        raise ValueError('Five complete realms required')
    fields=['userAgent','appVersion','platform','vendor','product','productSub','language','languages','hardwareConcurrency','deviceMemory','maxTouchPoints','webdriver','pdfViewerEnabled','uaData','api','globals','time','math','nativeBindings']
    stable={name:{key:realm[key] for key in fields} for name,realm in data['realms'].items()}
    window=data['realms']['window']
    for key in ['plugins','mimeTypes','display','mediaQueries','rendering']:
        stable['window'][key]=window[key]
    rendering=window['rendering']
    if set(rendering.get('webgl',{}))!={'webgl','webgl2'} or not all(v['noError'] is True for v in rendering['webgl'].values()):
        raise ValueError('Missing or invalid real WebGL coverage')
    for value in [rendering.get('canvas'),rendering.get('audio',{}).get('hash'),*(v['hash'] for v in rendering['webgl'].values())]:
        if not isinstance(value,str) or len(value)!=64 or any(c not in '0123456789abcdef' for c in value):raise ValueError('Missing rendering hash')
    # Connection/storage estimates, event timestamps and window positions are
    # recorded in raw evidence, but intentionally excluded from stable identity.
    return hashlib.sha256(json.dumps(stable,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--count',type=int,default=100)
    p.add_argument('--ui-helper',type=Path,required=True)
    p.add_argument('--sdk-manifest',type=Path,help='Explicit complete SDK bundle mode, with an owned deny-only provider')
    args=p.parse_args()
    if not 1<=args.count<=1000:p.error('count must be 1..1000')
    app=args.app.resolve(strict=True)
    sdk_mode=args.sdk_manifest is not None
    if sdk_mode:
        subprocess.run(['python3',str(BASE/'scripts/app-manifest.py'),str(app),'--check',str(args.sdk_manifest)],check=True)
        subprocess.run(['python3',str(BASE/'scripts/check-agentcore-bundle.py'),str(app/'Contents/Resources/agentcore')],check=True)
    else:
        assert not (app/'Contents/Resources/agentcore').exists() and not (app/'Contents/Frameworks/libmetabrowser_metacodes.dylib').exists()
    assert args.ui_helper.is_file() and not args.output.exists(),'Fresh output required; inspect any existing run instead of restarting it'
    for port in (18860,18861):
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            sock.bind(('127.0.0.1',port))
    root=Path(tempfile.mkdtemp(prefix='metabrowser-cold-stability-')).resolve();(root/'.metabrowser-owned-fixture').write_text('fingerprint-stability')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    sources={str(q.relative_to(BASE)):digest(q) for q in [Path(__file__).resolve(),HERE/'identity_surface_runner.py',HERE/'identity_surface_collector.js',HERE/'identity_surface_probe.mjs']}
    framework=app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'
    report={'app':str(app),'root':str(root),'framework_sha256':digest(framework),'probe_sha256':sources,'target_count':args.count,'started_at':time.time(),'completed':False,'requirement_100_met':False,'paid_model_calls':0,'active_pid':None,'iterations':[],'full_anonymity_passed':False}
    provider_calls=[];provider_server=None
    if sdk_mode:
        class DenyProvider(http.server.BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_GET(self):
                data=b'{"data":[]}'
                self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def do_POST(self):
                provider_calls.append(self.path);self.send_error(403,'No model calls allowed in stability fixture')
        provider_server=http.server.ThreadingHTTPServer(('127.0.0.1',18862),DenyProvider)
        threading.Thread(target=provider_server.serve_forever,daemon=True).start()
        report.update(sdk_mode=True,bundle_manifest_sha256=digest(args.sdk_manifest),plugin_sha256=digest(app/'Contents/Frameworks/libmetabrowser_metacodes.dylib'),sdk_source_manifest_sha256=digest(app/'Contents/Resources/agentcore/manifest.json'))
    env={k:v for k,v in os.environ.items() if k in ('HOME','PATH','USER','LOGNAME','LANG','LC_CTYPE','TMPDIR','SHELL','__CF_USER_TEXT_ENCODING')}
    env.update(METABROWSER_IDENTITY_HOME=str(root/'identities'),METABROWSER_ACCOUNT_HOME=str(root/'accounts'),METABROWSER_CONVERSATION_HOME=str(root/'conversations'),METABROWSER_WORKSPACE=str(root/'workspace'))
    if sdk_mode:env.update(METABROWSER_API_KEY='fixture',METABROWSER_PROVIDER='openai',METABROWSER_MODEL='stability-fixture',METABROWSER_ENDPOINT='http://127.0.0.1:18862/v1/chat/completions')
    server=http.server.ThreadingHTTPServer(('127.0.0.1',18861),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    log=args.output.with_suffix('.runtime.log').open('w');os.fchmod(log.fileno(),0o600)
    process=None
    monotonic_start=time.monotonic()
    def save():write_private(args.output,report)
    def interrupt(signum,frame):raise KeyboardInterrupt('Owned stability fixture interrupted')
    signal.signal(signal.SIGTERM,interrupt)
    try:
        save()
        for index in range(1,args.count+1):
            assert digest(framework)==report['framework_sha256'],'Engine changed during stability run'
            if sdk_mode:
                assert not provider_calls,'Unexpected model request in SDK stability fixture'
                assert digest(app/'Contents/Frameworks/libmetabrowser_metacodes.dylib')==report['plugin_sha256']
            for name,h in sources.items():assert digest(BASE/name)==h,'Probe changed during run: '+name
            # Restore no old probe tabs, but preserve the profile and its key.
            for filename,section,key,value in [('Default/Preferences','session','restore_on_startup',5),('Local State','was','restarted',False)]:
                path=root/'browser'/filename;path.parent.mkdir(parents=True,exist_ok=True);prefs=json.loads(path.read_text()) if path.exists() else {};prefs.setdefault(section,{})[key]=value;write_private(path,prefs)
            process=subprocess.Popen([str(app/'Contents/MacOS/Chromium'),'--user-data-dir='+str(root/'browser'),'--remote-debugging-port=18860','--window-size=1200,900','--use-mock-keychain', '--no-first-run','--no-default-browser-check','--disable-component-update','--disable-background-networking','--hide-crash-restore-bubble','about:blank'],env=env,stdout=log,stderr=log,start_new_session=True)
            report['active_pid']=process.pid;save();deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                assert process.poll() is None,'Owned browser exited'
                try:
                    with urllib.request.urlopen('http://127.0.0.1:18860/json/version',timeout=.3) as response:json.load(response)
                    break
                except (OSError,ValueError):time.sleep(.15)
            else:raise TimeoutError('Owned CDP readiness timeout')
            result=subprocess.run(['node',str(HERE/'identity_surface_probe.mjs'),'18860','http://127.0.0.1:18861'],capture_output=True,text=True,timeout=100)
            if result.returncode:raise RuntimeError(result.stderr[-2500:])
            data=json.loads(result.stdout);checks=validate(data);policy=validate_passive(data,True)
            assert checks['consistency_passed'] and policy['passed'],'Identity/policy gate failed'
            current=signature(data)
            raw=args.output.with_name(args.output.stem+f'-{index:04d}.private.json')
            write_private(raw,{'framework_sha256':report['framework_sha256'],'iteration':index,'observations':data,'consistency':checks,'passive_policy':policy,'stable_signature':current})
            subprocess.run([str(args.ui_helper),str(process.pid),'quit'],env=dict(env,METABROWSER_UI_NO_ACTIVATE='1'),check=True,timeout=10)
            process.wait(timeout=20);assert process.returncode==0,'Cold restart must end with a clean native shutdown'
            report['active_pid']=None
            secret=json.loads((root/'browser/Default/Preferences').read_text())['metabrowser']['privacy']['root_secret']
            assert isinstance(secret,str) and secret,'Persistent identity secret missing'
            secret_digest=hashlib.sha256(secret.encode()).hexdigest()
            if report['iterations']:assert secret_digest==report['iterations'][0]['root_secret_sha256'],'Persistent identity rotated'
            first=report['iterations'][0]['signature'] if report['iterations'] else current
            entry={'index':index,'root_secret_sha256':secret_digest,'elapsed_seconds':time.monotonic()-monotonic_start,'pid':process.pid,'clean_shutdown':True,'signature':current,'matches_first':current==first,'artifact':str(raw),'sha256':digest(raw),'finished_at':time.time()};report['iterations'].append(entry);process=None;save()
            print(json.dumps({'cold_start':index,'clean_shutdown':True,'matches_first':entry['matches_first']}),flush=True)
            assert entry['matches_first'],'Stable identity drift; raw evidence retained'
        if sdk_mode:
            assert not provider_calls,'Unexpected model request in SDK stability fixture'
            subprocess.run(['python3',str(BASE/'scripts/app-manifest.py'),str(app),'--check',str(args.sdk_manifest)],check=True)
            assert digest(args.sdk_manifest)==report['bundle_manifest_sha256']
            report['sdk_no_provider_requests']=True
        report.update(completed=True,requirement_100_met=args.count>=100,finished_at=time.time())
    except BaseException as error:
        report['error']=str(error);raise
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=20)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        report['active_pid']=None;server.shutdown();server.server_close();log.close();save()
        if provider_server:provider_server.shutdown();provider_server.server_close()


if __name__=='__main__':main()
