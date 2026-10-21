import threading
import unittest
from unittest.mock import patch

import tkinter as tk

from power_tool.core import runner, theme, widgets
from power_tool.tools import network

REAL_GUARD_ADMIN = widgets.guard_admin


class PingOnceArgsTests(unittest.TestCase):
    def test_builds_single_echo_command(self):
        self.assertEqual(network.ping_once_args("example.com"),
                         ["ping", "-n", "1", "-w", "2000", "example.com"])

    def test_trims_whitespace(self):
        self.assertEqual(network.ping_once_args("  8.8.8.8  "),
                         ["ping", "-n", "1", "-w", "2000", "8.8.8.8"])

    def test_empty_host_raises(self):
        with self.assertRaises(ValueError):
            network.ping_once_args("   ")


PARSE_ADAPTERS_SAMPLE = (
    "\n"
    "Admin State    State          Type             Interface Name\n"
    "--------------------------------------------------------------\n"
    "Enabled        Connected      Dedicated        Ethernet\n"
    "Enabled        Disconnected   Dedicated        Ethernet 2\n"
    "Enabled        Disconnected   Dedicated        Ethernet 2\n"
)


class ParseAdaptersTests(unittest.TestCase):
    def test_parse_adapters_sample_table(self):
        self.assertEqual(network.parse_adapters(PARSE_ADAPTERS_SAMPLE),
                         ["Ethernet", "Ethernet 2"])

    def test_parse_adapters_skips_headers_and_blanks(self):
        sample = (
            "\n"
            "Admin State    State          Type             Interface Name\n"
            "\n"
            "--------------------------------------------------------------\n"
            "Enabled        Connected      Dedicated        Loopback\n"
        )
        self.assertEqual(network.parse_adapters(sample), ["Loopback"])


class DhcpCommandsTests(unittest.TestCase):
    def test_dhcp_commands_exact(self):
        self.assertEqual(
            network.dhcp_commands("Ethernet 2"),
            [["netsh", "interface", "ipv4", "set", "address",
              "name=Ethernet 2", "dhcp"],
             ["netsh", "interface", "ipv4", "set", "dns",
              "name=Ethernet 2", "dhcp"]])


class StaticCommandsTests(unittest.TestCase):
    def test_static_commands_exact_with_gateway(self):
        self.assertEqual(
            network.static_commands("Ethernet", "192.168.1.10",
                                    "255.255.255.0", "192.168.1.1",
                                    "8.8.8.8", "8.8.4.4"),
            [["netsh", "interface", "ipv4", "set", "address",
              "name=Ethernet", "static", "192.168.1.10",
              "255.255.255.0", "192.168.1.1"],
             ["netsh", "interface", "ipv4", "set", "dns",
              "name=Ethernet", "static", "8.8.8.8"],
             ["netsh", "interface", "ipv4", "add", "dns",
              "name=Ethernet", "8.8.4.4", "index=2"]])

    def test_static_commands_blank_gateway_none(self):
        self.assertEqual(
            network.static_commands("Ethernet", "192.168.1.10",
                                    "255.255.255.0", "",
                                    "1.1.1.1", ""),
            [["netsh", "interface", "ipv4", "set", "address",
              "name=Ethernet", "static", "192.168.1.10",
              "255.255.255.0", "gateway=none"],
             ["netsh", "interface", "ipv4", "set", "dns",
              "name=Ethernet", "static", "1.1.1.1"]])

    def test_static_validation_rejects_bad_ip(self):
        with self.assertRaises(ValueError):
            network.static_commands("Ethernet", "999.1.1.1",
                                    "255.255.255.0", "192.168.1.1",
                                    "8.8.8.8", "")

    def test_static_validation_rejects_bad_mask(self):
        with self.assertRaises(ValueError):
            network.static_commands("Ethernet", "192.168.1.10",
                                    "255.0", "",
                                    "8.8.8.8", "")

    def test_static_validation_rejects_bad_dns(self):
        with self.assertRaises(ValueError):
            network.static_commands("Ethernet", "192.168.1.10",
                                    "255.255.255.0", "",
                                    "8.8.8", "")

    def test_static_validation_rejects_bad_gateway(self):
        with self.assertRaises(ValueError):
            network.static_commands("Ethernet", "192.168.1.10",
                                    "255.255.255.0", "not-an-ip",
                                    "8.8.8.8", "")

    def test_static_requires_dns_primary(self):
        with self.assertRaises(ValueError) as ctx:
            network.static_commands("Ethernet", "192.168.1.10",
                                    "255.255.255.0", "", "", "")
        self.assertIn("DNS server is required", str(ctx.exception))


