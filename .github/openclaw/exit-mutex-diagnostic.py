#!/usr/bin/env python3
"""At most 1,200 children or 20 minutes; upload symbolized text, never cores."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import time

parser = argparse.ArgumentParser()
for key in ['binary', 'fixture', 'output', 'cores']:
    parser.add_argument('--' + key, type=Path, required=True)
args = parser.parse_args()
args.binary = args.binary.resolve()
args.fixture = args.fixture.resolve()
args.output.mkdir(exist_ok=True, parents=True)
args.cores.mkdir(exist_ok=True, parents=True)
for name in ['home', 'tmp', 'state']:
    (args.output / name).mkdir(mode=0o700, exist_ok=True)
env = {'PATH': '/usr/bin:/bin', 'LANG': 'C', 'HOME': str(args.output / 'home'),
       'TMPDIR': str(args.output / 'tmp'), 'OPENCLAW_STATE_DIR': str(args.output / 'state')}
_, hard = resource.getrlimit(resource.RLIMIT_CORE)
resource.setrlimit(resource.RLIMIT_CORE, (hard, hard))
flags = ['--validateOptions=true', '--useFTLJIT=false', '--useFunctionDotArguments=true',
         '--validateExceptionChecks=true', '--useDollarVM=true', '--maxPerThreadStackUsage=1572864',
         '--useConcurrentJIT=false', '--thresholdForJITAfterWarmUp=100', '--scribbleFreeCells=true',
         '--collectContinuously=true', '--useGenerationalGC=false', '--verifyGC=true']
# Run GDB after process termination, preserving natural thread scheduling during reproduction.
gdb_script = args.output / 'capture.gdb'
gdb_script.write_text('''set pagination off
set print frame-arguments all
set print elements 32
info threads
p/x _mi_heap_default_key
info variables myThreadData
thread apply all bt full
thread apply all info registers
info sharedlibrary
info proc mappings
python
for thread in gdb.selected_inferior().threads():
    thread.switch()
    frame = gdb.newest_frame()
    while frame:
        name = frame.name() or ''
        if 'mutex' in name.lower():
            frame.select()
            print('MUTEX_FRAME', thread.num, name)
            try:
                mutex = frame.read_var('mutex')
                print('MUTEX_ADDRESS', mutex)
                print('MUTEX_VALUE', mutex.dereference())
                gdb.execute('info symbol ' + str(int(mutex)))
            except gdb.error as error:
                print(error)
        frame = frame.older()
end
''')
rows = []
provenance = {'diagnostic_only': True, 'machine': platform.machine(), 'flags': flags,
              'binary_sha256': hashlib.sha256(args.binary.read_bytes()).hexdigest(),
              'fixture_sha256': hashlib.sha256(args.fixture.read_bytes()).hexdigest(), 'observations': rows}
deadline = time.monotonic() + 20 * 60
def run(index):
    if time.monotonic() >= deadline:
        return None
    log = args.output / f'replay-{index:04}.log'
    start = time.monotonic()
    with log.open('w') as stream:
        proc = subprocess.Popen([str(args.binary), *flags, str(args.fixture)], stdout=stream,
                                stderr=subprocess.STDOUT, env=env)
        try:
            code = proc.wait(timeout=max(0.001, min(30, deadline - time.monotonic())))
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            code = 124
    row = {'index': index, 'pid': proc.pid, 'exit': code, 'elapsed_s': time.monotonic() - start, 'core_captured': False}
    core = args.cores / f'core.{proc.pid}'
    if core.exists():
        row['core_captured'] = True
        try:
            with (args.output / f'replay-{index:04}-stack.log').open('w') as stream:
                result = subprocess.run(['gdb', '-nx', '-q', '-batch', '-x', str(gdb_script),
                                         str(args.binary), str(core)], stdout=stream,
                                        stderr=subprocess.STDOUT, env=env, timeout=max(0.001, min(90, deadline - time.monotonic())))
                row['gdb_exit'] = result.returncode
        except subprocess.TimeoutExpired:
            row['gdb_timeout'] = True
        finally:
            core.unlink(missing_ok=True)
    if not log.stat().st_size and code == 0:
        log.unlink()
    return row
# The attempt cap is an independent resource budget, not a minimum observation window.
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    offset = 0
    while offset < 1200 and time.monotonic() < deadline:
        count = min(3 - sum(row["core_captured"] for row in rows), 1200 - offset)
        if not count:
            break
        rows.extend(row for row in pool.map(run, range(offset, offset + count)) if row is not None)
        offset += count
        (args.output / 'replay.json').write_text(json.dumps(provenance, indent=2) + '\n')
        if sum(row['core_captured'] for row in rows) >= 3 or time.monotonic() >= deadline:
            break
print(json.dumps({'runs': len(rows), 'failures': sum(row['exit'] != 0 for row in rows),
                  'cores': sum(row['core_captured'] for row in rows),
                  'timeouts': sum(row['exit'] == 124 for row in rows)}), flush=True)
assert not list(args.cores.glob('core.*')), 'Unprocessed core outside upload directory'
