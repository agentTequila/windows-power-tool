import sys
import unittest
from unittest.mock import patch

from power_tool.core import runner


class RunTests(unittest.TestCase):
    def test_run_captures_output(self):
        result = runner.run([sys.executable, "-c", "print('hello')"], timeout=30)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "hello")

    def test_run_timeout_returns_error_result(self):
        result = runner.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1)
        self.assertEqual(result.returncode, -1)
        self.assertIn("timed out", result.stderr)

    def test_run_missing_binary_returns_error_result(self):
        result = runner.run(["definitely_not_a_real_binary_xyz_123"])
        self.assertEqual(result.returncode, -1)
        self.assertTrue(result.stderr)

    def test_run_does_not_leak_console_output(self):
        self.assertTrue(runner.CREATE_NO_WINDOW > 0)

    def test_run_powershell_prepends_flags(self):
        result = runner.run_powershell("Write-Output 'ps-ok'", timeout=60)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("ps-ok", result.stdout)


class PsQuoteTests(unittest.TestCase):
    def test_wraps_in_single_quotes(self):
        self.assertEqual(runner.ps_quote("admin"), "'admin'")

    def test_doubles_embedded_single_quotes(self):
        self.assertEqual(runner.ps_quote("o'brien"), "'o''brien'")

    def test_non_string_input_is_stringified(self):
        self.assertEqual(runner.ps_quote(42), "'42'")


class RunPowershellCheckedTests(unittest.TestCase):
    @patch.object(runner, "run_powershell")
    def test_returns_stdout_on_success(self, fake_ps):
        fake_ps.return_value = runner.Result(0, "ok", "")
        self.assertEqual(runner.run_powershell_checked("x"), "ok")

    @patch.object(runner, "run_powershell")
    def test_raises_with_stderr_detail_on_failure(self, fake_ps):
        fake_ps.return_value = runner.Result(1, "", "boom")
        with self.assertRaises(RuntimeError) as ctx:
            runner.run_powershell_checked("x")
        self.assertIn("boom", str(ctx.exception))

    @patch.object(runner, "run_powershell")
    def test_passes_timeout_through(self, fake_ps):
        fake_ps.return_value = runner.Result(0, "", "")
        runner.run_powershell_checked("x", timeout=120)
        self.assertEqual(fake_ps.call_args.kwargs["timeout"], 120)


if __name__ == "__main__":
    unittest.main()
