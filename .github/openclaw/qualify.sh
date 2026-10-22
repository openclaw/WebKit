#!/usr/bin/env bash
set -euo pipefail
umask 022
pipeline=$(pwd)
inputs="$pipeline/.github/openclaw/qualification"
: "${ARTIFACT_DIR:?}"
: "${QUALIFICATION_DIR:?}"
mkdir -p "$QUALIFICATION_DIR"
QUALIFICATION_DIR=$(realpath "$QUALIFICATION_DIR")
BUN_COMMIT=$(python3 -c 'import json;print(json.load(open(".github/openclaw/variants.json"))["bun_commit"])')
BASE=1600131e46b5af48bbda3559af8d8a3327230b6e
SOURCE_SHA=$(git rev-parse HEAD)
export CI=1 PUPPETEER_SKIP_DOWNLOAD=1
# Separate source/build/cache directories prevent an old engine ABI from being reused.
git clone --depth=1 --filter=blob:none --no-checkout https://github.com/openclaw/bun.git "$QUALIFICATION_DIR/bun"
cd "$QUALIFICATION_DIR/bun"
git fetch --depth=1 origin "$BUN_COMMIT"
git checkout --detach "$BUN_COMMIT"
git apply "$inputs/patches/000-checksums.patch"
# Apply openclaw/bun#151 equally to both frozen-source arms.
git apply "$inputs/patches/012-vm-finalization-fixture.patch"
sha256sum "$inputs/patches/012-vm-finalization-fixture.patch" > "$QUALIFICATION_DIR/vm-finalization-fixture.sha256"
# Match the qualified host Node and preserve its authenticated session identity in both arms.
git apply "$inputs/patches/013-node-reference-fixtures.patch"
sha256sum "$inputs/patches/013-node-reference-fixtures.patch" > "$QUALIFICATION_DIR/node-reference-fixtures.sha256"
bootstrap=$(command -v bun)
"$bootstrap" install --frozen-lockfile
(cd test && "$bootstrap" install --frozen-lockfile)
python3 "$inputs/stage-local-artifact.py" "$ARTIFACT_DIR/bun-webkit-linux-amd64.tar.gz" --version "$SOURCE_SHA" --output "$QUALIFICATION_DIR/candidate-input"
for arm in baseline candidate; do
  if test "$arm" = candidate; then
    for patch in "$inputs/patches/001-proxy.patch" "$inputs"/patches/00[3-7]-*.patch; do
      git apply --exclude=CHANGELOG.md --exclude='docs/*' --exclude='test/js/node/worker_threads/*' "$patch"
    done
    git apply --exclude=CHANGELOG.md --exclude='docs/*' "$inputs/patches/008-namespace.patch"
    git apply --exclude=CHANGELOG.md --exclude='docs/*' "$inputs/patches/009-stack-positions.patch"
    git apply --exclude=CHANGELOG.md --exclude='docs/*' "$inputs/patches/010-arraybuffer-accounting.patch"
    git apply "$inputs/patches/011-bun-gc-timer-wake.patch"
    cp "$inputs/worker-resource-limits.test.ts" test/js/node/worker_threads/openclaw-resource-limits.test.ts
    git diff --check
    git diff --binary HEAD > "$QUALIFICATION_DIR/bun-adapters.patch"
    export BUN_WEBKIT_ARTIFACT_MANIFEST="$QUALIFICATION_DIR/candidate-input/artifacts.json"
    export BUN_BUILD_PREFETCH_DIR="$QUALIFICATION_DIR/candidate-input/prefetch"
    revision="$SOURCE_SHA"
  else
    export BUN_WEBKIT_ARTIFACT_MANIFEST="$inputs/upstream-artifacts.json"
    export BUN_BUILD_PREFETCH_DIR="$QUALIFICATION_DIR/baseline-prefetch"
    revision="$BASE"
  fi
  sha256sum test/js/node/vm/vm.test.ts > "$QUALIFICATION_DIR/vm-test-$arm.sha256"
  export BUN_BUILD_CACHE_DIR="$QUALIFICATION_DIR/cache-$arm"
  env -u GITHUB_SHA -u BUILDKITE_COMMIT -u GIT_SHA "$bootstrap" run build:release --lto=off --webkit-version="$revision" --buildDir="$QUALIFICATION_DIR/bun/build/qualify-$arm" --timings > "$QUALIFICATION_DIR/build-$arm.log" 2>&1
  candidate="$QUALIFICATION_DIR/bun/build/qualify-$arm/bun"
  "$candidate" -e 'if(process.versions.webkit!==process.argv[1] || Bun.revision!==process.argv[2]) throw new Error("wrong engine or Bun source revision");' "$revision" "$BUN_COMMIT"
  sha256sum "$candidate" > "$QUALIFICATION_DIR/bun-$arm.sha256"
  results="$QUALIFICATION_DIR/$arm"
  mkdir -p "$results" "$results/home" "$results/tmp" "$results/bin"
  chmod 700 "$results/home" "$results/tmp"
  ln -s "$candidate" "$results/bin/bun"
  mkdir -p build/openclaw-ci
  cp "$inputs/selected.json" build/openclaw-ci/selected.json
  cp "$inputs/selected.json" "$results/selected.json"
  rm -f build/openclaw-ci/results.json
  # Retain both arms when a reference fails; the strict all-pass gate below still rejects failures.
  if env -u BUN_WEBKIT_ARTIFACT_MANIFEST -u BUN_BUILD_CACHE_DIR -u BUN_BUILD_PREFETCH_DIR \
    HOME="$results/home" TMPDIR="$results/tmp" PATH="$results/bin:$PATH" OPENCLAW_CI_PLATFORM=linux \
    "$candidate" scripts/openclaw-ci/tests.ts test > "$results/tests.log" 2>&1; then
    printf '0\n' > "$results/exit-code.log"
  else
    printf '%s\n' "$?" > "$results/exit-code.log"
  fi
  cp build/openclaw-ci/results.json "$results/results.json"
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
mkdir -p "$QUALIFICATION_DIR/worker-engine"
tar -xzf "$ARTIFACT_DIR/bun-webkit-linux-amd64.tar.gz" -C "$QUALIFICATION_DIR/worker-engine"
WK="$QUALIFICATION_DIR/worker-engine/bun-webkit"
clang++-23 -std=c++23 -O2 -DNDEBUG -DBUILDING_WITH_CMAKE=1 -DHAVE_CONFIG_H=1 \
  -I"$WK/include" -I"$WK/include/JavaScriptCore" -I"$WK/include/wtf" \
  "$inputs/engine-limit-probe.cpp" "$QUALIFICATION_DIR/bun/build/qualify-candidate/obj/vendor/mimalloc/src/static.c.o" \
  -Wl,--start-group "$WK"/lib/*.a -Wl,--end-group -lpthread -ldl -lm -latomic \
  -o "$QUALIFICATION_DIR/engine-limit-probe" > "$QUALIFICATION_DIR/engine-limit-build.log" 2>&1
"$QUALIFICATION_DIR/engine-limit-probe" > "$QUALIFICATION_DIR/engine-limits.log" 2>&1
clang++-23 -std=c++23 -O2 -DNDEBUG -DBUILDING_WITH_CMAKE=1 -DHAVE_CONFIG_H=1 \
  -I"$WK/include" -I"$WK/include/JavaScriptCore" -I"$WK/include/wtf" \
  "$inputs/engine-gc-progress-probe.cpp" "$QUALIFICATION_DIR/bun/build/qualify-candidate/obj/vendor/mimalloc/src/static.c.o" \
  -Wl,--start-group "$WK"/lib/*.a -Wl,--end-group -lpthread -ldl -lm -latomic \
  -o "$QUALIFICATION_DIR/engine-gc-progress-probe" > "$QUALIFICATION_DIR/engine-gc-progress-build.log" 2>&1
"$QUALIFICATION_DIR/engine-gc-progress-probe" > "$QUALIFICATION_DIR/engine-gc-progress.json" 2> "$QUALIFICATION_DIR/engine-gc-progress.log"
"$candidate" "$inputs/module-context.mjs" matrix > "$QUALIFICATION_DIR/als-plugin.json"
"$candidate" "$inputs/module-context.mjs" matrix --native-hooks > "$QUALIFICATION_DIR/als-native.json"
python3 - "$QUALIFICATION_DIR" "$SOURCE_SHA" "$BUN_COMMIT" <<'PY'
import json,re,sys,hashlib
from pathlib import Path
root=Path(sys.argv[1])
faith=json.loads((root/'faithfulness.json').read_text())
assert faith['identical_file_outcomes'] and faith['all_passed']
assert all((root/arm/'exit-code.log').read_text().strip() == '0' for arm in ['baseline','candidate']), 'fork test runner failed'
assert faith['selected_files']==44 and faith['result_files']==46
for name in ['als-plugin','als-native']:
 rows=json.loads((root/(name+'.json')).read_text())['results']
 assert len(rows)==14 and all(r['exitCode']==0 for r in rows)
for name,minimum in [('proxy',4),('resource-limits',16),('namespace',41),('arraybuffer',19),('worker-statistics',7)]:
 text=(root/(name+'.log')).read_text()
 passes=re.search(r'(\d+) pass',text)
 assert passes and int(passes[1])>=minimum, name+' missing passing cases'
 assert re.search(r'\b0 fail\b',text),name+' failures'
gc_progress=json.loads((root/'engine-gc-progress.json').read_text())
assert all(gc_progress[key] is True for key in ['passed','passiveCollectorObserved','completedBeforeHelperRelease','rootsSurvived']),'passive collector did not progress'
assert all(gc_progress[key] is False for key in ['lateWaitStallObserved','timedOut']),'passive collector stalled'
assert type(gc_progress['helperCount']) is int and gc_progress['helperCount']>0,'GC helper precondition missing'
(root/'gate.json').write_text(json.dumps({'passed':True,'source':sys.argv[2],'bun_commit':sys.argv[3],
 'selected_files':44,'result_files':46,'als_variants_per_mode':14,'proxy_minimum':4,'resource_minimum':16,
 'gc_progress':gc_progress,
 'bun_adapter_sha256':hashlib.sha256((root/'bun-adapters.patch').read_bytes()).hexdigest()},indent=2)+'\n')
PY
