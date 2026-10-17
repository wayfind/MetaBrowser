"""Damaged catalogs must not become coverage evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('idl_audit', ROOT / 'scripts/audit-privacy-idl.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class InventoryEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((ROOT / 'out/evidence/idl-v18b-catalog-bound.private.json').read_text())
        cls.raw = (ROOT / 'out/evidence/identity-v18b-build-receipt.json').read_bytes()
        cls.receipt = json.loads(cls.raw)

    def test_intact_inventory_is_not_coverage(self):
        r = audit.audit(self.catalog, self.receipt, self.raw)
        self.assertTrue(r['inventory_integrity_passed'], r['errors'])
        self.assertFalse(r['privacy_coverage_proven'])
        self.assertEqual(r['unreviewed_members'], len(self.catalog['members']))
        self.assertGreater(r['conditional_member_count'], 0)

    def test_damaged_catalogs_rejected(self):
        def missing_source(c):
            del c['source_sha256'][c['members'][0]['source']]
        cases = {
            'different engine': lambda c: c.update(framework_sha256='0' * 64),
            'different receipt': lambda c: c.update(build_receipt_sha256='0' * 64),
            'omitted member': lambda c: c['members'].pop(),
            'duplicate member': lambda c: c['members'].append(copy.deepcopy(c['members'][0])),
            'missing generated source': missing_source,
            'changed condition': lambda c: c['members'][0]['exposure'].update(secure_context=True),
            'unbound owner': lambda c: c['members'][0].update(owner='MissingOwner'),
            'fabricated pass': lambda c: c['members'][0].update(review_status='verified'),
            'inventory becomes protection': lambda c: c.update(privacy_coverage_proven=True),
        }
        for name, change in cases.items():
            with self.subTest(name=name):
                c = copy.deepcopy(self.catalog)
                change(c)
                self.assertFalse(audit.audit(c, self.receipt, self.raw)['inventory_integrity_passed'])


if __name__ == '__main__':
    unittest.main()
