#!/usr/bin/env bash
set -euo pipefail
: "${ENGINE_BUILD_DIR:?}" "${QUALIFICATION_DIR:?}"
case "$(uname -m)" in arm64|aarch64) ;; *) echo 'Native ARM64 host required' >&2; exit 1;; esac
mkdir -p "$QUALIFICATION_DIR"
QUALIFICATION_DIR=$(cd "$QUALIFICATION_DIR" && pwd)
jsc="$ENGINE_BUILD_DIR/bin/jsc"
"$ENGINE_BUILD_DIR/bin/testmasm" > "$QUALIFICATION_DIR/testmasm.log" 2>&1
"$ENGINE_BUILD_DIR/bin/testFFI" > "$QUALIFICATION_DIR/testffi.log" 2>&1
"$ENGINE_BUILD_DIR/bin/testMimallocExit" > "$QUALIFICATION_DIR/mimalloc-exit.log" 2>&1
"$ENGINE_BUILD_DIR/bin/testMimallocExitInFlight" > "$QUALIFICATION_DIR/mimalloc-exit-in-flight.log" 2>&1
"$ENGINE_BUILD_DIR/bin/testVMEntryScope" > "$QUALIFICATION_DIR/vm-entry-scope.log" 2>&1
"$ENGINE_BUILD_DIR/bin/testForeignStackSuspension" > "$QUALIFICATION_DIR/foreign-stack-suspension.log" 2>&1
Tools/Scripts/run-jsc-stress-tests JSTests/stress --jsc "$jsc" --child-processes "${ENGINE_TEST_JOBS:-4}" \
  --filter 'promise|microtask|dynamic-import|bun-async-context|module-loader|top-level-await|async-module|module-namespace|intl-segmenter|callsite-syntax-positions|stack-position-regressions|error-stack|worker-heap-generational-cadence|array-buffer-allocation-should-trigger-gc|extra-memory-allocation-should-trigger-gc|array-buffer-extra-memory-classification' \
  --output-dir "$QUALIFICATION_DIR/jsc-stress" --no-retry > "$QUALIFICATION_DIR/jsc-stress.log" 2>&1
python3 .github/openclaw/verify-jsc-results.py "$QUALIFICATION_DIR/jsc-stress" --require module-namespace-esmodule-marker.js --require callsite-syntax-positions.js --require stack-position-regressions.js --require stack-position-regressions-cache.js --require worker-heap-generational-cadence.js --require array-buffer-allocation-should-trigger-gc.js --require extra-memory-allocation-should-trigger-gc.js --require array-buffer-extra-memory-classification.js
WEBKIT_CHECKOUT="$PWD" JSC="$jsc" RESULT_DIR="$QUALIFICATION_DIR/jsc-stack" bash .github/openclaw/qualification/stack/check-jsc.sh
Tools/Scripts/run-jsc-stress-tests JSTests/modules.yaml --jsc "$jsc" --child-processes "${ENGINE_TEST_JOBS:-4}" \
  --output-dir "$QUALIFICATION_DIR/jsc-modules" --no-retry > "$QUALIFICATION_DIR/jsc-modules.log" 2>&1
# Accounting requires generational GC; run its established explicit modes below.
for fixture in array-buffer-accounting heap-allocation-sampling; do
  for tier in interpreter baseline dfg ftl concurrent; do
    args=(--useGenerationalGC=true --forceMiniVMMode=false --useDollarVM=true)
    case "$tier" in
      interpreter) args+=(--useJIT=false);;
      baseline) args+=(--useDFGJIT=false --useFTLJIT=false);;
      dfg) args+=(--useFTLJIT=false --useConcurrentJIT=false --thresholdForJITAfterWarmUp=10 --thresholdForOptimizeAfterWarmUp=20);;
      ftl) args+=(--useConcurrentJIT=false --thresholdForJITAfterWarmUp=10 --thresholdForOptimizeAfterWarmUp=20 --thresholdForFTLOptimizeAfterWarmUp=20);;
      concurrent) args+=(--gcAtEnd=true --useConcurrentGC=true);;
    esac
    "$jsc" "${args[@]}" "JSTests/stress/$fixture.js" > "$QUALIFICATION_DIR/$fixture-$tier.log" 2>&1
  done
done
python3 - "$QUALIFICATION_DIR" "$(git rev-parse HEAD)" <<'PY'
import json, platform, sys
from pathlib import Path
out = Path(sys.argv[1])
counts = {}
for suite, minimum in [('jsc-stress', 1400), ('jsc-modules', 1600)]:
    lines = (out / suite / 'results').read_text().splitlines()
    assert len(lines) >= minimum and all(line.endswith(': PASS') for line in lines), suite
    counts[suite] = len(lines)
assert 'testAdd64RegisterAddress()' in (out / 'testmasm.log').read_text()
(out / 'arm64-gate.json').write_text(json.dumps({'passed': True, 'source': sys.argv[2], 'machine': platform.machine(), 'system': platform.system(), 'counts': counts, 'accounting_modes': 5, 'sampling_modes': 5, 'testmasm': True, 'testffi': True, 'vm_entry_scope': True, 'foreign_stack_suspension': True, 'stack_execution_modes': 7, 'stack_cache': json.loads((out / 'jsc-stack/cache-files.json').read_text())}, indent=2) + '\n')
PY
