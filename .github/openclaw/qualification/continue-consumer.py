#!/usr/bin/env python3
"""Finish only the two native probes for one admitted, already-tested Bun build."""
import hashlib
import importlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import zipfile

SYNC = "42e4245f4180941634b482a7e8ef7fca47467de5"
SOURCE = "2323913322dfdfed96ecf20163d62f5ff2796ecc"
RUN = 41279605249
CARRIER = "bf6e21076fbaf4b442347f64b64b61917bd07c47"
ARTIFACTS = {
    "proof": (13074375041, 409674, "8d09e24016faab6f2b8fa05b027a24321885f71e22c4ccf2855d3a047cfdbfe8"),
    "binaries": (13073981057, 183496527, "73b2ed22fbd7b24b366f24edf6f834c5d5582a51ed13c0d25cc8f202e79f996b"),
}
PROOF_INVENTORY = "798eb71db1b9db8547831ae20405a2394c482ce645a4da1225a75af022c2807e"
VERIFIER = "e9aeb350b0de5e5b5962af9934985805985a2291b3e90ff0302fd6c427a1db23"
PROBE_BOUNDARY = "assert len((out/'engine-limits.log').read_text().splitlines())==9\n"
MIMALLOC = "bun/build/qualify-candidate/obj/vendor/mimalloc/src/static.c.o"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def write_once(path, value):
    with path.open("x") as stream:
        stream.write(json.dumps(value, indent=2) + "\n")


def policy(pipeline):
    assert subprocess.check_output(["git", "-C", str(pipeline), "rev-parse", "HEAD"], text=True).strip() == SYNC
    inputs = pipeline / ".github/openclaw/qualification"
    sys.path.insert(0, str(inputs))
    return inputs, importlib.import_module("consumer_identity")


def unpack(retained, name):
    artifact, size, digest = ARTIFACTS[name]
    metadata = read(retained / (name + ".metadata.json"))
    archive = retained / (name + ".zip")
    assert metadata["id"] == artifact and not metadata["expired"]
    assert metadata["workflow_run"]["id"] == RUN and metadata["workflow_run"]["head_sha"] == CARRIER
    assert metadata["size_in_bytes"] == archive.stat().st_size == size
    assert metadata["digest"] == "sha256:" + digest and sha(archive) == digest
    destination = retained / name
    destination.mkdir()
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        assert len({entry.filename for entry in entries}) == len(entries)
        assert 0 < len(entries) <= (154 if name == "proof" else 128)
        assert sum(entry.file_size for entry in entries) <= (3719104 if name == "proof" else 512 * 1024**2)
        if name == "proof":
            inventory = [{"path": e.filename, "bytes": e.file_size, "mode": e.external_attr >> 16,
                          "directory": e.is_dir()} for e in entries]
            encoded = json.dumps(inventory, separators=(",", ":"), sort_keys=True).encode()
            assert len(entries) == 154 and hashlib.sha256(encoded).hexdigest() == PROOF_INVENTORY
        for entry in entries:
            path = PurePosixPath(entry.filename)
            assert not path.is_absolute() and "\\" not in entry.filename and "\x00" not in entry.filename
            assert all(part not in ("", ".", "..") for part in entry.filename.rstrip("/").split("/"))
            mode = stat.S_IFMT(entry.external_attr >> 16)
            assert mode in (0, stat.S_IFDIR if entry.is_dir() else stat.S_IFREG)
            target = destination / path
            if entry.is_dir():
                assert entry.file_size == 0
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(entry) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o600)
    return destination


def runtime_evidence(inputs, root):
    # Reuse the authoritative runtime assertions, stopping before either unfinished probe.
    # The complete unchanged verifier runs only after both real probes finish.
    verifier = inputs / "verify-sync.py"
    assert sha(verifier) == VERIFIER
    source = verifier.read_text()
    assert source.count(PROBE_BOUNDARY) == 1
    previous = sys.argv
    try:
        sys.argv = [str(verifier), str(root)]
        exec(compile(source.split(PROBE_BOUNDARY)[0], str(verifier), "exec"),
             {"__file__": str(verifier), "__name__": "__retained_runtime_admission__"})
    finally:
        sys.argv = previous


