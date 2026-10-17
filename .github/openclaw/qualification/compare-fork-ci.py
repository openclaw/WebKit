#!/usr/bin/env python3
"""Compare complete CI outcomes without hiding failed attempts or missing metadata."""
import argparse
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('upstream', type=Path)
p.add_argument('local', type=Path)
p.add_argument('--output', required=True, type=Path)
a = p.parse_args()

def read(root):
    selected = json.loads((root / 'selected.json').read_text())
    rows = json.loads((root / 'results.json').read_text())
    if (not isinstance(selected, list) or not selected
            or any(not isinstance(name, str) or not name.startswith('test/')
                   or '\\' in name or any(part in ('', '.', '..') for part in name.split('/'))
                   for name in selected) or len(selected) != len(set(selected))):
        raise ValueError('invalid/empty/duplicate selection')
    if not isinstance(rows, list):
        raise ValueError('results must be a list')
    expected = set(selected) | {'package.json', 'test/package.json'}
    by_file = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('testPath'), str):
            raise ValueError('invalid result row')
        name = row['testPath']
        if name not in expected or name in by_file:
            raise ValueError(f'unexpected/duplicate result: {name}')
        ok, status = row.get('ok'), row.get('status')
        code, signal = row.get('exitCode'), row.get('signalCode')
        if (type(ok) is not bool or status not in ('pass', 'fail')
                or ok != (status == 'pass')
                or (code is not None and (type(code) is not int or code < 0))
                or (signal is not None and (not isinstance(signal, str) or not signal))
                or (ok and (code not in (None, 0) or signal is not None or row.get('error')))):
            raise ValueError(f'contradictory/invalid outcome: {name}')
        # Grouped rows have no per-file process exit. Keep that absence; never invent zero.
        by_file[name] = (ok, status, code, signal)
    if set(by_file) != expected:
        raise ValueError('missing result files: ' + ', '.join(sorted(expected - set(by_file))))
    return selected, by_file

arms, errors = [], {}
for label, root in (('baseline', a.upstream), ('candidate', a.local)):
    try:
        arms.append(read(root))
    except (OSError, ValueError, TypeError) as error:
        errors[label] = str(error)
        arms.append(([], {}))
left_selection, left = arms[0]
right_selection, right = arms[1]
same = not errors and left_selection == right_selection and left == right
baseline_passed = bool(left) and all(value[0] for value in left.values())
candidate_passed = bool(right) and all(value[0] for value in right.values())
result = {'identical_file_outcomes': same, 'selected_files': len(left_selection),
          'result_files': len(left), 'additional_runner_results': sorted(set(left) - set(left_selection)),
          'baseline_all_passed': baseline_passed, 'candidate_all_passed': candidate_passed,
          'all_passed': not errors and baseline_passed and candidate_passed,
          'selection_matches': left_selection == right_selection,
          'errors': errors,
          'differences': sorted(name for name in set(left) | set(right) if left.get(name) != right.get(name))}
a.output.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
raise SystemExit(0 if same and result['all_passed'] else 1)
