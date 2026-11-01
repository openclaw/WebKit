"""Exercise the four test-only maintainer PRs on the integrated AOT engine."""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import shlex
import stat
import subprocess
import time
from xml.etree import ElementTree

INPUTS = Path(__file__).resolve().parent
SOURCE = Path('engine').resolve()
BUILD = Path(os.environ['RUNNER_TEMP']) / 'maintainer-native-build'
OUT = Path(os.environ['RUNNER_TEMP']) / 'maintainer-native-proof'
SPEC = json.loads((INPUTS / 'source-adapter.json').read_text())
ENGINE = '8e335354a58fa9a8eed14a70a8b9bf97b5d3073f'
RECORD = {'passed': False, 'engine': ENGINE, 'pipeline': os.environ['GITHUB_SHA'], 'steps': {}}
OUT.mkdir()


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save():
    (OUT / 'proof.json').write_text(json.dumps(RECORD, indent=2) + '\n')


def git(*args):
    return subprocess.check_output(['git', '-C', str(SOURCE), *args], text=True, timeout=120).strip()


def identity(path, expected):
    assert stat.S_ISREG(path.lstat().st_mode)
    assert stat.S_IMODE(path.stat().st_mode) == 0o644
    data = path.read_bytes()
    assert len(data) == expected['bytes'] and hashlib.sha256(data).hexdigest() == expected['sha256']
    assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == expected['blob']


def state(adapted):
    assert git('rev-parse', 'HEAD') == ENGINE
    assert git('write-tree') == git('rev-parse', 'HEAD^{tree}')
    tracked = {name for name, row in SPEC['files'].items() if row['before'] is not None}
    added = set(SPEC['files']) - tracked
    changed = set(git('diff', '--name-only', 'HEAD').splitlines())
    untracked = set(git('ls-files', '--others', '--exclude-standard').splitlines())
    assert changed == (tracked if adapted else set()), (changed, tracked, adapted)
    assert untracked == (added if adapted else set()), (untracked, added, adapted)
    for name, row in SPEC['files'].items():
        expected = row['after' if adapted else 'before']
        if expected is None:
            assert not os.path.lexists(SOURCE / name)
        else:
            identity(SOURCE / name, expected)


