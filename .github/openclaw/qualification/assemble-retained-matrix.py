"""Admit fixed-run build artifacts and fresh Linux proof for offline assembly."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import zipfile

REPO = "repos/openclaw/WebKit/"
SOURCE = "42e4245f4180941634b482a7e8ef7fca47467de5"
BUILD_RUN = 41286392252
BUILD_HEAD = "bfea5fad536fe27d6beb39bdf64106536418428f"
REPLAY_RUN = 41294955235
REPLAY_HEAD = "fe913cc9c90efd8fdc9c9f5be06ef3450d63cab4"
ORIGINAL = {'bun-webkit-linux-amd64': [13075718771,
                            709340274,
                            'sha256:e762b6e8022b4d0f454b1ddc8288f0b3b2ad511b159fe2b8cff7fd4a4eb197d4'],
 'bun-webkit-linux-amd64-lto': [13076530203,
                                390685186,
                                'sha256:6133bb0507c93acf3d1d2231012c3ccb0bb8f077c27293f316e79a2e2f5c43ce'],
 'bun-webkit-linux-amd64-musl-lto': [13076429158,
                                     283858242,
                                     'sha256:14457d9621316dccdc6b6eceef32e7f03410a7e7db62e26e30355f90273ac601'],
 'bun-webkit-linux-arm64-lto': [13076480901,
                                269297056,
                                'sha256:d9419c90be30b7588a11e9607edca4a16b23e39f4363013e0edda11dcb409dce'],
 'bun-webkit-linux-arm64-musl-lto': [13077105948,
                                     193259412,
                                     'sha256:cdcdb82ed96e2b4b80e9059acd6e408cbd47b549a7671497f6282de37428daf4'],
 'bun-webkit-macos-amd64-lto': [13076422209,
                                184072987,
                                'sha256:17c48099e23731b46b3814d09fee6d102d79508f31b3a4bd6d5841cb84dd2da3'],
 'bun-webkit-macos-arm64': [13075372671,
                            229404673,
                            'sha256:71689535668a18cf61cc4ef8f0dae281b48108b4923ce0b2af4e5ca7a5a8e15a'],
 'bun-webkit-macos-arm64-lto': [13076322480,
                                179644957,
                                'sha256:e2f0a8e675814af177875eab7e6475e49b3eb0777ffe26b65d468944e7ebb543'],
 'bun-webkit-windows-amd64-lto': [13076798389,
                                  572218334,
                                  'sha256:aaf339963631c8b83877fa90fa11809c7e7af59066c20bd7b8e0325d72a77324'],
 'bun-webkit-windows-arm64': [13077561521,
                              259571300,
                              'sha256:09735badc7ff3faf690c16dee640ce1842c8bc62e10fc6be4819124e86c3c8de'],
 'windows-arm64-qualification': [13077641419,
                                 1029,
                                 'sha256:c263cbb260585a610e0c1670cab7530b0efe3e694c3598fde845a50e5795a1a2']}


def api(route):
    return json.loads(subprocess.check_output(["gh", "api", REPO + route]))


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def run_identity(run_id, head, workflow):
    run = api(f"actions/runs/{run_id}")
    assert run["head_sha"] == head and run["run_attempt"] == 1 and run["status"] == "completed"
    assert run["head_repository"]["full_name"] == "openclaw/WebKit"
    assert run["path"].split("@", 1)[0] == ".github/workflows/" + workflow
    jobs = api(f"actions/runs/{run_id}/jobs?filter=latest&per_page=100")["jobs"]
    return run, {job["name"]: job for job in jobs}


def download(root, label, row, run_id, head):
    artifact_id, size, digest = row
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest) and 0 < size <= 1024**3
    metadata = api(f"actions/artifacts/{artifact_id}")
    assert metadata["id"] == artifact_id and metadata["name"] == label and not metadata["expired"]
    assert metadata["size_in_bytes"] == size and metadata["digest"] == digest
    assert metadata["workflow_run"]["id"] == run_id and metadata["workflow_run"]["head_sha"] == head
    archive_path = root / "download.zip"
    with archive_path.open("xb") as stream:
        subprocess.run(["gh", "api", REPO + f"actions/artifacts/{artifact_id}/zip"], stdout=stream, check=True)
    assert archive_path.stat().st_size == size and "sha256:" + sha(archive_path) == digest
    target = root / label
    target.mkdir()
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        assert 0 < len(entries) <= 4096 and sum(entry.file_size for entry in entries) <= 8 * 1024**3
        seen = set()
        for entry in entries:
            name = PurePosixPath(entry.filename)
            assert not name.is_absolute() and not any(part in ("", ".", "..") for part in entry.filename.rstrip("/").split("/"))
            assert "\\" not in entry.filename and "\x00" not in entry.filename and name not in seen
            seen.add(name)
            mode = stat.S_IFMT(entry.external_attr >> 16)
            if entry.is_dir():
                assert mode in (0, stat.S_IFDIR) and entry.file_size == 0
                (target / name).mkdir(parents=True, exist_ok=True)
            else:
                assert mode in (0, stat.S_IFREG)
                destination = target / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, destination.open("xb") as output:
                    shutil.copyfileobj(source, output)
    archive_path.unlink()
    return metadata


def main(root):
    root.mkdir()
    assert shutil.disk_usage(root).free >= 12 * 1024**3
    build, jobs = run_identity(BUILD_RUN, BUILD_HEAD, "openclaw-artifacts.yml")
    assert build["conclusion"] == "failure"
    required = {"build (" + label + ")" for label in ORIGINAL if label.startswith("bun-webkit-")} | {"windows-arm64"}
    assert len(required) == 11 and all(jobs[name]["conclusion"] == "success" and jobs[name]["run_attempt"] == 1 for name in required)
    replay, jobs = run_identity(REPLAY_RUN, REPLAY_HEAD, "openclaw-hosted-linux-consumer.yml")
    assert replay["conclusion"] == "success" and jobs["linux-native"]["conclusion"] == "success"
    artifacts = api(f"actions/runs/{REPLAY_RUN}/artifacts?per_page=100")["artifacts"]
    admitted = []
    for label in ("hosted-linux-native-proof", "hosted-linux-bun-executables"):
        matches = [item for item in artifacts if item["name"] == label]
        assert len(matches) == 1
        item = matches[0]
        assert item["size_in_bytes"] <= (8 * 1024**2 if label.endswith("proof") else 512 * 1024**2)
        admitted.append(download(root, label, [item["id"], item["size_in_bytes"], item["digest"]], REPLAY_RUN, REPLAY_HEAD))
    proof = root / "hosted-linux-native-proof"
    record, complete = read(proof / "matrix-replay.json"), read(proof / "matrix-replay-complete.json")
    assert record["run"] == BUILD_RUN and record["carrier"] == BUILD_HEAD and record["sync"] == SOURCE
    assert record["source"] == "2323913322dfdfed96ecf20163d62f5ff2796ecc"
    assert record["candidate_build_reused"] is True and record["candidate_runtime_evidence_reused"] is False
    assert record["manifest_sha256"] == "96d5eb1558b84d13b09e7ff1c56904a6834f72ad43d5558c92ad42e5ae75feb2"
    assert record["replay_control_sha256"] == "73f7154030e02bb01fbf0e2d62c77d17aac5c7a94e05ca022e6b26eebfd1d66d"
    assert complete["passed"] is True and complete["replay_sha256"] == sha(proof / "matrix-replay.json")
    assert complete["gate_sha256"] == sha(proof / "gate.json")
    assert complete["candidate_identity_sha256"] == record["candidate_identity_sha256"] == sha(proof / "candidate-identity.json")
    for name, digest in record["reused_files"].items():
        path = PurePosixPath(name)
        assert not path.is_absolute() and ".." not in path.parts
        assert sha(proof / path) == digest, name
    (root / "hosted-linux-native-proof").rename(root / "qualification")
    (root / "hosted-linux-bun-executables").rename(root / "linux-bun-executables")
    for label, row in ORIGINAL.items():
        admitted.append(download(root, label, row, BUILD_RUN, BUILD_HEAD))
    (root / "assembly-inputs.json").write_text(json.dumps({"source": SOURCE, "build_run": BUILD_RUN,
        "replay_run": REPLAY_RUN, "artifacts": admitted}, indent=2) + "\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
