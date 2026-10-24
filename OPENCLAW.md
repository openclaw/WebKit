# OpenClaw WebKit artifacts

The release branch `openclaw/release-5e3554fa` starts at the qualified replay
`3ab47948f3e3e26ec323d0de6a1c66e388363f0e`, on upstream
`5e3554face1338d738543540a82f23e3163045f5`. All sixteen fork patches and the
three qualified sampler/ArrayBuffer fixes are retained. The lane generator,
Dockerfiles, ICU inputs and macOS cross tools match this upstream base.

## Qualification

`.github/openclaw/variants.json` pins the full matched Bun commit and tree,
the upstream Bun revision, and the historical faithfulness control. The three
candidate arms build that exact matched source with separate source, build and
artifact caches. Each uses the production checksum resolver and verifies the
Bun and engine identities in the resulting executable.

The faithfulness control is the last published release pair: Bun
`cabfa8138d20ca57ccfb0a9309103ebb55900125` and WebKit
`a2976f02e69fde8ccc45dc8fb346173f9d63f8a1`. Its published manifest supplies
matching headers, libraries and checksums. Its cache version 39 supplies the old
format for the version 44 replacement proof. Legacy control backports are not
applied to this newer control source. Control and candidate builds use Node
26.3.0 and 26.12.1 respectively, as supplied by the workflow.

The Linux job runs engine stress and modules, the 44-file/46-record faithfulness
comparison, manifest-only compatibility with startup and three memory-release
tests, and feature qualification with the historical 56-path selection plus the
current selector. Cache proof retains all 56 semantic coordinates and proves
actual execution of marked warm-cache output. A changed cache serializer must be
reviewed before updating its pinned hash or reader. Candidate output is never a
new oracle.

Explicit CI mode and first-attempt JSON, logs and JUnit records are required.
Failed batches stop before fallback retries; both faithfulness arms must pass.
Module-loader comparisons use the shared executable owner, independent of JIT
tier, with case-insensitive pointer parsing. Assertions, selections, worker counts,
timeouts and heap bounds must not be relaxed to qualify a release.

## Publication

Only the owned OpenClaw workflows are installed. A push does not dispatch them.
The ten consumer lanes, native Windows ARM64 gate, source/archive-bound receipts,
checksums, provenance and immutable-release contract remain mandatory.

The coordinator dispatches `.github/workflows/openclaw-artifacts.yml` from the
release branch with its full current commit SHA. Workflow checkout, `GITHUB_SHA`
and the `sha` input must agree. Use `publish: false` for an optional dry run;
it does not replace the publication run's own green gates.

A publishing run waits at the protected `openclaw-artifacts` environment after
all prerequisites succeed. The exact branch must already be admitted by the
environment policy. Code does not change that policy or remove its reviewer.
After Peter approves the exact run/source/attempt, the coordinator runs:

```sh
python3 .github/openclaw/release.py authorize --source <full SHA> --run-id <run ID>
```

This verifies the immutable-release setting, complete successful job set and
pending environment, writes a short-lived source/run/attempt-bound receipt and
approves the deployment. The contents-only publishing job requires that receipt.
It atomically creates `autobuild-<full SHA>`, uploads the ten archives plus
`manifest.json`, `SHA256SUMS`, `provenance.tar.gz` and `LICENSE-SOURCES.txt`, then
verifies immutable state and public downloads. Existing tags, drafts or releases
are never resumed or overwritten. No toolchain images are published.

Consumers must pin the full engine SHA and all archive URL/SHA-256 mappings
together, verify bytes and rebuild against the matching headers and libraries.
Rollback restores the previous Bun/engine pair and rebuilds; prior assets remain
available. Release notes are in `.github/openclaw/release-notes.md`.

## Unreleased

- Prepare the qualified 5e3554fa engine with matched Bun 7f836a97, previous-release faithfulness control, explicit branch gates, and updated cache and build-tool pins.
- Retain first-attempt sync evidence and the standalone embedding's fatal allocator hook without changing assertions or memory bounds.
