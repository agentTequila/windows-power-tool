from tkinter import messagebox, ttk

from power_tool.core import admin


class StatusPane(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, style="Status.TFrame", padding=(12, 9))
        self._dot = ttk.Label(self, text="●", style="Idle.TLabel")
        self._dot.pack(side="left")
        self._label = ttk.Label(self, text="Ready", style="Idle.TLabel")
        self._label.pack(side="left", padx=(8, 0), fill="x", expand=True)

    def text(self) -> str:
        return str(self._label.cget("text"))

    def _show(self, text: str, style: str) -> None:
        self._label.configure(text=text, style=style)
        self._dot.configure(style=style)

    def set_idle(self, text: str = "Ready") -> None:
        self._show(text, "Idle.TLabel")

    def set_working(self, text: str = "Working...") -> None:
        self._show(text, "Working.TLabel")

    def set_success(self, text: str) -> None:
        self._show(text, "Success.TLabel")

    def set_error(self, text: str) -> None:
        self._show(text, "Error.TLabel")

    def set_warn(self, text: str) -> None:
        self._show(text, "Warn.TLabel")


def confirm(parent, title: str, message: str) -> bool:
    return messagebox.askyesno(title, message, icon="warning", parent=parent)


def guard_admin(status: StatusPane) -> bool:
    if admin.is_admin():
        return True
    status.set_error("Run as administrator required — restart the app as administrator.")
    return False


def copy_text(widget, text: str) -> None:
    widget.clipboard_clear()
    widget.clipboard_append(text)
