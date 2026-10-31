#!/usr/bin/env python3
"""Paired async-frame proof with the same measured API build adapter."""
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
BUILD = Path(os.environ['RUNNER_TEMP']) / 'upstream-async-build'
OUT = Path(os.environ['RUNNER_TEMP']) / 'upstream-async-proof'
OUT.mkdir(exist_ok=True)
SPEC = json.loads((INPUTS / 'source-adapter.json').read_text())
BASE = 'e66916298091dd12469076fd854e135b03fb16ff'
HEAD = '540ee746090a24a8d9df95cba19fd489307fb06b'
ADAPTER = '31b03fa17b3a9133d5240d593fa464b5825a2e33'
FIXTURE = 'Tools/TestWebKitAPI/Tests/JavaScriptCore/AsyncStackTrace.cpp'
REGISTRATION = 'Tools/TestWebKitAPI/CMakeLists.txt'
CASE = 'SuspendedFrameUsesResumeInstruction'
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
    identity(SOURCE / SPEC['production']['path'], SPEC['production']['before' if pin == BASE else 'after'])
    assert set(git('ls-files', '--others', '--exclude-standard').splitlines()) == ({FIXTURE} if pin == BASE and adapted else set())
    identity(SOURCE / REGISTRATION, SPEC['registration']['after' if pin == HEAD or adapted else 'before'])
    if pin == HEAD:
        identity(SOURCE / SPEC['stress_fixture']['path'], SPEC['stress_fixture'])
    else:
        assert not (SOURCE / SPEC['stress_fixture']['path']).exists()
    if pin == HEAD or adapted:
        identity(SOURCE / FIXTURE, SPEC['fixture'])
    else:
        assert not (SOURCE / FIXTURE).exists()


def admit(path, red):
    assert path.stat().st_size <= 16 * 1024**2
    cases = list(ElementTree.parse(path).iter('testcase'))
    assert len(cases) == 1
    case = cases[0]
    assert (case.get('classname'), case.get('name')) == ('JavaScriptCore_AsyncStackTrace', CASE)
    assert case.get('status') == 'run' and case.get('result') == 'completed'
    assert case.find('error') is None and case.find('skipped') is None
    failures = case.findall('failure')
    if not red:
        assert not failures
        return
    assert len(failures) == 1
    failure = failures[0]
    message = failure.get('message', '')
    match = re.search(r'Expected equality of these values:\s+frame\.bytecodeIndex\(\)\.offset\(\)\s+Which is: (\d+)\s+resumeOffset\s+Which is: (\d+)\s+switch offset: (\d+), relative target: (\d+)', message)
    assert match is not None, message
    actual, expected, switch, relative = map(int, match.groups())
    assert switch > 0 and relative > 0 and actual == relative and expected == switch + relative
    text = message + '\n' + ''.join(failure.itertext())
    assert re.search(r'AsyncStackTrace\.cpp:' + str(SPEC['expected_failure_line']) + r'\b', text), text


def stress(binary):
    fixture = SPEC['stress_fixture']
    identity(SOURCE / fixture['path'], fixture)
    before = sha(binary)
    results = Path(os.environ['RUNNER_TEMP']) / 'upstream-async-stress-results'
    prefix = 'stress/error-stack-async-relative-resume-target.js.'
    try:
        run('head-jsc-stress', ['Tools/Scripts/run-jsc-stress-tests', 'JSTests/stress',
            '--jsc', str(binary), '--filter', '^' + re.escape(prefix),
            '--report-execution-time', '--no-retry', '--child-processes', '1',
            '--output-dir', str(results)], seconds=600)
    finally:
        saved = {}
        for name in ['results', 'passed', 'failed', 'noresult', 'flaky']:
            path = results / name
            assert not path.is_symlink()
            if path.exists():
                assert path.is_file() and path.stat().st_size <= 1024**2
                saved[name] = path.read_text(encoding='ascii').splitlines()
            else:
                saved[name] = None
        (OUT / 'stress-results.json').write_text(json.dumps(saved, indent=2) + '\n')
    rows = saved['results']
    assert rows and saved['passed']
    names = []
    for row in rows:
        match = re.fullmatch(r'(.+): PASS', row)
        assert match and match[1].startswith(prefix), row
        names.append(match[1])
    assert len(names) == len(set(names)) and len(saved['passed']) == len(set(saved['passed']))
    assert set(saved['passed']) == set(names)
    assert all(not saved[name] for name in ['failed', 'noresult', 'flaky'])
    log = (OUT / 'head-jsc-stress.log').read_text()
    timings = re.findall(r'^PASS: ([^\r\n]+) ([0-9]+)ms$', log, re.MULTILINE)
    assert len(timings) == len(names) and len({name for name, _ in timings}) == len(names)
    assert {name for name, _ in timings} == set(names)
    assert all(0 <= int(ms) < 200 for _, ms in timings), timings
    assert sha(binary) == before
    identity(SOURCE / fixture['path'], fixture)
    RECORD['stress'] = {'source': HEAD, 'fixture_sha256': fixture['sha256'],
                        'binary_sha256': before,
                        'cases': [{'name': name, 'milliseconds': int(ms)} for name, ms in timings]}
    save()


