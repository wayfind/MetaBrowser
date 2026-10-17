"""Bounded TLS vector parsing and independent capture-integrity checks."""
import argparse
import base64
import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest
from tls_transport_capture import grease, parse_client_hello,parse_http1_request
from tls_transport_acceptance import verify
from identity_surface_runner import digest


def vector(data, prefix=2):
    return len(data).to_bytes(prefix,'big')+data


def sample(extension_order=None):
    extensions={10:vector(bytes.fromhex('0a0a001d')),11:vector(b'\0',1),
                13:vector(bytes.fromhex('08040403')),16:vector(vector(b'h2',1)+vector(b'http/1.1',1)),
                43:vector(bytes.fromhex('0a0a0304'),1),
                51:vector(bytes.fromhex('0a0a')+vector(b'x')+bytes.fromhex('001d')+vector(b'x'*32)),
                0x0a0a:b''}
    order=extension_order or list(extensions)
    payload=b''.join(struct.pack('!H',k)+vector(extensions[k]) for k in order)
    hello=bytes.fromhex('0303')+b'x'*32+vector(b'',1)+vector(bytes.fromhex('0a0a13011302'))+vector(b'\0',1)+vector(payload)
    return b'\1'+vector(hello,3)


class HelloParsing(unittest.TestCase):
    def test_known_vectors_and_order_independent_comparison(self):
        result=parse_client_hello(sample())
        self.assertEqual(result['ja3_string'],'771,4865-4866,10-11-13-16-43-51,29,0')
        self.assertEqual(result['normalized']['key_shares'],[{'group':29,'bytes':32}])
        reordered=parse_client_hello(sample([51,43,16,13,11,10,0x0a0a]))
        self.assertEqual(result['normalized'],reordered['normalized'])
        self.assertNotEqual(result['ja3_md5'],reordered['ja3_md5'])

    def test_all_grease_values_only(self):
        self.assertEqual([n for n in range(65536) if grease(n)],list(range(0x0a0a,0xffff,0x1010)))

    def test_every_truncation_rejected(self):
        wire=sample()
        for length in range(len(wire)):
            with self.subTest(length=length),self.assertRaises(ValueError):
                parse_client_hello(wire[:length])

    def test_trailing_and_duplicate_extensions_rejected(self):
        with self.assertRaises(ValueError):parse_client_hello(sample()+b'x')
        with self.assertRaises(ValueError):parse_client_hello(sample([10,10]))


class Http1Parsing(unittest.TestCase):
    def test_order_and_case_preserved(self):
        wire=b'GET /owned-transport HTTP/1.1\r\nHost: example.test\r\nsec-ch-ua: test\r\nUser-Agent: owned\r\n\r\n'
        parsed=parse_http1_request(wire)
        self.assertEqual(parsed['headers'],[['Host','example.test'],['sec-ch-ua','test'],['User-Agent','owned']])
        for i in range(len(wire)):
            with self.subTest(length=i),self.assertRaises(ValueError):parse_http1_request(wire[:i])

    def test_malformed_and_unbounded_headers(self):
        for wire in (b'POST / HTTP/1.1\r\n\r\n',b'GET / HTTP/1.1\r\n folded: value\r\n\r\n',
                     b'GET / HTTP/1.1\r\nBad Name: value\r\n\r\n',b'GET / HTTP/1.1\r\nMissingColon\r\n\r\n',
                     b'GET / HTTP/1.1\r\nLarge: '+b'x'*65536+b'\r\n\r\n'):
            with self.subTest(length=len(wire)),self.assertRaises(ValueError):parse_http1_request(wire)


class CaptureEvidence(unittest.TestCase):
    def test_actual(self):
        if REPORT is None:self.skipTest('No native capture supplied')
        self.assertTrue(verify(REPORT,REPORT['framework_sha256'])['passed'])

    def test_inconsistent_report_rejected(self):
        if REPORT is None:self.skipTest('No native capture supplied')
        cases={
            'unfinished':lambda r:r.update(completed=False),
            'unclean exit':lambda r:r.update(clean_shutdown=False),
            'wrong framework':lambda r:r.update(framework_sha256='0'*64),
            'boolean cost':lambda r:r.update(paid_model_calls=False),
            'paid calls':lambda r:r.update(paid_model_calls=1),
            'full privacy overclaim':lambda r:r.update(full_network_privacy_proven=True),
            'official parity overclaim':lambda r:r.update(official_release_parity_proven=True),
            'HTTP3 overclaim':lambda r:r.update(http3_proven=True),
            'header order overclaim':lambda r:r.update(decoded_header_order_proven=True),
            'missing raw trace':lambda r:r.update(connections=[]),
            'raw hash changed':lambda r:r.update(endpoint_capture_sha256='0'*64),
            'certificate checking disabled':lambda r:r['command'].append('--ignore-certificate-errors'),
        }
        for name,mutate in cases.items():
            with self.subTest(name=name):
                damaged=copy.deepcopy(REPORT);mutate(damaged)
                with self.assertRaises((AssertionError,KeyError,ValueError)):
                    verify(damaged,REPORT['framework_sha256'])
        print('Rejected transport evidence variants:',len(cases))


class Http1RawEvidence(unittest.TestCase):
    def test_aligned_trace_cannot_forge_decoded_headers(self):
        if REPORT is None or REPORT.get('protocol')!='http/1.1':self.skipTest('No native HTTP1 capture supplied')
        original=Path(REPORT['root'])
        for case in ('decoded_order_forged','host_changed','credentials_added','navigation_missing'):
            with self.subTest(case=case),tempfile.TemporaryDirectory(prefix='metabrowser-http1-contract-') as temp:
                root=Path(temp).resolve();(root/'.metabrowser-owned-fixture').write_text('tls-transport')
                for name in ('server.crt','probe-process.private.json'):(root/name).write_bytes((original/name).read_bytes())
                fixture=copy.deepcopy(REPORT);fixture['root']=str(root)
                fixture['command']=['--user-data-dir='+str(root/'browser') if s.startswith('--user-data-dir=') else s for s in fixture['command']]
                path=root/'endpoint-capture.private.json'
                def persist():
                    path.write_text(json.dumps(fixture['connections']));fixture['endpoint_capture_sha256']=digest(path)
                persist();self.assertTrue(verify(fixture,REPORT['framework_sha256'])['passed'])
                main=next(r for r in fixture['connections'] if r.get('http1_request',{}).get('path')=='/owned-transport')
                wire=base64.b64decode(main['http1_request_b64'])
                if case=='decoded_order_forged':main['http1_request']['headers'].reverse()
                else:
                    if case=='host_changed':wire=wire.replace(b'Host: transport.metabrowser.test:18912',b'Host: unrelated.test')
                    elif case=='credentials_added':wire=wire[:-2]+b'Authorization: owned-fake-canary\r\n\r\n'
                    else:wire=wire.replace(b'GET /owned-transport ',b'GET /unrelated ')
                    main['http1_request_b64']=base64.b64encode(wire).decode();main['http1_request']=parse_http1_request(wire)
                persist()
                with self.assertRaises((AssertionError,KeyError,ValueError)):verify(fixture,REPORT['framework_sha256'])
        print('Rejected aligned HTTP1 raw/decoded variants: 4')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report',type=Path)
    args=p.parse_args();REPORT=json.loads(args.report.read_text()) if args.report else None
    unittest.main(argv=[__file__])
