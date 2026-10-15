#!/usr/bin/env python3
"""Use the production resolver and checksum cache for an unpublished candidate."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('archive',type=Path)
p.add_argument('--version',required=True)
p.add_argument('--output',required=True,type=Path)
a=p.parse_args()
with a.archive.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
cache=a.output/'prefetch/by-sha256';cache.mkdir(parents=True,exist_ok=False)
shutil.copyfile(a.archive,cache/digest)
name=a.archive.name
manifest={'version':a.version,'artifacts':{name:{'url':f'https://github.com/openclaw/WebKit/releases/download/autobuild-{a.version}/{name}','sha256':digest}}}
(a.output/'artifacts.json').write_text(json.dumps(manifest,indent=2)+'\n')
