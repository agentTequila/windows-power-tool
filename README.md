# Windows Power Tool

[![License: PolyForm Noncommercial](https://img.shields.io/badge/license-PolyForm%20Noncommercial-blue)](LICENSE)

A portable, always-elevated Windows admin toolbox built with Python and tkinter.
One exe, twelve tools, zero runtime dependencies.

## Download

Grab [`WindowsPowerTool.exe`](WindowsPowerTool.exe) from this repository and run it —
it requests Administrator rights via UAC on launch.

> **Windows SmartScreen:** the exe is unsigned, so SmartScreen may show
> "Windows protected your PC". Click **More info → Run anyway**.

## Tools

### Core

| Tool | What it does |
|---|---|
| **USB Guard** | Disable/enable USB storage per device class via the USBSTOR registry. Disabled drives still show in This PC but open Access Denied; keyboards and mice are unaffected. |
| **Windows Speedup** | Clears `%TEMP%`, `Windows\Temp`, Recent and Prefetch; optionally clears browser cache/cookies (Chrome, Edge, Firefox) and reopens the browser. Clean-only or clean-and-reboot with a cancelable 10s countdown. |
| **Log Collector** | Collects Application/System/Security/Setup event logs for the last N minutes, filtered by level, to `.txt`, `.csv` or native `.evtx`. |
| **System Info** | Hostname, OS, IPs/MAC, local users and groups, hardware, storage (incl. removable) and uptime. Copy or save to text. |

### Admin

| Tool | What it does |
|---|---|
| **Network** | Flush the DNS cache, release/renew the IP address, and ping a host — output shown below each run. |
| **Installed Apps** | Every program in the Windows uninstall hives. Live search, Export CSV, and Uninstall which starts the program's own uninstaller after confirmation. |
| **Users & Groups** | Manage local accounts: group membership, password reset, enable, disable and delete. Destructive actions ask for confirmation first. |
| **Processes** | Live process table with search and a confirmed End Task. |
| **Services** | Service table with search and confirmed start/stop/restart plus startup-type changes. |

### System

| Tool | What it does |
|---|---|
| **Disk & Cleanup** | Fixed and removable drives with total size, free space and file system; launches the Windows Disk Cleanup utility. |
| **Restore Point** | Lists existing system restore points and creates new ones with confirmation. |
| **License Info** | Windows edition, product key (registry or OEM source when available) and activation status; copy to clipboard. |

## Requirements

- Windows 10 / 11
- Python 3.13+ (only to run from source — the exe needs nothing)
- Administrator privileges (the exe self-elevates via UAC)

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

Output: `dist\WindowsPowerTool.exe` (onefile, no console, requests admin on launch).
To regenerate the app icon: `python assets/generate_icon.py` (requires Pillow).

## Notes

- Nothing is written next to the exe; theme preference lives in
  `%LOCALAPPDATA%\WindowsPowerTool\settings.json`.
- Locked/temporarily-in-use files are always skipped, never force-deleted.
- Destructive actions (service control, account changes, uninstall, restore
  points) always confirm before running; reads and refreshes never prompt.

## License

PolyForm Noncommercial 1.0.0 — free to use, modify and share for
noncommercial purposes; **selling the software or derivatives is not
permitted**. See [LICENSE](LICENSE).
