#!/usr/bin/env python3
"""Qualify the pinned Bun AOT consumer against an exact local engine checkout."""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
from xml.etree import ElementTree

SOURCE = Path('/work/source')
ENGINE = Path('/work/engine')
OUT = Path('/work/aot-proof')
INPUTS = Path(__file__).resolve().parent
BUN = 'fd40ba44187c721ee023062fa153a6a27560e6b1'
WEBKIT = '5ec9ac8557722128588184ed9cf77347d9a30cf1'
PIPELINE = '7b573c05d0c52dffc67d4d25daf108bed5930cf2'
BUILD = SOURCE / 'build/aot-linux-arm64'
LIMIT = 128 * 1024**2
STEPS = []
START = time.monotonic()
DEADLINE = START + 270 * 60
ENV = {k: v for k, v in os.environ.items() if not any(t in k.upper() for t in ('TOKEN', 'PASSWORD', 'SECRET'))}
ENV.update(CI='true', BUN_WEBKIT_PATH=str(ENGINE))


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], timeout=120).decode().strip()


def save():
    (OUT / 'proof.json').write_text(json.dumps({
        'passed': False, 'bun': BUN, 'webkit': WEBKIT, 'pipeline': PIPELINE,
        'steps': STEPS, 'seconds': time.monotonic() - START,
    }, indent=2) + '\n')


