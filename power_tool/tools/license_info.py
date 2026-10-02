import base64
import json
import tkinter as tk
from tkinter import ttk

from power_tool.core import runner, tasks, theme, widgets

LICENSE_SCRIPT = r"""
$os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
$reg = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion' -ErrorAction Stop
$prod = Get-CimInstance SoftwareLicensingProduct -ErrorAction SilentlyContinue |
  Where-Object { $_.PartialProductKey -and $_.Name -like 'Windows*' } |
  Select-Object -First 1
$srv = Get-CimInstance SoftwareLicensingService -ErrorAction SilentlyContinue
$digital = $null
if ($reg.DigitalProductId) { $digital = [Convert]::ToBase64String([byte[]]$reg.DigitalProductId) }
$oem = ''
if ($srv -and $srv.OA3xOriginalProductKey) { $oem = [string]$srv.OA3xOriginalProductKey }
$status = $null
$partial = ''
$name = ''
if ($prod) { $status = $prod.LicenseStatus; $partial = [string]$prod.PartialProductKey; $name = [string]$prod.Name }
[ordered]@{
  caption = [string]$os.Caption
  edition = [string]$reg.EditionID
  build   = [string]$reg.CurrentBuildNumber
  product_name = $name
  partial_key = $partial
  oem_key = $oem
  status_code = $status
  digital_b64 = $digital
} | ConvertTo-Json -Depth 3 -Compress
"""

LICENSE_STATUS = {
    0: "Unlicensed",
    1: "Licensed",
    2: "Out-of-Box Grace Period",
    3: "Out-of-Tolerance Grace Period",
    4: "Non-Genuine Grace Period",
    5: "Notification",
    6: "Extended Grace Period",
}

_KEY_CHARS = "BCDFGHJKMPQRTVWXY2346789"


def parse_license(stdout: str) -> dict:
    try:
        data = json.loads(stdout)
    except ValueError as exc:
        raise ValueError(
            f"unexpected PowerShell output: {stdout[:200]}") from exc
    if not isinstance(data, dict):
        raise ValueError("license payload invalid")
    return data


def decode_product_key(digital_id) -> str | None:
    if not digital_id or len(digital_id) < 67:
        return None
    data = bytearray(digital_id)
    offset = 52
    is_win8 = (data[66] // 6) & 1
    data[66] = (data[66] & 0xF7) | ((is_win8 & 2) * 4)
    key = ""
    last = 0
    for _ in range(25):
        current = 0
        for j in range(14, -1, -1):
            current = current * 256 + data[j + offset]
            data[j + offset] = current // 24
            current = current % 24
        key = _KEY_CHARS[current] + key
        last = current
    if is_win8:
        key = key[1:last + 1] + "N" + key[last + 1:]
    return "-".join(key[i:i + 5] for i in range(0, 25, 5))


def status_name(code) -> str:
    try:
        return LICENSE_STATUS.get(int(code), f"Unknown ({code})")
    except (TypeError, ValueError):
        return "Unknown"


def _decoded_key(data: dict) -> str | None:
    encoded = data.get("digital_b64")
    if not encoded:
        return None
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        return None
    return decode_product_key(raw)


def format_license_block(data: dict) -> str:
    lines = []
    lines.append("=" * 62)
    lines.append("WINDOWS LICENSE INFORMATION")
    lines.append("=" * 62)
    lines.append(f"{'Edition':<14}: "
                 f"{data.get('caption') or 'Not available'}")
    if data.get("edition"):
        lines.append(f"{'Edition ID':<14}: {data['edition']}")
    if data.get("build"):
        lines.append(f"{'OS build':<14}: {data['build']}")
    lines.append("")
    lines.append(f"{'Status':<14}: {status_name(data.get('status_code'))}")
    if data.get("product_name"):
        lines.append(f"{'Licensed to':<14}: {data['product_name']}")
    lines.append("")
    decoded = _decoded_key(data)
    if decoded:
        lines.append(f"{'Product key':<14}: {decoded}")
        lines.append(f"{'Key source':<14}: Registry (DigitalProductId)")
    elif data.get("oem_key"):
        lines.append(f"{'Product key':<14}: {data['oem_key']}")
        lines.append(f"{'Key source':<14}: OEM firmware (OA3x)")
    else:
        lines.append(f"{'Product key':<14}: Not available")
    if data.get("partial_key"):
        lines.append(f"{'Partial key':<14}: {data['partial_key']}")
    lines.append("")
    return "\n".join(lines)


def gather() -> dict:
    stdout = runner.run_powershell_checked(LICENSE_SCRIPT, timeout=120)
    return parse_license(stdout)


class LicenseInfoFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=16)
        ttk.Label(self, text="License Info",
                  style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            self, wraplength=660, style="Dim.TLabel",
            text="Windows edition, product key (registry or OEM source "
                 "when available) and activation status. Copy puts the "
                 "whole block on the clipboard.",
        ).pack(anchor="w", pady=(6, 12))

        buttons = ttk.Frame(self)
        buttons.pack(anchor="w", pady=(0, 10))
        self._refresh_button = ttk.Button(
            buttons, text="Refresh", style="Accent.TButton",
            command=self._refresh)
        self._refresh_button.pack(side="left", padx=(0, 8))
        self._copy_button = ttk.Button(
            buttons, text="Copy", state="disabled", command=self._copy)
        self._copy_button.pack(side="left")

        pane_row = ttk.Frame(self)
        pane_row.pack(fill="both", expand=True)
        palette = theme.current_palette()
        self._output = tk.Text(
            pane_row, wrap="none", height=16, font=("Consolas", 10),
            bg=palette["entry_bg"], fg=palette["fg"],
            insertbackground=palette["fg"], relief="flat", padx=10, pady=8,
            state="disabled")
        self._output.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(pane_row, orient="vertical",
                               command=self._output.yview)
        scroll.pack(side="right", fill="y")
        self._output.configure(yscrollcommand=scroll.set)
        theme.observe(self._on_theme)

        self.status = widgets.StatusPane(self)
        self.status.pack(fill="x", pady=(10, 0))
        self._block = ""
        self._refresh()

    def _on_theme(self, palette: dict) -> None:
        self._output.configure(bg=palette["entry_bg"], fg=palette["fg"],
                               insertbackground=palette["fg"])

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self._refresh_button.configure(state=state)
        self._copy_button.configure(state=state)

    def _refresh(self) -> None:
        self._set_busy(True)
        self.status.set_working("Reading license information...")
        tasks.BackgroundTask(
            self, work=gather, on_done=self._load_done,
            on_error=self._load_error).start()

    def _load_done(self, data: dict) -> None:
        self._set_busy(False)
        try:
            self._block = format_license_block(data)
        except Exception as exc:
            self._copy_button.configure(state="disabled")
            self.status.set_error(f"Formatting failed: {exc}")
            return
        self._output.configure(state="normal")
        self._output.delete("1.0", "end")
        self._output.insert("1.0", self._block)
        self._output.configure(state="disabled")
        self._copy_button.configure(state="normal")
        self.status.set_success("License information loaded.")

    def _load_error(self, exc: BaseException) -> None:
        self._set_busy(False)
        self.status.set_error(f"Reading license information failed: {exc}")

    def _copy(self) -> None:
        if not self._block:
            self.status.set_warn("Nothing to copy yet.")
            return
        widgets.copy_text(self, self._block)
        self.status.set_success("Copied to clipboard.")


def create(parent: ttk.Frame) -> ttk.Frame:
    return LicenseInfoFrame(parent)
