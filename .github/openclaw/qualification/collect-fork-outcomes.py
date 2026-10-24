#!/usr/bin/env python3
"""Retain individual JUnit cases, including skips/todos, for qualification audit."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def collect(root):
    files = {}
    for path in sorted(root.glob('*.xml')):
        tree = ET.parse(path)
        for suite in tree.iter('testsuite'):
            for case in suite.findall('testcase'):
                file = case.get('file') or suite.get('file')
                if not file:
                    raise ValueError(f'Missing testcase file in {path}')
                state = 'pass'
                detail = ''
                for tag in ('failure', 'error', 'skipped'):
                    child = case.find(tag)
                    if child is not None:
                        state = tag
                        detail = child.get('message', '')
                        if tag == 'skipped' and 'todo' in (child.get('type', '') + detail).lower():
                            state = 'todo'
                        break
                files.setdefault(file, []).append({'name': case.get('name'), 'classname': case.get('classname'),
                                                  'status': state, 'detail': detail})
    selected = json.loads((root / 'selected.json').read_text())
    missing = sorted(set(selected) - set(files))
    if missing:
        raise ValueError(f'Missing JUnit test cases: {missing}')
    for file, cases in files.items():
        if any(case['status'] in ('failure', 'error') for case in cases):
            raise ValueError(f'Failed JUnit cases: {file}')
    (root / 'test-outcomes.json').write_text(json.dumps(files, indent=2) + '\n')
    return files


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('root', type=Path)
    collect(p.parse_args().root)
