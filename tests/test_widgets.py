import unittest
import tkinter as tk
from unittest.mock import patch

from power_tool.core import theme, widgets


class StatusPaneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        theme.apply_theme(self.root, "dark")
        self.status = widgets.StatusPane(self.root)
        self.status.pack()

    def test_starts_idle_ready(self):
        self.assertEqual(self.status.text(), "Ready")

    def test_set_success_updates_text_and_style(self):
        self.status.set_success("All good")
        self.assertEqual(self.status.text(), "All good")

    def test_set_error_updates_text(self):
        self.status.set_error("Boom failed")
        self.assertEqual(self.status.text(), "Boom failed")

    def test_set_working_updates_text(self):
        self.status.set_working("Crunching")
        self.assertEqual(self.status.text(), "Crunching")


class GuardAdminTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        theme.apply_theme(self.root, "dark")
        self.status = widgets.StatusPane(self.root)

    def test_guard_passes_when_admin(self):
        with patch("power_tool.core.admin.is_admin", return_value=True):
            self.assertTrue(widgets.guard_admin(self.status))

    def test_guard_blocks_and_sets_error_when_not_admin(self):
        with patch("power_tool.core.admin.is_admin", return_value=False):
            self.assertFalse(widgets.guard_admin(self.status))
        self.assertIn("administrator", self.status.text().lower())


class CopyTextTests(unittest.TestCase):
    def test_copy_text_sets_clipboard(self):
        root = tk.Tk()
        root.withdraw()
        try:
            widgets.copy_text(root, "copied-value")
            self.assertEqual(root.clipboard_get(), "copied-value")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
