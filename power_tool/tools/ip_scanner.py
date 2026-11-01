"""IP block scanner pure layer: CIDR parsing, threaded sweep, ARP merge.

No tkinter here — the UI feeds addresses in, gets sentinel-tagged
messages out via `put`, and can stop early through `stop_event`.
Nothing raises: unexpected failures surface as an ("error", ...)
sentinel instead of an exception.
"""

import ipaddress
import queue
import re
import socket
import threading
import time

from power_tool.core import runner

MAX_ADDRESSES = 4096

_BLOCK_HINT = "Enter an IPv4 block like 192.168.1.0/24"
_CAP_HINT = (f"That block is too big — {MAX_ADDRESSES} addresses max. "
             "Try a smaller range.")

_IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
_MAC_RE = re.compile(r"(?:[0-9a-fA-F]{2}[-:]){5}[0-9a-fA-F]{2}")


def parse_block(text: str) -> list[str]:
    """Expand a single IPv4 address or CIDR block into usable hosts.

    Network/broadcast are excluded by `hosts()` (/31 and /32 keep every
    address). Over the cap, or anything non-IPv4, raises ValueError.
    """
    cleaned = str(text).strip()
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
        return socket.gethostbyaddr(ip)[0]
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
    ms None), free = addresses − hosts, scanned = probes completed.
    """
    probe = ping_ms if probe is None else probe
    arp_out = _default_arp_out if arp_out is None else arp_out
    resolver = resolve_host if resolver is None else resolver

    lock = threading.Lock()
    state = {"done": 0, "alive": {}, "failure": None, "emitted": False}
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
            scanned = state["done"]

        if failure is not None:
            emit_terminal(("error", str(failure)))
            return

        # Early stop skips the ARP fetch for a fast, consistent partial
        # payload; otherwise merge ARP hits (restricted to the block).
        arp_hits = {} if stop_event.is_set() else parse_arp_table(arp_out())
        address_set = set(addresses)
        host_ips = set(alive) | {ip for ip in arp_hits if ip in address_set}
        hosts = [
            {"ip": ip, "hostname": resolver(ip), "mac": arp_hits.get(ip),
             "ms": alive.get(ip)}
            for ip in sorted(host_ips, key=_ip_order)
        ]
        free = [ip for ip in sorted(address_set, key=_ip_order)
                if ip not in host_ips]
        emit_terminal(("done", {"hosts": hosts, "free": free,
                                "scanned": scanned}))
    except BaseException as exc:  # never raise out of run_sweep
        emit_terminal(("error", str(exc)))
