"""Capture real ClientHello and HTTP/2 at an owned TLS endpoint, not a proxy."""
import argparse
import base64
import hashlib
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
from tls_transport_capture import CaptureServer


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app',type=Path,required=True)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--ui-helper',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--privacy',choices=['balanced','off'],required=True)
    p.add_argument('--protocol',choices=['h2','http/1.1'],default='h2')
    a=p.parse_args();app=a.app.resolve(strict=True);here=Path(__file__).resolve().parent
    subprocess.run(['python3',str(here.parents[1]/'scripts/app-manifest.py'),str(app),'--check',str(a.manifest)],check=True)
    assert not (app/'Contents/Resources/agentcore').exists()
    assert not (app/'Contents/Frameworks/libmetabrowser_metacodes.dylib').exists()
    for port in (18911,18912):
        with socket.socket() as s:
            s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('127.0.0.1',port))
    root=Path(tempfile.mkdtemp(prefix='metabrowser-tls-transport-')).resolve()
    (root/'.metabrowser-owned-fixture').write_text('tls-transport')
    cert,key=root/'server.crt',root/'server.key'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-sha256','-nodes','-days','1',
                    '-subj','/CN=transport.metabrowser.test','-addext','subjectAltName=DNS:transport.metabrowser.test',
                    '-keyout',str(key),'-out',str(cert)],capture_output=True,check=True,timeout=30)
    key.chmod(0o600)
    pub=subprocess.check_output(['openssl','x509','-in',str(cert),'-pubkey','-noout'])
    der=subprocess.run(['openssl','pkey','-pubin','-outform','DER'],input=pub,capture_output=True,check=True).stdout
    spki=base64.b64encode(hashlib.sha256(der).digest()).decode()
    env={k:v for k,v in os.environ.items() if k in ('HOME','PATH','USER','LOGNAME','LANG','LC_CTYPE','TMPDIR','SHELL','__CF_USER_TEXT_ENCODING')}
    env.update(METABROWSER_IDENTITY_HOME=str(root/'identities'),METABROWSER_ACCOUNT_HOME=str(root/'account'),METABROWSER_CONVERSATION_HOME=str(root/'conversations'),METABROWSER_WORKSPACE=str(root/'workspace'))
    sources=[Path(__file__).resolve(),here/'tls_transport_capture.py',here/'tls_transport_probe.mjs']
    report={'root':str(root),'completed':False,'clean_shutdown':False,'privacy':a.privacy,
            'framework_sha256':digest(app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'),
            'manifest_sha256':digest(a.manifest),'probe_sha256':{str(f):digest(f) for f in sources},
            'paid_model_calls':0,'full_network_privacy_proven':False,'official_release_parity_proven':False,
            'endpoint':'https://transport.metabrowser.test:18912','certificate_scope':'Owned ephemeral SPKI exception only; no system trust changes',
            'certificate_sha256':digest(cert),'certificate_spki_sha256_b64':spki,
            'server_alpn':[a.protocol],'protocol':a.protocol,'http3_proven':False,'decoded_header_order_proven':False}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    server=CaptureServer(('127.0.0.1',18912),str(cert),str(key),a.protocol)
    threading.Thread(target=server.serve_forever,daemon=True).start();process=None
    try:
        with a.output.with_suffix('.runtime.log').open('w') as log:
            os.fchmod(log.fileno(),0o600)
            command=[str(app/'Contents/MacOS/Chromium'),'--user-data-dir='+str(root/'browser'),
                '--remote-debugging-port=18911','--use-mock-keychain','--no-first-run',
                '--no-default-browser-check','--disable-component-update','--disable-background-networking',
                '--metabrowser-privacy='+a.privacy,'--ignore-certificate-errors-spki-list='+spki,
                '--no-proxy-server','--host-resolver-rules=MAP transport.metabrowser.test 127.0.0.1','about:blank']
            report['command']=command
            process=subprocess.Popen(command,env=env,stdout=log,stderr=log,start_new_session=True)
            report['pid']=process.pid
            for _ in range(150):
                assert process.poll() is None
                try:
                    urllib.request.urlopen('http://127.0.0.1:18911/json/version',timeout=.3).close();break
                except OSError:time.sleep(.1)
            else:raise TimeoutError('Owned transport browser readiness')
            result=subprocess.run(['node',str(here/'tls_transport_probe.mjs'),'18911'],capture_output=True,text=True,timeout=45)
            write_private(root/'probe-process.private.json',{'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
            assert result.returncode==0,result.stderr[-2000:]
            report['observation']=json.loads(result.stdout)
            subprocess.run([str(a.ui_helper),str(process.pid),'quit'],env=dict(env,METABROWSER_UI_NO_ACTIVATE='1'),check=True,timeout=10)
            process.wait(timeout=20);assert process.returncode==0
            for _ in range(50):
                with server.lock:
                    if server.records:break
                time.sleep(.1)
            with server.lock:report['connections']=list(server.records)
            assert any(row['completed'] for row in report['connections']), 'No real TLS/HTTP2 response captured'
            capture=root/'endpoint-capture.private.json'
            write_private(capture,report['connections'])
            report['endpoint_capture_sha256']=digest(capture)
            assert all(digest(Path(f))==h for f,h in report['probe_sha256'].items())
            report.update(completed=True,clean_shutdown=True)
    except BaseException as error:
        report['error']=str(error);raise
    finally:
        if process and process.poll() is None:process.terminate();process.wait(timeout=20)
        server.shutdown();server.server_close();write_private(a.output,report)
    print(json.dumps({'completed':True,'privacy':a.privacy,'connections':len(report['connections']),
                      'full_network_privacy_proven':False}))


if __name__=='__main__':main()
