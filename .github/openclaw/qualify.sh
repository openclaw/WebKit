#!/usr/bin/env bash
set -euo pipefail
umask 022
pipeline=$(pwd)
inputs="$pipeline/.github/openclaw/qualification"
: "${ARTIFACT_DIR:?}" "${QUALIFICATION_DIR:?}" "${INSPECTOR_RUNTIME:?}"
mkdir -p "$QUALIFICATION_DIR"
QUALIFICATION_DIR=$(realpath "$QUALIFICATION_DIR")
ARTIFACT_DIR=$(realpath "$ARTIFACT_DIR")
SOURCE_SHA=$(git rev-parse HEAD)
bootstrap=$(realpath "$INSPECTOR_RUNTIME")
test "$bootstrap" = "$INSPECTOR_RUNTIME" && test -x "$bootstrap"
export CI=1 PUPPETEER_SKIP_DOWNLOAD=1
python3 "$inputs/consumer_identity.py" baseline-inputs
# This compares a historical Bun-plus-engine baseline with the exact current Bun candidate.
# Independent source, dependencies, build directories and caches prevent ABI reuse.
for arm in baseline candidate; do
  commit=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))[sys.argv[2]]["commit"])' "$pipeline/.github/openclaw/variants.json" "$arm")
  tree=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))[sys.argv[2]]["tree"])' "$pipeline/.github/openclaw/variants.json" "$arm")
  if test "$arm" = baseline; then repo="$QUALIFICATION_DIR/bun-baseline"; else repo="$QUALIFICATION_DIR/bun"; fi
  git clone --depth=1 --filter=blob:none --no-checkout https://github.com/openclaw/bun.git "$repo"
  cd "$repo"
  git fetch --depth=1 origin "$commit"
  git checkout --detach "$commit"
  test "$(git rev-parse HEAD^{tree})" = "$tree"
  git diff --exit-code HEAD
  if test "$arm" = baseline; then
    git apply "$inputs/patches/000-checksums.patch"
    git apply "$inputs/patches/012-vm-finalization-fixture.patch"
    git diff --binary HEAD > "$QUALIFICATION_DIR/baseline-adapters.patch"
    export BUN_WEBKIT_ARTIFACT_MANIFEST="$inputs/upstream-artifacts.json"
    export BUN_BUILD_PREFETCH_DIR="$QUALIFICATION_DIR/baseline-prefetch"
    revision=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["baseline"]["engine"])' "$pipeline/.github/openclaw/variants.json")
  else
    unset BUN_WEBKIT_ARTIFACT_MANIFEST
    python3 "$inputs/stage-sync-artifact.py" "$ARTIFACT_DIR/bun-webkit-linux-amd64.tar.gz" \
      --lane-manifest "$ARTIFACT_DIR/bun-webkit-linux-amd64.manifest.json" --version "$SOURCE_SHA" --output "$QUALIFICATION_DIR/candidate-input"
    cp "$QUALIFICATION_DIR/candidate-input/artifacts.json" scripts/build/deps/webkit-artifacts.json
    git diff --binary HEAD > "$QUALIFICATION_DIR/candidate-manifest.patch"
    export BUN_BUILD_PREFETCH_DIR="$QUALIFICATION_DIR/candidate-input/prefetch"
    revision="$SOURCE_SHA"
  fi
  export BUN_BUILD_CACHE_DIR="$QUALIFICATION_DIR/cache-$arm"
  "$bootstrap" install --frozen-lockfile
  (cd test && "$bootstrap" install --frozen-lockfile)
  python3 "$inputs/consumer_identity.py" "check-$arm" --root "$QUALIFICATION_DIR" --inspector-runtime "$INSPECTOR_RUNTIME" --source "$SOURCE_SHA" --artifacts "$ARTIFACT_DIR"
  sha256sum test/js/node/vm/vm.test.ts > "$QUALIFICATION_DIR/vm-test-$arm.sha256"
  env -u GITHUB_SHA -u BUILDKITE_COMMIT -u GIT_SHA "$bootstrap" run build:release --lto=off --webkit-version="$revision" --buildDir="$repo/build/qualify-$arm" --timings > "$QUALIFICATION_DIR/build-$arm.log" 2>&1
  python3 "$inputs/consumer_identity.py" "check-$arm" --root "$QUALIFICATION_DIR" --inspector-runtime "$INSPECTOR_RUNTIME" --source "$SOURCE_SHA" --artifacts "$ARTIFACT_DIR"
  candidate="$repo/build/qualify-$arm/bun"
  if test "$arm" = baseline; then
    python3 "$inputs/consumer_identity.py" baseline --root "$QUALIFICATION_DIR" --inspector-runtime "$INSPECTOR_RUNTIME"
  else
    # Test-only input is copied after compilation and never enters the compiled index.
    test ! -e test/js/node/worker_threads/openclaw-resource-limits.test.ts
    cp "$inputs/worker-resource-limits.test.ts" test/js/node/worker_threads/openclaw-resource-limits.test.ts
    python3 "$inputs/consumer_identity.py" create --root "$QUALIFICATION_DIR" --inspector-runtime "$INSPECTOR_RUNTIME" --source "$SOURCE_SHA" --artifacts "$ARTIFACT_DIR" --receipt "$QUALIFICATION_DIR/candidate-identity.json"
  fi
  sha256sum "$candidate" > "$QUALIFICATION_DIR/bun-$arm.sha256"
  results="$QUALIFICATION_DIR/$arm"
  mkdir -p "$results" "$results/home" "$results/tmp" "$results/bin"
  chmod 700 "$results/home" "$results/tmp"
  ln -s "$candidate" "$results/bin/bun"
  mkdir -p build/openclaw-ci
  cp "$inputs/selected.json" build/openclaw-ci/selected.json
  cp "$inputs/selected.json" "$results/selected.json"
  rm -f build/openclaw-ci/results.json
  env -u BUN_WEBKIT_ARTIFACT_MANIFEST -u BUN_BUILD_CACHE_DIR -u BUN_BUILD_PREFETCH_DIR \
    HOME="$results/home" TMPDIR="$results/tmp" PATH="$results/bin:$PATH" OPENCLAW_CI_PLATFORM=linux \
    "$candidate" scripts/openclaw-ci/tests.ts test > "$results/tests.log" 2>&1
  cp build/openclaw-ci/results.json "$results/results.json"
