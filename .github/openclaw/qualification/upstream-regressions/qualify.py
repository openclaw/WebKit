"""Prove namespace isolation red/green and integrated native regressions."""
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import shlex
import stat
import subprocess
import time
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree

INPUTS = Path(__file__).resolve().parent
SOURCE = Path('engine').resolve()
BUILD = Path(os.environ['RUNNER_TEMP']) / 'maintainer-native-build'
OUT = Path(os.environ['RUNNER_TEMP']) / 'maintainer-native-proof'
SPEC = json.loads((INPUTS / 'source-adapter.json').read_text())
ENGINE = '163b3f42dbe9003508597eaa4c52f6b28ebd533d'
RECORD = {'passed': False, 'engine': ENGINE, 'pipeline': os.environ['GITHUB_SHA'], 'steps': {}}
OUT.mkdir()
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


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


def state(stage):
    assert stage in ('base', 'tests', 'ported', 'fixed', 'host')
    assert git('rev-parse', 'HEAD') == ENGINE
    assert git('write-tree') == git('rev-parse', 'HEAD^{tree}')
    applied = {name for name, row in SPEC['files'].items()
        if stage in ('ported', 'fixed', 'host') or (stage == 'tests' and row['kind'] == 'test')}
    tracked = {name for name in applied if SPEC['files'][name]['before'] is not None}
    added = applied - tracked
    changed = set(git('diff', '--name-only', 'HEAD').splitlines())
    untracked = set(git('ls-files', '--others', '--exclude-standard').splitlines())
    assert changed == tracked, (changed, tracked, stage)
    assert untracked == added, (untracked, added, stage)
    for name, row in SPEC['files'].items():
        expected = row.get('host', row['after']) if stage == 'host' else row.get('ported', row['after']) if stage == 'ported' else row['after' if name in applied else 'before']
        if expected is None:
            assert not os.path.lexists(SOURCE / name)
        else:
            identity(SOURCE / name, expected)
    for name, expected in SPEC['unchanged_inputs'].items():
        identity(SOURCE / name, expected)


def run(name, argv, seconds=120, env=None, cwd=None, expected_failure=False):
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
    assert not row['timed_out'] and (process.returncode != 0 if expected_failure else process.returncode == 0), name
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


assert SPEC['engine'] == ENGINE and len(SPEC['files']) == 11
assert sum(row['kind'] == 'production' for row in SPEC['files'].values()) == 7
assert sum(row['kind'] == 'test' for row in SPEC['files'].values()) == 4
RECORD['controls'] = {p.name: sha(p) for p in INPUTS.iterdir() if p.is_file()}
save()
state('base')
for name, row in SPEC['files'].items():
    if row['kind'] != 'test':
        continue
    control = INPUTS / row['control']
    identity(control, row['after'])
    (SOURCE / name).write_bytes(control.read_bytes())
