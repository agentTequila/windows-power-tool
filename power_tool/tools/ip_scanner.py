"""IP/port scanner: CIDR parsing, threaded sweep, ARP merge, TCP
connect scan, plus the IP Scanner tab frame.

The pure layer never raises: unexpected failures surface as an
("error", ...) sentinel instead of an exception. The frame feeds
addresses/ports in, gets sentinel-tagged messages out via `put`, and
can stop early through `stop_event`.
"""

import ipaddress
import queue
import re
import socket
import threading
import time
import tkinter as tk
from tkinter import ttk

from power_tool.core import runner, theme, widgets

MAX_ADDRESSES = 4096

_BLOCK_HINT = "Enter an IPv4 block like 192.168.1.0/24"
_CAP_HINT = (f"That block is too big — {MAX_ADDRESSES} addresses max. "
             "Try a smaller range.")

_IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_MAC_RE = re.compile(r"(?:[0-9a-fA-F]{2}[-:]){5}[0-9a-fA-F]{2}")


def normalize_host(host: str) -> str:
    """Trim whitespace and a DNS root dot from a host or block target.

    People paste addresses copied from DNS output ("router.lan.") or type
    a trailing dot by habit. Windows' resolver rejects "192.168.1.1." as
    an address, so the tool accepts the dotted form too.
    """
    return str(host).strip().rstrip(".")


def parse_block(text: str) -> list[str]:
    """Expand a single IPv4 address or CIDR block into usable hosts.

    Network/broadcast are excluded by `hosts()` (/31 and /32 keep every
    address). Over the cap, or anything non-IPv4, raises ValueError.
    """
    cleaned = normalize_host(text)
    try:
        network = ipaddress.ip_network(cleaned, strict=False)
    except ValueError as exc:
        raise ValueError(_BLOCK_HINT) from exc
    if network.version != 4:
        raise ValueError(_BLOCK_HINT)
    if network.num_addresses > MAX_ADDRESSES:
        raise ValueError(_CAP_HINT)
    return [str(address) for address in network.hosts()]


def parse_arp_table(text: str) -> dict[str, str]:
    """Map IP -> uppercase dashed MAC from `arp -a` output.

    Lines without both an IPv4 and a MAC (headers, interface lines,
    junk) are skipped.
    """
    table: dict[str, str] = {}
    for line in str(text).splitlines():
        ip_match = _IPV4_RE.search(line)
        mac_match = _MAC_RE.search(line)
        if ip_match is None or mac_match is None:
            continue
        mac = mac_match.group(0).upper().replace(":", "-")
        table[ip_match.group(0)] = mac
    return table


def ping_ms(ip: str) -> int | None:
    """Ping once; elapsed milliseconds on success, None otherwise.

    The return code decides — ping's output text is localized, so it is
    never parsed. `runner.run` converts timeout/OSError into a Result,
    so this does not raise either.
    """
    started = time.monotonic()
    result = runner.run(["ping", "-n", "1", "-w", "500", ip], timeout=5)
    elapsed_ms = int(round((time.monotonic() - started) * 1000))
    if result.returncode != 0:
        return None
    return max(0, elapsed_ms)


def resolve_host(ip: str) -> str:
    try:
        hostname = socket.gethostbyaddr(ip)[0].rstrip(".")
        return hostname or ip
    except OSError:
        return ip


def _default_arp_out() -> str:
    return runner.run(["arp", "-a"], timeout=10).stdout


def _ip_order(ip: str) -> bytes:
    return ipaddress.ip_address(ip).packed


