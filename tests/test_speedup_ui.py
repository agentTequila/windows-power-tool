import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import tkinter as tk

from power_tool.core import runner, theme
from power_tool.tools import speedup

RESULT = {"removed": 3, "freed": 1024, "skipped": 1, "browsers": ["Chrome"]}


class FrameSetupMixin:
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()
        theme.apply_theme(cls.root, "dark")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.frame = speedup.SpeedupFrame(self.root)


class BrowserSelectionTests(FrameSetupMixin, unittest.TestCase):
    def test_three_individual_browser_vars_default_unchecked(self):
        self.assertEqual(sorted(self.frame._browser_vars),
                         ["Chrome", "Edge", "Firefox"])
        self.assertEqual(self.frame._selected_browsers(), [])

    def test_selecting_individual_browsers(self):
        self.frame._browser_vars["Chrome"].set(True)
        self.frame._browser_vars["Firefox"].set(True)
        self.assertEqual(self.frame._selected_browsers(), ["Chrome", "Firefox"])


class WorkFlowTests(FrameSetupMixin, unittest.TestCase):
    @patch.object(speedup, "browser_launch_command",
                  return_value=["C:\\chrome.exe"])
    @patch.object(speedup, "browser_cleanup_targets",
                  return_value=[Path("cache-entry")])
    @patch.object(speedup, "runner")
    @patch.object(speedup, "clear_directory", return_value=(2, 100, 0))
    def test_work_closes_running_browser_cleans_and_reopens(
            self, fake_clear, fake_runner, fake_targets, fake_launch):
        fake_runner.run.side_effect = [
            runner.Result(0, "chrome.exe", ""),  # tasklist: running
            runner.Result(0, "", ""),            # taskkill
        ]
        with patch.object(speedup, "is_process_running", return_value=True), \
             patch.object(speedup, "close_process") as fake_close, \
             patch.object(speedup, "remove_target", return_value=(True, 5)):
            result = self.frame._work(["Chrome"], clear_recycle=False)
        fake_close.assert_called_once_with("chrome.exe")
        fake_launch.assert_called_once()
        fake_runner.start_detached.assert_called_once_with(["C:\\chrome.exe"])
        self.assertEqual(result["browsers"], ["Chrome"])
        self.assertEqual(result["removed"], 9)   # 4 temp dirs x2 + 1 browser
        self.assertEqual(result["freed"], 405)

    @patch.object(speedup, "clear_directory", return_value=(0, 0, 0))
    def test_work_leaves_stopped_browser_alone(self, fake_clear):
        with patch.object(speedup, "is_process_running", return_value=False), \
             patch.object(speedup, "close_process") as fake_close, \
             patch.object(speedup, "browser_cleanup_targets",
                          return_value=[Path("cache")]), \
             patch.object(speedup, "remove_target",
                          return_value=(True, 7)), \
             patch.object(speedup, "browser_launch_command") as fake_launch, \
             patch.object(speedup, "runner") as fake_runner:
            result = self.frame._work(["Firefox"], clear_recycle=False)
        fake_close.assert_not_called()
        fake_launch.assert_not_called()
        fake_runner.start_detached.assert_not_called()
        self.assertEqual(result["browsers"], ["Firefox"])

    def test_work_clears_recycle_bin_when_requested(self):
        with patch.object(speedup, "clear_directory", return_value=(0, 0, 0)), \
             patch.object(speedup, "runner") as fake_runner:
            self.frame._work([], clear_recycle=True)
        fake_runner.run_powershell.assert_called_once()
        self.assertIn("Clear-RecycleBin",
                      fake_runner.run_powershell.call_args[0][0])


class RebootFlowTests(FrameSetupMixin, unittest.TestCase):
    @patch.object(speedup, "runner")
    def test_on_done_without_reboot_never_touches_shutdown(self, fake_runner):
        self.frame._on_done(RESULT, reboot=False)
        fake_runner.run.assert_not_called()
        self.assertIn("Removed 3 items", self.frame.status.text())

    @patch.object(speedup, "runner")
    def test_on_done_with_reboot_schedules_ten_second_shutdown(self, fake_runner):
        fake_runner.run.return_value = runner.Result(0, "", "")
        self.frame._on_done(RESULT, reboot=True)
        args = fake_runner.run.call_args[0][0]
        self.assertEqual(args, ["shutdown", "/r", "/t", "10"])
        self.assertIn("rebooting in 10s", self.frame.status.text())

    @patch.object(speedup, "runner")
    def test_cancel_reboot_aborts_shutdown(self, fake_runner):
        fake_runner.run.return_value = runner.Result(0, "", "")
        self.frame._on_done(RESULT, reboot=True)
        fake_runner.run.reset_mock()
        fake_runner.run.return_value = runner.Result(0, "", "")
        self.frame._cancel_reboot()
        args = fake_runner.run.call_args[0][0]
        self.assertEqual(args, ["shutdown", "/a"])
        self.assertEqual(self.frame.status.text(), "Reboot cancelled.")

    @patch.object(speedup, "tasks")
    @patch("power_tool.core.widgets.confirm", return_value=False)
    @patch("power_tool.core.widgets.guard_admin", return_value=True)
    def test_reboot_confirmation_declined_starts_nothing(
            self, fake_guard, fake_confirm, fake_tasks):
        self.frame._start(reboot=True)
        fake_confirm.assert_called_once()
        fake_tasks.BackgroundTask.assert_not_called()
        self.assertEqual(self.frame.status.text(), "Ready")

    @patch.object(speedup, "tasks")
    @patch("power_tool.core.widgets.confirm", return_value=True)
    @patch("power_tool.core.widgets.guard_admin", return_value=True)
    def test_reboot_confirmation_accepted_starts_task(
            self, fake_guard, fake_confirm, fake_tasks):
        self.frame._start(reboot=True)
        fake_tasks.BackgroundTask.return_value.start.assert_called_once()
        self.assertIn("Cleaning temp folders", self.frame.status.text())


if __name__ == "__main__":
    unittest.main()