done
python3 "$inputs/compare-fork-ci.py" "$QUALIFICATION_DIR/baseline" "$QUALIFICATION_DIR/candidate" --output "$QUALIFICATION_DIR/faithfulness.json"
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
python3 "$inputs/consumer_identity.py" verify --root "$QUALIFICATION_DIR" --inspector-runtime "$INSPECTOR_RUNTIME" --source "$SOURCE_SHA" --artifacts "$ARTIFACT_DIR" --receipt "$QUALIFICATION_DIR/candidate-identity.json"
PYTHONPATH="$inputs" python3 - "$QUALIFICATION_DIR" "$SOURCE_SHA" <<'PY'
import json,re,sys
from pathlib import Path
from consumer_identity import sha,validate,validate_baseline
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
 assert passes and int(passes[1])>=minimum,name+' missing passing cases'
 assert re.search(r'\b0 fail\b',text),name+' failures'
identity=validate(json.loads((root/'candidate-identity.json').read_text()),sys.argv[2])
validate_baseline(json.loads((root/'baseline-identity.json').read_text()))
(root/'gate.json').write_text(json.dumps({'passed':True,'source':sys.argv[2],
 'comparison':'bun-plus-engine-upgrade','selected_files':44,'result_files':46,
 'als_variants_per_mode':14,'proxy_minimum':4,'resource_minimum':16,
 'candidate_identity_sha256':sha(root/'candidate-identity.json'),
 'baseline_identity_sha256':sha(root/'baseline-identity.json')},indent=2)+'\n')
PY
