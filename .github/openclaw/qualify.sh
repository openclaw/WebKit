#!/usr/bin/env bash
set -euo pipefail
umask 022
pipeline=$(pwd)
inputs="$pipeline/.github/openclaw/qualification"
: "${ARTIFACT_DIR:?}" "${QUALIFICATION_DIR:?}"
mkdir -p "$QUALIFICATION_DIR"
QUALIFICATION_DIR=$(realpath "$QUALIFICATION_DIR")
SOURCE_SHA=$(git rev-parse HEAD)
BUN_COMMIT=$(python3 -c 'import json;print(json.load(open(".github/openclaw/variants.json"))["bun_commit"])')
BASELINE_BUN=$(python3 -c 'import json;print(json.load(open(".github/openclaw/variants.json"))["baseline_bun_commit"])')
BASE=$(python3 -c 'import json;print(json.load(open(".github/openclaw/variants.json"))["baseline_webkit_commit"])')
bootstrap=$(command -v bun)
export CI=true PUPPETEER_SKIP_DOWNLOAD=1
source "$inputs/build-matched.sh"
# Keep the proven historical control intact. It also seeds the old cache format.
repo="$QUALIFICATION_DIR/bun-baseline"
git clone --depth=1 --filter=blob:none --no-checkout https://github.com/openclaw/bun.git "$repo"
cd "$repo"
git fetch --depth=1 origin "$BASELINE_BUN"
git checkout --detach "$BASELINE_BUN"
git apply "$inputs/patches/000-checksums.patch"
git apply "$inputs/patches/012-vm-finalization-fixture.patch"
# Match the IPv4 clients, as corrected in openclaw/bun#134; no assertion changes.
git apply "$inputs/patches/013-ipv4-loopback-fixture.patch"
# Backport the pinned candidate's isolated-stdio ownership fix (Bun #145 / upstream #38008).
# The historical control otherwise fails between files before running their tests.
git apply "$inputs/patches/014-baseline-isolated-stdio.patch"
sha256sum "$inputs/patches/014-baseline-isolated-stdio.patch" > "$QUALIFICATION_DIR/baseline-isolated-stdio.sha256"
sha256sum "$inputs/patches/013-ipv4-loopback-fixture.patch" > "$QUALIFICATION_DIR/net-loopback-fixture.sha256"
sha256sum "$inputs/patches/012-vm-finalization-fixture.patch" > "$QUALIFICATION_DIR/vm-finalization-fixture.sha256"
"$bootstrap" install --frozen-lockfile
(cd test && "$bootstrap" install --frozen-lockfile)
export BUN_WEBKIT_ARTIFACT_MANIFEST="$inputs/upstream-artifacts.json"
export BUN_BUILD_PREFETCH_DIR="$QUALIFICATION_DIR/baseline-prefetch"
export BUN_BUILD_CACHE_DIR="$QUALIFICATION_DIR/cache-baseline"
env -u GITHUB_SHA -u BUILDKITE_COMMIT -u GIT_SHA "$bootstrap" run build:release --lto=off --webkit-version="$BASE" --buildDir="$repo/build/qualify-baseline" --timings > "$QUALIFICATION_DIR/build-baseline.log" 2>&1
baseline="$repo/build/qualify-baseline/bun"
"$baseline" -e 'if(process.versions.webkit!==process.argv[1] || Bun.revision!==process.argv[2]) throw new Error("wrong control engine or Bun source revision");' "$BASE" "$BASELINE_BUN"
sha256sum "$baseline" > "$QUALIFICATION_DIR/bun-baseline.sha256"
unset BUN_WEBKIT_ARTIFACT_MANIFEST BUN_BUILD_PREFETCH_DIR BUN_BUILD_CACHE_DIR
for arm in baseline candidate; do
  if test "$arm" = candidate; then
    repo="$QUALIFICATION_DIR/bun"
    checkout_matched
    build_matched candidate
    # All production adapters and the VM fixture are now in the pinned source.
    cp "$inputs/worker-resource-limits.test.ts" test/js/node/worker_threads/openclaw-resource-limits.test.ts
  else
    candidate="$baseline"
  fi
  # Establish native backpressure before letting the peer drain, on both engines.
  git apply "$inputs/patches/015-net-writev-backpressure-fixture.patch"
  sha256sum "$inputs/patches/015-net-writev-backpressure-fixture.patch" > "$QUALIFICATION_DIR/net-backpressure-fixture.sha256"
  git diff -- test/js/node/net/node-net.test.ts > "$QUALIFICATION_DIR/net-fixture-$arm.patch"
  sha256sum test/js/node/vm/vm.test.ts > "$QUALIFICATION_DIR/vm-test-$arm.sha256"
  sha256sum test/js/node/net/node-net.test.ts > "$QUALIFICATION_DIR/net-test-$arm.sha256"
  results="$QUALIFICATION_DIR/$arm"
  mkdir -p "$results" "$results/home" "$results/tmp" "$results/bin"
  chmod 700 "$results/home" "$results/tmp"
  ln -s "$candidate" "$results/bin/bun"
  mkdir -p build/openclaw-ci
  cp "$inputs/selected.json" build/openclaw-ci/selected.json
  cp "$inputs/selected.json" "$results/selected.json"
  rm -f build/openclaw-ci/results.json
  python3 "$inputs/stage-fork-ci.py" "$repo" "$results"
  env OPENCLAW_QUALIFICATION_RESULTS="$results" HOME="$results/home" TMPDIR="$results/tmp" PATH="$results/bin:$PATH" OPENCLAW_CI_PLATFORM=linux \
    "$candidate" scripts/openclaw-ci/qualification-tests.ts test > "$results/tests.log" 2>&1
  cp build/openclaw-ci/results.json "$results/results.json"
  python3 "$inputs/collect-fork-outcomes.py" "$results"
