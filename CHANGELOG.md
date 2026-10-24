# Changelog

These entries describe the experimental `openclaw/aot-typed-3` fork.

## Unreleased

- Keep removed built-in source text empty when constructing its source provider, so trimmed AOT executables can start.
- Embed ARM64 WebAssembly SIMD bitmask constants in generated code instead of retaining compiler-process addresses.
