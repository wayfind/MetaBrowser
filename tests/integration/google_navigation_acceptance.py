"""Replay public forms and owned cookie evidence, not authenticated Gmail."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from identity_surface_runner import digest


def verify(report, framework_sha256):
    assert report['completed'] is True and report['passed'] is True and report['clean_shutdown'] is True
    assert not report.get('error') and report['framework_sha256']==framework_sha256
    assert report['login_submitted'] is False and report['real_account_used'] is False
    assert type(report['paid_model_calls']) is int and report['paid_model_calls']==0
    assert report['full_network_privacy_proven'] is False
    root=Path(report['root']).resolve(strict=True)
    assert (root/'.metabrowser-owned-fixture').read_text()=='google-navigation-compat'
    native=json.loads((root/'native-cookie-observation.private.json').read_text())
    assert any(any(c['name']=='SAPISID' and c['value']=='metabrowser-owned-cookie-canary' and
                   c['domain']=='.google.com' and c['path']=='/' and c['secure'] is True
                   for c in row['canaries']) for row in native['contexts'])
    assert report['browser_did_not_delete_test_site_cookie'] is True
    commands=[json.loads(p.read_text()) for p in sorted(root.glob('*-command.private.json'),key=lambda p:int(p.name.split('-')[0]))]
    assert commands and all(c['exit_code']==0 for c in commands)
    assert all(c['arguments'][0] in ('cookies','open','wait','eval','snapshot','screenshot','get','close') for c in commands)
    observations=[]
    for c in commands:
        data=json.loads(c['stdout'])
        assert data['success'] is True
        if c['arguments'][0]=='eval':
            value=data['data']['result']
            if isinstance(value,str):
                value=json.loads(value)
            if isinstance(value,dict) and 'identifier' in value:
                observations.append(value)
    assert len(observations)==2 and set(report['pages'])=={'google_accounts','gmail'}
    for label,observed in zip(('google_accounts','gmail'),observations):
        assert report['pages'][label]==observed
        parsed=urlsplit(observed['url'])
        assert parsed.scheme=='https' and parsed.hostname in ('accounts.google.com','mail.google.com')
        assert observed['errorPage'] is False and 'Google' in observed['title']
        identifier=observed['identifier']
        assert identifier['type'] in ('text','email','tel') and identifier['disabled'] is False
        assert identifier['visible'] is True and type(identifier['valueLength']) is int and identifier['valueLength']==0
        assert observed['nextButton']['visible'] is True and observed['nextButton']['disabled'] is False
        image=root/(label+'-page.png')
        assert not image.is_symlink() and image.read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
    netlog=root/'navigation-netlog.private.json'
    assert not netlog.is_symlink() and digest(netlog)==report['netlog_sha256']
    raw=json.loads(netlog.read_text());types={v:k for k,v in raw['constants']['logEventTypes'].items()}
    # At startup the only cookie is our synthetic canary. Its explicit removal
    # precedes the first public HTTP job; browser account observation did not
    # silently fetch ListAccounts in response to the cookie change.
    added=deleted=first_web=None
    for event in raw['events']:
        kind=types[event['type']]
        if kind=='COOKIE_STORE_COOKIE_ADDED' and added is None:added=float(event['time'])
        if kind=='COOKIE_STORE_COOKIE_DELETED' and deleted is None:deleted=float(event['time'])
        if kind=='URL_REQUEST_START_JOB' and first_web is None:
            url=urlsplit(event.get('params',{}).get('url',''))
            if url.scheme in ('http','https'):
                first_web=(float(event['time']),url.hostname,url.path)
    assert added is not None and deleted is not None and first_web is not None
    assert deleted-added>=1500 and first_web[0]>=deleted
    assert first_web[1:] == ('accounts.google.com','/')
    return {'passed':True,'public_login_forms':2,'canary_preserved_before_explicit_clear':True,
            'no_http_before_explicit_public_navigation':True,'login_submitted':False,
            'authenticated_google_gmail_proven':False,'full_network_privacy_proven':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path)
    parser.add_argument('--app',type=Path,required=True)
    args=parser.parse_args()
    report=json.loads(args.report.read_text())
    for name,key in [('google_navigation_compat_runner.py','probe_sha256'),('owned_cookie_readback.mjs','cookie_probe_sha256')]:
        assert digest(Path(__file__).with_name(name))==report[key]
    print(json.dumps(verify(report,digest(args.app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework')),indent=2))
