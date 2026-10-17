"""Reject incomplete configuration controls and malformed CPU observations."""
import argparse
import copy
import json
from pathlib import Path
import unittest
from privacy_configuration_acceptance import verify


class ConfigurationEvidence(unittest.TestCase):
    def test_actual_capture(self):
        self.assertTrue(verify(REPORT, FRAMEWORK)['passed'])

    def test_corruptions_rejected(self):
        def observed(report):
            return report['modes']['protected']['observations']

        cases = {
            'unfinished': lambda r: r.update(completed=False),
            'engine mismatch': lambda r: r.update(framework_sha256='0'*64),
            'paid calls': lambda r: r.update(paid_model_calls=1),
            'boolean cost': lambda r: r.update(paid_model_calls=False),
            'full privacy overclaim': lambda r: r.update(full_privacy_proven=True),
            'missing control': lambda r: r['modes'].pop('cpu_enabled_off'),
            'missing worker': lambda r: observed(r)['realms'].pop('shared'),
            'wrong core count': lambda r: observed(r)['realms']['window'].update(hardwareConcurrency=4),
            'boolean core count': lambda r: observed(r)['realms']['window'].update(hardwareConcurrency=True),
            'boolean CPU tier': lambda r: observed(r)['realms']['window']['cpuPerformance'].update(value=True),
            'invented worker CPU API': lambda r: observed(r)['realms']['service'].update(cpuPerformance={'present':True,'value':4}),
            'retained CPU changed': lambda r: observed(r)['retainedCPU'].update(after={'hardwareConcurrency':4,'cpuPerformance':2}),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                damaged = copy.deepcopy(REPORT)
                mutate(damaged)
                with self.assertRaises((AssertionError, KeyError, ValueError)):
                    verify(damaged, FRAMEWORK)
        print('Rejected configuration evidence variants:', len(cases))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    REPORT = json.loads(args.report.read_text())
    FRAMEWORK = REPORT['framework_sha256']
    unittest.main(argv=[__file__])
