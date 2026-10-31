#!/usr/bin/env python3
"""Paired heap-teardown proof with the same measured API build adapter."""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from xml.etree import ElementTree

INPUTS = Path(__file__).resolve().parent
SOURCE = Path('upstream').resolve()
BUILD = Path(os.environ['RUNNER_TEMP']) / 'upstream-heap-build'
OUT = Path(os.environ['RUNNER_TEMP']) / 'upstream-heap-proof'
OUT.mkdir(exist_ok=True)
SPEC = json.loads((INPUTS / 'source-adapter.json').read_text())
BASE = 'e66916298091dd12469076fd854e135b03fb16ff'
HEAD = '54247ada0f92ddae63cb9949619111b17cde10e8'
ADAPTER = '31b03fa17b3a9133d5240d593fa464b5825a2e33'
FIXTURE = 'Tools/TestWebKitAPI/Tests/JavaScriptCore/HeapTeardown.cpp'
REGISTRATION = 'Tools/TestWebKitAPI/CMakeLists.txt'
CASES = ['FinalizesNewCellsWithoutLiveBitmaps', 'FinalizesMarkedCellsWithoutLiveBitmaps']
RECORD = {'pipeline': os.environ['PIPELINE_SHA'], 'base': BASE, 'head': HEAD,
          'shared_build_adapter': ADAPTER, 'passed': False, 'steps': {}, 'arms': {}}
DEADLINE = time.monotonic() + 9000


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save():
    (OUT / 'proof.json').write_text(json.dumps(RECORD, indent=2) + '\n')


