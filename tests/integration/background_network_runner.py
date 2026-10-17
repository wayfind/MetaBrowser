"""Observe an owned SDK-free profile's startup traffic, without visiting sites.

Default NetLog capture omits sensitive headers. Raw logs stay in a private QA
directory; summaries contain hostnames only. Observation is not a network leak
verdict or proof that every transport has been inspected.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.parse import urlsplit

from identity_surface_runner import digest, write_private


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--ui-helper', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=30)
    parser.add_argument('--google-services-control', action='store_true')
    reuse = parser.add_mutually_exclusive_group()
    reuse.add_argument('--reuse-from', type=Path,
                       help='reuse only a successful same-engine owned network fixture profile')
    reuse.add_argument('--upgrade-from', type=Path,
                       help='upgrade a successful different-engine owned network fixture profile')
    args = parser.parse_args()
    assert 5 <= args.seconds <= 90
    app = args.app.resolve(strict=True)
    project = Path(__file__).resolve().parents[2]
    manifest_command = ['python3', str(project/'scripts/app-manifest.py'), str(app), '--check', str(args.manifest)]
    subprocess.run(manifest_command, check=True)
    assert not (app/'Contents/Resources/agentcore').exists()
    assert not (app/'Contents/Frameworks/libmetabrowser_metacodes.dylib').exists()
    root = Path(tempfile.mkdtemp(prefix='metabrowser-background-network-')).resolve()
    (root/'.metabrowser-owned-fixture').write_text('background-network')
    framework_sha256 = digest(app/'Contents/Frameworks/Chromium Framework.framework/Chromium Framework')
    profile_root = root
    previous_report = args.reuse_from or args.upgrade_from
    previous_framework = None
    if previous_report:
        previous = json.loads(previous_report.read_text())
        assert previous['completed'] is True and previous['clean_shutdown'] is True
        previous_framework = previous['framework_sha256']
        assert (previous_framework == framework_sha256) is bool(args.reuse_from)
        profile_root = Path(previous['profile_root']).resolve(strict=True)
        assert profile_root.parent == Path(tempfile.gettempdir()).resolve()
        assert profile_root.name.startswith('metabrowser-background-network-')
        assert not (profile_root/'.metabrowser-owned-fixture').is_symlink()
        assert (profile_root/'.metabrowser-owned-fixture').read_text() == 'background-network'
        assert not (profile_root/'browser').is_symlink()
        assert (profile_root/'browser').resolve(strict=True).is_relative_to(profile_root)
    preferences = profile_root/'browser/Default/Preferences'

    def stored_identity():
        if not preferences.exists():
            return None
        return json.loads(preferences.read_text()).get('metabrowser', {}).get('privacy', {}).get('root_secret')

    identity_before = stored_identity()
    env = {k:v for k,v in os.environ.items() if k in ('HOME','PATH','USER','LOGNAME','LANG','LC_CTYPE','TMPDIR','SHELL','__CF_USER_TEXT_ENCODING')}
    env.update(METABROWSER_IDENTITY_HOME=str(profile_root/'identities'), METABROWSER_ACCOUNT_HOME=str(profile_root/'account'),
               METABROWSER_CONVERSATION_HOME=str(profile_root/'conversations'), METABROWSER_WORKSPACE=str(profile_root/'workspace'))
    netlog = root/'startup-netlog.private.json'
    report = {'root':str(root), 'completed':False, 'clean_shutdown':False,
              'framework_sha256':framework_sha256, 'profile_root':str(profile_root),
              'reused_profile':bool(previous_report), 'upgraded_profile':bool(args.upgrade_from),
              'previous_framework_sha256':previous_framework, 'google_services_control':args.google_services_control,
              'reused_report_sha256':digest(previous_report) if previous_report else None,
              'stored_identity_existed':identity_before is not None,
              'manifest_sha256':digest(args.manifest), 'probe_sha256':digest(Path(__file__)),
              'capture_mode':'Default', 'seconds':args.seconds, 'paid_model_calls':0,
              'full_network_privacy_proven':False, 'explicit_navigation':'about:blank'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    process = None
    try:
        with (root/'runtime.private.log').open('w') as log:
            os.fchmod(log.fileno(), 0o600)
            flags = ['--metabrowser-enable-google-background-services'] if args.google_services_control else []
            process = subprocess.Popen([str(app/'Contents/MacOS/Chromium'), '--user-data-dir='+str(profile_root/'browser'),
                '--use-mock-keychain', '--no-first-run', '--no-default-browser-check', '--disable-component-update',
                '--disable-background-networking', '--log-net-log='+str(netlog), '--net-log-capture-mode=Default',
                *flags, 'about:blank'], env=env, stdout=log, stderr=log, start_new_session=True)
            report['pid'] = process.pid
            deadline = time.monotonic()+args.seconds
            while time.monotonic() < deadline:
                assert process.poll() is None, 'Owned startup fixture exited prematurely'
                time.sleep(min(.2, max(0, deadline-time.monotonic())))
            subprocess.run([str(args.ui_helper), str(process.pid), 'quit'],
                           env=dict(env, METABROWSER_UI_NO_ACTIVATE='1'), check=True, timeout=10)
            process.wait(timeout=20)
            assert process.returncode == 0, 'Owned startup fixture did not quit cleanly'
            report['clean_shutdown'] = True
        assert not netlog.is_symlink()
        netlog.chmod(0o600)
        raw = json.loads(netlog.read_text())
        if identity_before is not None:
            assert stored_identity() == identity_before, 'Existing profile identity changed'
        event_types = raw['constants']['logEventTypes']
        start_job = event_types['URL_REQUEST_START_JOB']
        hosts = Counter()
        requests = []
        dns_hosts = Counter()
        transports = Counter()
        sent_events = Counter()
        sent_bytes = Counter()
        dns_query_count = 0
        names = {value:key for key,value in event_types.items()}
        for event in raw['events']:
            kind = names[event['type']]
            if kind.endswith('BYTES_SENT') or kind == 'QUIC_SESSION_PACKET_SENT':
                sent_events[kind] += 1
                if kind.endswith('BYTES_SENT'):
                    count = event.get('params', {}).get('byte_count', 0)
                    assert type(count) is int and count >= 0
                    sent_bytes[kind] += count
            if kind == 'DNS_TRANSACTION_QUERY':
                dns_query_count += 1
            if kind in ('TCP_CONNECT', 'UDP_CONNECT', 'QUIC_SESSION'):
                if event.get('phase') == raw['constants']['logEventPhase']['PHASE_BEGIN']:
                    transports[kind] += 1
            if kind == 'HOST_RESOLVER_MANAGER_REQUEST':
                host = event.get('params', {}).get('host')
                if isinstance(host, str):
                    parsed = urlsplit(host if '://' in host else '//'+host)
                    if parsed.hostname:
                        dns_hosts[parsed.hostname] += 1
            if event['type'] != start_job:
                continue
            params = event.get('params', {})
            url = urlsplit(params.get('url', ''))
            if url.scheme not in ('http', 'https', 'ws', 'wss') or not url.hostname:
                continue
            hosts[url.hostname] += 1
            requests.append({'source_id':event['source']['id'], 'scheme':url.scheme,
                             'host':url.hostname, 'method':params.get('method')})
        report.update(completed=True, event_count=len(raw['events']),
                      request_hosts=dict(sorted(hosts.items())), requests=requests,
                      dns_hosts=dict(sorted(dns_hosts.items())), transport_start_counts=dict(transports),
                      sent_event_counts=dict(sent_events), sent_byte_counts=dict(sent_bytes),
                      send_summary_version=2,
                      dns_transaction_queries=dns_query_count,
                      netlog_sha256=digest(netlog),
                      existing_identity_preserved=identity_before is None or stored_identity() == identity_before,
                      scope='One fresh profile startup with background networking disabled; URL request events only. No user sites or credentials; no payload/identifier leakage verdict.')
        subprocess.run(manifest_command, check=True)
    except BaseException as error:
        report.update(completed=False, error=str(error))
        raise
    finally:
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=20)
        write_private(args.output, report)
    print(json.dumps({'completed':True, 'request_hosts':report['request_hosts'], 'full_network_privacy_proven':False}))


if __name__ == '__main__':
    main()
