#!/usr/bin/env python3
"""Owned packaging and provenance around the pinned upstream lane runner."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

BASE = '1600131e46b5af48bbda3559af8d8a3327230b6e'
ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / '.github/openclaw/variants.json').read_text())
RECIPE = ['.github/scripts/lanes.mjs', 'Dockerfile', 'Dockerfile.musl', 'Dockerfile.macos', 'Dockerfile.windows', 'icu', 'macos-cross']
# Keep the engine comparison BASE; admit only this reviewed Node security update.
# Tree identities include file modes and every descendant of recipe directories.
RECIPE_REVISION = {'reviewed_source':'87b224c8cb5510b638f48130722ffc7a6a616c0d',
    'tree_sha256':'fabc54c96a4f33f485be7964cbe55f4ef88838db6ad5713e5abe1b515b99c6da'}

def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)

def capture(*args):
    return subprocess.check_output(args, text=True).strip()

def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')

def source():
    sha = capture('git', 'rev-parse', 'HEAD')
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('full source SHA required')
    run('git', 'merge-base', '--is-ancestor', BASE, sha)
    recipe = subprocess.check_output(['git', 'ls-tree', '--full-tree', '-z', sha, '--', *RECIPE])
    if hashlib.sha256(recipe).hexdigest() != RECIPE_REVISION['tree_sha256']:
        raise ValueError('source recipe differs from the reviewed revision')
    run('git', 'diff', '--exit-code', 'HEAD')
    return sha

def lane_definitions():
    return json.loads(capture('node', '.github/scripts/lanes.mjs', '--json'))

def preflight():
    sha = source()
    if sha != os.environ['INPUT_SHA'] or sha != os.environ['GITHUB_SHA']:
        raise ValueError('dispatch must use the same reviewed branch head and full input SHA')
    if os.environ['GITHUB_REF'] not in ('refs/heads/openclaw/main', 'refs/heads/openclaw/batch-1'):
        raise ValueError('only an explicitly permitted owned branch may run this workflow')
    upstream = {l['label'] for l in lane_definitions()}
    wanted = [l['label'] for l in CONFIG['lanes']]
    if len(set(wanted)) != len(wanted) or not set(wanted) <= upstream:
        raise ValueError('invalid or duplicate lane selection')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        f.write('matrix=' + json.dumps({'include': [{'lane': l} for l in wanted]}, separators=(',', ':')) + '\n')

def build(label, destination):
    sha = source()
    if label not in [l['label'] for l in CONFIG['lanes']]:
        raise ValueError('lane is outside the approved consumer matrix')
    lane = next(l for l in lane_definitions() if l['label'] == label)
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    artifact = destination / 'bun-webkit'
    provenance = destination / 'provenance'
    provenance.mkdir()
    command = json.loads(capture('node', '.github/scripts/lanes.mjs', 'build', label, '--output', str(artifact), '--dry-run'))
    # Build the pinned recipe base locally. No image registry write or inherited workflow is used.
    base_tag = 'openclaw-webkit-toolchain:' + hashlib.sha256(lane['image'].encode()).hexdigest()[:24]
    base_command = command[:command.index('--target=artifact')] + ['--target=base', '--load', '--tag', base_tag, '--metadata-file', str(provenance/'toolchain-build.json'), '.']
    run('docker', 'buildx', 'use', 'default')
    started = time.time()
    run(*base_command)
    image = json.loads(capture('docker', 'image', 'inspect', base_tag))[0]
    write(provenance/'toolchain-image.json', {k:image.get(k) for k in ['Id','RepoDigests','Architecture','Os','Created']})
    tool_versions = capture('docker', 'run', '--rm', base_tag, 'sh', '-c', 'clang --version && cmake --version && ninja --version')
    (provenance/'tool-versions.txt').write_text(tool_versions+'\n')
    # Metadata is an output-only addition to upstream's generated argv, with identical lane settings.
    build_command = json.loads(capture('node', '.github/scripts/lanes.mjs', 'build', label, '--output', str(artifact), '--base-image', base_tag, '--dry-run'))
    build_command[-1:-1] = ['--metadata-file', str(provenance/'artifact-build.json')]
    run(*build_command)
    with (artifact/'include/cmakeconfig.h').open('a') as f:
        f.write('\n#define BUN_WEBKIT_VERSION "'+sha+'"\n')
    write(artifact/'package.json', {'name':label,'version':'0.0.1-'+sha,'os':[lane['package_os']],'cpu':[lane['package_cpu']],'repository':'https://github.com/openclaw/WebKit'})
    for path in (artifact/'lib').glob('*.so*'):
        if path.is_file() or path.is_symlink():
            path.unlink()
    archive = destination/(label+'.tar.gz')
    run('tar', '-czf', str(archive), '-C', str(destination), 'bun-webkit')
    paths = capture('git', 'ls-files', '--', *RECIPE).splitlines()
    patches = []
    for commit in capture('git','rev-list','--reverse',BASE+'..'+sha).splitlines():
        patch = subprocess.check_output(['git','show','--format=','--binary',commit])
        patches.append({'commit':commit,'subject':capture('git','show','-s','--format=%s',commit),'patch_sha256':hashlib.sha256(patch).hexdigest()})
    manifest = {'schema_version':1,'source':sha,'base':BASE,'recipe_revision':RECIPE_REVISION,'lane':lane,'patches':patches,
        'recipe_sha256':{p:digest(ROOT/p) for p in paths},'toolchain_image_id':image['Id'],
        'commands':{'base':base_command,'artifact':build_command},
        'tool_versions':tool_versions,'docker_version':capture('docker','version'),'buildx_version':capture('docker','buildx','version'),
        'workflow_run':os.environ.get('GITHUB_RUN_ID'),'run_attempt':os.environ.get('GITHUB_RUN_ATTEMPT'),
        'elapsed_seconds':time.time()-started,'files':{archive.name:{'sha256':digest(archive),'size':archive.stat().st_size}},
        'provenance_files':{p.name:digest(p) for p in provenance.iterdir() if p.is_file()}}
    write(destination/(label+'.manifest.json'), manifest)
    (destination/'SHA256SUMS').write_text(digest(archive)+'  '+archive.name+'\n')
    if label == 'bun-webkit-linux-amd64':
        run(str(artifact/'bin/jsc'), '-e', 'print("OpenClaw WebKit ready")')
        run(str(artifact/'bin/testFFI'))
        run(str(artifact/'bin/testMimallocExit'))
        run(str(artifact/'bin/testMimallocExitInFlight'))
        run(str(artifact/'bin/testVMEntryRecord'))
        run(str(artifact/'bin/testVMEntryScope'))
        run(str(artifact / 'bin/testForeignStackSuspension'))
    shutil.rmtree(artifact)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('command',choices=['preflight','build'])
    p.add_argument('--lane')
    p.add_argument('--output',type=Path)
    a=p.parse_args()
    os.chdir(ROOT)
    if a.command=='preflight': preflight()
    else: build(a.lane,a.output)

if __name__ == "__main__":
    main()
