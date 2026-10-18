#!/usr/bin/env python3
"""Apply and restore the fixed build/test harness adapters without changing compile pins."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
if __package__:
    from . import consumer_identity as identity
else:
    import consumer_identity as identity


def source(root, arm, engine, inspector):
    if arm == 'baseline':
        identity.baseline_source(root, inspector)
    else:
        identity.source_identity(root / 'bun', engine, inspector)


def state(repo, arm, spec):
    pin = identity.CONFIG[arm]
    identity.require(identity.git(repo, 'rev-parse', 'HEAD', 'HEAD^{tree}').decode().splitlines()
                     == [pin['commit'], pin['tree']], 'adapter source drift')
    index = identity.git(repo, 'write-tree').decode().strip()
    identity.require(index == pin['tree'], 'adapter index drift')
    patch = identity.git(repo, 'diff', '--binary', 'HEAD', '--', '.',
                         *[':(exclude)' + path for path in spec['files']])
    return {'index_tree': index, 'other_patch_sha256': hashlib.sha256(patch).hexdigest()}


def files(repo, spec, stage):
    for path, record in spec['files'].items():
        file = repo / path
        identity.require(file.is_file() and not file.is_symlink()
                         and identity.sha(file) == record[stage]
                         and stat.S_IMODE(file.stat().st_mode) == int(record['mode'], 8) & 0o777,
                         'unexpected harness bytes or mode: ' + path)


def excluded_inputs(repo, spec, inspector):
    identity.require_tracked_build_inputs(repo, inspector)
    inventory = identity.discover_build_inputs(repo, inspector)
    inputs = {Path(path).resolve() for path in inventory}
    identity.require(not any((repo / path).resolve() in inputs for path in spec['files']),
                     'harness adapter enters compiled source inventory')
    return hashlib.sha256(json.dumps(sorted(str(path.relative_to(repo.resolve())) for path in inputs)).encode()).hexdigest()


def measured_identity(root, arm, engine, inspector):
    path = root / (arm + '-identity.json')
    record = json.loads(path.read_text())
    measured = (identity.capture_baseline(root, inspector) if arm == 'baseline'
                else identity.capture(root, engine, inspector))
    identity.require(record == measured, 'consumer identity changed around test invocation')
    return identity.file_record(root, path.name), record['executable']


def prepare(root, name, phase, engine, inspector, command, prefix=None):
    arm = 'baseline' if name == 'baseline' else 'candidate'
    identity.require(phase != 'build' or name != 'sync', 'invalid build arm')
    repo = root / ('bun-baseline' if arm == 'baseline' else 'bun')
    spec = identity.adapter_spec(arm, phase)
    receipt = root / (arm + '-build-tools.json' if phase == 'build' else name + '/invocation.json')
    pending = receipt.with_suffix('.pending.json')
    identity.require(not receipt.exists() and not pending.exists(), 'adapter receipt already exists')
    source(root, arm, engine, inspector)
    files(repo, spec, 'before')
    record = {'schema_version': 1, 'arm': arm, 'phase': phase, 'source': identity.CONFIG[arm],
              'adapter': spec, 'restored': False, 'before': state(repo, arm, spec),
              'compiled_inputs_sha256': excluded_inputs(repo, spec, inspector),
              'argv': command, 'cwd': str(repo)}
    if phase == 'build':
        record['engine_source'] = identity.CONFIG['baseline']['engine'] if arm == 'baseline' else engine['source']
        record['bootstrap'] = identity.file_record(Path('/'), str(inspector))
    if phase == 'test':
        record['identity'], record['executable'] = measured_identity(root, arm, engine, inspector)
        record['selection'] = identity.file_record(root, name + '/selected.json')
        identity.require((repo / 'build/openclaw-ci/selected.json').read_bytes()
                         == (root / record['selection']['path']).read_bytes(), 'helper selection mismatch')
        identity.require((name == 'sync' and isinstance(prefix, str)
                          and re.fullmatch('openclaw-sync-junit-[0-9a-f]{32}-', prefix))
                         or (name != 'sync' and prefix is None), 'invalid invocation reporting mode')
        for filename in ('results.json', 'runner-terminal.json', 'wrapper-terminal.json', 'net-direct.json'):
            identity.require(not (root / name / filename).exists(), 'stale invocation evidence: ' + filename)
    subprocess.run(['git', '-C', str(repo), 'apply', '--check', str(identity.INPUTS / spec['patch'])], check=True)
    # A non-restored receipt is never accepted as evidence, including after interruption.
    identity.write_once(pending, record)
    return record, identity.sha(pending), pending.stat().st_ino


def restore(root, name, phase, engine, inspector, status, active, completed):
    arm = 'baseline' if name == 'baseline' else 'candidate'
    repo = root / ('bun-baseline' if arm == 'baseline' else 'bun')
    spec = identity.adapter_spec(arm, phase)
    receipt = root / (arm + '-build-tools.json' if phase == 'build' else name + '/invocation.json')
    pending = receipt.with_suffix('.pending.json')
    record, digest, inode = active
    identity.require(pending.is_file() and not pending.is_symlink() and pending.stat().st_ino == inode
                     and identity.sha(pending) == digest, 'active adapter receipt changed')
    identity.require(record['schema_version'] == 1 and record['arm'] == arm and record['phase'] == phase
                     and record['source'] == identity.CONFIG[arm] and record['adapter'] == spec
                     and record['restored'] is False, 'wrong active adapter receipt')
    # Never overwrite a modified adapter or unrelated source while unwinding an invocation.
    try:
        files(repo, spec, 'after')
    except ValueError:
        # A failed atomic apply may leave the original bytes; unknown bytes stay visible.
        files(repo, spec, 'before')
        identity.require(not completed, 'adapter unexpectedly absent after execution')
        adapted = False
    else:
        adapted = True
    identity.require(state(repo, arm, spec) == record['before'], 'source changed during adapted phase')
    identity.require(excluded_inputs(repo, spec, inspector) == record['compiled_inputs_sha256'],
                     'compiled source inventory changed during adapted phase')
    if adapted:
        subprocess.run(['git', '-C', str(repo), 'apply', '--reverse', '--check', str(identity.INPUTS / spec['patch'])], check=True)
        subprocess.run(['git', '-C', str(repo), 'apply', '--reverse', str(identity.INPUTS / spec['patch'])], check=True)
    files(repo, spec, 'before')
    source(root, arm, engine, inspector)
    record['after'] = state(repo, arm, spec)
    identity.require(record['after'] == record['before'], 'source restoration mismatch')
    if completed and phase == 'build':
        record['status'] = status
        path = identity.BASELINE_EXECUTABLE if arm == 'baseline' else identity.EXECUTABLE
        record['executable'] = identity.file_record(root, path) if (root / path).is_file() else None
    elif completed:
        consumer, executable = measured_identity(root, arm, engine, inspector)
        identity.require((consumer, executable) == (record['identity'], record['executable']), 'test changed consumer identity')
        identity.require(identity.file_record(root, name + '/selected.json') == record['selection'], 'selection changed during test')
        record['evidence'] = {filename: identity.file_record(root, name + '/' + filename)
                              if (root / name / filename).is_file() else None
                              for filename in ('results.json', 'runner-terminal.json', 'wrapper-terminal.json', 'net-direct.json')}
    identity.require(pending.is_file() and not pending.is_symlink() and pending.stat().st_ino == inode
                     and identity.sha(pending) == digest, 'pending adapter receipt changed')
    pending.unlink()
    if completed:
        record['restored'] = True
        identity.write_once(receipt, record)


def run(root, name, phase, engine, inspector, prefix=None):
    arm = 'baseline' if name == 'baseline' else 'candidate'
    repo = root / ('bun-baseline' if arm == 'baseline' else 'bun')
    env = os.environ.copy()
    if phase == 'build':
        revision = identity.CONFIG['baseline']['engine'] if arm == 'baseline' else engine['source']
        command = [str(inspector), 'run', 'build:release', '--lto=off', '--webkit-version=' + revision,
                   '--buildDir=' + str(repo / 'build' / ('qualify-' + arm)), '--timings']
        for key in ('GITHUB_SHA', 'BUILDKITE_COMMIT', 'GIT_SHA'):
            env.pop(key, None)
        log = root / ('build-' + arm + '.log')
    else:
        executable = identity.BASELINE_EXECUTABLE if arm == 'baseline' else identity.EXECUTABLE
        command = [str(root / executable), 'scripts/openclaw-ci/tests.ts', 'test']
        if prefix is not None:
            command += ['--junit-prefix', prefix]
        for key in identity.BUILD_ENV:
            env.pop(key, None)
        if name != 'sync':
            env.update(HOME=str(root / name / 'home'), TMPDIR=str(root / name / 'tmp'),
                       PATH=str(root / name / 'bin') + os.pathsep + env['PATH'], OPENCLAW_CI_PLATFORM='linux')
        else:
            identity.require(env.get('HOME') == str(root / name / 'home')
                             and env.get('TMPDIR') == str(root / name / 'tmp')
                             and env['PATH'].startswith(str(root / name / 'bin') + os.pathsep)
                             and env.get('OPENCLAW_CI_PLATFORM') == 'linux', 'sync environment drift')
        log = root / name / 'tests.log'
    active = prepare(root, name, phase, engine, inspector, command, prefix)
    status, completed = None, False
    try:
        spec = active[0]['adapter']
        subprocess.run(['git', '-C', str(repo), 'apply', str(identity.INPUTS / spec['patch'])], check=True)
        files(repo, spec, 'after')
        identity.require(state(repo, arm, spec) == active[0]['before'], 'source changed while applying adapter')
        if phase == 'test':
            for filename in ('results.json', 'runner-terminal.json', 'net-direct.json'):
                (repo / 'build/openclaw-ci' / filename).unlink(missing_ok=True)
        with log.open('x') as stream:
            try:
                status = subprocess.run(command, cwd=repo, env=env, stdout=stream, stderr=subprocess.STDOUT).returncode
            except OSError as error:
                stream.write('Failed to start fixed qualification command: ' + type(error).__name__ + '\n')
        if phase == 'test':
            identity.write_once(root / name / 'wrapper-terminal.json', {'status': status})
            for filename in ('results.json', 'runner-terminal.json', 'net-direct.json'):
                path = 'build/openclaw-ci/' + filename
                if (repo / path).exists():
                    identity.file_record(repo, path)
                    with (root / name / filename).open('xb') as output:
                        output.write((repo / path).read_bytes())
        completed = True
    finally:
        restore(root, name, phase, engine, inspector, status, active, completed)
    return status if status is not None and status >= 0 else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['build', 'test'])
    parser.add_argument('--name', choices=['baseline', 'candidate', 'sync'], required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--inspector-runtime', type=Path, required=True)
    parser.add_argument('--junit-prefix')
    args = parser.parse_args()
    engine = identity.engine_input(args.artifacts / (identity.LANE + '.tar.gz'),
                                   args.artifacts / (identity.LANE + '.manifest.json'), args.source)
    return run(args.root, args.name, args.phase, engine, args.inspector_runtime, args.junit_prefix)


if __name__ == '__main__':
    raise SystemExit(main())
