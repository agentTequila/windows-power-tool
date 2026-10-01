# Manual Test Checklist — Windows Power Tool

Run `python run.py` as a normal user (UAC should prompt). Check every box.

## Shell
- [ ] Window opens, sidebar shows CORE group with 4 tools
- [ ] Each tool opens without errors; switching is instant
- [ ] Theme toggle switches dark/light and survives an app restart
- [ ] Top-right badge reads "Running as Administrator"
- [ ] No console window ever flashes while using the app
- [ ] Checkboxes show tick marks (not crosses) when selected
- [ ] Dark mode: hovering any checkbox/button keeps text readable (no white-on-white)

## USB Guard
- [ ] Indicator shows "USB storage: ALLOWED" (green) on a default system
- [ ] Block → indicator turns red "BLOCKED — visible, access denied"
- [ ] Plugged USB flash drive: STILL appears in This PC while blocked
- [ ] Opening or copying to the blocked drive = Access denied
- [ ] Keyboard/mouse still work while blocked
- [ ] Allow → indicator green; the same drive opens normally (reopen/replug)
- [ ] Drives plugged BEFORE blocking still show while blocked

## Windows Speedup
- [ ] Clean Temp Data → green summary with items removed, MB freed, skipped count
- [ ] Prefetch/Temp/Recent actually emptied (spot-check C:\Windows\Temp)
- [ ] Locked file (e.g. open a file in %TEMP%) is counted as skipped, no error
- [ ] Browsers are unchecked by default; each browser selectable individually
- [ ] With Chrome checked + running: Chrome closes during cleanup, then reopens
- [ ] Only checked browsers are touched; others stay running
- [ ] Browser history, passwords and settings remain after cleaning
- [ ] Cookies cleared: sites ask for login again
- [ ] Recycle Bin checkbox empties the recycle bin when checked
- [ ] Clean Temp & Reboot → 10s countdown visible with Cancel Reboot button
- [ ] Cancel Reboot → status "Reboot cancelled.", machine does NOT reboot
- [ ] Letting the countdown finish reboots the PC after ~10s
- [ ] Restart selected browsers → only checked browsers restart

## Log Collector
- [ ] No log ticked → red "select at least one log"
- [ ] Minutes = "abc" → red validation error, nothing runs
- [ ] Text over 10 min → events.txt produced, green count message
- [ ] CSV over 10 min → events.csv opens in Excel with expected columns
- [ ] EVTX → Application.evtx opens in Event Viewer
- [ ] Empty output (0 events) is reported honestly, not fake-success
- [ ] Preset buttons 10/30/60/1440 fill the minutes box
- [ ] Browse changes the destination folder

## System Info
- [ ] Show System Info fills every section (OS, hardware, network, storage, users)
- [ ] External/removable drive appears under Storage
- [ ] Users show correct groups (Administrators/Users)
- [ ] Copy to Clipboard pastes the report
- [ ] Save as TXT writes a readable file
- [ ] Theme toggle recolors the report pane
