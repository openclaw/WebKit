# Linux faithfulness control

`qualify.sh` compares the fixed 44-file selection on the previous release’s matched Bun/WebKit pair and the matched candidate pair in `variants.json`. The gate compares complete file outcomes and requires both arms to pass. The Bun revisions contain different test inventories; per-test inventories are retained for diagnosis rather than treated as identical source.

The control is Bun `cabfa8138d20ca57ccfb0a9309103ebb55900125` with published engine `a2976f02e69fde8ccc45dc8fb346173f9d63f8a1`. Its immutable manifest is pinned in `baseline-artifacts.json`. The old checksum, VM-finalization, IPv4 and stdio backports are unnecessary on this source. Both arms retain the same backpressure fixture and complete outcome assertions. The control builds with Node 26.3.0 and the candidate with Node 26.12.1; the workflow supplies their exact executable paths. The previous engine produces cache version 39, preserving the replacement proof against candidate version 44.

The runner's CI predicate accepts `CI=true`, not `CI=1` alone. The qualifier sets the former explicitly so standalone proof uses the same batching and validation policy as Actions.

`stage-fork-ci.py` creates two untracked copies of the pinned runner and entrypoint. The tracked Bun source remains untouched. The copies preserve execution flags and selection while enabling JUnit, retaining batch process exit/signal fields on each batch file record, and recording the first batch outcome before fallback. Any failed batch terminates qualification without solo retries. Source and instrumented runner hashes are retained for each arm; changed runner anchors fail closed.

Each arm retains `results.json`, `test-outcomes.json`, JUnit reports, and the batch's `batch.json` / `batch.log`. `collect-fork-outcomes.py` requires test cases for every selected file and rejects failed/error cases. The uploaded JSON contains every test name, class, pass/skip/todo outcome and diagnostic detail. No engine-version expected-difference exceptions are installed.
