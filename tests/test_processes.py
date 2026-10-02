import json
import unittest
from unittest.mock import patch

import tkinter as tk

from power_tool.core import theme, widgets
from power_tool.tools import processes

REAL_GUARD_ADMIN = widgets.guard_admin

FIXTURE = [
    {"name": "chrome", "pid": 100, "cpu": 1.5, "ram": 52428800,
     "path": "C:\\Program Files\\Chrome\\chrome.exe"},
    {"name": "notepad", "pid": 200, "cpu": 0.0, "ram": 20971520, "path": ""},
]


class ParseProcessesTests(unittest.TestCase):
    def test_parses_list(self):
        items = processes.parse_processes(json.dumps(FIXTURE))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["pid"], 100)

    def test_single_dict_wrapped_into_list(self):
        items = processes.parse_processes(json.dumps(FIXTURE[0]))
        self.assertEqual(items[0]["name"], "chrome")

    def test_null_returns_empty(self):
        self.assertEqual(processes.parse_processes("null"), [])

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            processes.parse_processes("not json")

    def test_non_dict_list_raises(self):
        with self.assertRaises(ValueError):
            processes.parse_processes("[1, 2, 3]")


class FormatRamTests(unittest.TestCase):
    def test_formats_mb(self):
        self.assertEqual(processes.format_ram(52428800), "50.0 MB")

    def test_zero_and_garbage(self):
        self.assertEqual(processes.format_ram(0), "0.0 MB")
        self.assertEqual(processes.format_ram(None), "0.0 MB")
        self.assertEqual(processes.format_ram("abc"), "0 MB")


class FilterProcessesTests(unittest.TestCase):
    def test_empty_returns_all(self):
        self.assertEqual(processes.filter_processes(FIXTURE, " "), FIXTURE)

    def test_matches_name_case_insensitive(self):
        result = processes.filter_processes(FIXTURE, "NOTE")
        self.assertEqual([p["name"] for p in result], ["notepad"])

    def test_matches_path(self):
        result = processes.filter_processes(FIXTURE, "program files")
        self.assertEqual([p["name"] for p in result], ["chrome"])


class EndProcessScriptTests(unittest.TestCase):
    def test_builds_command(self):
        self.assertEqual(processes.end_process_script(100),
                         "Stop-Process -Id 100 -Force")

    def test_non_int_raises(self):
        with self.assertRaises(ValueError):
            processes.end_process_script("chrome; Remove-Item x")


class GatherTests(unittest.TestCase):
    @patch.object(processes.runner, "run_powershell_checked")
    def test_uses_checked_runner(self, fake_checked):
        fake_checked.return_value = json.dumps(FIXTURE)
        items = processes.gather()
        self.assertEqual(len(items), 2)
        fake_checked.assert_called_once_with(
            processes.LIST_SCRIPT, timeout=120)


class ProcessesFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()
        theme.apply_theme(cls.root, "dark")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        task = patch.object(processes.tasks, "BackgroundTask")
        self.fake_task = task.start()
        self.addCleanup(task.stop)
        guard = patch.object(processes.widgets, "guard_admin",
                             return_value=True)
        guard.start()
        self.addCleanup(guard.stop)
        self.frame = processes.ProcessesFrame(self.root)
        self.fake_task.reset_mock()

    def _load(self, items=FIXTURE):
        self.frame._load_done(list(items))

    def test_load_done_populates_tree(self):
        self._load()
        self.assertEqual(len(self.frame._tree.get_children()), 2)

    def test_refresh_button_starts_task(self):
        self._load()
        self.frame._refresh_button.invoke()
        kwargs = self.fake_task.call_args.kwargs
        self.assertIs(kwargs["work"], processes.gather)

    def test_search_filters_live(self):
        self._load()
        self.frame._query.set("note")
        self.assertEqual(len(self.frame._tree.get_children()), 1)
        self.assertEqual(self.frame._visible[0]["name"], "notepad")

    def test_end_without_selection_warns(self):
        with patch.object(processes.widgets, "confirm",
                          return_value=True):
            self.frame._end_process()
        self.fake_task.assert_not_called()
        self.assertIn("Select a process first", self.frame.status.text())

    def test_end_cancelled_confirm_starts_no_task(self):
        self._load()
        self.frame._tree.selection_set("0")
        with patch.object(processes.widgets, "confirm",
                          return_value=False):
            self.frame._end_process()
        self.fake_task.assert_not_called()
        self.assertIn("Cancelled", self.frame.status.text())

    def test_end_confirmed_starts_task_with_script(self):
        self._load()
        self.frame._tree.selection_set("0")
        with patch.object(processes.widgets, "confirm",
                          return_value=True):
            self.frame._end_process()
        work = self.fake_task.call_args.kwargs["work"]
        self.assertEqual(work.args[0], "Stop-Process -Id 100 -Force")

    def test_action_done_reports_and_refreshes(self):
        self._load()
        self.frame._tree.selection_set("0")
        with patch.object(processes.widgets, "confirm",
                          return_value=True):
            self.frame._end_process()
        kwargs = self.fake_task.call_args.kwargs
        kwargs["on_done"](None)
        load_kwargs = self.fake_task.call_args.kwargs
        load_kwargs["on_done"](list(FIXTURE))
        self.assertIn("Process 100 ended", self.frame.status.text())

    def test_action_error_reports_detail(self):
        self._load()
        self.frame._tree.selection_set("0")
        with patch.object(processes.widgets, "confirm",
                          return_value=True):
            self.frame._end_process()
        kwargs = self.fake_task.call_args.kwargs
        kwargs["on_error"](RuntimeError("Access is denied"))
        self.assertIn("Access is denied", self.frame.status.text())

    def test_load_error_clears_pending_success_prefix(self):
        self.frame._action_done("Process 100 ended.")
        self.frame._load_error(RuntimeError("boom"))
        self._load()
        self.assertEqual(self.frame.status.text(), "2 processes running.")

    def test_clearing_search_restores_total_count_status(self):
        self._load()
        self.frame._query.set("note")
        self.assertEqual(self.frame.status.text(), "1 of 2 match")
        self.frame._query.set("")
        self.assertEqual(self.frame.status.text(), "2 processes running.")

    def test_refresh_disables_buttons_and_error_reenables(self):
        self.frame._refresh()
        self.assertEqual(
            str(self.frame._refresh_button.cget("state")), "disabled")
        self.assertEqual(str(self.frame._end_button.cget("state")),
                         "disabled")
        kwargs = self.fake_task.call_args.kwargs
        kwargs["on_error"](RuntimeError("boom"))
        self.assertEqual(
            str(self.frame._refresh_button.cget("state")), "normal")
        self.assertEqual(str(self.frame._end_button.cget("state")),
                         "normal")
        self.assertIn("boom", self.frame.status.text())
        self.assertEqual(str(self.frame.status._label.cget("style")),
                         "Error.TLabel")

    def test_action_guarded_requires_admin(self):
        self._load()
        self.frame._tree.selection_set("0")
        with patch.object(processes.widgets, "guard_admin",
                          REAL_GUARD_ADMIN), \
             patch("power_tool.core.admin.is_admin", return_value=False), \
             patch.object(processes.widgets, "confirm", return_value=True):
            self.frame._end_process()
        self.fake_task.assert_not_called()
        self.assertIn("Run as administrator required",
                      self.frame.status.text())


if __name__ == "__main__":
    unittest.main()
