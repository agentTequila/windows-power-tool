import sys
import unittest

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


if __name__ == "__main__":
    unittest.main()
