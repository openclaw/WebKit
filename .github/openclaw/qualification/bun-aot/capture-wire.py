#!/usr/bin/env python3
"""Capture one emitted wire fixture; deliberately provide no engine verdict."""
import hashlib
import json
from pathlib import Path
import stat
import sys

out = Path('/work/aot-proof')
with (out / 'wire-capture-invocations.log').open('a') as stream:
    stream.write('capture\n')
assert len(sys.argv) == 4 and sys.argv[1:3] == ['print', '--wire']
source = Path(sys.argv[3])
metadata = source.lstat()
assert stat.S_ISREG(metadata.st_mode) and 0 < metadata.st_size <= 8 * 1024**2
data = source.read_bytes()
assert 0 < len(data) <= 8 * 1024**2
with (out / 'wire-program.bin').open('xb') as stream:
    stream.write(data)
with (out / 'wire-capture.json').open('x') as stream:
    json.dump({'diagnostic_only': True, 'arguments': ['print', '--wire', '<fixture>'],
               'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}, stream)
    stream.write('\n')
print('OPENCLAW_AOT_WIRE_CAPTURED', file=sys.stderr)
raise SystemExit(86)