class FakePaceStop:
    """Stand-in for threading.Event whose wait() records pacing calls."""

    def __init__(self, wait_result=False):
        self.waits = []
        self._set = False
        self._wait_result = wait_result

    def is_set(self):
        return self._set

    def set(self):
        self._set = True

    def wait(self, timeout=None):
        self.waits.append(timeout)
        return self._wait_result


class PingSessionTests(unittest.TestCase):
    @patch.object(network, "runner")
    def test_ping_session_counts_timeouts_as_loss(self, fake_runner):
        fake_runner.run.side_effect = [
            runner.Result(0, "Reply from 8.8.8.8: bytes=32 time=10ms TTL=118", ""),
            runner.Result(1, "Request timed out.", ""),
        ]
        stop = threading.Event()
        events = []

        def put(item):
            events.append(item)
            if item[0] == "stats" and item[1] == 2:
                stop.set()

        result = network.run_ping_session("8.8.8.8", stop, put,
                                          count=2, interval=0)
        self.assertEqual(result, {"sent": 2, "lost": 1})

    @patch.object(network, "runner")
    def test_done_event_payload(self, fake_runner):
        fake_runner.run.side_effect = [runner.Result(1, "timed out", "")]
        stop = threading.Event()

        def put(item):
            if item[0] == "stats":
                stop.set()

        result = network.run_ping_session("10.255.255.1", stop, put,
                                          count=1, interval=0)
        self.assertEqual(result["lost"], 1)

    @patch.object(network, "runner")
    def test_ping_session_respects_count(self, fake_runner):
        fake_runner.run.side_effect = [
            runner.Result(0, "Reply from 8.8.8.8: bytes=32", ""),
            runner.Result(0, "Reply from 8.8.8.8: bytes=32", ""),
            runner.Result(0, "Reply from 8.8.8.8: bytes=32", ""),
        ]
        stop = threading.Event()
        events = []
        network.run_ping_session("8.8.8.8", stop, events.append,
                                 count=3, interval=0)
        self.assertEqual(fake_runner.run.call_count, 3)
        done = [item for item in events if item[0] == "done"]
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0][1]["count"], 3)
        self.assertEqual(done[0][1]["sent"], 3)

    @patch.object(network, "runner")
    def test_ping_session_paces_with_event_wait(self, fake_runner):
        fake_runner.run.side_effect = [runner.Result(0, "ok", "")] * 4
        stop = FakePaceStop(wait_result=False)
        events = []
        network.run_ping_session("8.8.8.8", stop, events.append,
                                 count=4, interval=0.5)
        self.assertEqual(stop.waits, [0.5, 0.5, 0.5])
        done = [item for item in events if item[0] == "done"]
        self.assertEqual(len(done), 1)

    @patch.object(network, "runner")
    def test_ping_session_stop_during_pace_breaks(self, fake_runner):
        fake_runner.run.side_effect = [
            runner.Result(1, "Request timed out.", ""),
            runner.Result(1, "Request timed out.", ""),
        ]
        stop = FakePaceStop(wait_result=True)
        events = []
        network.run_ping_session("10.255.255.1", stop, events.append,
                                 count=5, interval=2.0)
        self.assertEqual(fake_runner.run.call_count, 1)
        self.assertEqual(stop.waits, [2.0])
        done = [item for item in events if item[0] == "done"]
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0][1], {"sent": 1, "lost": 1, "count": 5})


class ActionCommandsTests(unittest.TestCase):
    def test_flush_dns_single_command(self):
        self.assertEqual(network.action_commands("Flush DNS"),
                         [["ipconfig", "/flushdns"]])

    def test_release_ip_single_command(self):
        self.assertEqual(network.action_commands("Release IP"),
                         [["ipconfig", "/release"]])

    def test_renew_ip_single_command(self):
        self.assertEqual(network.action_commands("Renew IP"),
                         [["ipconfig", "/renew"]])

    def test_release_renew_runs_two_commands(self):
        self.assertEqual(network.action_commands("Release + Renew"),
                         [["ipconfig", "/release"], ["ipconfig", "/renew"]])

    def test_unknown_action_raises(self):
        with self.assertRaises(KeyError):
            network.action_commands("Make Coffee")


