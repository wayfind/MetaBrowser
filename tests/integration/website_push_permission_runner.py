"""Owned service-worker subscription probe; never sends a push message."""
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


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--ui-helper',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--permission',choices=['denied','granted'],required=True)
    parser.add_argument('--google-services-control',action='store_true')
    parser.add_argument('--persist-permission',action='store_true')
    parser.add_argument('--keep-subscription',action='store_true')
    parser.add_argument('--restore-from',type=Path)
    args=parser.parse_args();app=args.app.resolve(strict=True)
    manifest=['python3',str(Path(__file__).resolve().parents[2]/'scripts/app-manifest.py'),str(app),'--check',str(args.manifest)]
    subprocess.run(manifest,check=True)
    assert not (app/'Contents/Resources/agentcore').exists() and not (app/'Contents/Frameworks/libmetabrowser_metacodes.dylib').exists()
    for port in (18905,18906):
        with socket.socket() as s:s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('127.0.0.1',port))
    root=Path(tempfile.mkdtemp(prefix='metabrowser-webpush-permission-')).resolve()
    (root/'.metabrowser-owned-fixture').write_text('website-push-permission')
    framework=digest(app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework')
    profile_root=root
    previous=None
    if args.restore_from:
        previous=json.loads(args.restore_from.read_text())
        assert previous['completed'] is True and previous['clean_shutdown'] is True
        assert previous['framework_sha256']==framework and previous['keep_subscription'] is True
        profile_root=Path(previous['profile_root']).resolve(strict=True)
        assert profile_root.parent==Path(tempfile.gettempdir()).resolve()
        assert profile_root.name.startswith('metabrowser-webpush-permission-')
        assert (profile_root/'.metabrowser-owned-fixture').read_text()=='website-push-permission'
        assert not (profile_root/'browser').is_symlink() and (profile_root/'browser').resolve().is_relative_to(profile_root)
    preferences=profile_root/'browser/Default/Preferences'
    identity_before=None
    if preferences.exists():identity_before=json.loads(preferences.read_text()).get('metabrowser',{}).get('privacy',{}).get('root_secret')
    if args.persist_permission:
        assert args.permission=='granted'
        prefs=json.loads(preferences.read_text()) if preferences.exists() else {}
        notifications=prefs.setdefault('profile',{}).setdefault('content_settings',{}).setdefault('exceptions',{}).setdefault('notifications',{})
        notifications['http://127.0.0.1:18906,*']={'setting':1,'last_modified':str(int((time.time()+11644473600)*1000000))}
        preferences.parent.mkdir(parents=True,exist_ok=True);write_private(preferences,prefs)
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            if self.path=='/sw.js':body=b"self.addEventListener('push',()=>{});";mime='text/javascript'
            else:body=b'<!doctype html><title>Owned push permission fixture</title>';mime='text/html'
            self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
    server=http.server.ThreadingHTTPServer(('127.0.0.1',18906),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    env={k:v for k,v in os.environ.items() if k in ('HOME','PATH','USER','LOGNAME','LANG','LC_CTYPE','TMPDIR','SHELL','__CF_USER_TEXT_ENCODING')}
    env.update(METABROWSER_IDENTITY_HOME=str(profile_root/'identities'),METABROWSER_ACCOUNT_HOME=str(profile_root/'account'),METABROWSER_CONVERSATION_HOME=str(profile_root/'conversations'),METABROWSER_WORKSPACE=str(profile_root/'workspace'))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    probe=Path(__file__).with_name('website_push_permission_probe.mjs')
    report={'root':str(root),'profile_root':str(profile_root),'permission':args.permission,'persisted_permission':args.persist_permission,'keep_subscription':args.keep_subscription,'restored_report_sha256':digest(args.restore_from) if args.restore_from else None,'google_services_control':args.google_services_control,'framework_sha256':framework,'probe_sha256':{str(p):digest(p) for p in [Path(__file__),probe]},'completed':False,'clean_shutdown':False,'paid_model_calls':0,'messages_sent':0,'full_network_privacy_proven':False}
    process=None
    try:
        with (root/'runtime.private.log').open('w') as log:
            os.fchmod(log.fileno(),0o600)
            flags=['--metabrowser-enable-google-background-services'] if args.google_services_control else []
            process=subprocess.Popen([str(app/'Contents/MacOS/Chromium'),'--user-data-dir='+str(profile_root/'browser'),'--remote-debugging-port=18905','--use-mock-keychain','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-component-update','--log-net-log='+str(root/'push-netlog.private.json'),'--net-log-capture-mode=Default',*flags,'about:blank'],env=env,stdout=log,stderr=log,start_new_session=True)
            report['pid']=process.pid
            for _ in range(150):
                assert process.poll() is None
                try:
                    with urllib.request.urlopen('http://127.0.0.1:18905/json/list',timeout=.3) as r:
                        if any(x['type']=='page' for x in json.load(r)):break
                except OSError:pass
                time.sleep(.1)
            else:raise TimeoutError('Owned push browser not ready')
            result=subprocess.run(['node',str(probe),'18905',args.permission,'persisted' if args.persist_permission else 'override','keep' if args.keep_subscription else 'cleanup','restore' if args.restore_from else 'new'],capture_output=True,text=True,timeout=130)
            write_private(root/'probe-process.private.json',{'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
            assert result.returncode==0,result.stderr[-2000:]
            report['observations']=json.loads(result.stdout)
            if previous:
                old=previous['observations']['result']['outcome'];new=report['observations']['result']['outcome']
                report['restored_subscription_matches']=all(new.get(key)==old.get(key) for key in ('endpoint','p256dh_sha256','auth_sha256')) and new['kind']=='subscription'
            subprocess.run([str(args.ui_helper),str(process.pid),'quit'],env=dict(env,METABROWSER_UI_NO_ACTIVATE='1'),check=True,timeout=10)
            process.wait(timeout=20);assert process.returncode==0
            report.update(clean_shutdown=True,completed=True)
            if identity_before is not None:
                assert json.loads(preferences.read_text()).get('metabrowser',{}).get('privacy',{}).get('root_secret')==identity_before
                report['existing_identity_preserved']=True
        netlog=root/'push-netlog.private.json';netlog.chmod(0o600);report['netlog_sha256']=digest(netlog)
        subprocess.run(manifest,check=True)
    except BaseException as error:report['error']=str(error);raise
    finally:
        if process and process.poll() is None:process.terminate();process.wait(timeout=20)
        server.shutdown();server.server_close();write_private(args.output,report)
    outcome=report['observations']['result']['outcome']
    print(json.dumps({'completed':True,'permission':args.permission,'outcome_kind':outcome['kind'],'error_name':outcome.get('name'),'subscription_created':outcome['kind']=='subscription' and not args.restore_from,'unsubscribed':report['observations']['result']['unsubscribe'],'full_network_privacy_proven':False}))


if __name__=='__main__':main()
