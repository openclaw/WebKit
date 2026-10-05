#!/usr/bin/env python3
"""Matched diagnostic scheduling window; cores remain local and are deleted by capture."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

p = argparse.ArgumentParser()
for name in ['build', 'output', 'cores']:
    p.add_argument('--' + name, type=Path, required=True)
a = p.parse_args()
a.build = a.build.resolve()
a.output = a.output.resolve()
a.cores = a.cores.resolve()
a.output.mkdir(parents=True, exist_ok=True)
root = Path.cwd()
allocator = root / 'Source/bmalloc/mimalloc/mimalloc'
key_file = allocator / 'src/prim/unix/prim.c'
summary = {'diagnostic_only': True, 'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(), 'candidate': json.loads((root / '.github/openclaw/exit-key-candidate.json').read_text()), 'arms': {}}

def command(args, log, expected=0, timeout=300):
    with log.open('w') as stream:
        result = subprocess.run([str(x) for x in args], stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode != expected:
        raise RuntimeError(f'{log.name}: expected exit {expected}, got {result.returncode}')

def native(arm):
    out = a.output / arm
    out.mkdir(exist_ok=True)
    tests = root / '.github/openclaw/exit-key-tests'
    flags = ['clang-23', '-O2', '-g', '-DNDEBUG', '-I' + str(allocator / 'include')]
    command([*flags, tests / 'test-exit.c', allocator / 'src/static.c', '-lpthread', '-ldl', '-lrt', '-o', out / 'late'], out / 'late-build.log')
    command([*flags, '-DMI_TEST_THREAD_KEY_WAIT=1', '-Dpthread_setspecific=mimalloc_test_setspecific', '-Dpthread_key_delete=mimalloc_test_key_delete', '-c', allocator / 'src/static.c', '-o', out / 'hooks.o'], out / 'hooks-build.log')
    command([*flags, tests / 'test-exit-in-flight.c', out / 'hooks.o', '-lpthread', '-ldl', '-lrt', '-o', out / 'inflight'], out / 'inflight-build.log')
    for test in ['late', 'inflight']:
        command([out / test], out / (test + '.log'), expected=1 if arm == 'baseline' else 0, timeout=30)

def replay(arm):
    out = a.output / arm
    command([sys.executable, root / '.github/openclaw/exit-mutex-diagnostic.py', '--binary', a.build / 'bin/jsc', '--fixture', root / 'JSTests/stress/masquerader-as-function-in-promise.js', '--output', out, '--cores', a.cores], out / 'driver.log', timeout=1300)
    data = json.loads((out / 'replay.json').read_text())
    rows = data['observations']
    summary['arms'][arm] = {'runs': len(rows), 'failures': sum(row['exit'] != 0 for row in rows), 'cores': sum(row['core_captured'] for row in rows), 'key_source_sha256': hashlib.sha256(key_file.read_bytes()).hexdigest(), 'binary_sha256': data['binary_sha256']}
    owners = []
    for stack in out.glob('*-stack.log'):
        for line in stack.read_text().splitlines():
            if not line.startswith('OWNER_RECORD '):
                continue
            owner = json.loads(line.removeprefix('OWNER_RECORD '))
            if (owner.get('crashing') and owner.get('mutex_kind', 0) != 0
                    and owner.get('mutex') is not None
                    and owner.get('mutex') == owner.get('parking_mutex')
                    and owner.get('parking_data') is not None
                    and owner.get('parking_data') == owner.get('heap_tld')
                    and owner.get('slot_data') == owner.get('tld_theaps')
                    and owner.get('slot_seq', 0) >= 3
                    and owner.get('slot_seq') == owner.get('key_seq')
                    and 'ThreadSpecific' in owner.get('key_destructor', '')
                    and any('WTF::Mutex::lock' in frame for frame in owner.get('frames', []))
                    and any('ParkingLot::parkConditionallyImpl' in frame for frame in owner.get('frames', []))):
                owners.append(owner)
    summary['arms'][arm]['confirmed_owners'] = owners

    (a.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')

native('baseline')
replay('baseline')
command(['git', 'apply', '.github/openclaw/exit-key-candidate.patch'], a.output / 'apply.log')
command(['cmake', '--build', a.build, '--target', 'jsc', '-j4'], a.output / 'fixed-build.log', timeout=1800)
native('fixed')
replay('fixed')
assert summary['arms']['baseline']['confirmed_owners'], 'No core proved the targeted TLS/parking-mutex ownership collision'
assert summary['arms']['fixed']['key_source_sha256'] == summary['candidate']['key_source_sha256'], 'Candidate source hash mismatch'
assert summary['arms']['fixed']['runs'] == 1200 and summary['arms']['fixed']['failures'] == 0, 'Fixed replay is not clean and complete'
print(json.dumps(summary), flush=True)
