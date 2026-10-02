import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tkinter as tk

from power_tool.core import theme
from power_tool.tools import installed_apps


class FakeKey:
    def __init__(self, children=(), values=None):
        self.children = list(children)
        self.values = values or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeWinreg:
    HKEY_LOCAL_MACHINE = "HKEY_LOCAL_MACHINE"
    HKEY_CURRENT_USER = "HKEY_CURRENT_USER"
    KEY_READ = 0x20019
    KEY_WOW64_64KEY = 0x100
    KEY_WOW64_32KEY = 0x200

    def __init__(self, root_keys):
        self.root_keys = root_keys

    def OpenKey(self, hive, path, reserved=0, access=0):
        if isinstance(hive, FakeKey):
            return hive.children[int(path)]
        view = access & (self.KEY_WOW64_64KEY | self.KEY_WOW64_32KEY)
        key = self.root_keys.get((hive, path, view))
        if key is None:
            raise FileNotFoundError(path)
        return key

    @staticmethod
    def EnumKey(key, index):
        return str(index)

    @staticmethod
    def QueryInfoKey(key):
        return (len(key.children), 0, 0)

    @staticmethod
    def QueryValueEx(key, name):
        if name not in key.values:
            raise OSError(name)
        value = key.values[name]
        return (value, 4 if isinstance(value, int) else 1)


def make_fake_reg():
    view64 = FakeKey(children=[
        FakeKey(values={
            "DisplayName": "Firefox",
            "DisplayVersion": "128.0",
            "Publisher": "Mozilla",
            "EstimatedSize": 70000,
            "InstallDate": "20260115",
            "UninstallString": '"C:\\Program Files\\Mozilla Firefox'
                               '\\uninstall.exe" /S',
        }),
        FakeKey(values={"DisplayName": "Hidden", "SystemComponent": 1}),
        FakeKey(values={"NoDisplayName": "x"}),
    ])
    view32 = FakeKey(children=[
        FakeKey(values={"DisplayName": "Firefox", "DisplayVersion": "128.0",
                        "Publisher": "Mozilla"}),
        FakeKey(values={"DisplayName": "32-bit Tool", "DisplayVersion": "1.0",
                        "Publisher": "Acme", "EstimatedSize": 512}),
    ])
    hkcu = FakeKey(children=[
        FakeKey(values={"DisplayName": "User App", "EstimatedSize": 500}),
    ])
    return FakeWinreg({
        (FakeWinreg.HKEY_LOCAL_MACHINE, installed_apps.UNINSTALL_PATH,
         0x100): view64,
        (FakeWinreg.HKEY_LOCAL_MACHINE, installed_apps.UNINSTALL_PATH,
         0x200): view32,
        (FakeWinreg.HKEY_CURRENT_USER, installed_apps.UNINSTALL_PATH,
         0x100): hkcu,
    })


FIXTURE = [
    {"name": "Firefox", "version": "128.0", "publisher": "Mozilla",
     "size_kb": 70000, "installed": "20260115",
     "uninstall": '"C:\\Program Files\\Mozilla Firefox\\uninstall.exe" /S'},
    {"name": "32-bit Tool", "version": "1.0", "publisher": "Acme",
     "size_kb": 512, "installed": "", "uninstall": "MsiExec.exe /X{ABC}"},
    {"name": "User App", "version": "", "publisher": "",
     "size_kb": 500, "installed": "", "uninstall": ""},
]


class GatherAppsTests(unittest.TestCase):
    def test_enumerates_three_hives_dedupes_and_sorts(self):
        fake = make_fake_reg()
        with patch.object(installed_apps, "winreg", fake):
            apps = installed_apps.gather_apps()
        names = [a["name"] for a in apps]
        self.assertEqual(names, ["32-bit Tool", "Firefox", "User App"])
        firefox = [a for a in apps if a["name"] == "Firefox"][0]
        self.assertEqual(firefox["version"], "128.0")
        self.assertEqual(firefox["size_kb"], 70000)
        self.assertEqual(firefox["installed"], "20260115")
        self.assertIn("uninstall.exe", firefox["uninstall"])

    def test_missing_hive_is_skipped_not_fatal(self):
        fake = FakeWinreg({})
        with patch.object(installed_apps, "winreg", fake):
            self.assertEqual(installed_apps.gather_apps(), [])


class FormatTests(unittest.TestCase):
    def test_format_size_empty_zero_negative(self):
        self.assertEqual(installed_apps.format_size(0), "")
        self.assertEqual(installed_apps.format_size(None), "")
        self.assertEqual(installed_apps.format_size(-5), "")

    def test_format_size_kb_and_mb(self):
        self.assertEqual(installed_apps.format_size(512), "512 KB")
        self.assertEqual(installed_apps.format_size(70000), "68.4 MB")

    def test_format_size_garbage(self):
        self.assertEqual(installed_apps.format_size("abc"), "")

    def test_format_date_yyyymmdd(self):
        self.assertEqual(installed_apps.format_date("20260115"), "2026-01-15")

    def test_format_date_passthrough(self):
        self.assertEqual(installed_apps.format_date(""), "")
        self.assertEqual(installed_apps.format_date("notadate"), "notadate")


