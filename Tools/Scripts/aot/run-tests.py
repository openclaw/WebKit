#!/usr/bin/env python3
"""Runs the engine's own tests of ahead-of-time compilation and sound types. A few minutes.

    run-tests.py <jsc> [--jobs <n>]

The tests are JSTests/stress/aot-*.js and sound-types-*.js. Each `//@ runDefault(...)` of a header is a run of its own; the runs of
one test follow each other, since they may write the same files, and different tests run beside each other. The first one
runs twice more: with every inferred type checked against the value and the B3 and Air validators on, as in the mode `aot-validate`;
and without data stubs, which is what a CPU other than ARM64 and x86-64 would compile. A `//@ run("name", ...)` in the header is one
more run, with the options of the first `runDefault` and its own.

A test fails if it prints anything or exits with anything but 0. run-javascriptcore-tests runs all of this and much more, in
the modes `aot` and `aot-validate` among the rest. This is what is quick enough to run after every change.
"""
import argparse
import concurrent.futures
import glob
import os
import platform
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STRESS = os.path.realpath(os.path.join(HERE, "..", "..", "..", "JSTests", "stress"))
SKIP_LISTS = ("bun-tests-that-change-builtins.txt", "bun-tests-that-read-function-text.txt")


def aot_skip_lists():
    """The same lists used by run-jsc-stress-tests for its aot modes."""
    result = {}
    for name in SKIP_LISTS:
        with open(os.path.join(STRESS, "..", name)) as file:
            for line in file:
                entry = line.strip()
                if entry and not entry.startswith("#"):
                    result[entry] = name
    return result


def architecture_of_host():
    architecture = platform.machine().lower()
    return {"aarch64": "arm64", "amd64": "x86_64"}.get(architecture, architecture)


def header_skip_reason(header, architecture):
    for line in header:
        if match := re.match(r'//@ skip if \$architecture (!=|==) "([^"]+)"(?:\s*#.*)?$', line):
            equal = architecture == match.group(2)
            if equal == (match.group(1) == "=="):
                return f"requires a different architecture ({line[3:]})"
        elif line.startswith("//@ skip"):
            # Do not silently run (or skip) a new Ruby condition we do not understand.
            raise ValueError(f"unsupported skip directive: {line}")
        if re.search(r'\$skipModes\s*<<\s*:(aot|lockdown)\b', line):
            return "header skips the aot modes"
    return None

def header_of(path):
    with open(path, errors="replace") as file:
        lines = file.read().split("\n")
    count = next((index for index, line in enumerate(lines) if not line.startswith("//@ ")), len(lines))
    return lines[:count]


def options_in(text):
    return re.findall(r'"(--?[^"]*)"', text)


def uses_aot(options):
    enabled = False
    for option in options:
        if option == "--compileMainScriptAheadOfTime":
            enabled = True
        elif option.startswith("--compileMainScriptAheadOfTime="):
            enabled = option.split("=", 1)[1].lower() not in ("0", "false")
        elif option.startswith("--aotImagePath="):
            enabled = bool(option.split("=", 1)[1])
    return enabled


def run(jsc, options, test):
    """Returns None if the test passed, or a line that says how it did not."""
    if "-m" in options:
        options = [option for option in options if option != "-m"] + ["-m"]
    command = [sys.executable, os.path.join(HERE, "capped.py"), "4", "120", jsc, *options, test]
    result = subprocess.run(command, cwd=STRESS, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    output = [line for line in result.stdout.split("\n") if line and not line.startswith("[capped]")]
    if not result.returncode and not output:
        return None
    return f"exit {result.returncode} {output[0][:120] if output else ''}"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("jsc")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--filter", default="", help="only test names matching this regular expression")
    parser.add_argument("--architecture", default=architecture_of_host(), help="target architecture, if different from the host")
    parser.add_argument("--ignore-skip-lists", action="store_true", help="run listed tests too, to regenerate the AOT skip lists")
    arguments = parser.parse_args()
    jsc = os.path.abspath(arguments.jsc)

    tests = sorted(os.path.basename(path) for pattern in ("aot-*.js", "sound-types-*.js") for path in glob.glob(os.path.join(STRESS, pattern)) if re.search(arguments.filter, os.path.basename(path)))
    skip_lists = {} if arguments.ignore_skip_lists else aot_skip_lists()
    header_skips = {}
    runs = []
    for test in tests:
        header = header_of(os.path.join(STRESS, test))
        header_skips[test] = header_skip_reason(header, arguments.architecture)
        common = options_in(" ".join(line for line in header if not line.startswith("//@ run")))
        lines = [common + options_in(line) for line in header if re.match(r"//@ run[A-Z]", line)] or [common]
        options = lines[0]
        for line in header:
            if also := re.match(r'//@ run\("([^"]+)"(.*)\)', line):
                runs.append((test, options + options_in(also.group(2)), also.group(1)))
        for index, line in enumerate(lines):
            runs.append((test, line, "as it says" if len(lines) == 1 else f"run {index + 1} of {len(lines)}"))
        if not any("$skipModes << :aot_validate" in line for line in header):
            runs.append((test, options + ["--validateAOTInferredTypes=true", "--validateGraphAtEachPhase=true", "--aotTypeCoveragePath="], "validated"))
        runs.append((test, options + ["--useAOTDataStubs=false"], "without data stubs"))

    selected = []
    skipped = {}
    for entry in runs:
        test, options, label = entry
        reason = header_skips[test] or (skip_lists.get("stress/" + test) if uses_aot(options) else None)
        if reason:
            previous = skipped.get(test, (reason, 0))
            skipped[test] = (reason, previous[1] + 1)
        else:
            selected.append(entry)
    runs = selected
    for test, (reason, count) in skipped.items():
        print(f"SKIP {test}: {reason} ({count} runs)")

    failures = 0
    runs_of = {test: [entry for entry in runs if entry[0] == test] for test in tests}
    with concurrent.futures.ThreadPoolExecutor(max_workers=arguments.jobs) as pool:
        for problems in pool.map(lambda test: [(entry, run(jsc, entry[1], test)) for entry in runs_of[test]], tests):
            for (test, options, label), problem in problems:
                if problem:
                    failures += 1
                    print(f"FAIL {test} [{label}] {problem}")
    print(f"{len(runs) - failures} pass, {failures} fail, {sum(count for reason, count in skipped.values())} runs skipped in {len(skipped)} tests")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
