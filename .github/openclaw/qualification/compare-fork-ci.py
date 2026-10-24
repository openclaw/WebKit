#!/usr/bin/env python3
"""Compare complete CI outcomes, including failures, without declaring them green."""
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
    assert selected and len(selected) == len(set(selected)), 'empty/duplicate selection'
    by_file = {}
    for row in rows:
        by_file.setdefault(row['testPath'], []).append((row['ok'], row.get('status'), row.get('exitCode'), row.get('signalCode')))
    assert set(selected) <= set(by_file), 'missing selected result files'
    return selected, {name: sorted(values, key=repr) for name, values in by_file.items()}

left_selection, left = read(a.upstream)
right_selection, right = read(a.local)
same = left_selection == right_selection and left == right
result = {'identical_file_outcomes': same, 'selected_files': len(left_selection),
          'result_files': len(left), 'additional_runner_results': sorted(set(left) - set(left_selection)),
          'all_passed': all(value[0] and value[1] == 'pass' and value[2] in (None, 0) and value[3] is None
                            for arm in (left, right) for values in arm.values() for value in values),
          'differences': sorted(name for name in set(left) | set(right) if left.get(name) != right.get(name))}
a.output.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
raise SystemExit(0 if same and result['all_passed'] else 1)
