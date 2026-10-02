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


def ping_args(host: str) -> list[str]:
    cleaned = str(host).strip()
    if not cleaned:
        raise ValueError("host is empty")
    return ["ping", "-n", "4", cleaned]


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
        ttk.Label(ping_row, text="Ping host:").pack(side="left")
        self._ping_entry = ttk.Entry(ping_row, width=30)
        self._ping_entry.pack(side="left", padx=8)
        self._ping_button = ttk.Button(
            ping_row, text="Ping", style="Accent.TButton", command=self._ping)
        self._ping_button.pack(side="left")

        palette = theme.current_palette()
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
        self._output.configure(bg=palette["entry_bg"], fg=palette["fg"],
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

    def _ping(self) -> None:
        try:
            commands = [ping_args(self._ping_entry.get())]
        except ValueError:
            self.status.set_error("Enter a host name or IP address to ping.")
            return
        self._run(commands, "Pinging...")

    def _done(self, text: str) -> None:
        self._set_busy(False)
        self._append(text)
        self.status.set_success("Done.")

    def _error(self, exc: BaseException) -> None:
        self._set_busy(False)
        self.status.set_error(str(exc))


def create(parent: ttk.Frame) -> ttk.Frame:
    return NetworkFrame(parent)
