import threading
import unittest
from unittest.mock import MagicMock, Mock, patch

import tkinter as tk

from power_tool.core import runner, theme
from power_tool.tools import ip_scanner


class ParseBlockTests(unittest.TestCase):
    def test_slash24_hosts_only(self):
        addrs = ip_scanner.parse_block("192.168.1.0/24")
        self.assertEqual(len(addrs), 254)
        self.assertIn("192.168.1.1", addrs)
        self.assertNotIn("192.168.1.0", addrs)
        self.assertNotIn("192.168.1.255", addrs)

    def test_single_ip(self):
        self.assertEqual(ip_scanner.parse_block("  10.0.0.5  "),
                         ["10.0.0.5"])

    def test_too_big(self):
        self.assertEqual(ip_scanner.MAX_ADDRESSES, 4096)
        with self.assertRaises(ValueError) as ctx:
            ip_scanner.parse_block("10.0.0.0/16")
        self.assertIn("4096", str(ctx.exception))

    def test_invalid_and_ipv6(self):
        for bad in ("blah", "2001:db8::/64"):
            with self.assertRaises(ValueError) as ctx:
                ip_scanner.parse_block(bad)
            self.assertIn("192.168.1.0/24", str(ctx.exception))

    def test_slash32(self):
        self.assertEqual(ip_scanner.parse_block("10.0.0.9/32"),
                         ["10.0.0.9"])


ARP_SAMPLE = (
    "\n"
    "Interface: 192.168.1.100 --- 0x5\n"
    "  Internet Address      Physical Address      Type\n"
    "  192.168.1.1           aa-bb-cc-dd-ee-ff     dynamic\n"
    "\n"
    "Interface: 10.0.0.50 --- 0xc\n"
    "  Internet Address      Physical Address      Type\n"
    "  10.0.0.1              11:22:33:44:55:66     static\n"
    "  some junk line with no ip or mac at all\n"
)


class ParseArpTableTests(unittest.TestCase):
    def test_parses_mixed_dashes_and_colons(self):
        self.assertEqual(
            ip_scanner.parse_arp_table(ARP_SAMPLE),
            {"192.168.1.1": "AA-BB-CC-DD-EE-FF",
             "10.0.0.1": "11-22-33-44-55-66"})

    def test_junk_lines_skipped(self):
        self.assertEqual(ip_scanner.parse_arp_table(""), {})
        self.assertEqual(ip_scanner.parse_arp_table("nothing\nhere 1 2 3"),
                         {})


class PingMsTests(unittest.TestCase):
    def test_success_returns_elapsed_ms(self):
        with patch.object(ip_scanner.runner, "run") as fake_run:
            fake_run.return_value = runner.Result(0, "TTL=128 zeit=1ms", "")
            ms = ip_scanner.ping_ms("192.168.1.1")
        self.assertIsInstance(ms, int)
        self.assertGreaterEqual(ms, 0)
        fake_run.assert_called_once_with(
            ["ping", "-n", "1", "-w", "500", "192.168.1.1"], timeout=5)

    def test_failure_returns_none(self):
        with patch.object(ip_scanner.runner, "run") as fake_run:
            fake_run.return_value = runner.Result(
                1, "", "Request timed out.")
            self.assertIsNone(ip_scanner.ping_ms("192.168.1.1"))

    def test_timeout_result_returns_none(self):
        with patch.object(ip_scanner.runner, "run") as fake_run:
            fake_run.return_value = runner.Result(-1, "", "timed out")
            self.assertIsNone(ip_scanner.ping_ms("10.0.0.1"))


class ResolveHostTests(unittest.TestCase):
    def test_resolves_hostname(self):
        with patch.object(ip_scanner.socket, "gethostbyaddr",
                          return_value=("box.lan", [], ["1.2.3.4"])):
            self.assertEqual(ip_scanner.resolve_host("1.2.3.4"), "box.lan")

    def test_failure_falls_back_to_ip(self):
        with patch.object(ip_scanner.socket, "gethostbyaddr",
                          side_effect=OSError("no dns")):
            self.assertEqual(ip_scanner.resolve_host("1.2.3.4"), "1.2.3.4")


