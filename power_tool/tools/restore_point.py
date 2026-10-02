import json
from datetime import datetime
from functools import partial
from tkinter import ttk

from power_tool.core import runner, tasks, widgets

LIST_SCRIPT = r"""
$items = @(Get-ComputerRestorePoint -ErrorAction Stop | Sort-Object SequenceNumber -Descending | ForEach-Object {
  $c = $_.CreationTime
  if ($c -is [datetime]) { $created = $c.ToString('yyyy-MM-dd HH:mm:ss') } else { $created = [string]$c }
  [ordered]@{ sequence = [int]$_.SequenceNumber; description = [string]$_.Description; created = $created; type = [string]$_.RestorePointType; event = [string]$_.EventType }
})
ConvertTo-Json -InputObject $items -Depth 3 -Compress
"""

_RESTORE_TYPE = {
    0: "APPLICATION_INSTALL",
    1: "APPLICATION_UNINSTALL",
    12: "MODIFY_SETTINGS",
}


def parse_restore_points(stdout: str) -> list[dict]:
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
        raise ValueError("restore point payload invalid")
    return data


def timestamped_description(now=None) -> str:
    moment = now or datetime.now()
    return f"WPT {moment:%Y-%m-%d %H:%M:%S}"


def create_script(description: str) -> str:
    return ("Checkpoint-Computer -Description "
            f"{runner.ps_quote(description)} "
            "-RestorePointType 'MODIFY_SETTINGS'")


def restore_type_name(code) -> str:
    try:
        return _RESTORE_TYPE.get(int(code), str(code))
    except (TypeError, ValueError):
        return str(code)


def gather() -> list[dict]:
    stdout = runner.run_powershell_checked(LIST_SCRIPT, timeout=120)
    return parse_restore_points(stdout)


class RestorePointFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=16)
        ttk.Label(self, text="Restore Point",
                  style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            self, wraplength=660, style="Dim.TLabel",
            text="Existing system restore points and a button to create "
                 "a new one. Windows normally allows one restore point "
                 "per 24 hours; the result appears in the status bar.",
        ).pack(anchor="w", pady=(6, 12))

        tree_row = ttk.Frame(self)
        tree_row.pack(fill="both", expand=True)
        columns = ("sequence", "created", "description", "type", "event")
        self._tree = ttk.Treeview(tree_row, columns=columns,
                                  show="headings", height=14)
        headings = {"sequence": ("ID", 60), "created": ("Created", 150),
                    "description": ("Description", 260),
                    "type": ("Type", 170), "event": ("Event", 170)}
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
        self._refresh_button = ttk.Button(
            buttons, text="Refresh", style="Accent.TButton",
            command=self._refresh)
        self._refresh_button.pack(side="left", padx=(0, 8))
        self._create_button = ttk.Button(
            buttons, text="Create Restore Point",
            command=self._create)
        self._create_button.pack(side="left")

        self.status = widgets.StatusPane(self)
        self.status.pack(fill="x", pady=(10, 0))

        self._points: list[dict] = []
        self._pending_success = ""
        self._refresh()

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self._refresh_button.configure(state=state)
        self._create_button.configure(state=state)

    def _refresh(self) -> None:
        self._set_busy(True)
        self.status.set_working("Loading restore points...")
        tasks.BackgroundTask(
            self, work=gather, on_done=self._load_done,
            on_error=self._load_error).start()

    def _load_done(self, points: list[dict]) -> None:
        self._set_busy(False)
        self._points = points
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        for index, item in enumerate(self._points):
            self._tree.insert("", "end", iid=str(index), values=(
                item.get("sequence", ""), item.get("created", ""),
                item.get("description", ""),
                restore_type_name(item.get("type")),
                item.get("event", "")))
        prefix = ""
        if self._pending_success:
            prefix = f"{self._pending_success} "
            self._pending_success = ""
        self.status.set_success(
            f"{prefix}{len(self._points)} restore points.")

    def _load_error(self, exc: BaseException) -> None:
        self._set_busy(False)
        self._pending_success = None
        self.status.set_error(f"Loading restore points failed: {exc}")

    def _create(self) -> None:
        if not widgets.guard_admin(self.status):
            return
        if not widgets.confirm(
                self, "Create restore point",
                "Create a system restore point now? This may take "
                "a minute."):
            self.status.set_idle("Cancelled.")
            return
        script = create_script(timestamped_description())
        self._set_busy(True)
        self.status.set_working("Creating restore point...")
        tasks.BackgroundTask(
            self, work=partial(runner.run_powershell_checked, script, 300),
            on_done=lambda _: self._action_done("Restore point created."),
            on_error=self._action_error).start()

    def _action_done(self, message: str) -> None:
        self._pending_success = message
        self._refresh()

    def _action_error(self, exc: BaseException) -> None:
        self._set_busy(False)
        self.status.set_error(f"Creating restore point failed: {exc}")


def create(parent: ttk.Frame) -> ttk.Frame:
    return RestorePointFrame(parent)
