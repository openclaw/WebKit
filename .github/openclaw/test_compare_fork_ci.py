#!/usr/bin/env python3
"""Exercise the comparator CLI with complete, contradictory, and incomplete evidence."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).parent / 'qualification' / 'compare-fork-ci.py'
SELECTED = ['test/a.test.ts', 'test/b.test.ts']
ROWS = [{'testPath': name, 'ok': True, 'status': 'pass'}
        for name in [*SELECTED, 'package.json', 'test/package.json']]

class CompareForkCI(unittest.TestCase):
    def compare(self, left=None, right=None, selection=None, right_selection=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for label, rows in (('baseline', ROWS if left is None else left),
                                ('candidate', ROWS if right is None else right)):
                arm = root / label
                arm.mkdir()
                chosen = SELECTED if selection is None else selection
                if label == 'candidate' and right_selection is not None:
                    chosen = right_selection
                (arm / 'selected.json').write_text(json.dumps(chosen))
                (arm / 'results.json').write_text(json.dumps(rows))
            output = root / 'comparison.json'
            run = subprocess.run([sys.executable, str(SCRIPT), str(root / 'baseline'),
                                  str(root / 'candidate'), '--output', str(output)],
                                 capture_output=True, text=True, timeout=10)
            self.assertEqual(run.stderr, '')
            return run.returncode, json.loads(output.read_text())

    def test_equal_complete_passes(self):
        code, report = self.compare()
        self.assertEqual(code, 0)
        self.assertTrue(report['identical_file_outcomes'])
        self.assertTrue(report['all_passed'])
        self.assertEqual(report['additional_runner_results'], ['package.json', 'test/package.json'])

    def test_each_arm_and_identical_failures_stay_red(self):
        failed = copy.deepcopy(ROWS)
        failed[0].update(ok=False, status='fail', error='first grouped attempt failed')
        for left, right in ((failed, ROWS), (ROWS, failed), (failed, failed)):
            with self.subTest(left_failed=left is failed, right_failed=right is failed):
                code, report = self.compare(left, right)
                self.assertEqual(code, 1)
                self.assertFalse(report['all_passed'])
                self.assertEqual(report['baseline_all_passed'], left is ROWS)
                self.assertEqual(report['candidate_all_passed'], right is ROWS)
                self.assertEqual(report['identical_file_outcomes'], left is right)

    def test_optional_exit_metadata_is_not_normalized(self):
        serial = copy.deepcopy(ROWS)
        serial[0].update(exitCode=0, signalCode=None)
        code, report = self.compare(serial, ROWS)
        self.assertEqual(code, 1)
        self.assertTrue(report['all_passed'])
        self.assertFalse(report['identical_file_outcomes'])
        self.assertEqual(report['differences'], [SELECTED[0]])

    def test_selection_order_remains_part_of_comparison(self):
        code, report = self.compare(right_selection=list(reversed(SELECTED)))
        self.assertEqual(code, 1)
        self.assertTrue(report['all_passed'])
        self.assertFalse(report['selection_matches'])
        self.assertFalse(report['identical_file_outcomes'])

    def test_invalid_results_fail_closed_on_either_arm(self):
        malformed = [None, {}, [], ROWS + [ROWS[0]], ROWS[:-1],
                     ROWS + [{'testPath': 'test/unselected.test.ts', 'ok': True, 'status': 'pass'}]]
        for change in ({'ok': 1}, {'status': 'fail'}, {'exitCode': 1}, {'signalCode': 'SIGKILL'},
                       {'exitCode': True}, {'exitCode': -1}, {'signalCode': ''}, {'error': 'failed'}):
            rows = copy.deepcopy(ROWS)
            rows[0].update(change)
            malformed.append(rows)
        for rows in malformed:
            # None is a malformed row rather than the helper's default argument.
            rows = [None] if rows is None else rows
            for arm in ('left', 'right'):
                with self.subTest(rows=rows, arm=arm):
                    code, report = self.compare(**{arm: rows})
                    self.assertEqual(code, 1)
                    self.assertFalse(report['all_passed'])
                    self.assertFalse(report['identical_file_outcomes'])
                    self.assertIn('baseline' if arm == 'left' else 'candidate', report['errors'])

    def test_invalid_selection(self):
        for selected in ([], {}, [SELECTED[0], SELECTED[0]], [1], ['test/../a'],
                         ['/test/a'], ['test\\a'], ['test//a']):
            with self.subTest(selected=selected):
                code, report = self.compare(selection=selected)
                self.assertEqual(code, 1)
                self.assertEqual(set(report['errors']), {'baseline', 'candidate'})

if __name__ == '__main__':
    unittest.main()
