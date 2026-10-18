# Linux faithfulness control

`qualify.sh` compares the fixed 44-file selection on the pinned historical Bun/WebKit pair and the matched candidate pair in `variants.json`. The gate compares complete file outcomes and requires both arms to pass. The Bun revisions contain different test inventories; per-test inventories are retained for diagnosis rather than treated as identical source.

The historical control applies checksum resolution, the collected-realm and IPv4 fixtures, and `014-baseline-isolated-stdio.patch`. The last patch backports only isolated-stdio ownership from openclaw/bun commit `242876295b1a485be2d3d4c5e27dd7ff4c0a68e1` (Bun #145, adapting oven-sh/bun#38008). It releases the outgoing file's stdio polls, drains pending output before the next isolated file starts, and closes synchronously at VM teardown. It changes neither the control engine nor test assertions, worker counts, deadlines or memory bounds. Its checksum is part of the qualification evidence.

The runner's CI predicate accepts `CI=true`, not `CI=1` alone. The qualifier sets the former explicitly so standalone proof uses the same batching and validation policy as Actions.

`stage-fork-ci.py` creates two untracked copies of the pinned runner and entrypoint. The tracked Bun source remains untouched. The copies preserve execution flags and selection while enabling JUnit, retaining batch process exit/signal fields on each batch file record, and recording the first batch outcome before fallback. Any failed batch terminates qualification without solo retries. Source and instrumented runner hashes are retained for each arm; changed runner anchors fail closed.

Each arm retains `results.json`, `test-outcomes.json`, JUnit reports, and the batch's `batch.json` / `batch.log`. `collect-fork-outcomes.py` requires test cases for every selected file and rejects failed/error cases. The uploaded JSON contains every test name, class, pass/skip/todo outcome and diagnostic detail. No engine-version expected-difference exceptions are installed.
