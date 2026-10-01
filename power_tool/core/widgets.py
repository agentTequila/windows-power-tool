from tkinter import messagebox, ttk

from power_tool.core import admin


class StatusPane(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, style="Panel.TFrame", padding=(10, 8))
        self._label = ttk.Label(self, text="Ready", style="Idle.TLabel")
        self._label.pack(fill="x")

    def text(self) -> str:
        return str(self._label.cget("text"))

    def _show(self, text: str, style: str) -> None:
        self._label.configure(text=text, style=style)

    def set_idle(self, text: str = "Ready") -> None:
        self._show(text, "Idle.TLabel")

    def set_working(self, text: str = "Working...") -> None:
        self._show(text, "Working.TLabel")

    def set_success(self, text: str) -> None:
        self._show(text, "Success.TLabel")

    def set_error(self, text: str) -> None:
        self._show(text, "Error.TLabel")


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
