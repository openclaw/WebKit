#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).parent / 'qualification'


def module(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FaithfulnessTests(unittest.TestCase):
    def compare(self, left, right):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, rows in [('a', left), ('b', right)]:
                arm = root / name
                arm.mkdir()
                (arm / 'selected.json').write_text('["case.ts"]')
                (arm / 'results.json').write_text(json.dumps(rows))
            proc = subprocess.run([sys.executable, str(HERE / 'compare-fork-ci.py'), str(root/'a'),
                                   str(root/'b'), '--output', str(root/'result.json')], capture_output=True)
            return proc.returncode, json.loads((root/'result.json').read_text())

    @staticmethod
    def row(**kw):
        return dict(testPath='case.ts', ok=True, status='pass', exitCode=0, signalCode=None, **kw)

    def test_equal_pass(self):
        code, data = self.compare([self.row()], [self.row()])
        self.assertEqual(code, 0)
        self.assertTrue(data['all_passed'])

    def test_equal_failures_are_not_green(self):
        row = self.row()
        row.update(ok=False, status='fail', exitCode=1)
        code, data = self.compare([row], [row])
        self.assertNotEqual(code, 0)
        self.assertFalse(data['all_passed'])

    def test_candidate_failure_is_not_hidden(self):
        row = self.row()
        row.update(ok=False, status='fail', exitCode=1)
        code, data = self.compare([self.row()], [row])
        self.assertNotEqual(code, 0)
        self.assertFalse(data['all_passed'])

    def test_signal_is_not_green(self):
        row = self.row()
        row.update(signalCode='SIGABRT')
        code, data = self.compare([row], [row])
        self.assertNotEqual(code, 0)
        self.assertFalse(data['all_passed'])

    def test_capture_contract_is_exact(self):
        mod = module('stage-fork-ci')
        with self.assertRaises(ValueError):
            mod.replace_once('duplicate duplicate', 'duplicate', 'changed')
        with self.assertRaises(ValueError):
            mod.replace_once('missing', 'old', 'changed')
        self.assertEqual(mod.replace_once('a old b', 'old', 'new'), 'a new b')

    def test_collect_nested_cases_and_skips(self):
        mod = module('collect-fork-outcomes')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'selected.json').write_text('["case.ts"]')
            (root/'batch.xml').write_text('''<testsuites><testsuite file="case.ts"><testsuite file="case.ts">
              <testcase name="passes"/><testcase name="skips"><skipped/></testcase>
              <testcase name="pending"><skipped type="todo"/></testcase>
              </testsuite></testsuite></testsuites>''')
            cases = mod.collect(root)['case.ts']
            self.assertEqual([x['status'] for x in cases], ['pass', 'skipped', 'todo'])
            self.assertEqual([x['name'] for x in cases], ['passes', 'skips', 'pending'])

    def test_collect_rejects_missing_and_failed_cases(self):
        mod = module('collect-fork-outcomes')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'selected.json').write_text('["case.ts"]')
            with self.assertRaises(ValueError):
                mod.collect(root)
            (root/'batch.xml').write_text('''<testsuite file="case.ts"><testcase name="broken"><failure/></testcase></testsuite>''')
            with self.assertRaises(ValueError):
                mod.collect(root)


if __name__ == '__main__':
    unittest.main()
