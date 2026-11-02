import json
import unittest
from unittest.mock import patch

import tkinter as tk

from power_tool.core import theme, widgets
from power_tool.tools import users_groups

REAL_GUARD_ADMIN = widgets.guard_admin

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


class ValidateUsernameTests(unittest.TestCase):
    def test_valid_simple(self):
        self.assertIsNone(users_groups.validate_username("bob123"))

    def test_valid_display_name(self):
        self.assertIsNone(users_groups.validate_username("John Doe"))

    def test_empty(self):
        message = users_groups.validate_username("")
        self.assertIn("Username", message)

    def test_too_long(self):
        message = users_groups.validate_username("a" * 21)
        self.assertIn("Username", message)

    def test_bad_char(self):
        message = users_groups.validate_username("bob@home")
        self.assertIn("Username", message)

    def test_leading_dot(self):
        message = users_groups.validate_username(".bob")
        self.assertIn("Username", message)

    def test_whitespace_stripped(self):
        self.assertIsNone(users_groups.validate_username("  bob  "))


class ValidatePasswordTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(
            users_groups.validate_password("", ""),
            "Password must not be empty.")

    def test_mismatch(self):
        self.assertEqual(
            users_groups.validate_password("secret1", "secret2"),
            "Passwords do not match.")

    def test_ok(self):
        self.assertIsNone(
            users_groups.validate_password("secret1", "secret1"))


class AddUserScriptsTests(unittest.TestCase):
    def test_single_script_no_admin(self):
        scripts = users_groups.add_user_scripts("bob", "s3cret", False)
        self.assertEqual(len(scripts), 1)
        self.assertIn("New-LocalUser -Name 'bob'", scripts[0])
        self.assertIn("-AsPlainText -Force", scripts[0])
        self.assertIn("-AccountNeverExpires", scripts[0])
        self.assertIn("'s3cret'", scripts[0])

    def test_admin_script_appended(self):
        scripts = users_groups.add_user_scripts("bob", "s3cret", True)
        self.assertEqual(len(scripts), 2)
        self.assertIn("Add-LocalGroupMember -Group 'Administrators' "
                      "-Member 'bob'", scripts[1])

    def test_password_with_quote_is_escaped(self):
        scripts = users_groups.add_user_scripts("bob", "it's", False)
        self.assertIn("'it''s'", scripts[0])


class AddUserDisplayTests(unittest.TestCase):
    def test_masks_and_matches_shape(self):
        lines = users_groups.add_user_display("bob", True)
        self.assertEqual(len(lines), 2)
        self.assertIn("****", lines[0])
        self.assertNotIn("Password (ConvertTo-SecureString '",
                         lines[0])  # no real key material
        self.assertIn("New-LocalUser -Name 'bob'", lines[0])

    def test_display_is_the_script_shape_with_the_password_masked(self):
        scripts = users_groups.add_user_scripts("bob", "s3cret", True)
        display = users_groups.add_user_display("bob", True)
        self.assertEqual(
            display,
            [script.replace("'s3cret'", "****") for script in scripts])


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

    def test_load_error_clears_pending_success_prefix(self):
        self.frame._action_done("Added admin to Administrators.")
        self.frame._load_error(RuntimeError("boom"))
        self._load()
        self.assertEqual(self.frame.status.text(),
                         "2 users, 3 groups loaded.")

    def test_load_done_reenables_before_populating_tree(self):
        self._load()
        calls = []
        real_set_busy = self.frame._set_busy
        real_delete = self.frame._tree.delete
        real_insert = self.frame._tree.insert

        def set_busy(busy):
            calls.append("set_busy")
            real_set_busy(busy)

        def delete(iid):
            calls.append("delete")
            return real_delete(iid)

        def insert(*args, **kwargs):
            calls.append("insert")
            return real_insert(*args, **kwargs)

        self.frame._set_busy = set_busy
        self.frame._tree.delete = delete
        self.frame._tree.insert = insert
        self._load()
        self.assertEqual(calls[0], "set_busy")

    def test_load_done_null_full_name_renders_blank(self):
        data = json.loads(json.dumps(FIXTURE))
        data["users"][0]["full"] = None
        self._load(data)
        values = self.frame._tree.item("0", "values")
        self.assertEqual(values[1], "")

    def test_refresh_disables_buttons_and_error_reenables(self):
        self.frame._refresh()
        self.assertEqual(
            str(self.frame._refresh_button.cget("state")), "disabled")
        for button in self.frame._action_buttons:
            self.assertEqual(str(button.cget("state")), "disabled")
        kwargs = self.fake_task.call_args.kwargs
        kwargs["on_error"](RuntimeError("boom"))
        self.assertEqual(
            str(self.frame._refresh_button.cget("state")), "normal")
        for button in self.frame._action_buttons:
            self.assertEqual(str(button.cget("state")), "normal")
        self.assertIn("boom", self.frame.status.text())
        self.assertEqual(str(self.frame.status._label.cget("style")),
                         "Error.TLabel")

    def test_action_guarded_requires_admin(self):
        self._load()
        self.frame._tree.selection_set("0")
        self.frame._group_combo.set("Administrators")
        with patch.object(users_groups.widgets, "guard_admin",
                          REAL_GUARD_ADMIN), \
             patch("power_tool.core.admin.is_admin", return_value=False):
            self.frame._add_to_group()
        self.fake_task.assert_not_called()
        self.assertIn("Run as administrator required",
                      self.frame.status.text())


