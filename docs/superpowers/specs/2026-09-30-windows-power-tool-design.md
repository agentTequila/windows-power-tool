# Windows Power Tool — Design Spec

Date: 2026-09-30
Status: Approved

## Goal

A single portable Windows desktop app for IT admins that combines the four tools the user already built as separate exes (USB Enabler/Disabler, Windows Speedup, Log Collector, System Info) plus eight admin helpers, in one always-elevated Python/tkinter GUI that builds to a portable exe with PyInstaller.

## Confirmed decisions

| Topic | Decision |
|---|---|
| Structure | One combined app, sidebar navigation, 12 tools |
| Tool set | Original 4 + 8 admin extras (all selected) |
| USB scope | USB storage only (USBSTOR); keyboards/mice/printers unaffected |
| Log format | Text, CSV, or native EVTX — user picks per run |
| OS support | Windows 10/11 only |
| Theme | Dark and light with a toggle |
| Architecture | Modular vanilla tkinter/ttk, zero third-party runtime deps |
| Execution | Nothing is run on the dev host; the user runs and tests everything |
| Distribution | GitHub push happens only when the user says so |

## Architecture

```
power_tool/
  main.py              # entry: sidebar, frame switching, top bar, theme toggle
  core/
    theme.py           # dark/light palettes, apply(root), toggle persistence
    runner.py          # hidden-window subprocess/PowerShell exec, capture, timeout
    admin.py           # is_admin(), require_admin()
    widgets.py         # shared styled widgets (buttons, checkboxes, status bar)
  tools/
    usb_guard.py       speedup.py        log_collector.py   system_info.py
    network.py         installed_apps.py users_groups.py    processes.py
    services.py        disk_cleanup.py   restore_point.py   license_info.py
  build.spec           # PyInstaller: --onefile --uac_admin --windowed
```

- Each tool module exposes a frame class/factory taking a parent; the sidebar swaps frames.
- Sidebar groups: **Core** (USB Guard, Speedup, Log Collector, System Info), **Admin** (Network, Installed Apps, Users & Groups, Processes, Services), **System** (Disk & Cleanup, Restore Point, License Info).
- Top bar: app title, dark/light toggle, "Running as Administrator" badge.
- `core/theme.py` holds color dicts for both themes; the toggle re-applies colors to all widgets. Preference persists to `%LOCALAPPDATA%\WindowsPowerTool\settings.json` — the app never writes files next to the exe.
- Long operations run in a background `thread`; results post back to tkinter with `after()`. The action button disables and a status message shows while work runs.
- Every external command goes through `core/runner.py`: `subprocess.run` with `CREATE_NO_WINDOW`, captured stdout/stderr, timeout guard.
- Errors never crash the app: failures render as inline red status text in the tool, including the command's stderr.

## Elevation

- PyInstaller builds with `uac_admin=True`, so every launch triggers the UAC prompt.
- Defense in depth: `core/admin.py` checks `IsUserAnAdmin()`; if not elevated, each action button shows "Run as administrator required" instead of executing.

## Tool specs

### 1. USB Guard

- Status indicator (green/red dot + label) reads `HKLM\SYSTEM\CurrentControlSet\Services\USBSTOR\Start` when the tool opens and after every action: `4` = Disabled, `3` = Enabled (Windows default).
- Buttons: **Disable USB Storage** (write `4`) and **Enable USB Storage** (write `3`), via `winreg`, admin only.
- Applies to newly plugged devices without reboot; hint text tells the user to replug an already-connected drive.
- Blocked drives still appear in This PC but open with Access Denied — expected behavior, noted in the UI hint.

### 2. Speedup