def run_sweep(addresses: list[str], stop_event, put, workers: int = 64,
              probe=None, arp_out=None, resolver=None) -> None:
    """Sweep `addresses` with up to `workers` threads; never raises.

    Emits ("progress", done, total) per completed probe and exactly one
    terminal sentinel: ("done", payload) on completion or early stop,
    ("error", str(exc)) if anything outside the workers fails (then no
    done). Payload: hosts = ping-alive ∪ in-block ARP hits (ARP-only ⇒
    ms None), free = checked addresses that answered nothing (verified
    free), unchecked = addresses a stop left unprobed, scanned = probes
    completed. On a complete sweep unchecked is empty.
    """
    probe = ping_ms if probe is None else probe
    arp_out = _default_arp_out if arp_out is None else arp_out
    resolver = resolve_host if resolver is None else resolver

    lock = threading.Lock()
    state = {"done": 0, "alive": {}, "checked": set(), "failure": None,
             "emitted": False}
    abort = threading.Event()

    def emit_terminal(message) -> None:
        # Lock-guarded flag: exactly one terminal sentinel, even when a
        # stop races completion or failure lands mid-sweep.
        with lock:
            if state["emitted"]:
                return
            state["emitted"] = True
        put(message)

    def worker() -> None:
        while not abort.is_set() and not stop_event.is_set():
            try:
                ip = work.get_nowait()
            except queue.Empty:
                return
            try:
                ms = probe(ip)
            except BaseException as exc:  # never raise out of a worker
                with lock:
                    if state["failure"] is None:
                        state["failure"] = exc
                abort.set()
                return
            with lock:
                if ms is not None:
                    state["alive"][ip] = ms
                state["checked"].add(ip)
                state["done"] += 1
                done, total = state["done"], total_count
            put(("progress", done, total))

    try:
        total_count = len(addresses)
        work: queue.Queue = queue.Queue()
        for ip in addresses:
            work.put(ip)
        pool = [
            threading.Thread(target=worker, daemon=True)
            for _ in range(min(max(workers, 1), total_count))
        ]
        for thread in pool:
            thread.start()
        for thread in pool:
            thread.join()

        with lock:
            failure = state["failure"]
            alive = dict(state["alive"])
            checked = set(state["checked"])
            scanned = state["done"]

        if failure is not None:
            emit_terminal(("error", str(failure)))
            return

        address_set = set(addresses)
        unchecked = address_set - checked
        # ARP is merged only when every probe finished: on an early stop
        # the partial payload stays honest about what was not checked.
        arp_hits = {} if unchecked else parse_arp_table(arp_out())
        host_ips = set(alive) | {ip for ip in arp_hits if ip in address_set}
        hosts = [
            {"ip": ip, "hostname": resolver(ip), "mac": arp_hits.get(ip),
             "ms": alive.get(ip)}
            for ip in sorted(host_ips, key=_ip_order)
        ]
        # "free" means verified free: probed and answered nothing. An
        # address a stop left unprobed belongs in "unchecked", never here.
        free = [ip for ip in sorted(checked, key=_ip_order)
                if ip not in host_ips]
        unchecked_list = sorted(unchecked, key=_ip_order)
        emit_terminal(("done", {"hosts": hosts, "free": free,
                                "unchecked": unchecked_list,
                                "scanned": scanned}))
    except BaseException as exc:  # never raise out of run_sweep
        emit_terminal(("error", str(exc)))


MAX_PORTS = 4096

_PORT_SPEC_HINT = "Enter ports like 1-1024 or 22,80,443"
_PORT_CAP_HINT = (f"That's more than {MAX_PORTS} ports — scan a smaller "
                  "range.")


def parse_port_spec(text: str) -> list[int]:
    """Expand "22,80,443" / "1-1024" spec text into a sorted port list.

    Values must be 1-65535, range starts may not exceed their ends, and
    the total after de-duplication must fit within `MAX_PORTS`. Anything
    else — blanks, junk tokens, inverted ranges, over-cap — raises
    ValueError with a fixable-sounding hint.
    """
    seen: set[int] = set()
    for raw_token in str(text).split(","):
        token = raw_token.strip()
        try:
            if "-" in token:
                start_s, _sep, end_s = token.partition("-")
                start, end = int(start_s), int(end_s)
                if not 1 <= start <= end <= 65535:
                    raise ValueError
                seen.update(range(start, end + 1))
            else:
                port = int(token)
                if not 1 <= port <= 65535:
                    raise ValueError
                seen.add(port)
        except ValueError as exc:
            raise ValueError(_PORT_SPEC_HINT) from exc
    ports = sorted(seen)
    if len(ports) > MAX_PORTS:
        raise ValueError(_PORT_CAP_HINT)
    return ports


def port_service(port: int) -> str:
    """Well-known TCP service name for `port`, or "-" when unnamed."""
    try:
        return socket.getservbyport(port, "tcp")
    except OSError:
        return "-"


