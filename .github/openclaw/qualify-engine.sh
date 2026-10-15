#!/usr/bin/env bash
set -euo pipefail
: "${ARTIFACT_DIR:?}" "${QUALIFICATION_DIR:?}"
mkdir -p "$QUALIFICATION_DIR/engine"
QUALIFICATION_DIR=$(realpath "$QUALIFICATION_DIR")
source_sha=$(git rev-parse HEAD)
tar -xzf "$ARTIFACT_DIR/bun-webkit-linux-amd64.tar.gz" -C "$QUALIFICATION_DIR/engine"
jsc="$QUALIFICATION_DIR/engine/bun-webkit/bin/jsc"
"$jsc" --useDollarVM=true -e 'if(typeof $vm.moduleNamespaceForRequire!=="function")throw Error("namespace hook absent")'
Tools/Scripts/run-jsc-stress-tests JSTests/stress --jsc "$jsc" --child-processes 16 \
  --filter 'promise|microtask|dynamic-import|bun-async-context|module-loader|top-level-await|async-module|module-namespace|intl-segmenter|callsite-syntax-positions|stack-position-regressions|error-stack|worker-heap-generational-cadence|array-buffer-allocation-should-trigger-gc|extra-memory-allocation-should-trigger-gc|array-buffer-extra-memory-classification' \
  --output-dir "$QUALIFICATION_DIR/jsc-stress" --no-retry > "$QUALIFICATION_DIR/jsc-stress.log" 2>&1
python3 .github/openclaw/verify-jsc-results.py "$QUALIFICATION_DIR/jsc-stress" --require module-namespace-esmodule-marker.js --require callsite-syntax-positions.js --require stack-position-regressions.js --require stack-position-regressions-cache.js --require worker-heap-generational-cadence.js --require array-buffer-allocation-should-trigger-gc.js --require extra-memory-allocation-should-trigger-gc.js --require array-buffer-extra-memory-classification.js
python3 .github/openclaw/check-stack-visitor.py "$jsc" > "$QUALIFICATION_DIR/stack-visitor.log"
WEBKIT_CHECKOUT="$PWD" JSC="$jsc" RESULT_DIR="$QUALIFICATION_DIR/jsc-stack" bash .github/openclaw/qualification/stack/check-jsc.sh
Tools/Scripts/run-jsc-stress-tests JSTests/modules.yaml --jsc "$jsc" --child-processes 16 \
  --output-dir "$QUALIFICATION_DIR/jsc-modules" --no-retry > "$QUALIFICATION_DIR/jsc-modules.log" 2>&1
"$jsc" --useDollarVM=true --useImportDefer=true .github/openclaw/qualification/als/jsc/module-context.js > "$QUALIFICATION_DIR/jsc-context.log" 2>&1
fixture=JSTests/stress/heap-allocation-sampling.js
common=(--useDollarVM=true --useGenerationalGC=true --forceMiniVMMode=false)
"$jsc" "${common[@]}" "$fixture" > "$QUALIFICATION_DIR/sampling-default.log" 2>&1
"$jsc" "${common[@]}" --useJIT=false "$fixture" > "$QUALIFICATION_DIR/sampling-interpreter.log" 2>&1
"$jsc" "${common[@]}" --useDFGJIT=false --useFTLJIT=false "$fixture" > "$QUALIFICATION_DIR/sampling-baseline.log" 2>&1
"$jsc" "${common[@]}" --useConcurrentJIT=false --thresholdForOptimizeAfterWarmUp=10 --thresholdForFTLOptimizeAfterWarmUp=20 "$fixture" > "$QUALIFICATION_DIR/sampling-ftl.log" 2>&1
fixture=JSTests/stress/array-buffer-accounting.js
common=(--useGenerationalGC=true --forceMiniVMMode=false)
"$jsc" "${common[@]}" --useJIT=false "$fixture" > "$QUALIFICATION_DIR/accounting-interpreter.log" 2>&1
"$jsc" "${common[@]}" --useDFGJIT=false --useFTLJIT=false "$fixture" > "$QUALIFICATION_DIR/accounting-baseline.log" 2>&1
"$jsc" "${common[@]}" --useFTLJIT=false --useConcurrentJIT=false "$fixture" > "$QUALIFICATION_DIR/accounting-dfg.log" 2>&1
"$jsc" "${common[@]}" --useConcurrentJIT=false --thresholdForJITAfterWarmUp=10 --thresholdForOptimizeAfterWarmUp=20 --thresholdForFTLOptimizeAfterWarmUp=20 "$fixture" > "$QUALIFICATION_DIR/accounting-ftl.log" 2>&1
"$jsc" "${common[@]}" --gcAtEnd=true --useConcurrentGC=true "$fixture" > "$QUALIFICATION_DIR/accounting-concurrent.log" 2>&1
python3 - "$QUALIFICATION_DIR" "$source_sha" <<'PY'
import json,sys
from pathlib import Path
root=Path(sys.argv[1]);counts={}
for name,minimum in [('jsc-stress',1400),('jsc-modules',1600)]:
    lines=(root/name/'results').read_text().splitlines()
    assert len(lines)>=minimum,(name,len(lines))
    assert all(line.endswith(': PASS') for line in lines),name+' failures'
    counts[name]=len(lines)
(root/'engine-gate.json').write_text(json.dumps({'passed':True,'source':sys.argv[2],'stress_counts':counts,'sampling_tiers':4,'arraybuffer_execution_modes':5,'stack_execution_modes':7,'stack_cache':json.loads((root/'jsc-stack/cache-files.json').read_text())},indent=2)+'\n')
PY
