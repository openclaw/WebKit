#!/usr/bin/env python3
"""Diagnose the frozen consumer driver; this never emits a qualification gate."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import signal
import stat
import subprocess
import sys
import time
import zipfile

SYNC = "42e4245f4180941634b482a7e8ef7fca47467de5"
CARRIER = "4f3c924c6e29be27b902e285b1e82801dca81b21"
RUN = 41236713193
ARTIFACTS = {
    "proof": (13065898437, 146231, "dee1f3532c401e3db86272aa0e8acace8dd0264b6b48ffa6f1617b53ebf8046c"),
    "binaries": (13065868636, 181870231, "c66ce8b9176f6bb7bd71a35d879e1a9b9e8d800707aef79c3cce1fd7515b2275"),
}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def unpack(root, name, *, expected=None, run=RUN, carrier=CARRIER):
    artifact, size, digest = ARTIFACTS[name] if expected is None else expected
    metadata = read(root / (name + ".metadata.json"))
    archive = root / (name + ".zip")
    assert metadata["id"] == artifact and not metadata["expired"]
    assert metadata["size_in_bytes"] == archive.stat().st_size == size
    assert metadata["digest"] == "sha256:" + digest and sha(archive) == digest
    assert metadata["workflow_run"]["id"] == run
    assert metadata["workflow_run"]["head_sha"] == carrier
    destination = root / name
    destination.mkdir()
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        assert 0 < len(entries) <= 128 and sum(x.file_size for x in entries) < 512 * 1024**2
        assert len({x.filename for x in entries}) == len(entries)
        for entry in entries:
            path = PurePosixPath(entry.filename)
            assert not path.is_absolute() and "\\" not in entry.filename
            assert all(p not in ("", ".", "..") for p in entry.filename.rstrip("/").split("/"))
            mode = stat.S_IFMT(entry.external_attr >> 16)
            assert mode in (0, stat.S_IFDIR if entry.is_dir() else stat.S_IFREG)
            target = destination / path
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(entry) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(0o600)
    return destination


def bounded(command, output, seconds, **kwargs):
    with output.open("xb") as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=True, **kwargs)
        try:
            return process.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            return None
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)


def instrument(path):
    text = path.read_text()
    def replace(before, after):
        nonlocal text
        assert text.count(before) == 1, before
        text = text.replace(before, after)
    replace("readFileSync, rmSync, statfsSync, writeFileSync", "readFileSync, rmSync, statfsSync, writeFileSync, writeSync")
    marker = "function diagnostic(stage: string, facts: unknown = null) { writeSync(2, JSON.stringify({diagnostic: stage, facts}) + \"\\n\"); }\n"
    replace("// In 50 trials,", marker + "// In 50 trials,")
    replace("    const kibibytes = Number.parseInt(usage.stdout, 10);", "    diagnostic(\"du-return\", {name, pid: usage.pid, status: usage.status, signal: usage.signal, code: usage.error?.code, message: usage.error?.message});\n    const kibibytes = Number.parseInt(usage.stdout, 10);")
    replace("    writeFileSync(`build/openclaw-ci/disk-${stage}-tests.json`, JSON.stringify(snapshot, null, 2) + \"\\n\");", "    diagnostic(\"before-disk-write\", stage);\n    writeFileSync(`build/openclaw-ci/disk-${stage}-tests.json`, JSON.stringify(snapshot, null, 2) + \"\\n\");\n    diagnostic(\"after-disk-write\", stage);")
    replace('      { stdio: "inherit" },\n    );', '      { stdio: "inherit" },\n    );\n    diagnostic("grouped-return", {pid: result.pid, status: result.status, signal: result.signal, code: result.error?.code, message: result.error?.message});')
    replace('      direct = spawnSync(process.execPath, ["test", netTest], { encoding: "utf8" });', '      direct = spawnSync(process.execPath, ["test", netTest], { encoding: "utf8" });\n      diagnostic("net-return", {pid: direct.pid, status: direct.status, signal: direct.signal, code: direct.error?.code, message: direct.error?.message});')
    replace('    reportDiskUsage("after");', '    reportDiskUsage("after");\n    diagnostic("before-terminal-write");')
    replace('    if (ownerExitFailed) throw new Error', '    diagnostic("after-terminal-write");\n    if (ownerExitFailed) throw new Error')
    replace('    if (result.error) throw result.error;', '    diagnostic("before-error-check", {hasError: !!result.error});\n    if (result.error) throw result.error;')
    replace('    if (result.status !== 0) process.exit(result.status ?? 1);', '    if (result.status !== 0) { diagnostic("before-exit", result.status); process.exit(result.status ?? 1); diagnostic("exit-returned"); }')
    replace('    assertSelectedTestResults(selected, results);', '    diagnostic("before-result-check");\n    assertSelectedTestResults(selected, results);\n    diagnostic("after-result-check");')
    path.write_text(text)
    return sha(path)


def main():
    root, frozen, repo, inspector = map(lambda x: Path(x).resolve(), sys.argv[1:])
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "ACTIONS_RUNTIME_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN"):
        os.environ.pop(key, None)
    assert subprocess.check_output(["git", "-C", str(frozen), "rev-parse", "HEAD"], text=True).strip() == SYNC
    inputs = frozen / ".github/openclaw/qualification"
    sys.path.insert(0, str(inputs))
    import consumer_identity as identity
    proof, binaries = unpack(root, "proof"), unpack(root, "binaries")
    baseline, candidate = read(proof / "baseline-identity.json"), read(proof / "candidate-identity.json")
    identity.validate_baseline_evidence(baseline, binaries, proof)
    identity.validate_evidence(candidate, SYNC, candidate["engine"], binaries, proof)
    identity.validate_invocation(proof, "baseline")
    carrier = read(proof / "carrier.json")
    assert carrier["carrier"] == CARRIER and carrier["sync"] == SYNC
    pin = identity.CONFIG["candidate"]
    assert subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD", "HEAD^{tree}"], text=True).splitlines() == [pin["commit"], pin["tree"]]
    subprocess.run(["git", "-C", str(repo), "diff", "--exit-code", "HEAD"], check=True)
    overlay = proof / "candidate-manifest.patch"
    subprocess.run(["git", "-C", str(repo), "apply", "--check", str(overlay)], check=True)
    subprocess.run(["git", "-C", str(repo), "apply", str(overlay)], check=True)
    actual_overlay = subprocess.check_output(["git", "-C", str(repo), "diff", "--binary", "HEAD"])
    assert hashlib.sha256(actual_overlay).hexdigest() == candidate["overlay"]["patch_sha256"]
    fixture = repo.parent / candidate["fixture"]["path"]
    assert not fixture.exists()
    shutil.copyfile(binaries / candidate["fixture"]["path"], fixture)
    spec = identity.adapter_spec("candidate", "test")
    for path, record in spec["files"].items():
        assert sha(repo / path) == record["before"]
    patch = inputs / spec["patch"]
    assert sha(patch) == spec["sha256"]
    subprocess.run(["git", "-C", str(repo), "apply", "--check", str(patch)], check=True)
    subprocess.run(["git", "-C", str(repo), "apply", str(patch)], check=True)
    for path, record in spec["files"].items():
        assert sha(repo / path) == record["after"]
    run = root / "diagnostic"
    run.mkdir()
    state = repo.parent / "candidate"
    state.mkdir()
    for name in ("home", "tmp", "bin"):
        (state / name).mkdir(mode=0o700)
    executable = repo.parent / candidate["executable"]["path"]
    executable.parent.mkdir(parents=True)
    shutil.copyfile(binaries / candidate["executable"]["path"], executable)
    assert sha(executable) == candidate["executable"]["sha256"]
    executable.chmod(0o700)
    (state / "bin/bun").symlink_to(executable)
    selection = inputs / "selected.json"
    assert selection.read_bytes() == (proof / "candidate/selected.json").read_bytes()
    target = repo / "build/openclaw-ci"
    target.mkdir(parents=True)
    shutil.copyfile(selection, target / "selected.json")
    driver = repo / "scripts/openclaw-ci/tests.ts"
    before, after = sha(driver), instrument(driver)
    env = os.environ.copy()
    for key in ("GH_TOKEN", "GITHUB_TOKEN", *identity.BUILD_ENV):
        env.pop(key, None)
    env.update(HOME=str(state / "home"), TMPDIR=str(state / "tmp"), CI="1", PUPPETEER_SKIP_DOWNLOAD="1",
               PATH=str(state / "bin") + os.pathsep + str(inspector.parent) + os.pathsep + env["PATH"],
               OPENCLAW_CI_PLATFORM="linux")
    assert not any(key in env for key in ("GH_TOKEN", "GITHUB_TOKEN"))
    status = {"qualification": False, "source": SYNC, "reused_run": RUN,
              "binary": candidate["executable"], "driver_before_sha256": before,
              "driver_instrumented_sha256": after, "deadline_seconds": 600}
    bootstrap = read(proof / "candidate-build-tools.json")["bootstrap"]
    assert inspector.stat().st_size == bootstrap["size"] and sha(inspector) == bootstrap["sha256"]
    # The installed inspector only prepares dependencies; the retained candidate runs the failing driver.
    install_env = os.environ.copy()
    install_env.update(CI="1", PUPPETEER_SKIP_DOWNLOAD="1",
                       PATH=str(inspector.parent) + os.pathsep + install_env["PATH"])
    for folder in (repo, repo / "test"):
        assert bounded([str(inspector), "install", "--frozen-lockfile"],
                       run / ("install-root.log" if folder == repo else "install-test.log"),
                       180, cwd=folder, env=install_env) == 0
    assert identity.runtime(executable) == candidate["runtime"]
    log = run / "driver.log"
    with log.open("xb") as stream:
        process = subprocess.Popen([str(executable), "scripts/openclaw-ci/tests.ts", "test"],
                                   cwd=repo, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        started = time.monotonic()
        try:
            while process.poll() is None and time.monotonic() - started < 600:
                if log.stat().st_size >= 32 * 1024**2:
                    status["output_limit_reached"] = True
                    break
                if int(time.monotonic() - started) % 10 == 0:
                    print(json.dumps({"elapsed_seconds": int(time.monotonic() - started), "log_bytes": log.stat().st_size}), flush=True)
                time.sleep(1)
            status.update(pid=process.pid, elapsed_seconds=round(time.monotonic() - started, 2),
                          returncode=process.poll(), timed_out=process.poll() is None)
            if process.poll() is None:
                rows = subprocess.check_output(["ps", "-eo", "pid,ppid,pgid,stat,wchan:32,comm"], text=True)
                owned = [line for line in rows.splitlines()[1:] if line.split()[2] == str(process.pid)]
                (run / "processes.txt").write_text("\n".join(owned) + "\n")
                bounded(["sudo", "-n", "gdb", "--nx", "--nh", "--batch", "-iex", "set auto-load off",
                         "-iex", "set debuginfod enabled off", "-ex", "attach " + str(process.pid),
                         "-ex", "thread apply all bt 20", "-ex", "detach"], run / "stacks.log", 20)
                if process.poll() is None:
                    bounded(["sudo", "-n", "strace", "-tt", "-T", "-p", str(process.pid),
                             "-e", "trace=process,futex,write,exit,exit_group"], run / "syscalls.log", 10)
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
            status["cleanup_returncode"] = process.returncode
            for name in ("results.json", "runner-terminal.json", "net-direct.json", "disk-before-tests.json", "disk-after-tests.json"):
                path = target / name
                if path.exists():
                    assert path.is_file() and not path.is_symlink() and path.stat().st_size <= 16 * 1024**2
                    shutil.copyfile(path, run / name)
            (run / "diagnostic.json").write_text(json.dumps(status, indent=2) + "\n")
    print(json.dumps(status), flush=True)
    return int(status["timed_out"] or status["returncode"] != 0)


if __name__ == "__main__":
    raise SystemExit(main())
