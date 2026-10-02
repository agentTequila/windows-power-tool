import json
import tkinter as tk
from functools import partial
from tkinter import ttk

from power_tool.core import runner, tasks, widgets

LIST_SCRIPT = r"""
$items = @(Get-Process | ForEach-Object {
  $p = $_
  $path = ''
  try { $path = $p.Path } catch { $path = '' }
  if (-not $path) { $path = '' }
  $cpu = $p.CPU
  if ($null -eq $cpu) { $cpu = 0 }
  [ordered]@{ name = $p.Name; pid = $p.Id; cpu = [math]::Round([double]$cpu, 1); ram = [int64]$p.WorkingSet64; path = $path }
})
ConvertTo-Json -InputObject $items -Depth 3 -Compress
"""


def parse_processes(stdout: str) -> list[dict]:
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
        raise ValueError("process payload invalid")
    return data


def format_ram(num_bytes) -> str:
    try:
        total = int(num_bytes or 0)
    except (TypeError, ValueError):
        return "0 MB"
    return f"{total / (1024 * 1024):.1f} MB"


def filter_processes(items: list[dict], query: str) -> list[dict]:
    cleaned = str(query or "").strip().lower()
    if not cleaned:
        return list(items)
    return [item for item in items
            if cleaned in str(item.get("name", "")).lower()
            or cleaned in str(item.get("path", "")).lower()]


def end_process_script(pid) -> str:
    return f"Stop-Process -Id {int(pid)} -Force"


def gather() -> list[dict]:
    stdout = runner.run_powershell_checked(LIST_SCRIPT, timeout=120)
    return parse_processes(stdout)


class ProcessesFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=16)
        ttk.Label(self, text="Processes", style="Title.TLabel").pack(
            anchor="w")
        ttk.Label(
            self, wraplength=660, style="Dim.TLabel",
            text="Running processes with PID, CPU time, memory and "
                 "executable path. End Process asks for confirmation "
                 "before stopping the selected process.",
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
        columns = ("name", "pid", "cpu", "ram", "path")
        self._tree = ttk.Treeview(tree_row, columns=columns,
                                  show="headings", height=14)
        headings = {"name": ("Name", 180), "pid": ("PID", 80),
                    "cpu": ("CPU (s)", 90), "ram": ("RAM", 100),
                    "path": ("Path", 380)}
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
        self._end_button = ttk.Button(
            buttons, text="End Process", style="Danger.TButton",
            command=self._end_process)
        self._end_button.pack(side="left")

        self.status = widgets.StatusPane(self)
        self.status.pack(fill="x", pady=(10, 0))

        self._all: list[dict] = []
        self._visible: list[dict] = []
        self._pending_success = ""
        self._refresh()

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self._refresh_button.configure(state=state)
        self._end_button.configure(state=state)

    def _refresh(self) -> None:
        self._set_busy(True)
        self.status.set_working("Loading processes...")
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
            f"{prefix}{len(self._all)} processes running.")

    def _load_error(self, exc: BaseException) -> None:
        self._set_busy(False)
        self.status.set_error(f"Loading processes failed: {exc}")

    def _refilter(self) -> None:
        self._visible = filter_processes(self._all, self._query.get())
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        for index, item in enumerate(self._visible):
            self._tree.insert("", "end", iid=str(index), values=(
                item.get("name", ""), item.get("pid", ""),
                item.get("cpu", ""), format_ram(item.get("ram")),
                item.get("path", "")))
        if self._query.get().strip():
            self.status.set_idle(
                f"{len(self._visible)} of {len(self._all)} match")

    def _selected_pid(self):
        selection = self._tree.selection()
        if not selection:
            return None
        return self._visible[int(selection[0])].get("pid")

    def _end_process(self) -> None:
        pid = self._selected_pid()
        if pid is None:
            self.status.set_warn("Select a process first.")
            return
        if not widgets.guard_admin(self.status):
            return
        if not widgets.confirm(self, "End process",
                               f"End process {pid}? Unsaved data in it "
                               "will be lost."):
            self.status.set_idle("Cancelled.")
            return
        try:
            script = end_process_script(pid)
        except (TypeError, ValueError):
            self.status.set_error(f"Invalid PID: {pid}")
            return
        self._set_busy(True)
        self.status.set_working(f"Ending process {pid}...")
        tasks.BackgroundTask(
            self, work=partial(runner.run_powershell_checked, script, 60),
            on_done=lambda _: self._action_done(f"Process {pid} ended."),
            on_error=self._action_error).start()

    def _action_done(self, message: str) -> None:
        self._pending_success = message
        self._refresh()

    def _action_error(self, exc: BaseException) -> None:
        self._set_busy(False)
        self.status.set_error(f"End process failed: {exc}")


def create(parent: ttk.Frame) -> ttk.Frame:
    return ProcessesFrame(parent)
