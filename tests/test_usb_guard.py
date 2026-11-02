import unittest
from unittest.mock import patch

import tkinter as tk

from power_tool.core import theme
from power_tool.tools import usb_guard


class FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class IsBlockedTests(unittest.TestCase):
    @patch.object(usb_guard, "winreg")
    def test_blocked_when_deny_read_is_one(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        fake_winreg.QueryValueEx.return_value = (1, 4)
        self.assertTrue(usb_guard.is_blocked())

    @patch.object(usb_guard, "winreg")
    def test_not_blocked_when_value_zero(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        fake_winreg.QueryValueEx.return_value = (0, 4)
        self.assertFalse(usb_guard.is_blocked())

    @patch.object(usb_guard, "winreg")
    def test_not_blocked_when_policy_key_missing(self, fake_winreg):
        fake_winreg.OpenKey.side_effect = FileNotFoundError("no key")
        self.assertFalse(usb_guard.is_blocked())

    @patch.object(usb_guard, "winreg")
    def test_legacy_usbstor_start_four_counts_as_blocked(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        # Deny_Read=0, Deny_Write=0, USBSTOR Start=4.
        fake_winreg.QueryValueEx.side_effect = [(0, 4), (0, 4), (4, 4)]
        self.assertTrue(usb_guard.is_blocked())

    @patch.object(usb_guard, "winreg")
    def test_write_only_is_not_a_read_block(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        fake_winreg.QueryValueEx.side_effect = [(0, 4), (1, 4),
                                                (0, 4), (1, 4)]
        self.assertEqual(usb_guard.read_state(),
                         usb_guard.STATE_WRITE_PROTECTED)
        self.assertFalse(usb_guard.is_blocked())

    @patch.object(usb_guard, "winreg")
    def test_reads_64bit_view_of_policy_path(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        fake_winreg.QueryValueEx.return_value = (0, 4)
        usb_guard.is_blocked()
        policy_calls = [
            call for call in fake_winreg.OpenKey.call_args_list
            if call[0][1] == usb_guard.POLICY_PATH]
        self.assertTrue(policy_calls)
        args = policy_calls[0][0]
        self.assertEqual(args[0], fake_winreg.HKEY_LOCAL_MACHINE)
        self.assertEqual(args[2], 0)
        self.assertTrue(args[3] & fake_winreg.KEY_WOW64_64KEY)


class ReadStateTests(unittest.TestCase):
    def _state(self, deny_read, deny_write, start):
        with patch.object(usb_guard, "_policy_flags",
                          return_value=(deny_read, deny_write)), \
             patch.object(usb_guard, "driver_start", return_value=start):
            return usb_guard.read_state()

    def test_allowed_when_nothing_is_set(self):
        self.assertEqual(self._state(0, 0, 3), usb_guard.STATE_ALLOWED)

    def test_deny_read_is_blocked(self):
        self.assertEqual(self._state(1, 1, 3), usb_guard.STATE_BLOCKED)

    def test_deny_write_only_is_write_protected(self):
        self.assertEqual(self._state(0, 1, 3),
                         usb_guard.STATE_WRITE_PROTECTED)

    def test_usbstor_start_four_is_hidden(self):
        self.assertEqual(self._state(0, 0, 4), usb_guard.STATE_HIDDEN)

    def test_deny_read_wins_over_legacy_start(self):
        self.assertEqual(self._state(1, 1, 4), usb_guard.STATE_BLOCKED)


class SetBlockedTests(unittest.TestCase):
    @patch.object(usb_guard, "winreg")
    def test_block_sets_deny_read_and_write(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        fake_winreg.CreateKeyEx.return_value = FakeKey()
        usb_guard.set_blocked(True)
        values = {call[0][1]: call[0][4]
                  for call in fake_winreg.SetValueEx.call_args_list}
        self.assertEqual(values[usb_guard.DENY_READ], 1)
        self.assertEqual(values[usb_guard.DENY_WRITE], 1)

    @patch.object(usb_guard, "winreg")
    def test_unblock_clears_deny_values(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        fake_winreg.CreateKeyEx.return_value = FakeKey()
        usb_guard.set_blocked(False)
        values = {call[0][1]: call[0][4]
                  for call in fake_winreg.SetValueEx.call_args_list}
        self.assertEqual(values[usb_guard.DENY_READ], 0)
        self.assertEqual(values[usb_guard.DENY_WRITE], 0)

    @patch.object(usb_guard, "winreg")
    def test_writes_dword_in_64bit_view(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        fake_winreg.CreateKeyEx.return_value = FakeKey()
        usb_guard.set_blocked(True)
        create_args = fake_winreg.CreateKeyEx.call_args[0]
        self.assertEqual(create_args[0], fake_winreg.HKEY_LOCAL_MACHINE)
        self.assertEqual(create_args[1], usb_guard.POLICY_PATH)
        access = create_args[3]
        self.assertTrue(access & fake_winreg.KEY_WOW64_64KEY)
        sample = fake_winreg.SetValueEx.call_args[0]
        self.assertEqual(sample[2], 0)
        self.assertEqual(sample[3], fake_winreg.REG_DWORD)

    @patch.object(usb_guard, "winreg")
    def test_block_repairs_legacy_usbstor_start_to_enabled(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        fake_winreg.CreateKeyEx.return_value = FakeKey()
        usb_guard.set_blocked(True)
        start_calls = [call[0] for call in fake_winreg.SetValueEx.call_args_list
                       if call[0][1] == usb_guard.VALUE_NAME]
        self.assertEqual(len(start_calls), 1)
        self.assertEqual(start_calls[0][4], usb_guard.ENABLED)

    @patch.object(usb_guard, "winreg")
    def test_unblock_also_repairs_legacy_usbstor_start(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        fake_winreg.CreateKeyEx.return_value = FakeKey()
        usb_guard.set_blocked(False)
        start_calls = [call[0] for call in fake_winreg.SetValueEx.call_args_list
                       if call[0][1] == usb_guard.VALUE_NAME]
        self.assertEqual(len(start_calls), 1)
        self.assertEqual(start_calls[0][4], usb_guard.ENABLED)

    @patch.object(usb_guard, "winreg")
    def test_survives_missing_legacy_key(self, fake_winreg):
        fake_winreg.OpenKey.side_effect = FileNotFoundError("no key")
        fake_winreg.CreateKeyEx.return_value = FakeKey()
        usb_guard.set_blocked(True)  # must not raise
        fake_winreg.CreateKeyEx.assert_called_once()


class UsbGuardFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()
        theme.apply_theme(cls.root, "dark")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def _frame(self, state=usb_guard.STATE_ALLOWED):
        with patch.object(usb_guard, "read_state", return_value=state):
            frame = usb_guard.UsbGuardFrame(self.root)
        frame.pack()
        self.addCleanup(frame.destroy)
        return frame

    def test_opening_the_tool_does_not_write_the_registry(self):
        with patch.object(usb_guard, "read_state",
                          return_value=usb_guard.STATE_ALLOWED), \
             patch.object(usb_guard, "_ensure_driver_enabled") as fake_start, \
             patch.object(usb_guard, "set_blocked") as fake_set:
            frame = usb_guard.UsbGuardFrame(self.root)
        self.addCleanup(frame.destroy)
        fake_start.assert_not_called()
        fake_set.assert_not_called()

    def test_blocked_state_is_shown(self):
        frame = self._frame(usb_guard.STATE_BLOCKED)
        self.assertIn("BLOCKED", str(frame._state_label.cget("text")))
        self.assertEqual(str(frame._state_label.cget("style")),
                         "Error.TLabel")

    def test_write_protected_state_is_shown_as_a_warning(self):
        frame = self._frame(usb_guard.STATE_WRITE_PROTECTED)
        self.assertIn("WRITE-PROTECTED", str(frame._state_label.cget("text")))
        self.assertEqual(str(frame._state_label.cget("style")),
                         "Warn.TLabel")

    def test_legacy_hidden_state_is_shown(self):
        frame = self._frame(usb_guard.STATE_HIDDEN)
        self.assertIn("HIDDEN", str(frame._state_label.cget("text")))
        self.assertIn("legacy", str(frame._state_label.cget("text")).lower())

    def test_allowed_state_is_shown(self):
        frame = self._frame(usb_guard.STATE_ALLOWED)
        self.assertIn("ALLOWED", str(frame._state_label.cget("text")))
        self.assertEqual(str(frame._state_label.cget("style")),
                         "Success.TLabel")

    def test_block_tells_the_user_to_reconnect(self):
        frame = self._frame(usb_guard.STATE_ALLOWED)
        with patch.object(usb_guard.widgets, "guard_admin",
                          return_value=True), \
             patch.object(usb_guard, "set_blocked") as fake_set, \
             patch.object(usb_guard, "read_state",
                          return_value=usb_guard.STATE_BLOCKED):
            frame._block()
        fake_set.assert_called_once_with(True)
        self.assertIn("Reconnect the drive", frame.status.text())
        self.assertIn("restart", frame.status.text().lower())

    def test_unblock_tells_the_user_to_reconnect(self):
        frame = self._frame(usb_guard.STATE_BLOCKED)
        with patch.object(usb_guard.widgets, "guard_admin",
                          return_value=True), \
             patch.object(usb_guard, "set_blocked") as fake_set, \
             patch.object(usb_guard, "read_state",
                          return_value=usb_guard.STATE_ALLOWED):
            frame._unblock()
        fake_set.assert_called_once_with(False)
        self.assertIn("Reconnect the drive", frame.status.text())
        self.assertIn("restart", frame.status.text().lower())

    def test_toggle_requires_admin(self):
        frame = self._frame(usb_guard.STATE_ALLOWED)
        with patch("power_tool.core.admin.is_admin", return_value=False), \
             patch.object(usb_guard, "set_blocked") as fake_set:
            frame._block()
        fake_set.assert_not_called()
        self.assertIn("administrator", frame.status.text().lower())

    def test_registry_failure_surfaces_in_the_status_pane(self):
        frame = self._frame(usb_guard.STATE_ALLOWED)
        with patch.object(usb_guard.widgets, "guard_admin",
                          return_value=True), \
             patch.object(usb_guard, "set_blocked",
                          side_effect=OSError("denied")), \
             patch.object(usb_guard, "read_state",
                          return_value=usb_guard.STATE_ALLOWED):
            frame._block()
        self.assertIn("Registry write failed", frame.status.text())
        self.assertIn("denied", frame.status.text())
        self.assertEqual(str(frame.status._label.cget("style")),
                         "Error.TLabel")


if __name__ == "__main__":
    unittest.main()