ADDRESSES = ["192.168.1.1", "192.168.1.2", "192.168.1.3"]

# .2 exists only in the ARP table (in-block); .9 is outside the block and
# must not leak into the hosts list.
SWEEP_ARP = (
    "  192.168.1.2           de-ad-be-ef-00-01     dynamic\n"
    "  192.168.1.9           00-11-22-33-44-55     dynamic\n"
)


def fake_probe(ip: str):
    return 12 if ip.endswith(".1") else None


def fake_arp() -> str:
    return SWEEP_ARP


def fake_resolver(ip: str) -> str:
    return f"h-{ip}"


class RunSweepTests(unittest.TestCase):
    def _sweep(self, addresses, stop, probe=fake_probe, arp_out=fake_arp,
               resolver=fake_resolver):
        messages = []
        ip_scanner.run_sweep(addresses, stop, messages.append,
                             probe=probe, arp_out=arp_out, resolver=resolver)
        return messages

    @staticmethod
    def _done(messages):
        done = [m for m in messages if m[0] == "done"]
        return done[0][1] if done else None

    def test_live_free_and_arp_only_split(self):
        messages = self._sweep(ADDRESSES, threading.Event())
        payload = self._done(messages)
        self.assertIsNotNone(payload)
        self.assertEqual([h["ip"] for h in payload["hosts"]],
                         ["192.168.1.1", "192.168.1.2"])
        by_ip = {h["ip"]: h for h in payload["hosts"]}
        self.assertEqual(by_ip["192.168.1.1"],
                         {"ip": "192.168.1.1", "hostname": "h-192.168.1.1",
                          "mac": None, "ms": 12})
        self.assertEqual(payload["free"], ["192.168.1.3"])
        self.assertEqual(payload["scanned"], 3)

    def test_arp_only_host_counts_live(self):
        messages = self._sweep(ADDRESSES, threading.Event())
        payload = self._done(messages)
        by_ip = {h["ip"]: h for h in payload["hosts"]}
        self.assertIn("192.168.1.2", by_ip)
        self.assertNotIn("192.168.1.2", payload["free"])
        self.assertIsNone(by_ip["192.168.1.2"]["ms"])
        self.assertEqual(by_ip["192.168.1.2"]["mac"], "DE-AD-BE-EF-00-01")
        self.assertEqual(by_ip["192.168.1.2"]["hostname"], "h-192.168.1.2")

    def test_progress_and_done_once(self):
        messages = self._sweep(ADDRESSES, threading.Event())
        kinds = [m[0] for m in messages]
        progress = [m for m in messages if m[0] == "progress"]
        self.assertEqual(kinds.count("done"), 1)
        self.assertNotIn("error", kinds)
        self.assertEqual(len(progress), 3)
        self.assertEqual(sorted(m[1] for m in progress), [1, 2, 3])
        self.assertTrue(all(m[2] == 3 for m in progress))
        self.assertEqual(messages[-1][0], "done")

    def test_stop_short_circuits(self):
        stop = threading.Event()
        stop.set()
        calls = []
        messages = self._sweep(ADDRESSES, stop,
                               probe=lambda ip: calls.append(ip) or 12)
        self.assertEqual(calls, [])
        self.assertEqual([m for m in messages if m[0] == "progress"], [])
        payload = self._done(messages)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["scanned"], 0)
        self.assertEqual(payload["hosts"], [])
        self.assertEqual(payload["free"], ADDRESSES)

    def test_stop_mid_scan_still_emits_done(self):
        stop = threading.Event()
        calls = []
        arp_calls = []

        def probe(ip):
            calls.append(ip)
            stop.set()
            return 12 if ip.endswith(".1") else None

        def arp():
            arp_calls.append("called")
            return SWEEP_ARP

        messages = self._sweep(ADDRESSES, stop, probe=probe, arp_out=arp)
        payload = self._done(messages)
        self.assertIsNotNone(payload)
        self.assertGreaterEqual(payload["scanned"], 1)
        self.assertLessEqual(payload["scanned"], len(ADDRESSES))
        self.assertEqual(payload["scanned"], len(calls))
        self.assertEqual(arp_calls, [])  # ARP fetch skipped on early stop
        host_ips = {h["ip"] for h in payload["hosts"]}
        self.assertTrue(host_ips <= set(ADDRESSES))
        self.assertEqual(host_ips | set(payload["free"]), set(ADDRESSES))
        self.assertEqual(host_ips & set(payload["free"]), set())

    def test_probe_exception_becomes_error_sentinel(self):
        def probe(ip):
            if ip.endswith(".2"):
                raise RuntimeError("kaboom")
            return 1

        messages = self._sweep(ADDRESSES, threading.Event(), probe=probe)
        kinds = [m[0] for m in messages]
        self.assertIn("error", kinds)
        self.assertNotIn("done", kinds)
        errors = [m for m in messages if m[0] == "error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("kaboom", errors[0][1])

    def test_outputs_sorted_numerically(self):
        addrs = ["192.168.1.10", "192.168.1.2", "192.168.1.1"]
        messages = self._sweep(addrs, threading.Event())
        payload = self._done(messages)
        # .1 ping-alive, .2 ARP-only, .10 dead — numeric order, not text
        self.assertEqual([h["ip"] for h in payload["hosts"]],
                         ["192.168.1.1", "192.168.1.2"])
        self.assertEqual(payload["free"], ["192.168.1.10"])

    def test_workers_threaded(self):
        with patch.object(ip_scanner.threading, "Thread") as fake_thread:
            messages = self._sweep(ADDRESSES, threading.Event())
        self.assertGreaterEqual(fake_thread.call_count, 1)
        self.assertEqual(len([m for m in messages if m[0] == "done"]), 1)


class ParsePortSpecTests(unittest.TestCase):
    def test_range(self):
        ports = ip_scanner.parse_port_spec("1-1024")
        self.assertEqual(len(ports), 1024)
        self.assertEqual(ports[0], 1)
        self.assertEqual(ports[-1], 1024)

    def test_list(self):
        self.assertEqual(ip_scanner.parse_port_spec("443,22,8080"),
                         [22, 443, 8080])

    def test_mixed(self):
        self.assertEqual(ip_scanner.parse_port_spec("22,8000-8002"),
                         [22, 8000, 8001, 8002])

    def test_dedupe(self):
        self.assertEqual(ip_scanner.parse_port_spec("80,80-82"),
                         [80, 81, 82])

    def test_bad_values(self):
        for bad in ("", "0", "abc", "100-50", "65536", "22-", "-5"):
            with self.assertRaises(ValueError) as ctx:
                ip_scanner.parse_port_spec(bad)
            self.assertIn("1-1024", str(ctx.exception))

    def test_over_cap(self):
        self.assertEqual(ip_scanner.MAX_PORTS, 4096)
        with self.assertRaises(ValueError) as ctx:
            ip_scanner.parse_port_spec("1-5000")
        self.assertIn("4096", str(ctx.exception))


class PortServiceTests(unittest.TestCase):
    def test_known(self):
        self.assertEqual(ip_scanner.port_service(80), "http")

    def test_unknown(self):
        with patch.object(ip_scanner.socket, "getservbyport",
                          side_effect=OSError("noPE")):
            self.assertEqual(ip_scanner.port_service(9), "-")


HOST = "192.168.1.7"
SCAN_PORTS = [22, 80, 443]


def fake_addrinfo(address, _port=None):
    return [(2, 1, 6, "", ("127.0.0.1", 0))]


class FakeSocket:
    closed_count = 0

    def close(self):
        FakeSocket.closed_count += 1
        self.closed = True


def fake_getserv(port, proto=None):
    if port == 22:
        return "ssh"
    if port == 80:
        return "http"
    raise OSError("noPE")


def make_connector(open_ports):
    calls = []

    def connector(address, timeout=0.4):
        calls.append((address, timeout))
        if address[1] in open_ports:
            return FakeSocket() if address[1] == 22 else None
        raise OSError("refused")

    connector.calls = calls
    return connector


class RunPortScanTests(unittest.TestCase):
    def _scan(self, ports, stop, connector, workers=64):
        messages = []
        with patch.object(ip_scanner.socket, "getaddrinfo", fake_addrinfo):
            ip_scanner.run_port_scan(HOST, ports, stop, messages.append,
                                     workers=workers, connector=connector)
        return messages

    @staticmethod
    def _done(messages):
        done = [m for m in messages if m[0] == "done"]
        return done[0][1] if done else None

    def test_open_listed_with_service(self):
        connector = make_connector({22, 80})
        with patch.object(ip_scanner.socket, "getservbyport", fake_getserv):
            messages = self._scan(SCAN_PORTS, threading.Event(), connector)
        payload = self._done(messages)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["open"], [(22, "ssh"), (80, "http")])
        self.assertEqual(payload["scanned"], len(SCAN_PORTS))

    def test_open_sockets_closed(self):
        connector = make_connector({22, 80})
        FakeSocket.closed_count = 0
        with patch.object(ip_scanner.socket, "getservbyport", fake_getserv):
            self._scan(SCAN_PORTS, threading.Event(), connector)
        # One FakeSocket was handed out (port 22) and it got closed; the
        # None-returning fake (port 80) was skipped via the hasattr check.
        self.assertEqual(FakeSocket.closed_count, 1)
        self.assertEqual(len(connector.calls), len(SCAN_PORTS))

    def test_stop_short_circuits(self):
        stop = threading.Event()
        stop.set()
        connector = Mock()
        messages = self._scan(SCAN_PORTS, stop, connector)
        self.assertEqual(connector.call_args_list, [])
        self.assertEqual([m for m in messages if m[0] == "progress"], [])
        payload = self._done(messages)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["open"], [])
        self.assertEqual(payload["scanned"], 0)

    def test_unresolvable_host_error_sentinel(self):
        connector = Mock()
        messages = []
        with patch.object(ip_scanner.socket, "getaddrinfo",
                          side_effect=ip_scanner.socket.gaierror(2, "noPE")):
            ip_scanner.run_port_scan(HOST, SCAN_PORTS, threading.Event(),
                                     messages.append, connector=connector)
        kinds = [m[0] for m in messages]
        self.assertEqual(kinds, ["error"])
        self.assertIn(HOST, messages[0][1])
        self.assertEqual(connector.call_args_list, [])

    def test_connector_exception_becomes_error_sentinel(self):
        connector = MagicMock(side_effect=RuntimeError("kaboom"))
        messages = self._scan(SCAN_PORTS, threading.Event(), connector)
        kinds = [m[0] for m in messages]
        self.assertIn("error", kinds)
        self.assertNotIn("done", kinds)
        errors = [m for m in messages if m[0] == "error"]
        self.assertEqual(len(errors), 1)
        self.assertIn("kaboom", errors[0][1])

    def test_progress_and_done_once(self):
        connector = make_connector({22})
        messages = self._scan(SCAN_PORTS, threading.Event(), connector)
        kinds = [m[0] for m in messages]
        progress = [m for m in messages if m[0] == "progress"]
        self.assertEqual(kinds.count("done"), 1)
        self.assertNotIn("error", kinds)
        self.assertEqual(len(progress), len(SCAN_PORTS))
        self.assertEqual(sorted(m[1] for m in progress),
                         [1, 2, len(SCAN_PORTS)])
        self.assertTrue(all(m[2] == len(SCAN_PORTS) for m in progress))
        self.assertEqual(messages[-1][0], "done")

    def test_connector_uses_timeout(self):
        connector = make_connector({22})
        self._scan(SCAN_PORTS, threading.Event(), connector)
        # Every port is attempted (closed ports raise OSError inside the
        # fake), pulled from the queue in whatever order the workers
        # raced — the seam contract is timeout=0.4 on every call.
        by_port = {address[1]: timeout for address, timeout in connector.calls}
        self.assertEqual(sorted(by_port), SCAN_PORTS)
        for timeout in by_port.values():
            self.assertEqual(timeout, 0.4)


