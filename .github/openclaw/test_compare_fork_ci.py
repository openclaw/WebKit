#!/usr/bin/env python3
"""Exercise the real CLI with paired, incomplete, and invalid native evidence."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from qualification import compare_fork_ci as comparison, consumer_identity as consumer
from test_consumer_identity import write_invocation

SCRIPT = Path(comparison.__file__)
SELECTED = json.loads((SCRIPT.parent / 'selected.json').read_text())
FACTS = {'exitCode': 0, 'signalCode': None, 'spawnError': False, 'timedOut': False, 'idledOut': False}


def evidence(grouped=True, selected=SELECTED):
    group = {**FACTS, 'id': 'bun-tests-batch-serial-1.xml', 'memberCount': len(selected)}
    rows = []
    for name in [*selected, 'package.json', 'test/package.json']:
        row = {'testPath': name, 'ok': True, 'status': 'pass'}
        if grouped and name in selected:
            row.update(groupedProcess=copy.deepcopy(group), groupedReport={'suite': {'failures': 0, 'seconds': 0, 'cases': []}})
        else:
            row.update(FACTS)
        rows.append(row)
    return {'selected.json': selected, 'results.json': rows,
            'runner-terminal.json': {'status': 0, 'signal': None, 'spawnError': False},
            'wrapper-terminal.json': {'status': 0}}


def failed_baseline(unreported=False):
    arm = evidence()
    for row in arm['results.json'][:len(SELECTED)]:
        row['groupedProcess']['exitCode'] = 1
    row = arm['results.json'][0]
    row.update(ok=False, status='fail', error='parallel JUnit report is missing this file' if unreported else 'failed in the parallel batch')
    row['groupedReport']['suite'] = None if unreported else {'failures': 1, 'seconds': 1,
        'cases': [{'name': 'ordinary assertion', 'message': 'expected value'}]}
    arm['runner-terminal.json']['status'] = arm['wrapper-terminal.json']['status'] = 2
    return arm


class CompareForkCI(unittest.TestCase):
    def compare(self, baseline=None, candidate=None, mutate=None, candidate_name="candidate"):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for label, value in [('baseline', baseline or evidence()), (candidate_name, candidate or evidence())]:
                write_invocation(root,label,value)
            if mutate: mutate(root)
            output = root / 'comparison.json'
            run = subprocess.run([sys.executable, str(SCRIPT), str(root / 'baseline'), str(root / candidate_name),
                                  '--output', str(output)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.stderr, '')
            return run.returncode, json.loads(output.read_text())

    def test_complete_passes(self):
        code, report = self.compare()
        self.assertEqual(code, 0)
        self.assertEqual(report['policy'], comparison.POLICY)
        self.assertTrue(report['passed'])
        self.assertTrue(report['identical_file_outcomes'])
        self.assertTrue(report['all_passed'])
        self.assertEqual((report['selected_files'], report['result_files']), (44, 46))
        self.assertEqual(report['baseline_failed'], [])
        self.assertEqual(report['baseline_unreported'], [])

    def test_baseline_failures_and_gaps_remain_visible(self):
        for unreported in (False, True):
            with self.subTest(unreported=unreported):
                code, report = self.compare(baseline=failed_baseline(unreported))
                self.assertEqual(code, 0)
                self.assertTrue(report['passed'])
                self.assertFalse(report['all_passed'])
                self.assertFalse(report['baseline_all_passed'])
                self.assertTrue(report['candidate_all_passed'])
                self.assertFalse(report['identical_file_outcomes'])
                self.assertEqual(report['baseline_unreported' if unreported else 'baseline_failed'], [SELECTED[0]])

    def test_candidate_failure_or_gap_blocks(self):
        for unreported in (False, True):
            code, report = self.compare(baseline=failed_baseline(unreported), candidate=failed_baseline(unreported))
            self.assertEqual(code, 1)
            self.assertFalse(report['passed'])

    def test_raw_metadata_difference_does_not_invent_per_file_exit(self):
        code, report = self.compare(baseline=evidence(False))
        self.assertEqual(code, 0)
        self.assertTrue(report['all_passed'])
        self.assertFalse(report['identical_file_outcomes'])
        self.assertEqual(set(report['differences']), set(SELECTED))

    def test_selection_is_trusted_ordered_and_complete(self):
        for chosen in (list(reversed(SELECTED)), SELECTED[:-1], SELECTED + [SELECTED[0]],
                       [], {}, ['test/../a'], ['test//a'], ['test\\a']):
            arm = evidence(); arm['selected.json'] = chosen
            code, report = self.compare(baseline=arm, candidate=arm)
            self.assertEqual(code, 1)
            self.assertEqual(set(report['errors']), {'baseline', 'candidate'})
        arm = evidence(); arm['selected.json'] = list(reversed(SELECTED))
        self.assertFalse(self.compare(candidate=arm)[1]['selection_matches'])

    def test_missing_duplicate_and_unexpected_rows(self):
        for rows in ([], [None], {}, evidence()['results.json'][:-1],
                     evidence()['results.json'] + [evidence()['results.json'][0]],
                     evidence()['results.json'] + [{'testPath': 'test/unselected.ts'}]):
            for label in ('baseline', 'candidate'):
                with self.subTest(rows=rows, label=label):
                    arm = evidence(); arm['results.json'] = rows
                    self.assertIn(label, self.compare(**{label: arm})[1]['errors'])

    def test_abnormal_process_facts_block_on_both_arms(self):
        changes = [{'exitCode': None}, {'exitCode': True}, {'exitCode': 134}, {'signalCode': 'SIGABRT'},
                   {'spawnError': True}, {'timedOut': True}, {'idledOut': True}, {'timedOut': 0}]
        for grouped in (False, True):
            for change in changes:
                for label in ('baseline', 'candidate'):
                    with self.subTest(grouped=grouped, change=change, label=label):
                        arm = evidence(grouped)
                        target = arm['results.json'][0]
                        if grouped: target = target['groupedProcess']
                        target.update(change)
                        code, report = self.compare(**{label: arm})
                        self.assertEqual(code, 1)
                        self.assertIn(label, report['errors'])
                        self.assertTrue(report['selection_matches'])
        for key in comparison.FACTS:
            arm = evidence(False); del arm['results.json'][0][key]
            self.assertEqual(self.compare(baseline=arm)[0], 1)

    def test_group_report_and_membership_must_be_valid(self):
        changes = [lambda r: r['groupedProcess'].update(memberCount=43),
                   lambda r: r['groupedProcess'].update(exitCode=1),
                   lambda r: r.update(exitCode=0),
                   lambda r: r['groupedReport'].update(error='invalid report'),
                   lambda r: r['groupedReport'].update(suite=None),
                   lambda r: r['groupedReport']['suite'].update(failures=True),
                   lambda r: r['groupedReport']['suite'].update(seconds=-1),
                   lambda r: r['groupedReport']['suite'].update(cases=[{'name': 'x'}]),
                   lambda r: r.update(ok=False, status='fail', error='unexplained')]
        for change in changes:
            for label in ('baseline', 'candidate'):
                arm = evidence(); change(arm['results.json'][0])
                self.assertEqual(self.compare(**{label: arm})[0], 1)
        arm = failed_baseline(True)
        for row in arm['results.json'][:len(SELECTED)]:
            row.update(ok=False, status='fail', error='parallel JUnit report is missing this file')
            row['groupedReport']['suite'] = None
        self.assertIn('empty grouped report', self.compare(baseline=arm)[1]['errors']['baseline'])

    def test_worker_crash_and_failed_install_are_not_baseline_exemptions(self):
        for case in ({'name': '(worker crashed)', 'message': 'details'},
                     {'name': 'details', 'message': 'worker process crashed before reporting results'}):
            arm = failed_baseline(); arm['results.json'][0]['groupedReport']['suite']['cases'] = [case]
            self.assertIn('worker crash', self.compare(baseline=arm)[1]['errors']['baseline'])
        arm = evidence(); arm['results.json'][-1].update(ok=False, status='fail', error='code 1', exitCode=1)
        arm['runner-terminal.json']['status'] = arm['wrapper-terminal.json']['status'] = 2
        self.assertIn('install failed', self.compare(baseline=arm)[1]['errors']['baseline'])

    def test_terminal_status_signal_spawn_and_missing_receipts_block(self):
        for label in ('baseline', 'candidate'):
            for name in ('runner-terminal.json', 'wrapper-terminal.json'):
                for code in (None, True, 1, 3, 137, 2):
                    arm = evidence(); arm[name]['status'] = code
                    self.assertEqual(self.compare(**{label: arm})[0], 1)
                arm = evidence(); del arm[name]
                self.assertEqual(self.compare(**{label: arm})[0], 1)
            for change in ({'signal': 'SIGTERM'}, {'spawnError': True}, {'spawnError': 0}):
                arm = evidence(); arm['runner-terminal.json'].update(change)
                self.assertEqual(self.compare(**{label: arm})[0], 1)

    def test_canonical_fatal_errors_block_ordinary_failures_remain_visible(self):
        for error in (*comparison.FATAL_ERRORS, '  ERROR: AddressSanitizer detail  ', 'code 1', 'EEXIST epoll_ctl'):
            arm = evidence(False)
            arm['results.json'][0].update(ok=False, status='fail', exitCode=1, error=error)
            arm['runner-terminal.json']['status'] = arm['wrapper-terminal.json']['status'] = 2
            code, report = self.compare(baseline=arm)
            fatal = error not in ('code 1', 'EEXIST epoll_ctl')
            self.assertEqual(code, 1 if fatal else 0)
            self.assertEqual('baseline' in report['errors'], fatal)
            if not fatal: self.assertEqual(report['baseline_failed'], [SELECTED[0]])

    def test_duplicate_json_keys_and_nonfinite_numbers_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'input.json'
            for text in ('{"status":0,"status":2}', '{"seconds":NaN}', '{"seconds":Infinity}'):
                file.write_text(text)
                with self.assertRaises(ValueError): comparison.read_json(file)



    def test_consumer_and_build_provenance_cannot_be_redigested_into_acceptance(self):
        for arm in ('baseline', 'candidate'):
            for field in ('runtime', 'overlay', 'argv', 'restored', 'adapter'):
                def tamper(root, arm=arm, field=field):
                    consumer_path=root/(arm+'-identity.json');record=json.loads(consumer_path.read_text())
                    tools_path=root/(arm+'-build-tools.json');tools=json.loads(tools_path.read_text())
                    if field=='runtime': record['runtime']['bun_revision']='f'*40
                    elif field=='overlay': tools['before']['other_patch_sha256']=tools['after']['other_patch_sha256']='f'*64
                    elif field=='argv': tools['argv'][3]='--lto=on'
                    elif field=='restored': tools['restored']=False
                    else: tools['adapter']['sha256']='f'*64
                    tools_path.write_text(json.dumps(tools));record['build_tools']=consumer.file_record(root,tools_path.name)
                    consumer_path.write_text(json.dumps(record))
                    write_invocation(root,arm,evidence())
                with self.subTest(arm=arm,field=field):
                    code,report=self.compare(mutate=tamper)
                    self.assertEqual(code,1);self.assertIn(arm,report['errors'])

    def test_paired_comparison_rejects_sync_reporting_mode(self):
        code,report=self.compare(candidate_name='sync')
        self.assertEqual(code,1)
        self.assertEqual(report['errors']['candidate'],'wrong paired invocation mode: candidate')

    def test_invocation_bytes_mode_and_freshness_are_bound(self):
        for kind in ('results', 'identity', 'selection', 'argv', 'restored', 'missing', 'direct'):
            def tamper(root, kind=kind):
                path=root/'candidate/invocation.json';record=json.loads(path.read_text())
                if kind=='results': (root/'candidate/results.json').write_text('[]')
                elif kind=='identity': record['identity']['sha256']='f'*64
                elif kind=='selection': record['selection']['sha256']='f'*64
                elif kind=='argv': record['argv']+=['--junit-prefix','openclaw-sync-junit-'+'1'*32+'-']
                elif kind=='restored': record['restored']=False
                elif kind=='missing': path.unlink();return
                else:
                    direct=root/'candidate/net-direct.json';value=json.loads(direct.read_text());value['exitCode']=1
                    direct.write_text(json.dumps(value));record['evidence']['net-direct.json']=consumer.file_record(root,'candidate/net-direct.json')
                path.write_text(json.dumps(record))
            with self.subTest(kind=kind): self.assertEqual(self.compare(mutate=tamper)[0],1)


if __name__ == '__main__':
    unittest.main()
