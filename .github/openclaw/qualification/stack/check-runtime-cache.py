"""Prove cache version replacement and execution of cached transpiler output."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import struct
import subprocess

p = argparse.ArgumentParser()
p.add_argument('--baseline', required=True)
p.add_argument('--candidate', required=True)
p.add_argument('--fixture', required=True, type=Path)
p.add_argument('--output', required=True, type=Path)
p.add_argument('--expected-version', required=True, type=int)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=False)
source_marker = 'W152_CACHE_SOURCE'
replay_marker = 'W152_CACHE_REPLAY'
source = a.output / 'positions.js'
source.write_text(a.fixture.read_text() + '\nconsole.error("' + source_marker + '");\n/*' + (' cache proof ' * 6000) + '*/\n')
cache = a.output / 'cache'
cache.mkdir()
env = {**os.environ, 'BUN_RUNTIME_TRANSPILER_CACHE_PATH': str(cache)}
receipts = []


def snapshot():
    files = sorted(f for f in cache.rglob('*') if f.is_file())
    assert files, 'cache was not populated'
    return [{'name': str(f.relative_to(cache)), 'bytes': f.stat().st_size,
             'sha256': hashlib.sha256(f.read_bytes()).hexdigest(),
             'version': int.from_bytes(f.read_bytes()[:4], 'little')} for f in files]


def mark_cached_output():
    changed = []
    for file in sorted(cache.rglob('*.pile')):
        data = bytearray(file.read_bytes())
        assert len(data) >= 102, 'truncated cache header'
        assert int.from_bytes(data[:4], 'little') == a.expected_version, 'candidate did not replace old cache format'
        # Metadata::encode: u32 version, two u8 tags, then twelve little-endian u64s.
        offset, length = struct.unpack_from('<QQ', data, 30)
        assert 102 <= offset <= len(data) and length <= len(data) - offset
        encoding = 'utf-16-le' if data[5] == 2 else 'utf-8'
        before = source_marker.encode(encoding)
        after = replay_marker.encode(encoding)
        output = bytes(data[offset:offset + length])
        if before not in output:
            continue
        assert output.count(before) == 1 and len(before) == len(after)
        marked = output.replace(before, after)
        payload = a.output / 'marked-output.bin'
        payload.write_bytes(marked)
        script = 'const bytes=require("fs").readFileSync(process.argv[1]);console.log(Bun.hash.wyhash(bytes,42n).toString())'
        digest = int(subprocess.check_output([a.candidate, '-e', script, str(payload)], env=env, text=True).strip())
        data[offset:offset + length] = marked
        struct.pack_into('<Q', data, 46, digest)
        file.write_bytes(data)
        changed.append(str(file.relative_to(cache)))
    assert len(changed) == 1, ('expected one fixture cache entry', changed)
    return changed[0]


for arm, repeat in [('baseline', 'cold'), ('baseline', 'warm'), ('candidate', 'old-cache'), ('candidate', 'warm')]:
    marked_entry = mark_cached_output() if arm == 'candidate' and repeat == 'warm' else None
    before_warm = snapshot() if marked_entry else None
    result = subprocess.run([getattr(a, arm), str(source)], env=env, text=True, capture_output=True, check=True)
    expected_marker = replay_marker if marked_entry else source_marker
    assert result.stderr.strip() == expected_marker, ('cache output was not replayed', repeat, result.stderr)
    rows = json.loads(result.stdout)
    files = snapshot()
    if arm == 'candidate':
        assert all(f['version'] == a.expected_version for f in files), files
    if marked_entry:
        assert files == before_warm, 'warm run replaced the marked cache instead of loading it'
    receipt = {'arm': arm, 'repeat': repeat,
               'matches': sum(v['actual'] == v['expected'] for v in rows), 'total': len(rows),
               'cacheFiles': files, 'cache_hit_proven': bool(marked_entry), 'marked_entry': marked_entry}
    receipts.append(receipt)
    (a.output / f'{arm}-{repeat}.json').write_text(result.stdout)
    if arm == 'candidate':
        assert receipt['matches'] == receipt['total'], receipt
(a.output / 'receipts.json').write_text(json.dumps(receipts, indent=2) + '\n')
print(json.dumps(receipts, indent=2))
