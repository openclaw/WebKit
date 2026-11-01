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


MATRIX_RUN = 41286392252
MATRIX_CARRIER = "bfea5fad536fe27d6beb39bdf64106536418428f"
MATRIX_ARTIFACTS = {
    "proof": (13077667443, 144089, "1b86433996f4e980474eab578aa73c5146064505433080ee7451bc33164e30ba"),
    "binaries": (13077208926, 183496528, "01af375c560db6655ec4915f85e206ceb764e8205cf944562f3c6be6c1ec7251"),
}
MIMALLOC = "bun/build/qualify-candidate/obj/vendor/mimalloc/src/static.c.o"


def replay_matrix(pipeline, carrier, retained, root, artifacts, checkout, inspector):
    assert subprocess.check_output(["git", "-C", str(pipeline), "rev-parse", "HEAD"], text=True).strip() == SYNC
    assert not (root / "matrix-replay.json").exists() and not (root / "bun").exists()
    inputs = pipeline / ".github/openclaw/qualification"
    sys.path.insert(0, str(inputs))
    import consumer_identity as identity
    diagnostic = carrier / ".github/openclaw/qualification/diagnose-retained-consumer.py"
    assert sha(diagnostic) == DIAGNOSTIC_SHA
    spec = importlib.util.spec_from_file_location("retained_diagnostic", diagnostic)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    proof, binaries = [module.unpack(retained, name, expected=MATRIX_ARTIFACTS[name],
                                     run=MATRIX_RUN, carrier=MATRIX_CARRIER)
                       for name in ("proof", "binaries")]
    engine = identity.engine_input(artifacts / (identity.LANE + ".tar.gz"),
                                   artifacts / (identity.LANE + ".manifest.json"), SYNC)
    baseline, candidate = [read(proof / (arm + "-identity.json")) for arm in ("baseline", "candidate")]
    identity.validate_baseline_evidence(baseline, binaries, proof)
    identity.validate_evidence(candidate, SYNC, engine, binaries, proof)
    identity.validate_invocation(proof, "baseline")
    assert candidate["executable"]["sha256"] == "c6cca50dcf3f5eb7e53550a97a234a93918eb63b74af692d1c7236474da55079"
    previous = read(proof / "reuse.json")
    assert previous["candidate_repair_source"] == SOURCE and previous["engine_evidence_reused"] is False
    engine_gate = read(proof / "engine-gate.json")
    assert engine_gate["passed"] is True and engine_gate["source"] == SYNC
    assert engine_gate["stress_counts"]["jsc-stress"] >= 1400 and engine_gate["stress_counts"]["jsc-modules"] >= 1600
    for name, count in engine_gate["stress_counts"].items():
        lines = (proof / name / "results").read_text().splitlines()
        assert len(lines) == count and all(line.endswith(": PASS") for line in lines), name
    assert not (proof / "gate.json").exists() and not (proof / "sync-gate.json").exists()
    pin = identity.CONFIG["candidate"]
    assert identity.git(checkout, "rev-parse", "HEAD", "HEAD^{tree}").decode().splitlines() == [pin["commit"], pin["tree"]]
    assert not identity.git(checkout, "status", "--porcelain")
    assert Path(read(proof / "candidate-build-tools.json")["cwd"]) == root / "bun"
    bootstrap = read(proof / "candidate-build-tools.json")["bootstrap"]
    assert inspector.stat().st_size == bootstrap["size"] and sha(inspector) == bootstrap["sha256"]
    shutil.move(str(checkout), root / "bun")
    reused = {}
    for source in proof.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(proof)
        name = relative.as_posix()
        if relative.parts[0] == "candidate":
            name = "previous-candidate/" + "/".join(relative.parts[1:])
        elif name in ("faithfulness.json", "reuse.json"):
            name = "previous-" + name
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        assert not target.exists()
        shutil.copyfile(source, target)
        reused[name] = sha(source)
    for name in (identity.BASELINE_EXECUTABLE, identity.EXECUTABLE, identity.FIXTURE, MIMALLOC):
        target = root / name
        assert not target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(binaries / name, target)
        target.chmod(0o700 if name in (identity.BASELINE_EXECUTABLE, identity.EXECUTABLE) else 0o600)
    repo = root / "bun"
    overlay = root / "candidate-manifest.patch"
    subprocess.run(["git", "-C", str(repo), "apply", "--check", str(overlay)], check=True)
    subprocess.run(["git", "-C", str(repo), "apply", str(overlay)], check=True)
    (root / "engine").mkdir()
    subprocess.run(["tar", "-xzf", str(artifacts / (identity.LANE + ".tar.gz")), "-C", str(root / "engine")], check=True)
    identity.verify(root, engine, root / "candidate-identity.json", inspector)
    source = subprocess.check_output(["git", "-C", str(pipeline), "show", SYNC + ":.github/openclaw/qualify.sh"])
    assert source == (pipeline / ".github/openclaw/qualify.sh").read_bytes()
    begin = b'  results="$QUALIFICATION_DIR/$arm"\n'
    end = b'done\npython3 "$inputs/compare_fork_ci.py"'
    assert source.count(begin) == source.count(end) == 1
    driver = source[:source.index(b"for arm in baseline candidate; do")]
    driver += b'arm=candidate\nrepo="$QUALIFICATION_DIR/bun"\ncandidate="$repo/build/qualify-candidate/bun"\ncd "$repo"\n'
    driver += b'"$bootstrap" install --frozen-lockfile\n(cd test && "$bootstrap" install --frozen-lockfile)\n'
    driver += source[source.index(begin):source.index(end)] + source[source.index(end) + len(b"done\n"):]
    proxy = b'"$candidate" test test/js/node/vm/vm.test.ts'
    assert driver.count(proxy) == 1
    driver = driver.replace(proxy, b'"$candidate" test --expose-internals test/js/node/vm/vm.test.ts')
    (root / "qualify-retained-matrix.sh").write_bytes(driver)
    manifest = read(inputs / "consumer-repair.json")
    for name, digest in manifest["files"].items():
        target = inputs.parent / name if name in ("test_consumer_identity.py", "variants.json", "qualify-sync.sh") else inputs / name
        assert sha(target) == digest, name
    with (root / "matrix-replay.json").open("x") as stream:
        stream.write(json.dumps({"run": MATRIX_RUN, "carrier": MATRIX_CARRIER, "source": SOURCE,
            "sync": SYNC, "artifacts": MATRIX_ARTIFACTS, "reused_files": reused,
            "candidate_identity_sha256": sha(root / "candidate-identity.json"),
            "candidate_build_reused": True, "candidate_runtime_evidence_reused": False,
            "controls": manifest["files"], "manifest_sha256": sha(inputs / "consumer-repair.json"),
            "driver_sha256": sha(root / "qualify-retained-matrix.sh"),
            "replay_control_sha256": sha(Path(__file__))}, indent=2) + "\n")


