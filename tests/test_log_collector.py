import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from power_tool.tools import log_collector


class ParseMinutesTests(unittest.TestCase):
    def test_strips_and_parses(self):
        self.assertEqual(log_collector.parse_minutes("  10 "), 10)

    def test_zero_rejected(self):
        with self.assertRaises(ValueError):
            log_collector.parse_minutes("0")

    def test_negative_rejected(self):
        with self.assertRaises(ValueError):
            log_collector.parse_minutes("-5")

    def test_text_rejected(self):
        with self.assertRaises(ValueError):
            log_collector.parse_minutes("ten")

    def test_float_rejected(self):
        with self.assertRaises(ValueError):
            log_collector.parse_minutes("10.5")

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            log_collector.parse_minutes("")


class BuildXpathTests(unittest.TestCase):
    NOW = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

    def test_single_level_uses_systemtime_cutoff(self):
        xpath = log_collector.build_xpath([2], 10, now=self.NOW)
        self.assertEqual(
            xpath,
            "*[System[TimeCreated[@SystemTime >= '2026-01-01T11:50:00.000Z'] "
            "and (Level=2)]]")

    def test_multiple_levels(self):
        xpath = log_collector.build_xpath([1, 2, 3], 60, now=self.NOW)
        self.assertIn("'2026-01-01T11:00:00.000Z'", xpath)
        self.assertIn("(Level=1 or Level=2 or Level=3)", xpath)

    def test_day_spanning_minutes(self):
        xpath = log_collector.build_xpath([4], 1440, now=self.NOW)
        self.assertIn("'2025-12-31T12:00:00.000Z'", xpath)

    def test_no_level_clause_when_none_selected(self):
        xpath = log_collector.build_xpath([], 10, now=self.NOW)
        self.assertNotIn("Level", xpath)
        self.assertIn("@SystemTime >=", xpath)

    def test_contains_no_timediff(self):
        xpath = log_collector.build_xpath([1, 2, 3], 60, now=self.NOW)
        self.assertNotIn("timediff", xpath)


class BuildPsQueryTests(unittest.TestCase):
    def test_contains_logs_levels_and_starttime(self):
        script = log_collector.build_ps_query(["Application", "System"], [1, 2], 10)
        self.assertIn("'Application'", script)
        self.assertIn("'System'", script)
        self.assertIn("Get-WinEvent", script)
        self.assertIn("AddMinutes(-10)", script)
        self.assertIn("$levels = @(1,2)", script)

    def test_text_script_has_output_path_and_count(self):
        script = log_collector.build_text_script(
            ["Application"], [1], 5, Path(r"C:\out\events.txt"))
        self.assertIn(r"C:\out\events.txt", script)
        self.assertIn("COLLECTED=", script)
        self.assertIn("Format-List", script)

    def test_csv_script_uses_export_csv(self):
        script = log_collector.build_csv_script(
            ["System"], [2, 3], 15, Path(r"C:\out\events.csv"))
        self.assertIn("Export-Csv -Path", script)
        self.assertNotIn("Export-Csv -FilePath", script)
        self.assertIn(r"C:\out\events.csv", script)
        self.assertIn("COLLECTED=", script)


class ParseCountTests(unittest.TestCase):
    def test_extracts_count(self):
        self.assertEqual(log_collector.parse_count("noise\nCOLLECTED=42\n"), 42)

    def test_missing_count_returns_zero(self):
        self.assertEqual(log_collector.parse_count("no marker here"), 0)


class DefaultOutputDirTests(unittest.TestCase):
    def test_timestamped_name(self):
        now = datetime.datetime(2026, 9, 30, 14, 5, 9)
        path = log_collector.default_output_dir(Path(r"C:\Users\me\Desktop"), now)
        self.assertEqual(path.name, "Logs_20260930_140509")
        self.assertEqual(path.parent, Path(r"C:\Users\me\Desktop"))


