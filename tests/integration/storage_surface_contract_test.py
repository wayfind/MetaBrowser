"""A green storage summary cannot replace real partition/lifecycle evidence."""
import argparse
import copy
import json
from pathlib import Path
import unittest
from storage_surface_acceptance import verify


class StorageEvidence(unittest.TestCase):
    def test_actual_evidence(self):
        self.assertTrue(verify(REPORT, REPORT['framework_sha256'])['passed'])

    def test_damaged_evidence_rejected(self):
        def worker_leak(r):
            r['iterations'][1]['observations']['contexts']['aUnderB']['workers']['shared']['stores']['indexedDB']['value'] = 'first-a'
        def denied_api(r):
            r['iterations'][0]['observations']['contexts']['firstA']['stores']['opfs'] = {'completed': False, 'error': 'SecurityError'}
        def wrong_quota(r):
            r['iterations'][0]['observations']['contexts']['firstA']['workers']['module']['bucketEstimate']['quota'] = 1024
        def missing_worker(r):
            del r['iterations'][0]['observations']['contexts']['bUnderA']['workers']['service']
        def dirty_clear(r):
            r['iterations'][3]['observations']['contexts']['firstB']['stores']['cacheStorage']['value'] = 'first-b'
        cases = {
            'summary without launches': lambda r: r.update(iterations=[]),
            'omitted final restart': lambda r: r['iterations'].pop(),
            'worker crosses partition': worker_leak,
            'API denial disguised as privacy': denied_api,
            'requested bucket quota ignored': wrong_quota,
            'missing service worker': missing_worker,
            'clear did not clear': dirty_clear,
            'reused process': lambda r: r['iterations'][1].update(pid=r['iterations'][0]['pid']),
            'unclean shutdown': lambda r: r['iterations'][0].update(clean_shutdown=False),
            'identity rotated': lambda r: r['iterations'][1].update(root_secret_sha256='0' * 64),
            'profiles share identity': lambda r: r['iterations'][2].update(root_secret_sha256=r['iterations'][0]['root_secret_sha256']),
            'different engine': lambda r: r.update(framework_sha256='0' * 64),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                data = copy.deepcopy(REPORT)
                mutate(data)
                with self.assertRaises((AssertionError, KeyError, ValueError)):
                    verify(data, REPORT['framework_sha256'])


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('report', type=Path)
    args = p.parse_args()
    REPORT = json.loads(args.report.read_text())
    assert REPORT['privacy'] == 'balanced', 'Identity negative tests use the protected fixture'
    unittest.main(argv=[__file__])
