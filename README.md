# Windows Power Tool

A portable, always-elevated Windows admin toolbox built with Python and tkinter.
One exe, twelve planned tools, zero runtime dependencies.

## Tools (this milestone)

| Tool | What it does |
|---|---|
| USB Guard | Disable/enable USB storage via the USBSTOR registry value; drives show in This PC but open Access Denied while disabled. Keyboards/mice unaffected. |
| Windows Speedup | Clears `%TEMP%`, `Windows\Temp`, Recent, Prefetch; optionally clears browser cache + cookies/site data (Chrome, Edge, Firefox) and reopens the browser. Clean-only or clean-and-reboot (10s countdown, cancelable). |
| Log Collector | Collects Application/System/Security/Setup event logs for the last N minutes, filtered by level, as .txt, .csv or native .evtx. |
| System Info | Hostname, OS, IPs/MAC, local users + groups, hardware, storage (incl. removable), uptime. Copy/save to text. |

## Requirements

- Windows 10 / 11
- Python 3.13+ (to run from source)
- Administrator privileges (the exe self-elevates via UAC)

## Run from source

```powershell
python run.py
```

## Tests

```powershell
python -m unittest discover -s tests -t . -v
```

## Build the portable exe

```powershell
pyinstaller --noconfirm build.spec
```

Output: `dist\WindowsPowerTool.exe` (onefile, no console, requests admin on launch).

## Notes

- Nothing is written next to the exe; theme preference lives in
  `%LOCALAPPDATA%\WindowsPowerTool\settings.json`.
- Locked/temporarily-in-use files are always skipped, never force-deleted.
