"""Bounded native permission/subscription proof, not OS-prompt or delivery QA."""
import argparse
import ipaddress
import json
from pathlib import Path
import shlex
from urllib.parse import urlsplit
from identity_surface_runner import digest


def verify(report, framework_sha256):
    assert report['completed'] is True and report['clean_shutdown'] is True and not report.get('error')
    assert report['framework_sha256']==framework_sha256
    assert type(report['paid_model_calls']) is int and report['paid_model_calls']==0
    assert type(report['messages_sent']) is int and report['messages_sent']==0
    assert report['full_network_privacy_proven'] is False
    assert type(report['google_services_control']) is bool
    kept=report.get('keep_subscription',False);persisted=report.get('persisted_permission',False)
    assert type(kept) is bool and type(persisted) is bool
    root=Path(report['root']).resolve(strict=True)
    assert (root/'.metabrowser-owned-fixture').read_text()=='website-push-permission'
    process=json.loads((root/'probe-process.private.json').read_text())
    assert process['exit_code']==0
    raw_observations=json.loads(process['stdout'])
    assert raw_observations==report['observations'] and raw_observations['completed'] is True
    permission=report['permission'];assert permission in ('denied','granted')
    assert raw_observations['permission']==permission and raw_observations['messages_sent']==0
    expected_control='owned persisted native notification setting, not an OS consent prompt' if persisted else 'native Browser.setPermission override, not an OS consent prompt'
    assert raw_observations['permission_control']==expected_control
    result=raw_observations['result']
    assert result['origin']=='http://127.0.0.1:18906' and result['secure'] is True
    assert result['before']==dict.fromkeys(('notification','query','push'),permission)
    assert type(result['notificationsSent']) is int and result['notificationsSent']==0
    assert result['remainingSubscription'] is kept
    outcome=result['outcome']
    restoring=bool(report.get('restored_report_sha256'))
    if restoring:
        value=report['restored_report_sha256']
        assert isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)
        assert result['was_existing'] is True and report['restored_subscription_matches'] is True
        assert report['existing_identity_preserved'] is True
    if permission=='denied':
        assert kept is False
        assert outcome['kind']=='error' and outcome['name']=='NotAllowedError'
        assert result['unsubscribe'] is None
    else:
        assert outcome['kind']=='subscription', 'A pending/error result is not functional push acceptance'
        endpoint=urlsplit(outcome['endpoint'])
        assert endpoint.scheme=='https' and endpoint.hostname=='fcm.googleapis.com' and len(endpoint.path)>30
        assert outcome['hasP256DH'] is True and outcome['hasAuth'] is True
        if kept:
            assert result['unsubscribe'] is None
        else:
            assert result['unsubscribe'] is True
    netlog=root/'push-netlog.private.json'
    assert not netlog.is_symlink() and digest(netlog)==report['netlog_sha256']
    raw=json.loads(netlog.read_text());names={v:k for k,v in raw['constants']['logEventTypes'].items()}
    client=raw['constants']['clientInfo'];assert client['version']=='154.0.8037.97'
    command=shlex.split(client['command_line'])
    assert ('--metabrowser-enable-google-background-services' in command) is report['google_services_control']
    assert '--user-data-dir='+str(Path(report.get('profile_root',report['root']))/'browser') in command
    assert '--log-net-log='+str(netlog) in command and '--net-log-capture-mode=Default' in command
    urls=[];dns=[]
    for event in raw['events']:
        params=event.get('params',{})
        if names[event['type']]=='URL_REQUEST_START_JOB':
            url=urlsplit(params.get('url',''))
            if url.scheme in ('http','https') and url.hostname:urls.append((url.hostname,url.path))
        if names[event['type']]=='HOST_RESOLVER_MANAGER_REQUEST' and isinstance(params.get('host'),str):
            host=params['host'];parsed=urlsplit(host if '://' in host else '//'+host)
            if parsed.hostname:dns.append(parsed.hostname)
    assert any(host=='127.0.0.1' and path=='/sw.js' for host,path in urls)
    external={host for host,path in urls if host!='127.0.0.1'}
    if not report['google_services_control']:
        if permission=='denied':
            assert not external and all(host=='127.0.0.1' for host in dns), 'Denied permission contacted external service'
            for event in raw['events']:
                kind=names[event['type']];params=event.get('params',{})
                assert kind not in ('UDP_BYTES_SENT','QUIC_SESSION','QUIC_SESSION_PACKET_SENT','SSL_CONNECT','SSL_SOCKET_BYTES_SENT','DNS_TRANSACTION_QUERY')
                if kind in ('TCP_CONNECT','TCP_CONNECT_ATTEMPT'):
                    addresses=list(params.get('address_list',[]))
                    addresses.extend(params[key] for key in ('address','remote_address') if key in params)
                    for address in addresses:
                        assert ipaddress.ip_address(urlsplit('//'+address).hostname).is_loopback
                if kind=='UDP_CONNECT' and 'address' in params:
                    # HostResolverManager's local IPv6 route check uses UDP
                    # connect/GetLocalAddress, not send. Treat it separately
                    # from packets; an empty datagram would also fail above.
                    assert params['address']=='[2001:4860:4860::8888]:443'
        else:
            assert external.issubset({'android.clients.google.com'}), 'Unrelated Google service piggybacked on website push'
            if not report.get('restored_report_sha256'):
                assert ('android.clients.google.com','/checkin') in urls
                assert ('android.clients.google.com','/c2dm/register3') in urls
    return {'passed':True,'permission':permission,'google_services_control':report['google_services_control'],
            'subscription_available':permission=='granted','subscription_created':permission=='granted' and not restoring,
            'unsubscribe_completed':permission=='granted' and not kept,
            'external_http_hosts':sorted(external),'messages_sent':0,
            'os_notification_consent_proven':False,'notification_delivery_proven':False,'full_network_privacy_proven':False}


