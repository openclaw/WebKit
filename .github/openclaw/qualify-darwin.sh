#!/usr/bin/env bash
set -euo pipefail
umask 022
: "${ARTIFACT_DIR:?}" "${QUALIFICATION_DIR:?}" "${INSPECTOR_RUNTIME:?}"
test "$(uname -s)" = Darwin && test "$(uname -m)" = arm64
pipeline=$(pwd -P)
inputs="$pipeline/.github/openclaw/qualification"
source_sha=$(git rev-parse HEAD)
lane=bun-webkit-macos-arm64-aot
test -d "$QUALIFICATION_DIR/bun/.git"
QUALIFICATION_DIR=$(cd "$QUALIFICATION_DIR" && pwd -P)
ARTIFACT_DIR=$(cd "$ARTIFACT_DIR" && pwd -P)
bootstrap="$INSPECTOR_RUNTIME"
test -x "$bootstrap"
export CI=1 PUPPETEER_SKIP_DOWNLOAD=1 OPENCLAW_CI_PLATFORM=darwin
commit=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["candidate"]["commit"])' "$pipeline/.github/openclaw/variants.json")
tree=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["candidate"]["tree"])' "$pipeline/.github/openclaw/variants.json")
repo="$QUALIFICATION_DIR/bun"
cd "$repo"
test "$(git rev-parse HEAD)" = "$commit"
test "$(git rev-parse HEAD^{tree})" = "$tree"
git diff --exit-code HEAD
unset BUN_WEBKIT_ARTIFACT_MANIFEST
python3 "$inputs/stage-sync-artifact.py" "$ARTIFACT_DIR/$lane.tar.gz" \
  --lane-manifest "$ARTIFACT_DIR/$lane.manifest.json" --lane "$lane" \
  --version "$source_sha" --output "$QUALIFICATION_DIR/candidate-input"
cp "$QUALIFICATION_DIR/candidate-input/artifacts.json" scripts/build/deps/webkit-artifacts.json
git diff --binary HEAD > "$QUALIFICATION_DIR/candidate-manifest.patch"
export BUN_BUILD_PREFETCH_DIR="$QUALIFICATION_DIR/candidate-input/prefetch"
export BUN_BUILD_CACHE_DIR="$QUALIFICATION_DIR/cache-candidate"
"$bootstrap" install --frozen-lockfile
(cd test && "$bootstrap" install --frozen-lockfile)
python3 "$inputs/consumer_identity.py" check-candidate --lane "$lane" --root "$QUALIFICATION_DIR" \
  --inspector-runtime "$bootstrap" --source "$source_sha" --artifacts "$ARTIFACT_DIR"
python3 "$inputs/harness_adapters.py" build --name candidate --lane "$lane" --root "$QUALIFICATION_DIR" \
  --inspector-runtime "$bootstrap" --source "$source_sha" --artifacts "$ARTIFACT_DIR"
# The shared receipt includes this test-only input, copied after native compilation.
test ! -e test/js/node/worker_threads/openclaw-resource-limits.test.ts
cp "$inputs/worker-resource-limits.test.ts" test/js/node/worker_threads/openclaw-resource-limits.test.ts
python3 "$inputs/consumer_identity.py" create --lane "$lane" --root "$QUALIFICATION_DIR" \
  --inspector-runtime "$bootstrap" --source "$source_sha" --artifacts "$ARTIFACT_DIR" \
  --receipt "$QUALIFICATION_DIR/candidate-identity.json"
(cd "$repo/build/qualify-candidate" && shasum -a 256 bun) > "$QUALIFICATION_DIR/bun-candidate.sha256"
results="$QUALIFICATION_DIR/candidate"
mkdir -p "$results/home" "$results/tmp" "$results/bin" "$QUALIFICATION_DIR/sync" build/openclaw-ci
chmod 700 "$results/home" "$results/tmp"
ln -s "$repo/build/qualify-candidate/bun" "$results/bin/bun"
# Recompute with the pinned selection owner; reject drift from the reviewed ordered list.
"$bootstrap" --eval 'import {selectTests} from "./scripts/openclaw-ci/tests.ts";const tracked=Bun.spawnSync(["git","ls-files","-z"]);if(tracked.exitCode!==0)throw new Error("tracked source inventory failed");console.log(JSON.stringify(selectTests(["scripts/build/deps/webkit.ts"],tracked.stdout.toString().split("\0").filter(Boolean),true,"darwin"),null,2));' > build/openclaw-ci/selected.json
cmp "$inputs/darwin-selected.json" build/openclaw-ci/selected.json
cp build/openclaw-ci/selected.json "$results/selected.json"
python3 "$inputs/harness_adapters.py" test --name candidate --lane "$lane" --root "$QUALIFICATION_DIR" \
  --inspector-runtime "$bootstrap" --source "$source_sha" --artifacts "$ARTIFACT_DIR"
unset BUN_WEBKIT_ARTIFACT_MANIFEST BUN_BUILD_PREFETCH_DIR BUN_BUILD_CACHE_DIR
"$repo/build/qualify-candidate/bun" test test/aot/every-platform.test.ts > "$QUALIFICATION_DIR/sync/aot-every-platform.log" 2>&1
python3 "$inputs/consumer_identity.py" verify --lane "$lane" --root "$QUALIFICATION_DIR" \
  --inspector-runtime "$bootstrap" --source "$source_sha" --artifacts "$ARTIFACT_DIR" \
  --receipt "$QUALIFICATION_DIR/candidate-identity.json"
python3 "$inputs/darwin.py" --root "$QUALIFICATION_DIR" --binaries "$QUALIFICATION_DIR" \
  --source "$source_sha" --artifacts "$ARTIFACT_DIR"