def engine_evidence(proof):
    gate = read(proof / "engine-gate.json")
    assert gate["passed"] is True and gate["source"] == SYNC
    assert gate["stress_counts"]["jsc-stress"] >= 1400 and gate["stress_counts"]["jsc-modules"] >= 1600
    for name, count in gate["stress_counts"].items():
        lines = (proof / name / "results").read_text().splitlines()
        assert len(lines) == count and all(line.endswith(": PASS") for line in lines), name


def receipts(inputs, identity, proof, binaries, engine):
    baseline, candidate = [read(proof / (arm + "-identity.json")) for arm in ("baseline", "candidate")]
    identity.validate_baseline_evidence(baseline, binaries, proof)
    identity.validate_evidence(candidate, SYNC, engine, binaries, proof)
    for arm in ("baseline", "candidate", "sync"):
        identity.validate_invocation(proof, arm)
    from compare_fork_ci import validate_arm
    selected = read(proof / "candidate/selected.json")
    assert len(selected) == 44 and validate_arm(proof / "candidate", selected)["all_passed"]
    assert (proof / "baseline/selected.json").read_bytes() == (inputs / "selected.json").read_bytes()
    candidate_sha = sha(proof / "candidate-identity.json")
    gate = read(proof / "gate.json")
    assert gate["passed"] is True and gate["source"] == SYNC and "upstream_sync" not in gate
    assert gate["candidate_identity_sha256"] == candidate_sha
    assert gate["baseline_identity_sha256"] == sha(proof / "baseline-identity.json")
    assert gate["selected_files"] == 44 and gate["result_files"] == 46
    compatibility = read(proof / "compatibility-gate.json")
    assert compatibility["passed"] is True and compatibility["source"] == SYNC
    assert compatibility["candidate_identity_sha256"] == candidate_sha
    assert compatibility["memory_tests"] == 3 and compatibility["startup"] is True
    engine_evidence(proof)
    assert not (proof / "sync-gate.json").exists()
    failure = (proof / "sync/engine-limit-build.log").read_text()
    assert "undefined reference to `Bun__outOfMemory'" in failure
    assert not (proof / "sync/engine-limits.log").exists()
    assert not (proof / "sync/engine-gc-progress.json").exists()
    return candidate, gate


def prepare(pipeline, carrier, retained, root, artifacts, checkout, inspector):
    inputs, identity = policy(pipeline)
    assert subprocess.check_output(["git", "-C", str(carrier), "rev-parse", "HEAD"], text=True).strip() == read(root / "carrier.json")["carrier"]
    assert not (root / "continuation.json").exists() and not (root / "bun").exists()
    proof, binaries = [unpack(retained, name) for name in ("proof", "binaries")]
    engine = identity.engine_input(artifacts / (identity.LANE + ".tar.gz"),
                                   artifacts / (identity.LANE + ".manifest.json"), SYNC)
    old_carrier = read(proof / "carrier.json")
    assert old_carrier["carrier"] == CARRIER and old_carrier["sync"] == SYNC
    previous = read(proof / "reuse.json")
    assert previous["candidate_repair_source"] == SOURCE and previous["sync"] == SYNC
    manifest = read(inputs / "consumer-repair.json")
    assert manifest["source"] == SOURCE and manifest["engine"] == SYNC
    for name, digest in previous["repair"]["files"].items():
        if name != "qualify-sync.sh":
            assert manifest["files"][name] == digest, "reused build/test policy changed: " + name
    candidate, gate = receipts(inputs, identity, proof, binaries, engine)
    # Retained SQLite reports contain absolute source paths. Preserve their original cwd.
    assert Path(read(proof / "candidate-build-tools.json")["cwd"]) == root / "bun"
    assert identity.git(checkout, "rev-parse", "HEAD", "HEAD^{tree}").decode().splitlines() == [
        identity.CONFIG["candidate"]["commit"], identity.CONFIG["candidate"]["tree"]]
    assert not identity.git(checkout, "status", "--porcelain")
    shutil.move(str(checkout), root / "bun")
    reused = {}
    for source in proof.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(proof).as_posix()
        target_name = {"carrier.json": "retained-carrier.json", "reuse.json": "retained-reuse.json",
                       "engine-artifact.json": "retained-engine-artifact.json",
                       "engine-zip-entries.json": "retained-engine-zip-entries.json",
                       "sync/engine-limit-build.log": "sync/engine-limit-build.previous.log"}.get(relative, relative)
        target = root / target_name
        target.parent.mkdir(parents=True, exist_ok=True)
        assert not target.exists()
        shutil.copyfile(source, target)
        reused[target_name] = sha(source)
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
    engine_directory = root / "engine"
    engine_directory.mkdir()
    subprocess.run(["tar", "-xzf", str(artifacts / (identity.LANE + ".tar.gz")), "-C", str(engine_directory)], check=True)
    identity.verify(root, engine, root / "candidate-identity.json", inspector)
    runtime_evidence(inputs, root)
    controls = {}
    for name, digest in manifest["files"].items():
        path = inputs.parent / name if name in ("test_consumer_identity.py", "variants.json", "qualify-sync.sh") else inputs / name
        assert sha(path) == digest
        controls[name] = digest
    write_once(root / "continuation.json", {
        "run": RUN, "carrier": CARRIER, "source": SOURCE, "sync": SYNC,
        "artifacts": ARTIFACTS, "proof_inventory_sha256": PROOF_INVENTORY,
        "candidate_identity_sha256": sha(root / "candidate-identity.json"),
        "mimalloc_sha256": sha(root / MIMALLOC), "ordinary_gate": gate,
        "reused_files": reused, "controls": controls,
        "manifest_sha256": sha(inputs / "consumer-repair.json"),
        "continuation_carrier": read(root / "carrier.json"),
        "candidate_build_reused": True, "candidate_runtime_evidence_reused": True,
    })


