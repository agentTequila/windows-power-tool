import unittest
from unittest.mock import patch

import winreg as real_winreg

from power_tool.tools import usb_guard


class FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class IsBlockedTests(unittest.TestCase):
    @patch.object(usb_guard, "winreg")
    def test_blocked_when_deny_all_is_one(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        fake_winreg.QueryValueEx.return_value = (1, 4)
        self.assertTrue(usb_guard.is_blocked())

    @patch.object(usb_guard, "winreg")
    def test_blocked_when_only_class_deny_read_is_one(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        fake_winreg.QueryValueEx.side_effect = [(0, 4), (1, 4)]
        self.assertTrue(usb_guard.is_blocked())

    @patch.object(usb_guard, "winreg")
    def test_not_blocked_when_values_zero(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        fake_winreg.QueryValueEx.return_value = (0, 4)
        self.assertFalse(usb_guard.is_blocked())

    @patch.object(usb_guard, "winreg")
    def test_not_blocked_when_policy_key_missing(self, fake_winreg):
        fake_winreg.OpenKey.side_effect = FileNotFoundError("no key")
        self.assertFalse(usb_guard.is_blocked())

    @patch.object(usb_guard, "winreg")
    def test_reads_root_key_first_in_64bit_view(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        fake_winreg.QueryValueEx.return_value = (0, 4)
        usb_guard.is_blocked()
        args = fake_winreg.OpenKey.call_args_list[0][0]
        self.assertEqual(args[0], fake_winreg.HKEY_LOCAL_MACHINE)
        self.assertEqual(args[1], usb_guard.POLICY_ROOT)
        self.assertEqual(args[2], 0)
        self.assertTrue(args[3] & real_winreg.KEY_WOW64_64KEY)


class SetBlockedTests(unittest.TestCase):
    @patch.object(usb_guard, "winreg")
    def test_block_sets_deny_all_and_class_values(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        fake_winreg.CreateKeyEx.return_value = FakeKey()
        usb_guard.set_blocked(True)
        values = {call[0][1]: call[0][4]
                  for call in fake_winreg.SetValueEx.call_args_list}
        self.assertEqual(values[usb_guard.DENY_ALL], 1)
        self.assertEqual(values[usb_guard.DENY_READ], 1)
        self.assertEqual(values[usb_guard.DENY_WRITE], 1)

    @patch.object(usb_guard, "winreg")
    def test_block_writes_root_and_class_keys(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        fake_winreg.CreateKeyEx.return_value = FakeKey()
        usb_guard.set_blocked(True)
        created = [call[0][1] for call in fake_winreg.CreateKeyEx.call_args_list]
        self.assertEqual(created, [usb_guard.POLICY_ROOT, usb_guard.CLASS_PATH])

    @patch.object(usb_guard, "winreg")
    def test_unblock_purges_deny_all_and_class_key(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        usb_guard.set_blocked(False)
        deleted_values = [call[0][1]
                          for call in fake_winreg.DeleteValue.call_args_list]
        deleted_keys = [call[0][1]
                        for call in fake_winreg.DeleteKey.call_args_list]
        self.assertIn(usb_guard.DENY_ALL, deleted_values)
        self.assertIn(usb_guard.CLASS_PATH, deleted_keys)
        deny_sets = [call for call in fake_winreg.SetValueEx.call_args_list
                     if call[0][1] in (usb_guard.DENY_READ, usb_guard.DENY_WRITE,
                                       usb_guard.DENY_ALL)]
        self.assertEqual(deny_sets, [])

    @patch.object(usb_guard, "winreg")
    def test_unblock_tolerates_already_purged_keys(self, fake_winreg):
        fake_winreg.OpenKey.side_effect = FileNotFoundError("gone")
        fake_winreg.DeleteValue.side_effect = FileNotFoundError("gone")
        fake_winreg.DeleteKey.side_effect = FileNotFoundError("gone")
        usb_guard.set_blocked(False)  # must not raise

    @patch.object(usb_guard, "winreg")
    def test_block_writes_dword_in_64bit_view(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        fake_winreg.CreateKeyEx.return_value = FakeKey()
        usb_guard.set_blocked(True)
        create_args = fake_winreg.CreateKeyEx.call_args_list[0][0]
        self.assertEqual(create_args[0], fake_winreg.HKEY_LOCAL_MACHINE)
        self.assertEqual(create_args[1], usb_guard.POLICY_ROOT)
        self.assertTrue(create_args[3] & real_winreg.KEY_WOW64_64KEY)
        sample = fake_winreg.SetValueEx.call_args_list[0][0]
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
        self.assertEqual(fake_winreg.CreateKeyEx.call_count, 2)


if __name__ == "__main__":
    unittest.main()
