"""Regression for a real prefix-migration bug in the native patch staging helper."""
import ast
import copy
from pathlib import Path
import unittest


class StagingMigration(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).resolve().parents[2]/'scripts/stage-privacy-mac.py'
        tree = ast.parse(source.read_text())
        plan = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name == 'make_plan')
        edit = next(n for n in plan.body if isinstance(n,ast.FunctionDef) and n.name == 'edit')
        module = ast.fix_missing_locations(ast.Module(body=[copy.deepcopy(edit)],type_ignores=[]))
        self.state = {'file':'anchor\n'}
        self.globals = {'MARKER':'// METABROWSER_MAC_PRIVACY_V1: ', 'result':self.state,
                        'read':lambda path:self.state[path]}
        exec(compile(module,str(source),'exec'), self.globals)
        self.old = 'owner = [\n  "surface.h",'
        self.new = self.old + '\n  "cpu.h",'

    def edit(self):
        self.globals['edit']('file','anchor',self.new,'owner',previous=self.old)

    def test_prefix_migration_and_repeat(self):
        self.state['file'] = self.globals['MARKER'] + 'owner\n' + self.old + '\n'
        self.edit()
        first = self.state['file']
        self.edit()
        self.assertEqual(self.state['file'],first)
        self.assertEqual(first.count('cpu.h'),1)

    def test_duplicate_current_patch_rejected(self):
        self.edit()
        self.state['file'] *= 2
        with self.assertRaises(ValueError):
            self.edit()

    def test_source_drift_rejected(self):
        self.state['file'] = 'unknown source\n'
        with self.assertRaises(ValueError):
            self.edit()


if __name__ == '__main__':
    unittest.main()
