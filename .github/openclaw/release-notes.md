# Unreleased pipeline preparation
- Update the source and recipe base to oven-sh/WebKit `b1e30d08cb1428688c5f24109fe4f534096ee2ad` and admit the exact `openclaw/release-b1e30d08` branch in code. Preserve all ten artifacts, qualification gates and immutable-release verification. Publication still requires the environment's separate exact-name policy and a fully qualified engine replay.

## Previous release

This release fixes two native stack storage paths that could conservatively retain otherwise unreachable objects, including cancellation reasons. Newly created VM entry records now initialize their callee-save scratch buffers and alignment padding. Deferred microtask entry scopes use two initialized pointers instead of an optional engagement byte with stale padding. Lazy entry, global-object updates, unwind state and teardown boundaries remain intact, without a new heap allocation. Native poisoned-storage regressions cover both owners. Thanks @robobun for the related whole-word-state remedy in [oven-sh/WebKit#694](https://github.com/oven-sh/WebKit/pull/694).

This batch also fixes a Linux deadlock when a Worker waits in a native call on a foreign stack, as used by Koffi. Asynchronous VM trap sampling now makes one suspension attempt and releases the process-wide suspension lock before retrying a refused sample. This lets another VM finish collection and release the native call while termination remains pending. Blocking GC suspension still requires a valid stack/register snapshot; Mach suspension retains its existing operation. The native regression checks parent collection before native release, rooted-object survival, pending termination, temporary refusal and nested suspension. General same-VM foreign-stack scanning is outside this fix.

The original Koffi probe timed out in 66 of 200 processes with the released Bun and passed all 200 with the patched engine; each process performs ten Worker terminations. The controlled native regression deadlocks on the original engine and passes with the fix. ASAN passes with its standard incomplete swapcontext-support warning. TSAN remains nonzero: all eight reported signatures were also reproduced by an unpatched two-VM GC control, without suppressions. This is baseline attribution, not a clean TSAN or race-freedom claim.

Qualification now uses the collected-realm FinalizationRegistry fixture merged in [Bun #151](https://github.com/openclaw/bun/pull/151), adapted from [oven-sh/bun#44544](https://github.com/oven-sh/bun/pull/44544); thanks @robobun. It requires at least one realm to be observed collected and zero callbacks for every collected realm. PR and artifact workflows retain the four qualified Linux Bun executables and their hashes for three days, including available executables after a failure. These diagnostics are separate from the immutable release assets.

Both fixes use the existing Bun embedding adapters; the suspension fix needs no new runtime adapter. Consumers still need a joint rebuild with the matching engine headers and libraries.

Previously released fixes remain included. The engine wakes a passive garbage collector when its mutator starts waiting, allowing collection to progress when shared GC helpers are occupied elsewhere. A native regression checks the late-wait transition, completion before helper release, and survival of rooted objects.

Budgeted workers use young-generation collections and bound post-full-collection growth independently of machine-wide RAM. Full collections still verify heap-limit exhaustion. Idle collection requires the matching immediate GC timer wakeup in [Bun #129](https://github.com/openclaw/bun/pull/129); include that companion when consuming this engine.

The previously released worker termination and allocator fixes remain included. The engine delivers pending worker heap-limit termination promptly after GC. It invalidates optimized code at the mutator's collection epilogue so existing JavaScript safe points deliver the pending trap without repeated full collections. Full-GC managed live accounting, heap budgets and ArrayBuffer exclusions are unchanged. Native regressions cover termination after one over-cap full collection and near-limit survival; Bun qualification retains the worker OOM event contract and external-buffer controls.

It also fixes the JSC shell's mimalloc process-exit TLS race by closing admission and draining in-flight setters before deleting the pthread key. Deterministic native regressions cover late initialization and an already-admitted setter. Standard Bun builds disable this allocator teardown and are unaffected by that race. Thanks @dylan-conway for the diagnosis in oven-sh/WebKit#698.

Other previously released engine changes remain included:

- Correct ARM64 register-to-memory 64-bit addition, restoring DFG typed-array allocation accounting and preserving the source register. Native macOS and Linux ARM64 qualification covers assembler tests and JSC interpreter, baseline, DFG, FTL and concurrent-GC modes.
- Include the non-LTO Windows ARM64 archive alongside the other nine artifacts on upstream `5718a6ec579b98362ea7276a426deedcc6281ef5`, with native Windows 11 ARM64 startup, DFG JIT, FFI and accounting gates bound to the archive and source. The unchanged upstream cross-compilation recipe requires both JSC and testFFI to be native ARM64 PE files.

- Cache requested provider-relative stack line and column conversions under the existing line-table lock, preserving document offsets, builtin overrides, and persistent bytecode format; thanks @steipete. Regressions cover repeated reads, independent providers, UTF-16 columns, and compressed line-table boundaries across interpreter/JIT tiers and cache modes.

- Release free allocator memory from idle compiler threads and long Atomics waits; thanks @Jarred-Sumner.
- Preserve Segmenter surrogate boundaries, opt-in Proxy global prototypes, module-loader AsyncLocalStorage context, and per-VM worker heap/stack budgets; thanks @steipete and @robobun.
- Give require(esm) a separate live namespace with its own `__esModule` marker while preserving unmarked import namespaces; thanks @robobun.
- Add VM-owned byte-based allocation sampling, allocating-stack profiles, and independent major/minor GC inclusion.
- Preserve ArrayBuffer allocation ownership across transfers, separate backing storage from JavaScript heap statistics, and inspect worker memory on its owning VM during execution and atomic waits; thanks @robobun for the upstream accounting investigation.
- Synchronize the accounting-related parallel-helper assertion and visited-memory counters.
- Preserve syntax-selected stack positions for calls, constructors, property reads and async continuations, including live/captured stacks and cache replay; thanks @robobun for the upstream source-position work.

Qualification includes all ten artifact builds, Linux JSC module/promise/namespace/Segmenter and allocation-sampling regressions, the paired Bun selection, a build of the exact prepared upstream-synced Bun runtime with its required namespace API adapter and candidate manifest with startup and unchanged upstream memory-release tests, and a separate build with feature adapters for the complete fork selection and patch regressions. Syntax-selected stack positions are checked across execution tiers, live/captured stacks, and cache replay. Separate native Linux ARM64 checks cover assembler and JSC regressions. Native Windows ARM64 qualification covers JSC startup, DFG JIT, FFI and five ArrayBuffer accounting modes. macOS and the remaining targets have compilation and provenance proof for this batch. Bun consumer qualification is separate.

The existing embedding requirements remain: Bun's mimalloc idle hook and matching adapters. A manifest-only update of the original sync tree does not compile: its old namespace marker access must be replaced by the namespace adapter (Bun #106), paired atomically with this engine. Consumers must rebuild with the manifest's exact headers and libraries; an older executable is not interchangeable.

Source and licenses: LICENSE-SOURCES.txt. Checksums: SHA256SUMS and manifest.json. Build and qualification evidence: provenance.tar.gz.

Rollback by restoring the prior Bun manifest and WebKit pin together, then rebuilding. Prior releases remain available.
