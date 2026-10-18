#!/usr/bin/env python3
"""The stress runner's results file, not its exit status, is authoritative."""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("root", type=Path)
parser.add_argument("--require", action="append", dest="required", help="Regression filename that must execute (repeatable)")
args = parser.parse_args()
root = args.root
lines = (root / "results").read_text().splitlines()
if not lines:
    raise SystemExit("JSC produced no test results")
required = args.required or ["module-namespace-esmodule-marker.js"]
variants = {name: sum(name in line for line in lines) for name in required}
missing = [name for name, count in variants.items() if not count]
if missing:
    raise SystemExit("JSC regressions did not execute: " + ", ".join(missing))
failures = [line for line in lines if not line.endswith(": PASS")]
if failures:
    raise SystemExit("JSC failures:\n" + "\n".join(failures))
print(json.dumps({"tests": len(lines), "required_variants": variants, "passed": True}))
