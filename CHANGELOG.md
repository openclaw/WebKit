# Changelog

These entries describe the experimental `openclaw/aot-typed` fork.

## Unreleased

- Preserve typed AOT program lengths and section offsets above 4 GiB with format 38.
- Check declared-array accessor reads in audit mode while preserving the enforcing mode's immutable-array fast path.
- Account for far-call veneer alignment once per caller, allowing large AOT images without weakening branch-distance limits.
