"""Native error/closed profile and explicit recovery in owned QA directories."""
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
import identity_surface_runner as identity


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--app',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--ui-helper',type=Path,required=True)
    p.add_argument('--ocr-helper',type=Path,default=Path('/tmp/metabrowser-privacy-error-ocr'))
    p.add_argument('--window-helper',type=Path,default=Path('/tmp/metabrowser-owned-error-window'))
    p.add_argument('--case',action='append',choices=['base64','short','empty','wrong_type','json_parse','json_type'])
    p.add_argument('--rejection-launches',type=int,default=1,choices=[1,2,3])
    a=p.parse_args();app=a.app.resolve(strict=True)
    subprocess.run(['python3',str(Path(__file__).resolve().parents[2]/'scripts/app-manifest.py'),str(app),'--check',str(a.manifest)],check=True)
    assert not (app/'Contents/Resources/agentcore').exists()
    assert not (app/'Contents/Frameworks/libmetabrowser_metacodes.dylib').exists()
    with socket.socket() as s:s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('127.0.0.1',18876))
    root=Path(tempfile.mkdtemp(prefix='metabrowser-root-rejection-')).resolve();requests=[]
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            requests.append(self.path)
            body=b'<!doctype html><title>Owned root recovery canary</title>'
            self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=http.server.ThreadingHTTPServer(('127.0.0.1',18876),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
    env={k:v for k,v in os.environ.items() if k in ('HOME','PATH','USER','LOGNAME','LANG','LC_CTYPE','TMPDIR','SHELL','__CF_USER_TEXT_ENCODING')}
    env.update(METABROWSER_IDENTITY_HOME=str(root/'identities'),METABROWSER_ACCOUNT_HOME=str(root/'account'),METABROWSER_CONVERSATION_HOME=str(root/'conversations'),METABROWSER_WORKSPACE=str(root/'workspace'))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    report={'engine_manifest_sha256':identity.digest(a.manifest),'root':str(root),'framework_sha256':identity.digest(app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'),'cases':{},'completed':False,'passed':False,'paid_model_calls':0,'rejection_launches':a.rejection_launches,'full_anonymity_proven':False,'probe_sha256':{str(f):identity.digest(f) for f in [Path(__file__).resolve(),Path(__file__).with_name('privacy_error_ocr.swift'),Path(__file__).with_name('owned_error_window.swift')]}};process=None
    log=a.output.with_suffix('.runtime.log').open('w');os.fchmod(log.fileno(),0o600)
    def launch(profile,url):
        return subprocess.Popen([str(app/'Contents/MacOS/Chromium'),'--user-data-dir='+str(profile),'--use-mock-keychain','--no-first-run','--no-default-browser-check','--disable-component-update','--disable-background-networking',url],env=env,stdout=log,stderr=log,start_new_session=True)
    def dump():
        return subprocess.check_output([str(a.ui_helper),str(process.pid),'dump'],env=dict(env,METABROWSER_UI_NO_ACTIVATE='1'),text=True,timeout=5)
    def stop():
        if process.poll() is None:process.terminate();process.wait(timeout=20)
    try:
        for name,value in [('base64','not-base64'),('short',base64.b64encode(b'short').decode()),('empty',''),('wrong_type',False),('json_parse',None),('json_type',None)]:
            if a.case and name not in a.case:continue
            profile=root/name;pref=profile/'Default/Preferences';pref.parent.mkdir(parents=True)
            if name=='json_parse':
                pref.write_text('{"metabrowser":{"privacy":{"root_secret":"'+base64.b64encode(b'r'*32).decode()+'"')
            elif name=='json_type':pref.write_text('[]')
            else:identity.write_private(pref,{'metabrowser':{'privacy':{'root_secret':value}}})
            original_bytes=pref.read_bytes();stock_warnings=0
            def check_preserved():
                if name in ('json_parse','json_type'):
                    copies=[f for f in pref.parent.glob('Preferences*') if f.is_file() and f.read_bytes()==original_bytes]
                    assert copies,'Original damaged preferences were not retained'
                    if pref.exists():
                        try:current=json.loads(pref.read_text())
                        except ValueError:current=None
                        if isinstance(current,dict):assert not current.get('metabrowser',{}).get('privacy',{}).get('root_secret'),'A replacement identity was created'
                else:assert json.loads(pref.read_text())['metabrowser']['privacy']['root_secret']==value
            rejection_attempts=[]
            for rejection_index in range(a.rejection_launches):
                artifact_name=name if rejection_index==a.rejection_launches-1 else name+'-repeat-'+str(rejection_index)
                stock_warnings=0
                start=len(requests);process=launch(profile,'http://127.0.0.1:18876/'+name+'/blocked')
                ui='';evidence_method='native-accessibility';deadline=time.monotonic()+25
                while time.monotonic()<deadline:
                    assert requests[start:]==[],'Rejected identity contacted site before explicit recovery'
                    assert process.poll() is None,'Owned fixture exited without the expected native error'
                    ui=dump()
                    identity.write_private(root/(artifact_name+'-last-ui.private.json'),{'pid':process.pid,'accessibility':ui})
                    if name in ('json_parse','json_type') and (('您的偏好设置文件已损坏或无效' in ui and '无法恢复您的设置' in ui) or ('系统无法读取您的偏好设置' in ui and '对偏好设置所做的更改不会保存' in ui)) and 'AXButton 确定 ' in ui:
                        assert stock_warnings==0,'Repeated upstream warning instead of a closed profile'
                        stock_warnings+=1
                        identity.write_private(root/(artifact_name+'-upstream-warning.private.json'),{'pid':process.pid,'accessibility':ui,'method':'native-accessibility'})
                        assert requests[start:]==[]
                        subprocess.run([str(a.ui_helper),str(process.pid),'press','确定'],env=env,check=True,timeout=10)
                        time.sleep(.2)
                        continue
                    if '身份配置无法读取或校验' in ui and '原身份未更换' in ui:break
                    # A startup NSAlert can be visible before app AX registration.
                    # Capture only this PID's window and verify actual rendered text.
                    window=subprocess.run([str(a.ui_helper),str(process.pid),'window'],env=dict(env,METABROWSER_UI_NO_ACTIVATE='1'),capture_output=True,text=True,timeout=5)
                    if window.returncode==0:
                        image=root/(artifact_name+'-dialog.png')
                        subprocess.run(['/usr/sbin/screencapture','-x','-l',window.stdout.strip(),str(image)],check=True,timeout=5)
                        words=json.loads(subprocess.check_output([str(a.ocr_helper),str(image)],text=True,timeout=15))
                        text=''.join(''.join(words).split())
                        if name in ('json_parse','json_type') and (('您的偏好设置文件已损坏或无效' in text and '无法恢复您的设置' in text) or ('系统无法读取您的偏好设置' in text and '对偏好设置所做的更改不会保存' in text)) and '确定' in text:
                            assert stock_warnings==0,'Repeated upstream warning instead of a closed profile'
                            stock_warnings+=1
                            identity.write_private(root/(artifact_name+'-upstream-warning.private.json'),{'pid':process.pid,'text':words,'image_sha256':identity.digest(image)})
                            import shutil
                            shutil.copy2(image,root/(artifact_name+'-upstream-warning.png'))
                            assert requests[start:]==[]
                            subprocess.run([str(a.ui_helper),str(process.pid),'key','Return'],env=env,check=True,timeout=10)
                            time.sleep(.2)
                            continue
                        if '身份配置无法读取或校验' in text and '原身份未更换' in text and '确定' in text:
                            evidence_method='owned-window-image-and-Vision-OCR'
                            ui='\n'.join(words)
                            break
                    time.sleep(.2)
                else:raise AssertionError('No explicit native damaged-identity error')
                identity.write_private(root/(artifact_name+'-dialog.private.json'),{'pid':process.pid,'accessibility':ui})
                time.sleep(.5)
                assert requests[start:]==[],'Broken identity reached the requested site'
                check_preserved()
                if evidence_method=='native-accessibility':
                    buttons=[l.split(' ',2)[1] for l in ui.splitlines() if l.startswith('AXButton ')];ack=next((x for x in buttons if x in ['确定','好','OK']),None);assert ack,'No native acknowledgement button'
                    subprocess.run([str(a.ui_helper),str(process.pid),'press',ack],env=env,check=True,timeout=10)
                else:
                    subprocess.run([str(a.ui_helper),str(process.pid),'key','Return'],env=env,check=True,timeout=10)
                # Wait for the actual profile-picker UI, rather than killing the
                # browser while the startup NSAlert is still closing. Fixed sleeps
                # caused SIGTERM watchdog dumps and did not prove acknowledgement.
                ready=False;button_retries=0;deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    assert requests[start:]==[]
                    if process.poll() is not None:
                        raise AssertionError('Rejected fixture exited before a usable native profile picker; exit alone cannot prove picker readiness')
                    rejected_ui=dump()
                    if '访客模式' in rejected_ui and '添加' in rejected_ui:
                        ready=True;break
                    windows=json.loads(subprocess.check_output([str(a.window_helper),'list',str(process.pid)],text=True,timeout=5))
                    for w in windows:
                        if w['width']<100 or w['height']<80:continue
                        post_image=root/(artifact_name+'-post-ack-'+str(w['id'])+'.png')
                        subprocess.run(['/usr/sbin/screencapture','-x','-o','-l',str(w['id']),str(post_image)],check=True,capture_output=True,timeout=5)
                        boxes=json.loads(subprocess.check_output([str(a.window_helper),'text-boxes',str(post_image)],text=True,timeout=15))
                        rendered=''.join(''.join(b['text'] for b in boxes).split())
                        identity.write_private(root/(artifact_name+'-post-ack.private.json'),{'window':w,'text_boxes':boxes,'image_sha256':identity.digest(post_image)})
                        if '访客模式' in rendered and '添加' in rendered and '个人资料' in rendered:
                            ready=True;break
                        if button_retries==0 and '身份配置无法读取或校验' in rendered and '原身份未更换' in rendered:
                            buttons=[b for b in boxes if b['text']=='确定'];assert len(buttons)==1
                            b=buttons[0];x=w['x']+w['width']*(b['x']+b['width']/2);y=w['y']+w['height']*(1-b['y']-b['height']/2)
                            subprocess.run([str(a.window_helper),'click',str(process.pid),str(w['id']),str(x),str(y)],check=True,timeout=5)
                            button_retries+=1
                    if ready:break
                    time.sleep(.2)
                assert ready,'Rejected profile did not return to a usable native profile picker'
                if process.poll() is None:
                    subprocess.run([str(a.ui_helper),str(process.pid),'quit'],env=dict(env,METABROWSER_UI_NO_ACTIVATE='1'),check=True,timeout=10)
                    process.wait(timeout=20)
                rejected_exit=process.returncode
                assert rejected_exit==0,'Rejected fixture did not shut down cleanly'
                process=None
                assert requests[start:]==[]
                check_preserved()
                rejection_attempts.append({'index':rejection_index,'artifact_prefix':artifact_name,'exit_code':rejected_exit,'picker_ready':ready,'blocked_requests':requests[start:].copy(),'evidence_method':evidence_method,'dialog_text_sha256':identity.digest(root/(artifact_name+'-dialog.private.json')),'dialog_image_sha256':identity.digest(root/(artifact_name+'-dialog.png')) if evidence_method=='owned-window-image-and-Vision-OCR' else None})
            rejected=root/(name+'-rejected-input.private.bin');rejected.write_bytes(original_bytes);rejected.chmod(0o600)
            blocked_requests=requests[start:].copy()
            if name in ('json_parse','json_type'):d={'metabrowser':{'privacy':{}}}
            else:d=json.loads(pref.read_text())
            restored=base64.b64encode(b'r'*32).decode();d['metabrowser']['privacy']['root_secret']=restored;identity.write_private(pref,d)
            start=len(requests);process=launch(profile,'http://127.0.0.1:18876/'+name+'/restored');deadline=time.monotonic()+25
            while time.monotonic()<deadline:
                assert process.poll() is None,'Explicitly restored profile failed to open'
                if '/'+name+'/restored' in requests[start:]:break
                time.sleep(.2)
            else:raise AssertionError('Explicit restoration did not recover site navigation')
            subprocess.run([str(a.ui_helper),str(process.pid),'quit'],env=dict(env,METABROWSER_UI_NO_ACTIVATE='1'),check=True,timeout=10);process.wait(timeout=20);assert process.returncode==0;process=None
            assert json.loads(pref.read_text())['metabrowser']['privacy']['root_secret']==restored,'Restored root rotated'
            report['cases'][name]={'rejection_attempts':rejection_attempts,'rejected_profile_picker_ready':True,'rejected_clean_shutdown':True,'rejected_exit_code':rejected_exit,'evidence_method':evidence_method,'dialog_text_sha256':identity.digest(root/(name+'-dialog.private.json')),'dialog_image_sha256':identity.digest(root/(name+'-dialog.png')) if evidence_method=='owned-window-image-and-Vision-OCR' else None,'upstream_warnings_acknowledged':stock_warnings,'rejected_input_sha256':identity.digest(rejected),'blocked_requests':blocked_requests,'restored_requests':requests[start:].copy(),'explicit_native_error':True,'site_not_contacted':True,'damaged_root_preserved':True,'explicit_restore_recovers_navigation':True,'restored_root_preserved':True};identity.write_private(a.output,report);print(json.dumps({'case':name,'passed':True}),flush=True)
        subprocess.run(['python3',str(Path(__file__).resolve().parents[2]/'scripts/app-manifest.py'),str(app),'--check',str(a.manifest)],check=True)
        report.update(completed=True,passed=bool(report['cases']))
    except BaseException as error:report['error']=str(error);raise
    finally:
        if process and process.poll() is None:stop()
        server.shutdown();server.server_close();log.close();report['observed_requests']=requests.copy();identity.write_private(a.output,report)


if __name__=='__main__':main()
