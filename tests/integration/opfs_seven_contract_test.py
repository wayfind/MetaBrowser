"""Aligned raw/summary evidence must still prove each real realm and payload."""
import argparse
import copy
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlsplit
from opfs_seven_acceptance import verify,digest


class SevenRealmEvidence(unittest.TestCase):
    def test_actual_capture(self):
        self.assertTrue(verify(REPORT,REPORT['framework_sha256'])['passed'])

    def test_aligned_raw_semantics_rejected(self):
        def row(r,index=0):return r['observations']['rows'][index]
        cases={
            'quota masked by abort':lambda r:row(r)['write'].update(error='AbortError'),
            'large write succeeded':lambda r:row(r)['write'].update(completed=True),
            'wrong failure stage':lambda r:row(r)['write'].update(stage='close'),
            'buffer was only a view':lambda r:row(r,1)['payload'].update(type='Uint8Array'),
            'offset lost':lambda r:row(r,2)['payload'].update(byteOffset=0),
            'backing buffer not larger':lambda r:row(r,2)['payload'].update(backingBytes=8*1024**2),
            'boolean offset':lambda r:row(r)['payload'].update(byteOffset=False),
            'DataView bounds corrupted':lambda r:row(r,3)['normal'].update(sha256='0'*64),
            'string bytes corrupted':lambda r:row(r,5)['normal'].update(sha256='0'*64),
            'old buffer lost':lambda r:row(r)['retained'].update(sha256='0'*64),
            'cancel did not finish':lambda r:row(r,6).update(cancelled=False),
            'inflight operation hung':lambda r:row(r,7).update(completed=False),
            'unexpected permission denial':lambda r:row(r,7).update(write={'completed':False,'error':'SecurityError','stage':'write'}),
            'recovery failed':lambda r:row(r,7)['recovered'].update(sha256='0'*64),
            'iframe was top-level':lambda r:row(r,8).update(topLevel=True),
            'iframe parameters mismatched':lambda r:row(r,8).update(actualLocation='http://127.0.0.1:18878/opfs-frame.html'),
            'worker was a window':lambda r:row(r,16).update(actualGlobal='Window'),
            'module lacked import.meta':lambda r:row(r,24).update(moduleUrl=None),
            'nested worker lacked parent':lambda r:row(r,32).update(nestedParentLocation=None),
            'shared worker was dedicated':lambda r:row(r,40).update(actualGlobal='DedicatedWorkerGlobalScope'),
            'service worker was dedicated':lambda r:row(r,48).update(actualGlobal='DedicatedWorkerGlobalScope'),
            'service scope mismatched':lambda r:row(r,48).update(serviceScope='http://127.0.0.1:18878/'),
            'missing final case':lambda r:r['observations']['rows'].pop(),
            'duplicate realm':lambda r:row(r,16).update(realm='window'),
            'boolean cost':lambda r:r.update(paid_model_calls=False),
            'paid call':lambda r:r.update(paid_model_calls=1),
        }
        requests=(Path(REPORT['root'])/'fixture-requests.private.json').read_bytes()
        for name,mutate in cases.items():
            with self.subTest(name=name),tempfile.TemporaryDirectory(prefix='metabrowser-opfs-seven-contract-') as temp:
                root=Path(temp);(root/'.metabrowser-owned-fixture').write_text('opfs-errors')
                (root/'fixture-requests.private.json').write_bytes(requests)
                fixture=copy.deepcopy(REPORT);fixture['root']=str(root)
                def persist():
                    (root/'probe-process.private.json').write_text(json.dumps({'exit_code':0,'stdout':json.dumps(fixture['observations']),'stderr':''}))
                persist();self.assertTrue(verify(fixture,REPORT['framework_sha256'])['passed'])
                mutate(fixture);persist()
                with self.assertRaises((AssertionError,KeyError,ValueError)):
                    verify(fixture,REPORT['framework_sha256'])
        print('Rejected aligned raw/summary variants:',len(cases))

    def test_worker_request_provenance(self):
        paths=['/opfs-module.js','/opfs-nested.js','/opfs-shared.js','/opfs-service.js']
        requests=json.loads((Path(REPORT['root'])/'fixture-requests.private.json').read_text())
        for path in paths:
            with self.subTest(path=path),tempfile.TemporaryDirectory(prefix='metabrowser-opfs-request-contract-') as temp:
                root=Path(temp);(root/'.metabrowser-owned-fixture').write_text('opfs-errors')
                fixture=copy.deepcopy(REPORT);fixture['root']=str(root)
                (root/'probe-process.private.json').write_text(json.dumps({'exit_code':0,'stdout':json.dumps(fixture['observations']),'stderr':''}))
                raw=root/'fixture-requests.private.json';raw.write_text(json.dumps(requests));fixture['fixture_requests_sha256']=digest(raw)
                self.assertTrue(verify(fixture,REPORT['framework_sha256'])['passed'])
                raw.write_text(json.dumps([p for p in requests if urlsplit(p).path!=path]));fixture['fixture_requests_sha256']=digest(raw)
                with self.assertRaises(AssertionError):verify(fixture,REPORT['framework_sha256'])
        print('Rejected missing worker-source request variants:',len(paths))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path)
    args=p.parse_args();REPORT=json.loads(args.report.read_text());unittest.main(argv=[__file__])
