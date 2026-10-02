import json
import tkinter as tk
from functools import partial
from tkinter import ttk

from power_tool.core import runner, tasks, widgets

LIST_SCRIPT = r"""
$items = @(Get-Service | ForEach-Object {
  [ordered]@{ name = $_.Name; display = $_.DisplayName; status = [string]$_.Status; start = [string]$_.StartType }
})
ConvertTo-Json -InputObject $items -Depth 3 -Compress
"""

STARTUP_CHOICES = ("Automatic", "Manual", "Disabled")


def parse_services(stdout: str) -> list[dict]:
    try:
        data = json.loads(stdout)
    except ValueError as exc:
        raise ValueError(
            f"unexpected PowerShell output: {stdout[:200]}") from exc
    if data is None:
        return []
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not all(
            isinstance(item, dict) for item in data):
        raise ValueError("service payload invalid")
    return data


def filter_services(items: list[dict], query: str) -> list[dict]:
    cleaned = str(query or "").strip().lower()
    if not cleaned:
        return list(items)
    return [item for item in items
            if cleaned in str(item.get("name", "")).lower()
            or cleaned in str(item.get("display", "")).lower()]


def start_script(name: str) -> str:
    return f"Start-Service -Name {runner.ps_quote(name)}"


def stop_script(name: str) -> str:
    return f"Stop-Service -Name {runner.ps_quote(name)}"


def restart_script(name: str) -> str:
    return f"Restart-Service -Name {runner.ps_quote(name)}"


def set_startup_script(name: str, startup: str) -> str:
    if startup not in STARTUP_CHOICES:
        raise ValueError(f"unknown startup type: {startup}")
    return (f"Set-Service -Name {runner.ps_quote(name)} "
            f"-StartupType {startup}")


def gather() -> list[dict]:
    stdout = runner.run_powershell_checked(LIST_SCRIPT, timeout=120)
    return parse_services(stdout)


class ServicesFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=16)
        ttk.Label(self, text="Services", style="Title.TLabel").pack(
            anchor="w")
        ttk.Label(
            self, wraplength=660, style="Dim.TLabel",
            text="Local Windows services with status and startup type. "
                 "Start, Stop, Restart and startup changes ask for "
                 "confirmation first.",
        ).pack(anchor="w", pady=(6, 12))

        search_row = ttk.Frame(self)
        search_row.pack(fill="x", pady=(0, 8))
        ttk.Label(search_row, text="Search:").pack(side="left")
        self._query = tk.StringVar()
        self._query.trace_add("write", lambda *_: self._refilter())
        ttk.Entry(search_row, textvariable=self._query,
                  width=40).pack(side="left", padx=8)

        tree_row = ttk.Frame(self)
        tree_row.pack(fill="both", expand=True)
        columns = ("name", "display", "status", "start")
        self._tree = ttk.Treeview(tree_row, columns=columns,
                                  show="headings", height=13)
        headings = {"name": ("Name", 170), "display": ("Display name", 260),
                    "status": ("Status", 110), "start": ("Startup", 130)}
        for key, (label, width) in headings.items():
            self._tree.heading(key, text=label)
            self._tree.column(key, width=width, anchor="w")
        scroll = ttk.Scrollbar(tree_row, orient="vertical",
                               command=self._tree.yview)
        self._tree.configure(yscrollcommand=scroll.set)
        self._tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        buttons = ttk.Frame(self)
        buttons.pack(anchor="w", pady=(10, 0))
        self._action_buttons = []
        for text, command in (("Start", self._start),
                              ("Stop", self._stop),
                              ("Restart", self._restart)):
            button = ttk.Button(buttons, text=text, command=command)
            button.pack(side="left", padx=(0, 6))
            self._action_buttons.append(button)
        self._refresh_button = ttk.Button(
            buttons, text="Refresh", style="Accent.TButton",
            command=self._refresh)
        self._refresh_button.pack(side="left", padx=(10, 0))

        startup_row = ttk.Frame(self)
        startup_row.pack(anchor="w", pady=(8, 0))
        ttk.Label(startup_row, text="Startup type:").pack(side="left")
        self._startup_combo = ttk.Combobox(
            startup_row, state="readonly", width=16,
            values=list(STARTUP_CHOICES))
        self._startup_combo.set(STARTUP_CHOICES[0])
        self._startup_combo.pack(side="left", padx=6)
        self._apply_button = ttk.Button(
            startup_row, text="Apply", command=self._apply_startup)
        self._apply_button.pack(side="left")
        self._action_buttons.append(self._apply_button)

        self.status = widgets.StatusPane(self)
        self.status.pack(fill="x", pady=(10, 0))

        self._all: list[dict] = []
        self._visible: list[dict] = []
        self._pending_success = ""
        self._refresh()

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for button in self._action_buttons:
            button.configure(state=state)
        self._refresh_button.configure(state=state)

    def _refresh(self) -> None:
        self._set_busy(True)
        self.status.set_working("Loading services...")
        tasks.BackgroundTask(
            self, work=gather, on_done=self._load_done,
            on_error=self._load_error).start()

    def _load_done(self, items: list[dict]) -> None:
        self._all = items
        self._set_busy(False)
        self._refilter()
        prefix = ""
        if self._pending_success:
            prefix = f"{self._pending_success} "
            self._pending_success = ""
        self.status.set_success(
            f"{prefix}{len(self._all)} services loaded.")

    def _load_error(self, exc: BaseException) -> None:
        self._set_busy(False)
        self._pending_success = None
        self.status.set_error(f"Loading services failed: {exc}")

    def _refilter(self) -> None:
        self._visible = filter_services(self._all, self._query.get())
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        for index, item in enumerate(self._visible):
            self._tree.insert("", "end", iid=str(index), values=(
                item.get("name", ""), item.get("display", ""),
                item.get("status", ""), item.get("start", "")))
        if self._query.get().strip():
            self.status.set_idle(
                f"{len(self._visible)} of {len(self._all)} match")
        else:
            self.status.set_success(f"{len(self._all)} services loaded.")

    def _selected_name(self) -> str | None:
        selection = self._tree.selection()
        if not selection:
            return None
        return str(self._visible[int(selection[0])].get("name", ""))

    def _need_selection(self) -> str | None:
        name = self._selected_name()
        if not name:
            self.status.set_warn("Select a service first.")
        return name

    def _run_action(self, script: str, action_title: str,
                    confirm_message: str, success: str) -> None:
        name = self._need_selection()
        if name is None:
            return
        if not widgets.guard_admin(self.status):
            return
        if not widgets.confirm(self, action_title, confirm_message):
            self.status.set_idle("Cancelled.")
            return
        self._set_busy(True)
        self.status.set_working(f"{action_title}...")
        tasks.BackgroundTask(
            self, work=partial(runner.run_powershell_checked, script, 60),
            on_done=lambda _: self._action_done(success),
            on_error=self._action_error).start()

    def _action_done(self, message: str) -> None:
        self._pending_success = message
        self._refresh()

    def _action_error(self, exc: BaseException) -> None:
        self._set_busy(False)
        self.status.set_error(f"Service action failed: {exc}")

    def _start(self) -> None:
        name = self._selected_name()
        if not name:
            self.status.set_warn("Select a service first.")
            return
        self._run_action(start_script(name), "Start",
                         f"Start service {name}?",
                         f"{name} started.")

    def _stop(self) -> None:
        name = self._selected_name()
        if not name:
            self.status.set_warn("Select a service first.")
            return
        self._run_action(stop_script(name), "Stop",
                         f"Stop service {name}?", f"{name} stopped.")

    def _restart(self) -> None:
        name = self._selected_name()
        if not name:
            self.status.set_warn("Select a service first.")
            return
        self._run_action(restart_script(name), "Restart",
                         f"Restart service {name}?",
                         f"{name} restarted.")

    def _apply_startup(self) -> None:
        name = self._selected_name()
        if not name:
            self.status.set_warn("Select a service first.")
            return
        startup = self._startup_combo.get()
        try:
            script = set_startup_script(name, startup)
        except ValueError as exc:
            self.status.set_error(str(exc))
            return
        self._run_action(script, "Change startup type",
                         f"Change {name} startup type to {startup}?",
                         f"{name} startup set to {startup}.")


def create(parent: ttk.Frame) -> ttk.Frame:
    return ServicesFrame(parent)
