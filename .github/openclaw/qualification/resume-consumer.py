#!/usr/bin/env python3
"""Retain unchanged baseline/engine evidence and rebuild the integrated consumer."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

SYNC = "42e4245f4180941634b482a7e8ef7fca47467de5"
SOURCE = "2323913322dfdfed96ecf20163d62f5ff2796ecc"
DIAGNOSTIC_SHA = "18857aa910f38803aca4f9578fac86d7e42b83792931d582272b3ffeebcb3144"
PREVIOUS_RUN = 41269886896
PREVIOUS_CARRIER = "e3dc9d3be7d3a6cff1996ab68da3057e14e006ad"
RETAINED = {
    "proof": (13068952583, 149694, "b6097d6a0b6ceb8267228c5a90e6355742d22c1b75303040366d022d9ab46cb8"),
    "binaries": (13068828135, 181870231, "ecd304f17a76299f15d1dcd65843af4ca6b5fe075c26f10ea82394f9c52e314f"),
}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def install_controls(pipeline, carrier, identity):
    frozen = pipeline / ".github/openclaw/qualification"
    reviewed = carrier / ".github/openclaw/qualification"
    source_manifest = read(reviewed / "consumer-repair.json")
    assert source_manifest["source"] == SOURCE and source_manifest["engine"] == SYNC
    expected_paths = {"harness-adapters.json", "harness_adapters.py",
                      "harness-adapters/candidate-build.patch", "harness-adapters/candidate-test.patch",
                      "test_consumer_identity.py", "variants.json", "qualify-sync.sh", "verify-sync.py",
                      "continue-consumer.py", "probe-allocator.cpp"}
    assert set(source_manifest["files"]) == expected_paths
    new_adapters = read(reviewed / "harness-adapters.json")
    assert new_adapters["arms"]["baseline"] == identity.ADAPTERS["arms"]["baseline"]
    assert new_adapters["origins"] == identity.ADAPTERS["origins"]
    variants = read(reviewed.parent / "variants.json")
    original_variants = identity.CONFIG
    assert {k: v for k, v in variants.items() if k != "candidate"} == {
        k: v for k, v in original_variants.items() if k != "candidate"}
    assert variants["candidate"] == {
        "commit": "d9be087429c21e563bb5ac29f8a11805e64b56a3",
        "tree": "980068aa5aa9f51f40fc4125114a68fccd9bc9dc",
        "manifest_blob": "e9544c96d5cd9a5e5f6b0245ed5c8dd78fb1a218"}
    assert new_adapters["arms"]["candidate"]["pin"] == variants["candidate"]["commit"]
    parent_files = {"test_consumer_identity.py", "variants.json", "qualify-sync.sh"}
    for name, digest in source_manifest["files"].items():
        source = reviewed.parent / name if name in parent_files else reviewed / name
        target = frozen.parent / name if name in parent_files else frozen / name
        assert sha(source) == digest, name
        shutil.copyfile(source, target)
    shutil.copyfile(reviewed / "consumer-repair.json", frozen / "consumer-repair.json")

    return source_manifest


def main():
    args = sys.argv[1:]
    fresh_engine = bool(args and args[0] == "--fresh-engine")
    if fresh_engine:
        args = args[1:]
    pipeline, carrier, retained, root, artifacts = [Path(p).resolve() for p in args]
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
    baseline = read(proof / "baseline-identity.json")
    engine = identity.engine_input(artifacts / (identity.LANE + ".tar.gz"),
                                   artifacts / (identity.LANE + ".manifest.json"), SYNC)
    identity.validate_baseline_evidence(baseline, binaries, proof)
    identity.validate_invocation(proof, "baseline")
    assert (proof / "baseline/selected.json").read_bytes() == (frozen / "selected.json").read_bytes()
    assert len(read(frozen / "selected.json")) == 44
    old_carrier = read(proof / "carrier.json")
    assert old_carrier["carrier"] == PREVIOUS_CARRIER and old_carrier["sync"] == SYNC
    engine_proof = root if fresh_engine else proof
    engine_gate = read(engine_proof / "engine-gate.json")
    assert engine_gate["passed"] is True and engine_gate["source"] == SYNC
    assert engine_gate["stress_counts"]["jsc-stress"] >= 1400
    assert engine_gate["stress_counts"]["jsc-modules"] >= 1600
    for name, count in engine_gate["stress_counts"].items():
        lines = (engine_proof / name / "results").read_text().splitlines()
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
    if not fresh_engine:
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

    source_manifest = install_controls(pipeline, carrier, identity)

    # Candidate receipts and executables are deliberately not copied across source changes.
    # Keep the normal build, identity creation, selection and every later gate.
    source = subprocess.check_output(["git", "-C", str(pipeline), "show", SYNC + ":.github/openclaw/qualify.sh"])
    assert source == (pipeline / ".github/openclaw/qualify.sh").read_bytes()
    anchor = b"for arm in baseline candidate; do"
    assert source.count(anchor) == 1
    source = source.replace(anchor, b"for arm in candidate; do")
    proxy_command = b'"$candidate" test test/js/node/vm/vm.test.ts'
    assert source.count(proxy_command) == 1
    source = source.replace(proxy_command, b'"$candidate" test --expose-internals test/js/node/vm/vm.test.ts')
    driver = root / "qualify-candidate-fresh.sh"
    driver.write_bytes(source)
    (root / "reuse.json").write_text(json.dumps({
        "previous_run": PREVIOUS_RUN, "previous_carrier": PREVIOUS_CARRIER,
        "sync": SYNC, "candidate_repair_source": SOURCE,
        "proof_artifact": RETAINED["proof"][0],
        "binary_artifact": RETAINED["binaries"][0],
        "baseline_identity_sha256": sha(root / "baseline-identity.json"),
        "baseline_invocation_sha256": sha(root / "baseline/invocation.json"),
        "engine_gate_sha256": sha(root / "engine-gate.json"),
        "engine_evidence_reused": not fresh_engine,
        "candidate_driver_sha256": sha(driver),
        "candidate_build_reused": False,
        "candidate_selection_reused": False,
        "repair": source_manifest,
    }, indent=2) + "\n")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "install":
        pipeline, carrier = [Path(p).resolve() for p in sys.argv[2:]]
        assert subprocess.check_output(["git", "-C", str(pipeline), "rev-parse", "HEAD"], text=True).strip() == SYNC
        sys.path.insert(0, str(pipeline / ".github/openclaw/qualification"))
        import consumer_identity as identity
        install_controls(pipeline, carrier, identity)
    else:
        main()
