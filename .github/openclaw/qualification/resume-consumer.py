#!/usr/bin/env python3
"""Admit prior proof and prepare a candidate-only run of the frozen gates."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

SYNC = "42e4245f4180941634b482a7e8ef7fca47467de5"
SOURCE = "6e0c032a394820b65278943bd3a4e793718a97ca"
DIAGNOSTIC_SHA = "f8b39dc04c29c8482c8a0537b1ab44c6c6f98c240538e65f119c407f489ed994"


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
    proof, binaries = module.unpack(retained, "proof"), module.unpack(retained, "binaries")
    baseline, candidate = read(proof / "baseline-identity.json"), read(proof / "candidate-identity.json")
    engine = identity.engine_input(artifacts / (identity.LANE + ".tar.gz"),
                                   artifacts / (identity.LANE + ".manifest.json"), SYNC)
    identity.validate_baseline_evidence(baseline, binaries, proof)
    identity.validate_invocation(proof, "baseline")
    identity.validate_evidence(candidate, SYNC, engine, binaries, proof)
    assert (proof / "baseline/selected.json").read_bytes() == (frozen / "selected.json").read_bytes()
    assert (proof / "candidate/selected.json").read_bytes() == (frozen / "selected.json").read_bytes()
    assert len(read(frozen / "selected.json")) == 44
    old_carrier = read(proof / "carrier.json")
    assert old_carrier["carrier"] == module.CARRIER and old_carrier["sync"] == SYNC
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

    # Preserve every gate; omit only the admitted historical build/test arm.
    source = subprocess.check_output(["git", "-C", str(pipeline), "show", SYNC + ":.github/openclaw/qualify.sh"])
    assert source == (pipeline / ".github/openclaw/qualify.sh").read_bytes()
    anchor = b"for arm in baseline candidate; do"
    assert source.count(anchor) == 1
    source = source.replace(anchor, b"for arm in candidate; do")
    driver = root / "qualify-candidate-reuse.sh"
    driver.write_bytes(source)
    (root / "reuse.json").write_text(json.dumps({
        "previous_run": module.RUN, "previous_carrier": module.CARRIER,
        "sync": SYNC, "candidate_repair_source": SOURCE,
        "proof_artifact": module.ARTIFACTS["proof"][0],
        "binary_artifact": module.ARTIFACTS["binaries"][0],
        "baseline_identity_sha256": sha(root / "baseline-identity.json"),
        "baseline_invocation_sha256": sha(root / "baseline/invocation.json"),
        "engine_gate_sha256": sha(root / "engine-gate.json"),
        "candidate_driver_sha256": sha(driver),
        "repair": source_manifest,
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
