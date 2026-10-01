import unittest
from unittest.mock import patch

from power_tool.core import admin


class AdminTests(unittest.TestCase):
    def test_is_admin_true(self):
        with patch.object(admin.ctypes, "windll") as wl:
            wl.shell32.IsUserAnAdmin.return_value = 1
            self.assertTrue(admin.is_admin())

    def test_is_admin_false(self):
        with patch.object(admin.ctypes, "windll") as wl:
            wl.shell32.IsUserAnAdmin.return_value = 0
            self.assertFalse(admin.is_admin())

    def test_is_admin_swallows_exception(self):
        with patch.object(admin.ctypes, "windll") as wl:
            wl.shell32.IsUserAnAdmin.side_effect = OSError("boom")
            self.assertFalse(admin.is_admin())


if __name__ == "__main__":
    unittest.main()
