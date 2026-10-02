import json
from functools import partial
from tkinter import simpledialog, ttk

from power_tool.core import runner, tasks, widgets

USERS_SCRIPT = r"""
$users = @(Get-LocalUser | ForEach-Object {
  $u = $_
  $memberOf = @()
  foreach ($g in Get-LocalGroup) {
    try {
      Get-LocalGroupMember -Group $g.Name -Member $u.Name -ErrorAction Stop | Out-Null
      $memberOf += $g.Name
    } catch {}
  }
  [ordered]@{ name = $u.Name; full = $u.FullName; enabled = [bool]$u.Enabled; groups = @($memberOf) }
})
$allGroups = @(Get-LocalGroup | ForEach-Object { [ordered]@{ name = $_.Name } })
ConvertTo-Json -InputObject ([ordered]@{ users = $users; groups = $allGroups }) -Depth 5 -Compress
"""

PREFERRED_GROUPS = ("Administrators", "Users")


def parse_data(stdout: str) -> dict:
    try:
        data = json.loads(stdout)
    except ValueError as exc:
        raise ValueError(
            f"unexpected PowerShell output: {stdout[:200]}") from exc
    if not isinstance(data, dict) or "users" not in data:
        raise ValueError("users payload missing")
    if isinstance(data["users"], dict):
        data["users"] = [data["users"]]
    if not isinstance(data["users"], list):
        raise ValueError("users payload invalid")
    if not isinstance(data.get("groups"), list):
        data["groups"] = []
    return data


def add_to_group_script(user: str, group: str) -> str:
    return (f"Add-LocalGroupMember -Group {runner.ps_quote(group)} "
            f"-Member {runner.ps_quote(user)}")


def remove_from_group_script(user: str, group: str) -> str:
    return (f"Remove-LocalGroupMember -Group {runner.ps_quote(group)} "
            f"-Member {runner.ps_quote(user)}")


def enable_user_script(user: str) -> str:
    return f"Enable-LocalUser -Name {runner.ps_quote(user)}"


def disable_user_script(user: str) -> str:
    return f"Disable-LocalUser -Name {runner.ps_quote(user)}"


def reset_password_script(user: str, password: str) -> str:
    return (f"Set-LocalUser -Name {runner.ps_quote(user)} "
            f"-Password (ConvertTo-SecureString {runner.ps_quote(password)} "
            f"-AsPlainText -Force)")


def delete_user_script(user: str) -> str:
    return f"Remove-LocalUser -Name {runner.ps_quote(user)}"


def gather() -> dict:
    stdout = runner.run_powershell_checked(USERS_SCRIPT, timeout=120)
    return parse_data(stdout)


class UsersGroupsFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=16)
        ttk.Label(self, text="Users & Groups",
                  style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            self, wraplength=660, style="Dim.TLabel",
            text="Manage local accounts: group membership, password reset, "
                 "enable, disable and delete. Destructive actions ask for "
                 "confirmation first.",
        ).pack(anchor="w", pady=(6, 12))

        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 8))
        self._refresh_button = ttk.Button(
            top, text="Refresh", style="Accent.TButton",
            command=self._refresh)
        self._refresh_button.pack(side="left")

        tree_row = ttk.Frame(self)
        tree_row.pack(fill="both", expand=True)
        columns = ("name", "full", "enabled", "groups")
        self._tree = ttk.Treeview(tree_row, columns=columns,
                                  show="headings", height=12)
        headings = {"name": ("Name", 150), "full": ("Full name", 180),
                    "enabled": ("Enabled", 90), "groups": ("Groups", 300)}
        for key, (label, width) in headings.items():
            self._tree.heading(key, text=label)
            self._tree.column(key, width=width, anchor="w")
        scroll = ttk.Scrollbar(tree_row, orient="vertical",
                               command=self._tree.yview)
        self._tree.configure(yscrollcommand=scroll.set)
        self._tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        group_row = ttk.Frame(self)
        group_row.pack(anchor="w", pady=(10, 6))
        ttk.Label(group_row, text="Group:").pack(side="left")
        self._group_combo = ttk.Combobox(
            group_row, state="readonly", width=22,
            values=list(PREFERRED_GROUPS))
        self._group_combo.pack(side="left", padx=(6, 10))
        self._group_combo.set(PREFERRED_GROUPS[0])
        self._action_buttons = []
        for text, command in (
                ("Add to Group", self._add_to_group),
                ("Remove from Group", self._remove_from_group)):
            button = ttk.Button(group_row, text=text, command=command)
            button.pack(side="left", padx=(0, 6))
            self._action_buttons.append(button)

        account_row = ttk.Frame(self)
        account_row.pack(anchor="w", pady=(0, 6))
        for text, command in (
                ("Enable", self._enable),
                ("Disable", self._disable),
                ("Reset Password", self._reset_password),
                ("Delete", self._delete)):
            style = "Danger.TButton" if text in ("Disable", "Delete") else ""
            kwargs = {"style": style} if style else {}
            button = ttk.Button(account_row, text=text, command=command,
                                **kwargs)
            button.pack(side="left", padx=(0, 6))
            self._action_buttons.append(button)

        self.status = widgets.StatusPane(self)
        self.status.pack(fill="x", pady=(8, 0))

        self._users: list[dict] = []
        self._pending_success = ""
        self._refresh()

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self._refresh_button.configure(state=state)
        for button in self._action_buttons:
            button.configure(state=state)

    def _refresh(self) -> None:
        self._set_busy(True)
        self.status.set_working("Loading local users...")
        tasks.BackgroundTask(
            self, work=gather, on_done=self._load_done,
            on_error=self._load_error).start()

    def _load_done(self, data: dict) -> None:
        self._users = data["users"]
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        for index, user in enumerate(self._users):
            groups = ", ".join(user.get("groups") or []) or "-"
            enabled = "Yes" if user.get("enabled") else "No"
            self._tree.insert("", "end", iid=str(index), values=(
                user.get("name", ""), user.get("full", ""), enabled,
                groups))
        group_names = sorted({
            str(g.get("name", "")) for g in data["groups"]
            if g.get("name")})
        preferred = [g for g in PREFERRED_GROUPS if g in group_names]
        rest = [g for g in group_names if g not in preferred]
        values = preferred + rest
        self._group_combo.configure(values=values)
        if values and self._group_combo.get() not in values:
            self._group_combo.set(values[0])
        self._set_busy(False)
        prefix = ""
        if self._pending_success:
            prefix = f"{self._pending_success} "
            self._pending_success = ""
        self.status.set_success(
            f"{prefix}{len(self._users)} users, {len(values)} groups loaded.")

    def _load_error(self, exc: BaseException) -> None:
        self._set_busy(False)
        self.status.set_error(f"Loading users failed: {exc}")

    def _selected_user(self) -> str | None:
        selection = self._tree.selection()
        if not selection:
            return None
        return str(self._users[int(selection[0])]["name"])

    def _selected_group(self) -> str | None:
        value = self._group_combo.get().strip()
        return value or None

    def _start_action(self, script: str, success: str) -> None:
        if not widgets.guard_admin(self.status):
            return
        self._set_busy(True)
        self.status.set_working("Applying change...")
        tasks.BackgroundTask(
            self, work=partial(runner.run_powershell_checked, script, 60),
            on_done=lambda _: self._action_done(success),
            on_error=self._action_error).start()

    def _action_done(self, message: str) -> None:
        self._pending_success = message
        self._refresh()

    def _action_error(self, exc: BaseException) -> None:
        self._set_busy(False)
        self.status.set_error(f"Action failed: {exc}")

    def _need_user(self) -> str | None:
        user = self._selected_user()
        if user is None:
            self.status.set_warn("Select a user first.")
        return user

    def _add_to_group(self) -> None:
        user = self._need_user()
        if user is None:
            return
        group = self._selected_group()
        if group is None:
            self.status.set_warn("Pick a group first.")
            return
        self._start_action(add_to_group_script(user, group),
                           f"Added {user} to {group}.")

    def _remove_from_group(self) -> None:
        user = self._need_user()
        if user is None:
            return
        group = self._selected_group()
        if group is None:
            self.status.set_warn("Pick a group first.")
            return
        if not widgets.confirm(self, "Remove from group",
                               f"Remove {user} from {group}?"):
            self.status.set_idle("Cancelled.")
            return
        self._start_action(remove_from_group_script(user, group),
                           f"Removed {user} from {group}.")

    def _enable(self) -> None:
        user = self._need_user()
        if user is None:
            return
        self._start_action(enable_user_script(user),
                           f"Account {user} enabled.")

    def _disable(self) -> None:
        user = self._need_user()
        if user is None:
            return
        if not widgets.confirm(self, "Disable account",
                               f"Disable {user}? They will not be able "
                               "to sign in."):
            self.status.set_idle("Cancelled.")
            return
        self._start_action(disable_user_script(user),
                           f"Account {user} disabled.")

    def _reset_password(self) -> None:
        user = self._need_user()
        if user is None:
            return
        if not widgets.confirm(self, "Reset password",
                               f"Reset the password for {user}?"):
            self.status.set_idle("Cancelled.")
            return
        password = simpledialog.askstring(
            "Reset password", f"New password for {user}:", show="*",
            parent=self)
        if password is None:
            self.status.set_idle("Cancelled.")
            return
        if not password:
            self.status.set_error("Password must not be empty.")
            return
        self._start_action(reset_password_script(user, password),
                           f"Password reset for {user}.")

    def _delete(self) -> None:
        user = self._need_user()
        if user is None:
            return
        if not widgets.confirm(self, "Delete account",
                               f"Permanently delete the local account "
                               f"{user}? This cannot be undone."):
            self.status.set_idle("Cancelled.")
            return
        self._start_action(delete_user_script(user),
                           f"Account {user} deleted.")


def create(parent: ttk.Frame) -> ttk.Frame:
    return UsersGroupsFrame(parent)
