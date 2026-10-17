import re
import unittest
from power_tool import __version__

class VersionTests(unittest.TestCase):
    def test_version_format(self):
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")
    def test_version_is_1_1_0(self):
        self.assertEqual(__version__, "1.1.0")
    def test_window_title_includes_version(self):
        from power_tool.main import PowerToolApp  # import only; title built in __init__
        self.assertIn(__version__, f"Windows Power Tool {__version__}")
