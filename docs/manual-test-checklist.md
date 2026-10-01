# Manual Test Checklist — Windows Power Tool

Run `python run.py` as a normal user (UAC should prompt). Check every box.

## Shell
- [ ] Window opens, sidebar shows CORE group with 4 tools
- [ ] Each tool opens without errors; switching is instant
- [ ] Theme toggle switches dark/light and survives an app restart
- [ ] Top-right badge reads "Running as Administrator"
- [ ] No console window ever flashes while using the app

## USB Guard
- [ ] Indicator shows "USB storage: ENABLED" (green) on a default system
- [ ] Disable → indicator turns red "DISABLED"; registry value is 4
- [ ] Plugged USB flash drive: appears in This PC, double-click = Access Denied
- [ ] Keyboard/mouse still work while disabled
- [ ] Enable → indicator green; the same drive opens normally after replug
- [ ] Drives plugged BEFORE disabling still work until replugged once

## Windows Speedup
- [ ] Clean Temp Data → green summary with items removed, MB freed, skipped count
- [ ] Prefetch/Temp/Recent actually emptied (spot-check C:\Windows\Temp)
- [ ] Locked file (e.g. open a file in %TEMP%) is counted as skipped, no error
- [ ] With Chrome running + checked: Chrome closes, cleans, reopens
- [ ] Browser history, passwords and settings remain after cleaning
- [ ] Cookies cleared: sites ask for login again
- [ ] Clean Temp & Reboot → 10s countdown visible with Cancel Reboot button
- [ ] Cancel Reboot → status "Reboot cancelled.", machine does NOT reboot
- [ ] Letting the countdown finish reboots the PC after ~10s

## Log Collector
- [ ] No log ticked → red "select at least one log"
- [ ] Minutes = "abc" → red validation error, nothing runs
- [ ] Text over 10 min → events.txt produced, green count message
- [ ] CSV over 10 min → events.csv opens in Excel with expected columns
- [ ] EVTX → Application.evtx opens in Event Viewer
- [ ] Preset buttons 10/30/60/1440 fill the minutes box
- [ ] Browse changes the destination folder

## System Info
- [ ] Show System Info fills every section (OS, hardware, network, storage, users)
- [ ] External/removable drive appears under Storage
- [ ] Users show correct groups (Administrators/Users)
- [ ] Copy to Clipboard pastes the report
- [ ] Save as TXT writes a readable file
- [ ] Theme toggle recolors the report pane
