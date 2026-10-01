import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tkinter as tk

from power_tool.core import theme
from power_tool.tools import speedup


class BrowserSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()
        theme.apply_theme(cls.root, "dark")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.frame = speedup.SpeedupFrame(self.root)

    def test_three_individual_browser_vars_all_checked_by_default(self):
        self.assertEqual(sorted(self.frame._browser_vars),
                         ["Chrome", "Edge", "Firefox"])
        selected = self.frame._selected_browsers()
        self.assertEqual(selected, ["Chrome", "Edge", "Firefox"])

    def test_unchecking_one_browser_excludes_it(self):
        self.frame._browser_vars["Chrome"].set(False)
        self.assertEqual(self.frame._selected_browsers(),
                         ["Edge", "Firefox"])

    def test_gather_targets_follows_selection(self):
        fake_env = {"TEMP": r"C:\t", "WINDIR": r"C:\Windows",
                    "APPDATA": r"C:\AppData"}
        with patch.object(speedup, "browser_cleanup_targets",
                          side_effect=lambda browser, env: [Path(browser)]):
            targets = self.frame._gather_targets(fake_env)
        self.assertIn(Path("Chrome"), targets)
        self.assertIn(Path("Edge"), targets)
        self.assertIn(Path("Firefox"), targets)
        self.frame._browser_vars["Firefox"].set(False)
        with patch.object(speedup, "browser_cleanup_targets",
                          side_effect=lambda browser, env: [Path(browser)]):
            targets = self.frame._gather_targets(fake_env)
        self.assertNotIn(Path("Firefox"), targets)

    def test_gather_targets_excludes_temp_when_unchecked(self):
        fake_env = {"TEMP": r"C:\t", "WINDIR": r"C:\Windows",
                    "APPDATA": r"C:\AppData"}
        self.frame._temp_var.set(False)
        with patch.object(speedup, "browser_cleanup_targets",
                          side_effect=lambda browser, env: [Path(browser)]):
            targets = self.frame._gather_targets(fake_env)
        self.assertEqual(len(targets), 3)


if __name__ == "__main__":
    unittest.main()
