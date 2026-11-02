#!/usr/bin/env python3
"""Stage fixed engine archives and current controls for the Bun sync continuation."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import zipfile

ENGINE = "1281a1be4796f541bcaf0ef751941c41dfbf7817"
RUN = 41348390908
ARTIFACTS = (
    ("native", 13100940398, "bun-webkit-linux-amd64", 716167821,
     "5301976fbc042f06a746a5bc31bbf75826856c029673cb82f0a388c8f5827fd4"),
    ("aot", 13101342737, "bun-webkit-linux-amd64-aot", 1286974348,
     "c148115518c5a553540a7172afeeff5f7dda02c1eb2166a4e27563adc0ab9d99"),
)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True, timeout=120).strip()


def main():
    workspace = Path(os.environ["GITHUB_WORKSPACE"])
    pipeline, controls = workspace / "pipeline", workspace / "controls"
    root = Path(os.environ["RUNNER_TEMP"])
    retained, proof = root / "retained-engine", root / "qualification"
    assert git(pipeline, "rev-parse", "HEAD") == ENGINE
    control_head = git(controls, "rev-parse", "HEAD")
    assert control_head == os.environ["GITHUB_SHA"]
    proof.mkdir(exist_ok=True)
    artifacts = {}
    for key, identity, name, size, digest in ARTIFACTS:
        metadata = json.loads((retained / (key + ".metadata.json")).read_text())
        archive = retained / (key + ".zip")
        assert metadata["id"] == identity and metadata["name"] == name and not metadata["expired"]
        assert metadata["workflow_run"]["id"] == RUN and metadata["workflow_run"]["head_sha"] == ENGINE
        assert metadata["size_in_bytes"] == archive.stat().st_size == size
        assert metadata["digest"] == "sha256:" + digest and sha(archive) == digest
        destination = root / ("linux-artifact" if key == "native" else "linux-aot-artifact")
        destination.mkdir()
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            assert 0 < len(entries) <= 64
            assert len({entry.filename for entry in entries}) == len(entries)
            assert sum(entry.file_size for entry in entries) < 3 * 1024**3
            assert bundle.testzip() is None
            for entry in entries:
                relative = PurePosixPath(entry.filename)
                assert not relative.is_absolute() and ".." not in relative.parts and "\\" not in entry.filename
                assert all(part not in ("", ".", "..") for part in entry.filename.rstrip("/").split("/"))
                mode = stat.S_IFMT(entry.external_attr >> 16)
                assert mode in (0, stat.S_IFDIR if entry.is_dir() else stat.S_IFREG)
                target = destination / relative
                if entry.is_dir():
                    assert entry.file_size == 0
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with bundle.open(entry) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
                    target.chmod(0o644)
        artifacts[key] = {"id": identity, "name": name, "bytes": size, "sha256": digest, "run": RUN}

    names = git(controls, "ls-files", "-z", "--", ".github/openclaw").split("\0")
    names = [name for name in names if name]
    assert 0 < len(names) <= 512
    assert sum((controls / name).stat().st_size for name in names) < 64 * 1024**2
    installed = {}
    for name in names:
        source, target = controls / name, pipeline / name
        assert stat.S_ISREG(source.lstat().st_mode)
        indexed = git(controls, "ls-files", "-s", "--", name).split()
        data = source.read_bytes()
        assert indexed[0] in ("100644", "100755")
        assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == indexed[1]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o755 if indexed[0] == "100755" else 0o644)
        installed[name] = hashlib.sha256(data).hexdigest()
    assert git(pipeline, "rev-parse", "HEAD") == ENGINE
    receipt = {"engine": ENGINE, "controls": control_head, "artifacts": artifacts,
               "installed_controls": installed, "engine_runtime_proof": "reused from run41348390908",
               "bun_native_qualification": "pending"}
    (proof / "continuation-inputs.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"engine": ENGINE, "controls": control_head, "artifacts": artifacts,
                      "installed_controls": len(installed)}))


if __name__ == "__main__":
    main()
