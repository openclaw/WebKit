#!/usr/bin/env bash
set -euo pipefail
pipeline=$(pwd)
inputs="$pipeline/.github/openclaw/qualification"
: "${ARTIFACT_DIR:?}" "${QUALIFICATION_DIR:?}"
QUALIFICATION_DIR=$(realpath "$QUALIFICATION_DIR")
SOURCE_SHA=$(git rev-parse HEAD)
BUN_BASE=d2d2a26ef973cdd97b37953f5dba58052acad74f
SYNC_TREE=d9ec052fccc81afbf43a5344e52bc980f439d587
PAIRED_TREE=$(python3 -c 'import json;print(json.load(open(".github/openclaw/variants.json"))["upstream_sync"]["paired_tree"])')
NAMESPACE_SHA=$(python3 -c 'import json;print(json.load(open(".github/openclaw/variants.json"))["upstream_sync"]["required_namespace_adapter_sha256"])')
bootstrap=$(command -v bun)
export CI=1 PUPPETEER_SKIP_DOWNLOAD=1
repo="$QUALIFICATION_DIR/bun-sync-compatibility"
results="$QUALIFICATION_DIR/compatibility"
mkdir -p "$results/home" "$results/tmp"
chmod 700 "$results/home" "$results/tmp"
git clone --depth=1 --filter=blob:none --no-checkout https://github.com/openclaw/bun.git "$repo"
cd "$repo"
git fetch --depth=1 origin "$BUN_BASE"
git checkout --detach "$BUN_BASE"
git apply --index "$inputs/sync/upstream-sync.patch"
test "$(git write-tree)" = "$SYNC_TREE"
namespace_patch="$inputs/patches/008-namespace.patch"
test "$(sha256sum "$namespace_patch" | cut -d' ' -f1)" = "$NAMESPACE_SHA"
git apply --index --exclude=CHANGELOG.md --exclude='docs/*' "$namespace_patch"
test "$(git write-tree)" = "$PAIRED_TREE"
git diff --binary "$SYNC_TREE" > "$QUALIFICATION_DIR/bun-required-namespace-pair.patch"
python3 "$inputs/stage-sync-artifact.py" "$ARTIFACT_DIR/bun-webkit-linux-amd64.tar.gz" --version "$SOURCE_SHA" --output "$QUALIFICATION_DIR/compatibility-input"
cp "$QUALIFICATION_DIR/compatibility-input/artifacts.json" scripts/build/deps/webkit-artifacts.json
# The namespace API requires its existing Bun counterpart; no other feature adapters enter this arm.
test "$(git diff --name-only)" = scripts/build/deps/webkit-artifacts.json
"$bootstrap" install --frozen-lockfile
(cd test && "$bootstrap" install --frozen-lockfile)
export BUN_BUILD_PREFETCH_DIR="$QUALIFICATION_DIR/compatibility-input/prefetch"
export BUN_BUILD_CACHE_DIR="$QUALIFICATION_DIR/cache-sync-compatibility"
env -u GITHUB_SHA -u BUILDKITE_COMMIT -u GIT_SHA "$bootstrap" run build:release --lto=off --buildDir="$repo/build/qualify-sync-compatibility" --timings > "$QUALIFICATION_DIR/build-sync-compatibility.log" 2>&1
test "$(git write-tree)" = "$PAIRED_TREE"
test "$(git diff --name-only)" = scripts/build/deps/webkit-artifacts.json
git diff --binary "$PAIRED_TREE" > "$QUALIFICATION_DIR/bun-sync-compatibility.patch"
candidate="$repo/build/qualify-sync-compatibility/bun"
"$candidate" -e 'if(process.versions.webkit!==process.argv[1] || Bun.revision!==process.argv[2]) throw new Error("wrong engine or Bun source revision");' "$SOURCE_SHA" "$BUN_BASE"
sha256sum "$candidate" > "$QUALIFICATION_DIR/bun-sync-compatibility.sha256"
unset BUN_BUILD_PREFETCH_DIR BUN_BUILD_CACHE_DIR BUN_WEBKIT_ARTIFACT_MANIFEST
export HOME="$results/home" TMPDIR="$results/tmp"
"$candidate" --revision > "$results/revision.log"
"$candidate" -e 'const server=Bun.serve({port:0,fetch(){return new Response("ready")}});try{if(await(await fetch(server.url)).text()!=="ready")throw Error("startup");console.log("build/startup/http passed")}finally{await server.stop(true)}' > "$results/startup.log" 2>&1
"$candidate" test test/js/web/atomics.test.ts test/js/bun/wasm/compile-rss.test.ts -t 'Atomics.wait lets mimalloc|a notify that arrives while Atomics.wait|WebAssembly.compile does not retain' > "$results/memory-release.log" 2>&1
python3 - "$QUALIFICATION_DIR" "$SOURCE_SHA" "$BUN_BASE" "$SYNC_TREE" "$PAIRED_TREE" "$NAMESPACE_SHA" <<'PY'
import hashlib,json,re,sys
from pathlib import Path
root=Path(sys.argv[1]);text=(root/'compatibility/memory-release.log').read_text()
assert re.search(r'\b3 pass\b',text) and re.search(r'\b0 fail\b',text)
assert not re.search(r'\b[1-9]\d* skip\b',text)
record={'passed':True,'source':sys.argv[2],'base_commit':sys.argv[3],'prepared_tree':sys.argv[4],
        'paired_tree':sys.argv[5],'required_namespace_adapter_sha256':sys.argv[6],
        'only_manifest_changed_after_pairing':True,'memory_tests':3,'startup':True,
        'manifest_patch_sha256':hashlib.sha256((root/'bun-sync-compatibility.patch').read_bytes()).hexdigest()}
(root/'compatibility-gate.json').write_text(json.dumps(record,indent=2)+'\n')
PY
