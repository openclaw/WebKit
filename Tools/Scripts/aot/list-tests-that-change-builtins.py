#!/usr/bin/env python3
"""Refresh the AOT-suite entries in JSTests/bun-tests-that-change-builtins.txt.

    list-tests-that-change-builtins.py <jsc> [--jobs N] > /tmp/builtins.txt

Runs every aot-* and sound-types-* test with validation, ignoring the skip lists,
then reruns failures in the interpreter with immutable intrinsics. Only failures
in both runs are candidates. Inspect each candidate's mutation before replacing
the list. Entries outside this suite are preserved; regenerate those with the
full run-jsc-stress-tests aot-validate mode as described in the list's header.
"""
import argparse
import concurrent.futures
import glob
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("aot_run_tests", os.path.join(HERE, "run-tests.py"))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def validation_options(options):
    return options + ["--compileMainScriptAheadOfTime=1", "--validateAOTInferredTypes=true", "--validateGraphAtEachPhase=true", "--aotTypeCoveragePath="]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("jsc", type=os.path.abspath)
    parser.add_argument("--jobs", type=int, default=4)
    arguments = parser.parse_args()
    tests = sorted(os.path.basename(path) for pattern in ("aot-*.js", "sound-types-*.js") for path in glob.glob(os.path.join(runner.STRESS, pattern)))

    def changes_builtins(test):
        header = runner.header_of(os.path.join(runner.STRESS, test))
        if runner.header_skip_reason(header, runner.architecture_of_host()) or any("$skipModes << :aot_validate" in line for line in header):
            return None
        common = runner.options_in(" ".join(line for line in header if not line.startswith("//@ run")))
        runs = [common + runner.options_in(line) for line in header if re.match(r"//@ run[A-Z]", line)] or [common]
        options = runs[0]
        if runner.run(arguments.jsc, validation_options(options), test) is None:
            return False
        interpreted = [option for option in options if not option.startswith(("--compileMainScriptAheadOfTime=", "--aotImagePath=", "--writeAOTImageTo="))]
        interpreted += ["--useJIT=0", "--useImmutableIntrinsics=1"]
        failure = runner.run(arguments.jsc, interpreted, test)
        if failure is None:
            return False
        print(f"{test}: {failure}", file=sys.stderr)
        return True

    path = os.path.join(runner.STRESS, "..", "bun-tests-that-change-builtins.txt")
    with open(path) as file:
        lines = file.read().splitlines()
    entries = {line for line in lines if line and not line.startswith("#")}
    with concurrent.futures.ThreadPoolExecutor(arguments.jobs) as pool:
        for test, changes in zip(tests, pool.map(changes_builtins, tests)):
            if changes:
                entries.add("stress/" + test)
            elif changes is not None:
                entries.discard("stress/" + test)
    for line in lines:
        if line.startswith("#"):
            print(line)
    print()
    print("\n".join(sorted(entries)))


if __name__ == "__main__":
    main()
