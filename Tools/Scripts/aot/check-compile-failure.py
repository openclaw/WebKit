#!/usr/bin/env python3
"""Check that failed AOT compilation exits unsuccessfully without overwriting an image.

    check-compile-failure.py <jsc>
"""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jsc", type=lambda value: str(Path(value).resolve()))
    arguments = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="aot-compile-failure-") as directory:
        source = Path(directory) / "invalid.js"
        source.write_text("function ( {\n")
        image = Path(directory) / "program.img"
        for previous in (None, b"previous image\n"):
            if previous is not None:
                image.write_bytes(previous)
            result = subprocess.run([arguments.jsc, f"--writeAOTImageTo={image}", str(source)], capture_output=True)
            assert result.returncode != 0, "failed compilation reported success"
            if previous is None:
                assert not image.exists(), "failed compilation created an image"
            else:
                assert image.read_bytes() == previous, "failed compilation overwrote an existing image"
    print("2 compile-failure checks passed")


if __name__ == "__main__":
    main()
