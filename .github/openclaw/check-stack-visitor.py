#!/usr/bin/env python3
"""Pin the live stack visitor to the same call tokens as captured stacks."""
import json
import re
import subprocess
import sys
from pathlib import Path

fixture = Path(__file__).with_name("qualification") / "stack-visitor.js"
expected = [(1, 22), (2, 21), (3, 1)]
for mode, flags in [("default", []), ("interpreter", ["--useJIT=false"])]:
    result = subprocess.run([sys.argv[1], *flags, str(fixture)], capture_output=True, text=True, check=True)
    actual = [(int(line), int(column)) for line, column in re.findall(r"stack-visitor\.js:(\d+):(\d+)", result.stderr)]
    if actual != expected:
        raise SystemExit(f"{mode}: expected {expected}, got {actual}\n{result.stderr}")
    print(json.dumps({"mode": mode, "positions": actual, "passed": True}))
