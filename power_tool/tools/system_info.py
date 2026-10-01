import json
from datetime import datetime
from typing import Mapping

import tkinter as tk
from tkinter import ttk

from power_tool.core import runner, tasks, theme, widgets

COLLECT_SCRIPT = r"""
$os = Get-CimInstance Win32_OperatingSystem
$cs = Get-CimInstance Win32_ComputerSystem
$cpu = @(Get-CimInstance Win32_Processor | ForEach-Object {
  [ordered]@{ name = $_.Name; cores = $_.NumberOfCores; logical = $_.NumberOfLogicalProcessors }
})
$ram = @(Get-CimInstance Win32_PhysicalMemory | ForEach-Object {
  [ordered]@{ slot = $_.DeviceLocator; size = [int64]$_.Capacity; speed = $_.Speed; maker = $_.Manufacturer }
})
$network = @(Get-NetIPConfiguration | Where-Object { $_.NetAdapter } | ForEach-Object {
  [ordered]@{
    interface = $_.InterfaceAlias
    mac       = $_.NetAdapter.MacAddress
    ipv4      = @($_.IPv4Address | ForEach-Object { $_.IPAddress })
    ipv6      = @($_.IPv6Address | ForEach-Object { $_.IPAddress })
  }
})
$disks = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=2 or DriveType=3' | ForEach-Object {
  [ordered]@{
    device = $_.DeviceID
    label  = $_.VolumeName
    fs     = $_.FileSystem
    total  = [int64]$_.Size
    free   = [int64]$_.FreeSpace
    type   = if ($_.DriveType -eq 2) { 'Removable' } else { 'Fixed' }
  }
})
$users = @(Get-LocalUser | ForEach-Object {
  $u = $_
  $groups = @()
  foreach ($g in Get-LocalGroup) {
    try { Get-LocalGroupMember -Group $g.Name -Member $u.Name -ErrorAction Stop | Out-Null
          $groups += $g.Name } catch {}
  }
  [ordered]@{ name = $u.Name; full = $u.FullName; enabled = [bool]$u.Enabled; groups = @($groups) }
})
$result = [ordered]@{
  hostname  = $env:COMPUTERNAME
  generated = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
  os        = [ordered]@{ caption = $os.Caption; version = $os.Version; build = $os.BuildNumber; arch = $os.OSArchitecture }
  hardware  = [ordered]@{ manufacturer = $cs.Manufacturer; model = $cs.Model; totalRam = [int64]$cs.TotalPhysicalMemory }
  cpu       = $cpu
  ram       = $ram
  network   = $network
  disks     = $disks
  users     = $users
  boot      = $os.LastBootUpTime.ToString('yyyy-MM-ddTHH:mm:ss')
}
ConvertTo-Json -InputObject $result -Depth 6 -Compress
"""


def parse_report(stdout: str) -> dict:
    try:
        data = json.loads(stdout)
    except ValueError as exc:
        raise ValueError(f"unexpected PowerShell output: {stdout[:200]}") from exc
    if not isinstance(data, dict):
        raise ValueError("report JSON is not an object")
    return data


def _gb(num_bytes) -> str:
    if not num_bytes:
        return "0 B"
    return f"{num_bytes / (1024 ** 3):.1f} GB"


def format_uptime(boot: str, now: str) -> str:
    boot_dt = datetime.fromisoformat(boot)
    now_dt = datetime.fromisoformat(now)
    delta = now_dt - boot_dt
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes}m"


