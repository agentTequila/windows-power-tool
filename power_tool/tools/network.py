import ipaddress
import queue
import re
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


def parse_adapters(text: str) -> list[str]:
    """Pull interface names from `netsh interface show interface` output.

    Blank lines and the header (it mentions "Admin") are skipped, and the
    name is the field after the last run of 2+ spaces, so multi-word
    names like "Ethernet 2" come through whole. Rows repeat and are
    deduped, first occurrence first.
    """
    adapters = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or "Admin" in stripped:
            continue
        name = re.split(r"\s{2,}", stripped)[-1].strip()
        if not name or name.replace("-", "") == "":
            continue  # the dashed rule under the header, minus its padding
        if name not in adapters:
            adapters.append(name)
    return adapters


def dhcp_commands(adapter: str) -> list[list[str]]:
    return [
        ["netsh", "interface", "ipv4", "set", "address",
         f"name={adapter}", "dhcp"],
        ["netsh", "interface", "ipv4", "set", "dns",
         f"name={adapter}", "dhcp"],
    ]


def _validated_ipv4(value: str, label: str) -> str:
    cleaned = str(value).strip()
    try:
        ipaddress.IPv4Address(cleaned)
    except ValueError as exc:
        raise ValueError(f"Invalid {label}: {cleaned!r}") from exc
    return cleaned


def static_commands(adapter: str, ip: str, mask: str, gateway: str,
                    dns_primary: str, dns_alt: str) -> list[list[str]]:
    primary = str(dns_primary).strip()
    if not primary:
        raise ValueError("DNS server is required")
    address = _validated_ipv4(ip, "IP address")
    clean_mask = str(mask).strip()
    clean_gateway = str(gateway).strip()
    if clean_gateway:
        clean_gateway = _validated_ipv4(clean_gateway, "gateway")
    else:
        clean_gateway = "gateway=none"
    primary = _validated_ipv4(primary, "DNS server")
    alt = ""
    if str(dns_alt).strip():
        alt = _validated_ipv4(dns_alt, "DNS server")
    try:
        ipaddress.IPv4Network(f"{address}/{clean_mask}", strict=False)
    except ValueError as exc:
        raise ValueError(f"Invalid subnet mask: {clean_mask!r}") from exc
    commands = [
        ["netsh", "interface", "ipv4", "set", "address",
         f"name={adapter}", "static", address, clean_mask, clean_gateway],
        ["netsh", "interface", "ipv4", "set", "dns",
         f"name={adapter}", "static", primary],
    ]
    if alt:
        commands.append(["netsh", "interface", "ipv4", "add", "dns",
                         f"name={adapter}", alt, "index=2"])
    return commands


def run_ping_session(host: str, stop_event, put, count: int = 10,
                     interval: float = 1.0) -> dict:
    """Ping `host` at most `count` times, pacing between pings.

    After each non-final iteration the worker paces with
    `stop_event.wait(interval)` (never `time.sleep`), so Stop takes
    effect immediately, even mid-pace. The `finally` emits the done
    sentinel exactly once — payload gains the planned `count` — then any
    exception propagates past it (dormant in practice: runner.run never
    raises).
    """
    sent = 0
    lost = 0
    try:
        for _ in range(count):
            if stop_event.is_set():
                break
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
            if sent < count and stop_event.wait(interval):
                break
    finally:
        put(("done", {"sent": sent, "lost": lost, "count": count}))
    return {"sent": sent, "lost": lost, "count": count}


def action_commands(name: str) -> list[list[str]]:
    return ACTIONS[name]


ADAPTERS_CMD = ["netsh", "interface", "show", "interface"]


def fetch_adapters() -> list[str]:
    result = runner.run(ADAPTERS_CMD, timeout=30)
    return parse_adapters(result.stdout)


