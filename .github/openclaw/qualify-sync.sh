#!/usr/bin/env bash
set -euo pipefail
pipeline=$(pwd)
inputs="$pipeline/.github/openclaw/qualification"
: "${ARTIFACT_DIR:?}" "${QUALIFICATION_DIR:?}"
QUALIFICATION_DIR=$(realpath "$QUALIFICATION_DIR")
SOURCE_SHA=$(git rev-parse HEAD)
BUN_BASE=d2d2a26ef973cdd97b37953f5dba58052acad74f
SYNC_TREE=d9ec052fccc81afbf43a5344e52bc980f439d587
bootstrap=$(command -v bun)
export CI=1 PUPPETEER_SKIP_DOWNLOAD=1
repo="$QUALIFICATION_DIR/bun-sync"
results="$QUALIFICATION_DIR/sync"
mkdir -p "$results/home" "$results/tmp" "$results/bin"
chmod 700 "$results/home" "$results/tmp"
git clone --depth=1 --filter=blob:none --no-checkout https://github.com/openclaw/bun.git "$repo"
cd "$repo"
git fetch --depth=1 origin "$BUN_BASE"
git checkout --detach "$BUN_BASE"
git apply --index "$inputs/sync/upstream-sync.patch"
test "$(git write-tree)" = "$SYNC_TREE"
# The complete W150 prepared tree is verified before qualification-only adapters.
for patch in "$inputs"/patches/00[3-7]-*.patch; do
  git apply --index --exclude=CHANGELOG.md --exclude='docs/*' --exclude='test/js/node/worker_threads/*' "$patch"
done
for patch in 008-namespace.patch 009-allocation-sampling.patch 010-als-regressions.patch 009-stack-positions.patch 010-arraybuffer-accounting.patch; do
  git apply --index --exclude=CHANGELOG.md --exclude='docs/*' "$inputs/patches/$patch"
done
git apply --index "$inputs/sync/inspect-stack-position.patch"
git apply --index "$inputs/patches/011-bun-gc-timer-wake.patch"
git apply --index "$inputs/patches/012-vm-finalization-fixture.patch"
sha256sum test/js/node/vm/vm.test.ts > "$QUALIFICATION_DIR/vm-test-sync.sha256"
cp "$inputs/worker-resource-limits.test.ts" test/js/node/worker_threads/openclaw-resource-limits.test.ts
git add test/js/node/worker_threads/openclaw-resource-limits.test.ts
python3 "$inputs/stage-sync-artifact.py" "$ARTIFACT_DIR/bun-webkit-linux-amd64.tar.gz" --version "$SOURCE_SHA" --output "$QUALIFICATION_DIR/sync-input"
cp "$QUALIFICATION_DIR/sync-input/artifacts.json" scripts/build/deps/webkit-artifacts.json
git add scripts/build/deps/webkit-artifacts.json
git diff --check HEAD
git diff --binary HEAD > "$QUALIFICATION_DIR/bun-sync-adapters.patch"
"$bootstrap" install --frozen-lockfile
(cd test && "$bootstrap" install --frozen-lockfile)
export BUN_BUILD_PREFETCH_DIR="$QUALIFICATION_DIR/sync-input/prefetch"
export BUN_BUILD_CACHE_DIR="$QUALIFICATION_DIR/cache-sync"
env -u GITHUB_SHA -u BUILDKITE_COMMIT -u GIT_SHA "$bootstrap" run build:release --lto=off --buildDir="$repo/build/qualify-sync" --timings > "$QUALIFICATION_DIR/build-sync.log" 2>&1
candidate="$repo/build/qualify-sync/bun"
"$candidate" -e 'if(process.versions.webkit!==process.argv[1] || Bun.revision!==process.argv[2]) throw new Error("wrong engine or Bun source revision");' "$SOURCE_SHA" "$BUN_BASE"
sha256sum "$candidate" > "$QUALIFICATION_DIR/bun-sync.sha256"
"$candidate" --revision > "$results/revision.log"
"$candidate" -e 'const server=Bun.serve({port:0,fetch(){return new Response("ready")}});try{if(await(await fetch(server.url)).text()!=="ready")throw Error("startup");console.log("build/startup/http passed")}finally{await server.stop(true)}' > "$results/startup.log" 2>&1
unset BUN_BUILD_PREFETCH_DIR BUN_BUILD_CACHE_DIR BUN_WEBKIT_ARTIFACT_MANIFEST
ln -s "$candidate" "$results/bin/bun"
export HOME="$results/home" TMPDIR="$results/tmp" PATH="$results/bin:$PATH" OPENCLAW_CI_PLATFORM=linux
# Recompute the engine/nightly selection and retain every W150 upstream-sync case.
"$candidate" --eval 'import {selectTests} from "./scripts/openclaw-ci/tests.ts"; import{execFileSync}from"node:child_process";import{readFileSync,writeFileSync,mkdirSync}from"node:fs";const tracked=execFileSync("git",["ls-files","-z","test"],{encoding:"utf8"}).split("\0").filter(Boolean);const original=JSON.parse(readFileSync(process.argv[1],"utf8"));const selected=[...new Set([...original,...selectTests(["scripts/build/deps/webkit.ts"],tracked,true,"linux")])].sort();for(const file of selected)if(!tracked.includes(file))throw Error("missing selected test "+file);mkdirSync("build/openclaw-ci",{recursive:true});writeFileSync("build/openclaw-ci/selected.json",JSON.stringify(selected,null,2)+"\n");' "$inputs/sync/selected.json"
cp build/openclaw-ci/selected.json "$results/selected.json"
if "$candidate" scripts/openclaw-ci/tests.ts test > "$results/tests.log" 2>&1; then
  selection_exit=0
