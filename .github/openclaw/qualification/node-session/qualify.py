#!/usr/bin/env python3
"""Prove the constructor-session fix using real, source-bound Node builds."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

# This path also runs after build/test failures; only its bounded final archive is uploaded.
if len(sys.argv) == 4 and sys.argv[1] == '--pack':
    root, target = Path(sys.argv[2]), Path(sys.argv[3])
    files = sorted(root.iterdir())
    if not files or len(files) > 12 or any(not p.is_file() or p.is_symlink() for p in files):
        raise ValueError('unexpected Node proof evidence file set')
    if sum(p.stat().st_size for p in files) > 256 * 1024 ** 2:
        raise ValueError('Node proof raw evidence exceeds 256 MiB')
    manifest = {}
    for p in files:
        with p.open('rb') as stream:
            manifest[p.name] = {'size': p.stat().st_size,
                                'sha256': hashlib.file_digest(stream, 'sha256').hexdigest()}
    pending = target.with_suffix(target.suffix + '.pending')
    with tarfile.open(pending, 'w:gz', compresslevel=6) as archive:
        for p in files:
            archive.add(p, arcname=p.name, recursive=False)
        content = (json.dumps(manifest, indent=2) + '\n').encode()
        record = tarfile.TarInfo('archive-manifest.json');record.size = len(content)
        archive.addfile(record, io.BytesIO(content))
    if pending.stat().st_size > 32 * 1024 ** 2:
        raise ValueError('Node proof archive exceeds 32 MiB; pending archive will not be uploaded')
    with pending.open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    pending.rename(target)
    print('Node proof archive SHA256 ' + sha)
    raise SystemExit(0)

PIN = 'd44625a4b80c672215b469906ce583ce7eeeebaf'
WRAP = 'lib/internal/tls/wrap.js'
BASE_BLOBS = {WRAP: '82f343de726023a1ed85c98340235c372b3d1089',
              'src/crypto/crypto_common.cc': '759353f08f035f3a805f01cecfad3e2aee6d21f7'}
INPUTS = Path(__file__).resolve().parent
SOURCE = Path(sys.argv[1]).resolve()
OUTPUT = Path(sys.argv[2]).resolve()
BASELINE = Path(sys.argv[3]).resolve()
OUTPUT.mkdir(parents=True, exist_ok=False)
GIB = 1024 ** 3
BUILD_TIMEOUTS = {'patched': 10800}
memory = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                  if line.startswith('MemTotal:'))) * 1024
cgroup_limit = Path('/sys/fs/cgroup/memory.max')
if cgroup_limit.exists() and cgroup_limit.read_text().strip().isdigit():
    memory = min(memory, int(cgroup_limit.read_text()))
jobs = min(4, os.cpu_count() or 1, max(1, memory // (3 * GIB)))
env = {key: value for key, value in os.environ.items()
       if key not in ('GH_TOKEN', 'GITHUB_TOKEN', 'ACTIONS_RUNTIME_TOKEN',
                      'ACTIONS_ID_TOKEN_REQUEST_TOKEN')}
env.update(CC='gcc', CXX='g++', CARGO_BUILD_JOBS=str(jobs))


def command(argv, **kwargs):
    return subprocess.run(argv, cwd=SOURCE, env=env, check=True, **kwargs)


def git(*args):
    return subprocess.check_output(['git', *args], cwd=SOURCE).decode().strip()


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(name, value):
    with (OUTPUT / name).open('x') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')


def build(arm):
    try:
        with (OUTPUT / (arm + '-build.log')).open('x') as stream:
            command(['/usr/bin/time', '-v', 'make', '-j' + str(jobs)],
                    stdout=stream, stderr=subprocess.STDOUT, timeout=BUILD_TIMEOUTS[arm])
    finally:
        # Check after either build outcome. Transient products stay on this disposable runner.
        size = int(subprocess.check_output(['du', '-sk', str(SOURCE)]).split()[0]) * 1024
        if size > 24 * GIB:
            raise ValueError('Node source/build workspace exceeded its 24-GiB budget')
    executable = SOURCE / 'out/Release/node'
    script = """
