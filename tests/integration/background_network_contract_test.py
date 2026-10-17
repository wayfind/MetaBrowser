"""Quietness requires raw DNS and socket evidence, not just an HTTP counter."""
import argparse
import copy
import json
from pathlib import Path
import shlex
import tempfile
import unittest

from background_network_acceptance import digest, verify


class NetworkEvidence(unittest.TestCase):
    def check(self, report):
        return verify(report, FRAMEWORK, MANIFEST, PROBE)

    def test_actual_capture(self):
        self.assertTrue(self.check(REPORT)['passed'])

    def test_summary_and_binding_corruptions(self):
        cases = {
            'unfinished':lambda r:r.update(completed=False),
            'unclean exit':lambda r:r.update(clean_shutdown=False),
            'engine substituted':lambda r:r.update(framework_sha256='0'*64),
            'manifest substituted':lambda r:r.update(manifest_sha256='0'*64),
            'probe substituted':lambda r:r.update(probe_sha256='0'*64),
            'raw log substituted':lambda r:r.update(netlog_sha256='0'*64),
            'sensitive capture':lambda r:r.update(capture_mode='IncludeSensitive'),
            'not idle':lambda r:r.update(explicit_navigation='https://www.google.com/'),
            'paid calls':lambda r:r.update(paid_model_calls=1),
            'boolean cost':lambda r:r.update(paid_model_calls=False),
            'short capture':lambda r:r.update(seconds=1),
            'boolean duration':lambda r:r.update(seconds=True),
            'control disguised as quiet':lambda r:r.update(google_services_control=True),
            'wrong profile':lambda r:r.update(profile_root=r['profile_root']+'/other'),
            'event count fabricated':lambda r:r.update(event_count=0),
            'DNS summary fabricated':lambda r:r.update(dns_hosts={'www.google.com':1}),
            'packet summary fabricated':lambda r:r.update(sent_event_counts={'QUIC_SESSION_PACKET_SENT':1}),
            'identity lost':lambda r:r.update(existing_identity_preserved=False),
            'full network overclaim':lambda r:r.update(full_network_privacy_proven=True),
            'unknown send schema':lambda r:r.update(send_summary_version=3),
            'boolean send schema':lambda r:r.update(send_summary_version=True),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                report = copy.deepcopy(REPORT)
                mutate(report)
                with self.assertRaises((AssertionError, KeyError, ValueError)):
                    self.check(report)
        print('Summary/binding negative types:',len(cases))

    def test_raw_non_http_traffic_and_empty_capture(self):
        original = Path(REPORT['root'])/'startup-netlog.private.json'
        for case in ('tcp_only', 'tls_only', 'udp_only', 'quic_only', 'dns_only', 'empty_capture'):
            with self.subTest(case=case), tempfile.TemporaryDirectory(prefix='metabrowser-network-contract-') as tmp:
                root = Path(tmp).resolve()
                (root/'.metabrowser-owned-fixture').write_text('background-network')
                path = root/'startup-netlog.private.json'
                raw = json.loads(original.read_text())
                command = shlex.split(raw['constants']['clientInfo']['command_line'])
                command = ['--log-net-log='+str(path) if arg.startswith('--log-net-log=') else arg for arg in command]
                raw['constants']['clientInfo']['command_line'] = shlex.join(command)
                report = copy.deepcopy(REPORT)
                report['root'] = str(root)

                def save():
                    path.write_text(json.dumps(raw))
                    report['netlog_sha256'] = digest(path)
                    report['event_count'] = len(raw['events'])

                # The relocated clean fixture must pass first, so a later
                # rejection cannot be explained by an unrelated path mismatch.
                save()
                self.assertTrue(self.check(report)['passed'])
                kinds = raw['constants']['logEventTypes']
                name = {'tcp_only':'SOCKET_BYTES_SENT', 'tls_only':'SSL_SOCKET_BYTES_SENT',
                        'udp_only':'UDP_BYTES_SENT', 'quic_only':'QUIC_SESSION_PACKET_SENT',
                        'dns_only':'HOST_RESOLVER_MANAGER_REQUEST'}.get(case)
                if case == 'empty_capture':
                    raw['events'] = []
                else:
                    params = {'host':'https://www.google.com:443'} if case == 'dns_only' else {'byte_count':12, 'size':12}
                    raw['events'].append({'type':kinds[name], 'phase':raw['constants']['logEventPhase']['PHASE_BEGIN'],
                                          'time':'1', 'source':{'id':987654, 'type':0, 'start_time':'1'}, 'params':params})
                    if case == 'udp_only':
                        report['sent_event_counts'] = {name:1}
                        report['sent_byte_counts'] = {name:12}
                    elif case == 'quic_only':
                        report['sent_event_counts'] = {name:1}
                    elif case == 'dns_only':
                        report['dns_hosts'] = {'www.google.com':1}
                save()
                with self.assertRaises((AssertionError, KeyError, ValueError)):
                    self.check(report)
        print('Raw non-HTTP/empty-capture negative types: 6')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    REPORT = json.loads(args.report.read_text())
    FRAMEWORK, MANIFEST, PROBE = (REPORT[key] for key in ('framework_sha256', 'manifest_sha256', 'probe_sha256'))
    unittest.main(argv=[__file__])
