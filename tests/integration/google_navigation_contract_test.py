import argparse
import copy
import json
from pathlib import Path
import unittest
from google_navigation_acceptance import verify


class NavigationEvidence(unittest.TestCase):
    def test_actual(self):
        self.assertTrue(verify(REPORT,REPORT['framework_sha256'])['passed'])

    def test_inconsistent_evidence(self):
        cases={
            'unfinished':lambda d:d.update(completed=False),
            'unclean exit':lambda d:d.update(clean_shutdown=False),
            'different engine':lambda d:d.update(framework_sha256='0'*64),
            'login submitted':lambda d:d.update(login_submitted=True),
            'real account':lambda d:d.update(real_account_used=True),
            'paid model':lambda d:d.update(paid_model_calls=1),
            'boolean cost':lambda d:d.update(paid_model_calls=False),
            'full privacy overclaim':lambda d:d.update(full_network_privacy_proven=True),
            'lost canary':lambda d:d.update(browser_did_not_delete_test_site_cookie=False),
            'missing Gmail':lambda d:d['pages'].pop('gmail'),
            'invented observation':lambda d:d['pages']['gmail'].update(title='Injected title'),
            'forged raw log hash':lambda d:d.update(netlog_sha256='0'*64),
        }
        for name,mutate in cases.items():
            with self.subTest(name=name):
                damaged=copy.deepcopy(REPORT);mutate(damaged)
                with self.assertRaises((AssertionError,KeyError,ValueError)):
                    verify(damaged,REPORT['framework_sha256'])
        print('Rejected navigation evidence variants:',len(cases))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path)
    args=parser.parse_args();REPORT=json.loads(args.report.read_text())
    unittest.main(argv=[__file__])