SWEEP_HOSTS = [
    {"ip": "192.168.1.1", "hostname": "box1.lan",
     "mac": "AA-BB-CC-DD-EE-FF", "ms": 12},
    {"ip": "192.168.1.2", "hostname": "192.168.1.2",
     "mac": None, "ms": None},
]
SWEEP_PAYLOAD = {"hosts": [dict(h) for h in SWEEP_HOSTS],
                 "free": ["192.168.1.3"], "scanned": 3}


class IPScannerFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()
        theme.apply_theme(cls.root, "dark")

    @classmethod
    def tearDownClass(cls):
        # Scan starts leave a self-rescheduling after(100, drain) poll
        # pending (worker threads are patched out in these tests). Cancel
        # each pending timer by id before destroy — the console frame's
        # trick — so a later event pump can't fire them against a dead
        # root and print "invalid command name" on stderr.
        tk_id = cls.root.tk
        for after_id in tk_id.splitlist(tk_id.call("after", "info")):
            tk_id.call("after", "cancel", after_id)
        cls.root.destroy()

    def setUp(self):
        self.frame = ip_scanner.IPScannerFrame(self.root)

    def _start_sweep(self, block="192.168.1.0/24"):
        """Start a block sweep with the worker thread patched out."""
        with patch.object(ip_scanner.threading, "Thread") as fake_thread:
            self.frame._block_entry.insert(0, block)
            self.frame._start_sweep()
        return fake_thread

    # --- block scan ---------------------------------------------------
    def test_bad_block_reports_error_no_thread(self):
        with patch.object(ip_scanner.threading, "Thread") as fake_thread:
            self.frame._block_entry.insert(0, "999.1.1.1")
            self.frame._start_sweep()
        fake_thread.assert_not_called()
        self.assertIn("192.168.1.0/24", self.frame.status.text())
        self.assertEqual(str(self.frame.status._label.cget("style")),
                         "Error.TLabel")

    def test_block_scan_starts_thread_and_toggles(self):
        fake_thread = self._start_sweep()
        fake_thread.assert_called_once()
        kwargs = fake_thread.call_args.kwargs
        self.assertIs(kwargs["target"], ip_scanner.run_sweep)
        self.assertTrue(kwargs["daemon"])
        args = kwargs["args"]
        self.assertEqual(len(args[0]), 254)
        self.assertFalse(args[1].is_set())          # fresh stop event
        self.assertEqual(args[2], self.frame._sweep_queue.put)
        self.assertEqual(str(self.frame._sweep_button.cget("text")), "Stop")
        self.assertEqual(str(self.frame._block_entry.cget("state")),
                         "disabled")
        self.assertEqual(float(self.frame._sweep_progress.cget("maximum")),
                         254.0)

    def test_done_payload_fills_trees_and_counts(self):
        # Simulate a running sweep first so "re-enable FIRST" is visible.
        self.frame._set_sweep_busy(True)
        self.frame._sweep_button.configure(
            text="Stop", command=self.frame._stop_sweep)
        seen = {}
        real_success = self.frame.status.set_success

        def spy(message):
            seen["entry"] = str(self.frame._block_entry.cget("state"))
            seen["button"] = str(self.frame._sweep_button.cget("text"))
            real_success(message)

        with patch.object(self.frame.status, "set_success", side_effect=spy):
            self.frame._sweep_done(dict(SWEEP_PAYLOAD))
        self.assertEqual(seen["entry"], "normal")    # re-enabled FIRST
        self.assertEqual(seen["button"], "Scan")
        rows = self.frame._hosts_tree.get_children()
        self.assertEqual(len(rows), 2)
        self.assertEqual(tuple(self.frame._hosts_tree.item(rows[0],
                                                           "values")),
                         ("192.168.1.1", "box1.lan", "AA-BB-CC-DD-EE-FF",
                          "12"))
        self.assertEqual(tuple(self.frame._hosts_tree.item(rows[1],
                                                           "values")),
                         ("192.168.1.2", "192.168.1.2", "-", "-"))
        self.assertEqual(str(self.frame._free_count.cget("text")),
                         "1 free of 4")
        self.assertEqual(self.frame._free_text.get("1.0", "end").strip(),
                         "192.168.1.3")
        self.assertIn("Scan finished. 2 hosts live, 1 free.",
                      self.frame.status.text())
        self.assertEqual(str(self.frame._copy_button.cget("state")),
                         "normal")
        self.assertEqual(str(self.frame._block_entry.cget("state")),
                         "normal")
        self.assertEqual(str(self.frame._sweep_button.cget("text")), "Scan")

    def test_stop_sets_event(self):
        self._start_sweep()
        event = self.frame._sweep_stop
        self.frame._sweep_button.invoke()
        self.assertTrue(event.is_set())
        # The toggle only flips back when the terminal sentinel lands,
        # mirroring network's ping Start/Stop.
        self.assertEqual(str(self.frame._sweep_button.cget("text")), "Stop")
        self.frame._sweep_done({"hosts": [], "free": [], "scanned": 5})
        self.assertEqual(str(self.frame._sweep_button.cget("text")), "Scan")

    def test_error_sentinel_reenables_first(self):
        self._start_sweep()
        seen = {}
        real_error = self.frame.status.set_error

        def spy(message):
            seen["entry"] = str(self.frame._block_entry.cget("state"))
            seen["button"] = str(self.frame._sweep_button.cget("text"))
            real_error(message)

        with patch.object(self.frame.status, "set_error", side_effect=spy):
            self.frame._sweep_error("disk exploded")
        self.assertEqual(seen["entry"], "normal")    # re-enabled FIRST
        self.assertEqual(seen["button"], "Scan")
        self.assertIn("disk exploded", self.frame.status.text())
        self.assertEqual(str(self.frame.status._label.cget("style")),
                         "Error.TLabel")
        self.assertEqual(str(self.frame._block_entry.cget("state")),
                         "normal")

    def test_stopped_early_labels_partial_sweep(self):
        self._start_sweep()                          # 192.168.1.0/24
        self.assertEqual(self.frame._sweep_total, 254)
        self.frame._sweep_done({"hosts": [], "free": ["192.168.1.1"],
                                "scanned": 40})
        # Unprobed addresses must not read as verified-free.
        self.assertIn("Stopped early — 40 of 254 checked.",
                      self.frame.status.text())
        self.assertNotIn("Scan finished", self.frame.status.text())

    def test_full_sweep_keeps_normal_finished_text(self):
        self._start_sweep()
        self.frame._sweep_done({"hosts": [], "free": [], "scanned": 254})
        self.assertIn("Scan finished. 0 hosts live, 0 free.",
                      self.frame.status.text())

    def test_drain_updates_progressbar_and_working_text(self):
        self._start_sweep()
        self.frame._sweep_queue.put(("progress", 3, 254))
        self.frame._drain_sweep()
        self.assertEqual(float(self.frame._sweep_progress.cget("value")),
                         3.0)
        self.assertIn("Scanning… 3/254", self.frame.status.text())

    def test_copy_report_contains_hosts_and_free(self):
        self.frame._sweep_done(dict(SWEEP_PAYLOAD))
        with patch.object(ip_scanner.widgets, "copy_text") as fake_copy:
            self.frame._copy_report()
        fake_copy.assert_called_once()
        text = fake_copy.call_args.args[1]
        self.assertIn("IP  Hostname  MAC  Ping ms", text)
        self.assertIn("192.168.1.1  box1.lan  AA-BB-CC-DD-EE-FF  12", text)
        self.assertIn("192.168.1.2  192.168.1.2  -  -", text)
        self.assertIn("Free IPs: 192.168.1.3", text)
        self.assertIn("Copied to clipboard", self.frame.status.text())

    def test_copy_without_results_warns(self):
        self.frame._copy_report()
        self.assertIn("Nothing to copy", self.frame.status.text())
        self.assertEqual(str(self.frame.status._label.cget("style")),
                         "Warn.TLabel")

    # --- port scanner -------------------------------------------------
    def test_port_bad_spec_error_no_thread(self):
        with patch.object(ip_scanner.threading, "Thread") as fake_thread:
            self.frame._host_entry.insert(0, "example.com")
            self.frame._ports_entry.insert(0, "0-5")
            self.frame._start_port()
        fake_thread.assert_not_called()
        self.assertIn("1-1024", self.frame.status.text())
        self.assertEqual(str(self.frame.status._label.cget("style")),
                         "Error.TLabel")

    def test_port_done_fills_tree(self):
        self.frame._set_port_busy(True)
        self.frame._port_button.configure(
            text="Stop", command=self.frame._stop_port)
        self.frame._port_done({"open": [(22, "ssh")], "scanned": 10})
        rows = self.frame._ports_tree.get_children()
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            tuple(self.frame._ports_tree.item(rows[0], "values")),
            ("22", "ssh"))
        self.assertIn("1 open ports in 10 scanned.",
                      self.frame.status.text())
        self.assertEqual(str(self.frame._port_button.cget("text")), "Scan")
        self.assertEqual(str(self.frame._host_entry.cget("state")),
                         "normal")
        self.assertEqual(str(self.frame._ports_entry.cget("state")),
                         "normal")

    def test_port_done_with_nothing_open_says_so(self):
        self.frame._port_done({"open": [], "scanned": 5})
        self.assertEqual(self.frame._ports_tree.get_children(), ())
        self.assertIn("No open ports found.", self.frame.status.text())

    def test_port_host_empty_warns(self):
        with patch.object(ip_scanner.threading, "Thread") as fake_thread:
            self.frame._ports_entry.insert(0, "22,80")
            self.frame._start_port()
        fake_thread.assert_not_called()
        self.assertIn("host", self.frame.status.text().lower())
        self.assertEqual(str(self.frame.status._label.cget("style")),
                         "Warn.TLabel")

    # --- section independence & layout --------------------------------
    def test_sections_independent(self):
        # A running block sweep leaves the port section fully usable.
        self._start_sweep()
        for widget in (self.frame._host_entry, self.frame._ports_entry):
            self.assertEqual(str(widget.cget("state")), "normal")
        self.assertEqual(str(self.frame._port_button.cget("text")), "Scan")
        self.assertEqual(str(self.frame._port_button.cget("state")),
                         "normal")
        # Finish the sweep, then run a port scan: the block section
        # stays usable while the port section manages its own inputs.
        self.frame._sweep_done({"hosts": [], "free": [], "scanned": 254})
        with patch.object(ip_scanner.threading, "Thread") as fake_thread:
            self.frame._host_entry.insert(0, "example.com")
            self.frame._ports_entry.insert(0, "22,80")
            self.frame._start_port()
        fake_thread.assert_called_once()
        self.assertEqual(str(self.frame._host_entry.cget("state")),
                         "disabled")
        self.assertEqual(str(self.frame._block_entry.cget("state")),
                         "normal")
        self.assertEqual(str(self.frame._sweep_button.cget("text")), "Scan")
        self.assertEqual(str(self.frame._sweep_button.cget("state")),
                         "normal")

    def test_layout_columns_match_spec(self):
        for column, width, heading in (("ip", 110, "IP"),
                                       ("hostname", 230, "Hostname"),
                                       ("mac", 130, "MAC"),
                                       ("ms", 70, "Ping ms")):
            self.assertEqual(self.frame._hosts_tree.column(column, "width"),
                             width)
            self.assertEqual(self.frame._hosts_tree.heading(column, "text"),
                             heading)
        for column, width in (("port", 90), ("service", 180)):
            self.assertEqual(self.frame._ports_tree.column(column, "width"),
                             width)
        self.assertEqual(str(self.frame._sweep_button.cget("text")), "Scan")
        self.assertEqual(str(self.frame._copy_button.cget("state")),
                         "disabled")

    def test_create_returns_frame(self):
        frame = ip_scanner.create(self.root)
        self.assertIsInstance(frame, ip_scanner.IPScannerFrame)


if __name__ == "__main__":
    unittest.main()