def format_report(data: Mapping) -> str:
    lines: list[str] = []
    lines.append("=" * 62)
    lines.append(f"SYSTEM INFO — {data.get('hostname', '?')}")
    lines.append(f"Generated: {data.get('generated', '?')}")
    lines.append("=" * 62)

    os_info = data.get("os", {})
    lines.append("")
    lines.append("--- Operating System ---")
    lines.append(f"  Edition : {os_info.get('caption', '?')}")
    lines.append(f"  Version : {os_info.get('version', '?')} (build {os_info.get('build', '?')})")
    lines.append(f"  Arch    : {os_info.get('arch', '?')}")

    boot = data.get("boot")
    if boot:
        try:
            uptime = format_uptime(boot, str(datetime.now().replace(microsecond=0)))
        except ValueError:
            uptime = "unknown"
        lines.append(f"  Booted  : {boot.replace('T', ' ')} (up {uptime})")

    hw = data.get("hardware", {})
    lines.append("")
    lines.append("--- Hardware ---")
    lines.append(f"  Model   : {hw.get('manufacturer', '?')} {hw.get('model', '')}")
    lines.append(f"  RAM     : {_gb(hw.get('totalRam'))} total")
    for module in data.get("ram", []):
        lines.append(f"    - {module.get('slot', '?')}: {_gb(module.get('size'))} "
                     f"{module.get('speed', '?')} MHz ({module.get('maker', '?')})")
    for cpu in data.get("cpu", []):
        lines.append(f"  CPU     : {cpu.get('name', '?')}")
        lines.append(f"            {cpu.get('cores', '?')} cores / "
                     f"{cpu.get('logical', '?')} logical")

    lines.append("")
    lines.append("--- Network ---")
    for iface in data.get("network", []):
        lines.append(f"  {iface.get('interface', '?')}  [{iface.get('mac', '?')}]")
        for ip in iface.get("ipv4", []) or []:
            lines.append(f"    IPv4 : {ip}")
        for ip in iface.get("ipv6", []) or []:
            lines.append(f"    IPv6 : {ip}")

    lines.append("")
    lines.append("--- Storage ---")
    for disk in data.get("disks", []):
        total = disk.get("total") or 0
        free = disk.get("free") or 0
        pct = (free / total * 100) if total else 0.0
        lines.append(f"  {disk.get('device', '?')} {disk.get('label', '')} "
                     f"({disk.get('type', '?')}, {disk.get('fs', '?')}) "
                     f"— {_gb(total)} total, {_gb(free)} free ({pct:.0f}%)")

    lines.append("")
    lines.append("--- Local Users ---")
    for user in data.get("users", []):
        state = "enabled" if user.get("enabled") else "disabled"
        groups = ", ".join(user.get("groups", []) or []) or "none"
        full = user.get("full") or ""
        name = user.get("name", "?")
        lines.append(f"  {name}{f' ({full})' if full else ''} — {state} — {groups}")

    lines.append("")
    return "\n".join(lines)


def gather() -> dict:
    result = runner.run_powershell(COLLECT_SCRIPT, timeout=300)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(f"PowerShell failed: {detail}")
    return parse_report(result.stdout)


class SystemInfoFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=16)
        ttk.Label(self, text="System Info", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            self, wraplength=660, style="Dim.TLabel",
            text="Hostname, OS, network interfaces, users and groups, hardware, "
                 "storage (including removable) and uptime.",
        ).pack(anchor="w", pady=(6, 12))

        buttons = ttk.Frame(self)
        buttons.pack(anchor="w", pady=(0, 10))
        self._show_button = ttk.Button(
            buttons, text="Show System Info", style="Accent.TButton",
            command=self._start)
        self._show_button.pack(side="left", padx=(0, 8))
        self._copy_button = ttk.Button(buttons, text="Copy to Clipboard",
                                       state="disabled", command=self._copy)
        self._copy_button.pack(side="left", padx=(0, 8))
        self._save_button = ttk.Button(buttons, text="Save as TXT",
                                       state="disabled", command=self._save)
        self._save_button.pack(side="left")

        palette = theme.current_palette()
        self._output = tk.Text(
            self, wrap="none", height=26, font=("Consolas", 10),
            bg=palette["entry_bg"], fg=palette["fg"], insertbackground=palette["fg"],
            relief="flat", padx=10, pady=8, state="disabled")
        self._output.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(self, command=self._output.yview)
        self._output.configure(yscrollcommand=scroll.set)
        theme.observe(self._on_theme)

        self.status = widgets.StatusPane(self)
        self.status.pack(fill="x", pady=(10, 0))
        self._report_text = ""

    def _on_theme(self, palette: dict) -> None:
        self._output.configure(bg=palette["entry_bg"], fg=palette["fg"],
                               insertbackground=palette["fg"])

    def _start(self) -> None:
        if not widgets.guard_admin(self.status):
            return
        self._show_button.configure(state="disabled")
        self.status.set_working("Collecting system information...")
        tasks.BackgroundTask(self, work=gather, on_done=self._on_done,
                             on_error=self._on_error).start()

    def _on_done(self, data: dict) -> None:
        try:
            self._report_text = format_report(data)
        except Exception as exc:
            self._show_button.configure(state="normal")
            self.status.set_error(f"Formatting failed: {exc}")
            return
        self._output.configure(state="normal")
        self._output.delete("1.0", "end")
        self._output.insert("1.0", self._report_text)
        self._output.configure(state="disabled")
        self._show_button.configure(state="normal")
        self._copy_button.configure(state="normal")
        self._save_button.configure(state="normal")
        self.status.set_success("System information collected.")

    def _on_error(self, exc: BaseException) -> None:
        self._show_button.configure(state="normal")
        self.status.set_error(f"Collection failed: {exc}")

    def _copy(self) -> None:
        widgets.copy_text(self, self._report_text)
        self.status.set_success("Report copied to clipboard.")

    def _save(self) -> None:
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".txt",
            filetypes=[("Text files", "*.txt")],
            initialfile="system_info.txt")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self._report_text)
        except OSError as exc:
            self.status.set_error(f"Save failed: {exc}")
            return
        self.status.set_success(f"Saved to {path}")


def create(parent: ttk.Frame) -> ttk.Frame:
    return SystemInfoFrame(parent)
