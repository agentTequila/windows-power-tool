import json
import tempfile
import unittest
from pathlib import Path

from power_tool.core import theme


class PaletteTests(unittest.TestCase):
    def test_both_palettes_have_identical_keys(self):
        self.assertEqual(set(theme.PALETTES["dark"].keys()), set(theme.PALETTES["light"].keys()))

    def test_palette_keys_match_spec(self):
        expected = {"bg", "panel", "panel2", "fg", "dim", "accent", "accent_fg",
                    "success", "danger", "warn", "border", "entry_bg"}
        self.assertEqual(set(theme.PALETTES["dark"].keys()), expected)

    def test_get_palette_returns_copy(self):
        pal = theme.get_palette("dark")
        pal["bg"] = "mutated"
        self.assertNotEqual(theme.PALETTES["dark"]["bg"], "mutated")

    def test_get_palette_unknown_raises(self):
        with self.assertRaises(KeyError):
            theme.get_palette("neon")


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "settings.json"
        self.addCleanup(self.tmp.cleanup)

    def test_load_missing_file_returns_default(self):
        self.assertEqual(theme.load_theme_name(self.path), theme.DEFAULT_THEME)

    def test_load_corrupt_file_returns_default(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(theme.load_theme_name(self.path), theme.DEFAULT_THEME)

    def test_load_invalid_theme_name_returns_default(self):
        self.path.write_text(json.dumps({"theme": "neon"}), encoding="utf-8")
        self.assertEqual(theme.load_theme_name(self.path), theme.DEFAULT_THEME)

    def test_save_then_load_roundtrip(self):
        theme.save_theme_name("light", self.path)
        self.assertEqual(theme.load_theme_name(self.path), "light")

    def test_save_creates_parent_dirs(self):
        nested = Path(self.tmp.name) / "a" / "b" / "settings.json"
        theme.save_theme_name("dark", nested)
        self.assertTrue(nested.exists())

    def test_save_unknown_name_raises(self):
        with self.assertRaises(ValueError):
            theme.save_theme_name("neon", self.path)


if __name__ == "__main__":
    unittest.main()