- Browser checkboxes: Firefox, Chrome, Edge (independent).
- Temp pass clears all four locations every run: `%TEMP%`, `C:\Windows\Temp`, Recent, Prefetch. Locked/in-use files are skipped automatically and counted, never treated as errors.
- Browser pass (per checked browser): close the running instance → delete only `Cache`, `Code Cache`, `Service Worker`, `Cookies`, `Local Storage` (site data) → relaunch the browser only if it was running before. History, passwords, bookmarks, downloads, and site settings are untouched.
  - Chrome/Edge: `Local\Google\Chrome\User Data` and `Local\Microsoft\Edge\User Data`, each profile.
  - Firefox: `%APPDATA%\Mozilla\Firefox\Profiles\*\`.
- Buttons:
  - **Clean Temp Data** — runs the temp pass and the checked browser passes; shows summary (files removed, MB freed, files skipped).
  - **Clean Temp & Reboot** — runs the same cleaning, then shows a visible 10-second countdown in the UI and schedules `shutdown /r /t 10`. A **Cancel** button aborts the reboot with `shutdown /a`.

### 3. Log Collector

- Log checkboxes: Application, System, Security, Setup. (The user's "audit log" = audit records inside the Security log.)
- Level checkboxes: Critical, Error, Warning, Information, Verbose.
- Timeframe: numeric entry labeled with hardcoded "minutes" text, integers only; quick presets 10 / 30 / 60 / 1440.
- Format radio: **Text (.txt)**, **CSV (.csv)**, **Native EVTX (.evtx)** — one per run.
  - EVTX: `wevtutil epl` per selected log with an XPath time/level filter.
  - Text/CSV: PowerShell `Get-WinEvent` filtered by log, level, and time window, then formatted output.
- Destination: folder picker; default `Desktop\Logs_yyyyMMdd_HHmmss`.
- Progress feedback while collecting; summary shows events collected and file path.

### 4. System Info Display

- One **Show System Info** button fills a scrollable, selectable text pane with: hostname, OS edition/build, all IP addresses + MAC per adapter, local users and their groups (Administrators/Users/etc.), device manufacturer and model, CPU model/cores, RAM total and per-module, storage drives including removable/external, uptime and last boot time.
- Buttons: **Copy to Clipboard**, **Save as TXT**.

### 5. Network fix-its

- Actions: Flush DNS (`ipconfig /flushdns`), Release IP, Renew IP, Release + Renew; results shown in the output pane.
- Ping tool: host entry field, `ping -n 4 <host>`; output appears in the pane when the command finishes (runs in a background thread, button disabled meanwhile).

### 6. Installed Apps

- Treeview table (Name, Version, Publisher, Size, Installed date) aggregated from all Uninstall registry hives: HKLM 64-bit, HKLM 32-bit, HKCU.
- Search box filters live; **Export CSV** button.
- **Uninstall** button: confirmation dialog, then runs the app's UninstallString.

### 7. Restore Point Creator

- Table of existing restore points (`Get-ComputerRestorePoint`).
- **Create Restore Point** button runs `Checkpoint-Computer` with a timestamped description; status shows the result.

### 8. Users & Group Manager

- Table of local users: name, full name, enabled state, group membership.
- Actions, each behind a confirmation where destructive: add user to group / remove from group (group dropdown: Administrators, Users, plus other local groups), reset local password, enable account, disable account, delete account.

### 9. Process Manager

- Treeview: name, PID, CPU, RAM, executable path; search filter; **Refresh** button.
- **End Process** with confirmation dialog.

### 10. Service Manager

- Treeview: service name, display name, status, startup type; refresh.
- Actions with confirmation: Start, Stop, Restart, and change startup type (Automatic / Manual / Disabled).

### 11. Disk Space & Cleanup

- Table of all drives (fixed + external): total, free, % free, file system.
- **Run Disk Cleanup** button launches `cleanmgr`.

### 12. License / Activation Info

- Shows Windows edition, product key (registry/OEM source when available), digital license/activation status via `SoftwareLicensingProduct` CIM query.
- **Copy** button for the whole block.

## Error handling & UX conventions

- Destructive or system-level actions always confirm first.
- Every tool has a status area: idle (gray), working (blue + disabled buttons), success (green summary), failure (red + detail).
- No pop-up console windows ever appear (`CREATE_NO_WINDOW`).
- UI language: English.

## Build & repo

- PyInstaller `build.spec`: `--onefile --uac_admin --windowed`, icon included if present; output `dist/WindowsPowerTool.exe`.
- Repo layout: `power_tool/`, `build.spec`, `README.md`, `requirements.txt` (PyInstaller, dev-only), `.gitignore` (`build/`, `dist/`, `__pycache__/`), `docs/superpowers/specs/`.
- The four pre-existing exes in the repo root stay untouched.
- Nothing is executed on the dev machine by the assistant; the user runs the app, the build, and git commands when asked.

## Verification

Per-tool manual test checklist (written with the plan), covering for each button: expected visible result, expected registry/service/system change, and failure mode (e.g., running non-elevated, missing browser, locked file). The user runs the checklist and reports results.
