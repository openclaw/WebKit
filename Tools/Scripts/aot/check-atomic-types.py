#!/usr/bin/env python3
"""Check concurrent AOT type publication using a configured native build's flags.

    check-atomic-types.py <build directory>
"""
import argparse
import importlib.util
import json
import pathlib
import subprocess
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("include_checker", HERE / "check-includes.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build_directory", type=pathlib.Path)
    arguments = parser.parse_args()
    commands = json.loads((arguments.build_directory / "compile_commands.json").read_text())
    flags, directory = checker.flags_of(commands, "JavaScriptCore")
    with tempfile.TemporaryDirectory(prefix="aot-atomic-types-") as temporary:
        executable = pathlib.Path(temporary) / "atomic-type-publication"
        command = flags + ["-O2", "-pthread", str(HERE / "tests/atomic-type-publication.cpp"), "-o", str(executable)]
        subprocess.run(command, cwd=directory, check=True)
        return subprocess.run([str(executable)], timeout=60).returncode


if __name__ == "__main__":
    raise SystemExit(main())
