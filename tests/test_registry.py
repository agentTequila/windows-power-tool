import unittest

from power_tool.tools import REGISTRY

EXPECTED_KEYS = [
    "power_tool.tools.usb_guard",
    "power_tool.tools.speedup",
    "power_tool.tools.log_collector",
    "power_tool.tools.system_info",
]

EXPECTED_ADMIN = [
    "power_tool.tools.network",
    "power_tool.tools.installed_apps",
    "power_tool.tools.users_groups",
    "power_tool.tools.processes",
    "power_tool.tools.services",
]

EXPECTED_SYSTEM = [
    "power_tool.tools.disk_cleanup",
    "power_tool.tools.restore_point",
    "power_tool.tools.license_info",
]


class RegistryTests(unittest.TestCase):
    def test_core_group_lists_four_tools_in_order(self):
        self.assertEqual(REGISTRY[0][0], "Core")
        keys = [module.__name__ for _, module in REGISTRY[0][1]]
        self.assertEqual(keys, EXPECTED_KEYS)

    def test_admin_group_lists_tools_in_order(self):
        self.assertEqual(REGISTRY[1][0], "Admin")
        keys = [module.__name__ for _, module in REGISTRY[1][1]]
        self.assertEqual(keys, EXPECTED_ADMIN)

    def test_every_tool_exposes_create(self):
        for _, modules in REGISTRY:
            for label, module in modules:
                self.assertTrue(callable(getattr(module, "create", None)),
                                f"{label} missing create()")

    def test_tool_labels_are_human_readable(self):
        labels = [label for _, modules in REGISTRY for label, _ in modules]
        self.assertIn("USB Guard", labels)
        self.assertIn("Log Collector", labels)

    def test_admin_labels_are_human_readable(self):
        labels = [label for label, _ in REGISTRY[1][1]]
        self.assertEqual(labels, ["Network", "Installed Apps",
                                  "Users & Groups", "Processes",
                                  "Services"])

    def test_system_group_lists_tools_in_order(self):
        self.assertEqual(REGISTRY[2][0], "System")
        keys = [module.__name__ for _, module in REGISTRY[2][1]]
        self.assertEqual(keys, EXPECTED_SYSTEM)

    def test_system_labels_are_human_readable(self):
        labels = [label for label, _ in REGISTRY[2][1]]
        self.assertEqual(labels, ["Disk & Cleanup", "Restore Point",
                                  "License Info"])


if __name__ == "__main__":
    unittest.main()
