# Changelog

These entries describe the experimental `openclaw/aot-typed` fork.

## Unreleased

- Resolve compiled Flow checks through registered in-place member specializations while preserving object identity.
- Keep outlined calls after ARM64 frame setup so generic AOT entry points retain their caller's return address.
- Preserve Proxy-backed declared arrays through generic AOT accesses with element checks, while retaining native storage specialization for proven array allocations.
- Report final canonical function sizes for folded aliases in AOT maps after outlining and fall-through optimization.
- Check final AOT branch distances instead of rejecting large images for the sum of caller-local far-call veneers.
- Publish initial and final native-entry coverage snapshots without rewriting the full table during GC.
- Reduce native-entry snapshot serialization overhead while preserving complete per-VM coverage records.
- Materialize ARM64 SIMD bitmask tables in generated code so embedded Wasm works after AOT image relocation.
- Resolve structure property names through the identifier overflow table when enumerating large AOT programs.

- Preserve typed AOT program lengths and section offsets above 4 GiB with format 38.
- Check declared-array accessor reads in audit mode while preserving the enforcing mode's immutable-array fast path.
- Account for far-call veneer alignment once per caller, allowing large AOT images without weakening branch-distance limits.
- Preserve closure function IDs in the upper half of their 22-bit field while reserving the final 16 IDs.
