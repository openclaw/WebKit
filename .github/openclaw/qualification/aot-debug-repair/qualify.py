#!/usr/bin/env python3
"""Qualify measured C6 repairs and a host namespace cutover on one Debug graph."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
WORK = Path("/work")
OUT = WORK / "aot-debug-proof"
SOURCE = WORK / "source"
ENGINE = WORK / "engine"
MANIFEST = json.loads((HERE / "source-manifest.json").read_text())
NAMESPACE = "host require keeps compiled namespace markers and defaults separate from imports"
applied = []
proof = {"passed": False, "scope": "secretless native Linux x64 AOT Debug; no release or shipping pin promotion",
         "bun_base": MANIFEST["bun"], "engine_base": MANIFEST["engine"], "steps": {}}

def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

def git(repo, *args):
    return subprocess.check_output(["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false",
                                    "-C", str(repo), *args], text=True).strip()

def save():
    (OUT / "proof.json").write_text(json.dumps(proof, indent=2) + "\n")

def overlay(name):
    row = MANIFEST["groups"][name]
    repo = WORK / row["repo"]
    patch = HERE / name
    assert sha(patch) == row["sha256"], name
    for path, identity in row["files"].items():
        assert sha(repo / path) == identity["before"], path
    subprocess.run(["git", "-C", str(repo), "apply", "--check", str(patch)], check=True)
    subprocess.run(["git", "-C", str(repo), "apply", str(patch)], check=True)
    applied.append(name)
    for path, identity in row["files"].items():
        assert sha(repo / path) == identity["after"], path
    proof.setdefault("overlays", []).append({"name": name, **row})
    save()

def command(name, argv, cwd=SOURCE):
    log = OUT / (name + ".log")
    print("phase:", name, flush=True)
    with log.open("wb") as output:
        result = subprocess.run(argv, cwd=cwd, stdout=output, stderr=subprocess.STDOUT)
    row = {"argv": argv, "exit_code": result.returncode, "log_bytes": log.stat().st_size,
           "log_sha256": sha(log)}
    proof["steps"][name] = row
    save()
    assert log.stat().st_size <= 64 * 1024**2, "unbounded phase log"
    return result.returncode

def cases(name):
    path = OUT / (name + ".xml")
    assert path.is_file() and 0 < path.stat().st_size <= 8 * 1024**2
    root = ET.parse(path).getroot()
    rows = list(root.iter("testcase"))
    assert rows, name
    values = [{"name": row.get("name", ""), "classname": row.get("classname", ""),
               "failed": row.find("failure") is not None or row.find("error") is not None,
               "skipped": row.find("skipped") is not None} for row in rows]
    proof["steps"][name]["junit"] = values
    proof["steps"][name]["junit_sha256"] = sha(path)
    save()
    return values

def selected_case(name, title):
    rows = cases(name)
    matching = [row for row in rows if title in row["name"]]
    assert len(matching) == 1 and not matching[0]["skipped"], (name, matching)
    executed = [row for row in rows if not row["skipped"]]
    assert executed == matching, (name, executed)
    return matching[0]

def one_pass(name, title):
    assert not selected_case(name, title)["failed"], name

def build_inputs():
    path = SOURCE / "build/debug-prepush/compile_commands.json"
    assert path.is_file() and path.stat().st_size <= 64 * 1024**2
    rows = json.loads(path.read_text())
    assert rows and all(isinstance(row, dict) for row in rows)
    selected = []
    for row in rows:
        args = row.get("arguments") or shlex.split(row.get("command", ""))
        joined = " ".join(args)
        if "-DASSERT_ENABLED=1" in args and any("-fsanitize=address" in arg for arg in args):
            selected.append(row)
    assert selected, "no actual Debug assertion/ASAN native compiler inputs"
    assert any("/engine/" in json.dumps(row) for row in selected), "no local engine compilation inputs"
    assert any("AOT" in json.dumps(row) or "/aot/" in json.dumps(row) for row in rows), "no AOT compilation inputs"
    (OUT / "debug-compile-inputs.json").write_text(json.dumps(selected[:64], indent=2) + "\n")
    return {"compile_commands_sha256": sha(path), "entries": len(rows),
            "assertion_asan_entries": len(selected)}

def main():
    OUT.mkdir(exist_ok=True)
    save()
    assert all(not os.environ.get(key) for key in ("CI", "BUILDKITE", "GITHUB_ACTIONS", "GH_TOKEN",
        "GITHUB_TOKEN", "ACTIONS_RUNTIME_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN"))
    for repo, head in ((SOURCE, MANIFEST["bun"]), (ENGINE, MANIFEST["engine"])):
        assert git(repo, "rev-parse", "HEAD") == head
        assert not git(repo, "status", "--porcelain")
        assert git(repo, "diff", "--cached", "--name-only") == ""
    assert git(SOURCE, "rev-parse", "HEAD^{tree}") == MANIFEST["bun_tree"]
    proof["controls"] = os.environ.get("QUALIFICATION_CONTROLS")
    assert re.fullmatch("[0-9a-f]{40}", proof["controls"] or "")
    assert git(WORK / "proposal", "rev-parse", "HEAD") == proof["controls"]
    shutil.copyfile(HERE / "source-manifest.json", OUT / "source-manifest.json")
    bd = ["bun", "bd", "--webkit=local", "--webkit-version=" + MANIFEST["engine"], "--aot=on",
          "--ci=off", "--buildkite=off", "--build-dir=build/debug-prepush", "-j2"]
    def selected(name, file, title):
        return command(name, bd + ["test", file, "-t", title, "--reporter=junit",
                       "--reporter-outfile=" + str(OUT / (name + ".xml"))])
    try:
        overlay("runtime-repairs.patch")
        overlay("darwin-path-owner.patch")
        overlay("namespace-regression.patch")
        overlay("vm-pressure-regression.patch")
        overlay("engine-require-facade.patch")
        assert command("install-root", ["bun", "install", "--frozen-lockfile"]) == 0
        assert command("install-tests", ["bun", "install", "--frozen-lockfile"], SOURCE / "test") == 0
        red = selected("namespace-red", "./test/aot/run-aot.test.ts", NAMESPACE)
        row = selected_case("namespace-red", NAMESPACE)
        text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", (OUT / "namespace-red.log").read_text(errors="replace"))
        assert red == 1 and row["failed"]
        assert "namespace facade" in text and "expect(host.mocked.__esModule).toBe(true)" in text
        assert re.search(r"\b1 fail\b", text)
        assert re.search(r"(?m)^error: expect\(received\)\.toBe\(expected\)\s*$", text)
        assert re.search(r"Expected: true\s+Received: undefined", text)
        assert re.search(r"(?m)^\s+at .*[/\\]one\.test\.ts:24:\d+\)?\s*$", text)
        assert not re.search(r"panic|AddressSanitizer:|ASSERTION FAILED|IRTextError|Aborted|Segmentation fault", text, re.I)
        proof["namespace_red"] = "inner mocked module marker assertion reached; setup/crashes excluded"
        proof["red_build_inputs"] = build_inputs()
        binary = SOURCE / "build/debug-prepush/bun-debug"
        assert binary.is_file()
        proof["red_binary"] = {"bytes": binary.stat().st_size, "sha256": sha(binary)}
        save()
        overlay("namespace-host.patch")
        assert selected("namespace-green", "./test/aot/run-aot.test.ts", NAMESPACE) == 0
        one_pass("namespace-green", NAMESPACE)
        repairs = ["./test/js/bun/plugin/plugins.test.ts", "./test/js/node/fs/fs.test.ts",
                   "./test/js/node/module/node-module-module.test.js"]
        assert command("repairs", bd + ["test", *repairs, "--reporter=junit",
                       "--reporter-outfile=" + str(OUT / "repairs.xml")]) == 0
        rows = cases("repairs")
        assert not any(row["failed"] for row in rows)
        required = ("matches the Node stat and lstat oracle", "lstat still throws ENOTDIR",
                    "static-cycle-import", "static-cycle-require",
                    "but not for the name of a builtin", "but not for modules loaded while an onResolve callback is running",
                    "once when the path it returns matches its own filter",
                    "and when it declines, import.meta.resolve() of a path works as without plugins",
                    "from build.module() as well")
        for title in required:
            found = [row for row in rows if title in row["name"]]
            assert found and all(not row["skipped"] for row in found), title
        vm_title = "shared source buffers survive compilation-cache eviction"
        assert selected("vm-pressure", "./test/js/node/vm/vm.test.ts", vm_title) == 0
        vm_rows = cases("vm-pressure")
        vm_active = [row for row in vm_rows if not row["skipped"]]
        assert len(vm_active) == 2 and all(not row["failed"] and vm_title in row["name"] for row in vm_active)
        assert any("é" in row["name"] for row in vm_active) and any("λ🚀" in row["name"] for row in vm_active)
        for name, file, title in (
            ("json-smoke", "./test/aot/run-aot.test.ts", "a module that the constant parts of a dynamic path match is compiled"),
            ("mock-sibling", "./test/aot/a-mock-of-a-built-in-module-that-import-alone-reaches-is-what-runs.test.ts",
             "a module written at run time requires a module of native code that compiled code has imported and mocked")):
            assert selected(name, file, title) == 0
            one_pass(name, title)
        proof["green_build_inputs"] = build_inputs()
        proof["green_binary"] = {"bytes": binary.stat().st_size, "sha256": sha(binary)}
        for group in MANIFEST["groups"].values():
            for path, identity in group["files"].items():
                assert sha(WORK / group["repo"] / path) == identity["after"], path
        proof["passed"] = True
    finally:
        proof["restored"] = False
        try:
            for name in reversed(applied):
                repo = WORK / MANIFEST["groups"][name]["repo"]
                patch = HERE / name
                subprocess.run(["git", "-C", str(repo), "apply", "--reverse", "--check", str(patch)], check=True)
                subprocess.run(["git", "-C", str(repo), "apply", "--reverse", str(patch)], check=True)
                for path, identity in MANIFEST["groups"][name]["files"].items():
                    assert sha(repo / path) == identity["before"], path
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
