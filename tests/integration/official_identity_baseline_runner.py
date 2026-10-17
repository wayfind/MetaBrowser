"""Same-branch official CfT observation; never claims exact-release parity."""
import argparse
import http.server
import json
import os
from pathlib import Path
import plistlib
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from identity_surface_runner import Handler, digest, validate, validate_passive, write_private


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--app',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--ui-helper',type=Path,required=True);a=p.parse_args()
    app=a.app.resolve(strict=True);info=plistlib.loads((app/'Contents/Info.plist').read_bytes());executable=app/'Contents/MacOS'/info['CFBundleExecutable'];assert executable.is_file()
    assert info['CFBundleIdentifier']=='com.google.chrome.for.testing','Require the explicit official testing variant'
    here=Path(__file__).resolve().parent;root=Path(tempfile.mkdtemp(prefix='metabrowser-official-baseline-')).resolve();(root/'.metabrowser-owned-fixture').write_text('official-baseline')
    for port in (18870,18871):
        with socket.socket() as sock:sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);sock.bind(('127.0.0.1',port))
    framework_bundle=list((app/'Contents/Frameworks').glob('*.framework'));assert len(framework_bundle)==1;framework=framework_bundle[0]/framework_bundle[0].stem
    # Identical expressions/collector. Only endpoints change so a live stability
    # fixture cannot be attached to or have its network state changed.
    probe=(here/'identity_surface_probe.mjs').read_text().replace('18860','18870').replace('18861','18871');script=root/'probe.mjs';script.write_text(probe)
    env={k:v for k,v in os.environ.items() if k in ('HOME','PATH','USER','LOGNAME','LANG','LC_CTYPE','TMPDIR','SHELL','__CF_USER_TEXT_ENCODING')}
    report={'kind':'official-CfT-approximate-baseline','app':str(app),'root':str(root),'version':info['CFBundleShortVersionString'],'bundle_id':info['CFBundleIdentifier'],'framework_sha256':digest(framework),'probe_sha256':{'collector':digest(here/'identity_surface_collector.js'),'original_probe':digest(here/'identity_surface_probe.mjs'),'port_remapped_probe':digest(script)},'completed':False,'exact_release_parity_proven':False,'paid_model_calls':0}
    a.output.parent.mkdir(parents=True,exist_ok=True);log=a.output.with_suffix('.runtime.log').open('w');os.fchmod(log.fileno(),0o600)
    server=http.server.ThreadingHTTPServer(('127.0.0.1',18871),Handler);threading.Thread(target=server.serve_forever,daemon=True).start();process=None
    try:
        process=subprocess.Popen([str(executable),'--user-data-dir='+str(root/'browser'),'--remote-debugging-port=18870','--window-size=1200,900','--use-mock-keychain', '--no-first-run','--no-default-browser-check','--disable-component-update','--disable-background-networking','--hide-crash-restore-bubble','about:blank'],env=env,stdout=log,stderr=log,start_new_session=True)
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            assert process.poll() is None,'Official test browser exited'
            try:
                with urllib.request.urlopen('http://127.0.0.1:18870/json/version',timeout=.3) as response:json.load(response)
                break
            except (OSError,ValueError):time.sleep(.15)
        else:raise TimeoutError('Owned official baseline readiness timeout')
        # Match a real foreground window before observing appearance/media state.
        subprocess.run([str(a.ui_helper),str(process.pid),'navigate','http://127.0.0.1:18871/'],env=env,capture_output=True,text=True,check=True,timeout=15)
        result=subprocess.run(['node',str(script),'18870','http://127.0.0.1:18871'],capture_output=True,text=True,timeout=100)
        if result.returncode:raise RuntimeError(result.stderr[-2500:])
        data=json.loads(result.stdout);report.update(observations=data,consistency=validate(data),native_passive_controls=validate_passive(data,False))
        subprocess.run([str(a.ui_helper),str(process.pid),'quit'],env=dict(env,METABROWSER_UI_NO_ACTIVATE='1'),check=True,timeout=10);process.wait(timeout=20);assert process.returncode==0
        report.update(completed=True,clean_shutdown=True)
    except BaseException as error:report['error']=str(error);raise
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=20)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        server.shutdown();server.server_close();log.close();write_private(a.output,report)
    print(json.dumps({'completed':True,'version':report['version'],'identity_consistent':report['consistency']['consistency_passed'],'native_controls_passed':report['native_passive_controls']['passed'],'exact_release_parity_proven':False}))


if __name__=='__main__':main()
