#!/usr/bin/env bash
set -euo pipefail
pipeline=$(pwd)
inputs="$pipeline/.github/openclaw/qualification"
: "${ARTIFACT_DIR:?}" "${QUALIFICATION_DIR:?}"
QUALIFICATION_DIR=$(realpath "$QUALIFICATION_DIR")
SOURCE_SHA=$(git rev-parse HEAD)
bootstrap=$(command -v bun)
export CI=1 PUPPETEER_SKIP_DOWNLOAD=1
source "$inputs/build-matched.sh"
repo="$QUALIFICATION_DIR/bun-sync-compatibility"
results="$QUALIFICATION_DIR/compatibility"
mkdir -p "$results/home" "$results/tmp"
chmod 700 "$results/home" "$results/tmp"
checkout_matched
build_matched sync-compatibility
export HOME="$results/home" TMPDIR="$results/tmp"
"$candidate" --revision > "$results/revision.log"
"$candidate" -e 'const server=Bun.serve({port:0,fetch(){return new Response("ready")}});try{if(await(await fetch(server.url)).text()!=="ready")throw Error("startup");console.log("build/startup/http passed")}finally{await server.stop(true)}' > "$results/startup.log" 2>&1
"$candidate" test test/js/web/atomics.test.ts test/js/bun/wasm/compile-rss.test.ts -t 'Atomics.wait lets mimalloc|a notify that arrives while Atomics.wait|WebAssembly.compile does not retain' > "$results/memory-release.log" 2>&1
python3 - "$QUALIFICATION_DIR" "$SOURCE_SHA" "$matched_commit" "$matched_tree" <<'PYCODE'
import hashlib,json,re,sys
from pathlib import Path
root=Path(sys.argv[1]);text=(root/'compatibility/memory-release.log').read_text()
assert re.search(r'\b3 pass\b',text) and re.search(r'\b0 fail\b',text)
assert not re.search(r'\b[1-9]\d* skip\b',text)
record={'passed':True,'source':sys.argv[2],'bun_commit':sys.argv[3],'bun_tree':sys.argv[4],
        'only_manifest_changed':True,'memory_tests':3,'startup':True,
        'manifest_patch_sha256':hashlib.sha256((root/'bun-sync-compatibility-manifest.patch').read_bytes()).hexdigest()}
(root/'compatibility-gate.json').write_text(json.dumps(record,indent=2)+'\n')
PYCODE
