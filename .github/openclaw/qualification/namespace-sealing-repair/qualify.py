#!/usr/bin/env python3
"""Prove sealed require namespaces while preserving live exports and hook dispatch."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import xml.etree.ElementTree as ET

WORK = Path("/work")
SOURCE = WORK / "source"
ENGINE = WORK / "engine"
HERE = Path(__file__).resolve().parent
OUT = WORK / "namespace-sealing-proof"
MANIFEST = json.loads((HERE / "source-manifest.json").read_text())
proof = {"passed": False, "steps": {}}

def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()

def save():
    (OUT / "proof.json").write_text(json.dumps(proof, indent=2) + "\n")

def command(name, argv, cwd=SOURCE):
    with (OUT / (name + ".log")).open("w") as stream:
        result = subprocess.run(argv, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT)
    proof["steps"][name] = {"argv": argv, "exit": result.returncode}
    save()
    return result.returncode

def cases(name):
    path = OUT / (name + ".xml")
    root = ET.parse(path).getroot()
    rows = list(root.iter("testcase"))
    failed = [row for row in rows if row.find("failure") is not None or row.find("error") is not None]
    skipped = [row for row in rows if row.find("skipped") is not None]
    result = {"total": len(rows), "active": len(rows) - len(skipped),
              "failed": len(failed), "skipped": len(skipped),
              "failed_names": [row.attrib["name"] for row in failed],
              "skipped_names": [row.attrib["name"] for row in skipped]}
    proof[name] = result
    save()
    return result

def build_inputs(name):
    path = SOURCE / "build/debug-namespaces/compile_commands.json"
    rows = json.loads(path.read_text())
    debug = []
    for row in rows:
        args = row.get("arguments") or shlex.split(row.get("command", ""))
        if "-DASSERT_ENABLED=1" in args and any("-fsanitize=address" in arg for arg in args):
            debug.append(row)
    assert debug and any("/engine/" in json.dumps(row) for row in debug)
    assert any("/aot/" in json.dumps(row) or "AOT" in json.dumps(row) for row in rows)
    (OUT / (name + "-compile-inputs.json")).write_text(json.dumps(debug[:64], indent=2) + "\n")
    return {"compile_commands_sha256": sha(path), "entries": len(rows),
            "assertion_asan_entries": len(debug)}

def main():
    OUT.mkdir(exist_ok=True)
    for key in ("CI", "BUILDKITE", "GITHUB_ACTIONS", "GH_TOKEN", "GITHUB_TOKEN",
                "ACTIONS_RUNTIME_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN"):
        assert not os.environ.get(key), key
    assert git(SOURCE, "rev-parse", "HEAD") == MANIFEST["bun"]
    assert git(SOURCE, "rev-parse", "HEAD^{tree}") == MANIFEST["bun_tree"]
    assert git(ENGINE, "rev-parse", "HEAD") == MANIFEST["engine"]
    for repo in (SOURCE, ENGINE):
        assert not git(repo, "status", "--porcelain")
    controls = os.environ["QUALIFICATION_CONTROLS"]
    assert re.fullmatch("[0-9a-f]{40}", controls)
    assert git(WORK / "proposal", "rev-parse", "HEAD") == controls
    proof["controls"] = controls
    proof["source_manifest_sha256"] = sha(HERE / "source-manifest.json")
    shutil.copyfile(HERE / "source-manifest.json", OUT / "source-manifest.json")
    patch = HERE / "runtime.patch"
    assert sha(patch) == MANIFEST["patch_sha256"]
    for name, identity in MANIFEST["files"].items():
        assert sha(SOURCE / name) == identity["before"], name
    snapshots = {name: (SOURCE / name).read_bytes() for name in MANIFEST["files"]}
    bd = ["bun", "bd", "--webkit=local", "--webkit-version=" + MANIFEST["engine"],
          "--aot=on", "--ci=off", "--buildkite=off", "--build-dir=build/debug-namespaces", "-j4"]
    fixture = "./test/js/bun/resolve/esModule.test.ts"
    def selected(name, file, title=None):
        argv = bd + ["test"] + ([file] if isinstance(file, str) else file)
        if title is not None:
            argv += ["-t", title]
        return command(name, argv + ["--reporter=junit", "--reporter-outfile=" + str(OUT / (name + ".xml"))])
    applied = False
    try:
        assert command("install-root", ["bun", "install", "--frozen-lockfile"]) == 0
        assert command("install-tests", ["bun", "install", "--frozen-lockfile"], SOURCE / "test") == 0
        assert selected("namespaces-before", fixture) == 1
        before = cases("namespaces-before")
        assert before["active"] == 5 and before["failed"] == 3 and before["skipped"] == 0
        assert all("marker reflection and live bindings" in name for name in before["failed_names"])
        log = (OUT / "namespaces-before.log").read_text(errors="replace")
        assert not re.search(r"panic|AddressSanitizer:|ASSERTION FAILED|Aborted|Segmentation fault", log, re.I)
        proof["before_build_inputs"] = build_inputs("before")
        subprocess.run(["git", "apply", "--check", str(patch)], cwd=SOURCE, check=True)
        subprocess.run(["git", "apply", str(patch)], cwd=SOURCE, check=True)
        applied = True
        for name, identity in MANIFEST["files"].items():
            assert sha(SOURCE / name) == identity["after"], name
        assert selected("namespaces-after", fixture) == 0
        after = cases("namespaces-after")
        assert after["active"] == 5 and after["failed"] == 0 and after["skipped"] == 0
        namespace_files = [
            fixture, "./test/js/bun/namespace-prototype-pollution.test.ts",
            "./test/js/bun/resolve/require-esm-evaluating-cycle.test.ts",
            "./test/js/bun/import-attributes/import-attributes.test.ts",
            "./test/js/node/module/require-extensions.test.ts",
        ]
        assert selected("namespace-contracts", namespace_files) == 0
        contracts = cases("namespace-contracts")
        assert os.geteuid() == 0
        assert contracts["total"] == 91 and contracts["active"] == 90 and contracts["failed"] == 0
        assert contracts["skipped"] == 1
        assert len(contracts["skipped_names"]) == 1
        assert contracts["skipped_names"][0].endswith("?inline on a file that cannot be read")
        assert selected("hook-compatibility", "./test/js/node/module/register-hooks-virtual-urls.test.ts") == 0
        hooks = cases("hook-compatibility")
        assert hooks["active"] == 102 and hooks["failed"] == 0 and hooks["skipped"] == 0
        assert not git(SOURCE, "diff", "--cached", "--name-only")
        assert set(git(SOURCE, "diff", "--name-only").splitlines()) == set(MANIFEST["files"])
        proof["after_build_inputs"] = build_inputs("after")
        binary = SOURCE / "build/debug-namespaces/bun-debug"
        proof["binary"] = {"bytes": binary.stat().st_size, "sha256": sha(binary)}
        proof["qualified_sources"] = {name: sha(SOURCE / name) for name in MANIFEST["files"]}
        proof["passed"] = True
    finally:
        proof["restored"] = False
        try:
            if applied:
                for name, identity in MANIFEST["files"].items():
                    assert sha(SOURCE / name) == identity["after"], name
                for name, content in snapshots.items():
                    (SOURCE / name).write_bytes(content)
            for name, identity in MANIFEST["files"].items():
                assert sha(SOURCE / name) == identity["before"], name
            for repo in (SOURCE, ENGINE):
                assert not git(repo, "diff", "--name-only")
                assert not git(repo, "diff", "--cached", "--name-only")
            proof["restored"] = True
        finally:
            if not proof["restored"]:
                proof["passed"] = False
            save()

if __name__ == "__main__":
    main()
