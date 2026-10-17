#!/usr/bin/env python3
"""One measured Bun consumer identity, reused unchanged by every qualification gate."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

INPUTS = Path(__file__).resolve().parent
CONFIG = json.loads((INPUTS.parent / 'variants.json').read_text())
LANE = 'bun-webkit-linux-amd64'
MANIFEST = 'scripts/build/deps/webkit-artifacts.json'
EXECUTABLE = 'bun/build/qualify-candidate/bun'
BASELINE_EXECUTABLE = 'bun-baseline/build/qualify-baseline/bun'
FIXTURE = 'bun/test/js/node/worker_threads/openclaw-resource-limits.test.ts'
FIXTURE_SHA256 = '2e925768c7625e093a3608cb0d47c33e1b2d591d16b485b2d7d30228e528b860'
BUILD_ENV = ('BUN_WEBKIT_ARTIFACT_MANIFEST', 'BUN_BUILD_PREFETCH_DIR', 'BUN_BUILD_CACHE_DIR')


def require(condition, message='invalid candidate identity'):
    if not condition:
        raise ValueError(message)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def file_record(root, path):
    file = root / path
    require(file.is_file() and not file.is_symlink(), 'identity file missing or linked: ' + path)
    return {'path': path, 'size': file.stat().st_size, 'sha256': sha(file)}


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


def engine_input(archive, lane_manifest, source):
    require(re.fullmatch('[0-9a-f]{40}', source) is not None)
    manifest = json.loads(lane_manifest.read_text())
    require(manifest['source'] == source and manifest['lane']['label'] == LANE)
    record = file_record(archive.parent, archive.name)
    require(record['path'] == LANE + '.tar.gz')
    require(manifest['files'][archive.name] == {'size': record['size'], 'sha256': record['sha256']})
    return {'source': source, 'lane': LANE, 'archive': record, 'lane_manifest_sha256': sha(lane_manifest)}


def overlay_manifest(engine):
    name = engine['archive']['path']
    return {'version': engine['source'], 'artifacts': {name: {
        'url': 'https://github.com/openclaw/WebKit/releases/download/autobuild-' + engine['source'] + '/' + name,
        'sha256': engine['archive']['sha256']}}}


def discover_build_inputs(repo, inspector_runtime):
    require(inspector_runtime is not None and inspector_runtime.is_absolute()
            and inspector_runtime.is_file() and os.access(inspector_runtime, os.X_OK), 'absolute source inspector required')
    module = (repo.resolve() / 'scripts/glob-sources.ts').as_uri()
    script = 'const {globAllSources}=await import(process.argv[1]);console.log(JSON.stringify([...new Set(Object.values(globAllSources()).flat())]));'
    return json.loads(subprocess.check_output([str(inspector_runtime), '--eval', script, module], cwd=repo, timeout=30))


def require_tracked_build_inputs(repo, inspector_runtime):
    # Ask the pinned build owner: ignored files can still enter native and JS globs.
    # Its own exclusions distinguish generated outputs from compiled source inputs.
    inventory = discover_build_inputs(repo, inspector_runtime)
    require(isinstance(inventory, list) and inventory and all(isinstance(path, str) for path in inventory),
            'invalid build source inventory')
    root = repo.resolve()
    tracked = {}
    for entry in git(repo, 'ls-files', '--stage', '-z').decode().split('\0'):
        if entry:
            metadata, name = entry.split('\t', 1)
            mode, _, stage = metadata.split()
            require(stage == '0', 'unmerged build source index')
            tracked[name] = mode

    def walk(parts, current=(), links=frozenset()):
        for part in parts:
            require((root.joinpath(*current)).is_dir(), 'invalid build source path')
            if part == '..':
                require(current, 'build source escapes checkout')
                current = current[:-1]
                continue
            path = root.joinpath(*current, part)
            relative = path.relative_to(root).as_posix()
            if stat.S_ISLNK(path.lstat().st_mode):
                # A tracked alias can expose tracked source, but every link in its
                # target must be reviewed too, including intermediate directories.
                require(tracked.get(relative) == '120000', 'untracked build input: ' + relative)
                require(relative not in links, 'cyclic build source alias')
                target = Path(os.readlink(path))
                if target.is_absolute():
                    target = target.relative_to(root)
                    current = ()
                current = walk(target.parts, current, links | {relative})
            else:
                current = (*current, part)
        return current

    for value in inventory:
        path = Path(value)
        require(path.is_absolute(), 'invalid build source path')
        try:
            parts = walk(path.relative_to(root).parts)
            canonical = root.joinpath(*parts)
            require(stat.S_ISREG(canonical.lstat().st_mode), 'invalid build source path')
        except OSError as error:
            raise ValueError('invalid build source path') from error
        require(tracked.get(canonical.relative_to(root).as_posix()) in ('100644', '100755'),
                'untracked build input: ' + str(path.relative_to(root)))


def source_identity(repo, engine, inspector_runtime):
    pin = CONFIG['candidate']
    commit, tree = git(repo, 'rev-parse', 'HEAD', 'HEAD^{tree}').decode().splitlines()
    index = git(repo, 'write-tree').decode().strip()
    require((commit, tree, index) == (pin['commit'], pin['tree'], pin['tree']))
    changed = git(repo, 'diff', '--name-only', '-z', 'HEAD').decode().strip('\0').split('\0')
    require(changed == [MANIFEST], 'candidate must have only the tracked manifest overlay')
    base_blob = git(repo, 'rev-parse', 'HEAD:' + MANIFEST).decode().strip()
    require(base_blob == pin['manifest_blob'])
    require(json.loads((repo / MANIFEST).read_text()) == overlay_manifest(engine), 'wrong candidate manifest overlay')
    patch = git(repo, 'diff', '--binary', 'HEAD', '--', MANIFEST)
    require_tracked_build_inputs(repo, inspector_runtime)
    return ({'repository': CONFIG['bun_repository'], 'commit': commit, 'tree': tree, 'index_tree': index},
            {'path': MANIFEST, 'base_blob': base_blob, 'sha256': sha(repo / MANIFEST),
             'patch_sha256': hashlib.sha256(patch).hexdigest(), 'tracked_changed_paths': changed})


def runtime(binary):
    env = {key: value for key, value in os.environ.items() if key not in BUILD_ENV}
    script = 'console.log(JSON.stringify({bun_revision:Bun.revision,webkit:process.versions.webkit,platform:process.platform,architecture:process.arch}))'
    return json.loads(subprocess.check_output([str(binary), '-e', script], env=env, timeout=30))


def baseline_inputs():
    pin = CONFIG['baseline']
    require(sha(INPUTS / 'upstream-artifacts.json') == pin['manifest_sha256'], 'baseline manifest drift')
    for name, digest in pin['patches'].items():
        require(sha(INPUTS / 'patches' / name) == digest, 'baseline patch drift')


def baseline_source(root, inspector_runtime):
    baseline_inputs()
    repo = root / 'bun-baseline'
    pin = CONFIG['baseline']
    require(git(repo, 'rev-parse', 'HEAD', 'HEAD^{tree}').decode().splitlines() == [pin['commit'], pin['tree']], 'baseline source drift')
    require(git(repo, 'write-tree').decode().strip() == pin['tree'], 'baseline index drift')
    patch = git(repo, 'diff', '--binary', 'HEAD')
    require(patch == (root / 'baseline-adapters.patch').read_bytes(), 'baseline build changed tracked source')
    require_tracked_build_inputs(repo, inspector_runtime)
    return hashlib.sha256(patch).hexdigest()


def capture_baseline(root, inspector_runtime):
    record = {'source': CONFIG['baseline'], 'tracked_patch_sha256': baseline_source(root, inspector_runtime),
              'executable': file_record(root, BASELINE_EXECUTABLE), 'runtime': runtime(root / BASELINE_EXECUTABLE)}
    validate_baseline(record)
    return record


def capture(root, engine, inspector_runtime):
    repo = root / 'bun'
    source, overlay = source_identity(repo, engine, inspector_runtime)
    fixture_relative = str(Path(FIXTURE).relative_to('bun'))
    require(not git(repo, 'ls-files', '--', fixture_relative), 'qualification fixture entered the compiled index')
    record = {'schema_version': 1, 'candidate': source, 'engine': engine, 'overlay': overlay,
              'executable': file_record(root, EXECUTABLE), 'runtime': runtime(root / EXECUTABLE),
              'fixture': file_record(root, FIXTURE), 'baseline': CONFIG['baseline']}
    validate(record, engine['source'])
    return record


def valid_digest(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def validate_file(record, path):
    require(set(record) == {'path', 'size', 'sha256'} and record['path'] == path
            and type(record['size']) is int and record['size'] > 0 and valid_digest(record['sha256']))


def validate_baseline(record):
    require(record['source'] == CONFIG['baseline'], 'invalid baseline identity')
    require(valid_digest(record['tracked_patch_sha256']), 'invalid baseline identity')
    validate_file(record['executable'], BASELINE_EXECUTABLE)
    require(record['runtime'] == {'bun_revision': CONFIG['baseline']['commit'], 'webkit': CONFIG['baseline']['engine'],
            'platform': 'linux', 'architecture': 'x64'}, 'invalid baseline runtime')


def validate(record, source, engine=None):
    pin = CONFIG['candidate']
    require(record['schema_version'] == 1 and record['candidate'] == {
        'repository': CONFIG['bun_repository'], 'commit': pin['commit'], 'tree': pin['tree'], 'index_tree': pin['tree']})
    measured = record['engine']
    require(measured['source'] == source and re.fullmatch('[0-9a-f]{40}', source) is not None
            and measured['lane'] == LANE and valid_digest(measured['lane_manifest_sha256']))
    validate_file(measured['archive'], LANE + '.tar.gz')
    if engine is not None:
        require(measured == engine, 'candidate archive identity mismatch')
    overlay = record['overlay']
    require(overlay['path'] == MANIFEST and overlay['base_blob'] == pin['manifest_blob']
            and overlay['tracked_changed_paths'] == [MANIFEST]
            and valid_digest(overlay['sha256']) and valid_digest(overlay['patch_sha256']))
    validate_file(record['executable'], EXECUTABLE)
    validate_file(record['fixture'], FIXTURE)
    require(record['fixture']['sha256'] == FIXTURE_SHA256)
    require(record['runtime'] == {'bun_revision': pin['commit'], 'webkit': source, 'platform': 'linux', 'architecture': 'x64'})
    require(record['baseline'] == CONFIG['baseline'])
    return record


def validate_evidence(record, source, engine, binaries, proof):
    validate(record, source, engine)
    require(file_record(binaries, EXECUTABLE) == record['executable'], 'candidate executable identity mismatch')
    require(file_record(binaries, FIXTURE) == record['fixture'], 'candidate fixture identity mismatch')
    require(sha(proof / 'candidate-manifest.patch') == record['overlay']['patch_sha256'], 'candidate overlay patch mismatch')
    manifest = proof / 'candidate-input/artifacts.json'
    require(sha(manifest) == record['overlay']['sha256'] and json.loads(manifest.read_text()) == overlay_manifest(engine), 'candidate overlay bytes mismatch')


def validate_baseline_evidence(record, binaries, proof):
    validate_baseline(record)
    require(file_record(binaries, BASELINE_EXECUTABLE) == record['executable'], 'baseline executable identity mismatch')
    require(sha(proof / 'baseline-adapters.patch') == record['tracked_patch_sha256'], 'baseline patch identity mismatch')


def verify(root, engine, receipt, inspector_runtime):
    record = json.loads(receipt.read_text())
    validate(record, engine['source'], engine)
    require(record == capture(root, engine, inspector_runtime), 'candidate identity changed after build')
    return record


def write_once(path, record):
    with path.open('x') as stream:
        stream.write(json.dumps(record, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['baseline-inputs', 'check-baseline', 'baseline', 'check-candidate', 'create', 'verify'])
    parser.add_argument('--root', type=Path)
    parser.add_argument('--source')
    parser.add_argument('--artifacts', type=Path)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--inspector-runtime', type=Path)
    args = parser.parse_args()
    if args.command == 'baseline-inputs':
        baseline_inputs()
    elif args.command == 'check-baseline':
        baseline_source(args.root, args.inspector_runtime)
    elif args.command == 'baseline':
        write_once(args.root / 'baseline-identity.json', capture_baseline(args.root, args.inspector_runtime))
    else:
        engine = engine_input(args.artifacts / (LANE + '.tar.gz'), args.artifacts / (LANE + '.manifest.json'), args.source)
        if args.command == 'check-candidate':
            source_identity(args.root / 'bun', engine, args.inspector_runtime)
        elif args.command == 'create':
            write_once(args.receipt, capture(args.root, engine, args.inspector_runtime))
        else:
            verify(args.root, engine, args.receipt, args.inspector_runtime)


if __name__ == '__main__':
    main()