def run_port_scan(host: str, ports: list[int], stop_event, put,
                  workers: int = 64, connector=None) -> None:
    """TCP connect-scan `ports` on `host` with up to `workers` threads.

    Never raises. Emits ("progress", done, total) per attempted port and
    exactly one terminal sentinel: ("done", payload) on completion or
    early stop, ("error", str(exc)) if the host will not resolve or a
    connector failure is anything other than a closed port (refused,
    timed out, unreachable, ...). Payload: open = sorted (port, service)
    pairs, scanned = ports attempted. `connector` is a test seam.
    """
    connector = socket.create_connection if connector is None else connector
    host = normalize_host(host)

    try:
        if not host:
            put(("error", "Enter a host name or IP address."))
            return
        # Resolve up front so an unusable host fails fast with a clear
        # message instead of surfacing as a per-port gaierror.
        try:
            socket.getaddrinfo(host, None)
        except OSError:
            put(("error", f"Cannot resolve {host}"))
            return
    except BaseException as exc:  # never raise out of run_port_scan
        put(("error", str(exc)))
        return

    lock = threading.Lock()
    state = {"done": 0, "open": {}, "failure": None, "emitted": False}
    abort = threading.Event()

    def emit_terminal(message) -> None:
        # Lock-guarded flag: exactly one terminal sentinel, even when a
        # stop races completion or a failure lands mid-scan.
        with lock:
            if state["emitted"]:
                return
            state["emitted"] = True
        put(message)

    def worker() -> None:
        while not abort.is_set() and not stop_event.is_set():
            try:
                port = work.get_nowait()
            except queue.Empty:
                return
            try:
                sock = connector((host, port), timeout=0.4)
            except OSError:
                # Refused / timed out / unreachable: closed port, and a
                # normal scan result rather than a failure.
                with lock:
                    state["done"] += 1
                    done, total = state["done"], total_count
                put(("progress", done, total))
                continue
            except BaseException as exc:  # never raise out of a worker
                with lock:
                    if state["failure"] is None:
                        state["failure"] = exc
                abort.set()
                return
            try:
                try:
                    with lock:
                        state["open"][port] = port_service(port)
                        state["done"] += 1
                        done, total = state["done"], total_count
                except BaseException as exc:  # never raise out of a worker
                    with lock:
                        if state["failure"] is None:
                            state["failure"] = exc
                    abort.set()
                    return
            finally:
                # Fakes may return None or a bare Mock, so only close
                # what actually looks like a socket.
                if hasattr(sock, "close"):
                    try:
                        sock.close()
                    except OSError:
                        pass
            put(("progress", done, total))

    try:
        total_count = len(ports)
        work: queue.Queue = queue.Queue()
        for port in ports:
            work.put(port)
        pool = [
            threading.Thread(target=worker, daemon=True)
            for _ in range(min(max(workers, 1), total_count))
        ]
        for thread in pool:
            thread.start()
        for thread in pool:
            thread.join()

        with lock:
            failure = state["failure"]
            open_ports = sorted(state["open"].items())
            scanned = state["done"]

        if failure is not None:
            emit_terminal(("error", str(failure)))
            return
        emit_terminal(("done", {"open": open_ports, "scanned": scanned}))
    except BaseException as exc:  # never raise out of run_port_scan
        emit_terminal(("error", str(exc)))


