import base64
import json
import unittest
from unittest.mock import patch

import tkinter as tk

from power_tool.core import theme
from power_tool.tools import license_info

FIXTURE = {
    "caption": "Microsoft Windows 11 Pro",
    "edition": "Professional",
    "build": "26100.1742",
    "product_name": "Windows(R), Professional edition",
    "partial_key": "3V66T",
    "oem_key": "VK7JG-NPHTM-C97JM-9MPGT-3V66T",
    "status_code": 1,
    "digital_b64": None,
}


class ParseLicenseTests(unittest.TestCase):
    def test_parses_object(self):
        data = license_info.parse_license(json.dumps(FIXTURE))
        self.assertEqual(data["caption"], "Microsoft Windows 11 Pro")

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            license_info.parse_license("not json")

    def test_list_raises(self):
        with self.assertRaises(ValueError):
            license_info.parse_license("[1, 2]")


class DecodeProductKeyTests(unittest.TestCase):
    def test_all_zero_bytes_yield_b_key(self):
        self.assertEqual(license_info.decode_product_key(bytes(166)),
                         "BBBBB-BBBBB-BBBBB-BBBBB-BBBBB")

    def test_patterned_bytes_regression_vector(self):
        self.assertEqual(license_info.decode_product_key(bytes(range(166))),
                         "8PXYX-G432F-RQF44-PHNXP-QP69T")

    def test_empty_returns_none(self):
        self.assertIsNone(license_info.decode_product_key(b""))

    def test_short_returns_none(self):
        self.assertIsNone(license_info.decode_product_key(bytes(66)))


class StatusNameTests(unittest.TestCase):
    def test_known_codes(self):
        self.assertEqual(license_info.status_name(1), "Licensed")
        self.assertEqual(license_info.status_name(0), "Unlicensed")
        self.assertEqual(license_info.status_name(5), "Notification")

    def test_unknown_numeric_code(self):
        self.assertEqual(license_info.status_name(99), "Unknown (99)")

    def test_none_and_garbage(self):
        self.assertEqual(license_info.status_name(None), "Unknown")
        self.assertEqual(license_info.status_name("abc"), "Unknown")


class FormatLicenseBlockTests(unittest.TestCase):
    def test_oem_key_block(self):
        block = license_info.format_license_block(dict(FIXTURE))
        self.assertIn("WINDOWS LICENSE INFORMATION", block)
        self.assertIn("Microsoft Windows 11 Pro", block)
        self.assertIn("Professional", block)
        self.assertIn("26100.1742", block)
        self.assertIn("Licensed", block)
        self.assertIn("VK7JG-NPHTM-C97JM-9MPGT-3V66T", block)
        self.assertIn("OEM firmware (OA3x)", block)
        self.assertIn("3V66T", block)

    def test_registry_key_preferred_when_decodable(self):
        data = dict(FIXTURE)
        data["digital_b64"] = base64.b64encode(bytes(166)).decode("ascii")
        block = license_info.format_license_block(data)
        self.assertIn("BBBBB-BBBBB-BBBBB-BBBBB-BBBBB", block)
        self.assertIn("Registry (DigitalProductId)", block)
        self.assertNotIn("VK7JG-NPHTM-C97JM-9MPGT-3V66T", block)

    def test_no_keys_available(self):
        data = {"caption": "Microsoft Windows 11 Home", "status_code": 5,
                "partial_key": "", "oem_key": "", "digital_b64": None}
        block = license_info.format_license_block(data)
        self.assertIn("Product key   : Not available", block)
        self.assertIn("Notification", block)

    def test_missing_caption_and_status(self):
        block = license_info.format_license_block({})
        self.assertIn("Not available", block)
        self.assertIn("Unknown", block)


class GatherTests(unittest.TestCase):
    @patch.object(license_info.runner, "run_powershell_checked")
    def test_uses_checked_runner(self, fake_checked):
        fake_checked.return_value = json.dumps(FIXTURE)
        data = license_info.gather()
        self.assertEqual(data["partial_key"], "3V66T")
        fake_checked.assert_called_once_with(
            license_info.LICENSE_SCRIPT, timeout=120)


class LicenseInfoFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()
        theme.apply_theme(cls.root, "dark")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        task = patch.object(license_info.tasks, "BackgroundTask")
        self.fake_task = task.start()
        self.addCleanup(task.stop)
        self.frame = license_info.LicenseInfoFrame(self.root)
        self.fake_task.reset_mock()

    def _load(self, data=FIXTURE):
        self.frame._load_done(dict(data))

    def _pane_text(self) -> str:
        return self.frame._output.get("1.0", "end")

    def test_load_done_fills_pane_and_enables_copy(self):
        self._load()
        self.assertIn("WINDOWS LICENSE INFORMATION", self._pane_text())
        self.assertEqual(
            str(self.frame._copy_button.cget("state")), "normal")
        self.assertIn("License information loaded",
                      self.frame.status.text())

    def test_refresh_button_starts_task(self):
        self._load()
        self.frame._refresh_button.invoke()
        kwargs = self.fake_task.call_args.kwargs
        self.assertIs(kwargs["work"], license_info.gather)

    def test_refresh_disables_buttons_and_error_reenables(self):
        self.frame._refresh()
        self.assertEqual(
            str(self.frame._refresh_button.cget("state")), "disabled")
        kwargs = self.fake_task.call_args.kwargs
        kwargs["on_error"](RuntimeError("license query failed"))
        self.assertEqual(
            str(self.frame._refresh_button.cget("state")), "normal")
        self.assertIn("license query failed", self.frame.status.text())
        self.assertEqual(str(self.frame.status._label.cget("style")),
                         "Error.TLabel")

    def test_format_failure_reports_error_without_copy(self):
        with patch.object(license_info, "format_license_block",
                          side_effect=ValueError("bad data")):
            self.frame._load_done(dict(FIXTURE))
        self.assertIn("Formatting failed: bad data",
                      self.frame.status.text())
        self.assertEqual(
            str(self.frame._copy_button.cget("state")), "disabled")

    def test_copy_without_data_warns(self):
        self.frame._copy()
        self.assertIn("Nothing to copy", self.frame.status.text())

    def test_copy_puts_block_on_clipboard(self):
        self._load()
        self.frame._copy()
        self.assertEqual(self.root.clipboard_get(), self.frame._block)
        self.assertIn("Copied to clipboard", self.frame.status.text())


if __name__ == "__main__":
    unittest.main()