def run(name, argv, seconds=120, env=None, cwd=None):
    row = {'command': argv, 'returncode': None, 'timed_out': False}
    RECORD['steps'][name] = row
    save()
    start = time.monotonic()
    with (OUT / (name + '.log')).open('xb') as log:
        process = subprocess.Popen(argv, cwd=cwd or SOURCE, env=env, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            process.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            row['timed_out'] = True
            raise
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            row.update(returncode=process.returncode, seconds=time.monotonic() - start)
            save()
    assert process.returncode == 0 and not row['timed_out'], name
    assert sum(p.stat().st_size for p in OUT.iterdir()) <= 64 * 1024**2


def api(name, expected, extra_env=None):
    binary = BUILD / 'bin/TestWebKitAPI/TestJavaScriptCore'
    xml = OUT / (name + '.xml')
    run(name, [str(binary), '--gtest_filter=' + ':'.join('JavaScriptCore_' + item for item in expected),
        '--gtest_output=xml:' + str(xml)], 120, env=dict(os.environ, **(extra_env or {})))
    cases = list(ElementTree.parse(xml).iter('testcase'))
    observed = [case.get('classname', '').removeprefix('JavaScriptCore_') + '.' + case.get('name', '') for case in cases]
    assert len(observed) == len(expected) and set(observed) == set(expected), observed
    assert all(case.get('status') == 'run' and case.get('result') == 'completed' and
        all(case.find(tag) is None for tag in ('failure', 'error', 'skipped')) for case in cases)
    RECORD.setdefault('api_cases', {})[name] = observed
    save()


def stress(name, pattern, expected, quick=False, gc=False, timings=False):
    results = Path(os.environ['RUNNER_TEMP']) / (name + '-results')
    args = ['Tools/Scripts/run-jsc-stress-tests', 'JSTests/stress', '--jsc', str(BUILD / 'bin/jsc'),
        '--filter', pattern, '--no-retry', '--child-processes', '1', '--output-dir', str(results)]
    if quick:
        args.append('--quick')
    if gc:
        args += ['--env-vars', 'JSC_numberOfGCMarkers=4 JSC_useConcurrentGC=true']
    if timings:
        args.append('--report-execution-time')
    try:
        run(name, args, 600)
    finally:
        saved = {}
        for item in ('results', 'passed', 'failed', 'noresult', 'flaky'):
            path = results / item
            assert not path.is_symlink()
            if path.exists():
                assert path.is_file() and path.stat().st_size <= 1024**2
                saved[item] = path.read_text(encoding='ascii').splitlines()
            else:
                saved[item] = None
        (OUT / (name + '-results.json')).write_text(json.dumps(saved, indent=2) + '\n')
    assert saved['results'] and saved['passed']
    rows = [re.fullmatch(r'(.+): PASS', row) for row in saved['results']]
    assert all(rows)
    names = [row[1] for row in rows]
    assert len(names) == len(set(names)) == len(expected) and set(names) == set(expected), names
    assert len(saved['passed']) == len(expected) and set(saved['passed']) == set(expected)
    assert all(not saved[item] for item in ('failed', 'noresult', 'flaky'))
    if timings:
        measured = re.findall(r'^PASS: ([^\r\n]+) ([0-9]+)ms$', (OUT / (name + '.log')).read_text(), re.M)
        assert len(measured) == len(expected) and {n for n, _ in measured} == set(expected)
        assert all(0 <= int(ms) < 200 for _, ms in measured), measured
    RECORD.setdefault('stress_cases', {})[name] = names
    save()


assert SPEC['engine'] == ENGINE and len(SPEC['files']) == 3
RECORD['controls'] = {p.name: sha(p) for p in INPUTS.iterdir() if p.is_file()}
save()
state(False)
assert sha(SOURCE / 'Tools/TestWebKitAPI/Tests/JavaScriptCore/HeapTeardown.cpp') == '6ffd949ac2a2cba9aba09ca367bd982d3cb9c0d6e0364e7e8d7a19be8a519e71'
for name, row in SPEC['files'].items():
    control = INPUTS / row['control']
    identity(control, row['after'])
    (SOURCE / name).write_bytes(control.read_bytes())
state(True)
flags = ['-G', 'Ninja', '-DPORT=JSCOnly', '-DCMAKE_BUILD_TYPE=Release', '-DDEVELOPER_MODE=ON',
    '-DCMAKE_COMPILE_WARNING_AS_ERROR=OFF', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON', '-DENABLE_STATIC_JSC=ON', '-DUSE_BUN_JSC_ADDITIONS=ON',
    '-DUSE_BUN_EVENT_LOOP=ON', '-DUSE_MIMALLOC=ON', '-DUSE_EXTERNAL_MIMALLOC=OFF', '-DENABLE_FTL_JIT=ON',
    '-DENABLE_BUN_SKIP_FAILING_ASSERTIONS=ON', '-DALLOW_LINE_AND_COLUMN_NUMBER_IN_BUILTINS=ON',
    '-DENABLE_REMOTE_INSPECTOR=ON', '-DCMAKE_C_COMPILER=clang-23', '-DCMAKE_CXX_COMPILER=clang++-23']
run('configure', ['cmake', '-S', str(SOURCE), '-B', str(BUILD), *flags], 600)
run('build', ['cmake', '--build', str(BUILD), '--target', 'jsc', 'TestJavaScriptCore', '-j2'], 7200)
# AOT is derived in PlatformEnable.h. Ask the compiler using the actual API
# translation unit's flags, after the build has supplied any forced PCHs.
entries = json.loads((BUILD / 'compile_commands.json').read_text())
unit = SOURCE / 'Source/JavaScriptCore/aot/runtime/AOTNoFeatureRemoved.cpp'
rows = [row for row in entries if Path(row['file']).resolve() == unit and
        'TestJavaScriptCore.dir/' in (row.get('output', '') + row.get('command', '') + ' '.join(row.get('arguments', [])))]
assert len(rows) == 1, 'missing or ambiguous API AOT translation unit'
row = rows[0]
arguments = row.get('arguments') or shlex.split(row['command'])
assert not any(arg.startswith('@') for arg in arguments), 'unexpanded compiler response file'
assert arguments.count(str(unit)) == 1 and arguments.count('-c') == 1
argv = []
iterator = iter(arguments)
for arg in iterator:
    if arg in ('-o', '-MF', '-MT', '-MQ', '-MJ'):
        next(iterator)
    elif arg not in ('-c', '-MD', '-MMD', '-MP', str(unit)):
        argv.append(arg)
probe = BUILD / 'full-aot-admission.cpp'
probe.write_text('#include ' + json.dumps(str(unit)) + '\n#ifndef ENABLE\n#error missing WebKit platform configuration\n#endif\n#if !ENABLE(AOT)\n#error full AOT is disabled for TestJavaScriptCore\n#endif\n')
RECORD['feature_admission'] = {'compile_row': row, 'probe_sha256': sha(probe)}
save()
run('full-aot-admission', [*argv, '-E', '-x', 'c++', str(probe), '-o', '/dev/null'], cwd=Path(row['directory']))
state(True)
binaries = {name: sha(BUILD / path) for name, path in {'jsc': 'bin/jsc', 'api': 'bin/TestWebKitAPI/TestJavaScriptCore'}.items()}
api('marked-vector', ['MarkedVector.Append_JSObjectPtr'])
api('heap-teardown', ['HeapTeardown.FinalizesNewCellsWithoutLiveBitmaps', 'HeapTeardown.FinalizesMarkedCellsWithoutLiveBitmaps'])
api('async-frame', ['AsyncStackTrace.SuspendedFrameUsesResumeInstruction'], {'JSC_useAsyncStackTrace': 'true'})
stress('gc-helpers', r'^stress/(basic-eden-gc-test|weakmap-gc)\.js\.(default|no-cjit)$',
    ['stress/' + script + '.js.' + mode for script in ('basic-eden-gc-test', 'weakmap-gc') for mode in ('default', 'no-cjit')], quick=True, gc=True)
stress('async-stress', r'^stress/error-stack-async-relative-resume-target\.js\.',
    ['stress/error-stack-async-relative-resume-target.js.' + mode for mode in (
        'default', 'bytecode-cache', 'mini-mode', 'lockdown', 'no-llint', 'no-cjit-validate-phases',
        'no-cjit-collect-continuously', 'dfg-eager', 'dfg-eager-no-cjit-validate', 'eager-jettison-no-cjit',
        'no-ftl', 'ftl-eager', 'ftl-eager-no-cjit', 'ftl-no-cjit-small-pool',
        'ftl-no-cjit-validate-sampling-profiler', 'ftl-no-cjit-no-put-stack-validate', 'ftl-no-cjit-no-inline-validate')], timings=True)
shell_off = BUILD.with_name('maintainer-shell-off')
run('shell-off-configure', ['cmake', '-S', str(SOURCE), '-B', str(shell_off), *flags, '-DENABLE_JAVASCRIPT_SHELL=OFF'], 600)
run('shell-off-api-link', ['ninja', '-C', str(shell_off), '-t', 'query', 'bin/TestWebKitAPI/TestJavaScriptCore'])
link = (OUT / 'shell-off-api-link.log').read_text()
assert 'aot-builtin-table-obj' in link and 'AOTNoFeatureRemoved.cpp.o' in link
state(True)
assert binaries == {name: sha(BUILD / path) for name, path in {'jsc': 'bin/jsc', 'api': 'bin/TestWebKitAPI/TestJavaScriptCore'}.items()}
RECORD.update(passed=True, binary_sha256=binaries, overlays=SPEC['files'], cmake_cache_sha256=sha(BUILD / 'CMakeCache.txt'))
save()
