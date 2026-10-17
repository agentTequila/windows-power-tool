import queue
import threading
import tkinter as tk
from functools import partial
from tkinter import ttk

from power_tool.core import runner, tasks, theme, widgets

ACTIONS = {
    "Flush DNS": [["ipconfig", "/flushdns"]],
    "Release IP": [["ipconfig", "/release"]],
    "Renew IP": [["ipconfig", "/renew"]],
    "Release + Renew": [["ipconfig", "/release"], ["ipconfig", "/renew"]],
}


def ping_once_args(host: str) -> list[str]:
    cleaned = str(host).strip()
    if not cleaned:
        raise ValueError("host is empty")
    return ["ping", "-n", "1", "-w", "2000", cleaned]


def run_ping_session(host: str, stop_event, put) -> dict:
    """Ping `host` until stop_event is set; never raises past `put("done")`."""
    sent = 0
    lost = 0
    try:
        while not stop_event.is_set():
            result = runner.run(ping_once_args(host), timeout=8)
            sent += 1
            if (result.returncode != 0
                    or "timed out" in result.stdout.lower()):
                lost += 1
            lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
            if not lines:
                lines = [ln for ln in result.stderr.splitlines()
                         if ln.strip()]
            if not lines:
                lines = [f"ping exited with code {result.returncode}"]
            for line in lines:
                put(("line", line))
            put(("stats", sent, lost))
    finally:
        put(("done", {"sent": sent, "lost": lost}))
    return {"sent": sent, "lost": lost}


def action_commands(name: str) -> list[list[str]]:
    return ACTIONS[name]


def run_commands(commands: list[list[str]]) -> str:
    blocks = []
    for cmd in commands:
        result = runner.run(cmd, timeout=60)
        if result.returncode != 0:
            detail = (result.stderr.strip() or result.stdout.strip()
                      or f"exit code {result.returncode}")
            raise RuntimeError(f"{' '.join(cmd)} failed: {detail}")
        blocks.append(f"$ {' '.join(cmd)}\n{result.stdout.strip()}")
    return "\n\n".join(blocks)


class NetworkFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=16)
        ttk.Label(self, text="Network", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            self, wraplength=660, style="Dim.TLabel",
            text="Fix everyday network problems: flush the DNS cache, "
                 "release or renew the IP address, and ping a host. "
                 "Output appears below each run.",
        ).pack(anchor="w", pady=(6, 12))

        actions = ttk.Frame(self)
        actions.pack(anchor="w", pady=(0, 10))
        self._action_names = list(ACTIONS)
        self._action_buttons = {}
        for index, name in enumerate(self._action_names):
            button = ttk.Button(actions, text=name,
                                command=lambda n=name: self._action(n))
            button.grid(row=0, column=index, padx=(0, 8))
            self._action_buttons[name] = button

        ping_row = ttk.Frame(self)
        ping_row.pack(anchor="w", pady=(0, 10))
        ttk.Label(ping_row, text="Live ping:").grid(row=0, column=0, sticky="w")
        self._ping_entry = ttk.Entry(ping_row, width=30)
        self._ping_entry.grid(row=0, column=1, padx=8)
        self._ping_button = ttk.Button(
            ping_row, text="Start", style="Accent.TButton",
            command=self._start_ping)
        self._ping_button.grid(row=0, column=2)
        self._ping_stats = ttk.Label(
            ping_row, style="Dim.TLabel", text="Pinged 0 · lost 0 · loss 0%")
        self._ping_stats.grid(row=0, column=3, padx=(10, 0))
        self._ping_queue = queue.Queue()
        self._ping_stop = None
        self._ping_running = False

        palette = theme.current_palette()
        self._ping_output = tk.Text(
            self, wrap="none", height=6, font=("Consolas", 10),
            bg=palette["entry_bg"], fg=palette["fg"],
            insertbackground=palette["fg"], relief="flat", padx=10, pady=8,
            state="disabled")
        self._ping_output.pack(fill="x", pady=(0, 10))
        self._output = tk.Text(
            self, wrap="none", height=18, font=("Consolas", 10),
            bg=palette["entry_bg"], fg=palette["fg"],
            insertbackground=palette["fg"], relief="flat", padx=10, pady=8,
            state="disabled")
        self._output.pack(fill="both", expand=True)
        theme.observe(self._on_theme)

        self.status = widgets.StatusPane(self)
        self.status.pack(fill="x", pady=(10, 0))

    def _on_theme(self, palette: dict) -> None:
        for widget in (self._output, self._ping_output):
            widget.configure(bg=palette["entry_bg"], fg=palette["fg"],
                              insertbackground=palette["fg"])

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for button in self._action_buttons.values():
            button.configure(state=state)
        self._ping_button.configure(state=state)

    def _append(self, text: str) -> None:
        self._output.configure(state="normal")
        self._output.insert("end", text + "\n\n")
        self._output.see("end")
        self._output.configure(state="disabled")

    def _run(self, commands: list[list[str]], working: str) -> None:
        if not widgets.guard_admin(self.status):
            return
        self._set_busy(True)
        self.status.set_working(working)
        tasks.BackgroundTask(
            self, work=partial(run_commands, commands),
            on_done=self._done, on_error=self._error).start()

    def _action(self, name: str) -> None:
        try:
            commands = action_commands(name)
        except KeyError:
            self.status.set_error(f"Unknown action: {name}")
            return
        self._run(commands, f"Running {name}...")

    def _append_ping(self, text: str) -> None:
        self._ping_output.configure(state="normal")
        self._ping_output.insert("end", text + "\n")
        self._ping_output.see("end")
        self._ping_output.configure(state="disabled")

    @staticmethod
    def _loss_percent(sent: int, lost: int) -> int:
        return int(round(100 * lost / sent)) if sent else 0

    def _start_ping(self) -> None:
        if self._ping_running:
            return
        host = self._ping_entry.get().strip()
        try:
            ping_once_args(host)
        except ValueError:
            self.status.set_error("Enter a host name or IP address to ping.")
            return
        self._ping_queue = queue.Queue()
        self._ping_stop = threading.Event()
        self._ping_running = True
        self._set_busy(True)
        self._ping_button.configure(
            text="Stop", state="normal", command=self._stop_ping)
        self._ping_stats.configure(text="Pinged 0 · lost 0 · loss 0%")
        self._ping_output.configure(state="normal")
        self._ping_output.delete("1.0", "end")
        self._ping_output.configure(state="disabled")
        self._append_ping(f"Pinging {host}...")
        self.status.set_working(f"Pinging {host} — streaming replies...")
        threading.Thread(
            target=run_ping_session,
            args=(host, self._ping_stop, self._ping_queue.put),
            daemon=True).start()
        self.after(100, self._drain_ping)

    def _stop_ping(self) -> None:
        if self._ping_stop is not None:
            self._ping_stop.set()
        self.status.set_working(
            "Stopping ping — waiting for the current reply...")

    def _drain_ping(self) -> None:
        finalized = False
        for _ in range(50):
            try:
                item = self._ping_queue.get_nowait()
            except queue.Empty:
                break
            kind = item[0]
            if kind == "line":
                self._append_ping(str(item[1]))
            elif kind == "stats":
                sent, lost = int(item[1]), int(item[2])
                percent = self._loss_percent(sent, lost)
                self._ping_stats.configure(
                    text=f"Pinged {sent} · lost {lost} · loss {percent}%")
            elif kind == "done":
                self._finish_ping(item[1])
                finalized = True
        if not finalized:
            self.after(100, self._drain_ping)

    def _finish_ping(self, summary: dict) -> None:
        sent = int(summary.get("sent", 0))
        lost = int(summary.get("lost", 0))
        percent = self._loss_percent(sent, lost)
        self._set_busy(False)  # re-enable FIRST so the UI never wedges
        self._ping_running = False
        self._ping_stop = None
        self._ping_button.configure(text="Start", command=self._start_ping)
        self._ping_stats.configure(
            text=f"Pinged {sent} · lost {lost} · loss {percent}%")
        message = f"Pinged {sent} · lost {lost} ({percent}%) — stopped."
        self._append_ping(message)
        self.status.set_success(message)

    def _done(self, text: str) -> None:
        self._set_busy(False)
        self._append(text)
        self.status.set_success("Done.")

    def _error(self, exc: BaseException) -> None:
        self._set_busy(False)
        self.status.set_error(str(exc))


def create(parent: ttk.Frame) -> ttk.Frame:
    return NetworkFrame(parent)