class AddUserFlowTests(unittest.TestCase):
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

    def _prompts(self, name="bob", password="s3cret", confirm="s3cret"):
        return patch.object(
            users_groups.simpledialog, "askstring",
            side_effect=[name, password, confirm])

    def test_username_cancel_no_guard(self):
        with patch.object(users_groups.widgets, "guard_admin") as fake_guard, \
             patch.object(users_groups.simpledialog, "askstring",
                          return_value=None), \
             patch.object(users_groups.widgets, "confirm") as fake_confirm:
            self.frame._add_user()
        fake_guard.assert_not_called()
        fake_confirm.assert_not_called()
        self.fake_task.assert_not_called()
        self.assertIn("Cancelled", self.frame.status.text())

    def test_invalid_username_reports_error_no_task(self):
        with patch.object(users_groups.simpledialog, "askstring",
                          return_value="bob@x"):
            self.frame._add_user()
        self.fake_task.assert_not_called()
        self.assertIn("Username", self.frame.status.text())

    def test_password_mismatch_reports_error_no_task(self):
        with self._prompts(password="secret1", confirm="secret2"):
            self.frame._add_user()
        self.fake_task.assert_not_called()
        self.assertIn("do not match", self.frame.status.text())

    def test_not_admin_never_reaches_confirm(self):
        with patch.object(users_groups.widgets, "guard_admin",
                          REAL_GUARD_ADMIN), \
             patch("power_tool.core.admin.is_admin", return_value=False), \
             self._prompts(), \
             patch.object(users_groups.messagebox, "askyesno",
                          return_value=True), \
             patch.object(users_groups.widgets, "confirm") as fake_confirm:
            self.frame._add_user()
        fake_confirm.assert_not_called()
        self.fake_task.assert_not_called()
        self.assertIn("Run as administrator required",
                      self.frame.status.text())

    def test_confirm_cancelled_no_task(self):
        with self._prompts(), \
             patch.object(users_groups.messagebox, "askyesno",
                          return_value=True), \
             patch.object(users_groups.widgets, "confirm",
                          return_value=False):
            self.frame._add_user()
        self.fake_task.assert_not_called()
        self.assertIn("Cancelled", self.frame.status.text())

    def test_confirmed_runs_scripts_and_refreshes(self):
        with self._prompts(), \
             patch.object(users_groups.messagebox, "askyesno",
                          return_value=True), \
             patch.object(users_groups.widgets, "confirm",
                          return_value=True):
            self.frame._add_user()
        self.fake_task.return_value.start.assert_called_once()
        kwargs = self.fake_task.call_args.kwargs
        with patch.object(users_groups.runner,
                          "run_powershell_checked") as fake_checked:
            kwargs["work"]()
        expected = users_groups.add_user_scripts("bob", "s3cret", True)
        self.assertEqual([c.args for c in fake_checked.call_args_list],
                         [(s, 60) for s in expected])
        kwargs["on_done"](None)
        load_kwargs = self.fake_task.call_args.kwargs
        self.assertEqual(load_kwargs["work"], users_groups.gather)
        load_kwargs["on_done"](json.loads(json.dumps(FIXTURE)))
        self.assertIn("User 'bob' created", self.frame.status.text())

    def test_confirm_message_masks_password(self):
        with self._prompts(), \
             patch.object(users_groups.messagebox, "askyesno",
                          return_value=True), \
             patch.object(users_groups.widgets, "confirm",
                          return_value=True) as fake_confirm:
            self.frame._add_user()
        message = fake_confirm.call_args.args[2]
        self.assertNotIn("s3cret", message)
        self.assertIn("****", message)
        self.assertIn("New-LocalUser -Name 'bob'", message)

    def test_admin_choice_false_still_creates_without_admin_script(self):
        with self._prompts(), \
             patch.object(users_groups.messagebox, "askyesno",
                          return_value=False), \
             patch.object(users_groups.widgets, "confirm",
                          return_value=True), \
             patch.object(users_groups, "run_scripts") as fake_run:
            self.frame._add_user()
        work = self.fake_task.call_args.kwargs["work"]
        work()
        fake_run.assert_called_once()
        scripts = fake_run.call_args.args[0]
        self.assertEqual(len(scripts), 1)
        self.assertIn("New-LocalUser -Name 'bob'", scripts[0])

    @patch.object(users_groups.runner, "run_powershell_checked")
    def test_run_scripts_stops_at_first_failure(self, fake_checked):
        fake_checked.side_effect = [RuntimeError("boom"), "unreachable"]
        with self.assertRaises(RuntimeError):
            users_groups.run_scripts(["one", "two"])
        fake_checked.assert_called_once_with("one", 60)

    def test_start_action_accepts_list(self):
        with patch.object(users_groups, "run_scripts") as fake_run:
            self.frame._start_action(["a", "b"], "Done.")
            work = self.fake_task.call_args.kwargs["work"]
            work()
        self.fake_task.return_value.start.assert_called_once()
        fake_run.assert_called_once_with(["a", "b"])

    def test_add_user_button_busy_coverage(self):
        button = self.frame._add_user_button
        self.assertEqual(str(button.cget("text")), "Add User")
        self.assertIn(button, self.frame._action_buttons)
        self.frame._set_busy(True)
        self.assertEqual(str(button.cget("state")), "disabled")
        self.frame._set_busy(False)
        self.assertEqual(str(button.cget("state")), "normal")

    def test_every_prompt_is_parented_to_the_tool(self):
        with patch.object(users_groups.simpledialog, "askstring",
                          side_effect=["bob", "s3cret", "s3cret"]) as fake_ask, \
             patch.object(users_groups.messagebox, "askyesno",
                          return_value=True) as fake_admin, \
             patch.object(users_groups.widgets, "confirm",
                          return_value=False):
            self.frame._add_user()
        self.assertEqual(fake_ask.call_count, 3)
        for call in fake_ask.call_args_list:
            self.assertIs(call.kwargs.get("parent"), self.frame)
        self.assertIs(fake_admin.call_args.kwargs.get("parent"), self.frame)

    def test_failure_redacts_password_from_status(self):
        with self._prompts(), \
             patch.object(users_groups.messagebox, "askyesno",
                          return_value=True), \
             patch.object(users_groups.widgets, "confirm",
                          return_value=True):
            self.frame._add_user()
        on_error = self.fake_task.call_args.kwargs["on_error"]
        on_error(RuntimeError("New-LocalUser failed near 's3cret'"))
        self.assertNotIn("s3cret", self.frame.status.text())
        self.assertIn("****", self.frame.status.text())
        self.assertIn("Adding user failed", self.frame.status.text())
        self.assertEqual(str(self.frame.status._label.cget("style")),
                         "Error.TLabel")


if __name__ == "__main__":
    unittest.main()
