from tkinter import ttk

import winreg

from power_tool.core import widgets

CLASS_GUID = "{53f5630d-b6bf-11d0-94f2-00a0c91efb8b}"
POLICY_PATH = (rf"SOFTWARE\Policies\Microsoft\Windows\RemovableStorageDevices"
               rf"\{CLASS_GUID}")
DENY_READ = "Deny_Read"
DENY_WRITE = "Deny_Write"

KEY_PATH = r"SYSTEM\CurrentControlSet\Services\USBSTOR"
VALUE_NAME = "Start"
ENABLED = 3
_READ_FLAGS = winreg.KEY_READ | winreg.KEY_WOW64_64KEY
_WRITE_FLAGS = winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY


def is_blocked() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, POLICY_PATH, 0,
                            _READ_FLAGS) as key:
            value, _ = winreg.QueryValueEx(key, DENY_READ)
            return int(value) == 1
    except (OSError, ValueError):
        return False


def _ensure_driver_enabled() -> None:
    """Older builds hid drives via USBSTOR Start=4; restore the default 3."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, KEY_PATH, 0,
                            _WRITE_FLAGS) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_DWORD, ENABLED)
    except OSError:
        pass


def set_blocked(blocked: bool) -> None:
    _ensure_driver_enabled()
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, POLICY_PATH, 0,
                            _WRITE_FLAGS) as key:
        dword = 1 if blocked else 0
        winreg.SetValueEx(key, DENY_READ, 0, winreg.REG_DWORD, dword)
        winreg.SetValueEx(key, DENY_WRITE, 0, winreg.REG_DWORD, dword)


class UsbGuardFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=16)
        ttk.Label(self, text="USB Guard", style="Title.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(
            self, wraplength=660, style="Dim.TLabel",
            text="Block USB storage drives: they stay visible in This PC so "
                 "everyone can see the drive is plugged in, but opening or "
                 "copying to it shows Access denied. Keyboards, mice, printers "
                 "and network adapters are not affected.",
        ).grid(row=1, column=0, sticky="w", pady=(6, 12))

        strip = ttk.Frame(self, style="Panel.TFrame", padding=12)
        strip.grid(row=2, column=0, sticky="ew")
        self._indicator = ttk.Label(strip, text="●", style="Idle.TLabel")
        self._indicator.pack(side="left")
        self._state_label = ttk.Label(strip, text="", style="Idle.TLabel")
        self._state_label.pack(side="left", padx=(8, 0))
        self.grid_columnconfigure(0, weight=1)

        buttons = ttk.Frame(self)
        buttons.grid(row=3, column=0, sticky="w", pady=(14, 4))
        ttk.Button(buttons, text="Block USB Storage", style="Danger.TButton",
                   command=self._block).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Allow USB Storage", style="Accent.TButton",
                   command=self._unblock).pack(side="left")

        ttk.Label(
            self, wraplength=660, style="Dim.TLabel",
            text="Takes effect on the next open of a drive. Replug or reopen "
                 "the drive if it was already open.",
        ).grid(row=4, column=0, sticky="w", pady=(4, 12))

        self.status = widgets.StatusPane(self)
        self.status.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        _ensure_driver_enabled()
        self.refresh(silent=True)

    def refresh(self, silent: bool = False) -> None:
        if is_blocked():
            self._indicator.configure(style="Error.TLabel")
            self._state_label.configure(
                text="USB storage: BLOCKED — visible, access denied",
                style="Error.TLabel")
            if not silent:
                self.status.set_success(
                    "USB storage blocked. Drives stay visible but opening one "
                    "is denied.")
        else:
            self._indicator.configure(style="Success.TLabel")
            self._state_label.configure(text="USB storage: ALLOWED",
                                        style="Success.TLabel")
            if not silent:
                self.status.set_success("USB storage allowed.")

    def _set(self, blocked: bool) -> None:
        if not widgets.guard_admin(self.status):
            return
        try:
            set_blocked(blocked)
        except OSError as exc:
            self.status.set_error(f"Registry write failed: {exc}")
            self.refresh(silent=True)
            return
        self.refresh()

    def _block(self) -> None:
        self._set(True)

    def _unblock(self) -> None:
        self._set(False)


def create(parent: ttk.Frame) -> ttk.Frame:
    return UsbGuardFrame(parent)