def show_config(adapter: str) -> str:
    result = runner.run(
        ["netsh", "interface", "ipv4", "show", "config",
         f"name={adapter}"], timeout=30)
    if result.returncode != 0:
        detail = (result.stderr.strip() or result.stdout.strip()
                  or f"exit code {result.returncode}")
        raise RuntimeError(f"Show configuration failed: {detail}")
    return result.stdout.strip()


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
            text="Networking acting up? Flush the DNS cache, renew the "
                 "IP, or watch a ping stream by itself. The IP "
                 "Configuration box below is where you flip an adapter "
                 "between automatic and static addresses when DHCP "
                 "isn't cutting it.",
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
        self._ping_count = ttk.Spinbox(ping_row, from_=1, to=120, width=5)
        self._ping_count.set("10")
        self._ping_count.grid(row=0, column=2, padx=8)
        self._ping_button = ttk.Button(
            ping_row, text="Start", style="Accent.TButton",
            command=self._start_ping)
        self._ping_button.grid(row=0, column=3)
        self._ping_stats = ttk.Label(
            ping_row, style="Dim.TLabel", text="Pinged 0 · lost 0 · loss 0%")
        self._ping_stats.grid(row=0, column=4, padx=(10, 0))
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

        ip_section = ttk.LabelFrame(self, text="IP Configuration",
                                    padding=10)
        ip_section.pack(fill="x", pady=(0, 10))
        adapter_row = ttk.Frame(ip_section)
        adapter_row.pack(fill="x", pady=(0, 6))
        ttk.Label(adapter_row, text="Adapter:").pack(side="left")
        self._adapter_combo = ttk.Combobox(adapter_row, state="readonly",
                                           width=28)
        self._adapter_combo.pack(side="left", padx=8)
        self._refresh_button = ttk.Button(
            adapter_row, text="Refresh", command=self._refresh_adapters)
        self._refresh_button.pack(side="left")

        mode_row = ttk.Frame(ip_section)
        mode_row.pack(fill="x", pady=(0, 6))
        ttk.Label(mode_row, text="Mode:").pack(side="left")
        self._mode_var = tk.StringVar(value="DHCP")
        self._mode_radios = []
        for value, label in (("DHCP", "DHCP (automatic)"),
                             ("Static", "Static")):
            radio = ttk.Radiobutton(
                mode_row, text=label, value=value, variable=self._mode_var,
                command=self._mode_changed)
            radio.pack(side="left", padx=(8, 0))
            self._mode_radios.append(radio)

        fields = ttk.Frame(ip_section)
        fields.pack(fill="x", pady=(0, 6))
        self._ip_entry = self._make_field(fields, 0, "IP address:")
        self._mask_entry = self._make_field(fields, 1, "Subnet mask:")
        self._gw_entry = self._make_field(fields, 2, "Gateway (blank = none):")
        self._dns_entry = self._make_field(fields, 3, "DNS server:")
        self._dns_alt_entry = self._make_field(fields, 4,
                                               "DNS alternate (optional):")

        buttons = ttk.Frame(ip_section)
        buttons.pack(anchor="w", pady=(4, 0))
        self._show_config_button = ttk.Button(
            buttons, text="Show current config", command=self._show_config)
        self._show_config_button.pack(side="left", padx=(0, 8))
        self._apply_button = ttk.Button(
            buttons, text="Apply", style="Accent.TButton",
            command=self._apply)
        self._apply_button.pack(side="left")
        self._mode_changed()  # entries start disabled under DHCP

        self._output = tk.Text(
            self, wrap="none", height=18, font=("Consolas", 10),
            bg=palette["entry_bg"], fg=palette["fg"],
            insertbackground=palette["fg"], relief="flat", padx=10, pady=8,
            state="disabled")
        self._output.pack(fill="both", expand=True)
        theme.observe(self._on_theme)

        self.status = widgets.StatusPane(self)
        self.status.pack(fill="x", pady=(10, 0))

    def _make_field(self, parent, row: int, label: str) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w",
                                           pady=2)
        entry = ttk.Entry(parent, width=32)
        entry.grid(row=row, column=1, sticky="w", padx=8, pady=2)
        return entry

    def _mode_changed(self) -> None:
        state = "normal" if self._mode_var.get() == "Static" else "disabled"
        for entry in (self._ip_entry, self._mask_entry, self._gw_entry,
                      self._dns_entry, self._dns_alt_entry):
            entry.configure(state=state)

    def _refresh_adapters(self) -> None:
        self._set_busy(True)
        self.status.set_working("Loading adapters...")
        tasks.BackgroundTask(
            self, work=fetch_adapters, on_done=self._adapters_loaded,
            on_error=self._error).start()

    def _adapters_loaded(self, adapters: list[str]) -> None:
        self._set_busy(False)
        self._adapter_combo.configure(values=list(adapters))
        if adapters:
            self._adapter_combo.set(adapters[0])
            self.status.set_success(f"{len(adapters)} adapter(s) found.")
        else:
            self._adapter_combo.set("")
            self.status.set_warn("No network adapters found.")

    def _selected_adapter(self) -> str:
        return str(self._adapter_combo.get()).strip()

    def _show_config(self) -> None:
        adapter = self._selected_adapter()
        if not adapter:
            self.status.set_error("Select an adapter first.")
            return
        self._set_busy(True)
        self.status.set_working(f"Reading config for {adapter}...")
        tasks.BackgroundTask(
            self, work=partial(show_config, adapter),
            on_done=self._config_done, on_error=self._error).start()

    def _config_done(self, text: str) -> None:
        self._set_busy(False)
        self._append(text)
        self.status.set_success("Configuration shown below.")

    def _apply(self) -> None:
        adapter = self._selected_adapter()
        if not adapter:
            self.status.set_error("Select an adapter first.")
            return
        if self._mode_var.get() == "Static":
            try:
                commands = static_commands(
                    adapter, self._ip_entry.get(), self._mask_entry.get(),
                    self._gw_entry.get(), self._dns_entry.get(),
                    self._dns_alt_entry.get())
            except ValueError as exc:
                self.status.set_error(str(exc))
                return
        else:
            commands = dhcp_commands(adapter)
        if not widgets.guard_admin(self.status):
            return
        message = (f"Apply IP configuration to {adapter}?\n\n"
                   + "\n".join(" ".join(cmd) for cmd in commands))
        if not widgets.confirm(self, "Apply IP configuration", message):
            self.status.set_idle("Cancelled.")
            return
        self._set_busy(True)
        self.status.set_working("Applying IP configuration...")
        tasks.BackgroundTask(
            self, work=partial(run_commands, commands),
            on_done=self._apply_done, on_error=self._error).start()

    def _apply_done(self, text: str) -> None:
        self._set_busy(False)  # re-enable FIRST so the UI never wedges
        self._append(text)
        self.status.set_success("IP configuration applied.")

    def _on_theme(self, palette: dict) -> None:
        for widget in (self._output, self._ping_output):
            widget.configure(bg=palette["entry_bg"], fg=palette["fg"],
                              insertbackground=palette["fg"])

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for button in self._action_buttons.values():
            button.configure(state=state)
        self._ping_button.configure(state=state)
        for button in (self._refresh_button, self._show_config_button,
                       self._apply_button):
            button.configure(state=state)
        # Inputs too — a ping shouldn't leave the host field editable.
        for widget in (self._ping_entry, self._ping_count):
            widget.configure(state=state)
        self._adapter_combo.configure(
            state="disabled" if busy else "readonly")
        for radio in self._mode_radios:
            radio.configure(state=state)
        if busy:
            for entry in (self._ip_entry, self._mask_entry, self._gw_entry,
                          self._dns_entry, self._dns_alt_entry):
                entry.configure(state="disabled")
        else:
            # Static entries are mode-governed: DHCP keeps them disabled.
            self._mode_changed()

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
        try:
            count = max(1, min(120, int(self._ping_count.get())))
        except (TypeError, ValueError):
            count = 10  # defensive: non-integer input falls back to default
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
            args=(host, self._ping_stop, self._ping_queue.put, count),
            daemon=True).start()
        self.after(100, self._drain_ping)

    def _stop_ping(self) -> None:
        """Request a stop; it takes effect instantly while pacing between
        pings (stop_event.wait), or after the current in-flight ping
        iteration (bounded ≤ ~8s by the runner timeout, typically ~2s) —
        the ping process is not killed mid-ping."""
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
