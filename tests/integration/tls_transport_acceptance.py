"""Replay native endpoint bytes; normalized equality is not official TLS parity."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
from identity_surface_runner import digest
from tls_transport_capture import parse_client_hello,parse_http1_request


def verify(report, framework):
    assert report['completed'] is True and report['clean_shutdown'] is True and not report.get('error')
    assert type(report['paid_model_calls']) is int and report['paid_model_calls']==0
    assert report['framework_sha256']==framework
    assert report['privacy'] in ('balanced','off')
    assert report['full_network_privacy_proven'] is False
    assert report['official_release_parity_proven'] is False
    assert report['http3_proven'] is False and report['decoded_header_order_proven'] is False
    protocol=report.get('protocol','h2');assert protocol in ('h2','http/1.1')
    assert report['server_alpn']==[protocol]
    root=Path(report['root']).resolve(strict=True)
    assert (root/'.metabrowser-owned-fixture').read_text()=='tls-transport'
    raw=root/'endpoint-capture.private.json'
    assert not raw.is_symlink() and digest(raw)==report['endpoint_capture_sha256']
    assert json.loads(raw.read_text())==report['connections']
    process=json.loads((root/'probe-process.private.json').read_text())
    assert process['exit_code']==0 and json.loads(process['stdout'])==report['observation']
    assert report['observation']['completed'] is True
    page=report['observation']['observation']
    assert page['url']=='https://transport.metabrowser.test:18912/owned-transport' and page['title']=='Owned transport'
    command=report['command']
    assert '--ignore-certificate-errors' not in command
    assert '--user-data-dir='+str(root/'browser') in command
    assert '--metabrowser-privacy='+report['privacy'] in command
    assert '--remote-debugging-port=18911' in command
    assert '--no-proxy-server' in command
    assert '--host-resolver-rules=MAP transport.metabrowser.test 127.0.0.1' in command
    cert=root/'server.crt'
    assert not cert.is_symlink() and digest(cert)==report['certificate_sha256']
    pub=subprocess.check_output(['openssl','x509','-in',str(cert),'-pubkey','-noout'])
    der=subprocess.run(['openssl','pkey','-pubin','-outform','DER'],input=pub,capture_output=True,check=True).stdout
    spki=base64.b64encode(hashlib.sha256(der).digest()).decode()
    assert spki==report['certificate_spki_sha256_b64']
    assert [s for s in command if s.startswith('--ignore-certificate-errors-spki-list=')]==['--ignore-certificate-errors-spki-list='+spki]
    usable=[]
    for connection in report['connections']:
        assert not connection.get('error'), connection.get('error')
        assert connection['peer_loopback'] is True
        hello=parse_client_hello(base64.b64decode(connection['client_hello_b64'],validate=True))
        assert hello==connection['client_hello']
        assert connection['client_hellos']
        for index, item in enumerate(connection['client_hellos']):
            assert parse_client_hello(base64.b64decode(item['wire_b64'],validate=True))==item['parsed']
            if index==0:assert item['parsed']==hello and item['wire_b64']==connection['client_hello_b64']
        assert hello['cipher_suites'] and hello['groups'] and hello['signature_algorithms']
        assert hello['server_names']==['transport.metabrowser.test']
        assert hello['alpn']==['h2','http/1.1'] and 0x304 in hello['supported_versions']
        assert connection['tls_version']=='TLSv1.3' and connection['alpn']==protocol
        if not connection['completed']:continue
        if protocol=='http/1.1':
            request=parse_http1_request(base64.b64decode(connection['http1_request_b64'],validate=True))
            assert request==connection['http1_request']
            if request['path']!='/owned-transport':continue
            names=[key for key,value in request['headers']]
            lower=[key.lower() for key in names]
            assert len(lower)==len(set(lower)) and lower[0]=='host'
            assert {'host','user-agent','accept','accept-language','sec-ch-ua','sec-ch-ua-platform'}<=set(lower)
            values={key.lower():value for key,value in request['headers']}
            assert values['host']=='transport.metabrowser.test:18912'
            assert 'Chrom' in values['user-agent'] and values['sec-ch-ua-platform']=='"macOS"'
            assert 'cookie' not in lower and 'authorization' not in lower
            usable.append({'client_hello':hello['normalized'],'http1_header_order':names})
            continue
        assert connection['http2_preface'] is True and connection['response_streams']
        settings=[row['settings'] for row in connection['frames'] if row['type']==4 and not row['flags']&1]
        windows=[row['increment'] for row in connection['frames'] if row['type']==8 and row['stream']==0]
        assert len(settings)==1 and settings[0] and windows and all(v>0 for v in windows)
        assert any(row['type']==1 and row['stream'] in connection['response_streams'] for row in connection['frames'])
        usable.append({'client_hello':hello['normalized'],'http2_settings':settings[0],
                       'initial_connection_window_increment':windows[0]})
    assert usable
    assert all(value==usable[0] for value in usable)
    return {'passed':True,'privacy':report['privacy'],'connections':len(usable),
            'framework_sha256':framework,'normalized_transport':usable[0],
            'http1_header_order_proven':protocol=='http/1.1',
            'scope':'Loopback TLS1.3/'+protocol+' termination endpoint, ephemeral certificate SPKI exception. No proxy. HTTP1 raw header order only when selected; no HTTP3, HPACK decoded order, official-release or external-site parity claim.',
            'full_network_privacy_proven':False,'official_release_parity_proven':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path)
    p.add_argument('--app',type=Path,required=True);p.add_argument('--other',type=Path)
    p.add_argument('--probe-dir',type=Path,help='Frozen capture sources for historical replay')
    args=p.parse_args();r=json.loads(args.report.read_text())
    for f,h in r['probe_sha256'].items():assert digest(args.probe_dir/Path(f).name if args.probe_dir else Path(f))==h
    framework=digest(args.app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework')
    result=verify(r,framework)
    if args.other:
        other=json.loads(args.other.read_text())
        for f,h in other['probe_sha256'].items():assert digest(args.probe_dir/Path(f).name if args.probe_dir else Path(f))==h
        second=verify(other,framework)
        assert r['privacy']!=other['privacy'] and r['pid']!=other['pid'] and r['root']!=other['root']
        assert result['normalized_transport']==second['normalized_transport']
        result['protected_off_normalized_transport_equal']=True
    print(json.dumps(result,indent=2))
