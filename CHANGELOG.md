# Changelog

These entries describe the experimental `openclaw/aot-typed-2` fork.

## Unreleased

- Preserve typed program lengths and section offsets above 4 GiB with format 39.
- Keep native-entry coverage per VM with image-bound initial and final snapshots, and preserve wide counter relocations during outlining.
- Check final branch reach and folded alias sizes after AOT image layout, and keep outlined calls after ARM64 frame setup.
- Preserve declared Proxy arrays through typed boundaries while retaining checked native-array specialization for proven allocations.
- Preserve full-width closure IDs, overflow property identifiers, and relocated ARM64 SIMD constants.
- Check audited array reads, retain fresh-record guarded calls, and report the actual access when a captured field violates a fact.
- Preserve compiled Flow views, generic Object.entries iterators, and capacity for later fields when cloning through typed aliases.
