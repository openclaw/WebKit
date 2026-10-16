# OpenClaw WebKit artifacts

This fork owns the WebKit artifacts consumed by `openclaw/bun`. The engine base is
`b1e30d08cb1428688c5f24109fe4f534096ee2ad`. The lane generator, Dockerfiles,
ICU inputs and macOS cross tools must match that base exactly. No workflow
publishes toolchain images. The ten consumer lanes and qualification gates remain
the release contract; upstream fuzzing lanes are not selected for publication.

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
Windows ARM64 adds the upstream non-LTO release lane, for ten artifacts. LLVM's
CodeView register-tuple limitation prevents ARM64 LTO (oven-sh/bun#31345).
Debug, ASAN, Android and FreeBSD are not selected by these OpenClaw workflows. x64 has one Nehalem baseline.

## Add a patch and qualify

Start from `openclaw/main`. Add each focused engine patch as its own commit with
upstream links and author credit. Retain the existing opt-in defaults and update
this document's changelog. Check that the recipe is unchanged relative to the
base, then review the whole batch. Changing the upstream recipe requires a
separate qualification and an explicit base/recipe update.

Dispatch **OpenClaw WebKit artifacts** from `openclaw/main` (or the protected
`openclaw/batch-1`, `openclaw/release-5718a6ec`, or `openclaw/release-b1e30d08` publication branch) with its full current
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
this gate does not claim native runtime qualification on every architecture. A
Windows 11 ARM64 job verifies archive provenance and native ARM64 PE identity,
then runs JSC startup, DFG JIT, testFFI and ArrayBuffer accounting in five execution modes. Assembly and publication require
its source- and archive-bound receipt.

## Publish and verify

Batch 1 is published from `openclaw/batch-1` so concurrently reviewed batch-2
engine changes can land on `openclaw/main` without entering this release. All publication
branches require the same protected environment and full-SHA/green-job checks.

Pull requests run **OpenClaw engine checks** at the exact PR head, with a native
Linux build using the same lane recipe and Bun qualification gate, plus the
macOS arm64 fork artifact cross-built on a separate Linux runner. Both jobs are
read-only; the macOS lane proves compilation, not native macOS execution.
The native job also runs the ArrayBuffer accounting
and confirmed parked-waiter inspection regression with LLInt, DFG, FTL and
concurrent GC. This workflow provides the pre-merge check; it cannot publish.

For final publication, dispatch the reviewed full SHA with `publish: true`.
For the `b1e30d08` line, dispatch from `openclaw/release-b1e30d08` itself. The
workflow and its scripts are loaded from that branch, and the input SHA must
equal its current full commit SHA. A push does not start this publication workflow.
This builds every lane and runs all qualification gates before waiting at the protected
`openclaw-artifacts` environment. Only the publication job has repository write
permission. It assembles exactly the ten archives, `manifest.json`,
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
A separate `publish: false` dispatch is an optional dry run; it never substitutes
for the final publication run’s own green gates. Existing tags, drafts and releases are never resumed or overwritten. A partial
publication needs investigation and a new source commit/tag; there is no
replacement option. Inspect the publication receipt before updating a consumer.

Consumers must pin the full WebKit SHA and each exact filename/URL/SHA-256
mapping together. Verify archive bytes before extracting or reusing a cache.

## Rollback

Keep every prior release. Revert the Bun manifest and WebKit source pin together,
then rebuild Bun against that matched engine. Never replace a published asset or
use an old Bun executable with headers/libraries from another engine ABI.

## VM entry storage

The paired qualifier keeps its frozen Bun source and applies the test-only fix
from `4c8accdd045b84c942fe447348a31a7cba04cde4` to both arms. The feature-sync
qualifier uses the same fixture; the compatibility-only source contract is
unchanged. Each VM test file hash is retained with the existing proof logs.
Both PR checks and artifact builds upload the baseline, candidate, feature-sync,
and compatibility Bun executables in `linux-bun-executables`. A failed run retains
the executables built before the failure, without retrying the qualifier.

The Linux x64 `testVMEntryRecord` native target poisons the next entry record and
checks all fixed-arity and generic entry stubs, locator purity, nested-entry
preservation, and ordinary JavaScript exception handling. Its synthetic callee
captures storage before any legitimate spill; it never executes bytecode or
collects while its deliberately incomplete JavaScript frame is active.

The `testVMEntryScope` native target checks poisoned deferred-scope storage and
entry, reset, nested-scope, and microtask lifecycle behavior. Deferred scopes keep
the existing lazy entry and teardown boundaries without allocating heap storage.

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

- Rebase the sixteen retained engine patches onto `b1e30d08`; skip incomplete first-call compilation frames during allocation sampling, and make sampler and ArrayBuffer regression checks track explicit collection and actual liveness.

- Prepare the artifact pipeline for oven-sh/WebKit `b1e30d08cb1428688c5f24109fe4f534096ee2ad` and the exact `openclaw/release-b1e30d08` publication branch, preserving all ten consumer lanes, qualification gates and immutable publication checks.

The new release line also requires adding its exact branch name to the existing
`openclaw-artifacts` environment deployment policy. The old policy contains literal
names, not a release-branch wildcard. Code changes do not modify that repository
setting. The old release branch's exact protection rule does not cover the new
line either; retain its protection settings when creating the new branch's rule.
Do not dispatch publication until the engine replay and qualification are complete.
The historical paired Bun baseline and sync trees below remain frozen qualification
inputs; this pipeline migration does not replace them or waive their gates.

## Stack retention and Linux suspension (2026-10-09)

- Initialize new VM entry scratch buffers and alignment padding before entering JavaScript or native callees, preventing stale stack values from retaining otherwise unreachable objects during collection.
- Store deferred microtask entry scopes as two initialized pointers, avoiding stale optional-flag padding that can conservatively retain lexical environments and cancellation reasons. Adapts the whole-word-state remedy in oven-sh/WebKit#694; thanks @robobun.
- Verify dead-realm cleanup with the collected-realm fixture from openclaw/bun#151, adapted from oven-sh/bun#44544; thanks @robobun. Retain the qualified Linux Bun executables and hashes for three days, including failed qualification runs.
- Retry asynchronous VM trap delivery after a foreign-stack suspension refusal without holding the process-wide suspension lock, allowing other VMs to collect while native calls await them. Blocking GC suspension and Mach suspension retain their existing contracts.

## Passive collector progress and worker cadence (2026-10-07)

- Wake passive collectors when a mutator begins waiting, even while shared helpers serve another heap; the native regression requires completion before helper release and preserves rooted objects.
- Let workers use young-generation collections within their heap budgets; verify exhaustion with a full collection and preserve progress while idle through the matching Bun timer adapter.
- Bound budgeted workers' post-full growth independently of machine-wide RAM, while retaining the collector minimum, separate nursery pacing and full-only heap-limit verification.

## Worker termination and allocator exit (2026-10-06)

- Deliver pending worker heap-limit termination promptly after GC by invalidating optimized code on the mutator, preserving full-GC live accounting and external-buffer exclusions.

- Prevent late JSC helper-thread allocation from overwriting a recycled pthread TLS key during process exit; close admission and drain in-flight TLS setters before deleting the key, with deterministic native regressions. Builds on the diagnosis in oven-sh/WebKit#698, thanks @dylan-conway. Standard Bun builds disable this allocator teardown.

## ARM64 arithmetic and Windows artifacts (2026-10-05)

- Fix ARM64 register-to-memory 64-bit addition so DFG typed-array allocations update their accounting counter without corrupting the source register; cover the operation in testmasm and qualify native ARM64 JSC across interpreter and JIT tiers.

- Add the upstream non-LTO Windows ARM64 archive and require native Windows 11 ARM64 startup, JIT and FFI qualification before publication.

## Repeated stack coordinates (2026-10-05)

- Cache source-relative stack line and column lookups on demand, including syntax-selected positions; carries engine PR #8 onto the rebased release line, thanks @steipete.
- Build both fork engine artifacts at the exact pull-request head before landing, with native Linux qualification and a Linux-hosted macOS arm64 compilation check.
- Require the repeated-coordinate regression and surrounding error-stack stress cases, with seven direct stack execution modes including interpreter, baseline-only, DFG-only, eager FTL and concurrent GC, while retaining every rebased release gate.

## Rebased engine batch

- Keep syntax-selected stack positions separate from exception ranges for calls, constructors, property reads, and async continuations. Preserve the positions across bytecode rewriting, optimization, and cache replay.

- Add real byte-based JSC heap allocation sampling with weighted allocating-stack profiles and independent major/minor collection inclusion.
- Check allocation sampling across interpreter and JIT tiers before merging engine pull requests.
- Preserve ArrayBuffer allocator attribution across worker transfers, report fresh holder external bytes, and exclude backing storage from JS heap statistics and worker limits; builds on oven-sh/WebKit#303, thanks @robobun.
- Inspect worker memory on its owning VM thread during JavaScript execution and atomic waits; the matching Bun reporting adapter must ship with this engine.
- Synchronize the parallel-helper activity assertion with task claims and completion; fixes a race exposed by ThreadSanitizer during accounting qualification.
- Use atomic loads and resets for visited extra/external-memory totals updated by parallel markers.

## Rebased release qualification

- Rebase the four batch-1 engine patches and the landed namespace, allocation-sampling, stack-position and ArrayBuffer-accounting patches onto oven-sh/WebKit `5718a6ec579b98362ea7276a426deedcc6281ef5` (upstream #768). Thanks @Jarred-Sumner for idle compiler-thread and Atomics.wait memory release.
- Retain the published batch-1 release. Publish this separately qualified batch only through the protected `openclaw/release-5718a6ec` environment policy; updating the Bun main manifest is a separate integration task.

The existing qualification baseline remains upstream `1600131e46b5af48bbda3559af8d8a3327230b6e` with its committed archive checksums. The source/provenance base advances to `5718a6ec579b98362ea7276a426deedcc6281ef5`; the Docker and lane recipes are unchanged. Unlanded engine work is not included in this rebase.


The rebased release is frozen on `openclaw/release-5718a6ec`; only patches merged
into engine main and explicitly included before the freeze enter this batch.
Later main changes require a new source commit and qualification. The published
release notes come from `.github/openclaw/release-notes.md`.

The original W113 comparison retains its pinned Bun source and 44 selected files
plus two dependency checks. Its candidate additionally takes the upstream
mimalloc bump needed by `mi_on_thread_idle`. This is a matched engine/allocator
comparison, not an engine-only performance measurement.

A separate qualification build reproduces W150's prepared upstream-sync tree
`d9ec052fccc81afbf43a5344e52bc980f439d587` exactly from Bun
`d2d2a26ef973cdd97b37953f5dba58052acad74f` before applying recorded qualification
adapters and replacing the local checksum manifest. The production manifest
resolver stays intact, using its SHA-256 prefetch cache. No Bun branch is pushed.
This build runs the union of the original 56-file sync selection and the current
engine/nightly selection, requires every result to pass, and explicitly executes
the unchanged Atomics purge, notification-race and idle Wasm RSS tests without
skips. Runtime source/engine identities, adapter bytes and results are retained
in provenance. Release assembly requires this gate in addition to W113.

The shared test job also checks the namespace and Segmenter stress cases,
promise/microtask stress and complete module manifest, allocation sampling in
four execution tiers, seven worker heap counters, fourteen worker cases, the
ALS hook/continuous-GC matrices, realm/retention probes, and Bun inspector tests.
The upstream delta changes only waiting/compiler-thread allocator release and
its bridge; module-loader, namespace, managed-heap and inspector patches remain
patch-identical on the new base.
## Stack positions

`CodeBlock::callSitePositionForBytecodeIndex` returns an optional absolute source offset for an exact instruction or async resume label. Stack readers use this position while exception expression ranges and debugger line tables retain their existing divots. RareData owns the two sparse vectors, including decoded cache entries; the bytecode cache revision prevents older layouts from being reused.

Bun must be rebuilt with its matching stack-reader adapter. It must also preserve built-in error constructor syntax: rewriting `new Error()` as `Error()` changes the position and allows a returning arrow to become a proper tail call. The engine's proper-tail-call behavior is unchanged. The integration continues @robobun’s upstream Bun source-position work in [#35179](https://github.com/oven-sh/bun/pull/35179), [#37396](https://github.com/oven-sh/bun/pull/37396), and [#41580](https://github.com/oven-sh/bun/pull/41580).

The release gate includes the landed stack-position adapter, the complete CallSite/util/source-map and minifier regressions, live stack visitor, async positions, and owned/persistent JSC cache replay.


The compatibility arm first reproduces that exact W150 tree, then applies only
its required namespace API counterpart from `patches/008-namespace.patch`.
The adapter SHA-256 and resulting tree `aee7cd52d7efcb9835b434a24fa47de06cc664f6`
are pinned in `variants.json`. A manifest-only attempt against the original
prepared tree failed to compile because it accessed the removed public
`TriState` namespace marker. **Bun #106 (or this exact adapter) must accompany
the manifest update.** No legacy marker shim is restored in the engine.

After that explicit pairing, the index must retain the pinned paired tree
before and after compilation, and the manifest must be the sole tracked
worktree change. Startup and all three unchanged memory-release tests must pass.
The separate feature build applies the remaining adapters for the full regression
selection. Both gates are mandatory for assembly and publication; the failed
manifest-only result is retained as dependency evidence.

The ArrayBuffer patch is qualified in five interpreter/JIT/concurrent-GC modes,
with process ownership, worker snapshot, native external-buffer and serializer
regressions. A combined regression inspects a worker during the new idle-memory
purge and notification windows. VM inspection runs before the idle-purge branch,
with the waiter-list lock dropped and VM heap access restored only for inspection;
both paths recheck notification/termination before waiting again.

The source provider caches only requested line/column conversions under its existing
line-table lock. Coordinates remain relative to the provider's text; document
offsets and builtin provider overrides retain their existing behavior. The cache
fills only when a reader requests a position, and the persistent bytecode-cache
format is unchanged.
