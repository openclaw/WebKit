#!/usr/bin/env python3
"""Validate first-attempt evidence; preserve baseline failures and incomplete coverage."""
import argparse
import json
import math
from pathlib import Path
if __package__:
    from . import consumer_identity as identity
else:
    import consumer_identity as identity

POLICY = 'candidate-pass-baseline-observed-v1'
INPUTS = Path(__file__).resolve().parent
INSTALLS = {'package.json', 'test/package.json'}
FACTS = ('exitCode', 'signalCode', 'spawnError', 'timedOut', 'idledOut')
# Same fatal categories as the pinned runner's isAlwaysFailure; inspect its retained error only.
FATAL_ERRORS = ('segmentation fault', 'illegal instruction', 'unchecked exception', 'sigtrap',
                'sigabrt', 'sigkill', 'error: addresssanitizer', 'internal assertion failure',
                'core dumped', 'crash reported')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, 'duplicate JSON key: ' + key)
            value[key] = item
        return value
    def invalid(value):
        raise ValueError('invalid JSON number: ' + value)
    return json.loads(path.read_text(), object_pairs_hook=unique, parse_constant=invalid)


def selection(value):
    require(isinstance(value, list) and bool(value)
            and all(isinstance(name, str) and name.startswith('test/') and '\\' not in name
                    and all(part not in ('', '.', '..') for part in name.split('/')) for name in value)
            and len(value) == len(set(value)), 'invalid/empty/duplicate selection')
    return value


def process_facts(value, name):
    require(isinstance(value, dict) and all(key in value for key in FACTS), 'missing process facts: ' + name)
    require(type(value['exitCode']) is int and value['exitCode'] in (0, 1)
            and value['signalCode'] is None
            and all(type(value[key]) is bool and not value[key]
                    for key in ('spawnError', 'timedOut', 'idledOut')), 'abnormal process termination: ' + name)
    return value['exitCode']


def file_suite(value, name):
    require(isinstance(value, dict) and set(value) == {'failures', 'seconds', 'cases'}, 'invalid file suite: ' + name)
    require(type(value['failures']) is int and 0 <= value['failures'] <= 2**53 - 1
            and type(value['seconds']) in (int, float) and math.isfinite(value['seconds']) and value['seconds'] >= 0
            and isinstance(value['cases'], list), 'invalid file suite metrics: ' + name)
    for case in value['cases']:
        require(isinstance(case, dict) and set(case) == {'name', 'message'}
                and isinstance(case['name'], str) and isinstance(case['message'], str), 'invalid failed case: ' + name)
        require(case['name'] != '(worker crashed)'
                and case['message'] != 'worker process crashed before reporting results', 'worker crash: ' + name)
    # The native file outcome includes zero/skip-only suites. Executed-case gates are separate.
    return value['failures'] > 0 or bool(value['cases'])


