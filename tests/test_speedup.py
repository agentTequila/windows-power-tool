import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from power_tool.tools import speedup


class TempTargetTests(unittest.TestCase):
    def test_exactly_four_expected_targets(self):
        env = {
            "TEMP": r"C:\Users\me\AppData\Local\Temp",
            "WINDIR": r"C:\Windows",
            "APPDATA": r"C:\Users\me\AppData\Roaming",
        }
        targets = speedup.default_temp_targets(env)
        self.assertEqual(len(targets), 4)
        self.assertEqual(targets[0], Path(env["TEMP"]))
        self.assertEqual(targets[1], Path(r"C:\Windows\Temp"))
        self.assertEqual(targets[2],
                         Path(env["APPDATA"]) / "Microsoft" / "Windows" / "Recent")
        self.assertEqual(targets[3], Path(r"C:\Windows\Prefetch"))


class ClearDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)

    def test_missing_directory_returns_zeros(self):
        self.assertEqual(speedup.clear_directory(self.path / "nope"), (0, 0, 0))

    def test_removes_files_and_counts_bytes(self):
        (self.path / "a.txt").write_text("x" * 100, encoding="utf-8")
        removed, freed, skipped = speedup.clear_directory(self.path)
        self.assertEqual((removed, freed, skipped), (1, 100, 0))
        self.assertFalse((self.path / "a.txt").exists())

    def test_removes_subdirectories(self):
        sub = self.path / "sub"
        sub.mkdir()
        (sub / "b.txt").write_text("y" * 50, encoding="utf-8")
        removed, freed, skipped = speedup.clear_directory(self.path)
        self.assertEqual((removed, freed, skipped), (1, 50, 0))

    def test_locked_file_is_skipped_not_raised(self):
        (self.path / "locked.txt").write_text("z" * 10, encoding="utf-8")
        with patch.object(Path, "unlink",
                          side_effect=PermissionError("in use")):
            removed, freed, skipped = speedup.clear_directory(self.path)
        self.assertEqual((removed, freed), (0, 0))
        self.assertEqual(skipped, 1)
        self.assertTrue((self.path / "locked.txt").exists())


class ChromiumProfilesTests(unittest.TestCase):
    def test_only_dirs_with_preferences_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            user_data = Path(tmp)
            (user_data / "Default").mkdir()
            (user_data / "Default" / "Preferences").write_text("{}", encoding="utf-8")
            (user_data / "Profile 1").mkdir()
            (user_data / "Profile 1" / "Preferences").write_text("{}", encoding="utf-8")
            (user_data / "System Profile").mkdir()
            profiles = speedup.chromium_profiles(user_data)
            names = sorted(p.name for p in profiles)
            self.assertEqual(names, ["Default", "Profile 1"])

    def test_missing_user_data_returns_empty(self):
        self.assertEqual(
            speedup.chromium_profiles(Path(r"C:\no\such\dir\here")), [])


class BrowserTargetTests(unittest.TestCase):
    def test_chrome_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            user_data = Path(tmp) / "Google" / "Chrome" / "User Data"
            default = user_data / "Default"
            default.mkdir(parents=True)
            (default / "Preferences").write_text("{}", encoding="utf-8")
            targets = speedup.browser_cleanup_targets(
                "Chrome", {"LOCALAPPDATA": tmp})
            names = {p.name for p in targets}
            self.assertIn("Cache", names)
            self.assertIn("Code Cache", names)
            self.assertIn("Service Worker", names)
            self.assertIn("Local Storage", names)
            self.assertIn("Cookies", names)
            for target in targets:
                self.assertIn("Default", str(target))
            self.assertNotIn("History", names)
            self.assertNotIn("Login Data", names)

    def test_firefox_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "Mozilla" / "Firefox" / "Profiles" / "abc.default"
            profile.mkdir(parents=True)
            targets = speedup.browser_cleanup_targets("Firefox", {"APPDATA": tmp})
            names = {p.name for p in targets}
            self.assertIn("cache2", names)
            self.assertIn("storage", names)
            self.assertIn("cookies.sqlite", names)
            self.assertNotIn("places.sqlite", names)

    def test_missing_browser_dirs_return_empty(self):
        targets = speedup.browser_cleanup_targets(
            "Edge", {"LOCALAPPDATA": r"C:\no\such\dir"})
        self.assertEqual(targets, [])


class RemoveTargetTests(unittest.TestCase):
    def test_removes_file_with_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "Cookies"
            f.write_text("data", encoding="utf-8")
            removed, freed = speedup.remove_target(f)
            self.assertTrue(removed)
            self.assertEqual(freed, 4)

    def test_removes_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "Cache"
            d.mkdir()
            (d / "f").write_text("abc", encoding="utf-8")
            removed, freed = speedup.remove_target(d)
            self.assertTrue(removed)
            self.assertEqual(freed, 3)
            self.assertFalse(d.exists())

    def test_missing_path_returns_false_zero(self):
        self.assertEqual(speedup.remove_target(Path(r"C:\no\such\file")), (False, 0))


class SummaryTests(unittest.TestCase):
    def test_format_summary(self):
        text = speedup.format_summary(12, 5 * 1024 * 1024, 3)
        self.assertIn("12", text)
        self.assertIn("5.0 MB", text)
        self.assertIn("3", text)

    def test_format_summary_zero(self):
        text = speedup.format_summary(0, 0, 0)
        self.assertIn("0", text)


class LaunchCommandTests(unittest.TestCase):
    def test_chrome_finds_installed_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "Google" / "Chrome" / "Application" / "chrome.exe"
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"MZ")
            env = {"PROGRAMFILES": tmp, "PROGRAMFILES(X86)": r"C:\none",
                   "LOCALAPPDATA": r"C:\none"}
            cmd = speedup.browser_launch_command("Chrome", env)
            self.assertIsNotNone(cmd)
            self.assertEqual(cmd[0], str(exe))

    def test_returns_none_when_not_installed(self):
        env = {"PROGRAMFILES": r"C:\no\such", "PROGRAMFILES(X86)": r"C:\no\such2",
               "LOCALAPPDATA": r"C:\no\such3"}
        self.assertIsNone(speedup.browser_launch_command("Firefox", env))


class ProcessHelperTests(unittest.TestCase):
    @patch.object(speedup, "runner")
    def test_is_process_running_true(self, fake_runner):
        from power_tool.core.runner import Result
        fake_runner.run.return_value = Result(0, "chrome.exe", "")
        self.assertTrue(speedup.is_process_running("chrome.exe"))

    @patch.object(speedup, "runner")
    def test_is_process_running_false_when_no_tasks(self, fake_runner):
        from power_tool.core.runner import Result
        fake_runner.run.return_value = Result(0, "INFO: No tasks are running.", "")
        self.assertFalse(speedup.is_process_running("chrome.exe"))


if __name__ == "__main__":
    unittest.main()
