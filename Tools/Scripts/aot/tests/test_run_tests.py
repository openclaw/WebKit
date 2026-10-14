import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("runner", Path(__file__).resolve().parents[1] / "run-tests.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
text_spec = importlib.util.spec_from_file_location("function_text", Path(__file__).resolve().parents[1] / "list-tests-that-read-function-text.py")
function_text = importlib.util.module_from_spec(text_spec)
text_spec.loader.exec_module(function_text)
builtins_spec = importlib.util.spec_from_file_location("builtins_list", Path(__file__).resolve().parents[1] / "list-tests-that-change-builtins.py")
builtins_list = importlib.util.module_from_spec(builtins_spec)
builtins_spec.loader.exec_module(builtins_list)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.stress = self.root / "stress"
        self.stress.mkdir()
        for name in runner.SKIP_LISTS:
            (self.root / name).write_text("# comment\n\n")
        self.patch = patch.object(runner, "STRESS", str(self.stress))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def run_suite(self, header, *arguments):
        (self.stress / "aot-example.js").write_text(header + "\nthrow new Error('must run');\n")
        output = io.StringIO()
        with patch("sys.argv", ["run-tests.py", "/unused/jsc", *arguments]), patch.object(runner, "run", return_value="known failure") as run, contextlib.redirect_stdout(output):
            result = runner.main()
        return result, run.call_args_list, output.getvalue()

    def test_unlisted_failures_still_fail_all_modes(self):
        result, calls, output = self.run_suite('//@ runDefault("--compileMainScriptAheadOfTime=1")')
        self.assertEqual(result, 1)
        self.assertEqual(len(calls), 3)
        self.assertIn("0 pass, 3 fail, 0 runs skipped in 0 tests", output)
        self.assertIn("--validateAOTInferredTypes=true", calls[1].args[1])

    def test_both_lists_are_honored(self):
        for name in runner.SKIP_LISTS:
            with self.subTest(name=name):
                (self.root / name).write_text("# comment\n\nstress/aot-example.js\n")
                result, calls, output = self.run_suite('//@ runDefault("--compileMainScriptAheadOfTime=1")')
                self.assertEqual((result, len(calls)), (0, 0))
                self.assertIn(name, output)
                (self.root / name).write_text("")

    def test_regeneration_bypasses_lists(self):
        (self.root / runner.SKIP_LISTS[0]).write_text("stress/aot-example.js\n")
        result, calls, _ = self.run_suite('//@ runDefault("--compileMainScriptAheadOfTime=1")', "--ignore-skip-lists")
        self.assertEqual((result, len(calls)), (1, 3))

    def test_interpreter_controls_are_not_excluded(self):
        (self.root / runner.SKIP_LISTS[0]).write_text("stress/aot-example.js\n")
        header = '//@ runDefault("--compileMainScriptAheadOfTime=1")\n//@ runDefault("--compileMainScriptAheadOfTime=0")'
        result, calls, output = self.run_suite(header)
        self.assertEqual((result, len(calls)), (1, 1))
        self.assertIn("--compileMainScriptAheadOfTime=0", calls[0].args[1])
        self.assertIn("3 runs skipped in 1 tests", output)

    def test_architecture_directive(self):
        header = '//@ skip if $architecture != "arm64" # instruction size\n//@ runDefault'
        result, calls, output = self.run_suite(header, "--architecture=x86_64", "--ignore-skip-lists")
        self.assertEqual((result, len(calls)), (0, 0))
        self.assertIn("architecture", output)
        result, calls, _ = self.run_suite(header, "--architecture=arm64")
        self.assertEqual((result, len(calls)), (1, 3))

    def test_validation_skip_does_not_hide_other_modes(self):
        result, calls, _ = self.run_suite('//@ $skipModes << :aot_validate\n//@ runDefault')
        self.assertEqual((result, len(calls)), (1, 2))

    def test_unknown_skip_is_not_silently_ignored(self):
        with self.assertRaisesRegex(ValueError, "unsupported skip"):
            self.run_suite('//@ skip if $unknown\n//@ runDefault')

    def test_function_text_probe_really_uses_the_interpreter(self):
        options = function_text.interpreter_options('//@ runDefault("--compileMainScriptAheadOfTime=1", "--useSoundTypes=1", "-m")')
        self.assertEqual(options, ["--useSoundTypes=1", "-m"])

    def test_mutation_probe_forces_aot_even_for_interpreter_fixtures(self):
        for options in ([], ["--compileMainScriptAheadOfTime=0"]):
            self.assertTrue(runner.uses_aot(builtins_list.validation_options(options)))

    def test_mutation_refresh_preserves_tests_it_cannot_run(self):
        (self.root / runner.SKIP_LISTS[0]).write_text("stress/aot-example.js\n")
        (self.stress / "aot-example.js").write_text('//@ skip if $architecture != "arm64"\n')
        output = io.StringIO()
        with patch.object(builtins_list.runner, "STRESS", str(self.stress)), patch.object(builtins_list.runner, "architecture_of_host", return_value="x86_64"), patch.object(builtins_list.runner, "run", side_effect=AssertionError("must not run")), patch("sys.argv", ["generator", "/unused/jsc"]), contextlib.redirect_stdout(output):
            builtins_list.main()
        self.assertIn("stress/aot-example.js", output.getvalue())

    def test_explicit_source_retention_is_not_a_reason_to_skip(self):
        for value in ("1", "true"):
            self.assertIsNone(function_text.interpreter_options(f'//@ runDefault("--compileMainScriptAheadOfTime=1", "--useAOTFunctionSource={value}")'))


if __name__ == "__main__":
    unittest.main()