state('tests')
# The only test change is a warmup call in another test's IR. Keep the old
# baseline tied to its original bytes and line, rather than relabeling it.
baseline = SPEC['reused_baseline']
fixture = SOURCE / SPEC['regression']['file']
current = fixture.read_text()
assert current.count(baseline['inserted_call']) == 1
original = current.replace(baseline['inserted_call'], '').encode()
assert len(original) == baseline['fixture']['bytes']
assert hashlib.sha256(original).hexdigest() == baseline['fixture']['sha256']
assert hashlib.sha1(b'blob ' + str(len(original)).encode() + b'\0' + original).hexdigest() == baseline['fixture']['blob']
archive = Path(os.environ['RUNNER_TEMP']) / 'namespace-baseline.zip'
assert archive.stat().st_size == baseline['bytes'] and sha(archive) == baseline['sha256']
with zipfile.ZipFile(archive) as prior:
    entries = prior.infolist()
    names = {entry.filename for entry in entries}
    assert len(names) == len(entries) == 10
    for entry in entries:
        name = PurePosixPath(entry.filename)
        assert not name.is_absolute() and len(name.parts) == 1 and '..' not in name.parts
        assert stat.S_IFMT(entry.external_attr >> 16) in (0, stat.S_IFREG)
    assert prior.testzip() is None
    manifest = json.loads(prior.read('archive-manifest.json'))
    assert set(manifest) == names - {'archive-manifest.json'}
    for name, expected in manifest.items():
        data = prior.read(name)
        assert len(data) == expected['bytes'] and hashlib.sha256(data).hexdigest() == expected['sha256']
    proof = json.loads(prior.read('proof.json'))
    assert proof['passed'] is False and proof['engine'] == ENGINE and proof['pipeline'] == baseline['pipeline']
    assert proof['controls']['AOTSharingModeAndNamespaceTests.cpp'] == baseline['fixture']['sha256']
    for name in ('configure', 'baseline-build', 'baseline-full-aot-admission'):
        row = proof['steps'][name]
        assert row['returncode'] == 0 and row['timed_out'] is False
    assert proof['feature_admission']['baseline'] and len(proof['baseline_binary_sha256']) == 3
    assert proof['baseline_expected_failure'] == baseline['regression']
    row = proof['steps']['namespace-baseline']
    assert row['returncode'] == -6 and row['timed_out'] is False
    text = prior.read('namespace-baseline.log').decode()
    regression = baseline['regression']
    assert re.search(r'^' + re.escape(regression['case']) + r'$', text, re.M)
    assert 'ASSERTION FAILED: ' + regression['failure_expression'] in text
    assert re.search(re.escape(Path(regression['file']).name) + r'\(' + str(regression['failure_line']) + r'\)\s*:\s*native test', text)
    RECORD['reused_baseline'] = dict(baseline, archive_manifest=manifest,
        baseline_binary_sha256=proof['baseline_binary_sha256'])
(OUT / 'reused-baseline.zip').write_bytes(archive.read_bytes())
save()
patch = INPUTS / SPEC['production_patch']['control']
identity(patch, SPEC['production_patch'])
run('namespace-patch-check', ['git', 'apply', '--check', str(patch)])
run('namespace-patch-apply', ['git', 'apply', str(patch)])
state('ported')
flags = ['-G', 'Ninja', '-DPORT=JSCOnly', '-DCMAKE_BUILD_TYPE=Release', '-DDEVELOPER_MODE=ON',
    '-DCMAKE_COMPILE_WARNING_AS_ERROR=OFF', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON', '-DENABLE_STATIC_JSC=ON', '-DUSE_BUN_JSC_ADDITIONS=ON',
    '-DUSE_BUN_EVENT_LOOP=ON', '-DUSE_MIMALLOC=ON', '-DUSE_EXTERNAL_MIMALLOC=OFF', '-DENABLE_FTL_JIT=ON',
    '-DENABLE_BUN_SKIP_FAILING_ASSERTIONS=ON', '-DALLOW_LINE_AND_COLUMN_NUMBER_IN_BUILTINS=ON',
    '-DENABLE_REMOTE_INSPECTOR=ON', '-DCMAKE_C_COMPILER=clang-23', '-DCMAKE_CXX_COMPILER=clang++-23']
run('configure', ['cmake', '-S', str(SOURCE), '-B', str(BUILD), *flags], 600)
targets = ['testaot', 'jsc', 'TestJavaScriptCore']
paths = {'testaot': 'bin/testaot', 'jsc': 'bin/jsc', 'api': 'bin/TestWebKitAPI/TestJavaScriptCore'}


def binary_hashes():
    return {name: sha(BUILD / path) for name, path in paths.items()}


def admit_full_aot(label):
    # Use the actual API translation unit's flags after its forced PCH exists.
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
    probe = BUILD / (label + '-full-aot-admission.cpp')
    probe.write_text('#include ' + json.dumps(str(unit)) + '\n#ifndef ENABLE\n#error missing WebKit platform configuration\n#endif\n#if !ENABLE(AOT)\n#error full AOT is disabled for TestJavaScriptCore\n#endif\n')
    RECORD.setdefault('feature_admission', {})[label] = {'compile_row': row, 'probe_sha256': sha(probe)}
    save()
    run(label + '-full-aot-admission', [*argv, '-E', '-x', 'c++', str(probe), '-o', '/dev/null'], cwd=Path(row['directory']))


