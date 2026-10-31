#!/usr/bin/env python3
"""Stage one measured lane through the production checksum resolver."""
import argparse
import json
import shutil
from pathlib import Path
from consumer_identity import engine_input, overlay_manifest

parser = argparse.ArgumentParser()
parser.add_argument('archive', type=Path)
parser.add_argument('--lane-manifest', required=True, type=Path)
parser.add_argument('--version', required=True)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
engine = engine_input(args.archive, args.lane_manifest, args.version)
cache = args.output / 'prefetch/by-sha256'
cache.mkdir(parents=True, exist_ok=False)
shutil.copyfile(args.archive, cache / engine['archive']['sha256'])
(args.output / 'artifacts.json').write_text(json.dumps(overlay_manifest(engine), indent=2) + '\n')
