import unittest
from unittest.mock import patch

import tkinter as tk

from power_tool.core import runner, theme
from power_tool.tools import network


class PingArgsTests(unittest.TestCase):
    def test_builds_ping_command(self):
        self.assertEqual(network.ping_args("example.com"),
                         ["ping", "-n", "4", "example.com"])

    def test_trims_whitespace(self):
        self.assertEqual(network.ping_args("  8.8.8.8  "),
                         ["ping", "-n", "4", "8.8.8.8"])

    def test_empty_host_raises(self):
        with self.assertRaises(ValueError):
            network.ping_args("   ")


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

    @patch.object(network.tasks, "BackgroundTask")
    def test_ping_empty_entry_reports_error_without_task(self, fake_task):
        self.frame._ping()
        fake_task.assert_not_called()
        self.assertIn("host name", self.frame.status.text())

    @patch.object(network.tasks, "BackgroundTask")
    def test_ping_builds_four_echo_command(self, fake_task):
        self.frame._ping_entry.insert(0, " 8.8.8.8 ")
        self.frame._ping()
        fake_task.return_value.start.assert_called_once()
        self.assertEqual(fake_task.call_args.kwargs["work"].args[0],
                         [["ping", "-n", "4", "8.8.8.8"]])


if __name__ == "__main__":
    unittest.main()
