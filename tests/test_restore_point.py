import json
import unittest
from datetime import datetime
from unittest.mock import patch

import tkinter as tk

from power_tool.core import theme, widgets
from power_tool.tools import restore_point

REAL_GUARD_ADMIN = widgets.guard_admin

FIXTURE = [
    {"sequence": 12, "description": "Windows Update",
     "created": "2026-10-01 08:00:00", "type": "APPLICATION_INSTALL",
     "event": "BEGIN_SYSTEM_CHANGE"},
    {"sequence": 11, "description": "Manual checkpoint",
     "created": "2026-09-30 17:30:00", "type": "MODIFY_SETTINGS",
     "event": "BEGIN_SYSTEM_CHANGE"},
]


class ParseRestorePointsTests(unittest.TestCase):
    def test_parses_list(self):
        items = restore_point.parse_restore_points(json.dumps(FIXTURE))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["sequence"], 12)

    def test_single_dict_wrapped_into_list(self):
        items = restore_point.parse_restore_points(json.dumps(FIXTURE[0]))
        self.assertEqual(items[0]["description"], "Windows Update")

    def test_null_returns_empty(self):
        self.assertEqual(restore_point.parse_restore_points("null"), [])

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            restore_point.parse_restore_points("not json")

    def test_non_dict_list_raises(self):
        with self.assertRaises(ValueError):
            restore_point.parse_restore_points("[1, 2, 3]")


class TimestampedDescriptionTests(unittest.TestCase):
    def test_fixed_moment(self):
        now = datetime(2026, 10, 2, 15, 45, 7)
        self.assertEqual(restore_point.timestamped_description(now),
                         "WPT 2026-10-02 15:45:07")


class CreateScriptTests(unittest.TestCase):
    def test_builds_command(self):
        self.assertEqual(
            restore_point.create_script("WPT 2026-10-02 15:45:07"),
            "Checkpoint-Computer -Description 'WPT 2026-10-02 15:45:07'"
            " -RestorePointType 'MODIFY_SETTINGS'")

    def test_quotes_single_quotes_in_description(self):
        script = restore_point.create_script("it's here")
        self.assertIn("'it''s here'", script)


class GatherTests(unittest.TestCase):
    @patch.object(restore_point.runner, "run_powershell_checked")
    def test_uses_checked_runner(self, fake_checked):
        fake_checked.return_value = json.dumps(FIXTURE)
        items = restore_point.gather()
        self.assertEqual(len(items), 2)
        fake_checked.assert_called_once_with(
            restore_point.LIST_SCRIPT, timeout=120)


class RestorePointFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()
        theme.apply_theme(cls.root, "dark")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        task = patch.object(restore_point.tasks, "BackgroundTask")
        self.fake_task = task.start()
        self.addCleanup(task.stop)
        guard = patch.object(restore_point.widgets, "guard_admin",
                             return_value=True)
        guard.start()
        self.addCleanup(guard.stop)
        self.frame = restore_point.RestorePointFrame(self.root)
        self.fake_task.reset_mock()

    def _load(self, points=FIXTURE):
        self.frame._load_done(list(points))

    def test_load_done_populates_tree(self):
        self._load()
        self.assertEqual(len(self.frame._tree.get_children()), 2)
        values = self.frame._tree.item("0", "values")
        self.assertEqual(values, ("12", "2026-10-01 08:00:00",
                                  "Windows Update", "APPLICATION_INSTALL",
                                  "BEGIN_SYSTEM_CHANGE"))

    def test_refresh_button_starts_task(self):
        self._load()
        self.frame._refresh_button.invoke()
        kwargs = self.fake_task.call_args.kwargs
        self.assertIs(kwargs["work"], restore_point.gather)

    def test_refresh_disables_buttons_and_error_reenables(self):
        self.frame._refresh()
        self.assertEqual(
            str(self.frame._refresh_button.cget("state")), "disabled")
        self.assertEqual(str(self.frame._create_button.cget("state")),
                         "disabled")
        kwargs = self.fake_task.call_args.kwargs
        kwargs["on_error"](RuntimeError("System Restore is disabled"))
        self.assertEqual(
            str(self.frame._refresh_button.cget("state")), "normal")
        self.assertEqual(str(self.frame._create_button.cget("state")),
                         "normal")
        self.assertIn("System Restore is disabled",
                      self.frame.status.text())
        self.assertEqual(str(self.frame.status._label.cget("style")),
                         "Error.TLabel")

    def test_create_guarded_requires_admin(self):
        with patch.object(restore_point.widgets, "guard_admin",
                          REAL_GUARD_ADMIN), \
             patch("power_tool.core.admin.is_admin", return_value=False), \
             patch.object(restore_point.widgets, "confirm",
                          return_value=True):
            self.frame._create()
        self.fake_task.assert_not_called()
        self.assertIn("Run as administrator required",
                      self.frame.status.text())

    def test_create_cancelled_confirm_starts_no_task(self):
        with patch.object(restore_point.widgets, "confirm",
                          return_value=False):
            self.frame._create()
        self.fake_task.assert_not_called()
        self.assertIn("Cancelled", self.frame.status.text())

    def test_create_confirmed_starts_task_with_script(self):
        with patch.object(restore_point.widgets, "confirm",
                          return_value=True):
            self.frame._create()
        work = self.fake_task.call_args.kwargs["work"]
        self.assertTrue(
            work.args[0].startswith(
                "Checkpoint-Computer -Description 'WPT "))
        self.assertIn("-RestorePointType 'MODIFY_SETTINGS'", work.args[0])
        self.assertEqual(work.args[1], 300)

    def test_action_done_reports_and_refreshes(self):
        with patch.object(restore_point.widgets, "confirm",
                          return_value=True):
            self.frame._create()
        kwargs = self.fake_task.call_args.kwargs
        kwargs["on_done"](None)
        load_kwargs = self.fake_task.call_args.kwargs
        load_kwargs["on_done"](list(FIXTURE))
        self.assertIn("Restore point created", self.frame.status.text())
        self.assertIn("2 restore points", self.frame.status.text())

    def test_action_error_reports_detail(self):
        with patch.object(restore_point.widgets, "confirm",
                          return_value=True):
            self.frame._create()
        kwargs = self.fake_task.call_args.kwargs
        kwargs["on_error"](RuntimeError("rate limit reached"))
        self.assertIn("rate limit reached", self.frame.status.text())

    def test_load_error_clears_pending_success_prefix(self):
        self.frame._action_done("Restore point created.")
        self.frame._load_error(RuntimeError("boom"))
        self._load()
        self.assertEqual(self.frame.status.text(),
                         "2 restore points.")


if __name__ == "__main__":
    unittest.main()
