#!/usr/bin/env python3
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("verify-jsc-results.py")


class JSCResultTests(unittest.TestCase):
    def run_check(self, rows, *args):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "results").write_text("\n".join(rows))
            return subprocess.run([sys.executable, str(SCRIPT), directory, *args], capture_output=True, text=True)

    def test_default_requires_namespace(self):
        self.assertNotEqual(self.run_check(["stress/another.js.default: PASS"]).returncode, 0)
        result = self.run_check(["stress/module-namespace-esmodule-marker.js.default: PASS"])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_all_requested_regressions_must_execute(self):
        result = self.run_check(["stress/callsite.js.default: PASS"], "--require", "callsite.js", "--require", "property.js")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("property.js", result.stderr)

    def test_any_failed_configuration_rejects_results(self):
        result = self.run_check(["stress/callsite.js.default: PASS", "stress/callsite.js.ftl-eager: FAIL"], "--require", "callsite.js")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ftl-eager: FAIL", result.stderr)
        self.assertNotEqual(self.run_check([], "--require", "callsite.js").returncode, 0)

    def test_reports_all_passing_variants(self):
        result = self.run_check(["stress/callsite.js.default: PASS", "stress/callsite.js.ftl-eager: PASS", "stress/property.js.default: PASS"], "--require", "callsite.js", "--require", "property.js")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"tests": 3, "required_variants": {"callsite.js": 2, "property.js": 1}, "passed": True})


if __name__ == "__main__":
    unittest.main()
