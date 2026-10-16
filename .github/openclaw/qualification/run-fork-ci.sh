#!/usr/bin/env bash
set -euo pipefail
test "$(uname -sm)" = 'Linux x86_64'
: "${BUN_CHECKOUT:?set Bun checkout}"
: "${CANDIDATE_BUN:?set an absolute candidate binary}"
: "${RESULT_DIR:?set a fresh absolute evidence directory}"
case "$RESULT_DIR" in /*) ;; *) exit 2;; esac
case "$CANDIDATE_BUN" in /*) ;; *) exit 2;; esac
test ! -e "$RESULT_DIR"
umask 077
mkdir -p "$RESULT_DIR" "$RESULT_DIR/home" "$RESULT_DIR/state" "$RESULT_DIR/tmp" "$RESULT_DIR/bin"
chmod 700 "$RESULT_DIR/home" "$RESULT_DIR/state" "$RESULT_DIR/tmp"
stat -c '%a %n' "$RESULT_DIR/home" "$RESULT_DIR/state" "$RESULT_DIR/tmp" > "$RESULT_DIR/private-directory-modes.txt"
umask 022
umask > "$RESULT_DIR/test-umask.txt"
ln -s "$CANDIDATE_BUN" "$RESULT_DIR/bin/bun"
export PATH="$RESULT_DIR/bin:$PATH" HOME="$RESULT_DIR/home" OPENCLAW_STATE_DIR="$RESULT_DIR/state" TMPDIR="$RESULT_DIR/tmp"
export CI=1 PUPPETEER_SKIP_DOWNLOAD=1 OPENCLAW_CI_PLATFORM=linux
unset PR_BASE_SHA PR_HEAD_SHA GITHUB_EVENT_NAME
unset BUN_WEBKIT_ARTIFACT_MANIFEST BUN_BUILD_PREFETCH_DIR BUN_BUILD_CACHE_DIR
cd "$BUN_CHECKOUT"
git rev-parse HEAD > "$RESULT_DIR/bun-sha.txt"
sha256sum "$CANDIDATE_BUN" > "$RESULT_DIR/bun.sha256"
"$CANDIDATE_BUN" --revision > "$RESULT_DIR/bun-revision.txt"
"$CANDIDATE_BUN" scripts/openclaw-ci/tests.ts select > "$RESULT_DIR/select.log" 2>&1
cp build/openclaw-ci/selected.json "$RESULT_DIR/nightly-selected.json"
# Include the fork's own engine-upgrade coverage added by the upstream sync.
node --input-type=module - <<'JS' >> "$RESULT_DIR/select.log" 2>&1
import { selectTests } from './scripts/openclaw-ci/tests.ts';
import { execFileSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';
const tracked = execFileSync('git', ['ls-files', '-z', 'test'], { encoding: 'utf8' }).split('\0').filter(Boolean);
const selected = selectTests(['scripts/build/deps/webkit.ts'], tracked, true, 'linux');
writeFileSync('build/openclaw-ci/selected.json', JSON.stringify(selected, null, 2) + '\n');
console.log(JSON.stringify({ selectorInput: { changed: ['scripts/build/deps/webkit.ts'], nightly: true, platform: 'linux' }, files: selected.length }));
JS
cp build/openclaw-ci/selected.json "$RESULT_DIR/selected.json"
# Do not reuse a report left by a prior variant if this run crashes.
rm -f build/openclaw-ci/results.json
set +e
/usr/bin/time -v -o "$RESULT_DIR/test-time.txt" \
  "$CANDIDATE_BUN" scripts/openclaw-ci/tests.ts test > "$RESULT_DIR/tests.log" 2>&1
rc=$?
set -e
printf '%s\n' "$rc" > "$RESULT_DIR/exit-code.txt"
if test -f build/openclaw-ci/results.json; then
  cp build/openclaw-ci/results.json "$RESULT_DIR/results.json"
fi
exit "$rc"
