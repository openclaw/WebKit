# OpenClaw WebKit artifacts

This fork owns the WebKit artifacts consumed by `openclaw/bun`. The engine base is
`1600131e46b5af48bbda3559af8d8a3327230b6e`; each engine change is a separate
commit. Upstream `.github/scripts/lanes.mjs`, Dockerfiles, ICU inputs and macOS
cross tools remain unchanged. No workflow publishes toolchain images.

## Patch batch

The first batch contains the Segmenter surrogate-boundary fix (Peter Steinberger,
[upstream #753](https://github.com/oven-sh/WebKit/pull/753)), the opt-in global
Proxy prototype support (robobun, [#626](https://github.com/oven-sh/WebKit/pull/626)),
module-loader AsyncLocalStorage context propagation (Peter Steinberger, informed
by robobun's [#274](https://github.com/oven-sh/WebKit/pull/274)), and per-VM worker
heap and stack budgets (Peter Steinberger). Proxy and worker APIs require matching
Bun adapters and a joint rebuild because engine class layouts change.

## Artifact matrix

[variants.json](.github/openclaw/variants.json) records the exact consuming Bun
commit and each active workflow-to-artifact mapping. The release workflow uses
LTO for Linux glibc x64/arm64, macOS x64/arm64, and its optional Linux musl
x64/arm64 and Windows x64 targets. Fork CI adds non-LTO Linux x64 and macOS arm64.
That is nine artifacts. Windows arm64, debug, ASAN, Android and FreeBSD are not
selected by these OpenClaw workflows. x64 has one Nehalem baseline.

## Add a patch and qualify

Start from `openclaw/main`. Add each focused engine patch as its own commit with
upstream links and author credit. Retain the existing opt-in defaults and update
this document's changelog. Check that the recipe is unchanged relative to the
base, then review the whole batch. Changing the upstream recipe requires a
separate qualification and an explicit base/recipe update.

Dispatch **OpenClaw WebKit artifacts** from `openclaw/main` (or the protected
`openclaw/batch-1` publication branch) with its full current
commit SHA and `publish: false`. It builds the selected lanes on Linux x64 with
Docker Buildx, at most two lanes at once. Each lane records the exact source,
commit patches, recipe hashes, locally built toolchain image ID, BuildKit
metadata, tool versions, elapsed time and tarball SHA-256. These records and the
tarball are workflow artifacts. SDKs and toolchain images are not redistributed.

The Linux test job builds both baseline and candidate Bun with separate caches.
Qualification-only Bun adapters live under `.github/openclaw/qualification`;
they do not update or publish the Bun fork. The job runs the original 44-file
fork selector output plus its two dependency checks, requires identical all-pass
results, and checks Segmenter, four Proxy regressions, both 14-variant ALS hook
modes and at least 16 worker resource-limit cases. Other platforms are built;
this gate does not claim native runtime qualification on every architecture.

## Publish and verify

Batch 1 is published from `openclaw/batch-1` so concurrently reviewed batch-2
engine changes can land on `openclaw/main` without entering this release. Both
branches require the same protected environment and full-SHA/green-job checks.

Pull requests run **OpenClaw engine checks** at the exact PR head, with a native
Linux build using the same lane recipe and Bun qualification gate, plus the
macOS arm64 fork artifact cross-built on a separate Linux runner. Both jobs are
read-only; the macOS lane proves compilation, not native macOS execution.
The native job also runs the ArrayBuffer accounting
and confirmed parked-waiter inspection regression with LLInt, DFG, FTL and
concurrent GC. This workflow provides the pre-merge check; it cannot publish.

After a green build/test dispatch, dispatch the same full SHA with `publish:
true`. This repeats the build and qualification, then waits at the protected
`openclaw-artifacts` environment. Only the publication job has repository write
permission. It assembles exactly the nine archives, `manifest.json`,
`SHA256SUMS`, `provenance.tar.gz`, and `LICENSE-SOURCES.txt`.

Repository immutable releases must be enabled. Once the publishing dispatch is
waiting at its environment, a maintainer runs:

```sh
python3 .github/openclaw/release.py authorize --source <full SHA> --run-id <run ID>
```

This uses the maintainer's existing administrator login to verify the exact green
jobs and the admin-only immutability setting, writes a fresh environment receipt
bound to that source/run/attempt, then approves the protected job. No admin token
is stored in Actions. The contents-only workflow token requires that receipt and
still checks the published release's immutable state. Publication first atomically
creates `autobuild-<full SHA>`, creates a draft, uploads every asset, verifies
GitHub's asset digests, and publishes it. It then requires `immutable: true`,
downloads every public asset, and checks the manifest and SHA256SUMS again.
Existing tags, drafts and releases are never resumed or overwritten. A partial
publication needs investigation and a new source commit/tag; there is no
replacement option. Inspect the publication receipt before updating a consumer.

Consumers must pin the full WebKit SHA and each exact filename/URL/SHA-256
mapping together. Verify archive bytes before extracting or reusing a cache.

## Rollback

Keep every prior release. Revert the Bun manifest and WebKit source pin together,
then rebuild Bun against that matched engine. Never replace a published asset or
use an old Bun executable with headers/libraries from another engine ABI.

## Batch 1 (2026-10-04)

- Fix Segmenter queries at surrogate-pair boundaries; thanks @steipete.
- Allow embedders to opt into Proxy global prototypes; thanks @robobun.
- Preserve module-loader async context through resolution and evaluation.
- Add opt-in per-VM worker managed-heap and stack budgets.
- Add checksum-pinned, immutable OpenClaw artifact publication with a Linux regression gate.

## Namespace interop qualification

Pull requests run the read-only Linux engine check. It builds the unchanged native lane, verifies the JSC namespace stress results, and builds Bun with the matching qualification adapters before running the fork selection and namespace regressions. It has no publication job.

The namespace adapter in `.github/openclaw/qualification/patches/008-namespace.patch` accompanies the engine facade API. Keep it in sync with the matching Bun integration until that integration becomes the qualification baseline. The native engine change and Bun consumer must be rebuilt together; a new engine release alone does not remove Bun's old namespace prototype.

## Allocation sampling

The allocation sampler is owned by each VM's `HeapProfiler`. Embedders call
`startAllocationSampling(interval, includeMajorGC, includeMinorGC)`,
`allocationSamplingProfile()`, and `stopAllocationSampling()` with the VM API
lock held. The returned JSON has a `head` allocation-site tree with weighted
`selfSize` estimates and `samples` carrying node IDs, byte estimates, and unique
ordinals. Stack frames identify function definitions and are limited to 128.
The exponential byte-sampling model follows V8's sampling heap profiler.

The sampler observes GC cells, newly reported string backing storage, and auxiliary storage, including generated
free-list allocations, precise allocations, and growth. Other native allocations and external buffer
storage are outside this measurement. Sampling records do not strongly retain
objects or executable code. Collection reconciles addresses before sweeping;
the major/minor flags select whether dead samples remain as cumulative records.
The existing free-list allocation fast paths are unchanged when sampling is disabled.
Bun's inspector adapter requires a joint rebuild against this engine.

The read-only **OpenClaw engine checks** job also exercises the sampler with
default tiers, the interpreter, baseline JIT, and eager FTL, using the same Linux
artifact as namespace qualification. It does not invoke artifact publication.
The separate artifact workflow remains the coordinator's build/test/publish
entrypoint.

## ArrayBuffer ownership and worker snapshots

The accounting adapter in `.github/openclaw/qualification/patches/010-arraybuffer-accounting.patch`
uses the engine's allocation-origin and holder accounts for process, V8 and worker
statistics. The qualification gate exercises its Node-compatible ownership cases
and worker inspections in addition to the existing fork selection. Keep the adapter
in sync with the Bun integration until that integration becomes the qualification
baseline. Engine and Bun headers and libraries must be rebuilt together.

## Unreleased

- Initialize new VM entry scratch buffers and alignment padding, and store deferred microtask entry scopes as two initialized pointers, preventing stale stack values from retaining otherwise unreachable objects; carries #24 onto engine main and adapts the whole-word-state remedy in oven-sh/WebKit#694, thanks @robobun.
- Require the native VM entry storage regressions in the Linux x64 artifact check, qualify dead-realm cleanup with the collected-realm fixture from openclaw/bun#151, and retain both qualified Linux Bun executables and hashes for three days; the fixture adapts oven-sh/bun#44544, thanks @robobun.

- Deliver pending worker heap-limit termination promptly after GC by invalidating optimized code on the mutator, preserving full-GC live accounting and external-buffer exclusions.

- Preserve mimalloc pthread TLS-key ownership during shell exit by draining active setters before deletion; cover both late and in-flight allocations with native regressions. Builds on oven-sh/WebKit#698, thanks @dylan-conway.
- Let workers use young-generation collections within their heap budgets; verify exhaustion with a full collection and preserve progress while idle through the matching Bun timer adapter.
- Bound budgeted workers' post-full growth independently of machine-wide RAM, while retaining the collector minimum, separate nursery pacing and full-only heap-limit verification.

- Fix ARM64 MacroAssembler register-to-memory `add64` operand order, restoring DFG typed-array allocation accounting and preserving the source register; cover the operation in testmasm and native ARM64 qualification.

- Cache source-relative stack line and column lookups on demand, including syntax-selected positions.
- Build both fork engine artifacts at the exact pull-request head before landing, with native Linux qualification and a Linux-hosted macOS arm64 compilation check.
- Keep syntax-selected stack positions separate from exception ranges for calls, constructors, property reads, and async continuations. Preserve the positions across bytecode rewriting, optimization, and cache replay.

- Add real byte-based JSC heap allocation sampling with weighted allocating-stack profiles and independent major/minor collection inclusion.
- Check allocation sampling across interpreter and JIT tiers before merging engine pull requests.
- Preserve ArrayBuffer allocator attribution across worker transfers, report fresh holder external bytes, and exclude backing storage from JS heap statistics and worker limits; builds on oven-sh/WebKit#303, thanks @robobun.
- Inspect worker memory on its owning VM thread during JavaScript execution and atomic waits; the matching Bun reporting adapter must ship with this engine.
- Synchronize the parallel-helper activity assertion with task claims and completion; fixes a race exposed by ThreadSanitizer during accounting qualification.
- Use atomic loads and resets for visited extra/external-memory totals updated by parallel markers.

## Stack positions

`CodeBlock::callSitePositionForBytecodeIndex` returns an optional absolute source offset for an exact instruction or async resume label. Stack readers use this position while exception expression ranges and debugger line tables retain their existing divots. RareData owns the two sparse vectors, including decoded cache entries; the bytecode cache revision prevents older layouts from being reused.

Bun must be rebuilt with its matching stack-reader adapter. It must also preserve built-in error constructor syntax: rewriting `new Error()` as `Error()` changes the position and allows a returning arrow to become a proper tail call. The engine's proper-tail-call behavior is unchanged. The integration continues @robobun’s upstream Bun source-position work in [#35179](https://github.com/oven-sh/bun/pull/35179), [#37396](https://github.com/oven-sh/bun/pull/37396), and [#41580](https://github.com/oven-sh/bun/pull/41580).

The source provider caches only requested line/column conversions under its existing
line-table lock. Coordinates remain relative to the provider's text; document
offsets and builtin provider overrides retain their existing behavior. The cache
fills only when a reader requests a position, and the persistent bytecode-cache
format is unchanged.