class CollectEvtxTests(unittest.TestCase):
    @staticmethod
    def _export_ok(args, timeout=300):
        from power_tool.core.runner import Result
        Path(args[3]).write_bytes(b"evtx-bytes")
        return Result(0, "", "")

    @patch.object(log_collector, "runner")
    def test_builds_wevtutil_command_per_log(self, fake_runner):
        from power_tool.core.runner import Result
        fake_runner.run.side_effect = self._export_ok
        fake_runner.run_powershell.return_value = Result(0, "COUNT=1", "")
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            paths, errors = log_collector.collect_evtx(
                ["Application", "System"], [1, 2], 10, out_dir)
        self.assertEqual(errors, [])
        self.assertEqual(len(paths), 2)
        self.assertEqual(paths[0].name, "Application.evtx")
        epl_calls = [c[0][0] for c in fake_runner.run.call_args_list
                     if c[0][0][:2] == ["wevtutil", "epl"]]
        first_args = epl_calls[0]
        self.assertEqual(first_args[2], "Application")
        self.assertTrue(any(arg.startswith("/q:*[System") for arg in first_args))
        self.assertIn("@SystemTime", first_args[4])

    @patch.object(log_collector, "runner")
    def test_collects_errors_from_failed_logs(self, fake_runner):
        from power_tool.core.runner import Result
        fake_runner.run.return_value = Result(1, "", "Access denied")
        with tempfile.TemporaryDirectory() as tmp:
            paths, errors = log_collector.collect_evtx(["Security"], [1], 10,
                                                       Path(tmp))
        self.assertEqual(paths, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("Access denied", errors[0])

    @patch.object(log_collector, "runner")
    def test_empty_export_deleted_and_reported(self, fake_runner):
        from power_tool.core.runner import Result
        fake_runner.run.side_effect = self._export_ok
        fake_runner.run_powershell.return_value = Result(0, "COUNT=0", "")
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            paths, errors = log_collector.collect_evtx(["System"], [1], 10,
                                                       out_dir)
            self.assertEqual(paths, [])
            self.assertEqual(len(errors), 1)
            self.assertIn("no events matched", errors[0])
            self.assertFalse((out_dir / "System.evtx").exists())

    @patch.object(log_collector, "runner")
    def test_probe_failure_keeps_exported_file(self, fake_runner):
        from power_tool.core.runner import Result
        fake_runner.run.side_effect = self._export_ok
        fake_runner.run_powershell.return_value = Result(
            1, "", "probe exploded")
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            paths, errors = log_collector.collect_evtx(["System"], [1], 10,
                                                       out_dir)
            self.assertEqual(errors, [])
            self.assertEqual(len(paths), 1)
            self.assertTrue((out_dir / "System.evtx").exists())

    @patch.object(log_collector, "runner")
    def test_mixed_logs_report_both_statuses(self, fake_runner):
        from power_tool.core.runner import Result
        fake_runner.run.side_effect = self._export_ok
        fake_runner.run_powershell.side_effect = [
            Result(0, "COUNT=0", ""),   # System: empty
            Result(0, "COUNT=1", ""),   # Application: has records
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            paths, errors = log_collector.collect_evtx(
                ["System", "Application"], [1], 10, out_dir)
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].name, "Application.evtx")
        self.assertEqual(len(errors), 1)
        self.assertIn("System", errors[0])
        self.assertIn("no events matched", errors[0])


class CollectTextCsvTests(unittest.TestCase):
    @patch.object(log_collector, "runner")
    def test_txt_collects_count(self, fake_runner):
        from power_tool.core.runner import Result
        with tempfile.TemporaryDirectory() as tmp:
            def fake_powershell(script, timeout=600):
                (Path(tmp) / "events.txt").write_text(
                    "TimeCreated : ...", encoding="utf-8")
                return Result(0, "COLLECTED=7\n", "")
            fake_runner.run_powershell.side_effect = fake_powershell
            path, count, error = log_collector.collect_text_csv(
                ["Application"], [1, 2, 3], 10, Path(tmp), "txt")
            self.assertEqual(path.name, "events.txt")
            self.assertEqual(count, 7)
            self.assertEqual(error, "")
            self.assertTrue(path.exists())

    @patch.object(log_collector, "runner")
    def test_csv_returns_error_on_failure(self, fake_runner):
        from power_tool.core.runner import Result
        fake_runner.run_powershell.return_value = Result(1, "", "boom")
        with tempfile.TemporaryDirectory() as tmp:
            path, count, error = log_collector.collect_text_csv(
                ["System"], [1], 10, Path(tmp), "csv")
        self.assertEqual(count, 0)
        self.assertIn("boom", error)

    @patch.object(log_collector, "runner")
    def test_reports_error_when_count_positive_but_file_empty(self, fake_runner):
        from power_tool.core.runner import Result
        fake_runner.run_powershell.return_value = Result(0, "COLLECTED=5\n", "")
        with tempfile.TemporaryDirectory() as tmp:
            path, count, error = log_collector.collect_text_csv(
                ["System"], [1], 10, Path(tmp), "csv")
            self.assertEqual(count, 0)
            self.assertIn("empty", error.lower())
            self.assertEqual(path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
