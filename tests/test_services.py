import json
import unittest
from unittest.mock import patch

import tkinter as tk

from power_tool.core import theme
from power_tool.tools import services

FIXTURE = [
    {"name": "Spooler", "display": "Print Spooler", "status": "Running",
     "start": "Automatic"},
    {"name": "wuauserv", "display": "Windows Update", "status": "Stopped",
     "start": "Manual"},
]


class ParseServicesTests(unittest.TestCase):
    def test_parses_list(self):
        items = services.parse_services(json.dumps(FIXTURE))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["name"], "Spooler")

    def test_single_dict_wrapped(self):
        items = services.parse_services(json.dumps(FIXTURE[0]))
        self.assertEqual(items[0]["display"], "Print Spooler")

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            services.parse_services("nope")

    def test_non_dict_list_raises(self):
        with self.assertRaises(ValueError):
            services.parse_services('["a"]')


class FilterServicesTests(unittest.TestCase):
    def test_empty_returns_all(self):
        self.assertEqual(services.filter_services(FIXTURE, ""), FIXTURE)

    def test_matches_name(self):
        result = services.filter_services(FIXTURE, "spool")
        self.assertEqual([s["name"] for s in result], ["Spooler"])

    def test_matches_display_case_insensitive(self):
        result = services.filter_services(FIXTURE, "WINDOWS UPDATE")
        self.assertEqual([s["name"] for s in result], ["wuauserv"])


class ScriptTests(unittest.TestCase):
    def test_start_script(self):
        self.assertEqual(services.start_script("Spooler"),
                         "Start-Service -Name 'Spooler'")

    def test_stop_script(self):
        self.assertEqual(services.stop_script("Spooler"),
                         "Stop-Service -Name 'Spooler'")

    def test_restart_script(self):
        self.assertEqual(services.restart_script("Spooler"),
                         "Restart-Service -Name 'Spooler'")

    def test_set_startup_script(self):
        self.assertEqual(
            services.set_startup_script("wuauserv", "Disabled"),
            "Set-Service -Name 'wuauserv' -StartupType Disabled")

    def test_set_startup_rejects_unknown_value(self):
        with self.assertRaises(ValueError):
            services.set_startup_script("x", "Boot")

    def test_script_escapes_quotes(self):
        self.assertEqual(services.start_script("o'b"),
                         "Start-Service -Name 'o''b'")


class GatherTests(unittest.TestCase):
    @patch.object(services.runner, "run_powershell_checked")
    def test_uses_checked_runner(self, fake_checked):
        fake_checked.return_value = json.dumps(FIXTURE)
        items = services.gather()
        self.assertEqual(len(items), 2)
        fake_checked.assert_called_once_with(
            services.LIST_SCRIPT, timeout=120)


class ServicesFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()
        theme.apply_theme(cls.root, "dark")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        task = patch.object(services.tasks, "BackgroundTask")
        self.fake_task = task.start()
        self.addCleanup(task.stop)
        guard = patch.object(services.widgets, "guard_admin",
                             return_value=True)
        guard.start()
        self.addCleanup(guard.stop)
        self.frame = services.ServicesFrame(self.root)
        self.fake_task.reset_mock()

    def _load(self, items=FIXTURE):
        self.frame._load_done(list(items))

    def test_load_done_populates_tree(self):
        self._load()
        self.assertEqual(len(self.frame._tree.get_children()), 2)

    def test_search_filters_live(self):
        self._load()
        self.frame._query.set("update")
        self.assertEqual(len(self.frame._tree.get_children()), 1)

    def test_action_without_selection_warns(self):
        with patch.object(services.widgets, "confirm",
                          return_value=True):
            self.frame._stop()
        self.fake_task.assert_not_called()
        self.assertIn("Select a service first", self.frame.status.text())

    def test_stop_cancelled_confirm_starts_no_task(self):
        self._load()
        self.frame._tree.selection_set("0")
        with patch.object(services.widgets, "confirm",
                          return_value=False):
            self.frame._stop()
        self.fake_task.assert_not_called()

    def test_start_confirmed_starts_task_with_script(self):
        self._load()
        self.frame._tree.selection_set("0")
        with patch.object(services.widgets, "confirm",
                          return_value=True):
            self.frame._start()
        work = self.fake_task.call_args.kwargs["work"]
        self.assertEqual(work.args[0], "Start-Service -Name 'Spooler'")

    def test_stop_confirmed_starts_task_with_script(self):
        self._load()
        self.frame._tree.selection_set("0")
        with patch.object(services.widgets, "confirm",
                          return_value=True):
            self.frame._stop()
        work = self.fake_task.call_args.kwargs["work"]
        self.assertEqual(work.args[0], "Stop-Service -Name 'Spooler'")

    def test_restart_confirmed_starts_task_with_script(self):
        self._load()
        self.frame._tree.selection_set("1")
        with patch.object(services.widgets, "confirm",
                          return_value=True):
            self.frame._restart()
        work = self.fake_task.call_args.kwargs["work"]
        self.assertEqual(work.args[0],
                         "Restart-Service -Name 'wuauserv'")

    def test_apply_startup_confirmed_starts_task(self):
        self._load()
        self.frame._tree.selection_set("1")
        self.frame._startup_combo.set("Disabled")
        with patch.object(services.widgets, "confirm",
                          return_value=True):
            self.frame._apply_startup()
        work = self.fake_task.call_args.kwargs["work"]
        self.assertEqual(
            work.args[0],
            "Set-Service -Name 'wuauserv' -StartupType Disabled")

    def test_action_done_reports_and_refreshes(self):
        self._load()
        self.frame._tree.selection_set("0")
        with patch.object(services.widgets, "confirm",
                          return_value=True):
            self.frame._stop()
        kwargs = self.fake_task.call_args.kwargs
        kwargs["on_done"](None)
        load_kwargs = self.fake_task.call_args.kwargs
        load_kwargs["on_done"](list(FIXTURE))
        self.assertIn("Spooler stopped", self.frame.status.text())

    def test_action_error_reports_detail(self):
        self._load()
        self.frame._tree.selection_set("0")
        with patch.object(services.widgets, "confirm",
                          return_value=True):
            self.frame._stop()
        kwargs = self.fake_task.call_args.kwargs
        kwargs["on_error"](RuntimeError("Cannot open service"))
        self.assertIn("Cannot open service", self.frame.status.text())


if __name__ == "__main__":
    unittest.main()