const crypto = require('node:crypto');
console.log(JSON.stringify({
  version: process.version, platform: process.platform, arch: process.arch,
  openssl: process.versions.openssl,
  builtin_sha256: crypto.createHash('sha256')
    .update(process.binding('natives')['internal/tls/wrap']).digest('hex')
}));
"""
    identity = json.loads(subprocess.check_output(
        [str(executable), '--no-warnings', '-e', script], cwd=SOURCE, env=env))
    if identity['platform'] != 'linux' or identity['arch'] != 'x64':
        raise ValueError('native Linux x64 Node required')
    if identity['builtin_sha256'] != digest(SOURCE / WRAP):
        raise ValueError('built Node does not embed the measured TLS owner source')
    identity.update(source=PIN, executable_sha256=digest(executable),
                    workspace_bytes=size)
    write(arm + '-identity.json', identity)
    return executable, identity


def probe(executable, arm):
    with (OUTPUT / (arm + '-test.log')).open('x') as stream:
        result = subprocess.run([str(executable), '--expose-internals', 'test/parallel/test-tls-session-constructor.js'],
                                cwd=SOURCE, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=120)
    return check_probe(arm, result.returncode)


def check_probe(arm, exit_code):
    lines = (OUTPUT / (arm + '-test.log')).read_text().splitlines()
    rows = [json.loads(line.removeprefix('SESSION_CASE ')) for line in lines
            if line.startswith('SESSION_CASE ')]
    if arm == 'base':
        if not (exit_code == 1 and len(rows) == 1
                and rows[0] == {'label': 'TLSv1.2/buffer/connected/explicit SNI',
                                'version': 'TLSv1.2', 'connected': True,
                                'expectedReuse': True, 'reused': False}):
            raise ValueError('base did not reproduce the constructor resumption failure')
    else:
        summaries = [json.loads(line.removeprefix('SESSION_RESULT ')) for line in lines
                     if line.startswith('SESSION_RESULT ')]
        fallback = [line for line in lines if line.startswith('SESSION_FALLBACK ')]
        keys = {(row['label'], row['version'], row['connected']) for row in rows}
        if not (exit_code == 0 and len(rows) == len(keys) == 80
                and all(row['reused'] is row['expectedReuse'] for row in rows)
                and summaries == [{'passed': True, 'cases': 82}]
                and set(fallback) == {'SESSION_FALLBACK TLSv1.2', 'SESSION_FALLBACK TLSv1.3'}
                and len(fallback) == 2):
            raise ValueError('patched Node constructor/identity/handle-swap matrix incomplete')
    return {'exit_code': exit_code, 'reported_cases': len(rows)}


if git('rev-parse', 'HEAD') != PIN or git('status', '--porcelain'):
    raise ValueError('Node source checkout is not the pristine frozen revision')
if any(git('rev-parse', 'HEAD:' + name) != blob for name, blob in BASE_BLOBS.items()):
    raise ValueError('Node TLS source blob drift')
patch = INPUTS / 'constructor-session.patch'
fixture = INPUTS / 'test-tls-session-constructor.js'
# Reuse the already observed red baseline; its native build and fixture inputs are frozen.
if digest(BASELINE) != 'e7b9f513cfc578c97a1462d9762187a3968f0c17e7aff20ec6ed8d83f16ddcf2':
    raise ValueError('baseline ZIP digest mismatch')
with zipfile.ZipFile(BASELINE) as archive:
    if archive.namelist() != ['node-session-proof.tar.gz']:
        raise ValueError('unexpected baseline ZIP entries')
    info = archive.getinfo('node-session-proof.tar.gz')
    if info.file_size > 32 * 1024**2:
        raise ValueError('baseline archive exceeds size budget')
    data = archive.read(info)
if hashlib.sha256(data).hexdigest() != 'bd4aded401d008b538e669af6b1403ef8e50c5dbc58566f11810f0da847c000f':
    raise ValueError('baseline TAR digest mismatch')
with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
    entries = archive.getmembers()
    expected = {'archive-manifest.json', 'inputs.json', 'tools.log', 'configure.log',
                'base-build.log', 'base-identity.json', 'base-test.log',
                'patched-build.log', 'patched-identity.json', 'patched-test.log'}
    if (len(entries) != len(expected) or {entry.name for entry in entries} != expected
            or any(not entry.isfile() for entry in entries)
            or sum(entry.size for entry in entries) > 256 * 1024**2):
        raise ValueError('unexpected baseline TAR inventory')
    contents = {entry.name: archive.extractfile(entry).read() for entry in entries}
manifest = json.loads(contents.pop('archive-manifest.json'))
if set(manifest) != set(contents):
    raise ValueError('baseline manifest inventory mismatch')
for name, content in contents.items():
    if (len(content) != manifest[name]['size']
            or hashlib.sha256(content).hexdigest() != manifest[name]['sha256']):
        raise ValueError('baseline manifest mismatch: ' + name)
prior_inputs = json.loads(contents['inputs.json'])
base_identity = json.loads(contents['base-identity.json'])
if (prior_inputs['source'] != PIN or prior_inputs['fixture_sha256'] != digest(fixture)
        or base_identity['source'] != PIN
        or base_identity['builtin_sha256'] != digest(SOURCE / WRAP)
        or '\tExit status: 0' not in contents['base-build.log'].decode()):
    raise ValueError('baseline source, embedded wrapper, fixture or successful build mismatch')
for name in ('base-build.log', 'base-identity.json', 'base-test.log'):
    (OUTPUT / name).write_bytes(contents[name])
base_result = check_probe('base', 1)
write('baseline-provenance.json', {
    'kind': 'prior-run-baseline', 'run': 41183895846, 'artifact': 13039247663,
    'producer': 'e1fd554b61300f5853c9ce6f9629a6205de8ec0e',
    'zip_sha256': digest(BASELINE), 'tar_sha256': hashlib.sha256(data).hexdigest(),
    'inputs': prior_inputs, 'files': {name: manifest[name] for name in
        ('base-build.log', 'base-identity.json', 'base-test.log')}})
destination = SOURCE / 'test/parallel' / fixture.name
if destination.exists():
    raise ValueError('refusing to replace an existing Node test')
shutil.copyfile(fixture, destination)
write('inputs.json', {'source': PIN, 'patch_sha256': digest(patch),
                      'fixture_sha256': digest(fixture), 'compiler_jobs': jobs,
                      'memory_bytes': memory, 'build_timeout_seconds': BUILD_TIMEOUTS,
                      'workspace_post_build_max_bytes': 24 * GIB,
                      'artifact_max_bytes': 32 * 1024 ** 2,
                      'artifact_max_input_bytes': 256 * 1024 ** 2, 'artifact_max_input_files': 12})
with (OUTPUT / 'tools.log').open('x') as stream:
    for argv in (['gcc', '--version'], ['g++', '--version'], ['python3', '--version'],
                 ['make', '--version'], ['rustc', '--version']):
        command(argv, stdout=stream, stderr=subprocess.STDOUT)
command(['git', 'apply', '--check', str(patch)])
command(['git', 'apply', str(patch)])
if git('diff', '--name-only').splitlines() != sorted(BASE_BLOBS):
    raise ValueError('Node patch changed an unexpected tracked source')
patched_source_sha256 = {name: digest(SOURCE / name) for name in BASE_BLOBS}
with (OUTPUT / 'configure.log').open('x') as stream:
    command(['./configure', '--without-npm'], stdout=stream, stderr=subprocess.STDOUT)
patched, patched_identity = build('patched')
if patched_identity['executable_sha256'] == base_identity['executable_sha256']:
    raise ValueError('patched Node executable did not change')
if any(patched_identity[key] != base_identity[key]
       for key in ('version', 'platform', 'arch', 'openssl')):
    raise ValueError('Node build platform or linked OpenSSL drift')
patched_result = probe(patched, 'patched')
with (OUTPUT / 'siblings.log').open('x') as stream:
    command(['python3', 'tools/test.py', '--mode=release', '--timeout=120',
             'parallel/test-tls-session-reuse-different-servername',
             'parallel/test-tls-session-reuse-provided-socket',
             'parallel/test-tls-secure-session',
             'parallel/test-tls-session-constructor',
             'parallel/test-tls-peer-certificate-repeated-reads'],
            stdout=stream, stderr=subprocess.STDOUT, timeout=600)
if digest(destination) != digest(fixture):
    raise ValueError('Node test fixture changed during qualification')
if (git('diff', '--name-only').splitlines() != sorted(BASE_BLOBS)
        or {name: digest(SOURCE / name) for name in BASE_BLOBS} != patched_source_sha256):
    raise ValueError('Node source changed during qualification')
write('gate.json', {'passed': True, 'source': PIN, 'base': base_result,
                    'patched': patched_result, 'sibling_files': 5,
                    'patched_sources': patched_source_sha256,
                    'baseline_kind': 'prior-run-baseline',
                    'baseline_provenance_sha256': digest(OUTPUT / 'baseline-provenance.json'),
                    'inputs_sha256': digest(OUTPUT / 'inputs.json'),
                    'base_identity_sha256': digest(OUTPUT / 'base-identity.json'),
                    'patched_identity_sha256': digest(OUTPUT / 'patched-identity.json')})
print('native constructor-session prior baseline/fresh patched and sibling proof passed')
