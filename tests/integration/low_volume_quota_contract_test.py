"""A claimed low-volume pass needs real mount, cleanup and every public exit."""
import argparse
import copy
import json
from pathlib import Path
import unittest
from low_volume_quota_acceptance import verify


class LowVolumeEvidence(unittest.TestCase):
    def test_actual(self):
        self.assertTrue(verify(REPORT,REPORT['framework_sha256'])['passed'])

    def test_damaged_reports_rejected(self):
        def context(r):return r['observations']['contexts']['firstA']
        def wrong_capacity(sample):
            headroom=(2 if REPORT['privacy']=='balanced' else 10)*1024**3
            sample['quota']=sample['usage']+headroom
        cases={
            'unfinished':lambda r:r.update(completed=False),
            'unclean quit':lambda r:r.update(clean_shutdown=False),
            'volume still mounted':lambda r:r.update(volume_detached=False),
            'not a separate volume':lambda r:r['volume'].update(different_device_from_host=False),
            'large host volume':lambda r:r['volume'].update(total_bytes=200*1024**3),
            'zero volume':lambda r:r['volume'].update(total_bytes=0),
            'engine mismatch':lambda r:r.update(framework_sha256='0'*64),
            'missing contexts':lambda r:r['observations'].update(contexts={}),
            'missing native worker':lambda r:context(r)['workers'].pop('service'),
            'worker raw capacity':lambda r:wrong_capacity(context(r)['workers']['module']['estimate']),
            'legacy API unavailable':lambda r:context(r)['extra']['window']['legacy']['webkitTemporaryStorage'].update(available=False),
            'legacy API denied':lambda r:context(r)['extra']['window']['legacy']['webkitPersistentStorage'].update(error='SecurityError'),
            'implicit bucket exposes capacity':lambda r:wrong_capacity(context(r)['extra']['window']['implicitBucket']),
            'explicit bucket cap overwritten':lambda r:context(r)['extra']['window']['explicitBucket'].update(quota=10*1024**3),
            'missing extra realm':lambda r:context(r)['extra'].pop('dedicated'),
            'worker implicit capacity raw':lambda r:wrong_capacity(context(r)['extra']['dedicated']['implicitBucket']),
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
