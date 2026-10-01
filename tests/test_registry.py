import unittest

from power_tool.tools import REGISTRY

EXPECTED_KEYS = [
    "power_tool.tools.usb_guard",
    "power_tool.tools.speedup",
    "power_tool.tools.log_collector",
    "power_tool.tools.system_info",
]


class RegistryTests(unittest.TestCase):
    def test_core_group_lists_four_tools_in_order(self):
        self.assertEqual(REGISTRY[0][0], "Core")
        keys = [module.__name__ for _, module in REGISTRY[0][1]]
        self.assertEqual(keys, EXPECTED_KEYS)

    def test_every_tool_exposes_create(self):
        for _, modules in REGISTRY:
            for label, module in modules:
                self.assertTrue(callable(getattr(module, "create", None)),
                                f"{label} missing create()")

    def test_tool_labels_are_human_readable(self):
        labels = [label for _, modules in REGISTRY for label, _ in modules]
        self.assertIn("USB Guard", labels)
        self.assertIn("Log Collector", labels)


if __name__ == "__main__":
    unittest.main()
