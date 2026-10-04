#!/usr/bin/env python3
"""The stress runner's results file, not its exit status, is authoritative."""
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
lines = (root / "results").read_text().splitlines()
if not lines:
    raise SystemExit("JSC produced no test results")
namespace = [line for line in lines if "module-namespace-esmodule-marker.js" in line]
if not namespace:
    raise SystemExit("The namespace marker regression did not execute")
failures = [line for line in lines if not line.endswith(": PASS")]
if failures:
    raise SystemExit("JSC failures:\n" + "\n".join(failures))
print(json.dumps({"tests": len(lines), "marker_variants": len(namespace), "passed": True}))
