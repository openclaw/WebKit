# Changelog

These entries describe the experimental `openclaw/aot-typed-3` fork.

## Unreleased

- Avoid retaining duplicate AOT value-flow dependencies across incremental runs, reducing use-graph memory growth.
- Allow AOT images to use more of the existing closure function-index field while preserving object-shape discrimination.
- Report excessive native function IDs before code generation instead of trapping while emitting closure guards.
- Keep removed built-in source text empty when constructing its source provider, so trimmed AOT executables can start.
- Embed ARM64 WebAssembly SIMD bitmask constants in generated code instead of retaining compiler-process addresses.
