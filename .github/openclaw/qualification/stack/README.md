# Stack cache qualification

The fixture and JSC mode/cache driver come from the landed stack-position work.
The runtime cache probe uses the exact matched Bun commit and its integrated
stack adapter. `variants.json` pins version 39 and the SHA-256 of
`src/jsc/RuntimeTranspilerCache.rs`, including its serializer and Wyhash seed.

The pinned Rust `Metadata::encode` writes a u32 version, two u8 tags, then twelve
little-endian u64 values. Output offset/length/hash begin at bytes 30/38/46.
`RuntimeTranspilerCache::hash` uses Wyhash with seed 42, also available through
`Bun.hash.wyhash`. The proof checks the version and bounds before using this
layout and fails if the source format changes.

Baseline cold/warm runs seed the prior format. The candidate must replace it
with version 39. Before its final warm run, the probe changes an equal-width
stderr marker only in the cached output and recomputes that output's checksum.
The original source, source map and all coordinate assertions stay unchanged.
The warm run must print the cache-only marker, preserve the marked entry, and
pass every coordinate assertion. Recompilation from the original source prints
the original marker and fails the gate. This proves cache execution rather than
inferring a cache hit from files merely existing.