assert (SPEC['base'], SPEC['head'], SPEC['build_adapter']) == (BASE, HEAD, ADAPTER)
assert sha(INPUTS / 'build-adapter.patch') == SPEC['build_patch_sha256']
identity(INPUTS / 'AsyncStackTrace.cpp', SPEC['fixture'])
RECORD.update(source_adapter_sha256=sha(INPUTS / 'source-adapter.json'),
              build_patch_sha256=SPEC['build_patch_sha256'], fixture_sha256=SPEC['fixture']['sha256'])
state(BASE, False)
run('fetch-head', ['git', '-c', 'gc.auto=0', '-c', 'maintenance.auto=false', 'fetch', '--no-tags',
                   '--no-prune', '--no-auto-maintenance', 'origin', HEAD])
assert set(git('diff', '--name-only', BASE, HEAD).splitlines()) == {
    SPEC['production']['path'], REGISTRATION, FIXTURE,
    'JSTests/stress/error-stack-async-relative-resume-target.js'}
baseline_binary = None
for arm, pin in [('base', BASE), ('head', HEAD)]:
    if arm == 'head':
        run('checkout-head', ['git', 'checkout', '--detach', HEAD])
    state(pin, False)
    run(arm + '-adapter-check', ['git', 'apply', '--check', str(INPUTS / 'build-adapter.patch')])
    run(arm + '-adapter', ['git', 'apply', str(INPUTS / 'build-adapter.patch')])
    if arm == 'base':
        (SOURCE / FIXTURE).write_bytes((INPUTS / 'AsyncStackTrace.cpp').read_bytes())
        registration = SOURCE / REGISTRATION
        text = registration.read_text()
        marker = '    set(TestJavaScriptCore_LIBRARIES\n'
        assert text.count(marker) == 1
        registration.write_text(text.replace(marker, SPEC['static_registration'] + marker))
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
    xml = OUT / (arm + '-async-frame.xml')
    run(arm + '-async-frame', ['env', 'JSC_useAsyncStackTrace=true', str(binary),
                              '--gtest_filter=JavaScriptCore_AsyncStackTrace.' + CASE,
                              '--gtest_output=xml:' + str(xml)], expected=1 if arm == 'base' else 0)
    admit(xml, red=arm == 'base')
    assert sha(binary) == before
    state(pin, True)
    if arm == 'head':
        run('head-build-jsc', ['cmake', '--build', str(BUILD), '--target', 'jsc', '-j4'], 1200)
        stress(BUILD / 'bin/jsc')
        state(pin, True)
    RECORD['arms'][arm] = {'source': pin, 'binary_sha256': before, 'case': CASE,
                           'cmake_cache_sha256': sha(BUILD / 'CMakeCache.txt'), 'adapted_inputs': adapted_inputs}
    run(arm + '-restore', ['git', 'restore', '--source=' + pin, '--worktree', '--', *SPEC['files'], REGISTRATION])
    if arm == 'base':
        (SOURCE / FIXTURE).unlink()
        baseline_binary = before
    state(pin, False)
    save()
assert RECORD['arms']['head']['binary_sha256'] != baseline_binary
RECORD.update(passed=True, qualification='959 runtime proof with shared 963 build adapter')
save()
