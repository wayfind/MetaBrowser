"""Negative acceptance cases for GPU/media evidence completeness."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from gpu_media_runner import CONTROL_CHECKS, EXTENDED_CHECKS, REQUIRED_CHECKS, validate_probe, write_report


class EvidenceContractTest(unittest.TestCase):
    def setUp(self):
        self.valid = {'checks': dict.fromkeys(REQUIRED_CHECKS, True),
                      'details': {key: {} for key in REQUIRED_CHECKS},
                      'passed': True, 'paid_model_calls': 0}

    def test_complete_success_and_honest_failure(self):
        validate_probe(self.valid)
        self.valid['checks']['webgpu'] = False
        self.valid['passed'] = False
        validate_probe(self.valid)

    def test_incomplete_and_extra_evidence_rejected(self):
        for field in ('checks', 'details'):
            for mutation in ('missing', 'extra', 'empty'):
                with self.subTest(field=field, mutation=mutation):
                    value = copy.deepcopy(self.valid)
                    if mutation == 'missing':
                        value[field].pop('webgpu')
                    elif mutation == 'extra':
                        value[field]['unknown'] = True
                    else:
                        value[field] = {}
                    with self.assertRaises(ValueError):
                        validate_probe(value)

    def test_truthy_non_booleans_rejected(self):
        for item in (1, 'true', [], None):
            value = copy.deepcopy(self.valid)
            value['checks']['webgpu'] = item
            with self.assertRaises(ValueError):
                validate_probe(value)

    def test_contradictory_pass_rejected(self):
        self.valid['checks']['webgpu'] = False
        with self.assertRaises(ValueError):
            validate_probe(self.valid)

    def test_paid_calls_rejected(self):
        for item in (1, False, '0', None):
            self.valid['paid_model_calls'] = item
            with self.assertRaises(ValueError):
                validate_probe(self.valid)

    def test_extended_run_requires_all_additional_checks(self):
        with self.assertRaises(ValueError):
            validate_probe(self.valid, extended=True)
        for name in EXTENDED_CHECKS:
            self.valid['checks'][name] = True
            self.valid['details'][name] = {}
        validate_probe(self.valid, extended=True)
        with self.assertRaises(ValueError):
            validate_probe(self.valid)
        for name in EXTENDED_CHECKS:
            value = copy.deepcopy(self.valid)
            value['checks'].pop(name)
            with self.assertRaises(ValueError):
                validate_probe(value, extended=True)

    def test_control_evidence_cannot_replace_full_matrix(self):
        value = {'checks': dict.fromkeys(CONTROL_CHECKS, True),
                 'details': {key: {} for key in CONTROL_CHECKS},
                 'passed': True, 'paid_model_calls': 0}
        validate_probe(value, control=True)
        with self.assertRaises(ValueError):
            validate_probe(value, extended=True)
        value['checks'].pop('retained_gpu_policy')
        with self.assertRaises(ValueError):
            validate_probe(value, control=True)

    def test_atomic_private_report_replaces_symlink_without_touching_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'keep.json'
            target.write_text('keep')
            output = root / 'report.json'
            output.symlink_to(target)
            write_report(output, self.valid)
            self.assertEqual(target.read_text(), 'keep')
            self.assertFalse(output.is_symlink())
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(output.read_text()), self.valid)
            self.assertEqual(len(list(root.iterdir())), 2)


if __name__ == '__main__':
    unittest.main()
