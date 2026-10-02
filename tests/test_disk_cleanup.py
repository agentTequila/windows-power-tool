import json
import unittest
from unittest.mock import patch

import tkinter as tk

from power_tool.core import theme, widgets
from power_tool.tools import disk_cleanup

REAL_GUARD_ADMIN = widgets.guard_admin

FIXTURE = [
    {"drive": "C:", "label": "System", "total": 107374182400,
     "free": 26843545600, "filesystem": "NTFS", "type": 3},
    {"drive": "D:", "label": "Data", "total": 536870912000,
     "free": 536870912000, "filesystem": "exFAT", "type": 2},
]


class ParseDrivesTests(unittest.TestCase):
    def test_parses_list(self):
        items = disk_cleanup.parse_drives(json.dumps(FIXTURE))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["drive"], "C:")

    def test_single_dict_wrapped_into_list(self):
        items = disk_cleanup.parse_drives(json.dumps(FIXTURE[0]))
        self.assertEqual(items[0]["drive"], "C:")

    def test_null_returns_empty(self):
        self.assertEqual(disk_cleanup.parse_drives("null"), [])

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            disk_cleanup.parse_drives("not json")

    def test_non_dict_list_raises(self):
        with self.assertRaises(ValueError):
            disk_cleanup.parse_drives("[1, 2, 3]")


class FormatGbTests(unittest.TestCase):
    def test_formats_gb(self):
        self.assertEqual(disk_cleanup.format_gb(1073741824), "1.0 GB")

    def test_zero_and_none(self):
        self.assertEqual(disk_cleanup.format_gb(0), "0.0 GB")
        self.assertEqual(disk_cleanup.format_gb(None), "0.0 GB")

    def test_garbage(self):
        self.assertEqual(disk_cleanup.format_gb("abc"), "0 GB")


class PctFreeTests(unittest.TestCase):
    def test_quarter_free(self):
        self.assertEqual(
            disk_cleanup.pct_free(107374182400, 26843545600), "25%")

    def test_full_free(self):
        self.assertEqual(disk_cleanup.pct_free(100, 100), "100%")

    def test_zero_total_is_not_available(self):
        self.assertEqual(disk_cleanup.pct_free(0, 0), "n/a")

    def test_garbage_is_not_available(self):
        self.assertEqual(disk_cleanup.pct_free("abc", "x"), "n/a")


class TypeNameTests(unittest.TestCase):
    def test_fixed_and_removable(self):
        self.assertEqual(disk_cleanup.type_name(3), "Fixed")
        self.assertEqual(disk_cleanup.type_name(2), "Removable")

    def test_string_number(self):
        self.assertEqual(disk_cleanup.type_name("3"), "Fixed")

    def test_unknown_code_passes_through(self):
        self.assertEqual(disk_cleanup.type_name(99), "99")


class GatherTests(unittest.TestCase):
    @patch.object(disk_cleanup.runner, "run_powershell_checked")
    def test_uses_checked_runner(self, fake_checked):
        fake_checked.return_value = json.dumps(FIXTURE)
        items = disk_cleanup.gather()
        self.assertEqual(len(items), 2)
        fake_checked.assert_called_once_with(
            disk_cleanup.DRIVES_SCRIPT, timeout=120)


class DiskCleanupFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()
        theme.apply_theme(cls.root, "dark")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        task = patch.object(disk_cleanup.tasks, "BackgroundTask")
        self.fake_task = task.start()
        self.addCleanup(task.stop)
        guard = patch.object(disk_cleanup.widgets, "guard_admin",
                             return_value=True)
        guard.start()
        self.addCleanup(guard.stop)
        self.frame = disk_cleanup.DiskCleanupFrame(self.root)
        self.fake_task.reset_mock()

    def _load(self, drives=FIXTURE):
        self.frame._load_done(list(drives))

    def test_load_done_populates_tree(self):
        self._load()
        self.assertEqual(len(self.frame._tree.get_children()), 2)
        values = self.frame._tree.item("0", "values")
        self.assertEqual(values, ("C:", "System", "100.0 GB", "25.0 GB",
                                  "25%", "NTFS", "Fixed"))

    def test_refresh_button_starts_task(self):
        self._load()
        self.frame._refresh_button.invoke()
        kwargs = self.fake_task.call_args.kwargs
        self.assertIs(kwargs["work"], disk_cleanup.gather)

    def test_refresh_disables_buttons_and_error_reenables(self):
        self.frame._refresh()
        self.assertEqual(
            str(self.frame._refresh_button.cget("state")), "disabled")
        self.assertEqual(str(self.frame._cleanup_button.cget("state")),
                         "disabled")
        kwargs = self.fake_task.call_args.kwargs
        kwargs["on_error"](RuntimeError("boom"))
        self.assertEqual(
            str(self.frame._refresh_button.cget("state")), "normal")
        self.assertEqual(str(self.frame._cleanup_button.cget("state")),
                         "normal")
        self.assertIn("boom", self.frame.status.text())
        self.assertEqual(str(self.frame.status._label.cget("style")),
                         "Error.TLabel")

    def test_cleanup_guarded_requires_admin(self):
        with patch.object(disk_cleanup.widgets, "guard_admin",
                          REAL_GUARD_ADMIN), \
             patch("power_tool.core.admin.is_admin", return_value=False), \
             patch.object(disk_cleanup.widgets, "confirm",
                          return_value=True), \
             patch.object(disk_cleanup.runner, "start_detached") as fake_det:
            self.frame._run_cleanup()
        fake_det.assert_not_called()
        self.assertIn("Run as administrator required",
                      self.frame.status.text())

    def test_cleanup_cancelled_confirm_starts_nothing(self):
        with patch.object(disk_cleanup.widgets, "confirm",
                          return_value=False), \
             patch.object(disk_cleanup.runner, "start_detached") as fake_det:
            self.frame._run_cleanup()
        fake_det.assert_not_called()
        self.assertIn("Cancelled", self.frame.status.text())

    def test_cleanup_confirmed_launches_cleanmgr(self):
        with patch.object(disk_cleanup.widgets, "confirm",
                          return_value=True), \
             patch.object(disk_cleanup.runner, "start_detached") as fake_det:
            self.frame._run_cleanup()
        fake_det.assert_called_once_with(["cleanmgr"])
        self.assertIn("Disk Cleanup opened", self.frame.status.text())

    def test_cleanup_launch_failure_reports_error(self):
        with patch.object(disk_cleanup.widgets, "confirm",
                          return_value=True), \
             patch.object(disk_cleanup.runner, "start_detached",
                          side_effect=FileNotFoundError("gone")):
            self.frame._run_cleanup()
        self.assertIn("Could not start Disk Cleanup",
                      self.frame.status.text())
        self.assertEqual(str(self.frame.status._label.cget("style")),
                         "Error.TLabel")


if __name__ == "__main__":
    unittest.main()