class IPScannerFrame(ttk.Frame):
    """IP block sweep + port scanner, each section independent.

    Both sections follow network.py's proven pattern: a worker thread
    `put`s sentinels into a private queue, the frame drains it via
    `self.after(100, ...)`, and a `threading.Event` requests an early
    stop. Terminal handlers re-enable FIRST so the UI never wedges.
    """

    def __init__(self, parent):
        super().__init__(parent, padding=16)
        self._sweep_queue: queue.Queue = queue.Queue()
        self._sweep_stop: threading.Event | None = None
        self._sweep_total: int | None = None
        self._port_queue: queue.Queue = queue.Queue()
        self._port_stop: threading.Event | None = None
        self._report = ""

        ttk.Label(self, text="IP Scanner",
                  style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            self, wraplength=660, style="Dim.TLabel",
            text="Hand it a block like 192.168.1.0/24 and it checks "
                 "every address, listing the devices that answer with "
                 "their name, MAC address and ping time — plus which "
                 "addresses are still free. The Port scanner tab probes "
                 "a single host to see which services are open to the "
                 "network.",
        ).pack(anchor="w", pady=(6, 12))

        self.status = widgets.StatusPane(self)
        self.status.pack(side="bottom", fill="x", pady=(8, 0))

        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill="both", expand=True)
        self._sweep_frame = ttk.Frame(self._notebook, padding=10)
        self._notebook.add(self._sweep_frame, text="Block scan")
        sweep_row = ttk.Frame(self._sweep_frame)
        sweep_row.pack(fill="x", pady=(0, 6))
        ttk.Label(sweep_row, text="Block:").pack(side="left")
        self._block_entry = ttk.Entry(sweep_row, width=22)
        self._block_entry.pack(side="left", padx=8)
        self._sweep_button = ttk.Button(
            sweep_row, text="Scan", style="Accent.TButton",
            command=self._start_sweep)
        self._sweep_button.pack(side="left", padx=(0, 8))
        self._sweep_progress = ttk.Progressbar(sweep_row, mode="determinate",
                                               length=160)
        self._sweep_progress.pack(side="left", padx=(0, 8))
        self._copy_button = ttk.Button(
            sweep_row, text="Copy report", state="disabled",
            command=self._copy_report)
        self._copy_button.pack(side="left")

        hosts_row = ttk.Frame(self._sweep_frame)
        hosts_row.pack(fill="both", expand=True, pady=(0, 6))
        self._hosts_tree = ttk.Treeview(
            hosts_row, columns=("ip", "hostname", "mac", "ms"),
            show="headings", height=6)
        for column, width, heading in (("ip", 110, "IP"),
                                       ("hostname", 230, "Hostname"),
                                       ("mac", 130, "MAC"),
                                       ("ms", 70, "Ping ms")):
            self._hosts_tree.heading(column, text=heading)
            self._hosts_tree.column(column, width=width, anchor="w")
        self._hosts_tree.pack(side="left", fill="both", expand=True)
        hosts_scroll = ttk.Scrollbar(hosts_row, orient="vertical",
                                     command=self._hosts_tree.yview)
        hosts_scroll.pack(side="right", fill="y")
        self._hosts_tree.configure(yscrollcommand=hosts_scroll.set)

        free_row = ttk.Frame(self._sweep_frame)
        free_row.pack(fill="x")
        ttk.Label(free_row, text="Free IPs:").pack(side="left")
        self._free_count = ttk.Label(free_row, style="Dim.TLabel",
                                     text="0 free of 0")
        self._free_count.pack(side="left", padx=8)
        palette = theme.current_palette()
        self._free_text = tk.Text(
            self._sweep_frame, wrap="word", height=3, font=("Consolas", 10),
            bg=palette["entry_bg"], fg=palette["fg"],
            insertbackground=palette["fg"], relief="flat", padx=10, pady=6,
            state="disabled")
        self._free_text.pack(fill="x", pady=(6, 0))
        theme.observe(self._on_theme)

        self._port_frame = ttk.Frame(self._notebook, padding=10)
        self._notebook.add(self._port_frame, text="Port scanner")
        port_row = ttk.Frame(self._port_frame)
        port_row.pack(fill="x", pady=(0, 6))
        ttk.Label(port_row, text="Host:").pack(side="left")
        self._host_entry = ttk.Entry(port_row, width=18)
        self._host_entry.pack(side="left", padx=(4, 12))
        ttk.Label(port_row, text="Ports:").pack(side="left")
        self._ports_entry = ttk.Entry(port_row, width=14)
        self._ports_entry.pack(side="left", padx=(4, 8))
        self._port_button = ttk.Button(
            port_row, text="Scan", style="Accent.TButton",
            command=self._start_port)
        self._port_button.pack(side="left", padx=(0, 8))
        self._port_progress = ttk.Progressbar(port_row, mode="determinate",
                                              length=160)
        self._port_progress.pack(side="left")

        ports_row = ttk.Frame(self._port_frame)
        ports_row.pack(fill="both", expand=True)
        self._ports_tree = ttk.Treeview(
            ports_row, columns=("port", "service"), show="headings",
            height=5)
        for column, width, heading in (("port", 90, "Port"),
                                       ("service", 180, "Service")):
            self._ports_tree.heading(column, text=heading)
            self._ports_tree.column(column, width=width, anchor="w")
        self._ports_tree.pack(side="left", fill="both", expand=True)
        ports_scroll = ttk.Scrollbar(ports_row, orient="vertical",
                                     command=self._ports_tree.yview)
        ports_scroll.pack(side="right", fill="y")
        self._ports_tree.configure(yscrollcommand=ports_scroll.set)

    # --- theming ------------------------------------------------------
    def _on_theme(self, palette: dict) -> None:
        self._free_text.configure(bg=palette["entry_bg"], fg=palette["fg"],
                                  insertbackground=palette["fg"])

    # --- block sweep --------------------------------------------------
    def _set_sweep_busy(self, busy: bool) -> None:
        # Per-section: the port scanner never follows this state.
        self._block_entry.configure(
            state="disabled" if busy else "normal")

    def _start_sweep(self) -> None:
        try:
            addresses = parse_block(self._block_entry.get())
        except ValueError as exc:
            self.status.set_error(str(exc))  # bad input ⇒ no thread
            return
        self._sweep_queue = queue.Queue()
        self._sweep_stop = threading.Event()
        self._sweep_total = len(addresses)
        self._set_sweep_busy(True)
        self._sweep_button.configure(text="Stop", command=self._stop_sweep)
        self._sweep_progress.configure(maximum=len(addresses), value=0)
        self._copy_button.configure(state="disabled")
        self._clear_sweep_results()
        self.status.set_working(f"Sweeping {len(addresses)} addresses…")
        threading.Thread(
            target=run_sweep,
            args=(addresses, self._sweep_stop, self._sweep_queue.put),
            daemon=True).start()
        self.after(100, self._drain_sweep)

    def _stop_sweep(self) -> None:
        # Only requests the stop; the UI flips back when the worker's
        # terminal sentinel arrives, mirroring network's ping toggle.
        if self._sweep_stop is not None:
            self._sweep_stop.set()
        self.status.set_working(
            "Stopping — waiting for the probes in flight…")

    def _clear_sweep_results(self) -> None:
        self._hosts_tree.delete(*self._hosts_tree.get_children())
        self._free_count.configure(text="0 free of 0")
        self._free_text.configure(state="normal")
        self._free_text.delete("1.0", "end")
        self._free_text.configure(state="disabled")
        self._report = ""

    def _drain_sweep(self) -> None:
        finalized = False
        for _ in range(50):
            try:
                item = self._sweep_queue.get_nowait()
            except queue.Empty:
                break
            kind = item[0]
            if kind == "progress":
                done, total = int(item[1]), int(item[2])
                self._sweep_progress.configure(value=done)
                self.status.set_working(f"Scanning… {done}/{total}")
            elif kind == "done":
                self._sweep_done(item[1])
                finalized = True
            elif kind == "error":
                self._sweep_error(item[1])
                finalized = True
        if not finalized:
            self.after(100, self._drain_sweep)

    def _sweep_done(self, payload: dict) -> None:
        self._set_sweep_busy(False)  # re-enable FIRST so the UI never wedges
        self._sweep_button.configure(text="Scan", command=self._start_sweep)
        hosts = payload.get("hosts", [])
        free = payload.get("free", [])
        unchecked = payload.get("unchecked", [])
        scanned = int(payload.get("scanned", 0))
        self._hosts_tree.delete(*self._hosts_tree.get_children())
        for host in hosts:
            ms = host.get("ms")
            self._hosts_tree.insert("", "end", values=(
                host.get("ip", ""), host.get("hostname") or "-",
                host.get("mac") or "-",
                "-" if ms is None else ms))
        if unchecked:
            self._free_count.configure(
                text=f"{len(free)} free · {len(unchecked)} unchecked")
        else:
            self._free_count.configure(
                text=f"{len(free)} free of {len(hosts) + len(free)}")
        self._free_text.configure(state="normal")
        self._free_text.delete("1.0", "end")
        self._free_text.insert("1.0", ", ".join(free))
        self._free_text.configure(state="disabled")
        self._report = self._build_report(hosts, free, unchecked)
        self._copy_button.configure(state="normal")
        total = self._sweep_total
        if total is not None and scanned < total:
            # Unprobed addresses are NOT verified free: report them apart
            # from the free list so nothing reads as confirmed.
            remaining = (len(unchecked) if unchecked
                         else max(total - scanned, 0))
            self.status.set_success(
                f"Stopped early — {scanned} of {total} checked, "
                f"{len(free)} free, {remaining} unchecked.")
        else:
            self.status.set_success(
                f"Scan finished. {len(hosts)} hosts live, {len(free)} free.")

    def _sweep_error(self, message: str) -> None:
        self._set_sweep_busy(False)  # re-enable FIRST so the UI never wedges
        self._sweep_button.configure(text="Scan", command=self._start_sweep)
        self.status.set_error(str(message))

    @staticmethod
    def _build_report(hosts: list, free: list,
                      unchecked: list | None = None) -> str:
        lines = ["IP  Hostname  MAC  Ping ms"]
        for host in hosts:
            ms = host.get("ms")
            lines.append(f"{host.get('ip', '')}  "
                         f"{host.get('hostname') or '-'}  "
                         f"{host.get('mac') or '-'}  "
                         f"{'-' if ms is None else ms}")
        lines.append("Free IPs: " + ", ".join(free))
        if unchecked:
            lines.append("Unchecked (not probed): " + ", ".join(unchecked))
        return "\n".join(lines)

    def _copy_report(self) -> None:
        if not self._report:
            self.status.set_warn("Nothing to copy yet.")
            return
        widgets.copy_text(self, self._report)
        self.status.set_success("Copied to clipboard.")

    # --- port scanner -------------------------------------------------
    def _set_port_busy(self, busy: bool) -> None:
        # Per-section: the block sweep never follows this state.
        state = "disabled" if busy else "normal"
        self._host_entry.configure(state=state)
        self._ports_entry.configure(state=state)

    def _start_port(self) -> None:
        try:
            ports = parse_port_spec(self._ports_entry.get())
        except ValueError as exc:
            self.status.set_error(str(exc))  # bad input ⇒ no thread
            return
        host = normalize_host(self._host_entry.get())
        if not host:
            self.status.set_warn("Enter a host name or IP address to scan.")
            return
        self._port_queue = queue.Queue()
        self._port_stop = threading.Event()
        self._set_port_busy(True)
        self._port_button.configure(text="Stop", command=self._stop_port)
        self._port_progress.configure(maximum=len(ports), value=0)
        self._ports_tree.delete(*self._ports_tree.get_children())
        self.status.set_working(f"Scanning {host} for {len(ports)} ports…")
        threading.Thread(
            target=run_port_scan,
            args=(host, ports, self._port_stop, self._port_queue.put),
            daemon=True).start()
        self.after(100, self._drain_port)

    def _stop_port(self) -> None:
        # Only requests the stop; the UI flips back on the sentinel.
        if self._port_stop is not None:
            self._port_stop.set()
        self.status.set_working(
            "Stopping — waiting for the connections in flight…")

    def _drain_port(self) -> None:
        finalized = False
        for _ in range(50):
            try:
                item = self._port_queue.get_nowait()
            except queue.Empty:
                break
            kind = item[0]
            if kind == "progress":
                done, total = int(item[1]), int(item[2])
                self._port_progress.configure(value=done)
                self.status.set_working(f"Scanning ports… {done}/{total}")
            elif kind == "done":
                self._port_done(item[1])
                finalized = True
            elif kind == "error":
                self._port_error(item[1])
                finalized = True
        if not finalized:
            self.after(100, self._drain_port)

    def _port_done(self, payload: dict) -> None:
        self._set_port_busy(False)  # re-enable FIRST so the UI never wedges
        self._port_button.configure(text="Scan", command=self._start_port)
        open_ports = payload.get("open", [])
        scanned = int(payload.get("scanned", 0))
        self._ports_tree.delete(*self._ports_tree.get_children())
        for port, service in open_ports:
            self._ports_tree.insert("", "end", values=(str(port), service))
        if open_ports:
            self.status.set_success(
                f"{len(open_ports)} open ports in {scanned} scanned.")
        else:
            self.status.set_success("No open ports found.")

    def _port_error(self, message: str) -> None:
        self._set_port_busy(False)  # re-enable FIRST so the UI never wedges
        self._port_button.configure(text="Scan", command=self._start_port)
        self.status.set_error(str(message))


def create(parent: ttk.Frame) -> ttk.Frame:
    return IPScannerFrame(parent)
