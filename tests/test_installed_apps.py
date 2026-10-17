import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tkinter as tk

from power_tool.core import theme, widgets
from power_tool.tools import installed_apps

REAL_GUARD_ADMIN = widgets.guard_admin


class FakeKey:
    def __init__(self, children=(), values=None, open_error=False):
        self.children = list(children)
        self.values = values or {}
        self.open_error = open_error

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
            child = hive.children[int(path)]
            if child.open_error:
                raise OSError(f"cannot open {path}")
            return child
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

    def test_one_broken_subkey_skips_row_not_whole_listing(self):
        fake = make_fake_reg()
        hkcu = fake.root_keys[(FakeWinreg.HKEY_CURRENT_USER,
                               installed_apps.UNINSTALL_PATH, 0x100)]
        hkcu.children.append(FakeKey(values={"DisplayName": "Racy App"},
                                     open_error=True))
        with patch.object(installed_apps, "winreg", fake):
            apps = installed_apps.gather_apps()
        names = [a["name"] for a in apps]
        self.assertEqual(names, ["32-bit Tool", "Firefox", "User App"])


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


class ScannerTests(unittest.TestCase):
    def _tmp_root(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def test_exact_display_name_folder_is_high_confidence(self):
        root = self._tmp_root()
        (root / "Firefox").mkdir()
        (root / "Waterfox").mkdir()
        found = installed_apps.scan_leftover_folders("Firefox", "Mozilla",
                                                     [root])
        self.assertEqual(len(found), 1)
        item = found[0]
        self.assertEqual(item["kind"], "folder")
        self.assertEqual(item["confidence"], "high")
        self.assertEqual(item["path"], root / "Firefox")
        self.assertEqual(item["label"], str(root / "Firefox"))

    def test_publisher_only_match_is_low_confidence(self):
        root = self._tmp_root()
        (root / "Acme Corp").mkdir()
        found = installed_apps.scan_leftover_folders("Something Else",
                                                     "Acme Corp", [root])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["confidence"], "low")

    def test_publisher_below_four_chars_never_matches(self):
        root = self._tmp_root()
        (root / "AB").mkdir()
        found = installed_apps.scan_leftover_folders("No Match", "AB", [root])
        self.assertEqual(found, [])

    def test_short_display_name_never_matches(self):
        root = self._tmp_root()
        (root / "Git").mkdir()
        found = installed_apps.scan_leftover_folders("Git", "Git SCM", [root])
        self.assertEqual(found, [])

    def test_short_display_name_with_spaces_never_matches(self):
        root = self._tmp_root()
        (root / "Git").mkdir()
        found = installed_apps.scan_leftover_folders(" Git ", "Git SCM", [root])
        self.assertEqual(found, [])

    def test_no_match_returns_empty(self):
        root = self._tmp_root()
        (root / "Firefox").mkdir()
        found = installed_apps.scan_leftover_folders("Chrome", "Google LLC",
                                                     [root])
        self.assertEqual(found, [])

    def test_case_insensitive_folder_match(self):
        root = self._tmp_root()
        (root / "FIREFOX").mkdir()
        found = installed_apps.scan_leftover_folders("firefox", "Mozilla",
                                                     [root])
        self.assertEqual([item["path"] for item in found],
                         [root / "FIREFOX"])

    def test_registry_scan_matches_exact_display_name_only(self):
        view64 = FakeKey(children=[
            FakeKey(values={"DisplayName": "Firefox", "DisplayVersion": "128.0"}),
            FakeKey(values={"DisplayName": "Firefox ESR"}),
            FakeKey(values={"DisplayName": "firefox"}),
            FakeKey(values={"NoDisplayName": "x"}),
        ])
        fake = FakeWinreg({
            (FakeWinreg.HKEY_LOCAL_MACHINE, installed_apps.UNINSTALL_PATH,
             0x100): view64,
        })
        with patch.object(installed_apps, "winreg", fake):
            result = installed_apps.scan_leftover_registry("Firefox")
        expected = [
            installed_apps.UNINSTALL_PATH + "\\0",
            installed_apps.UNINSTALL_PATH + "\\2",
        ]
        self.assertEqual(result, expected)

    def test_registry_scan_skips_missing_hive(self):
        fake = FakeWinreg({})
        with patch.object(installed_apps, "winreg", fake):
            self.assertEqual(installed_apps.scan_leftover_registry("Firefox"),
                             [])

    def test_remove_path_deletes_dir_and_counts_bytes(self):
        root = self._tmp_root()
        target = root / "leftover"
        target.mkdir()
        (target / "one.bin").write_bytes(b"x" * 1000)
        (target / "two.bin").write_bytes(b"y" * 2000)
        ok, size = installed_apps.remove_path(target)
        self.assertTrue(ok)
        self.assertEqual(size, 3000)
        self.assertFalse(target.exists())

    def test_remove_path_unlinks_file(self):
        root = self._tmp_root()
        target = root / "leftover.bin"
        target.write_bytes(b"z" * 256)
        ok, size = installed_apps.remove_path(target)
        self.assertTrue(ok)
        self.assertEqual(size, 256)
        self.assertFalse(target.exists())

    def test_remove_path_missing_returns_false_zero(self):
        root = self._tmp_root()
        self.assertEqual(installed_apps.remove_path(root / "gone"),
                         (False, 0))

    def test_remove_path_locked_returns_false(self):
        root = self._tmp_root()
        target = root / "locked"
        target.mkdir()
        with patch.object(installed_apps.shutil, "rmtree",
                          side_effect=OSError("busy")):
            ok, size = installed_apps.remove_path(target)
        self.assertFalse(ok)
        self.assertEqual(size, 0)
        self.assertTrue(target.exists())

    def test_dialog_defaults_high_ticked_low_unticked(self):
        findings = [
            {"kind": "folder", "confidence": "high"},
            {"kind": "folder", "confidence": "low"},
            {"kind": "registry", "confidence": "high"},
            {"kind": "folder", "confidence": "low"},
        ]
        self.assertEqual(
            installed_apps.default_checked(findings), [True, False, True,
                                                       False])


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
        self.fake_task.reset_mock()
        # Second confirm is the post-uninstall leftover prompt; declining it
        # must not start a scan task.
        with patch.object(installed_apps.widgets, "confirm",
                          side_effect=[True, False]), \
             patch.object(installed_apps.runner, "start_detached") as fake:
            self.frame._uninstall()
        fake.assert_called_once_with(["MsiExec.exe", "/X{ABC}"])
        self.assertIn("Uninstaller started", self.frame.status.text())
        self.fake_task.assert_not_called()

    def test_uninstall_prompts_leftover_scan_after_success(self):
        self._load()
        self.frame._tree.selection_set("1")
        self.fake_task.reset_mock()
        with patch.object(installed_apps.widgets, "confirm",
                          side_effect=[True, True]), \
             patch.object(installed_apps.runner, "start_detached") as fake:
            self.frame._uninstall()
        fake.assert_called_once_with(["MsiExec.exe", "/X{ABC}"])
        self.assertTrue(self.fake_task.called)
        self.assertTrue(self.fake_task.return_value.start.called)
        self.assertIn("Scanning for leftovers", self.frame.status.text())

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

    def test_clearing_search_restores_total_count_status(self):
        self._load()
        self.frame._query.set("fire")
        self.assertEqual(self.frame.status.text(), "1 of 3 apps match")
        self.frame._query.set("")
        self.assertEqual(self.frame.status.text(), "3 apps found.")

    def test_refresh_disables_buttons_and_error_reenables(self):
        self.frame._refresh()
        for button in (self.frame._refresh_button,
                       self.frame._export_button,
                       self.frame._uninstall_button,
                       self.frame._scan_button):
            self.assertEqual(str(button.cget("state")), "disabled")
        kwargs = self.fake_task.call_args.kwargs
        kwargs["on_error"](RuntimeError("boom"))
        for button in (self.frame._refresh_button,
                       self.frame._export_button,
                       self.frame._uninstall_button,
                       self.frame._scan_button):
            self.assertEqual(str(button.cget("state")), "normal")
        self.assertIn("boom", self.frame.status.text())
        self.assertEqual(str(self.frame.status._label.cget("style")),
                         "Error.TLabel")

    def test_action_guarded_requires_admin(self):
        self._load()
        self.frame._tree.selection_set("0")
        self.fake_task.reset_mock()
        with patch.object(installed_apps.widgets, "guard_admin",
                          REAL_GUARD_ADMIN), \
             patch("power_tool.core.admin.is_admin", return_value=False), \
             patch.object(installed_apps.widgets, "confirm",
                          return_value=True), \
             patch.object(installed_apps.runner,
                          "start_detached") as fake_start:
            self.frame._uninstall()
        self.fake_task.assert_not_called()
        fake_start.assert_not_called()
        self.assertIn("Run as administrator required",
                      self.frame.status.text())

    def test_scan_leftovers_requires_selection_warns(self):
        self.fake_task.reset_mock()
        self.frame._scan_leftovers()
        self.fake_task.assert_not_called()
        self.assertIn("Select an app first", self.frame.status.text())

    def test_scan_leftovers_is_unguarded(self):
        # Scanning is a read: it starts even as non-admin and never calls
        # guard_admin.
        self._load()
        self.frame._tree.selection_set("0")
        self.fake_task.reset_mock()
        guard_calls = []

        def spy(status):
            guard_calls.append(status)
            return REAL_GUARD_ADMIN(status)

        with patch.object(installed_apps.widgets, "guard_admin", spy), \
             patch("power_tool.core.admin.is_admin", return_value=False):
            self.frame._scan_leftovers()
        self.assertEqual(guard_calls, [])
        self.assertTrue(self.fake_task.called)
        self.assertTrue(self.fake_task.return_value.start.called)
        self.assertIn("Scanning for leftovers", self.frame.status.text())

    def test_remove_leftovers_guarded_then_confirmed_before_deletion(self):
        self._load()
        self.frame._tree.selection_set("0")
        app = self.frame._visible[0]
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder_path = Path(tmp.name) / "Firefox"
        folder_path.mkdir()
        registry_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Firefox"
        findings = [
            {"kind": "folder", "path": folder_path,
             "label": str(folder_path), "confidence": "high"},
            {"kind": "registry", "path": registry_path, "label": registry_path,
             "hive": "HKEY_LOCAL_MACHINE", "confidence": "high"},
        ]

        captured = {}

        def fake_dialog(parent, findings_arg, on_remove):
            captured["on_remove"] = on_remove

        with patch.object(installed_apps, "LeftoverDialog",
                          side_effect=fake_dialog), \
             patch.object(installed_apps, "remove_path") as fake_remove, \
             patch.object(installed_apps.widgets, "confirm") as fake_confirm, \
             patch.object(installed_apps.widgets, "guard_admin",
                          REAL_GUARD_ADMIN), \
             patch("power_tool.core.admin.is_admin", return_value=False), \
             patch.object(installed_apps, "winreg") as fake_winreg:
            fake_remove.return_value = (True, 1234)

            # Phase 1: real guard, not admin -> nothing is touched.
            self.frame._on_scan_done(findings, app)
            on_remove = captured["on_remove"]
            on_remove(list(findings))
            fake_confirm.assert_not_called()
            fake_remove.assert_not_called()
            self.assertIn("administrator required",
                          self.frame.status.text())

            # Phase 2: admin, but confirmation declined -> no deletion.
            fake_confirm.return_value = False
            with patch("power_tool.core.admin.is_admin", return_value=True):
                on_remove(list(findings))
            fake_confirm.assert_called()
            fake_remove.assert_not_called()

            # Phase 3: admin + confirmation -> task starts; deletion deferred.
            self.fake_task.reset_mock()
            fake_confirm.return_value = True
            with patch("power_tool.core.admin.is_admin", return_value=True):
                on_remove(list(findings))
            self.assertTrue(self.fake_task.called)
            self.assertTrue(self.fake_task.return_value.start.called)
            fake_remove.assert_not_called()
            fake_winreg.DeleteKey.assert_not_called()

            # Running the worker performs each deletion exactly once.
            kwargs = self.fake_task.call_args.kwargs
            kwargs["on_done"](kwargs["work"]())
            fake_remove.assert_called_once_with(folder_path)
            fake_winreg.DeleteKey.assert_called_once_with(
                "HKEY_LOCAL_MACHINE", registry_path)
            self.assertIn("Removed 2 items", self.frame.status.text())
            self.assertIn("MB freed", self.frame.status.text())
            self.assertIn("skipped", self.frame.status.text())


if __name__ == "__main__":
    unittest.main()
