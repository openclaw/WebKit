# Changelog

These entries describe the experimental `openclaw/aot-main` integration fork.

## Unreleased

- Raise AOT value-set storage from 16 GiB to 64 GiB per pool while preserving tagged IDs and distinct cache entries for adjacent sets.
- Allow AOT value-flow use lists to grow beyond 1 GiB while preserving stable addresses and 32-bit index bounds.
- Keep retained dependency regressions compatible with upstream value-flow query and property-read APIs.
- Deduplicate retained AOT value-flow dependencies across incremental runs.
- Preserve mapped counters when jump-only functions would be merged, including source-less generated helpers.
- Allow more closure function IDs while preserving object-shape discrimination, and diagnose the limit before native emission.
- Preserve empty removed built-in source spans during trimmed startup.
- Embed relocatable ARM64 SIMD bitmask constants in compiled WebAssembly.
