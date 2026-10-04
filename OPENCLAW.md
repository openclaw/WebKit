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

Dispatch **OpenClaw WebKit artifacts** from `openclaw/main` with its full current
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
modes and at least 14 worker resource-limit cases. Other platforms are built;
this gate does not claim native runtime qualification on every architecture.

## Publish and verify

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