else
  selection_exit=$?
fi
if test -f build/openclaw-ci/results.json; then
  cp build/openclaw-ci/results.json "$results/results.json"
fi
if test "$selection_exit" -ne 0; then exit "$selection_exit"; fi
# Run these unchanged upstream tests explicitly as well, so skips cannot satisfy the gate.
"$candidate" test test/js/web/atomics.test.ts test/js/bun/wasm/compile-rss.test.ts -t 'Atomics.wait lets mimalloc|a notify that arrives while Atomics.wait|WebAssembly.compile does not retain' > "$results/memory-release.log" 2>&1
"$candidate" test --expose-internals test/js/node/v8/capture-stack-trace.test.js test/js/node/util/util.test.js test/js/bun/sourcemap > "$results/stack-positions.log" 2>&1
"$candidate" test test/bundler/bundler_minify.test.ts > "$results/stack-minifier.log" 2>&1
python3 "$inputs/stack/check-runtime-cache.py" --baseline "$QUALIFICATION_DIR/bun/build/qualify-baseline/bun" --candidate "$candidate" --fixture "$inputs/stack/observe-regressions.js" --output "$results/runtime-cache" --expected-version 38 > "$results/stack-cache.json"
"$candidate" "$inputs/segmenter.js" > "$results/segmenter.log" 2>&1
"$candidate" test test/js/node/vm/vm.test.ts -t 'a Proxy in the prototype chain' > "$results/proxy.log" 2>&1
"$candidate" test test/js/node/worker_threads/openclaw-resource-limits.test.ts -t resourceLimits > "$results/resource-limits.log" 2>&1
"$candidate" test test/js/bun/resolve/esModule.test.ts test/js/bun/namespace-prototype-pollution.test.ts test/js/bun/resolve/require-esm-evaluating-cycle.test.ts test/js/bun/import-attributes/import-attributes.test.ts test/js/node/module/require-extensions.test.ts > "$results/namespace.log" 2>&1
"$candidate" test test/js/node/process/process.test.js -t 'ArrayBuffer memory ownership' > "$results/arraybuffer.log" 2>&1
"$candidate" test test/js/node/worker_threads/worker_threads.test.ts -t 'getHeapStatistics' > "$results/worker-statistics.log" 2>&1
"$candidate" test test/napi/napi.test.ts -t 'charges external payload without charging the ArrayBuffer allocator' > "$results/arraybuffer-native.log" 2>&1
"$candidate" test --expose-internals test/js/bun/jsc/bun-jsc.test.ts test/js/node/v8/v8-serdes-buffer.test.ts > "$results/arraybuffer-serializer.log" 2>&1
"$candidate" test "$inputs/inspection-idle.test.ts" > "$results/inspection-idle.log" 2>&1
"$candidate" test test/js/node/inspector/inspector-profiler.test.ts test/js/node/inspector/inspector.test.ts > "$results/inspector.log" 2>&1
"$candidate" test test/js/node/async_hooks test/js/bun/resolve/import-defer.test.ts test/js/bun/resolve/dynamic-import-tla-cycle.test.ts test/js/bun/resolve/require-esm-gc-roots.test.ts test/js/bun/resolve/require-esm-microtask-order.test.ts test/js/bun/resolve/require-esm-evaluating-cycle.test.ts test/js/bun/resolve/require-esm-transitive-tla.test.ts > "$results/als-suites.log" 2>&1
"$candidate" "$inputs/module-context.mjs" matrix > "$results/als-plugin.json"
"$candidate" "$inputs/module-context.mjs" matrix --native-hooks > "$results/als-native.json"
BUN_JSC_collectContinuously=1 "$candidate" "$inputs/module-context.mjs" matrix > "$results/als-gc.json"
"$candidate" "$inputs/als/realm-require.mjs" > "$results/als-realm.log" 2>&1
"$candidate" "$inputs/als/retention.mjs" > "$results/als-retention.json" 2>&1
WK="$QUALIFICATION_DIR/engine/bun-webkit"
clang++-23 -std=c++23 -O2 -DNDEBUG -DBUILDING_WITH_CMAKE=1 -DHAVE_CONFIG_H=1 \
  -I"$WK/include" -I"$WK/include/JavaScriptCore" -I"$WK/include/wtf" \
  "$inputs/engine-limit-probe.cpp" "$repo/build/qualify-sync/obj/vendor/mimalloc/src/static.c.o" \
  -Wl,--start-group "$WK"/lib/*.a -Wl,--end-group -lpthread -ldl -lm -latomic \
  -o "$results/engine-limit-probe" > "$results/engine-limit-build.log" 2>&1
"$results/engine-limit-probe" > "$results/engine-limits.log" 2>&1
clang++-23 -std=c++23 -O2 -DNDEBUG -DBUILDING_WITH_CMAKE=1 -DHAVE_CONFIG_H=1 \
  -I"$WK/include" -I"$WK/include/JavaScriptCore" -I"$WK/include/wtf" \
  "$inputs/engine-gc-progress-probe.cpp" "$repo/build/qualify-sync/obj/vendor/mimalloc/src/static.c.o" \
  -Wl,--start-group "$WK"/lib/*.a -Wl,--end-group -lpthread -ldl -lm -latomic \
  -o "$results/engine-gc-progress-probe" > "$results/engine-gc-progress-build.log" 2>&1
"$results/engine-gc-progress-probe" > "$results/engine-gc-progress.json" 2> "$results/engine-gc-progress.log"
python3 "$inputs/verify-sync.py" "$QUALIFICATION_DIR" "$SOURCE_SHA" "$BUN_BASE" "$SYNC_TREE"
