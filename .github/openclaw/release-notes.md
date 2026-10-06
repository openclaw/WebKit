This release delivers pending worker heap-limit termination promptly after GC. It invalidates optimized code at the mutator's collection epilogue so existing JavaScript safe points deliver the pending trap without repeated full collections. Full-GC managed live accounting, heap budgets and ArrayBuffer exclusions are unchanged. Native regressions cover termination after one over-cap full collection and near-limit survival; Bun qualification retains the worker OOM event contract and external-buffer controls.

It also fixes the JSC shell's mimalloc process-exit TLS race by closing admission and draining in-flight setters before deleting the pthread key. Deterministic native regressions cover late initialization and an already-admitted setter. Standard Bun builds disable this allocator teardown and are unaffected by that race. Thanks @dylan-conway for the diagnosis in oven-sh/WebKit#698.

The previously released engine changes remain included:

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

Qualification includes all ten artifact builds, Linux JSC module/promise/namespace/Segmenter and allocation-sampling regressions, the paired Bun selection, a build of the exact prepared upstream-synced Bun runtime with its required namespace API adapter and candidate manifest with startup and unchanged upstream memory-release tests, and a separate build with feature adapters for the complete fork selection and patch regressions. Syntax-selected stack positions are checked across execution tiers, live/captured stacks, and cache replay. Other targets have build/provenance proof; native runtime qualification additionally covers macOS and Linux ARM64 assembler/JSC regressions, and Windows ARM64 JSC startup, DFG JIT, FFI and five ArrayBuffer accounting modes. Bun consumer qualification is separate.

The new engine requires Bun's updated mimalloc idle hook and matching embedding adapters. A manifest-only update of the original sync tree does not compile: its old namespace marker access must be replaced by the namespace adapter (Bun #106), paired atomically with this engine. Consumers must rebuild with the manifest's exact headers and libraries; an older executable is not interchangeable.

Source and licenses: LICENSE-SOURCES.txt. Checksums: SHA256SUMS and manifest.json. Build and qualification evidence: provenance.tar.gz.

Rollback by restoring the prior Bun manifest and WebKit pin together, then rebuilding. Prior releases remain available.
