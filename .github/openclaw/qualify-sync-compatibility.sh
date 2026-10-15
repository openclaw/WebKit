#!/usr/bin/env bash
set -euo pipefail
pipeline=$(pwd)
inputs="$pipeline/.github/openclaw/qualification"
: "${ARTIFACT_DIR:?}" "${QUALIFICATION_DIR:?}" "${INSPECTOR_RUNTIME:?}" "${CANDIDATE_BUN:?}" "${CANDIDATE_RECEIPT:?}"
QUALIFICATION_DIR=$(realpath "$QUALIFICATION_DIR")
ARTIFACT_DIR=$(realpath "$ARTIFACT_DIR")
SOURCE_SHA=$(git rev-parse HEAD)
repo="$QUALIFICATION_DIR/bun"
candidate=$(realpath "$CANDIDATE_BUN")
test "$candidate" = "$repo/build/qualify-candidate/bun"
test "$(realpath "$CANDIDATE_RECEIPT")" = "$QUALIFICATION_DIR/candidate-identity.json"
python3 "$inputs/consumer_identity.py" verify --root "$QUALIFICATION_DIR" --inspector-runtime "$INSPECTOR_RUNTIME" --source "$SOURCE_SHA" --artifacts "$ARTIFACT_DIR" --receipt "$CANDIDATE_RECEIPT"
unset BUN_BUILD_PREFETCH_DIR BUN_BUILD_CACHE_DIR BUN_WEBKIT_ARTIFACT_MANIFEST
export CI=1 PUPPETEER_SKIP_DOWNLOAD=1
cd "$repo"
results="$QUALIFICATION_DIR/compatibility"
mkdir -p "$results/home" "$results/tmp"
chmod 700 "$results/home" "$results/tmp"
export HOME="$results/home" TMPDIR="$results/tmp"
"$candidate" --revision > "$results/revision.log"
"$candidate" -e 'const server=Bun.serve({port:0,fetch(){return new Response("ready")}});try{if(await(await fetch(server.url)).text()!=="ready")throw Error("startup");console.log("build/startup/http passed")}finally{await server.stop(true)}' > "$results/startup.log" 2>&1
"$candidate" test test/js/web/atomics.test.ts test/js/bun/wasm/compile-rss.test.ts -t 'Atomics.wait lets mimalloc|a notify that arrives while Atomics.wait|WebAssembly.compile does not retain' > "$results/memory-release.log" 2>&1
python3 "$inputs/consumer_identity.py" verify --root "$QUALIFICATION_DIR" --inspector-runtime "$INSPECTOR_RUNTIME" --source "$SOURCE_SHA" --artifacts "$ARTIFACT_DIR" --receipt "$CANDIDATE_RECEIPT"
PYTHONPATH="$inputs" python3 - "$QUALIFICATION_DIR" "$SOURCE_SHA" "$CANDIDATE_RECEIPT" <<'PY'
import json,re,sys
from pathlib import Path
from consumer_identity import sha,validate
root=Path(sys.argv[1]);text=(root/'compatibility/memory-release.log').read_text()
assert re.search(r'\b3 pass\b',text) and re.search(r'\b0 fail\b',text)
assert not re.search(r'\b[1-9]\d* skip\b',text)
validate(json.loads(Path(sys.argv[3]).read_text()),sys.argv[2])
record={'passed':True,'source':sys.argv[2],'candidate_identity_sha256':sha(Path(sys.argv[3])),
        'memory_tests':3,'startup':True}
(root/'compatibility-gate.json').write_text(json.dumps(record,indent=2)+'\n')
PY
