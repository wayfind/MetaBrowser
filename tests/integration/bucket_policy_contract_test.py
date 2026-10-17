"""Physical bucket count leakage cannot be hidden behind successful estimates."""
import argparse
import copy
import json
from pathlib import Path
import unittest
from bucket_policy_acceptance import verify


class BucketPolicyEvidence(unittest.TestCase):
    def test_actual(self):
        self.assertTrue(verify(REPORT,REPORT['framework_sha256'])['passed'])

    def test_corruptions_rejected(self):
        def signal(r,realm='window'):return r['observations']['contexts']['firstA']['extra'][realm]
        cases={
            'incomplete':lambda r:r.update(completed=False),
            'unclean quit':lambda r:r.update(clean_shutdown=False),
            'mounted volume':lambda r:r.update(volume_detached=False),
            'not independent volume':lambda r:r['volume'].update(different_device_from_host=False),
            'wrong binary':lambda r:r.update(framework_sha256='0'*64),
            'model calls':lambda r:r.update(paid_model_calls=1),
            'missing contexts':lambda r:r['observations'].update(contexts={}),
            'quota API failed':lambda r:signal(r)['largeQuotas'][0].update(opened=False,error='QuotaExceededError'),
            'large quota capped by private volume':lambda r:signal(r)['largeQuotas'][-1]['estimate'].update(quota=2*1024**3),
            'missing large quota class':lambda r:signal(r)['largeQuotas'].pop(),
            'reopen changed immutable quota':lambda r:signal(r)['reopen']['second'].update(quota=8*1024**2),
            'count silently unlimited':lambda r:signal(r)['count'].update(error=None),
            'wrong count failure':lambda r:signal(r)['count']['failures'][0].update(error='SecurityError'),
            'duplicate successful names':lambda r:signal(r)['count']['created'].append(signal(r)['count']['created'][0]),
            'missing actual keys':lambda r:signal(r)['count'].update(keysAtLimit=[]),
            'cleanup loses original metadata':lambda r:signal(r)['count'].update(afterCleanup=[]),
            'creation never recovers':lambda r:signal(r)['count'].update(creationRecovers=False),
            # Drift from the actual control: 2 GiB is a legitimate off-mode
            # value on this volume and must not be used as its negative case.
            'worker quota drift':lambda r:signal(r,'dedicated')['estimate'].update(quota=signal(r,'dedicated')['estimate']['quota']+1),
            'unknown terminal error':lambda r:r.update(error='unexpected native failure'),
        }
        print('Negative evidence mutations:',len(cases))
        for name,mutate in cases.items():
            with self.subTest(name=name):
                report=copy.deepcopy(REPORT);mutate(report)
                with self.assertRaises((AssertionError,KeyError,ValueError)):
                    verify(report,REPORT['framework_sha256'])


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('report',type=Path)
    args=p.parse_args();REPORT=json.loads(args.report.read_text());assert REPORT['privacy'] in ('balanced','off')
    unittest.main(argv=[__file__])
