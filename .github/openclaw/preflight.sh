#!/usr/bin/env bash
set -euo pipefail
uname -a
nproc
free -h
df -h .
test "$(uname -sm)" = 'Linux x86_64'
docker version
docker buildx version
docker buildx inspect --bootstrap
# The unchanged upstream recipe uses tmpfs and one compiler per visible CPU.
# Report measured capacity; do not silently change its compilation settings.
python3 - <<'PY'
import json,os,shutil
from pathlib import Path
m={s.split(':')[0]:int(s.split()[1])*1024 for s in Path('/proc/meminfo').read_text().splitlines() if s.split()[1].isdigit()}
print(json.dumps({'cpu':os.cpu_count(),'memory_bytes':m['MemTotal'],'available_bytes':m['MemAvailable'],'disk_free_bytes':shutil.disk_usage('.').free}))
PY