def seal_matrix(pipeline, root, artifacts, inspector):
    inputs = pipeline / ".github/openclaw/qualification"
    sys.path.insert(0, str(inputs))
    import consumer_identity as identity
    record = read(root / "matrix-replay.json")
    assert record["run"] == MATRIX_RUN and record["carrier"] == MATRIX_CARRIER and record["source"] == SOURCE and record["sync"] == SYNC
    assert sha(Path(__file__)) == record["replay_control_sha256"]
    assert sha(inputs / "consumer-repair.json") == record["manifest_sha256"]
    assert sha(root / "qualify-retained-matrix.sh") == record["driver_sha256"]
    manifest = read(inputs / "consumer-repair.json")
    assert record["controls"] == manifest["files"]
    for name, digest in record["controls"].items():
        target = inputs.parent / name if name in ("test_consumer_identity.py", "variants.json", "qualify-sync.sh") else inputs / name
        assert sha(target) == digest, name
    for name, digest in record["reused_files"].items():
        assert sha(root / name) == digest, name
    assert sha(root / "candidate-identity.json") == record["candidate_identity_sha256"]
    engine = identity.engine_input(artifacts / (identity.LANE + ".tar.gz"),
                                   artifacts / (identity.LANE + ".manifest.json"), SYNC)
    identity.verify(root, engine, root / "candidate-identity.json", inspector)
    gate = read(root / "gate.json")
    assert gate["passed"] is True and gate["upstream_sync"] == read(root / "sync-gate.json")
    assert gate["compatibility"] == read(root / "compatibility-gate.json")
    with (root / "matrix-replay-complete.json").open("x") as stream:
        stream.write(json.dumps({"passed": True, "replay_sha256": sha(root / "matrix-replay.json"),
            "gate_sha256": sha(root / "gate.json"), "candidate_identity_sha256": record["candidate_identity_sha256"]}, indent=2) + "\n")


if __name__ == "__main__":
    if sys.argv[1] == "replay-matrix":
        replay_matrix(*[Path(p).resolve() for p in sys.argv[2:]])
    elif sys.argv[1] == "seal-matrix":
        seal_matrix(*[Path(p).resolve() for p in sys.argv[2:]])
    elif len(sys.argv) == 4 and sys.argv[1] == "install":
        pipeline, carrier = [Path(p).resolve() for p in sys.argv[2:]]
        assert subprocess.check_output(["git", "-C", str(pipeline), "rev-parse", "HEAD"], text=True).strip() == SYNC
        sys.path.insert(0, str(pipeline / ".github/openclaw/qualification"))
        import consumer_identity as identity
        install_controls(pipeline, carrier, identity)
    else:
        main()
