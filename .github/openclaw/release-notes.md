This release rebases the qualified OpenClaw engine patches onto upstream `5718a6ec579b98362ea7276a426deedcc6281ef5`.

- Release free allocator memory from idle compiler threads and long Atomics waits; thanks @Jarred-Sumner.
- Preserve Segmenter surrogate boundaries, opt-in Proxy global prototypes, module-loader AsyncLocalStorage context, and per-VM worker heap/stack budgets; thanks @steipete and @robobun.
- Give require(esm) a separate live namespace with its own `__esModule` marker while preserving unmarked import namespaces; thanks @robobun.
- Add VM-owned byte-based allocation sampling, allocating-stack profiles, and independent major/minor GC inclusion.
- Preserve syntax-selected stack positions for calls, constructors, property reads and async continuations, including live/captured stacks and cache replay; thanks @robobun for the upstream source-position work.

Qualification includes all nine artifact builds, Linux JSC module/promise/namespace/Segmenter and allocation-sampling regressions, the W113 paired Bun selection, a manifest-only build of the exact prepared upstream-synced Bun runtime with startup and unchanged upstream memory-release tests, and a separate build with feature adapters for the complete fork selection and patch regressions. Syntax-selected stack positions are checked across execution tiers, live/captured stacks, and cache replay. Other targets have build/provenance proof; native runtime qualification is Linux x64.

The new engine requires Bun's updated mimalloc idle hook and matching embedding adapters. Consumers must rebuild with the manifest's exact headers and libraries; an older executable is not interchangeable.

Source and licenses: LICENSE-SOURCES.txt. Checksums: SHA256SUMS and manifest.json. Build and qualification evidence: provenance.tar.gz.

Rollback by restoring the prior Bun manifest and WebKit pin together, then rebuilding. Prior releases remain available.
