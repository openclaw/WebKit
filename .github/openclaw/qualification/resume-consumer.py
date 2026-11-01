#!/usr/bin/env python3
"""Admit successful builds and rerun the candidate through the frozen gates."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

SYNC = "42e4245f4180941634b482a7e8ef7fca47467de5"
SOURCE = "6e0c032a394820b65278943bd3a4e793718a97ca"
DIAGNOSTIC_SHA = "18857aa910f38803aca4f9578fac86d7e42b83792931d582272b3ffeebcb3144"
PREVIOUS_RUN = 41267060695
PREVIOUS_CARRIER = "e3df8cfa54c394697bcfa45cbe4f9fd33d08f1f3"
RETAINED = {
    "proof": (13068660557, 146302, "ddea8c8cd0522ca98356108ca2a3217e9cf0f7df4d0d9b08991ff54d8a226097"),
    "binaries": (13067819853, 181870231, "4a5b5d1063ef2a6d337e982556a5d1afd953a91625cdafdd5a88cf1846816232"),
}
CANDIDATE_SHA = "afab308b7280bda93a116d4f5208e201b7ee09ccc537d61ea8399ef7ce87090f"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def main():
    pipeline, carrier, retained, root, artifacts = [Path(p).resolve() for p in sys.argv[1:]]
    assert subprocess.check_output(["git", "-C", str(pipeline), "rev-parse", "HEAD"], text=True).strip() == SYNC
    frozen = pipeline / ".github/openclaw/qualification"
    reviewed = carrier / ".github/openclaw/qualification"
    # Validate old receipts with the original policy before installing new adapters.
    sys.path.insert(0, str(frozen))
    import consumer_identity as identity
    diagnostic = reviewed / "diagnose-retained-consumer.py"
    assert sha(diagnostic) == DIAGNOSTIC_SHA
    spec = importlib.util.spec_from_file_location("retained_diagnostic", diagnostic)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    proof, binaries = [module.unpack(retained, name, expected=RETAINED[name],
                                     run=PREVIOUS_RUN, carrier=PREVIOUS_CARRIER)
                       for name in ("proof", "binaries")]
    baseline, candidate = read(proof / "baseline-identity.json"), read(proof / "candidate-identity.json")
    engine = identity.engine_input(artifacts / (identity.LANE + ".tar.gz"),
                                   artifacts / (identity.LANE + ".manifest.json"), SYNC)
    identity.validate_baseline_evidence(baseline, binaries, proof)
    identity.validate_invocation(proof, "baseline")
    assert (proof / "baseline/selected.json").read_bytes() == (frozen / "selected.json").read_bytes()
    assert (proof / "candidate/selected.json").read_bytes() == (frozen / "selected.json").read_bytes()
    assert len(read(frozen / "selected.json")) == 44
    old_carrier = read(proof / "carrier.json")
    assert old_carrier["carrier"] == PREVIOUS_CARRIER and old_carrier["sync"] == SYNC
    engine_gate = read(proof / "engine-gate.json")
    assert engine_gate["passed"] is True and engine_gate["source"] == SYNC
    assert engine_gate["stress_counts"]["jsc-stress"] >= 1400
    assert engine_gate["stress_counts"]["jsc-modules"] >= 1600
    for name, count in engine_gate["stress_counts"].items():
        lines = (proof / name / "results").read_text().splitlines()
        assert len(lines) == count and all(line.endswith(": PASS") for line in lines), name

    shutil.copytree(proof / "baseline", root / "baseline")
    for name in ("baseline-identity.json", "baseline-build-tools.json", "baseline-adapters.patch",
                 "bun-baseline.sha256", "vm-test-baseline.sha256"):
        shutil.copyfile(proof / name, root / name)
    executable = root / identity.BASELINE_EXECUTABLE
    executable.parent.mkdir(parents=True)
    shutil.copyfile(binaries / identity.BASELINE_EXECUTABLE, executable)
    assert sha(executable) == baseline["executable"]["sha256"]
    executable.chmod(0o700)
    # Preserve original engine evidence; the engine and historical baseline are unchanged.
    for path in proof.rglob("*"):
        relative = path.relative_to(proof)
        if not path.is_file():
            continue
        name = relative.parts[0]
        if name.startswith(("jsc-", "sampling-", "accounting-")) or name in ("engine-gate.json", "stack-visitor.log"):
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
    engine_directory = root / "engine"
    engine_directory.mkdir()
    subprocess.run(["tar", "-xzf", str(artifacts / (identity.LANE + ".tar.gz")),
                    "-C", str(engine_directory)], check=True)

    source_manifest = read(reviewed / "consumer-repair.json")
    assert source_manifest["source"] == SOURCE and source_manifest["engine"] == SYNC
    expected_paths = {"harness-adapters.json", "harness_adapters.py",
                      "harness-adapters/candidate-build.patch", "harness-adapters/candidate-test.patch",
                      "test_consumer_identity.py"}
    assert set(source_manifest["files"]) == expected_paths
    new_adapters = read(reviewed / "harness-adapters.json")
    assert new_adapters["arms"]["baseline"] == identity.ADAPTERS["arms"]["baseline"]
    assert new_adapters["origins"] == identity.ADAPTERS["origins"]
    for name, digest in source_manifest["files"].items():
        source = reviewed.parent / name if name == "test_consumer_identity.py" else reviewed / name
        target = frozen.parent / name if name == "test_consumer_identity.py" else frozen / name
        assert sha(source) == digest, name
        shutil.copyfile(source, target)

    # The baseline uses its original policy; this build used the admitted repaired adapter.
    identity = importlib.reload(identity)
    identity.validate_evidence(candidate, SYNC, engine, binaries, proof)
    identity.validate_invocation(proof, "candidate")
    assert candidate["executable"]["sha256"] == CANDIDATE_SHA
    for name in ("candidate-build-tools.json", "candidate-identity.json", "build-candidate.log"):
        shutil.copyfile(proof / name, root / name)
    retained_candidate = root / "retained-candidate-bun"
    shutil.copyfile(binaries / identity.EXECUTABLE, retained_candidate)
    assert sha(retained_candidate) == CANDIDATE_SHA

    # Preserve source preparation and every test gate; reuse only the admitted builds.
    source = subprocess.check_output(["git", "-C", str(pipeline), "show", SYNC + ":.github/openclaw/qualify.sh"])
    assert source == (pipeline / ".github/openclaw/qualify.sh").read_bytes()
    anchor = b"for arm in baseline candidate; do"
    assert source.count(anchor) == 1
    source = source.replace(anchor, b"for arm in candidate; do")
    build = (b'  python3 "$inputs/harness_adapters.py" build --name "$arm" --root "$QUALIFICATION_DIR" \\\n'
             b'    --inspector-runtime "$INSPECTOR_RUNTIME" --source "$SOURCE_SHA" --artifacts "$ARTIFACT_DIR"\n')
    assert source.count(build) == 1
    source = source.replace(build,
        b'  install -D -m 700 "$QUALIFICATION_DIR/retained-candidate-bun" "$repo/build/qualify-$arm/bun"\n')
    create = b'    python3 "$inputs/consumer_identity.py" create --root '
    assert source.count(create) == 1
    source = source.replace(create, b'    python3 "$inputs/consumer_identity.py" verify --root ')
    driver = root / "qualify-candidate-reuse.sh"
    driver.write_bytes(source)
    (root / "reuse.json").write_text(json.dumps({
        "previous_run": PREVIOUS_RUN, "previous_carrier": PREVIOUS_CARRIER,
        "sync": SYNC, "candidate_repair_source": SOURCE,
        "proof_artifact": RETAINED["proof"][0],
        "binary_artifact": RETAINED["binaries"][0],
        "baseline_identity_sha256": sha(root / "baseline-identity.json"),
        "baseline_invocation_sha256": sha(root / "baseline/invocation.json"),
        "engine_gate_sha256": sha(root / "engine-gate.json"),
        "candidate_driver_sha256": sha(driver),
        "candidate_identity_sha256": sha(root / "candidate-identity.json"),
        "candidate_build_tools_sha256": sha(root / "candidate-build-tools.json"),
        "candidate_executable_sha256": CANDIDATE_SHA,
        "candidate_build_reused": True,
        "repair": source_manifest,
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
