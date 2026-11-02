#!/usr/bin/env python3
"""Admit the exact signed Bun source snapshot for pre-push native qualification."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

COMMIT = "c6a7bf9d8dc4d44db9f826e47a5ae7645ea6e8c9"
TREE = "ef814c1b5ef7731d6373cfacb8c88b0227a670aa"
PARENT = "04e10be52c3632ded738bc7c71e34d74babcd04e"
REF = "refs/heads/claude/webkit-bun-882-qualification-20261102"
PREREQUISITES = (
    "dd5eed75f82e5972e3a3928032bbede7eafd2795",
    "7b573c05d0c52dffc67d4d25daf108bed5930cf2",
    "3f3a9ff87cdccf3d32d7ec6b648c664eddaae840",
)
DIGEST = "d6e34e289b33399b0cf1e1cb40a3f3c6ac977685e7730b7b58d5572cef5f7249"
SIZE = 372405


def main():
    assert len(sys.argv) == 2, "expected a new destination directory"
    destination = Path(sys.argv[1]).resolve()
    assert not destination.exists(), "source destination already exists"
    encoded = Path(__file__).with_name("bun-882-qualification.bundle.b64")
    assert encoded.is_file() and encoded.stat().st_size < 512 * 1024
    data = base64.b64decode(b"".join(encoded.read_bytes().splitlines()), validate=True)
    assert len(data) == SIZE and hashlib.sha256(data).hexdigest() == DIGEST
    header = data.split(b"\n\n", 1)[0].decode("ascii").splitlines()
    assert header[0] == "# v2 git bundle"
    assert {line[1:].split(" ", 1)[0] for line in header[1:] if line.startswith("-")} == set(PREREQUISITES)
    assert [line for line in header[1:] if not line.startswith("-")] == [COMMIT + " " + REF]

    def git(*args):
        return subprocess.check_output(
            ["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false", "-C", str(destination), *args],
            timeout=180, text=True,
        ).strip()

    destination.mkdir(parents=True)
    git("init", "--quiet")
    git("remote", "add", "origin", "https://github.com/openclaw/bun.git")
    for commit in PREREQUISITES:
        git("fetch", "--no-tags", "--no-auto-gc", "--depth=1", "origin", commit)
        assert git("rev-parse", commit) == commit
    with tempfile.TemporaryDirectory(prefix="bun-source-") as scratch:
        bundle = Path(scratch, "source.bundle")
        bundle.write_bytes(data)
        git("bundle", "verify", str(bundle))
        git("fetch", "--no-tags", "--no-auto-gc", str(bundle), REF)
    assert git("rev-parse", COMMIT + "^{tree}") == TREE
    assert git("show", "-s", "--format=%P", COMMIT) == PARENT
    git("checkout", "--detach", COMMIT)
    assert git("rev-parse", "HEAD") == COMMIT
    assert not git("status", "--porcelain")
    print(json.dumps({"commit": COMMIT, "tree": TREE, "parent": PARENT,
                      "bundle_sha256": DIGEST, "bundle_bytes": SIZE,
                      "prerequisites": PREREQUISITES, "qualification_only": True}))


if __name__ == "__main__":
    main()
