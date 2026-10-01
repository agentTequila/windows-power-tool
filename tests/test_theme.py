import json
import tempfile
import unittest
from pathlib import Path

import tkinter as tk
from tkinter import ttk

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


class StyleAppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def test_dark_hover_background_dark_with_light_text(self):
        theme.apply_theme(self.root, "dark")
        style = ttk.Style(self.root)
        names = ("TCheckbutton", "TRadiobutton", "TButton",
                 "Accent.TButton", "Danger.TButton")
        for name in names:
            with self.subTest(name):
                bg = style.lookup(name, "background", ["active"])
                fg = style.lookup(name, "foreground", ["active"])
                self.assertNotEqual(bg, "#eeebe7")
                self.assertNotEqual(bg, fg)

    def test_checkbutton_hover_uses_panel2(self):
        theme.apply_theme(self.root, "dark")
        style = ttk.Style(self.root)
        self.assertEqual(
            style.lookup("TCheckbutton", "background", ["active"]),
            theme.PALETTES["dark"]["panel2"])

    def test_light_hover_background_light_with_dark_text(self):
        theme.apply_theme(self.root, "light")
        style = ttk.Style(self.root)
        self.assertEqual(
            style.lookup("TCheckbutton", "background", ["active"]),
            theme.PALETTES["light"]["panel2"])
        self.assertEqual(
            style.lookup("TCheckbutton", "foreground", ["active"]),
            theme.PALETTES["light"]["fg"])

    def test_selected_sidebar_hover_stays_visible(self):
        theme.apply_theme(self.root, "dark")
        style = ttk.Style(self.root)
        bg = style.lookup("Active.Sidebar.TButton", "background", ["active"])
        fg = style.lookup("Active.Sidebar.TButton", "foreground", ["active"])
        self.assertNotEqual(bg, "#eeebe7")
        self.assertEqual(fg, theme.PALETTES["dark"]["accent_fg"])

    def test_checkbutton_uses_tick_indicator_images(self):
        theme.apply_theme(self.root, "dark")
        style = ttk.Style(self.root)
        mapped = dict(style.map("TCheckbutton").get("indicatorimage", []))
        self.assertIn("selected", mapped)
        self.assertIn("!selected", mapped)
        images = getattr(self.root, "_wpt_check_images", None)
        self.assertIsNotNone(images)
        self.assertEqual(images["on"].width(), 13)

        def pixel(img, x, y):
            value = img.get(x, y)
            if isinstance(value, tuple):
                return tuple(int(c) for c in value)
            return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))

        def rgb(hex_color):
            return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))

        self.assertEqual(pixel(images["on"], 4, 8),
                         rgb(theme.PALETTES["dark"]["accent"]))
        self.assertEqual(pixel(images["off"], 4, 8),
                         rgb(theme.PALETTES["dark"]["entry_bg"]))


if __name__ == "__main__":
    unittest.main()
