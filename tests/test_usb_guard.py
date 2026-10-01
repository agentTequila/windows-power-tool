import unittest
from unittest.mock import patch

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
    def test_reads_64bit_view_of_policy_path(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        fake_winreg.QueryValueEx.return_value = (0, 4)
        usb_guard.is_blocked()
        args = fake_winreg.OpenKey.call_args[0]
        self.assertEqual(args[0], fake_winreg.HKEY_LOCAL_MACHINE)
        self.assertEqual(args[1], usb_guard.POLICY_PATH)
        self.assertEqual(args[2], 0)


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
    def test_repairs_legacy_usbsfor_start_to_enabled(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        fake_winreg.CreateKeyEx.return_value = FakeKey()
        usb_guard.set_blocked(True)
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


if __name__ == "__main__":
    unittest.main()
