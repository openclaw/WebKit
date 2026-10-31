# Changelog

These entries describe the experimental `openclaw/aot-main` integration fork.

## Unreleased

- Sync multi-image and GC fixes while preserving explicit operand emission order and retained solver and capacity regressions.

- Keep large closure-word boundary coverage with upstream closure numbering.

- Keep incremental dependency regressions compatible with the unconditional flow solver.

- Adapt retained incremental dependency tracking to compact solver lists and sequence new emitter operands.

- Preserve operand emission order in compact-table lookups, array stores, collection iterators, and saved-frame headers.

- Sequence instruction emission explicitly in new hash-table, property, array, and string optimizations.

- Match the missing-runtime-function regression to the current Bun arrayFromLength function ID.

- Sequence private-field location operands explicitly so compiler instruction order is independent of C++ argument evaluation order.

- Sync upstream main, AOT object-access optimizations and allocation polling fixes while retaining fork regressions.

- Sync upstream analysis budgets, built-in frames, and function capacity; use upstream disk-code flags and closure encoding while retaining regression coverage.

- Use upstream compiler-vector allocation growth while retaining the regression beyond 2 GiB.

- Sync upstream linear flow analyses and OOM handling; use upstream address-stable list capacity with the retained regression.

- Sync AOT async tail calls, segmented cell-cage allocation, strict IR checks, and upstream runtime fixes while preserving retained runtime and loader support.

- Preserve deterministic emission order for property enumeration and runtime validation.

- Sync upstream loader retention, exception and JSON fixes; use upstream named runtime-function fixtures while retaining the arm64 conversion regression.

- Sequence code-emitting arguments explicitly to keep AOT instruction order deterministic across C++ evaluation orders.

- Resolve named runtime functions in IR fixtures and keep numeric-return checks portable across arm64 conversion instructions.

- Sync AOT proxy and collection flow, JSON key ordering, exception frames, and startup table mappings with upstream.

- Sync upstream AOT loop optimizations and host-option analysis while retaining loader, counter-map, and value-flow capacity fixes.

- Keep builtin code indices aligned when ShadowRealm is disabled after its AOT declarations are removed.

- Preserve explicit permission to load disk code when AOT flow-results analysis is disabled.

- Sync with the current matching Bun/WebKit pair while preserving regression-tested AnalyzeFlow capacity and edge bounds.
- Raise AOT value-set storage from 16 GiB to 64 GiB per pool while preserving tagged IDs and distinct cache entries for adjacent sets.
- Preserve compiler-vector capacity above 2 GiB through upstream's shared allocation path.
- Allow AOT value-flow use lists to grow beyond 1 GiB while preserving stable addresses and 32-bit index bounds.
- Keep retained dependency regressions compatible with upstream value-flow query and property-read APIs.
- Deduplicate retained AOT value-flow dependencies across incremental runs.
- Preserve mapped counters when jump-only functions would be merged, including source-less generated helpers.
- Allow more closure function IDs while preserving object-shape discrimination, and diagnose the limit before native emission.
- Preserve empty removed built-in source spans during trimmed startup.
- Embed relocatable ARM64 SIMD bitmask constants in compiled WebAssembly.
