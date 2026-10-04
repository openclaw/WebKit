#!/usr/bin/env python3
"""Stage a built WebKit tarball in a private, checksum-verified Bun prefetch cache."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('archive', type=Path)
parser.add_argument('--version', required=True)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
with args.archive.open('rb') as stream:
    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
# .invalid makes a cache miss fail rather than silently downloading a different build.
name = args.archive.name
url = f'https://w104.invalid/{args.version}/{digest}/{name}'
cache = args.output / 'prefetch' / 'by-url'
cache.mkdir(parents=True, exist_ok=True)
key = hashlib.sha256(url.encode()).hexdigest()[:32]
shutil.copyfile(args.archive, cache / key)
manifest = {'version': args.version, 'artifacts': {name: {'url': url, 'sha256': digest}}}
(args.output / 'artifacts.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps({'manifest': str((args.output / 'artifacts.json').resolve()),
                  'prefetch': str((args.output / 'prefetch').resolve()), 'sha256': digest}))
