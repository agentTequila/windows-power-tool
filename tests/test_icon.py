import importlib.util
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

from power_tool import main as app_main

REPO = Path(__file__).resolve().parent.parent
GEN_PATH = REPO / "assets" / "generate_icon.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_icon", GEN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gen = _load_generator()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.ico_path = Path(cls.gen.build(cls._tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_ico_header_declares_seven_sizes(self):
        data = self.ico_path.read_bytes()
        reserved, img_type, count = struct.unpack_from("<HHH", data, 0)
        self.assertEqual((reserved, img_type, count), (0, 1, 7))
        widths = set()
        for i in range(count):
            entry = 6 + 16 * i
            width, height = data[entry], data[entry + 1]
            widths.add(width if width else 256)
            self.assertEqual(height if height else 256, width if width else 256)
            self.assertEqual(struct.unpack_from("<H", data, entry + 4)[0], 1)
            self.assertEqual(struct.unpack_from("<H", data, entry + 6)[0], 32)
        self.assertEqual(widths, {16, 24, 32, 48, 64, 128, 256})

    def test_every_entry_offset_and_size_inside_file(self):
        data = self.ico_path.read_bytes()
        count = struct.unpack_from("<H", data, 4)[0]
        for i in range(count):
            entry = 6 + 16 * i
            size, offset = struct.unpack_from("<II", data, entry + 8)
            self.assertGreater(size, 0)
            self.assertGreaterEqual(offset, 6 + 16 * count)
            self.assertLessEqual(offset + size, len(data))
            self.assertEqual(data[offset:offset + 8],
                             b"\x89PNG\r\n\x1a\n")

    def test_preview_png_written(self):
        preview = Path(self._tmp.name) / "icon-256.png"
        self.assertTrue(preview.is_file())
        self.assertEqual(preview.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_sizes_constant_matches_spec(self):
        self.assertEqual(self.gen.SIZES, (16, 24, 32, 48, 64, 128, 256))


class IconPathTests(unittest.TestCase):
    def test_dev_path_points_at_repo_asset(self):
        path = app_main._icon_path()
        self.assertEqual(path, os.path.join(str(REPO), "assets", "icon.ico"))

    def test_frozen_path_uses_meipass(self):
        sentinel = r"C:\fake\_MEIPASS"
        missing = object()
        old_meipass = getattr(sys, "_MEIPASS", missing)
        old_frozen = getattr(sys, "frozen", missing)
        sys._MEIPASS = sentinel
        sys.frozen = True
        try:
            self.assertEqual(
                app_main._icon_path(),
                os.path.join(sentinel, "assets", "icon.ico"))
        finally:
            if old_meipass is missing:
                del sys._MEIPASS
            else:
                sys._MEIPASS = old_meipass
            if old_frozen is missing:
                del sys.frozen
            else:
                sys.frozen = old_frozen

    def test_missing_icon_is_silent_no_raise(self):
        missing = object()
        old = getattr(app_main, "_icon_path", missing)
        app_main._icon_path = (
            lambda: os.path.join(str(REPO), "assets", "no_such_icon.ico"))
        try:
            app_main._apply_icon(object())
        finally:
            if old is missing:
                del app_main._icon_path
            else:
                app_main._icon_path = old

    def test_repo_icon_exists(self):
        self.assertTrue(os.path.isfile(os.path.join(
            str(REPO), "assets", "icon.ico")))


if __name__ == "__main__":
    unittest.main()
