import os
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import ttk

from power_tool.core import runner, theme, widgets

MODES = {
    "powershell": ["powershell.exe", "-NoLogo", "-NonInteractive", "-Command"],
    "cmd": ["cmd.exe", "/d", "/s", "/c"],
}


def shell_argv(mode: str, command: str) -> list[str]:
    try:
        prefix = MODES[mode]
    except KeyError:
        raise ValueError(f"unknown mode: {mode}") from None
    return prefix + [command]


def read_stream(proc, put) -> int | None:
    """Push decoded stdout+stderr lines to `put` until EOF; return exit code.

    Runs on a background thread — touches the queue only, never Tk.
    """
    try:
        for raw in proc.stdout:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            put(("line", str(raw).rstrip("\r\n")))
    finally:
        try:
            code = proc.wait(timeout=10)
        except Exception:
            code = None
        put(("done", code))


class ConsoleFrame(ttk.Frame):
    _MAX_LINES = 2000

    def __init__(self, parent):
        super().__init__(parent, padding=16)
        ttk.Label(self, text="Console", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            self, wraplength=660, style="Dim.TLabel",
            text="Run one-off PowerShell or CMD commands without leaving "
                 "the app. Output streams below; Stop kills the whole "
                 "command tree. Up/Down recalls earlier commands.",
        ).pack(anchor="w", pady=(6, 12))

        mode_row = ttk.Frame(self)
        mode_row.pack(anchor="w", pady=(0, 8))
        self._mode = tk.StringVar(value="powershell")
        self._mode_radios = []
        for label, value in (("PowerShell", "powershell"), ("CMD", "cmd")):
            radio = ttk.Radiobutton(mode_row, text=label,
                                    variable=self._mode, value=value)
            radio.pack(side="left", padx=(0, 10))
            self._mode_radios.append(radio)

        entry_row = ttk.Frame(self)
        entry_row.pack(fill="x", pady=(0, 8))
        self._command_entry = ttk.Entry(entry_row)
        self._command_entry.pack(side="left", fill="x", expand=True,
                                 padx=(0, 8))
        self._command_entry.bind("<Return>", self._run)
        self._command_entry.bind("<Up>", self._recall_up)
        self._command_entry.bind("<Down>", self._recall_down)

        buttons = ttk.Frame(self)
        buttons.pack(anchor="w", pady=(0, 10))
        self._run_button = ttk.Button(buttons, text="Run",
                                      style="Accent.TButton",
                                      command=self._run)
        self._run_button.pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Clear",
                   command=self._clear).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Open PowerShell here",
                   command=self._open_powershell).pack(side="left",
                                                       padx=(0, 8))
        ttk.Button(buttons, text="Open CMD here",
                   command=self._open_cmd).pack(side="left")

        palette = theme.current_palette()
        self._output = tk.Text(
            self, wrap="none", height=14, font=("Consolas", 10),
            bg=palette["entry_bg"], fg=palette["fg"],
            insertbackground=palette["fg"], relief="flat", padx=10, pady=8,
            state="disabled")
        self._output.pack(fill="both", expand=True)
        theme.observe(self._on_theme)

        self.status = widgets.StatusPane(self)
        self.status.pack(fill="x", pady=(10, 0))

        self._queue = queue.Queue()
        self._stop_event = None
        self._proc = None
        self._pid = None
        self._running = False
        self._history: list[str] = []
        self._history_index = 0

    def _on_theme(self, palette: dict) -> None:
        self._output.configure(bg=palette["entry_bg"], fg=palette["fg"],
                               insertbackground=palette["fg"])

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self._command_entry.configure(state=state)
        for radio in self._mode_radios:
            radio.configure(state=state)

    def append_output(self, text: str) -> None:
        self._output.configure(state="normal")
        self._output.insert("end", text + "\n")
        # Tk's end-1c lands one line past the last real line when the buffer
        # ends with "\n", so real line count is that index minus one.
        lines = int(float(self._output.index("end-1c"))) - 1
        excess = lines - self._MAX_LINES
        if excess > 0:
            self._output.delete("1.0", f"{excess + 1}.0")
        self._output.see("end")
        self._output.configure(state="disabled")

    def _clear(self) -> None:
        self._output.configure(state="normal")
        self._output.delete("1.0", "end")
        self._output.configure(state="disabled")

    def _remember(self, command: str) -> None:
        cleaned = command.strip()
        if not cleaned:
            return
        if self._history and self._history[-1] == cleaned:
            return
        self._history.append(cleaned)
        self._history_index = len(self._history)

    def _recall_up(self, event=None):
        if self._history and self._history_index > 0:
            self._history_index -= 1
            self._command_entry.delete(0, "end")
            self._command_entry.insert(0, self._history[self._history_index])
        return "break"

    def _recall_down(self, event=None):
        if self._history:
            if self._history_index < len(self._history) - 1:
                self._history_index += 1
                command = self._history[self._history_index]
            else:
                self._history_index = len(self._history)
                command = ""
            self._command_entry.delete(0, "end")
            self._command_entry.insert(0, command)
        return "break"

    def _run(self, event=None):
        if self._running:
            return
        command = self._command_entry.get().strip()
        if not command:
            self.status.set_error("Type a command to run first.")
            return
        argv = shell_argv(self._mode.get(), command)
        self._remember(command)
        self._queue = queue.Queue()
        self._stop_event = threading.Event()
        self._set_busy(True)  # entry + radios disabled
        # Run button becomes the enabled Stop toggle; re-entry is guarded
        self._run_button.configure(text="Stop", command=self._stop)
        self.status.set_working(f"Running: {command}")
        self._clear()
        try:
            proc = subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=runner.CREATE_NO_WINDOW)
        except OSError as exc:
            self._running = False
            self._set_busy(False)
            self._run_button.configure(text="Run", command=self._run)
            self.status.set_error(str(exc))
            return
        self._proc = proc
        self._pid = proc.pid
        self._running = True
        # Background thread: queue only, never Tk.
        threading.Thread(target=read_stream,
                         args=(proc, self._queue.put),
                         daemon=True).start()
        self.after(100, self._drain)

    def _stop(self):
        if not self._running or self._pid is None:
            return
        if self._stop_event is not None:
            self._stop_event.set()
        pid = self._pid
        # taskkill can block up to 15s — never run it on the GUI thread.
        threading.Thread(
            target=lambda: runner.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"], timeout=15),
            daemon=True).start()
        # Finalize now instead of waiting for the reader's "done" sentinel:
        # a grandchild can hold stdout open after taskkill, so the sentinel
        # may never arrive. _finish is idempotent (guarded by _running).
        self._finish(None)

    def _drain(self):
        finalized = False
        for _ in range(200):
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            kind = item[0]
            if kind == "line":
                self.append_output(str(item[1]))
            elif kind == "done":
                self._finish(item[1])
                finalized = True
        # After a Stop finalize, drain any queued lines one last time, then
        # stop rescheduling — the (abandoned, daemon) reader may never EOF.
        if not finalized and (self._running or not self._queue.empty()):
            self.after(100, self._drain)

    def _finish(self, returncode):
        if not self._running:
            return  # already finalized (e.g. by Stop) — ignore late "done"
        self._set_busy(False)  # re-enable FIRST so the UI never wedges
        self._running = False
        self._proc = None
        self._pid = None
        self._run_button.configure(text="Run", command=self._run)
        stopped = self._stop_event is not None and self._stop_event.is_set()
        self._stop_event = None
        if stopped:
            self.status.set_success("Command stopped.")
        elif returncode in (0, None):
            self.status.set_success("Command finished.")
        else:
            excerpt = self._output.get("1.0", "end-1c")[:200]
            self.status.set_error(
                f"Command exited with code {returncode}: {excerpt}")

    def _open_powershell(self):
        cwd = os.environ.get("USERPROFILE") or None
        runner.start_detached(["powershell.exe", "-NoExit"], cwd=cwd)

    def _open_cmd(self):
        cwd = os.environ.get("USERPROFILE") or None
        runner.start_detached(["cmd.exe", "/k"], cwd=cwd)


def create(parent: ttk.Frame) -> ttk.Frame:
    return ConsoleFrame(parent)
