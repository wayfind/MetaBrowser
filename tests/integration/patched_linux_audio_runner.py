"""Owned same-patch headless audio reference; no official/product parity claim."""
import argparse
import http.server
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from identity_surface_runner import Handler,digest,write_private
from linux_persona_launcher import FLAGS


def attest_proc_arguments(actual,exe,expected):
    canonical=[str(exe),*expected]
    if actual==canonical:return canonical,'nul-separated'
    # Chromium rewrites /proc cmdline into one process-title string. Accept
    # only an exact, unambiguous rendering of the already validated exec argv.
    assert all(token and not any(c.isspace() for c in token) for token in canonical)
    assert actual==[' '.join(canonical)],'Process title differs from validated exec argv'
    return canonical,'single-process-title'


def verify_renderer_transport(root,exe):
    records=[]
    for path in sorted(root.glob('renderer-launch-*.json')):
        entry=json.loads(path.read_text());pid=entry['pid'];proc=Path('/proc')/str(pid)
        if not proc.exists():continue
        assert (proc/'exe').resolve(strict=True)==exe
        actual=(proc/'cmdline').read_bytes().decode().rstrip('\0').split('\0')
        observation=root/f'renderer-proc-{pid}.json'
        write_private(observation,{'pid':pid,'actual':actual,'expected':entry['arguments']})
        canonical,representation=attest_proc_arguments(actual,exe,entry['arguments'])
        switches=canonical[1:canonical.index('--')] if '--' in canonical else canonical[1:]
        assert '--type=renderer' in switches and all(flag in switches for flag in FLAGS)
        records.append({'pid':pid,'actual_arguments':canonical,'raw_proc_arguments':actual,'cmdline_representation':representation,'launch_record':str(path)})
    assert records,'No live renderer with verified cohort transport'
    return records


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for flag in ('executable','node','build-receipt','output'):p.add_argument('--'+flag,type=Path,required=True)
    p.add_argument('--probe',choices=['audio-vector','audio-fft','audio-compressor','audio-resampler','audio-oscillator','audio-signature','audio-hrtf','audio-worklet','audio-hrtf-dynamic','audio-biquad-matrix','audio-biquad-boundary'],required=True)
    p.add_argument('--backend',choices=['scalar','native'],default='scalar');a=p.parse_args()
    assert os.uname().sysname=='Linux'
    exe=a.executable.resolve(strict=True);node=a.node.resolve(strict=True);receipt_raw=a.build_receipt.read_bytes();receipt=json.loads(receipt_raw)
    assert receipt['state']=='build-complete' and receipt['target']=='headless_shell'
    assert exe==Path(receipt['source'])/'out/metabrowser-linux-reference/headless_shell'
    assert digest(exe)==receipt['binary_sha256']
    for name,want in receipt['source_sha256'].items():assert digest(Path(receipt['source'])/name)==want,name
    for port in (18860,18861):
        with socket.socket() as s:s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('127.0.0.1',port))
    root=Path(tempfile.mkdtemp(prefix='metabrowser-patched-linux-audio-')).resolve();(root/'.metabrowser-owned-fixture').write_text('patched-linux-audio-reference')
    here=Path(__file__).resolve().parent;launcher=here/'linux_persona_launcher.py';probe=here/'audio_vector_probe.mjs';trial=here/(a.probe.replace('-','_')+'_trial.js')
    sources=[Path(__file__).resolve(),launcher,probe,trial,here/'identity_surface_runner.py',here/'identity_surface_collector.js']
    env={'PATH':'/usr/bin:/bin','HOME':str(root/'home'),'XDG_CONFIG_HOME':str(root/'config'),'XDG_CACHE_HOME':str(root/'cache'),'LANG':'C.UTF-8','TMPDIR':str(root),
         'METABROWSER_LINUX_REFERENCE_ROOT':str(root),'METABROWSER_LINUX_REFERENCE_BINARY':str(exe)}
    Path(env['HOME']).mkdir()
    flags=['--metabrowser-privacy=off','--disable-gpu','--no-sandbox','--no-zygote','--disable-dev-shm-usage','--disable-background-networking','--disable-component-update','--disable-sync','--password-store=basic',
           '--remote-debugging-address=127.0.0.1','--remote-debugging-port=18860','--user-data-dir='+str(root/'browser'),
           '--use-gl=angle','--use-angle=swiftshader','--use-webgpu-adapter=swiftshader','--enable-unsafe-swiftshader',
           '--disable-accelerated-video-decode','--disable-accelerated-video-encode']
    if a.backend=='scalar':flags+=['--metabrowser-persona-template=linux-x86_64-software-v1','--renderer-cmd-prefix='+sys.executable+' '+str(launcher)]
    command=[str(exe),*flags,'about:blank']
    report={'root':str(root),'completed':False,'clean_shutdown':False,'engine_sha256':digest(exe),
            'parent_mac_framework_sha256':receipt['parent_mac_framework_sha256'],'build_receipt_sha256':digest(a.build_receipt),
            'backend':a.backend,'probe_kind':a.probe,'command':command,'probe_sha256':{str(f):digest(f) for f in sources},
            'paid_model_calls':0,'requested_privacy':'off','hardware_gpu_rendering_proven':False,'full_scope_complete':False,'full_cross_platform_pipeline_proven':False,
            'scope':'Isolated headless, GPU disabled with software selectors, sandbox disabled for owned loopback fixtures; no official/default/UI/hardware parity.'}
    server=http.server.ThreadingHTTPServer(('127.0.0.1',18861),Handler);threading.Thread(target=server.serve_forever,daemon=True).start();process=None
    a.output.parent.mkdir(parents=True,exist_ok=True)
    try:
        with a.output.with_suffix('.runtime.log').open('w') as log:
            os.fchmod(log.fileno(),0o600);process=subprocess.Popen(command,env=env,stdout=log,stderr=log,start_new_session=True);report['pid']=process.pid
            for _ in range(200):
                assert process.poll() is None,'Owned headless exited'
                try:
                    with urllib.request.urlopen('http://127.0.0.1:18860/json/version',timeout=.3) as response:version=json.load(response)
                    assert version['Browser'].split('/')[-1]=='154.0.8037.97';report['browser_version']=version['Browser'];break
                except OSError:time.sleep(.1)
            else:raise TimeoutError('Headless readiness')
            result=subprocess.run([str(node),str(probe),trial.name],env=env,capture_output=True,text=True,timeout=210)
            write_private(root/'probe-process.private.json',{'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
            assert result.returncode==0,result.stderr[-3000:];report['observations']=json.loads(result.stdout)
            if a.backend=='scalar':report['renderer_transport']=verify_renderer_transport(root,exe)
            close="""const v=await(await fetch('http://127.0.0.1:18860/json/version')).json();if(!v.webSocketDebuggerUrl.startsWith('ws://127.0.0.1:18860/'))throw Error('Wrong owned endpoint');const w=new WebSocket(v.webSocketDebuggerUrl);await new Promise((ok,no)=>{w.onopen=ok;w.onerror=no});const done=new Promise(ok=>w.onclose=ok);w.send(JSON.stringify({id:1,method:'Browser.close'}));await done;"""
            subprocess.run([str(node),'--input-type=module','--eval',close],env=env,check=True,timeout=20)
            process.wait(timeout=20);assert process.returncode==0
            assert a.build_receipt.read_bytes()==receipt_raw and all(digest(Path(f))==h for f,h in report['probe_sha256'].items())
            report.update(completed=True,clean_shutdown=True)
    except BaseException as error:report['error']=str(error);raise
    finally:
        if process and process.poll() is None:process.terminate();process.wait(timeout=20)
        server.shutdown();server.server_close();write_private(a.output,report)
    print(json.dumps({'completed':True,'backend':a.backend,'probe_kind':a.probe,'full_scope_complete':False}))


if __name__=='__main__':main()
