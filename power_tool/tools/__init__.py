from power_tool.tools import (installed_apps, log_collector, network,
                              processes, services, speedup, system_info,
                              usb_guard, users_groups)

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
        ("Users & Groups", users_groups),
        ("Processes", processes),
        ("Services", services),
    ]),
]
