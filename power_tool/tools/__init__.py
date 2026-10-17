from power_tool.tools import (console, disk_cleanup, installed_apps,
                              license_info, log_collector, network,
                              processes, restore_point, services, speedup,
                              system_info, usb_guard, users_groups)

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
        ("Console", console),
    ]),
    ("System", [
        ("Disk & Cleanup", disk_cleanup),
        ("Restore Point", restore_point),
        ("License Info", license_info),
    ]),
]
