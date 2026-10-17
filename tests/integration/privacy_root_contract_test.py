"""Reject damaged root-recovery evidence without modifying raw artifacts."""
import argparse
import copy
import json
from pathlib import Path
import unittest
from privacy_root_acceptance import verify


class RootEvidence(unittest.TestCase):
    def test_real_evidence(self):
        self.assertTrue(verify(REPORT, REPORT['framework_sha256'])['passed'])

    def test_corrupted_summaries_rejected(self):
        def missing_case(r):
            del r['cases']['json_parse']
        mutations = {
            'counter only': lambda r: r.update(cases={}),
            'missing whole-file branch': missing_case,
            'site contacted': lambda r: r['cases']['base64']['blocked_requests'].append('/base64/blocked'),
            'no restoration navigation': lambda r: r['cases']['json_type'].update(restored_requests=[]),
            'changed error image': lambda r: r['cases']['empty'].update(dialog_image_sha256='0' * 64),
            'changed input': lambda r: r['cases']['short'].update(rejected_input_sha256='0' * 64),
            'different engine': lambda r: r.update(framework_sha256='0' * 64),
            'unfinished': lambda r: r.update(completed=False),
            'watchdog exit disguised as clean': lambda r: r['cases']['short'].update(rejected_exit_code=-15),
            'picker never ready': lambda r: r['cases']['empty'].update(rejected_profile_picker_ready=False),
        }
        if 'rejection_launches' in REPORT:
            mutations.update({
                'invalid repeat count': lambda r: r.update(rejection_launches=0),
                'boolean repeat count': lambda r: r.update(rejection_launches=True),
                'missing rejection attempt': lambda r: r['cases']['base64']['rejection_attempts'].pop(),
                'changed rejection prefix': lambda r: r['cases']['base64']['rejection_attempts'][0].update(artifact_prefix='../other'),
                'repeat crash concealed': lambda r: r['cases']['base64']['rejection_attempts'][0].update(exit_code=-6),
                'repeat site contact concealed': lambda r: r['cases']['base64']['rejection_attempts'][0].update(blocked_requests=['/base64/blocked']),
                'repeat picker absent': lambda r: r['cases']['base64']['rejection_attempts'][0].update(picker_ready=False),
                'repeat dialog forged': lambda r: r['cases']['base64']['rejection_attempts'][0].update(dialog_text_sha256='0' * 64),
            })
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                r = copy.deepcopy(REPORT)
                mutate(r)
                with self.assertRaises((AssertionError, KeyError, ValueError)):
                    verify(r, REPORT['framework_sha256'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    REPORT = json.loads(args.report.read_text())
    unittest.main(argv=[__file__])
