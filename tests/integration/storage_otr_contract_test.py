"""A green storage summary cannot replace real partition/lifecycle evidence."""
import argparse
import copy
import json
from pathlib import Path
import unittest
from storage_otr_acceptance import verify


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
            'different engine': lambda r: r.update(framework_sha256='0' * 64),
        }
        cases['regular context disguised as private'] = lambda r: r['iterations'][0]['observations'].update(browserContextId=r['iterations'][0]['observations']['regularBrowserContextId'])
        cases['unverified context'] = lambda r: r['iterations'][0]['observations'].update(nonDefaultBrowserContext=False)
        cases['private restart retained canary'] = lambda r: r['iterations'][1]['observations']['contexts']['firstA']['stores']['indexedDB'].update(value='first-a')
        def corrupt_sample(r, realm, phase, field, replacement):
            sample = r['iterations'][0]['observations']['contexts']['firstA']['mutationTrace'][realm][phase]
            if field == 'quota': sample['bucketEstimate']['quota'] = replacement
            elif field == 'operation': sample['operation'] = replacement
            else: sample['stores'][field]['value'] = replacement
        for realm in ('dedicated', 'shared', 'service', 'module', 'nested'):
            cases[realm + ' write not visible in window'] = lambda r, realm=realm: corrupt_sample(r, realm, 'windowAfterWrite', 'indexedDB', None)
            cases[realm + ' delete did not clear'] = lambda r, realm=realm: corrupt_sample(r, realm, 'windowAfterDelete', 'opfs', 'stale')
            cases[realm + ' write silently read'] = lambda r, realm=realm: corrupt_sample(r, realm, 'write', 'operation', 'read')
            cases[realm + ' mutation quota drift'] = lambda r, realm=realm: corrupt_sample(r, realm, 'write', 'quota', 1024)
        print('Checking negative evidence mutations:', len(cases))
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
