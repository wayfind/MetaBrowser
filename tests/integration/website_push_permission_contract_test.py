"""Replay real native captures; reject timeout and broken restart evidence."""
import argparse
import copy
import json
from pathlib import Path
import unittest

from website_push_permission_acceptance import digest, verify, verify_restore


class PushEvidence(unittest.TestCase):
    def test_actual_permission_and_restart(self):
        for report in (DENIED, SEED, RESTORED):
            self.assertTrue(verify(report, FRAMEWORK)['passed'])
        self.assertTrue(verify_restore(SEED, RESTORED, FRAMEWORK, SEED_SHA)['passed'])

    def test_actual_timeout_is_not_success(self):
        self.assertEqual(PENDING['observations']['result']['outcome']['kind'], 'pending_after_30s')
        with self.assertRaises(AssertionError):
            verify(PENDING, FRAMEWORK)

    def test_report_corruptions(self):
        cases = {
            'unfinished': lambda r: r.update(completed=False),
            'unclean shutdown': lambda r: r.update(clean_shutdown=False),
            'different engine': lambda r: r.update(framework_sha256='0'*64),
            'paid calls': lambda r: r.update(paid_model_calls=1),
            'boolean cost': lambda r: r.update(paid_model_calls=False),
            'message sent': lambda r: r.update(messages_sent=1),
            'full privacy overclaim': lambda r: r.update(full_network_privacy_proven=True),
            'forged opt-in': lambda r: r.update(google_services_control=True),
            'integer opt-in': lambda r: r.update(google_services_control=0),
            'permission replaced': lambda r: r.update(permission='denied'),
            'lost permission persistence': lambda r: r.update(persisted_permission=False),
            'subscription cleanup lost': lambda r: r.update(keep_subscription=True),
            'netlog replaced': lambda r: r.update(netlog_sha256='0'*64),
            'restore digest malformed': lambda r: r.update(restored_report_sha256='wrong'),
            'restored subscription lost': lambda r: r.update(restored_subscription_matches=False),
            'browser identity lost': lambda r: r.update(existing_identity_preserved=False),
            'invented probe observation': lambda r: r['observations']['result'].update(was_existing=False),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                damaged = copy.deepcopy(RESTORED)
                mutate(damaged)
                with self.assertRaises((AssertionError, KeyError, ValueError)):
                    verify(damaged, FRAMEWORK)
        print('Rejected push report variants:', len(cases))

    def test_restart_pair_bindings(self):
        cases = {
            'different profile': lambda r: r.update(profile_root=r['profile_root']+'/different'),
            'same capture root': lambda r: r.update(root=SEED['root']),
            'same browser process': lambda r: r.update(pid=SEED['pid']),
            'wrong predecessor digest': lambda r: r.update(restored_report_sha256='0'*64),
        }
        for name, mutate in cases.items():
            with self.subTest(name=name):
                damaged = copy.deepcopy(RESTORED)
                mutate(damaged)
                with self.assertRaises((AssertionError, KeyError, ValueError)):
                    verify_restore(SEED, damaged, FRAMEWORK, SEED_SHA)
        print('Rejected restart pair variants:', len(cases))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('denied', 'pending', 'seed', 'restored'):
        parser.add_argument('--'+name, required=True, type=Path)
    args = parser.parse_args()
    DENIED, PENDING, SEED, RESTORED = (json.loads(getattr(args, name).read_text())
                                    for name in ('denied', 'pending', 'seed', 'restored'))
    FRAMEWORK = SEED['framework_sha256']
    SEED_SHA = digest(args.seed)
    unittest.main(argv=[__file__])
