import unittest
from unittest.mock import patch

from power_tool.tools import usb_guard


class FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class ReadStateTests(unittest.TestCase):
    @patch.object(usb_guard, "winreg")
    def test_read_state_returns_dword_value(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        fake_winreg.QueryValueEx.return_value = (4, 4)
        self.assertEqual(usb_guard.read_state(), 4)

    @patch.object(usb_guard, "winreg")
    def test_read_state_returns_none_when_key_missing(self, fake_winreg):
        fake_winreg.OpenKey.side_effect = FileNotFoundError("no key")
        self.assertIsNone(usb_guard.read_state())

    @patch.object(usb_guard, "winreg")
    def test_read_state_uses_64bit_view_and_hklm(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        fake_winreg.QueryValueEx.return_value = (3, 4)
        usb_guard.read_state()
        args = fake_winreg.OpenKey.call_args[0]
        self.assertEqual(args[0], fake_winreg.HKEY_LOCAL_MACHINE)
        self.assertEqual(args[1], usb_guard.KEY_PATH)
        self.assertEqual(args[2], 0)


class WriteStateTests(unittest.TestCase):
    @patch.object(usb_guard, "winreg")
    def test_write_state_disables(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        usb_guard.write_state(usb_guard.DISABLED)
        args = fake_winreg.SetValueEx.call_args[0]
        self.assertEqual(args[1], usb_guard.VALUE_NAME)
        self.assertEqual(args[4], 4)
        self.assertEqual(args[3], fake_winreg.REG_DWORD)

    @patch.object(usb_guard, "winreg")
    def test_write_state_enables(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        usb_guard.write_state(usb_guard.ENABLED)
        self.assertEqual(fake_winreg.SetValueEx.call_args[0][4], 3)

    @patch.object(usb_guard, "winreg")
    def test_write_state_propagates_oserror(self, fake_winreg):
        fake_winreg.OpenKey.side_effect = PermissionError("denied")
        with self.assertRaises(OSError):
            usb_guard.write_state(usb_guard.DISABLED)


if __name__ == "__main__":
    unittest.main()