def run(name, argv, seconds=120, expected=0):
    record = {'command': argv, 'returncode': None, 'timed_out': False}
    RECORD['steps'][name] = record
    save()
    with (OUT / (name + '.log')).open('x') as log:
        process = subprocess.Popen(argv, cwd=SOURCE, stdout=log, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            process.wait(timeout=min(seconds, max(0, DEADLINE - time.monotonic())))
        except subprocess.TimeoutExpired:
            record['timed_out'] = True
            raise
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            record['returncode'] = process.returncode
            save()
    assert process.returncode == expected and not record['timed_out'], name


def git(*args):
    return subprocess.check_output(['git', *args], cwd=SOURCE, timeout=120).decode().strip()


def identity(path, expected):
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == expected['sha256'], str(path)
    assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == expected['blob']


def state(pin, adapted):
    assert git('rev-parse', 'HEAD') == pin
    assert git('write-tree') == git('rev-parse', 'HEAD^{tree}'), 'index drift'
    expected = set(SPEC['files']) if adapted else set()
    if pin == BASE and adapted:
        expected.add(REGISTRATION)
    assert set(git('diff', '--name-only', 'HEAD').splitlines()) == expected
    for name, entry in SPEC['files'].items():
        identity(SOURCE / name, entry['after' if adapted else 'before'])
        assert git('ls-files', '-s', '--', name).split()[0] == entry['mode']
    identity(SOURCE / REGISTRATION, SPEC['registration']['after' if pin == HEAD or adapted else 'before'])
    if pin == HEAD or adapted:
        identity(SOURCE / FIXTURE, SPEC['fixture'])
    else:
        assert not (SOURCE / FIXTURE).exists()


def admit(path, case_name, red):
    assert path.stat().st_size <= 16 * 1024**2
    cases = list(ElementTree.parse(path).iter('testcase'))
    assert len(cases) == 1
    case = cases[0]
    assert (case.get('classname'), case.get('name')) == ('JavaScriptCore_HeapTeardown', case_name)
    assert case.get('status') == 'run' and case.get('result') == 'completed'
    assert case.find('error') is None and case.find('skipped') is None
    failures = case.findall('failure')
    if not red:
        assert not failures
        return
    seen = set()
    for failure in failures:
        message = failure.get('message', '')
        match = re.search(r'Value of:\s*state\.(inactiveMarks|inactiveNewlyAllocated)\s+Actual:\s*false\s+Expected:\s*true', message)
        assert match is not None, message
        predicate = match.group(1)
        line = 89 if predicate == 'inactiveMarks' else 90
        text = message + '\n' + ''.join(failure.itertext())
        assert re.search(r'HeapTeardown\.cpp:' + str(line) + r'\b', text), text
        seen.add(predicate)
    assert seen == {'inactiveMarks', 'inactiveNewlyAllocated'}, seen


assert (SPEC['base'], SPEC['head'], SPEC['build_adapter']) == (BASE, HEAD, ADAPTER)
assert sha(INPUTS / 'build-adapter.patch') == SPEC['build_patch_sha256']
identity(INPUTS / 'HeapTeardown.cpp', SPEC['fixture'])
RECORD.update(source_adapter_sha256=sha(INPUTS / 'source-adapter.json'),
              build_patch_sha256=SPEC['build_patch_sha256'], fixture_sha256=SPEC['fixture']['sha256'])
state(BASE, False)
run('fetch-head', ['git', '-c', 'gc.auto=0', '-c', 'maintenance.auto=false', 'fetch', '--no-tags',
                   '--no-prune', '--no-auto-maintenance', 'origin', HEAD])
assert set(git('diff', '--name-only', BASE, HEAD).splitlines()) == {
    'Source/JavaScriptCore/heap/MarkedBlock.cpp', REGISTRATION, FIXTURE}
baseline_binary = None
for arm, pin in [('base', BASE), ('head', HEAD)]:
    if arm == 'head':
        run('checkout-head', ['git', 'checkout', '--detach', HEAD])
    state(pin, False)
    run(arm + '-adapter-check', ['git', 'apply', '--check', str(INPUTS / 'build-adapter.patch')])
    run(arm + '-adapter', ['git', 'apply', str(INPUTS / 'build-adapter.patch')])
    if arm == 'base':
        (SOURCE / FIXTURE).write_bytes((INPUTS / 'HeapTeardown.cpp').read_bytes())
        registration = SOURCE / REGISTRATION
        text = registration.read_text()
        marker = '        Tests/JavaScriptCore/DisallowVMEntry.cpp\n'
        assert text.count(marker) == 1
        registration.write_text(text.replace(marker, marker + '        Tests/JavaScriptCore/HeapTeardown.cpp\n'))
    state(pin, True)
    adapted_inputs = {name: sha(SOURCE / name) for name in [*SPEC['files'], FIXTURE, REGISTRATION]}
    if arm == 'base':
        paired_inputs = adapted_inputs
    else:
        assert paired_inputs == adapted_inputs, 'paired build/test overlays differ'
    run(arm + '-configure', ['cmake', '-S', str(SOURCE), '-B', str(BUILD), *SPEC['configure']], 600)
    run(arm + '-build', ['cmake', '--build', str(BUILD), '--target', 'TestJavaScriptCore', '-j4'], 4500 if arm == 'base' else 1200)
    binary = BUILD / 'bin/TestWebKitAPI/TestJavaScriptCore'
    before = sha(binary)
    for case in CASES:
        xml = OUT / (arm + '-' + case + '.xml')
        run(arm + '-' + case, [str(binary), '--gtest_filter=JavaScriptCore_HeapTeardown.' + case,
                              '--gtest_output=xml:' + str(xml)], expected=1 if arm == 'base' else 0)
        admit(xml, case, red=arm == 'base')
    assert sha(binary) == before
    state(pin, True)
    RECORD['arms'][arm] = {'source': pin, 'binary_sha256': before, 'cases': CASES,
                           'cmake_cache_sha256': sha(BUILD / 'CMakeCache.txt'), 'adapted_inputs': adapted_inputs}
    run(arm + '-restore', ['git', 'restore', '--source=' + pin, '--worktree', '--', *SPEC['files'], REGISTRATION])
    if arm == 'base':
        (SOURCE / FIXTURE).unlink()
        baseline_binary = before
    state(pin, False)
    save()
assert RECORD['arms']['head']['binary_sha256'] != baseline_binary
RECORD.update(passed=True, qualification='957 runtime proof with shared 963 build adapter')
save()
