#!/usr/bin/env bash
set -euo pipefail
: "${WEBKIT_CHECKOUT:?}" "${JSC:?}" "${RESULT_DIR:?}"
mkdir -p "$RESULT_DIR"
cd "$WEBKIT_CHECKOUT"
for mode in default interpreter optimizer eager-ftl; do
 args=()
 case "$mode" in
 interpreter) args=(--useJIT=false);;
 optimizer) args=(--useBytecodeOptimizer=true);;
 eager-ftl) args=(--useConcurrentJIT=false --thresholdForOptimizeAfterWarmUp=10 --thresholdForFTLOptimizeAfterWarmUp=20);;
 esac
 for fixture in callsite-syntax-positions.js stack-position-regressions.js stack-position-regressions-cache.js callsite-async-position.mjs; do
  module=(); case "$fixture" in *.mjs) module=(-m);; esac
  "$JSC" "${args[@]}" "${module[@]}" "JSTests/stress/$fixture" > "$RESULT_DIR/$mode-$fixture.log" 2>&1
 done
 printf '%s pass\n' "$mode" | tee -a "$RESULT_DIR/modes.txt"
done
for kind in owned persistent; do
 cache="$RESULT_DIR/cache-$kind";mkdir -p "$cache"
 args=(--diskCachePath="$cache")
 if test "$kind" = persistent; then args+=(--diskCachePayloadIsPersistentForTesting=true); fi
 for repeat in cold warm; do
  for fixture in callsite-syntax-positions.js stack-position-regressions.js stack-position-regressions-cache.js callsite-async-position.mjs; do
   module=(); case "$fixture" in *.mjs) module=(-m);; esac
   "$JSC" "${args[@]}" "${module[@]}" "JSTests/stress/$fixture" > "$RESULT_DIR/cache-$kind-$repeat-$fixture.log" 2>&1
  done
 done
done
python3 - "$RESULT_DIR" <<'COUNT'
from pathlib import Path
import json,sys
p=Path(sys.argv[1]);counts={}
for kind in ['owned','persistent']:
 files=[f for f in (p/('cache-'+kind)).rglob('*') if f.is_file()]
 counts[kind]={'files':len(files),'bytes':sum(f.stat().st_size for f in files)}
 assert len(files)>=3,counts
(p/'cache-files.json').write_text(json.dumps(counts,indent=2)+'\n')
COUNT
