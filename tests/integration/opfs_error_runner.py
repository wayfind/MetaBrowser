"""Native OPFS quota, cancellation and in-flight bucket-deletion observations."""
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
from identity_surface_runner import digest, write_private
from quota_pressure_runner import QuotaHandler
from opfs_seven_fixture import Handler as SevenHandler


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for flag in ('app','manifest','ui-helper','output'):p.add_argument('--'+flag,type=Path,required=True)
    p.add_argument('--privacy',choices=['balanced','off'],required=True)
    p.add_argument('--matrix',choices=['basic','seven'],default='basic')
    a=p.parse_args();app=a.app.resolve(strict=True);here=Path(__file__).resolve().parent
    subprocess.run(['python3',str(here.parents[1]/'scripts/app-manifest.py'),str(app),'--check',str(a.manifest)],check=True)
    assert not (app/'Contents/Resources/agentcore').exists()
    assert not (app/'Contents/Frameworks/libmetabrowser_metacodes.dylib').exists()
    for port in (18877,18878):
        with socket.socket() as s:s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('127.0.0.1',port))
    root=Path(tempfile.mkdtemp(prefix='metabrowser-opfs-errors-')).resolve()
    (root/'.metabrowser-owned-fixture').write_text('opfs-errors')
    env={k:v for k,v in os.environ.items() if k in ('HOME','PATH','USER','LOGNAME','LANG','LC_CTYPE','TMPDIR','SHELL','__CF_USER_TEXT_ENCODING')}
    env.update(METABROWSER_IDENTITY_HOME=str(root/'identities'),METABROWSER_ACCOUNT_HOME=str(root/'account'),METABROWSER_CONVERSATION_HOME=str(root/'conversations'),METABROWSER_WORKSPACE=str(root/'workspace'))
    probes=[Path(__file__).resolve(),here/'opfs_error_probe.mjs',here/'quota_pressure_runner.py',here/'quota_pressure_collector.js']
    if a.matrix=='seven':
        probes=[Path(__file__).resolve(),here/'opfs_seven_probe.mjs',here/'opfs_seven_trial.js',here/'opfs_seven_fixture.py']
    report={'root':str(root),'completed':False,'clean_shutdown':False,'privacy':a.privacy,
            'framework_sha256':digest(app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'),
            'probe_sha256':{str(f):digest(f) for f in probes},'matrix':a.matrix,'paid_model_calls':0,'full_storage_privacy_proven':False}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    handler=SevenHandler if a.matrix=='seven' else QuotaHandler
    if a.matrix=='seven':handler.requests=[]
    server=http.server.ThreadingHTTPServer(('127.0.0.1',18878),handler)
    threading.Thread(target=server.serve_forever,daemon=True).start();process=None
    try:
        with a.output.with_suffix('.runtime.log').open('w') as log:
            os.fchmod(log.fileno(),0o600)
            process=subprocess.Popen([str(app/'Contents/MacOS/Chromium'),'--user-data-dir='+str(root/'browser'),
              '--remote-debugging-port=18877','--use-mock-keychain','--no-first-run','--no-default-browser-check',
              '--disable-component-update','--disable-background-networking','--metabrowser-privacy='+a.privacy,'about:blank'],
              env=env,stdout=log,stderr=log,start_new_session=True)
            report['pid']=process.pid
            for _ in range(150):
                assert process.poll() is None
                try:urllib.request.urlopen('http://127.0.0.1:18877/json/version',timeout=.3).close();break
                except OSError:time.sleep(.1)
            else:raise TimeoutError('Owned OPFS readiness')
            probe=here/('opfs_seven_probe.mjs' if a.matrix=='seven' else 'opfs_error_probe.mjs')
            result=subprocess.run(['node',str(probe),'18877'],capture_output=True,text=True,timeout=240)
            write_private(root/'probe-process.private.json',{'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
            assert result.returncode==0,result.stderr[-3000:]
            report['observations']=json.loads(result.stdout)
            assert report['observations']['completed'] is True
            subprocess.run([str(a.ui_helper),str(process.pid),'quit'],env=dict(env,METABROWSER_UI_NO_ACTIVATE='1'),check=True,timeout=10)
            process.wait(timeout=20);assert process.returncode==0
            if a.matrix=='seven':
                requests=root/'fixture-requests.private.json'
                write_private(requests,handler.requests)
                report['fixture_requests_sha256']=digest(requests)
            assert all(digest(Path(f))==h for f,h in report['probe_sha256'].items())
            report.update(completed=True,clean_shutdown=True)
    except BaseException as error:report['error']=str(error);raise
    finally:
        if process and process.poll() is None:process.terminate();process.wait(timeout=20)
        server.shutdown();server.server_close();write_private(a.output,report)
    print(json.dumps({'completed':True,'privacy':a.privacy,'cases':len(report['observations']['rows'])}))


if __name__=='__main__':main()