def expected_native_failure(name, regression):
    run(name, [str(BUILD / paths['testaot']), 'native', regression['case'], '--single-process'],
        300, expected_failure=True)
    text = (OUT / (name + '.log')).read_text(errors='replace')
    assert re.search(r'^' + re.escape(regression['case']) + r'$', text, re.M)
    assert 'ASSERTION FAILED: ' + regression['failure_expression'] in text
    assert re.search(re.escape(Path(regression['file']).name) + r'\(' + str(regression['failure_line']) + r'\)\s*:\s*native test', text)


run('ported-build', ['cmake', '--build', str(BUILD), '--target', *targets, '-j2'], 7200)
admit_full_aot('ported')
state('ported')
ported_binaries = binary_hashes()
RECORD['ported_binary_sha256'] = ported_binaries
save()
expected_native_failure('namespace-cache-before-repair', SPEC['cache_regression'])
state('ported')
assert binary_hashes() == ported_binaries
RECORD['cache_expected_failure'] = SPEC['cache_regression']
save()
patch = INPUTS / SPEC['cache_fix_patch']['control']
identity(patch, SPEC['cache_fix_patch'])
run('namespace-cache-fix-check', ['git', 'apply', '--check', str(patch)])
run('namespace-cache-fix-apply', ['git', 'apply', str(patch)])
state('fixed')
run('fixed-build', ['cmake', '--build', str(BUILD), '--target', *targets, '-j2'], 7200)
admit_full_aot('fixed')
state('fixed')
cache_binaries = binary_hashes()
run('namespace-cache-after-repair', [str(BUILD / paths['testaot']), 'native', SPEC['cache_regression']['case'], '--single-process'], 300)
text = (OUT / 'namespace-cache-after-repair.log').read_text(errors='replace')
assert re.findall(r'^(sharing-mode-and-namespace/[^\r\n]+)$', text, re.M) == [SPEC['cache_regression']['case']]
assert len(re.findall(r'^1 passed, 0 failed, 0 todo$', text, re.M)) == 1
assert not re.search(r'^(FAIL |LEFT OUT )', text, re.M)
state('fixed')
assert binary_hashes() == cache_binaries
RECORD['cache_red_green'] = True
save()
patch = INPUTS / SPEC['host_api_patch']['control']
identity(patch, SPEC['host_api_patch'])
run('namespace-host-api-check', ['git', 'apply', '--check', str(patch)])
run('namespace-host-api-apply', ['git', 'apply', str(patch)])
state('host')
run('host-build', ['cmake', '--build', str(BUILD), '--target', *targets, '-j2'], 7200)
admit_full_aot('host')
state('host')
binaries = binary_hashes()
run('namespace-fixed', [str(BUILD / paths['testaot']), 'native', 'sharing-mode-and-namespace/', '--single-process'], 600)
text = (OUT / 'namespace-fixed.log').read_text(errors='replace')
observed = re.findall(r'^(sharing-mode-and-namespace/[^\r\n]+)$', text, re.M)
assert set(observed) == set(SPEC['native_cases']) and len(observed) == len(SPEC['native_cases']) == 11, observed
assert len(re.findall(r'^11 passed, 0 failed, 0 todo$', text, re.M)) == 1
assert not re.search(r'^(FAIL |LEFT OUT )', text, re.M)
RECORD['native_cases'] = SPEC['native_cases']
RECORD['host_api_limits'] = 'One loaded image: same-image conversion/idempotence only; cross-image/mock-boundary runtime is unproven.'
save()
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
state('host')
assert binaries == binary_hashes()
RECORD.update(passed=True, binary_sha256=binaries, source_delta=SPEC['files'], cmake_cache_sha256=sha(BUILD / 'CMakeCache.txt'))
save()
