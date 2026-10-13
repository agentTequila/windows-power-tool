# Windows Power Tool

[![License: PolyForm Noncommercial](https://img.shields.io/badge/license-PolyForm%20Noncommercial-blue)](LICENSE)

A portable Windows admin toolbox that always runs elevated. Python and tkinter, one exe, twelve tools, no runtime dependencies.

## Download

Get **WindowsPowerTool.exe** from the [latest release](https://github.com/agentTequila/windows-power-tool/releases/latest) and run it. Windows asks for Administrator rights through UAC, which is expected: the tool needs them.

> **SmartScreen:** the exe is unsigned, so Windows may show "Windows protected your PC". Click **More info → Run anyway**.

## Tools

### Core

| Tool | What it does |
|---|---|
| **USB Guard** | Turns USB storage on or off per device class through the USBSTOR registry. A disabled drive still shows up in This PC, but opening it gives Access Denied. Keyboards and mice are never touched. |
| **Windows Speedup** | Clears `%TEMP%`, `Windows\Temp`, Recent and Prefetch. Optionally wipes browser cache and cookies (Chrome, Edge, Firefox) and opens the browser again after. Pick clean-only or clean-and-reboot, the reboot coming with a 10-second countdown you can cancel. |
| **Log Collector** | Grabs Application/System/Security/Setup event logs from the last N minutes, filtered by level. Saves as `.txt`, `.csv`, or native `.evtx`. |
| **System Info** | Hostname, OS, IPs and MAC addresses, local users and groups, hardware, storage (removable included), uptime. Copy it or save to a text file. |

### Admin

| Tool | What it does |
|---|---|
| **Network** | Flush the DNS cache, release or renew the IP, ping a host. Output shows up underneath after each run. |
| **Installed Apps** | Everything sitting in the Windows uninstall hives, with search as you type. Export to CSV, or hit Uninstall, which runs the program's own uninstaller after asking you first. |
| **Users & Groups** | Local accounts: group membership, password reset, enable, disable, delete. Anything destructive asks first. |
| **Processes** | Live table of running processes with search. Ending a task always confirms. |
| **Services** | The same treatment for services: search, start, stop, restart and change startup type, every one of them confirmed before it runs. |

### System

| Tool | What it does |
|---|---|
| **Disk & Cleanup** | Fixed and removable drives with size, free space and file system. A button opens Windows' own Disk Cleanup, so you choose what gets deleted. |
| **Restore Point** | Shows the existing restore points and lets you create a new one, with confirmation. |
| **License Info** | Windows edition, product key (from the registry, or the OEM source when that's what's available) and activation status. Any of it copies to the clipboard. |

## Requirements

- Windows 10 or 11
- Python 3.13+, only if you run from source (the exe needs nothing)
- Administrator rights (the exe asks through UAC on launch)

## Run from source

```powershell
python run.py
```

## Tests

```powershell
python -m unittest
```

## Build the portable exe

```powershell
pip install -r requirements.txt
pyinstaller --noconfirm build.spec
```

Output lands in `dist\WindowsPowerTool.exe` (onefile, no console, asks for admin on launch). To regenerate the app icon, run `python assets/generate_icon.py`, which needs Pillow.

## Notes

- Nothing gets written next to the exe. Your theme choice lives in `%LOCALAPPDATA%\WindowsPowerTool\settings.json`.
- Locked or in-use files are always skipped. Nothing is ever force-deleted.
- Service control, account changes, uninstall, restore points: all confirm first. Reads and refreshes never prompt.

## License

PolyForm Noncommercial 1.0.0: free to use, modify and share for noncommercial purposes, but selling the software or derived versions isn't permitted. Full text in [LICENSE](LICENSE).
