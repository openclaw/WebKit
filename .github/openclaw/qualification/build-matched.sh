#!/usr/bin/env bash
# Sourced by the three qualification gates. Keep the production artifact resolver intact.
matched_commit=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["bun_commit"])' "$pipeline/.github/openclaw/variants.json")
matched_tree=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["bun_tree"])' "$pipeline/.github/openclaw/variants.json")

checkout_matched() {
  git clone --depth=1 --filter=blob:none --no-checkout https://github.com/openclaw/bun.git "$repo"
  cd "$repo"
  git fetch --depth=1 origin "$matched_commit"
  git checkout --detach "$matched_commit"
  test "$(git rev-parse HEAD)" = "$matched_commit"
  test "$(git write-tree)" = "$matched_tree"
  git diff --exit-code
}

build_matched() {
  local label=$1
  python3 "$inputs/stage-sync-artifact.py" "$ARTIFACT_DIR/bun-webkit-linux-amd64.tar.gz" --version "$SOURCE_SHA" --output "$QUALIFICATION_DIR/$label-input"
  cp "$QUALIFICATION_DIR/$label-input/artifacts.json" scripts/build/deps/webkit-artifacts.json
  test "$(git diff --name-only)" = scripts/build/deps/webkit-artifacts.json
  "$bootstrap" install --frozen-lockfile
  (cd test && "$bootstrap" install --frozen-lockfile)
  export BUN_BUILD_PREFETCH_DIR="$QUALIFICATION_DIR/$label-input/prefetch"
  export BUN_BUILD_CACHE_DIR="$QUALIFICATION_DIR/cache-$label"
  env -u BUN_WEBKIT_ARTIFACT_MANIFEST -u GITHUB_SHA -u BUILDKITE_COMMIT -u GIT_SHA "$bootstrap" run build:release --lto=off --buildDir="$repo/build/qualify-$label" --timings > "$QUALIFICATION_DIR/build-$label.log" 2>&1
  test "$(git write-tree)" = "$matched_tree"
  test "$(git diff --name-only)" = scripts/build/deps/webkit-artifacts.json
  candidate="$repo/build/qualify-$label/bun"
  "$candidate" -e 'if(process.versions.webkit!==process.argv[1] || Bun.revision!==process.argv[2]) throw new Error("wrong engine or Bun source revision");' "$SOURCE_SHA" "$matched_commit"
  sha256sum "$candidate" > "$QUALIFICATION_DIR/bun-$label.sha256"
  git diff --binary HEAD > "$QUALIFICATION_DIR/bun-$label-manifest.patch"
  unset BUN_BUILD_PREFETCH_DIR BUN_BUILD_CACHE_DIR BUN_WEBKIT_ARTIFACT_MANIFEST
}
