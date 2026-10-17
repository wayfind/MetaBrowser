"""Reject bad semantics even when a fixture's raw/summary observations agree."""
import argparse
import copy
import json
from pathlib import Path
import tempfile
import unittest
from opfs_error_acceptance import verify


class ErrorEvidence(unittest.TestCase):
    def test_actual(self):
        self.assertTrue(verify(REPORT,REPORT['framework_sha256'])['passed'])

    def test_semantics_not_only_raw_summary_equality(self):
        def row(r,index=0):return r['observations']['rows'][index]
        cases={
            'quota hidden by producer abort':lambda r:row(r)['write'].update(error='AbortError',message='Failed to write data to data pipe'),
            'blob quota lost':lambda r:row(r,1)['write'].update(error='NotReadableError'),
            'oversized write succeeded':lambda r:row(r)['write'].update(completed=True),
            'wrong failure stage':lambda r:row(r)['write'].update(stage='close'),
            'old interior bytes changed':lambda r:row(r)['retained'].update(sha256='0'*64),
            'old file truncated':lambda r:row(r)['retained'].update(bytes=0),
            'cancel did not complete':lambda r:row(r,3).update(cancelled=False),
            'recovery data corrupted':lambda r:row(r,4)['recovered'].update(sha256='0'*64),
            'wrong deletion error':lambda r:row(r,4).update(write={'completed':False,'error':'SecurityError','stage':'write'}),
            'deletion never settled':lambda r:row(r,4).update(completed=False),
            'worker payload case missing':lambda r:r['observations']['rows'].pop(7),
            'duplicate realm case':lambda r:row(r,5).update(realm='window'),
            'boolean cost':lambda r:r.update(paid_model_calls=False),
        }
        for name,mutate in cases.items():
            with self.subTest(name=name),tempfile.TemporaryDirectory(prefix='metabrowser-opfs-contract-') as temp:
                root=Path(temp)
                (root/'.metabrowser-owned-fixture').write_text('opfs-errors')
                fixture=copy.deepcopy(REPORT);fixture['root']=str(root)
                def persist():
                    (root/'probe-process.private.json').write_text(json.dumps({'exit_code':0,'stdout':json.dumps(fixture['observations']),'stderr':''}))
                persist()
                self.assertTrue(verify(fixture,REPORT['framework_sha256'])['passed'])
                mutate(fixture);persist()
                with self.assertRaises((AssertionError,KeyError,ValueError)):
                    verify(fixture,REPORT['framework_sha256'])
        print('Rejected aligned raw/summary evidence variants:',len(cases))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path)
    args=p.parse_args();REPORT=json.loads(args.report.read_text())
    unittest.main(argv=[__file__])
