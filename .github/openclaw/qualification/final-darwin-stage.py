#!/usr/bin/env python3
"""Admit the exact final PR artifact without rebuilding the engine."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import zipfile

ENGINE = "5e7f7f530fa77e832238fb2f93ac4dc6e48d926b"
BUN = "28b6101e24b93b4a222b03fc5a6a83cd4d1c2653"
RUN = 41439918784
ATTEMPT = 1
LANE = "bun-webkit-macos-arm64-aot"
ARTIFACT_ID = 13140589828
ARTIFACT_BYTES = 517845631
ARTIFACT_SHA256 = "9a4d70dd8352dc94e9f5fb933795d068308c253c9171aaefed9d9698ecac041b"
REPO = "repos/openclaw/WebKit"


def api(route):
    return json.loads(subprocess.check_output(["gh", "api", route], timeout=120))


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True, timeout=120).strip()


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    workspace = Path(os.environ["GITHUB_WORKSPACE"])
    pipeline, controls = workspace / "pipeline", workspace / "controls"
    assert ARTIFACT_ID > 0 and 0 < ARTIFACT_BYTES < 3 * 1024**3
    assert len(ARTIFACT_SHA256) == 64
    assert os.environ["GITHUB_REPOSITORY"] == "openclaw/WebKit"
    assert git(pipeline, "rev-parse", "HEAD") == ENGINE
    assert git(controls, "rev-parse", "HEAD") == os.environ["GITHUB_SHA"]
    subprocess.run(["git", "-C", str(pipeline), "diff", "--exit-code", "HEAD"], check=True)
    assert api(REPO + "/pulls/45")["head"]["sha"] == ENGINE
    run = api(f"{REPO}/actions/runs/{RUN}")
    assert run["head_sha"] == ENGINE and run["run_attempt"] == ATTEMPT
    assert run["repository"]["full_name"] == "openclaw/WebKit"
    assert run["path"] == ".github/workflows/openclaw-checks.yml"
    assert run["event"] == "pull_request"
    jobs = api(f"{REPO}/actions/runs/{RUN}/attempts/{ATTEMPT}/jobs?per_page=100")
    assert jobs["total_count"] <= 100
    matches = [j for j in jobs["jobs"] if j["name"] == "macos-fork-artifact"]
    assert len(matches) == 1 and matches[0]["status"] == "completed" and matches[0]["conclusion"] == "success"
    metadata = api(f"{REPO}/actions/artifacts/{ARTIFACT_ID}")
    assert metadata["id"] == ARTIFACT_ID and metadata["name"] == LANE and not metadata["expired"]
    assert metadata["workflow_run"]["id"] == RUN and metadata["workflow_run"]["head_sha"] == ENGINE
    assert metadata["size_in_bytes"] == ARTIFACT_BYTES
    assert metadata["digest"] == "sha256:" + ARTIFACT_SHA256
    temp = Path(os.environ["RUNNER_TEMP"])
    archive = temp / "final-darwin-engine.zip"
    with archive.open("xb") as output:
        subprocess.run(["gh", "api", f"{REPO}/actions/artifacts/{ARTIFACT_ID}/zip"], stdout=output, check=True, timeout=900)
    assert archive.stat().st_size == ARTIFACT_BYTES and sha(archive) == ARTIFACT_SHA256
    destination = temp / "darwin-artifact"
    destination.mkdir()
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        assert 0 < len(entries) <= 64 and len({e.filename for e in entries}) == len(entries)
        assert sum(e.file_size for e in entries) < 4 * 1024**3
        assert bundle.testzip() is None
        for entry in entries:
            relative = PurePosixPath(entry.filename)
            assert not relative.is_absolute() and ".." not in relative.parts and "\\" not in entry.filename
            assert all(p not in ("", ".", "..") for p in entry.filename.rstrip("/").split("/"))
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
    assert (destination / (LANE + ".tar.gz")).is_file()
    assert (destination / (LANE + ".manifest.json")).is_file()
    subprocess.run(["shasum", "-a", "256", "-c", "SHA256SUMS"], cwd=destination, check=True)
    proof = pipeline / "consumer"
    proof.mkdir(exist_ok=True)
    receipt = {
        "engine": ENGINE, "bun": BUN, "controls": os.environ["GITHUB_SHA"],
        "producer": {"run": RUN, "attempt": ATTEMPT, "head": ENGINE, "job": matches[0]["id"]},
        "artifact": {"id": ARTIFACT_ID, "name": LANE, "bytes": ARTIFACT_BYTES, "sha256": ARTIFACT_SHA256},
        "native_consumer_qualification": "pending",
    }
    (proof / "continuation-inputs.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