done
python3 "$inputs/compare-fork-ci.py" "$QUALIFICATION_DIR/baseline" "$QUALIFICATION_DIR/candidate" --output "$QUALIFICATION_DIR/faithfulness.json"
candidate="$QUALIFICATION_DIR/bun/build/qualify-candidate/bun"
unset BUN_WEBKIT_ARTIFACT_MANIFEST BUN_BUILD_CACHE_DIR BUN_BUILD_PREFETCH_DIR
"$candidate" test test/js/bun/resolve/esModule.test.ts test/js/bun/namespace-prototype-pollution.test.ts test/js/bun/resolve/require-esm-evaluating-cycle.test.ts test/js/bun/import-attributes/import-attributes.test.ts test/js/node/module/require-extensions.test.ts > "$QUALIFICATION_DIR/namespace.log" 2>&1
"$candidate" test --expose-internals test/js/node/v8/capture-stack-trace.test.js test/js/bun/sourcemap/internal-sourcemap.test.ts > "$QUALIFICATION_DIR/stack-positions.log" 2>&1
"$candidate" "$inputs/segmenter.js" > "$QUALIFICATION_DIR/segmenter.log" 2>&1
"$candidate" test test/js/node/vm/vm.test.ts -t 'a Proxy in the prototype chain' > "$QUALIFICATION_DIR/proxy.log" 2>&1
"$candidate" test test/js/node/process/process.test.js -t 'ArrayBuffer memory ownership' > "$QUALIFICATION_DIR/arraybuffer.log" 2>&1
"$candidate" test test/js/node/worker_threads/worker_threads.test.ts -t 'getHeapStatistics' > "$QUALIFICATION_DIR/worker-statistics.log" 2>&1
"$candidate" test test/js/node/worker_threads/openclaw-resource-limits.test.ts -t 'resourceLimits' > "$QUALIFICATION_DIR/resource-limits.log" 2>&1
"$candidate" "$inputs/module-context.mjs" matrix > "$QUALIFICATION_DIR/als-plugin.json"
"$candidate" "$inputs/module-context.mjs" matrix --native-hooks > "$QUALIFICATION_DIR/als-native.json"
python3 - "$QUALIFICATION_DIR" "$SOURCE_SHA" "$BUN_COMMIT" "$BASELINE_BUN" "$BASE" "$matched_tree" <<'PY'
import json,re,sys,hashlib
from pathlib import Path
root=Path(sys.argv[1])
faith=json.loads((root/'faithfulness.json').read_text())
assert faith['identical_file_outcomes'] and faith['all_passed']
assert faith['selected_files']==44 and faith['result_files']==46
for name in ['als-plugin','als-native']:
 rows=json.loads((root/(name+'.json')).read_text())['results']
 assert len(rows)==14 and all(r['exitCode']==0 for r in rows)
for name,minimum in [('proxy',4),('resource-limits',16),('namespace',41),('arraybuffer',19),('worker-statistics',7)]:
 text=(root/(name+'.log')).read_text()
 passes=re.search(r'(\d+) pass',text)
 assert passes and int(passes[1])>=minimum, name+' missing passing cases'
 assert re.search(r'\b0 fail\b',text),name+' failures'
(root/'gate.json').write_text(json.dumps({'passed':True,'source':sys.argv[2],'bun_commit':sys.argv[3],
 'bun_tree':sys.argv[6], 'selected_files':44,'result_files':46,'als_variants_per_mode':14,'proxy_minimum':4,'resource_minimum':16,
 'baseline_bun_commit':sys.argv[4], 'baseline_webkit_commit':sys.argv[5],
 'bun_manifest_sha256':hashlib.sha256((root/'bun-candidate-manifest.patch').read_bytes()).hexdigest()},indent=2)+'\n')
PY