def validate_arm(root, expected, baseline=False):
    invocation = identity.validate_invocation(root.parent, root.name)
    require((root.name == 'baseline') == baseline, 'wrong arm invocation')
    chosen = selection(read_json(root / 'selected.json'))
    require(chosen == selection(expected), 'selection differs from trusted ordered input')
    rows = read_json(root / 'results.json')
    require(isinstance(rows, list), 'results must be a list')
    wanted = set(expected) | INSTALLS
    by_file, groups = {}, {}
    failed, unreported = [], []
    for row in rows:
        require(isinstance(row, dict) and isinstance(row.get('testPath'), str), 'invalid result row')
        name = row['testPath']
        require(name in wanted and name not in by_file, 'unexpected/duplicate result: ' + name)
        require(type(row.get('ok')) is bool and row.get('status') in ('pass', 'fail')
                and row['ok'] == (row['status'] == 'pass'), 'contradictory/invalid outcome: ' + name)
        require((row.get('error') in (None, '') if row['ok'] else isinstance(row.get('error'), str) and bool(row['error'])),
                'invalid outcome error: ' + name)
        require(not any(value in (row.get('error') or '').lower().strip() for value in FATAL_ERRORS),
                'fatal runner outcome: ' + name)
        by_file[name] = row
        if 'groupedProcess' not in row:
            require('groupedReport' not in row, 'report without grouped process: ' + name)
            code = process_facts(row, name)
            require(row['ok'] == (code == 0), 'process/file outcome mismatch: ' + name)
            if not row['ok']:
                failed.append(name)
        else:
            group = row['groupedProcess']
            require(name not in INSTALLS and isinstance(group, dict)
                    and set(group) == set(FACTS) | {'id', 'memberCount'}, 'invalid group: ' + name)
            process_facts(group, name)
            require(not any(key in row for key in FACTS), 'fabricated per-file process facts: ' + name)
            require(isinstance(group['id'], str) and bool(group['id']) and '/' not in group['id'] and '\\' not in group['id']
                    and type(group['memberCount']) is int and group['memberCount'] > 0, 'invalid group identity: ' + name)
            report = row.get('groupedReport')
            require(isinstance(report, dict) and set(report) == {'suite'}, 'invalid grouped report: ' + name)
            suite = report['suite']
            suite_failed = None if suite is None else file_suite(suite, name)
            require(row['ok'] == (suite is not None and not suite_failed), 'suite/file outcome mismatch: ' + name)
            if suite is None:
                require(baseline and group['exitCode'] == 1, 'unreported file is not an admissible baseline gap: ' + name)
                require(row['error'] == 'parallel JUnit report is missing this file', 'missing-suite outcome mismatch: ' + name)
                unreported.append(name)
            elif suite_failed:
                require(row['error'] == 'failed in the parallel batch', 'failed-suite outcome mismatch: ' + name)
                failed.append(name)
            groups.setdefault(group['id'], []).append(row)
        require(name not in INSTALLS or row['ok'], 'install failed: ' + name)
    require(set(by_file) == wanted, 'missing result files: ' + ', '.join(sorted(wanted - set(by_file))))
    for group_id, members in groups.items():
        group = members[0]['groupedProcess']
        require(len(members) == group['memberCount'] and all(row['groupedProcess'] == group for row in members),
                'group membership/snapshot mismatch: ' + group_id)
        require(any(row['groupedReport']['suite'] is not None for row in members), 'empty grouped report: ' + group_id)
        require((group['exitCode'] == 0) == all(row['ok'] for row in members), 'group process/outcome mismatch: ' + group_id)
    passed = all(row['ok'] for row in rows)
    terminal = read_json(root / 'runner-terminal.json')
    require(isinstance(terminal, dict) and set(terminal) == {'status', 'signal', 'spawnError'}
            and type(terminal['status']) is int and terminal['status'] == (0 if passed else 2)
            and terminal['signal'] is None and terminal['spawnError'] is False, 'invalid runner terminal')
    wrapper = read_json(root / 'wrapper-terminal.json')
    require(isinstance(wrapper, dict) and set(wrapper) == {'status'} and type(wrapper['status']) is int
            and wrapper['status'] == terminal['status'], 'invalid helper terminal')
    return {'selected': chosen, 'rows': by_file, 'all_passed': passed, 'invocation': invocation,
            'failed': sorted(failed), 'unreported': sorted(unreported)}


def compare(baseline_root, candidate_root):
    expected = selection(read_json(INPUTS / 'selected.json'))
    require(len(expected) == 44, 'trusted paired selection must contain 44 files')
    arms, errors, selections = {}, {}, {}
    for label, root in (('baseline', baseline_root), ('candidate', candidate_root)):
        try:
            require(root.name == label, 'wrong paired invocation mode: ' + label)
            selections[label] = selection(read_json(root / 'selected.json'))
            arms[label] = validate_arm(root, expected, baseline=label == 'baseline')
        except (OSError, ValueError, TypeError, KeyError, OverflowError) as error:
            errors[label] = str(error)
    left, right = arms.get('baseline'), arms.get('candidate')
    def outcomes(arm):
        return {} if arm is None else {name: tuple(row.get(key) for key in ('ok', 'status', 'exitCode', 'signalCode'))
                                      for name, row in arm['rows'].items()}
    left_rows, right_rows = outcomes(left), outcomes(right)
    baseline_passed = left is not None and left['all_passed']
    candidate_passed = right is not None and right['all_passed']
    return {'policy': POLICY, 'passed': not errors and candidate_passed,
            'identical_file_outcomes': not errors and left_rows == right_rows,
            'selected_files': len(expected), 'result_files': len(left_rows),
            'additional_runner_results': sorted(INSTALLS),
            'baseline_all_passed': baseline_passed, 'candidate_all_passed': candidate_passed,
            'all_passed': not errors and baseline_passed and candidate_passed,
            'baseline_failed': [] if left is None else left['failed'],
            'baseline_unreported': [] if left is None else left['unreported'],
            'invocations': {label: arm['invocation'] for label, arm in arms.items()},
            'selection_matches': len(selections) == 2 and selections['baseline'] == selections['candidate'],
            'errors': errors,
            'differences': sorted(name for name in set(left_rows) | set(right_rows) if left_rows.get(name) != right_rows.get(name))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('upstream', type=Path)
    parser.add_argument('local', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = compare(args.upstream, args.local)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
