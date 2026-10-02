from power_tool.tools import (installed_apps, log_collector, network,
                              speedup, system_info, usb_guard)

REGISTRY: list = [
    ("Core", [
        ("USB Guard", usb_guard),
        ("Windows Speedup", speedup),
        ("Log Collector", log_collector),
        ("System Info", system_info),
    ]),
    ("Admin", [
        ("Network", network),
        ("Installed Apps", installed_apps),
    ]),
]
