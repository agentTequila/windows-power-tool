import os
import unittest
from unittest.mock import MagicMock, patch

import tkinter as tk

from power_tool.core import runner, theme
from power_tool.tools import console


class ShellArgvTests(unittest.TestCase):
    def test_shell_argv_powershell(self):
        self.assertEqual(console.shell_argv("powershell", "Get-Date"),
                         ["powershell.exe", "-NoLogo", "-NonInteractive",
                          "-Command", "Get-Date"])

    def test_shell_argv_cmd(self):
        self.assertEqual(console.shell_argv("cmd", "dir"),
                         ["cmd.exe", "/d", "/s", "/c", "dir"])

    def test_shell_argv_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            console.shell_argv("bash", "ls")


class StartDetachedCwdTests(unittest.TestCase):
    """runner.start_detached gains an optional cwd (consumed by Console)."""

    @patch.object(runner.subprocess, "Popen")
    def test_passes_cwd_through(self, fake_popen):
        fake_popen.return_value.pid = 99
        result = runner.start_detached(["notepad.exe"], cwd="C:\\Temp")
        fake_popen.assert_called_once_with(["notepad.exe"], cwd="C:\\Temp")
        self.assertEqual(result, 99)

    @patch.object(runner.subprocess, "Popen")
    def test_cwd_defaults_to_none_backward_compatible(self, fake_popen):
        fake_popen.return_value.pid = 7
        result = runner.start_detached(["notepad.exe"])
        fake_popen.assert_called_once_with(["notepad.exe"], cwd=None)
        self.assertEqual(result, 7)


def _fake_proc(pid=4321, lines=(), rc=0):
    proc = MagicMock()
    proc.pid = pid
    proc.stdout = iter(list(lines))
    proc.wait.return_value = rc
    return proc


class ConsoleFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()
        theme.apply_theme(cls.root, "dark")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.frame = console.ConsoleFrame(self.root)

    def _run_and_finish(self, command, proc=None):
        """Drive one mocked command end-to-end: _run -> reader -> drain."""
        proc = proc or _fake_proc()
        with patch.object(console.subprocess, "Popen", return_value=proc), \
             patch.object(console.threading, "Thread") as fake_thread:
            self.frame._command_entry.delete(0, "end")
            self.frame._command_entry.insert(0, command)
            self.frame._run()
            kwargs = fake_thread.call_args.kwargs
            kwargs["target"](*kwargs["args"])
        self.frame._drain()
        return proc

    def test_mode_radios_default_powershell(self):
        self.assertEqual(self.frame._mode.get(), "powershell")
        self.assertEqual(len(self.frame._mode_radios), 2)

    def test_create_returns_console_frame(self):
        frame = console.create(self.root)
        self.assertIsInstance(frame, console.ConsoleFrame)

    def test_append_output_caps_at_max_lines(self):
        for i in range(3000):
            self.frame.append_output(f"line {i}")
        # end-1c is real_lines + 1 when the buffer ends with "\n"
        count = int(float(self.frame._output.index("end-1c"))) - 1
        self.assertLessEqual(count, console.ConsoleFrame._MAX_LINES)
        self.assertEqual(count, 2000)
        text = self.frame._output.get("1.0", "end")
        self.assertTrue(text.startswith("line 1000"))  # oldest trimmed
        self.assertNotIn("line 999\n", text)
        self.assertIn("line 2999", text)  # newest kept

    def test_run_reads_on_background_thread(self):
        proc = _fake_proc(lines=[b"hi\n"])
        with patch.object(console.subprocess, "Popen",
                          return_value=proc) as fake_popen, \
             patch.object(console.threading, "Thread") as fake_thread:
            self.frame._command_entry.insert(0, "whoami")
            self.frame._run()
            fake_thread.return_value.start.assert_called_once()
            kwargs = fake_thread.call_args.kwargs
            # correct shell argv and no-console creationflags
            self.assertEqual(fake_popen.call_args.args[0],
                             ["powershell.exe", "-NoLogo", "-NonInteractive",
                              "-Command", "whoami"])
            self.assertTrue(fake_popen.call_args.kwargs["creationflags"] > 0)
            # busy: entry + radios disabled, Stop text shown
            self.assertEqual(
                str(self.frame._command_entry.cget("state")), "disabled")
            for radio in self.frame._mode_radios:
                self.assertEqual(str(radio.cget("state")), "disabled")
            self.assertEqual(str(self.frame._run_button.cget("text")), "Stop")
            # Run disabled while busy: re-entry spawns nothing
            self.frame._run()
            self.assertEqual(fake_popen.call_count, 1)
            # reader work fn runs (queue only), then drain on the GUI thread
            kwargs["target"](*kwargs["args"])
        self.frame._drain()
        self.assertIn("hi", self.frame._output.get("1.0", "end"))
        self.assertEqual(str(self.frame._run_button.cget("state")), "normal")
        self.assertEqual(str(self.frame._run_button.cget("text")), "Run")
        self.assertEqual(
            str(self.frame._command_entry.cget("state")), "normal")
        self.assertIn("finished", self.frame.status.text())

    def test_done_with_nonzero_exit_reports_error_with_excerpt(self):
        proc = _fake_proc(lines=[b"Access denied by policy\n"], rc=1)
        self._run_and_finish("netsh something", proc=proc)
        self.assertIn("Access denied", self.frame.status.text())
        self.assertIn("1", self.frame.status.text())
        self.assertEqual(str(self.frame._run_button.cget("text")), "Run")
        self.assertEqual(
            str(self.frame._run_button.cget("state")), "normal")
        self.assertIn("Access denied",
                      self.frame._output.get("1.0", "end"))

    def test_run_popen_failure_reports_error(self):
        with patch.object(console.subprocess, "Popen",
                          side_effect=OSError("No such file")):
            self.frame._command_entry.insert(0, "whoami")
            self.frame._run()
        self.assertIn("No such file", self.frame.status.text())
        self.assertEqual(str(self.frame._run_button.cget("text")), "Run")
        self.assertEqual(
            str(self.frame._command_entry.cget("state")), "normal")

    def test_stop_dispatches_taskkill_off_the_gui_thread(self):
        proc = _fake_proc()
        with patch.object(console.subprocess, "Popen", return_value=proc), \
             patch.object(console.threading, "Thread") as fake_thread, \
             patch.object(console, "runner") as fake_runner:
            self.frame._command_entry.insert(0, "ping -t 8.8.8.8")
            self.frame._run()
            stop_event = self.frame._stop_event
            self.frame._stop()
            # taskkill must NOT run synchronously on the calling (GUI) thread
            fake_runner.run.assert_not_called()
            # ...it is dispatched to a background thread instead (last Thread
            # construction is the kill; _run's reader thread came first)
            target = fake_thread.call_args.kwargs["target"]
            target()
            fake_runner.run.assert_called_once_with(
                ["taskkill", "/PID", "4321", "/T", "/F"], timeout=15)
            self.assertTrue(stop_event.is_set())

    def test_stop_finalizes_ui_without_reader_sentinel(self):
        proc = _fake_proc()
        with patch.object(console.subprocess, "Popen", return_value=proc), \
             patch.object(console.threading, "Thread"), \
             patch.object(console, "runner"):
            self.frame._command_entry.insert(0, "ping -t 8.8.8.8")
            self.frame._run()
            # reader thread never runs: no "done" sentinel will ever arrive
            self.frame._stop()
            self.assertEqual(str(self.frame._run_button.cget("text")), "Run")
            self.assertEqual(
                str(self.frame._run_button.cget("state")), "normal")
            self.assertEqual(
                str(self.frame._command_entry.cget("state")), "normal")
            self.assertIn("stopped", self.frame.status.text())
            self.assertFalse(self.frame._running)
            # a second Stop is a safe no-op
            self.frame._stop()
            # a late reader sentinel must not double-finalize
            self.frame._queue.put(("done", 1))
            self.frame._drain()
            self.assertIn("stopped", self.frame.status.text())
            self.assertNotIn("exited with code",
                             self.frame.status.text())

    def test_late_reader_sentinel_after_stop_does_not_refinalize(self):
        proc = _fake_proc(rc=1)
        with patch.object(console.subprocess, "Popen", return_value=proc), \
             patch.object(console.threading, "Thread") as fake_thread, \
             patch.object(console, "runner"):
            self.frame._command_entry.insert(0, "ping -t 8.8.8.8")
            self.frame._run()
            reader = fake_thread.call_args.kwargs  # _run's reader thread
            self.frame._stop()  # finalizes immediately, no sentinel needed
            # real reader finally reaches EOF and emits its "done" late
            reader["target"](*reader["args"])
        self.frame._drain()
        self.assertEqual(str(self.frame._run_button.cget("text")), "Run")
        self.assertEqual(
            str(self.frame._run_button.cget("state")), "normal")
        self.assertIn("stopped", self.frame.status.text())
        self.assertNotIn("exited with code", self.frame.status.text())

    def test_history_up_down_recall(self):
        self._run_and_finish("ipconfig /flushdns")
        self._run_and_finish("dir C:\\")
        self.assertEqual(self.frame._history,
                         ["ipconfig /flushdns", "dir C:\\"])
        self.frame._recall_up()
        self.assertEqual(self.frame._command_entry.get(), "dir C:\\")
        self.frame._recall_up()
        self.assertEqual(self.frame._command_entry.get(), "ipconfig /flushdns")
        self.frame._recall_up()  # stays put — no IndexError past the start
        self.assertEqual(self.frame._command_entry.get(), "ipconfig /flushdns")
        self.frame._recall_down()
        self.assertEqual(self.frame._command_entry.get(), "dir C:\\")
        self.frame._recall_down()  # past the newest → cleared
        self.assertEqual(self.frame._command_entry.get(), "")
        self.frame._recall_down()  # still cleared, no error
        self.assertEqual(self.frame._command_entry.get(), "")

    def test_history_skips_consecutive_duplicates_and_blanks(self):
        self._run_and_finish("whoami")
        self._run_and_finish("whoami")
        # blank input: _run errors out without a thread or history entry
        self.frame._command_entry.delete(0, "end")
        self.frame._command_entry.insert(0, "   ")
        self.frame._run()
        self.assertEqual(self.frame._history, ["whoami"])
        self.assertIn("Type a command", self.frame.status.text())

    def test_clear_empties_output(self):
        self.frame.append_output("leftover")
        self.frame._clear()
        self.assertEqual(self.frame._output.get("1.0", "end").strip(), "")

    def test_open_console_buttons_spawn_detached(self):
        home = os.environ.get("USERPROFILE") or None
        with patch.object(console, "runner") as fake_runner:
            self.frame._open_powershell()
            fake_runner.start_detached.assert_called_once_with(
                ["powershell.exe", "-NoExit"], cwd=home)
            if home is not None:
                self.assertTrue(
                    fake_runner.start_detached.call_args.kwargs["cwd"]
                    .endswith(os.path.basename(home)))
            fake_runner.reset_mock()
            self.frame._open_cmd()
            fake_runner.start_detached.assert_called_once_with(
                ["cmd.exe", "/k"], cwd=home)


if __name__ == "__main__":
    unittest.main()