class FilterAppsTests(unittest.TestCase):
    def test_empty_query_returns_all(self):
        self.assertEqual(installed_apps.filter_apps(FIXTURE, "  "),
                         FIXTURE)

    def test_case_insensitive_name_match(self):
        result = installed_apps.filter_apps(FIXTURE, "fire")
        self.assertEqual([a["name"] for a in result], ["Firefox"])

    def test_publisher_match(self):
        result = installed_apps.filter_apps(FIXTURE, "acme")
        self.assertEqual([a["name"] for a in result], ["32-bit Tool"])


class UninstallCommandTests(unittest.TestCase):
    def test_splits_quoted_path(self):
        cmd = installed_apps.uninstall_command(
            '"C:\\Program Files\\App\\unins.exe" /VERYSILENT')
        self.assertEqual(cmd,
                         ["C:\\Program Files\\App\\unins.exe", "/VERYSILENT"])

    def test_msiexec_command(self):
        self.assertEqual(
            installed_apps.uninstall_command("MsiExec.exe /X{GUID}"),
            ["MsiExec.exe", "/X{GUID}"])

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            installed_apps.uninstall_command("   ")


class WriteCsvTests(unittest.TestCase):
    def test_writes_header_and_rows(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "apps.csv"
        installed_apps.write_csv(str(path), FIXTURE)
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        self.assertEqual(lines[0],
                         ",".join(installed_apps.CSV_HEADER))
        self.assertEqual(len(lines), 4)
        self.assertIn("Firefox", lines[1])


class InstalledAppsFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()
        theme.apply_theme(cls.root, "dark")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        task = patch.object(installed_apps.tasks, "BackgroundTask")
        self.fake_task = task.start()
        self.addCleanup(task.stop)
        guard = patch.object(installed_apps.widgets, "guard_admin",
                             return_value=True)
        guard.start()
        self.addCleanup(guard.stop)
        self.frame = installed_apps.InstalledAppsFrame(self.root)

    def _load(self, apps=FIXTURE):
        kwargs = self.fake_task.call_args.kwargs
        kwargs["on_done"](list(apps))

    def test_initial_load_populates_tree(self):
        self._load()
        self.assertEqual(len(self.frame._tree.get_children()), 3)

    def test_search_filters_tree_live(self):
        self._load()
        self.frame._query.set("fire")
        children = self.frame._tree.get_children()
        self.assertEqual(len(children), 1)
        self.assertEqual(self.frame._visible[0]["name"], "Firefox")

    def test_uninstall_without_selection_warns(self):
        with patch.object(installed_apps.runner, "start_detached") as fake:
            self.frame._uninstall()
        fake.assert_not_called()
        self.assertIn("Select an app first", self.frame.status.text())

    def test_uninstall_cancelled_confirm_does_nothing(self):
        self._load()
        self.frame._tree.selection_set("1")
        with patch.object(installed_apps.widgets, "confirm",
                          return_value=False), \
             patch.object(installed_apps.runner, "start_detached") as fake:
            self.frame._uninstall()
        fake.assert_not_called()

    def test_uninstall_confirmed_starts_uninstaller(self):
        self._load()
        self.frame._tree.selection_set("1")
        with patch.object(installed_apps.widgets, "confirm",
                          return_value=True), \
             patch.object(installed_apps.runner, "start_detached") as fake:
            self.frame._uninstall()
        fake.assert_called_once_with(["MsiExec.exe", "/X{ABC}"])
        self.assertIn("Uninstaller started", self.frame.status.text())

    def test_uninstall_launch_failure_shown_as_status_error(self):
        self._load()
        self.frame._tree.selection_set("1")
        with patch.object(installed_apps.widgets, "confirm",
                          return_value=True), \
             patch.object(installed_apps.runner, "start_detached",
                          side_effect=FileNotFoundError("gone.exe")):
            self.frame._uninstall()
        self.assertIn("Could not start uninstaller",
                      self.frame.status.text())

    def test_export_writes_visible_rows(self):
        self._load()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = str(Path(tmp.name) / "out.csv")
        with patch.object(installed_apps.filedialog,
                          "asksaveasfilename", return_value=path):
            self.frame._export()
        content = Path(path).read_text(encoding="utf-8-sig")
        self.assertIn("Firefox", content)
        self.assertIn("MsiExec.exe /X{ABC}", content)
        self.assertIn("Exported 3 apps", self.frame.status.text())

    def test_export_with_no_match_warns(self):
        self._load()
        self.frame._query.set("zzzz")
        with patch.object(installed_apps.filedialog,
                          "asksaveasfilename") as fake:
            self.frame._export()
        fake.assert_not_called()
        self.assertIn("Nothing to export", self.frame.status.text())


if __name__ == "__main__":
    unittest.main()