def verify_restore(seed,restored,framework_sha256,seed_report_sha256):
    verify(seed,framework_sha256);verify(restored,framework_sha256)
    assert seed['keep_subscription'] is True and restored['keep_subscription'] is False
    assert seed['persisted_permission'] is True and restored['persisted_permission'] is True
    assert seed['profile_root']==restored['profile_root'] and seed['root']!=restored['root']
    assert seed['pid']!=restored['pid']
    assert restored['restored_report_sha256']==seed_report_sha256
    assert restored['restored_subscription_matches'] is True and restored['existing_identity_preserved'] is True
    first=seed['observations']['result'];second=restored['observations']['result']
    assert first['was_existing'] is False and second['was_existing'] is True
    for key in ('endpoint','p256dh_sha256','auth_sha256'):
        assert first['outcome'][key]==second['outcome'][key]
        if key!='endpoint':
            value=first['outcome'][key]
            assert isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)
    return {'passed':True,'same_saved_subscription_and_key_hashes':True,'native_restarts':1,
            'browser_identity_preserved':True,'unsubscribed_after_restart':True,
            'messages_sent':0,'os_notification_consent_proven':False,'notification_delivery_proven':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path)
    parser.add_argument('--app',type=Path,required=True)
    parser.add_argument('--probe-dir',type=Path,default=Path(__file__).parent)
    parser.add_argument('--restored-from',type=Path)
    args=parser.parse_args();report=json.loads(args.report.read_text())
    assert bool(args.restored_from)==bool(report.get('restored_report_sha256')), 'A restore report needs its independent seed artifact'
    for path,sha in report['probe_sha256'].items():assert digest(args.probe_dir/Path(path).name)==sha
    framework=digest(args.app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework')
    result=verify(report,framework)
    if args.restored_from:
        seed=json.loads(args.restored_from.read_text())
        for path,sha in seed['probe_sha256'].items():assert digest(args.probe_dir/Path(path).name)==sha
        result['restore']=verify_restore(seed,report,framework,digest(args.restored_from))
    print(json.dumps(result,indent=2))
