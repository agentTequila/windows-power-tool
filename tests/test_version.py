import inspect
import unittest
from power_tool import __version__
from power_tool import main as main_module

class VersionTests(unittest.TestCase):
    def test_version_format(self):
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")
    def test_version_is_1_1_0(self):
        self.assertEqual(__version__, "1.3.0")
    def test_window_title_includes_version(self):
        src = inspect.getsource(main_module)
        self.assertIn('f"Windows Power Tool {__version__}"', src)