class RunCommandsTests(unittest.TestCase):
    @patch.object(network, "runner")
    def test_concatenates_outputs(self, fake_runner):
        fake_runner.run.side_effect = [
            runner.Result(0, "Flushed the DNS Resolver Cache", ""),
            runner.Result(0, "renewed", ""),
        ]
        text = network.run_commands([["ipconfig", "/flushdns"],
                                     ["ipconfig", "/renew"]])
        self.assertIn("Flushed the DNS Resolver Cache", text)
        self.assertIn("renewed", text)
        self.assertIn("$ ipconfig /flushdns", text)

    @patch.object(network, "runner")
    def test_nonzero_raises_with_stderr_detail(self, fake_runner):
        fake_runner.run.return_value = runner.Result(1, "", "Access is denied")
        with self.assertRaises(RuntimeError) as ctx:
            network.run_commands([["ipconfig", "/flushdns"]])
        self.assertIn("Access is denied", str(ctx.exception))

    @patch.object(network, "runner")
    def test_nonzero_raises_with_stdout_when_stderr_empty(self, fake_runner):
        fake_runner.run.return_value = runner.Result(1, "some output", "")
        with self.assertRaises(RuntimeError) as ctx:
            network.run_commands([["ipconfig", "/flushdns"]])
        self.assertIn("some output", str(ctx.exception))


class NetworkFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()
        theme.apply_theme(cls.root, "dark")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        guard = patch.object(network.widgets, "guard_admin", return_value=True)
        guard.start()
        self.addCleanup(guard.stop)
        self.frame = network.NetworkFrame(self.root)

    def test_four_actions_in_declared_order(self):
        self.assertEqual(self.frame._action_names,
                         ["Flush DNS", "Release IP", "Renew IP",
                          "Release + Renew"])
        self.assertEqual(sorted(self.frame._action_buttons),
                         sorted(["Flush DNS", "Release IP", "Renew IP",
                                 "Release + Renew"]))

    def test_output_starts_empty(self):
        self.assertEqual(self.frame._output.get("1.0", "end").strip(), "")

    @patch.object(network.tasks, "BackgroundTask")
    def test_action_disables_buttons_runs_task_reports_success(
            self, fake_task):
        self.frame._action("Flush DNS")
        kwargs = fake_task.call_args.kwargs
        fake_task.return_value.start.assert_called_once()
        self.assertEqual(
            str(self.frame._action_buttons["Flush DNS"].cget("state")),
            "disabled")
        self.assertEqual(str(self.frame._ping_button.cget("state")),
                         "disabled")
        self.assertIn("Running", self.frame.status.text())
        self.assertEqual(kwargs["work"].args[0],
                         [["ipconfig", "/flushdns"]])
        kwargs["on_done"]("$ ipconfig /flushdns\nFlushed the DNS")
        self.assertEqual(
            str(self.frame._action_buttons["Flush DNS"].cget("state")),
            "normal")
        self.assertEqual(str(self.frame._ping_button.cget("state")), "normal")
        self.assertIn("Flushed the DNS",
                      self.frame._output.get("1.0", "end"))
        self.assertIn("Done", self.frame.status.text())

    @patch.object(network.tasks, "BackgroundTask")
    def test_on_error_reenables_and_reports(self, fake_task):
        self.frame._action("Flush DNS")
        kwargs = fake_task.call_args.kwargs
        kwargs["on_error"](RuntimeError("ipconfig /flushdns failed: nope"))
        self.assertEqual(
            str(self.frame._action_buttons["Flush DNS"].cget("state")),
            "normal")
        self.assertIn("nope", self.frame.status.text())

    def test_ping_button_toggles_start_stop_and_busy(self):
        self.assertEqual(str(self.frame._ping_button.cget("text")), "Start")
        with patch.object(network.threading, "Thread") as fake_thread, \
             patch.object(network.queue, "Queue") as fake_queue:
            self.frame._ping_entry.insert(0, "8.8.8.8")
            self.frame._start_ping()
        fake_thread.return_value.start.assert_called_once()
        self.assertEqual(str(self.frame._ping_button.cget("text")), "Stop")
        self.assertEqual(
            str(self.frame._action_buttons["Flush DNS"].cget("state")),
            "disabled")

    def test_ping_empty_entry_reports_error_without_thread(self):
        with patch.object(network.threading, "Thread") as fake_thread:
            self.frame._start_ping()
        fake_thread.assert_not_called()
        self.assertIn("host name", self.frame.status.text())

    def test_ping_count_spinbox_defaults_and_clamps(self):
        self.assertEqual(str(self.frame._ping_count.get()), "10")
        self.frame._ping_entry.insert(0, "8.8.8.8")
        with patch.object(network.threading, "Thread") as fake_thread:
            self.frame._ping_count.set("9999")
            self.frame._start_ping()
            self.assertEqual(fake_thread.call_args.kwargs["args"][3], 120)
            self.frame._ping_running = False  # reset the start guard
            self.frame._ping_count.set("0")
            self.frame._start_ping()
            self.assertEqual(fake_thread.call_args.kwargs["args"][3], 1)
            self.frame._ping_running = False
            self.frame._ping_count.set("abc")
            self.frame._start_ping()
            self.assertEqual(fake_thread.call_args.kwargs["args"][3], 10)
        self.assertEqual(fake_thread.call_count, 3)

    def test_drain_updates_stats_and_appends_lines(self):
        self.frame._ping_queue.put(("line", "Reply from 8.8.8.8: bytes=32"))
        self.frame._ping_queue.put(("stats", 3, 1))
        self.frame._drain_ping()
        self.assertIn("Reply from 8.8.8.8",
                      self.frame._ping_output.get("1.0", "end"))
        self.assertIn("3", str(self.frame._ping_stats.cget("text")))

    def test_stop_finalizes_and_reenables_start(self):
        self.frame._ping_queue.put(("done", {"sent": 4, "lost": 4}))
        self.frame._drain_ping()
        self.assertEqual(str(self.frame._ping_button.cget("text")), "Start")
        self.assertEqual(
            str(self.frame._action_buttons["Flush DNS"].cget("state")),
            "normal")
        self.assertIn("stopped", self.frame._ping_output.get("1.0", "end"))
        self.assertIn("4", self.frame.status.text())

    @patch.object(network.tasks, "BackgroundTask")
    def test_action_guarded_requires_admin(self, fake_task):
        with patch.object(network.widgets, "guard_admin",
                          REAL_GUARD_ADMIN), \
             patch("power_tool.core.admin.is_admin", return_value=False):
            self.frame._action("Flush DNS")
        fake_task.assert_not_called()
        self.assertIn("Run as administrator required",
                      self.frame.status.text())

    def _static_entries(self):
        return [self.frame._ip_entry, self.frame._mask_entry,
                self.frame._gw_entry, self.frame._dns_entry,
                self.frame._dns_alt_entry]

    def test_mode_radio_toggles_field_state(self):
        for entry in self._static_entries():
            self.assertEqual(str(entry.cget("state")), "disabled")
        self.frame._mode_var.set("Static")
        self.frame._mode_changed()
        for entry in self._static_entries():
            self.assertEqual(str(entry.cget("state")), "normal")
        self.frame._mode_var.set("DHCP")
        self.frame._mode_changed()
        for entry in self._static_entries():
            self.assertEqual(str(entry.cget("state")), "disabled")

    @patch.object(network.tasks, "BackgroundTask")
    @patch.object(network, "runner")
    def test_show_current_config_is_unguarded(self, fake_runner, fake_task):
        fake_runner.run.return_value = runner.Result(0, "conf", "")
        self.frame._adapters_loaded(["Ethernet"])
        with patch.object(network.widgets, "guard_admin",
                          REAL_GUARD_ADMIN), \
             patch("power_tool.core.admin.is_admin", return_value=False):
            self.frame._show_config()
        fake_task.return_value.start.assert_called_once()
        kwargs = fake_task.call_args.kwargs
        self.assertEqual(
            kwargs["work"].args[0], "Ethernet")
        kwargs["work"]()
        self.assertEqual(
            fake_runner.run.call_args.args[0],
            ["netsh", "interface", "ipv4", "show", "config",
             "name=Ethernet"])

    @patch.object(network.tasks, "BackgroundTask")
    def test_apply_requires_adapter_selection_warns(self, fake_task):
        with patch.object(network.widgets, "confirm", return_value=True):
            self.frame._apply()
        fake_task.assert_not_called()
        self.assertIn("Select an adapter", self.frame.status.text())
        self.assertEqual(str(self.frame._apply_button.cget("style")),
                         "Accent.TButton")

    @patch.object(network.tasks, "BackgroundTask")
    def test_apply_bad_ip_reports_error_without_task(self, fake_task):
        self.frame._adapters_loaded(["Ethernet"])
        self.frame._mode_var.set("Static")
        self.frame._mode_changed()
        self.frame._ip_entry.insert(0, "999.1.1.1")
        self.frame._mask_entry.insert(0, "255.255.255.0")
        self.frame._dns_entry.insert(0, "8.8.8.8")
        with patch.object(network.widgets, "confirm", return_value=True):
            self.frame._apply()
        fake_task.assert_not_called()
        self.assertIn("Invalid IP address", self.frame.status.text())

    @patch.object(network.tasks, "BackgroundTask")
    def test_apply_guarded_then_confirmed_before_running(self, fake_task):
        self.frame._adapters_loaded(["Ethernet"])
        # Phase 1: not admin -> guard blocks before confirm is even asked.
        with patch.object(network.widgets, "guard_admin",
                          REAL_GUARD_ADMIN), \
             patch("power_tool.core.admin.is_admin", return_value=False), \
             patch.object(network.widgets,
                          "confirm", return_value=True) as fake_confirm:
            self.frame._apply()
        fake_task.assert_not_called()
        fake_confirm.assert_not_called()
        self.assertIn("Run as administrator required",
                      self.frame.status.text())
        # Phase 2: admin, but confirmation declined -> no task.
        with patch.object(network.widgets, "guard_admin",
                          return_value=True), \
             patch.object(network.widgets, "confirm", return_value=False):
            self.frame._apply()
        fake_task.assert_not_called()
        self.assertIn("Cancelled", self.frame.status.text())
        # Phase 3: admin + confirm -> task starts with the dhcp commands.
        with patch.object(network.widgets, "guard_admin",
                          return_value=True), \
             patch.object(network.widgets,
                          "confirm", return_value=True) as fake_confirm:
            self.frame._apply()
        kwargs = fake_task.call_args.kwargs
        self.assertEqual(kwargs["work"].args[0],
                         network.dhcp_commands("Ethernet"))
        message = fake_confirm.call_args.args[2]
        self.assertIn("netsh interface ipv4 set address name=Ethernet dhcp",
                      message)
        self.assertIn("netsh interface ipv4 set dns name=Ethernet dhcp",
                      message)
        self.assertEqual(
            str(self.frame._apply_button.cget("state")), "disabled")
        kwargs["on_done"]("$ netsh ...\nOk.")
        self.assertEqual(str(self.frame._apply_button.cget("state")),
                         "normal")
        self.assertIn("IP configuration applied.",
                      self.frame.status.text())

    @patch.object(network.tasks, "BackgroundTask")
    def test_refresh_populates_adapter_combo(self, fake_task):
        with patch.object(network, "runner") as fake_runner:
            fake_runner.run.return_value = runner.Result(
                0, PARSE_ADAPTERS_SAMPLE, "")
            self.frame._refresh_adapters()
            kwargs = fake_task.call_args.kwargs
            adapters = kwargs["work"]()
            self.assertEqual(
                fake_runner.run.call_args.args[0],
                ["netsh", "interface", "show", "interface"])
        self.assertEqual(
            str(self.frame._refresh_button.cget("state")), "disabled")
        kwargs["on_done"](adapters)
        self.assertEqual(list(self.frame._adapter_combo.cget("values")),
                         ["Ethernet", "Ethernet 2"])
        self.assertEqual(self.frame._adapter_combo.get(), "Ethernet")
        self.assertEqual(str(self.frame._refresh_button.cget("state")),
                         "normal")


if __name__ == "__main__":
    unittest.main()
