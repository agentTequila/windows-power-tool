import tkinter as tk
from tkinter import ttk

import winreg

from power_tool.core import widgets

KEY_PATH = r"SYSTEM\CurrentControlSet\Services\USBSTOR"
VALUE_NAME = "Start"
ENABLED = 3
DISABLED = 4
_READ_FLAGS = winreg.KEY_READ | winreg.KEY_WOW64_64KEY
_WRITE_FLAGS = winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY


def read_state() -> int | None:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, KEY_PATH, 0, _READ_FLAGS) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return int(value)
    except (OSError, ValueError):
        return None


def write_state(value: int) -> None:
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, KEY_PATH, 0, _WRITE_FLAGS) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_DWORD, value)


class UsbGuardFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=16)
        ttk.Label(self, text="USB Guard", style="Title.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(
            self, wraplength=660, style="Dim.TLabel",
            text="Disable USB storage drives so they still show in This PC but open "
                 "as Access Denied. Keyboards, mice, printers and network adapters "
                 "are not affected.",
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
        ttk.Button(buttons, text="Disable USB Storage", style="Danger.TButton",
                   command=self._disable).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Enable USB Storage", style="Accent.TButton",
                   command=self._enable).pack(side="left")

        ttk.Label(
            self, wraplength=660, style="Dim.TLabel",
            text="Replug an already-connected drive after changing this setting. "
                 "No reboot needed.",
        ).grid(row=4, column=0, sticky="w", pady=(4, 12))

        self.status = widgets.StatusPane(self)
        self.status.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        self.refresh(silent=True)

    def refresh(self, silent: bool = False) -> None:
        state = read_state()
        if state is None:
            self._indicator.configure(style="Error.TLabel")
            self._state_label.configure(
                text="State unknown — USBSTOR registry key not found",
                style="Error.TLabel")
        elif state == DISABLED:
            self._indicator.configure(style="Error.TLabel")
            self._state_label.configure(text="USB storage: DISABLED",
                                        style="Error.TLabel")
            if not silent:
                self.status.set_success(
                    "USB storage disabled. Replug drives to apply.")
        elif state == ENABLED:
            self._indicator.configure(style="Success.TLabel")
            self._state_label.configure(text="USB storage: ENABLED",
                                        style="Success.TLabel")
            if not silent:
                self.status.set_success("USB storage enabled.")
        else:
            self._indicator.configure(style="Idle.TLabel")
            self._state_label.configure(
                text=f"USB storage: unexpected Start value {state}",
                style="Idle.TLabel")

    def _set(self, value: int) -> None:
        if not widgets.guard_admin(self.status):
            return
        try:
            write_state(value)
        except OSError as exc:
            self.status.set_error(f"Registry write failed: {exc}")
            self.refresh(silent=True)
            return
        self.refresh()

    def _disable(self) -> None:
        self._set(DISABLED)

    def _enable(self) -> None:
        self._set(ENABLED)


def create(parent: ttk.Frame) -> ttk.Frame:
    return UsbGuardFrame(parent)
