"""Reject semantically invalid persona evidence even when raw and summary agree."""
import argparse
import copy
import json
from pathlib import Path
import tempfile
import unittest
from persona_metadata_acceptance import verify


class PersonaEvidence(unittest.TestCase):
    def test_capture(self):
        self.assertTrue(verify(REPORT, REPORT['framework_sha256'])['passed'])

    def test_aligned_invalid_semantics(self):
        def extra(r): return r['observations']['extraRealms']
        def trace(r): return r['observations']['cpuTrace']
        mutations = {
            'module not actual worker': lambda r: extra(r)['module'].update(actualGlobal='Window'),
            'nested missing parent': lambda r: extra(r)['nested'].update(nestedParentGlobal=None),
            'nested metadata host fallback': lambda r: extra(r)['nested'].update(platform='MacIntel'),
            'module lacks import meta': lambda r: extra(r)['module'].update(moduleUrl=None),
            'module getter not native': lambda r: extra(r)['module'].update(platformNative=False),
            'retained platform host fallback': lambda r: trace(r)[0]['observed']['retained'].update(platform='MacIntel'),
            'retained Apple CPU tier': lambda r: trace(r)[0]['observed']['retained'].update(tier=4),
            'iframe core override ignored': lambda r: trace(r)[1]['observed']['iframe'].update(cores=8),
            'native getter overwritten': lambda r: r['observations']['nativePersonaGetters'].update(deviceMemory=False),
            'full persona falsely complete': lambda r: r.update(full_emulated_persona_proven=True),
            'boolean model cost': lambda r: r.update(paid_model_calls=False),
            'paid model call': lambda r: r.update(paid_model_calls=1),
            'custom UA conflict': lambda r: r['command'].append('--user-agent=owned-invalid'),
            'backend omitted': lambda r: r['command'].remove('--use-webgpu-adapter=swiftshader'),
            'actual host GPU backend': lambda r: r['observations']['nativeGpuInfo']['auxAttributes'].update(glRenderer='ANGLE (Apple, Apple M1, Metal)'),
            'missing actual GPU device': lambda r: r['observations']['nativeGpuInfo'].update(devices=[]),
            'boolean single core': lambda r: trace(r)[2]['observed']['iframe'].update(cores=True),
            'boolean CPU tier': lambda r: trace(r)[2]['observed']['retained'].update(tier=True),
        }
        assert REPORT['persona'] == 'linux-x86_64-software-v1'
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix='metabrowser-persona-contract-') as temp:
                root = Path(temp).resolve()
                (root/'.metabrowser-owned-fixture').write_text('persona-metadata')
                r = copy.deepcopy(REPORT)
                r['command'] = ['--user-data-dir='+str(root/'browser') if s.startswith('--user-data-dir=') else s for s in r['command']]
                r['root'] = str(root)
                def persist():
                    (root/'probe-process.private.json').write_text(json.dumps({'exit_code':0,'stdout':json.dumps(r['observations']),'stderr':''}))
                persist()
                self.assertTrue(verify(r, REPORT['framework_sha256'])['passed'])
                mutate(r); persist()
                with self.assertRaises((AssertionError, KeyError, ValueError)):
                    verify(r, REPORT['framework_sha256'])
        print('Rejected aligned semantic variants:', len(mutations))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('report', type=Path)
    a = p.parse_args(); REPORT = json.loads(a.report.read_text())
    unittest.main(argv=[__file__])
