# Changelog

These entries describe the experimental `openclaw/aot-typed-3` fork.

## Unreleased

- Include generated helper entry counters in AOT maps with an explicit absent-source marker.

- Allow AOT images to use more of the existing closure function-index field while preserving object-shape discrimination.
- Report excessive native function IDs before code generation instead of trapping while emitting closure guards.
- Keep removed built-in source text empty when constructing its source provider, so trimmed AOT executables can start.
- Embed ARM64 WebAssembly SIMD bitmask constants in generated code instead of retaining compiler-process addresses.
