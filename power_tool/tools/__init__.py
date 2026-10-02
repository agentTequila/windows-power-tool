from power_tool.tools import log_collector, network, speedup, system_info, usb_guard

REGISTRY: list = [
    ("Core", [
        ("USB Guard", usb_guard),
        ("Windows Speedup", speedup),
        ("Log Collector", log_collector),
        ("System Info", system_info),
    ]),
    ("Admin", [
        ("Network", network),
    ]),
]
