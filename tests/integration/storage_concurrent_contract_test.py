"""Reject forged or incomplete simultaneous-context isolation evidence."""
import argparse
import copy
import json
from pathlib import Path
import unittest
from storage_concurrent_acceptance import verify


class ConcurrentEvidence(unittest.TestCase):
    def test_actual_evidence(self):
        self.assertTrue(verify(REPORT, REPORT['framework_sha256'])['passed'])

    def test_corruptions_rejected(self):
        def raw(report):
            return report['observations']

        def sample(report, index):
            return raw(report)['records'][index]

        def value(report, index, new):
            sample(report,index)['contexts']['firstA']['stores']['indexedDB']['value'] = new

        def worker_value(report):
            sample(report,1)['contexts']['firstA']['workers']['shared']['stores']['indexedDB']['value'] = 'regular:first-a'

        def mutation_value(report):
            sample(report,2)['contexts']['firstA']['mutationTrace']['service']['windowAfterDelete']['stores']['opfs']['value'] = 'private:first-a'

        def quota_drift(report):
            sample(report,2)['contexts']['firstA']['mutationTrace']['module']['write']['bucketEstimate']['quota'] = 1024

        cases = {
            'unfinished':lambda r:r.update(completed=False),
            'unclean shutdown':lambda r:r.update(clean_shutdown=False),
            'engine mismatch':lambda r:r.update(framework_sha256='0'*64),
            'model call':lambda r:r.update(paid_model_calls=1),
            'boolean cost':lambda r:r.update(paid_model_calls=False),
            'missing samples':lambda r:raw(r).update(records=[]),
            'omitted disposal read':lambda r:raw(r)['records'].pop(),
            'wrong phase':lambda r:sample(r,1).update(name='regular_seed'),
            'same regular and private ID':lambda r:raw(r).update(firstPrivateContextId=raw(r)['regularBrowserContextId']),
            'reused private context':lambda r:raw(r).update(secondPrivateContextId=raw(r)['firstPrivateContextId']),
            'private page actually regular':lambda r:sample(r,1).update(browserContextId=raw(r)['regularBrowserContextId']),
            'private target actually regular':lambda r:sample(r,1).update(targetId=sample(r,0)['targetId']),
            'different regular target':lambda r:sample(r,3).update(targetId='other-target'),
            'disposal not verified':lambda r:raw(r).update(disposedFirstContextHasNoTargets=False),
            'private initially sees regular value':lambda r:value(r,1,'regular:first-a'),
            'regular overwritten by private':lambda r:value(r,3,'private:first-a'),
            'regular clear clears private':lambda r:value(r,5,None),
            'private clear clears regular':lambda r:value(r,8,None),
            'private disposal loses regular':lambda r:value(r,11,None),
            'private data survives disposal':lambda r:value(r,10,'private:first-a'),
            'worker crosses profile':worker_value,
            'worker delete did not clear':mutation_value,
            'mutation quota drift':quota_drift,
            'missing native worker':lambda r:sample(r,1)['contexts']['firstA']['workers'].pop('nested'),
            'API denial':lambda r:sample(r,2)['contexts']['firstA']['stores']['opfs'].update(completed=False,error='SecurityError'),
            'wrong origin':lambda r:sample(r,0)['contexts']['firstA'].update(origin='http://localhost:18878'),
        }
        print('Negative evidence mutations:',len(cases))
        for name, mutate in cases.items():
            with self.subTest(name=name):
                report = copy.deepcopy(REPORT)
                mutate(report)
                with self.assertRaises((AssertionError,KeyError,ValueError)):
                    verify(report, REPORT['framework_sha256'])


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('report',type=Path)
    args=p.parse_args()
    REPORT=json.loads(args.report.read_text())
    unittest.main(argv=[__file__])
