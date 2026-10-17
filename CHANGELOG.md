# Changelog

These entries describe the experimental `openclaw/aot-typed` fork.

## Unreleased

- Materialize ARM64 SIMD bitmask tables in generated code so embedded Wasm works after AOT image relocation.
- Resolve structure property names through the identifier overflow table when enumerating large AOT programs.

- Preserve typed AOT program lengths and section offsets above 4 GiB with format 38.
- Check declared-array accessor reads in audit mode while preserving the enforcing mode's immutable-array fast path.
- Account for far-call veneer alignment once per caller, allowing large AOT images without weakening branch-distance limits.
- Preserve closure function IDs in the upper half of their 22-bit field while reserving the final 16 IDs.
