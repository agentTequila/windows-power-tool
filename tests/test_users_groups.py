import json
import unittest
from unittest.mock import patch

import tkinter as tk

from power_tool.core import theme
from power_tool.tools import users_groups

FIXTURE = {
    "users": [
        {"name": "admin", "full": "Local Admin", "enabled": True,
         "groups": ["Administrators"]},
        {"name": "bob", "full": "", "enabled": False,
         "groups": ["Users"]},
    ],
    "groups": [{"name": "Administrators"}, {"name": "Users"},
               {"name": "Remote Desktop Users"}],
}


class ParseDataTests(unittest.TestCase):
    def test_parses_fixture(self):
        data = users_groups.parse_data(json.dumps(FIXTURE))
        self.assertEqual(len(data["users"]), 2)
        self.assertEqual(data["groups"][2]["name"], "Remote Desktop Users")

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            users_groups.parse_data("noise not json")

    def test_missing_users_raises(self):
        with self.assertRaises(ValueError):
            users_groups.parse_data(json.dumps({"groups": []}))

    def test_wraps_single_user_dict_into_list(self):
        payload = {"users": {"name": "solo"}, "groups": []}
        data = users_groups.parse_data(json.dumps(payload))
        self.assertEqual(data["users"], [{"name": "solo"}])

    def test_missing_groups_defaults_to_empty(self):
        data = users_groups.parse_data(json.dumps({"users": []}))
        self.assertEqual(data["groups"], [])


class ScriptBuilderTests(unittest.TestCase):
    def test_add_to_group_script(self):
        self.assertEqual(
            users_groups.add_to_group_script("alice", "Administrators"),
            "Add-LocalGroupMember -Group 'Administrators' -Member 'alice'")

    def test_remove_from_group_escapes_quotes(self):
        self.assertEqual(
            users_groups.remove_from_group_script("o'neil", "Users"),
            "Remove-LocalGroupMember -Group 'Users' -Member 'o''neil'")

    def test_enable_user_script(self):
        self.assertEqual(users_groups.enable_user_script("alice"),
                         "Enable-LocalUser -Name 'alice'")

    def test_disable_user_script(self):
        self.assertEqual(users_groups.disable_user_script("alice"),
                         "Disable-LocalUser -Name 'alice'")

    def test_reset_password_script(self):
        self.assertEqual(
            users_groups.reset_password_script("admin", "p'w"),
            "Set-LocalUser -Name 'admin' -Password "
            "(ConvertTo-SecureString 'p''w' -AsPlainText -Force)")

    def test_delete_user_script(self):
        self.assertEqual(users_groups.delete_user_script("bob"),
                         "Remove-LocalUser -Name 'bob'")


class GatherTests(unittest.TestCase):
    @patch.object(users_groups.runner, "run_powershell_checked")
    def test_uses_checked_runner_and_parses(self, fake_checked):
        fake_checked.return_value = json.dumps(FIXTURE)
        data = users_groups.gather()
        self.assertEqual(len(data["users"]), 2)
        fake_checked.assert_called_once_with(
            users_groups.USERS_SCRIPT, timeout=120)

    @patch.object(users_groups.runner, "run_powershell_checked")
    def test_propagates_runner_failure(self, fake_checked):
        fake_checked.side_effect = RuntimeError("PowerShell failed: nope")
        with self.assertRaises(RuntimeError):
            users_groups.gather()


class UsersGroupsFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()
        theme.apply_theme(cls.root, "dark")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        task = patch.object(users_groups.tasks, "BackgroundTask")
        self.fake_task = task.start()
        self.addCleanup(task.stop)
        guard = patch.object(users_groups.widgets, "guard_admin",
                             return_value=True)
        guard.start()
        self.addCleanup(guard.stop)
        self.frame = users_groups.UsersGroupsFrame(self.root)
        self.fake_task.reset_mock()

    def _load(self, data=FIXTURE):
        self.frame._load_done(json.loads(json.dumps(data)))

    def test_frame_starts_with_refresh_task(self):
        self.fake_task.assert_not_called()
        frame = users_groups.UsersGroupsFrame(self.root)
        kwargs = self.fake_task.call_args.kwargs
        self.assertIs(kwargs["work"], users_groups.gather)

    def test_load_done_populates_tree_and_group_combo(self):
        self._load()
        self.assertEqual(len(self.frame._tree.get_children()), 2)
        raw = self.frame._group_combo.cget("values")
        self.assertIn("Administrators", raw)
        self.assertIn("Users", raw)
        self.assertIn("Remote Desktop Users", raw)
        self.assertEqual(self.frame._group_combo.get(), "Administrators")

    def test_add_without_selection_warns_no_task(self):
        self.frame._add_to_group()
        self.fake_task.assert_not_called()
        self.assertIn("Select a user first", self.frame.status.text())

    def test_add_without_group_warns(self):
        self._load()
        self.frame._tree.selection_set("0")
        self.frame._group_combo.set("")
        self.frame._add_to_group()
        self.fake_task.assert_not_called()
        self.assertIn("Pick a group", self.frame.status.text())

    def test_add_starts_task_with_expected_script(self):
        self._load()
        self.frame._tree.selection_set("0")
        self.frame._group_combo.set("Administrators")
        self.frame._add_to_group()
        self.fake_task.return_value.start.assert_called_once()
        work = self.fake_task.call_args.kwargs["work"]
        self.assertEqual(
            work.args[0],
            "Add-LocalGroupMember -Group 'Administrators' -Member 'admin'")

    def test_remove_cancelled_confirm_starts_no_task(self):
        self._load()
        self.frame._tree.selection_set("0")
        self.frame._group_combo.set("Administrators")
        with patch.object(users_groups.widgets, "confirm",
                          return_value=False):
            self.frame._remove_from_group()
        self.fake_task.assert_not_called()
        self.assertIn("Cancelled", self.frame.status.text())

    def test_remove_confirmed_starts_task(self):
        self._load()
        self.frame._tree.selection_set("0")
        self.frame._group_combo.set("Administrators")
        with patch.object(users_groups.widgets, "confirm",
                          return_value=True):
            self.frame._remove_from_group()
        work = self.fake_task.call_args.kwargs["work"]
        self.assertEqual(
            work.args[0],
            "Remove-LocalGroupMember -Group 'Administrators' "
            "-Member 'admin'")

    def test_reset_password_cancel_dialog_starts_no_task(self):
        self._load()
        self.frame._tree.selection_set("0")
        with patch.object(users_groups.widgets, "confirm",
                          return_value=True), \
             patch.object(users_groups.simpledialog, "askstring",
                          return_value=None):
            self.frame._reset_password()
        self.fake_task.assert_not_called()

    def test_reset_password_empty_rejected(self):
        self._load()
        self.frame._tree.selection_set("0")
        with patch.object(users_groups.widgets, "confirm",
                          return_value=True), \
             patch.object(users_groups.simpledialog, "askstring",
                          return_value=""):
            self.frame._reset_password()
        self.fake_task.assert_not_called()
        self.assertIn("empty", self.frame.status.text())

    def test_reset_password_uses_asked_password(self):
        self._load()
        self.frame._tree.selection_set("0")
        with patch.object(users_groups.widgets, "confirm",
                          return_value=True), \
             patch.object(users_groups.simpledialog, "askstring",
                          return_value="S3cret!"):
            self.frame._reset_password()
        work = self.fake_task.call_args.kwargs["work"]
        self.assertIn("ConvertTo-SecureString 'S3cret!' -AsPlainText -Force",
                      work.args[0])

    def test_delete_cancelled_confirm_starts_no_task(self):
        self._load()
        self.frame._tree.selection_set("1")
        with patch.object(users_groups.widgets, "confirm",
                          return_value=False):
            self.frame._delete()
        self.fake_task.assert_not_called()

    def test_delete_confirmed_starts_task(self):
        self._load()
        self.frame._tree.selection_set("1")
        with patch.object(users_groups.widgets, "confirm",
                          return_value=True):
            self.frame._delete()
        work = self.fake_task.call_args.kwargs["work"]
        self.assertEqual(work.args[0], "Remove-LocalUser -Name 'bob'")

    def test_action_done_reports_and_refreshes(self):
        self._load()
        self.frame._tree.selection_set("0")
        self.frame._group_combo.set("Administrators")
        self.frame._add_to_group()
        kwargs = self.fake_task.call_args.kwargs
        kwargs["on_done"](None)
        load_kwargs = self.fake_task.call_args.kwargs
        self.assertEqual(load_kwargs["work"], users_groups.gather)
        load_kwargs["on_done"](json.loads(json.dumps(FIXTURE)))
        self.assertIn("Added admin to Administrators",
                      self.frame.status.text())

    def test_action_error_reports_detail(self):
        self._load()
        self.frame._tree.selection_set("0")
        self.frame._group_combo.set("Administrators")
        self.frame._add_to_group()
        kwargs = self.fake_task.call_args.kwargs
        kwargs["on_error"](RuntimeError("Access denied"))
        self.assertIn("Access denied", self.frame.status.text())


if __name__ == "__main__":
    unittest.main()
