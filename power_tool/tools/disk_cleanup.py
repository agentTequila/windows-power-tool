import json
from tkinter import ttk

from power_tool.core import runner, tasks, widgets

DRIVES_SCRIPT = r"""
$items = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=2 or DriveType=3' | ForEach-Object {
  $d = $_
  $size = $d.Size
  $free = $d.FreeSpace
  if ($null -eq $size) { $size = 0 }
  if ($null -eq $free) { $free = 0 }
  [ordered]@{ drive = [string]$d.DeviceID; label = [string]$d.VolumeName; total = [int64]$size; free = [int64]$free; filesystem = [string]$d.FileSystem; type = [int]$d.DriveType }
})
ConvertTo-Json -InputObject $items -Depth 3 -Compress
"""


def parse_drives(stdout: str) -> list[dict]:
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
        raise ValueError("drive payload invalid")
    return data


def format_gb(num_bytes) -> str:
    try:
        total = int(num_bytes or 0)
    except (TypeError, ValueError):
        return "0 GB"
    return f"{total / (1024 ** 3):.1f} GB"


def pct_free(total, free) -> str:
    try:
        total = int(total or 0)
        free = int(free or 0)
    except (TypeError, ValueError):
        return "n/a"
    if total <= 0:
        return "n/a"
    return f"{free / total * 100:.0f}%"


def type_name(type_code) -> str:
    mapping = {2: "Removable", 3: "Fixed"}
    try:
        return mapping.get(int(type_code), str(type_code))
    except (TypeError, ValueError):
        return str(type_code)


def gather() -> list[dict]:
    stdout = runner.run_powershell_checked(DRIVES_SCRIPT, timeout=120)
    return parse_drives(stdout)


class DiskCleanupFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=16)
        ttk.Label(self, text="Disk & Cleanup", style="Title.TLabel").pack(
            anchor="w")
        ttk.Label(
            self, wraplength=660, style="Dim.TLabel",
            text="Fixed and removable drives with total size, free space "
                 "and file system. Run Disk Cleanup opens the Windows "
                 "cleanmgr utility where you choose what to delete.",
        ).pack(anchor="w", pady=(6, 12))

        tree_row = ttk.Frame(self)
        tree_row.pack(fill="both", expand=True)
        columns = ("drive", "label", "total", "free", "pct", "filesystem",
                   "type")
        self._tree = ttk.Treeview(tree_row, columns=columns,
                                  show="headings", height=12)
        headings = {"drive": ("Drive", 70), "label": ("Label", 150),
                    "total": ("Total", 100), "free": ("Free", 100),
                    "pct": ("% Free", 80), "filesystem": ("File System", 100),
                    "type": ("Type", 90)}
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
        self._cleanup_button = ttk.Button(
            buttons, text="Run Disk Cleanup", command=self._run_cleanup)
        self._cleanup_button.pack(side="left")

        self.status = widgets.StatusPane(self)
        self.status.pack(fill="x", pady=(10, 0))

        self._drives: list[dict] = []
        self._refresh()

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self._refresh_button.configure(state=state)
        self._cleanup_button.configure(state=state)

    def _refresh(self) -> None:
        self._set_busy(True)
        self.status.set_working("Reading drives...")
        tasks.BackgroundTask(
            self, work=gather, on_done=self._load_done,
            on_error=self._load_error).start()

    def _load_done(self, drives: list[dict]) -> None:
        self._set_busy(False)
        self._drives = drives
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        for index, item in enumerate(self._drives):
            self._tree.insert("", "end", iid=str(index), values=(
                item.get("drive", ""), item.get("label", ""),
                format_gb(item.get("total")), format_gb(item.get("free")),
                pct_free(item.get("total"), item.get("free")),
                item.get("filesystem", ""),
                type_name(item.get("type"))))
        self.status.set_success(f"{len(self._drives)} drives found.")

    def _load_error(self, exc: BaseException) -> None:
        self._set_busy(False)
        self.status.set_error(f"Reading drives failed: {exc}")

    def _run_cleanup(self) -> None:
        if not widgets.guard_admin(self.status):
            return
        if not widgets.confirm(
                self, "Disk Cleanup",
                "Open Windows Disk Cleanup (cleanmgr)? You choose what "
                "to delete in the window that opens."):
            self.status.set_idle("Cancelled.")
            return
        try:
            runner.start_detached(["cleanmgr"])
        except OSError as exc:
            self.status.set_error(f"Could not start Disk Cleanup: {exc}")
            return
        self.status.set_success("Disk Cleanup opened.")


def create(parent: ttk.Frame) -> ttk.Frame:
    return DiskCleanupFrame(parent)
