import json
import unittest

from power_tool.tools import system_info

FIXTURE = {
    "hostname": "DESKTOP-TEST01",
    "generated": "2026-09-30 14:05:09",
    "os": {"caption": "Microsoft Windows 11 Pro", "version": "10.0.26100",
           "build": "26100", "arch": "64-bit"},
    "hardware": {"manufacturer": "Dell Inc.", "model": "Latitude 5440",
                 "totalRam": 17179869184},
    "cpu": [{"name": "Intel Core i7-1355U", "cores": 10, "logical": 12}],
    "ram": [{"slot": "DIMM A", "size": 8589934592, "speed": 3200,
             "maker": "Samsung"}],
    "network": [{"interface": "Ethernet", "mac": "AA:BB:CC:DD:EE:FF",
                 "ipv4": ["192.168.1.50"], "ipv6": ["fe80::1"]}],
    "disks": [{"device": "C:", "label": "Windows", "fs": "NTFS",
               "total": 512110190592, "free": 10737418240, "type": "Fixed"}],
    "users": [{"name": "admin", "full": "Local Admin", "enabled": True,
               "groups": ["Administrators"]},
              {"name": "guest1", "full": "", "enabled": False, "groups": ["Users"]}],
    "boot": "2026-09-30T08:00:00",
}


class ParseReportTests(unittest.TestCase):
    def test_parses_json(self):
        data = system_info.parse_report(json.dumps(FIXTURE))
        self.assertEqual(data["hostname"], "DESKTOP-TEST01")

    def test_rejects_garbage(self):
        with self.assertRaises(ValueError):
            system_info.parse_report("powershell noise not json")


class FormatReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = system_info.format_report(FIXTURE)

    def test_contains_hostname(self):
        self.assertIn("DESKTOP-TEST01", self.text)

    def test_contains_os_and_model(self):
        self.assertIn("Microsoft Windows 11 Pro", self.text)
        self.assertIn("Latitude 5440", self.text)

    def test_contains_cpu_and_ram(self):
        self.assertIn("Intel Core i7-1355U", self.text)
        self.assertIn("16.0 GB", self.text)

    def test_contains_ip_and_mac(self):
        self.assertIn("192.168.1.50", self.text)
        self.assertIn("AA:BB:CC:DD:EE:FF", self.text)

    def test_contains_users_with_groups(self):
        self.assertIn("admin", self.text)
        self.assertIn("Administrators", self.text)
        self.assertIn("guest1", self.text)
        self.assertIn("disabled", self.text.lower())

    def test_contains_disk_with_free_space(self):
        self.assertIn("C:", self.text)
        self.assertIn("NTFS", self.text)

    def test_size_formatting(self):
        self.assertIn("476.9 GB", self.text)      # total disk
        self.assertIn("10.0 GB", self.text)       # free
        self.assertIn("8.0 GB", self.text)        # dimm


class FormatUptimeTests(unittest.TestCase):
    def test_formats_uptime(self):
        text = system_info.format_uptime("2026-09-30T08:00:00",
                                         "2026-09-30T14:05:09")
        self.assertIn("6h", text)
        self.assertIn("5m", text)


if __name__ == "__main__":
    unittest.main()
