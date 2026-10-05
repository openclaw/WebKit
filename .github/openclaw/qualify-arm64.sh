#!/usr/bin/env bash
set -euo pipefail
: "${JSC_BUILD_DIR:?}" "${QUALIFICATION_DIR:?}"
case "$(uname -m)" in arm64|aarch64) ;; *) echo 'Native ARM64 host required' >&2; exit 1;; esac
mkdir -p "$QUALIFICATION_DIR"
QUALIFICATION_DIR=$(cd "$QUALIFICATION_DIR" && pwd)
jsc="$JSC_BUILD_DIR/bin/jsc"
"$JSC_BUILD_DIR/bin/testmasm" > "$QUALIFICATION_DIR/testmasm.log" 2>&1
"$JSC_BUILD_DIR/bin/testFFI" > "$QUALIFICATION_DIR/testffi.log" 2>&1
Tools/Scripts/run-jsc-stress-tests JSTests/stress --jsc "$jsc" --child-processes "${JSC_TEST_JOBS:-4}" \
  --filter 'promise|microtask|dynamic-import|bun-async-context|module-loader|top-level-await|async-module|module-namespace|intl-segmenter|callsite-syntax-positions|stack-position-regressions|error-stack' \
  --output-dir "$QUALIFICATION_DIR/jsc-stress" --no-retry > "$QUALIFICATION_DIR/jsc-stress.log" 2>&1
python3 .github/openclaw/verify-jsc-results.py "$QUALIFICATION_DIR/jsc-stress" --require module-namespace-esmodule-marker.js --require callsite-syntax-positions.js --require stack-position-regressions.js
Tools/Scripts/run-jsc-stress-tests JSTests/modules.yaml --jsc "$jsc" --child-processes "${JSC_TEST_JOBS:-4}" \
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
(out / 'arm64-gate.json').write_text(json.dumps({'passed': True, 'source': sys.argv[2], 'machine': platform.machine(), 'system': platform.system(), 'counts': counts, 'accounting_modes': 5, 'sampling_modes': 5, 'testmasm': True, 'testffi': True}, indent=2) + '\n')
PY
