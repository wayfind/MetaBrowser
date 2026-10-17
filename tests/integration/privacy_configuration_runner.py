"""Isolated malformed-config and conditional CPU API observations, no user data."""
import argparse
import base64
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
import identity_surface_runner as identity


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--ui-helper', type=Path, required=True)
    p.add_argument('--mode',action='append',choices=['protected','unknown_mode','empty_mode','corrupt_root','short_root','cpu_enabled','cpu_enabled_off','broken_preferences'])
    a=p.parse_args();app=a.app.resolve(strict=True)
    assert not (app/'Contents/Resources/agentcore').exists()
    assert not (app/'Contents/Frameworks/libmetabrowser_metacodes.dylib').exists()
    for port in (18860,18861):
        with socket.socket() as s:s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('127.0.0.1',port))
    root=Path(tempfile.mkdtemp(prefix='metabrowser-config-privacy-')).resolve()
    original=identity.HERE;probe=root/'probes';probe.mkdir()
    collector=(original/'identity_surface_collector.js').read_text()
    marker='const n = navigator, out = {secureContext:isSecureContext};'
    assert collector.count(marker)==1
    collector=collector.replace(marker,marker+"\n  out.cpuPerformance={present:'cpuPerformance' in n};if(out.cpuPerformance.present)out.cpuPerformance.value=n.cpuPerformance;")
    (probe/'identity_surface_collector.js').write_text(collector)
    node_probe=(original/'identity_surface_probe.mjs').read_text()
    marker='data.passiveSignalTrace=networkTrace;console.log(JSON.stringify(data));'
    assert node_probe.count(marker)==1
    retained="""data.passiveSignalTrace=networkTrace;
 data.retainedCPU=await evaluate(`(async()=>{
 const frame=document.createElement('iframe');frame.src='/';document.body.append(frame);
 await new Promise((ok,no)=>{frame.onload=ok;frame.onerror=no});
 const n=frame.contentWindow.navigator;
 const read=()=>({hardwareConcurrency:n.hardwareConcurrency,cpuPerformance:'cpuPerformance' in n?n.cpuPerformance:null});
 const before=read();frame.remove();await new Promise(r=>setTimeout(r,50));
 return {before,after:read()};})()`);
 console.log(JSON.stringify(data));"""
    (probe/'identity_surface_probe.mjs').write_text(node_probe.replace(marker,retained))
    identity.HERE=probe
    env={k:v for k,v in os.environ.items() if k in ('HOME','PATH','USER','LOGNAME','LANG','LC_CTYPE','TMPDIR','SHELL','__CF_USER_TEXT_ENCODING')}
    env.update(METABROWSER_IDENTITY_HOME=str(root/'identities'),METABROWSER_ACCOUNT_HOME=str(root/'account'),METABROWSER_CONVERSATION_HOME=str(root/'conversations'),METABROWSER_WORKSPACE=str(root/'workspace'))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    report={'root':str(root),'framework_sha256':identity.digest(app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'),'source_sha256':{str(f):identity.digest(f) for f in [Path(__file__).resolve(),original/'identity_surface_runner.py',probe/'identity_surface_collector.js',probe/'identity_surface_probe.mjs']},'modes':{},'completed':False,'paid_model_calls':0,'full_privacy_proven':False}
    server=http.server.ThreadingHTTPServer(('127.0.0.1',18861),identity.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    log=a.output.with_suffix('.runtime.log').open('w');os.fchmod(log.fileno(),0o600)
    modes=[('protected',[],None),('unknown_mode',['--metabrowser-privacy=balnced'],None),('empty_mode',['--metabrowser-privacy='],None),('corrupt_root',[],'invalid-base64-root'),('short_root',[],base64.b64encode(b'short').decode()),('cpu_enabled',['--enable-blink-features=CpuPerformance'],None),('cpu_enabled_off',['--enable-blink-features=CpuPerformance','--metabrowser-privacy=off'],None),('broken_preferences',[],'__broken_json__')]
    process=None
    try:
        for name,flags,corrupt in modes:
            if a.mode and name not in a.mode:continue
            data_dir=root/name;pref=data_dir/'Default/Preferences'
            if corrupt is not None:
                pref.parent.mkdir(parents=True)
                if name=='broken_preferences':
                    pref.write_text('{"metabrowser":{"privacy":{"root_secret":"'+base64.b64encode(b'r'*32).decode()+'"')
                else:identity.write_private(pref,{'metabrowser':{'privacy':{'root_secret':corrupt}}})
            process=subprocess.Popen([str(app/'Contents/MacOS/Chromium'),'--user-data-dir='+str(data_dir),'--remote-debugging-port=18860','--use-mock-keychain','--no-first-run','--no-default-browser-check','--disable-component-update','--disable-background-networking','--hide-crash-restore-bubble',*flags,'about:blank'],env=env,stdout=log,stderr=log,start_new_session=True)
            for _ in range(150):
                assert process.poll() is None,'Owned fixture exited during readiness'
                try:
                    urllib.request.urlopen('http://127.0.0.1:18860/json/version',timeout=.3).close();break
                except OSError:time.sleep(.15)
            else:raise TimeoutError('Owned fixture readiness timeout')
            r=subprocess.run(['node',str(probe/'identity_surface_probe.mjs'),'18860','http://127.0.0.1:18861'],capture_output=True,text=True,timeout=100)
            if r.returncode:raise RuntimeError(r.stderr[-2000:])
            data=json.loads(r.stdout);entry={'observations':data,'consistency':identity.validate(data),'protected_policy':identity.validate_passive(data,True),'native_control_policy':identity.validate_passive(data,False)}
            report['modes'][name]=entry
            subprocess.run([str(a.ui_helper),str(process.pid),'quit'],env=dict(env,METABROWSER_UI_NO_ACTIVATE='1'),check=True,timeout=10)
            process.wait(timeout=20);assert process.returncode==0;process=None
            if name=='broken_preferences':
                entry['new_identity_created']=bool(json.loads(pref.read_text()).get('metabrowser',{}).get('privacy',{}).get('root_secret'))
                entry['backup_files']={f.name:identity.digest(f) for f in pref.parent.glob('Preferences*') if f.is_file()}
            elif corrupt is not None:entry['corrupt_root_unchanged']=json.loads(pref.read_text())['metabrowser']['privacy']['root_secret']==corrupt
            identity.write_private(a.output,report)
            print(json.dumps({'mode':name,'protected':entry['protected_policy']['passed'],'native_control':entry['native_control_policy']['passed'],'cpu':{k:v['cpuPerformance'] for k,v in data['realms'].items()},'retained_cpu':data['retainedCPU']}),flush=True)
        report['completed']=True
    except BaseException as error:
        report['error']=str(error);raise
    finally:
        if process and process.poll() is None:process.terminate();process.wait(timeout=20)
        server.shutdown();server.server_close();log.close();identity.write_private(a.output,report)


if __name__=='__main__':main()
