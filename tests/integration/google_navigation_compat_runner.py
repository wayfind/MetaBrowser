"""Owned public-page/cookie compatibility. Never log in or send messages."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request
from urllib.parse import urlsplit

from identity_surface_runner import digest, write_private


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--ui-helper', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    app = args.app.resolve(strict=True)
    manifest_command = ['python3', str(Path(__file__).resolve().parents[2]/'scripts/app-manifest.py'),
                        str(app), '--check', str(args.manifest)]
    subprocess.run(manifest_command, check=True)
    assert not (app/'Contents/Resources/agentcore').exists()
    assert not (app/'Contents/Frameworks/libmetabrowser_metacodes.dylib').exists()
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('127.0.0.1',18903))
    root = Path(tempfile.mkdtemp(prefix='metabrowser-google-compat-')).resolve()
    (root/'.metabrowser-owned-fixture').write_text('google-navigation-compat')
    env = {k:v for k,v in os.environ.items() if k in ('HOME','PATH','USER','LOGNAME','LANG','LC_CTYPE','TMPDIR','SHELL','__CF_USER_TEXT_ENCODING')}
    env.update(METABROWSER_IDENTITY_HOME=str(root/'identities'), METABROWSER_ACCOUNT_HOME=str(root/'account'),
               METABROWSER_CONVERSATION_HOME=str(root/'conversations'), METABROWSER_WORKSPACE=str(root/'workspace'))
    session = subprocess.check_output(['agent-browser','session','id','--scope','worktree','--prefix','ng'],
                                      text=True, env=env, timeout=10).strip()+'-'+str(os.getpid())
    cli = ['agent-browser','--namespace','mbqa','--session',session,'--cdp','18903','--json']
    report = {'root':str(root), 'framework_sha256':digest(app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'),
              'probe_sha256':digest(Path(__file__)), 'manifest_sha256':digest(args.manifest),
              'cookie_probe_sha256':digest(Path(__file__).with_name('owned_cookie_readback.mjs')),
              'completed':False, 'passed':False, 'paid_model_calls':0, 'login_submitted':False,
              'real_account_used':False, 'full_network_privacy_proven':False, 'pages':{}, 'session':session}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    process = None
    steps = 0

    def command(*arguments, script=None, timeout=45):
        nonlocal steps
        steps += 1
        result = subprocess.run(cli+list(arguments), input=script, text=True, capture_output=True,
                                timeout=timeout, env=env)
        write_private(root/(str(steps)+'-command.private.json'),
                      {'arguments':arguments, 'stdout':result.stdout, 'stderr':result.stderr, 'exit_code':result.returncode})
        assert result.returncode == 0, 'Owned agent-browser command failed: '+(result.stderr+result.stdout)[-1500:]
        data = json.loads(result.stdout)
        assert data['success'] is True, data
        return data['data']

    try:
        with (root/'runtime.private.log').open('w') as log:
            os.fchmod(log.fileno(),0o600)
            process = subprocess.Popen([str(app/'Contents/MacOS/Chromium'), '--user-data-dir='+str(root/'browser'),
                '--remote-debugging-port=18903', '--use-mock-keychain', '--no-first-run','--no-default-browser-check',
                '--disable-background-networking','--disable-component-update',
                '--log-net-log='+str(root/'navigation-netlog.private.json'),'--net-log-capture-mode=Default','about:blank'],
                env=env, stdout=log, stderr=log, start_new_session=True)
            report['pid'] = process.pid
            deadline = time.monotonic()+25
            while time.monotonic()<deadline:
                assert process.poll() is None
                try:
                    with urllib.request.urlopen('http://127.0.0.1:18903/json/list',timeout=.3) as r:
                        if any(x['type']=='page' for x in json.load(r)):
                            break
                except OSError:
                    pass
                time.sleep(.15)
            else:
                raise TimeoutError('Owned CDP page not ready')
            # A fake, local test value, not a user cookie or Google credential.
            cookie_value = 'metabrowser-owned-cookie-canary'
            command('cookies','set','SAPISID',cookie_value,'--domain','.google.com','--path','/','--secure')
            time.sleep(2)
            before = command('cookies','get')
            write_private(root/'cookie-observation.private.json',before)
            # CLI cookie reads may be scoped to about:blank rather than the
            # domain just set. Independently inspect the owned browser stores.
            native=json.loads(subprocess.check_output(['node',str(Path(__file__).with_name('owned_cookie_readback.mjs')),'18903'],text=True,timeout=20))
            write_private(root/'native-cookie-observation.private.json',native)
            assert any(row['canaries'] for row in native['contexts']), 'Owned canary absent from native stores'
            report['browser_did_not_delete_test_site_cookie'] = True
            # Remove the fake cookie before any public Google navigation.
            command('cookies','clear')
            for label,url in [('google_accounts','https://accounts.google.com/'),('gmail','https://mail.google.com/')]:
                opened=command('open',url,timeout=60)
                command('wait','--load','domcontentloaded',timeout=30)
                if label=='gmail' and urlsplit(opened['url']).hostname=='workspace.google.com':
                    # Anonymous Gmail may redirect to its official landing page.
                    # Follow its actual sign-in link, never invent a login URL.
                    landing=command('snapshot','-i','-c')
                    refs=[ref for ref,item in landing['refs'].items() if item.get('role')=='link' and 'gmail' in item.get('name','').lower() and ('登录' in item.get('name','') or 'sign in' in item.get('name','').lower())]
                    assert len(refs)==1,'No unique visible Gmail sign-in link'
                    attribute=command('get','attr','@'+refs[0],'href')
                    hrefs={value for value in attribute.values() if isinstance(value,str) and urlsplit(value).scheme=='https' and urlsplit(value).hostname in ('accounts.google.com','mail.google.com')}
                    assert len(hrefs)==1,'No Google-hosted Gmail sign-in href'
                    href=hrefs.pop()
                    report['gmail_landing_signin_link']={'name':landing['refs'][refs[0]]['name'],'href':href}
                    command('open',href,timeout=60)
                    command('wait','--load','domcontentloaded',timeout=30)
                snapshot=command('snapshot','-i','-c')
                write_private(root/(label+'-snapshot.private.json'),snapshot)
                diagnostics=command('eval','--stdin',script='''JSON.stringify({url:location.href,title:document.title,
                  inputs:Array.from(document.querySelectorAll('input')).map(x=>({id:x.id,type:x.type,name:x.name,label:x.getAttribute('aria-label')})),
                  iframes:Array.from(document.querySelectorAll('iframe')).map(x=>x.src),
                  text:document.body ? document.body.innerText.slice(0,2000) : ''})''')
                write_private(root/(label+'-diagnostics.private.json'),diagnostics)
                command('screenshot',str(root/(label+'-page.png')))
                command('wait','#identifierId',timeout=30)
                page = command('eval','--stdin',script='''JSON.stringify({url:location.href,title:document.title,
                  ready:document.readyState,identifier:(()=>{const x=document.querySelector('input#identifierId[name=identifier]');
                  return x?{type:x.type,disabled:x.disabled,valueLength:x.value.length,visible:x.getBoundingClientRect().width>0&&x.getBoundingClientRect().height>0}:null})(),
                  nextButton:(()=>{const x=document.querySelector('#identifierNext button');return x?{disabled:x.disabled,visible:x.getBoundingClientRect().width>0&&x.getBoundingClientRect().height>0}:null})(),
                  bodyLength:document.body ? document.body.innerText.length : 0,
                  errorPage:location.protocol==='chrome-error:'})''')
                observation = page['result']
                if isinstance(observation,str):
                    observation = json.loads(observation)
                assert urlsplit(observation['url']).hostname in ('accounts.google.com','mail.google.com')
                assert observation['errorPage'] is False and observation['bodyLength']>0
                assert 'Google' in observation['title']
                identifier=observation['identifier']
                assert identifier and identifier['type'] in ('email','text','tel') and identifier['disabled'] is False
                assert identifier['visible'] is True and identifier['valueLength']==0
                assert observation['nextButton']=={'disabled':False,'visible':True}, 'No usable public Google login form reached'
                report['pages'][label] = observation
                write_private(args.output,report)
            command('close',timeout=15)
            if process.poll() is None:
                subprocess.run([str(args.ui_helper),str(process.pid),'quit'],
                               env=dict(env,METABROWSER_UI_NO_ACTIVATE='1'),check=True,timeout=10)
            process.wait(timeout=20)
            assert process.returncode == 0
            report['clean_shutdown'] = True
        netlog = root/'navigation-netlog.private.json'
        netlog.chmod(0o600)
        report['netlog_sha256'] = digest(netlog)
        subprocess.run(manifest_command,check=True)
        report.update(completed=True,passed=True)
    except BaseException as error:
        report['error'] = str(error)
        raise
    finally:
        if process and process.poll() is None:
            subprocess.run(cli+['close'],capture_output=True,text=True,timeout=15,env=env)
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=20)
        write_private(args.output,report)
    print(json.dumps({'passed':True,'public_login_pages':list(report['pages']),'login_submitted':False}))


if __name__=='__main__':
    main()
