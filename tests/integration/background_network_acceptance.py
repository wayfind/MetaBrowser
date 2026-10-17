"""Replay raw idle-profile NetLog, including traffic without URL requests."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
from urllib.parse import urlsplit


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(report, framework_sha256, manifest_sha256, probe_sha256, control=False):
    assert report['completed'] is True and report['clean_shutdown'] is True
    assert not report.get('error') and report['full_network_privacy_proven'] is False
    assert type(report['paid_model_calls']) is int and report['paid_model_calls'] == 0
    assert report['framework_sha256'] == framework_sha256
    assert report['manifest_sha256'] == manifest_sha256
    assert report['probe_sha256'] == probe_sha256
    assert report['capture_mode'] == 'Default' and report['explicit_navigation'] == 'about:blank'
    assert type(report['google_services_control']) is bool and report['google_services_control'] is control
    assert type(report['seconds']) is int and report['seconds'] >= (30 if control else 60)
    assert type(report['pid']) is int and report['pid'] > 0
    assert report['existing_identity_preserved'] is True
    root = Path(report['root']).resolve(strict=True)
    assert (root/'.metabrowser-owned-fixture').read_text() == 'background-network'
    netlog = root/'startup-netlog.private.json'
    assert not netlog.is_symlink() and digest(netlog) == report['netlog_sha256']
    raw = json.loads(netlog.read_text())
    client = raw['constants']['clientInfo']
    assert client['version'] == '154.0.8037.97'
    command = shlex.split(client['command_line'])
    assert '--user-data-dir='+str(Path(report['profile_root'])/'browser') in command
    assert '--log-net-log='+str(netlog) in command
    assert '--net-log-capture-mode=Default' in command
    assert ('--metabrowser-enable-google-background-services' in command) is control
    kinds = {value:key for key,value in raw['constants']['logEventTypes'].items()}
    begin = raw['constants']['logEventPhase']['PHASE_BEGIN']
    hosts, dns, transports, sends, sizes = (Counter() for _ in range(5))
    requests = []
    queries = 0
    assert len(raw['events']) == report['event_count']
    for event in raw['events']:
        kind = kinds[event['type']]
        params = event.get('params', {})
        if kind == 'URL_REQUEST_START_JOB':
            url = urlsplit(params.get('url', ''))
            if url.scheme in ('http', 'https', 'ws', 'wss') and url.hostname:
                hosts[url.hostname] += 1
                requests.append({'source_id':event['source']['id'], 'scheme':url.scheme,
                                 'host':url.hostname, 'method':params.get('method')})
        if kind == 'HOST_RESOLVER_MANAGER_REQUEST' and isinstance(params.get('host'), str):
            host = params['host']
            parsed = urlsplit(host if '://' in host else '//'+host)
            if parsed.hostname:
                dns[parsed.hostname] += 1
        if kind in ('TCP_CONNECT', 'UDP_CONNECT', 'QUIC_SESSION') and event.get('phase') == begin:
            transports[kind] += 1
        if kind == 'DNS_TRANSACTION_QUERY':
            queries += 1
        # Chromium logs TCP writes as SOCKET_BYTES_SENT, and TLS plaintext as
        # SSL_SOCKET_BYTES_SENT. Both must invalidate a claimed quiet capture.
        if kind.endswith('BYTES_SENT') or kind == 'QUIC_SESSION_PACKET_SENT':
            sends[kind] += 1
            if kind != 'QUIC_SESSION_PACKET_SENT':
                size = params.get('byte_count', 0)
                assert type(size) is int and size >= 0
                sizes[kind] += size
    assert dict(hosts) == report['request_hosts'] and requests == report['requests']
    assert dict(dns) == report['dns_hosts'] and dict(transports) == report['transport_start_counts']
    observed_types = {kinds[event['type']] for event in raw['events']}
    assert {'DNS_CONFIG_CHANGED', 'HTTP_SERVER_PROPERTIES_INITIALIZATION', 'COOKIE_STORE_ALIVE'}.issubset(observed_types), \
        'Empty/partial event capture cannot establish quiet startup'
    # The initial collector named TCP_BYTES_SENT and omitted the actual generic
    # socket counters. Its complete raw logs are still usable: validate that
    # legacy summary, but make the policy decision from ALL raw send events.
    if 'send_summary_version' in report:
        assert type(report['send_summary_version']) is int and report['send_summary_version'] == 2
        assert dict(sends) == report['sent_event_counts'] and dict(sizes) == report['sent_byte_counts']
    else:
        legacy = {'TCP_BYTES_SENT', 'UDP_BYTES_SENT', 'QUIC_SESSION_PACKET_SENT'}
        assert {k:v for k,v in sends.items() if k in legacy} == report['sent_event_counts']
        assert {k:v for k,v in sizes.items() if k in legacy} == report['sent_byte_counts']
    assert type(report['dns_transaction_queries']) is int and queries == report['dns_transaction_queries']
    if control:
        required = {'accounts.google.com', 'android.clients.google.com', 'clients2.google.com',
                    'www.google.com', 'update.googleapis.com', 'dl.google.com'}
        assert required.issubset(hosts), 'Positive control did not exercise all six baseline service hosts'
        assert dns and sum(sizes.values()) > 0
    else:
        assert not hosts and not dns and not transports and not sends and not sizes and queries == 0, \
            'Idle profile still initiates network work, even if no HTTP job exists'
    return {'passed':True, 'control':control, 'http_request_jobs':sum(hosts.values()),
            'dns_manager_requests':sum(dns.values()), 'dns_transaction_queries':queries,
            'outbound_tcp_udp_bytes':sizes['SOCKET_BYTES_SENT']+sizes['TCP_BYTES_SENT']+sizes['UDP_BYTES_SENT'],
            'raw_sent_event_counts':dict(sends),
            'tls_plaintext_bytes':sizes['SSL_SOCKET_BYTES_SENT'],
            'full_network_privacy_proven':False,
            'scope':'Timed fresh/owned profile idle NetLog only; not all browser states, website traffic, OS traffic or P1-P14.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--probe-source', type=Path, default=Path(__file__).with_name('background_network_runner.py'))
    parser.add_argument('--control', action='store_true')
    args = parser.parse_args()
    subprocess.run(['python3',str(Path(__file__).resolve().parents[2]/'scripts/app-manifest.py'),
                    str(args.app),'--check',str(args.manifest)], check=True, stdout=subprocess.DEVNULL)
    framework = args.app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework'
    print(json.dumps(verify(json.loads(args.report.read_text()), digest(framework), digest(args.manifest),
                            digest(args.probe_source), args.control), indent=2))


if __name__ == '__main__':
    main()