def run(name, command, seconds, env=None, expected=0):
    log = OUT / (name + '.log')
    started = time.monotonic()
    record = {'name': name, 'command': command, 'exitCode': None, 'timedOut': False}
    STEPS.append(record)
    save()
    with log.open('xb') as stream:
        proc = subprocess.Popen(command, cwd=SOURCE, env=env or ENV, stdin=subprocess.DEVNULL,
                                stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            while proc.poll() is None:
                if time.monotonic() >= min(started + seconds, DEADLINE):
                    record['timedOut'] = True
                    raise TimeoutError(name)
                if sum(p.stat().st_size for p in OUT.iterdir() if p.is_file()) > LIMIT:
                    raise RuntimeError('proof output exceeds 128 MiB')
                time.sleep(1)
        finally:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            stream.flush()
            record.update(exitCode=proc.returncode, seconds=time.monotonic() - started)
            save()
    assert proc.returncode == expected and not record['timedOut'], name
    assert log.stat().st_size <= LIMIT, name + ' oversized log'
    return log.read_text(errors='replace')


def source_state(adapted):
    assert git(SOURCE, 'rev-parse', 'HEAD') == BUN
    assert git(ENGINE, 'rev-parse', 'HEAD') == WEBKIT
    assert git(SOURCE, 'write-tree') == original_tree
    assert not git(ENGINE, 'diff', '--name-only', 'HEAD')
    changed = set(git(SOURCE, 'diff', '--name-only', 'HEAD').splitlines())
    assert changed == (set(spec['files']) if adapted else set()), changed
    for name, identity in spec['files'].items():
        path = SOURCE / name
        data = path.read_bytes()
        assert sha(path) == identity['after' if adapted else 'before'], name
        blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        assert blob == identity['adapted_blob' if adapted else 'base_blob'], name
        assert git(SOURCE, 'ls-files', '-s', '--', name).split()[0] == identity['mode']


def junit(path, expected=None):
    cases = list(ElementTree.parse(path).iter('testcase'))
    assert cases and all(not any(c.find(tag) is not None for tag in ('skipped', 'failure', 'error')) for c in cases)
    names = [c.get('name') for c in cases]
    assert len(names) == len(set(names)) and all(names)
    if expected is not None:
        assert names == [expected], names
    return names


OUT.mkdir(exist_ok=True)
assert git(Path('/work/pipeline'), 'rev-parse', 'HEAD') == PIPELINE
spec = json.loads((INPUTS / 'source-adapter.json').read_text())
assert spec['bun'] == BUN and spec['webkit'] == WEBKIT
assert len(spec['files']) == 8
assert sha(INPUTS / 'candidate.patch') == spec['patch_sha256']
original_tree = git(SOURCE, 'rev-parse', 'HEAD^{tree}')
source_state(False)
save()
jsc = ENGINE / 'Source/JavaScriptCore'
baseline = ['bun', 'run', str(jsc / 'aot/ir/generator/index.ts'), '--schema', str(jsc / 'aot/ir/AOTSchema.def')]
for name in [jsc / 'aot', SOURCE / 'src/aot', jsc / 'b3/B3Limits.h', jsc / 'ffi/JSFFICallback.cpp',
             jsc / 'runtime/AbstractModuleRecord.cpp', SOURCE / 'src/bundler/aot/data_values.rs',
             SOURCE / 'src/runtime/cli/compile_command/reports.rs']:
    baseline += ['--check-uses', str(name)]
text = run('baseline-generator', baseline, 120, expected=1)
assert re.search(r'(?:unknown|unexpected|unrecognized) (?:option|argument)[^\n]*check-uses', text, re.I), text[-2000:]
source_state(False)
run('apply-adapter', ['git', 'apply', '--check', str(INPUTS / 'candidate.patch')], 120)
run('apply-adapter-write', ['git', 'apply', str(INPUTS / 'candidate.patch')], 120)
source_state(True)
build_command = ['bun', 'scripts/build.ts', '--profile=release-local', '--webkit=local',
                 '--webkit-version=' + WEBKIT, '--aot=on', '--ci=on', '--buildkite=off',
                 '--os=linux', '--arch=aarch64', '--abi=gnu', '--build-dir=build/aot-linux-arm64', '-j2']
run('configure', [*build_command, '--configure-only'], 600)
source_state(True)
run('build', build_command, 14400)
source_state(True)
binary = BUILD / 'bun'
table = BUILD / 'codegen/aot_builtin_table.json'
assert all(p.is_file() and os.access(p, os.X_OK) for p in (binary, BUILD / 'jsc', BUILD / 'testaot'))
assert table.stat().st_size > 0
identities = {name: sha(BUILD / name) for name in ['bun', 'jsc', 'testaot', 'codegen/aot_builtin_table.json', 'build.ninja']}
internal_cases = {}
for name, file in [('build-contracts', 'build-aot-codegen-declared-outputs.test.ts'),
                   ('local-webkit-contracts', 'build-local-webkit.test.ts')]:
    xml = OUT / (name + '.xml')
    run(name, [str(binary), 'test', 'test/internal/' + file,
               '--reporter=junit', '--reporter-outfile=' + str(xml)], 600)
    internal_cases[file] = junit(xml)
    assert len(internal_cases[file]) >= 10
source_state(True)
run('restore-source', ['git', 'restore', '--source=' + BUN, '--worktree', '--', *spec['files']], 120)
source_state(False)
cases = []
for part, name in [('calls-of-proxies', 'strict--empty--two'), ('calls-of-proxies', 'strict--trap--method'),
                   ('builtin-modules', 'async-local-storage-get-store')]:
    expected = part + '/' + name
    case_env = dict(ENV, TEST_PART='aot/' + part, AOT_PROGRAMS=expected, AOT_SHARE='all',
                    AOT_PROGRAMS_JOBS='1', AOT_BUILTIN_TABLE=str(table))
    xml = OUT / (name + '.xml')
    text = run(name, [str(binary), 'test', 'test/aot/parts.test.ts', '--reporter=junit',
                      '--reporter-outfile=' + str(xml)], 600, env=case_env)
    assert not re.search(r'(?:SKIPPED:|TODO:|SHARE:|NOT THROUGH:)', text), expected
    cases += junit(xml, expected)
    source_state(False)
assert identities == {name: sha(BUILD / name) for name in identities}
result = json.loads((OUT / 'proof.json').read_text())
result.update(passed=True, binary_sha256=identities, program_cases=cases, build_contract_cases=internal_cases,
              patch_sha256=spec['patch_sha256'], source_tree=original_tree)
(OUT / 'proof.json').write_text(json.dumps(result, indent=2) + '\n')
