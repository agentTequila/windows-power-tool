import threading
import unittest
from unittest.mock import MagicMock, Mock, patch

from power_tool.core import runner
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


if __name__ == "__main__":
    unittest.main()
