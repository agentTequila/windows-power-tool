import winreg
from tkinter import ttk

from power_tool.core import widgets

# Removable Disks class (GUID_DEVCLASS_DISKDRIVE): the policy that covers
# USB mass-storage volumes without touching keyboards, mice or printers.
CLASS_GUID = "{53f5630d-b6bf-11d0-94f2-00a0c91efb8b}"
POLICY_PATH = (rf"SOFTWARE\Policies\Microsoft\Windows\RemovableStorageDevices"
               rf"\{CLASS_GUID}")
DENY_READ = "Deny_Read"
DENY_WRITE = "Deny_Write"

KEY_PATH = r"SYSTEM\CurrentControlSet\Services\USBSTOR"
VALUE_NAME = "Start"
ENABLED = 3
HIDDEN = 4
_READ_FLAGS = winreg.KEY_READ | winreg.KEY_WOW64_64KEY
_WRITE_FLAGS = winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY

STATE_ALLOWED = "allowed"
STATE_BLOCKED = "blocked"
STATE_WRITE_PROTECTED = "write_protected"
STATE_HIDDEN = "hidden"

_STATE_TEXT = {
    STATE_BLOCKED: ("USB storage: BLOCKED — visible, access denied",
                    "Error.TLabel"),
    STATE_WRITE_PROTECTED: ("USB storage: WRITE-PROTECTED — reads still work",
                            "Warn.TLabel"),
    STATE_HIDDEN: ("USB storage: HIDDEN — legacy USBSTOR block",
                   "Warn.TLabel"),
    STATE_ALLOWED: ("USB storage: ALLOWED", "Success.TLabel"),
}


def _query_dword(key, name: str) -> int:
    try:
        value, _ = winreg.QueryValueEx(key, name)
        return int(value)
    except (OSError, ValueError):
        return 0


def _policy_flags() -> tuple[int, int]:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, POLICY_PATH, 0,
                            _READ_FLAGS) as key:
            return _query_dword(key, DENY_READ), _query_dword(key, DENY_WRITE)
    except OSError:
        return 0, 0


def driver_start() -> int | None:
    """The USBSTOR Start value, or None when the key does not exist."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, KEY_PATH, 0,
                            _READ_FLAGS) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return int(value)
    except (OSError, ValueError):
        return None


def read_state() -> str:
    """One of allowed, blocked, write_protected or hidden.

    Deny_Read is the full block this tool writes. A Deny_Write-only value
    from another tool is reported separately so the UI does not call a
    read-only drive "blocked". Start=4 is what older builds wrote; it hides
    the drive instead of denying access, so it gets its own label.
    """
    deny_read, deny_write = _policy_flags()
    if deny_read:
        return STATE_BLOCKED
    if deny_write:
        return STATE_WRITE_PROTECTED
    if driver_start() == HIDDEN:
        return STATE_HIDDEN
    return STATE_ALLOWED


def is_blocked() -> bool:
    """True when USB storage is blocked or hidden by either mechanism."""
    return read_state() in (STATE_BLOCKED, STATE_HIDDEN)


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
                   command=self._unblock).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Refresh", command=self.refresh).pack(
            side="left")

        info = ttk.Frame(self, style="Panel.TFrame", padding=(16, 14))
        info.grid(row=4, column=0, sticky="ew", pady=(18, 0))
        info.grid_columnconfigure(1, weight=1)
        ttk.Label(info, text="AT A GLANCE",
                  style="PanelHeading.TLabel").grid(
                      row=0, column=0, columnspan=2, sticky="w",
                      pady=(0, 8))
        for index, (label, value) in enumerate((
                ("Blocks", "Read and write access to USB storage drives"),
                ("Leaves alone", "Keyboards, mice, printers, network adapters"),
                ("Applies", "When the drive is next connected"),
                ("Scope", "This PC, all users")), start=1):
            ttk.Label(info, text=label, style="PanelDim.TLabel").grid(
                row=index, column=0, sticky="nw", padx=(0, 18), pady=2)
            ttk.Label(info, text=value, style="Panel.TLabel").grid(
                row=index, column=1, sticky="w", pady=2)
        ttk.Label(info, text="A domain policy can override this setting.",
                  style="PanelDim.TLabel").grid(
                      row=5, column=0, columnspan=2, sticky="w",
                      pady=(8, 0))

        self.status = widgets.StatusPane(self)
        # Keep the status bar at the bottom of the page instead of floating
        # under the short form.
        self.grid_rowconfigure(5, weight=1)
        self.status.grid(row=6, column=0, sticky="ew", pady=(8, 8))
        self.refresh(silent=True)

    def refresh(self, silent: bool = False) -> str:
        state = read_state()
        text, style = _STATE_TEXT[state]
        self._indicator.configure(style=style)
        self._state_label.configure(text=text, style=style)
        if not silent:
            if state == STATE_BLOCKED:
                self.status.set_success(
                    "USB storage blocked. Reconnect the drive to enforce it; "
                    "restart Windows if it still opens.")
            elif state == STATE_WRITE_PROTECTED:
                self.status.set_warn(
                    "USB storage is write-protected by policy. Reads still "
                    "work; Allow USB Storage clears it — reconnect the drive "
                    "afterwards.")
            elif state == STATE_HIDDEN:
                self.status.set_warn(
                    "USB storage is hidden by the legacy USBSTOR switch. "
                    "Allow USB Storage turns the driver back on.")
            else:
                self.status.set_success(
                    "USB storage allowed. Reconnect the drive; restart "
                    "Windows if access is still denied.")
        return state

    def _set(self, blocked: bool) -> None:
        if not widgets.guard_admin(self.status):
            return
        try:
            set_blocked(blocked)
        except OSError as exc:
            self.status.set_error(f"Registry write failed: {exc}")
            self.refresh(silent=True)
            return
        state = self.refresh(silent=True)
        if blocked and state == STATE_BLOCKED:
            self.status.set_success(
                "USB storage blocked. Reconnect the drive to enforce it; "
                "restart Windows if it still opens.")
        elif not blocked and state == STATE_ALLOWED:
            self.status.set_success(
                "USB storage allowed. Reconnect the drive; restart Windows "
                "if access is still denied.")
        elif state in (STATE_WRITE_PROTECTED, STATE_HIDDEN):
            self.status.set_warn(
                "The change was written, but USB storage still reports a "
                "restriction. Another policy may be overriding it.")
        else:
            self.status.set_error(
                "The change was written but could not be confirmed. "
                "Restart Windows and check again.")

    def _block(self) -> None:
        self._set(True)

    def _unblock(self) -> None:
        self._set(False)


def create(parent: ttk.Frame) -> ttk.Frame:
    return UsbGuardFrame(parent)