def admitted(pipeline, root, artifacts, inspector, *, completed=False):
    inputs, identity = policy(pipeline)
    record = read(root / "continuation.json")
    assert record["run"] == RUN and record["carrier"] == CARRIER and record["source"] == SOURCE and record["sync"] == SYNC
    assert record["artifacts"] == {key: list(value) for key, value in ARTIFACTS.items()}
    assert record["proof_inventory_sha256"] == PROOF_INVENTORY
    assert record["candidate_build_reused"] is True and record["candidate_runtime_evidence_reused"] is True
    assert sha(inputs / "consumer-repair.json") == record["manifest_sha256"]
    assert record["controls"] == read(inputs / "consumer-repair.json")["files"]
    for name, digest in record["controls"].items():
        path = inputs.parent / name if name in ("test_consumer_identity.py", "variants.json", "qualify-sync.sh") else inputs / name
        assert sha(path) == digest
    for name, digest in record["reused_files"].items():
        if not (completed and name == "gate.json"):
            assert sha(root / name) == digest, "reused evidence changed: " + name
    assert sha(root / MIMALLOC) == record["mimalloc_sha256"]
    assert sha(root / "candidate-identity.json") == record["candidate_identity_sha256"]
    assert read(root / "carrier.json") == record["continuation_carrier"]
    engine = identity.engine_input(artifacts / (identity.LANE + ".tar.gz"),
                                   artifacts / (identity.LANE + ".manifest.json"), SYNC)
    identity.verify(root, engine, root / "candidate-identity.json", inspector)
    runtime_evidence(inputs, root)
    if completed:
        gate = read(root / "gate.json")
        assert {k: v for k, v in gate.items() if k not in ("upstream_sync", "engine", "compatibility")} == record["ordinary_gate"]
        sync_gate = read(root / "sync-gate.json")
        assert sync_gate["passed"] is True and sync_gate["source"] == SYNC
        assert sync_gate["candidate_identity_sha256"] == record["candidate_identity_sha256"]
        assert gate["upstream_sync"] == sync_gate
        write_once(root / "continuation-complete.json", {
            "passed": True, "continuation_sha256": sha(root / "continuation.json"),
            "candidate_identity_sha256": record["candidate_identity_sha256"],
            "sync_gate_sha256": sha(root / "sync-gate.json"), "gate_sha256": sha(root / "gate.json"),
        })


if __name__ == "__main__":
    mode, *args = sys.argv[1:]
    paths = [Path(value).resolve() for value in args]
    if mode == "prepare":
        prepare(*paths)
    elif mode in ("admit", "seal"):
        admitted(*paths, completed=mode == "seal")
    else:
        raise SystemExit("unknown fixed-run continuation command")
