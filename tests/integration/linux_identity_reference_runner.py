"""Official CfT Linux software-cohort diagnostic, never exact Mac release parity."""
import argparse
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
from identity_surface_runner import Handler,digest,write_private,validate


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for flag in ('executable','node','output'):p.add_argument('--'+flag,type=Path,required=True)
    p.add_argument('--probe',choices=['metadata','audio-vector'],default='metadata')
    a=p.parse_args();exe=a.executable.resolve(strict=True);node=a.node.resolve(strict=True)
    assert os.uname().sysname=='Linux' and 'cft-154.0.8037.92' in str(exe)
    for port in (18860,18861):
        with socket.socket() as s:s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('127.0.0.1',port))
    here=Path(__file__).resolve().parent
    root=Path(tempfile.mkdtemp(prefix='metabrowser-linux-reference-')).resolve()
    (root/'.metabrowser-owned-fixture').write_text('linux-identity-reference')
    env={'PATH':'/usr/bin:/bin','HOME':str(root/'home'),'XDG_CONFIG_HOME':str(root/'config'),
         'XDG_CACHE_HOME':str(root/'cache'),'LANG':'C.UTF-8','TMPDIR':str(root)}
    Path(env['HOME']).mkdir()
    sources=[Path(__file__).resolve(),here/'identity_surface_runner.py',here/'identity_surface_probe.mjs',here/'identity_surface_collector.js']
    probe=here/('identity_surface_probe.mjs' if a.probe=='metadata' else 'audio_vector_probe.mjs')
    if a.probe=='audio-vector':sources.extend([probe,here/'audio_vector_trial.js'])
    report={'root':str(root),'completed':False,'clean_shutdown':False,'reference_executable_sha256':digest(exe),
            'reference_version':'154.0.8037.92','target_version':'154.0.8037.97',
            'same_version_baseline_proven':False,'official_default_configuration_proven':False,
            'hardware_gpu_rendering_proven':False,'paid_model_calls':0,'full_privacy_proven':False,
            'probe_sha256':{str(f):digest(f) for f in sources},
            'scope':'Official CfT different-patch Linux headless software cohort, temporary HOME, owned loopback only; no native H200 GPU, Mac release parity or hardware timing proof.'}
    report['probe_kind']=a.probe
    flags=['--headless=new','--no-sandbox','--disable-dev-shm-usage','--no-first-run',
           '--no-default-browser-check','--disable-background-networking','--disable-component-update',
           '--disable-sync','--password-store=basic','--disable-gpu','--use-gl=angle',
           '--use-angle=swiftshader','--use-webgpu-adapter=swiftshader','--enable-unsafe-swiftshader',
           '--disable-accelerated-video-decode','--disable-accelerated-video-encode',
           '--user-data-dir='+str(root/'browser'),'--remote-debugging-address=127.0.0.1',
           '--remote-debugging-port=18860','about:blank']
    report['command']=[str(exe),*flags]
    server=http.server.ThreadingHTTPServer(('127.0.0.1',18861),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start();process=None
    a.output.parent.mkdir(parents=True,exist_ok=True)
    try:
        with a.output.with_suffix('.runtime.log').open('w') as log:
            os.fchmod(log.fileno(),0o600)
            process=subprocess.Popen(report['command'],env=env,stdout=log,stderr=log,start_new_session=True)
            report['pid']=process.pid
            for _ in range(150):
                assert process.poll() is None,'Owned reference browser exited'
                try:
                    with urllib.request.urlopen('http://127.0.0.1:18860/json/version',timeout=.3) as response:
                        version=json.load(response)
                    assert version['Browser']=='Chrome/154.0.8037.92'
                    report['browser_version']=version['Browser'];break
                except OSError:time.sleep(.1)
            else:raise TimeoutError('Owned Linux reference readiness')
            result=subprocess.run([str(node),str(probe),'18860','http://127.0.0.1:18861'],env=env,capture_output=True,text=True,timeout=180)
            write_private(root/'probe-process.private.json',{'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
            assert result.returncode==0,result.stderr[-2000:]
            report['observations']=json.loads(result.stdout)
            if a.probe=='metadata':
                report['consistency']=validate(report['observations'])
                window=report['observations']['realms']['window']
                assert window['uaData']['high']['platform']=='Linux'
                renderers=[v['parameters']['unmaskedRenderer'] for v in window['rendering']['webgl'].values()]
                assert len(renderers)==2 and all('SwiftShader' in r for r in renderers),renderers
                report['software_renderer_verified']=True
            else:
                assert report['observations']['platform']=='Linux x86_64'
                report['software_renderer_verified']=None
            close="""const v=await(await fetch('http://127.0.0.1:18860/json/version')).json();if(!v.webSocketDebuggerUrl.startsWith('ws://127.0.0.1:18860/'))throw Error('Wrong owned endpoint');const w=new WebSocket(v.webSocketDebuggerUrl);await new Promise((ok,no)=>{w.onopen=ok;w.onerror=no});const end=new Promise(ok=>{w.onclose=ok});w.send(JSON.stringify({id:1,method:'Browser.close'}));await end;"""
            subprocess.run([str(node),'--input-type=module','--eval',close],env=env,check=True,timeout=20)
            process.wait(timeout=20);assert process.returncode==0
            assert all(digest(Path(f))==h for f,h in report['probe_sha256'].items())
            report.update(completed=True,clean_shutdown=True)
    except BaseException as error:report['error']=str(error);raise
    finally:
        if process and process.poll() is None:process.terminate();process.wait(timeout=20)
        server.shutdown();server.server_close();write_private(a.output,report)
    print(json.dumps({'completed':True,'browser':report['browser_version'],'probe_kind':a.probe,
                     'software_renderer_verified':report['software_renderer_verified'],
                     'same_version_baseline_proven':False}))


if __name__=='__main__':main()
