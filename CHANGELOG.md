# Changelog

These entries describe the experimental `openclaw/aot-main` integration fork.

## Unreleased

- Deduplicate retained AOT value-flow dependencies across incremental runs.
- Preserve mapped counters when jump-only functions would be merged, including source-less generated helpers.
- Allow more closure function IDs while preserving object-shape discrimination, and diagnose the limit before native emission.
- Preserve empty removed built-in source spans during trimmed startup.
- Embed relocatable ARM64 SIMD bitmask constants in compiled WebAssembly.
