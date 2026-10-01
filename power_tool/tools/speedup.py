import os
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Mapping

from power_tool.core import runner, tasks, widgets

BROWSER_PROCESSES = {"Chrome": "chrome.exe", "Edge": "msedge.exe",
                     "Firefox": "firefox.exe"}
_CHROMIUM_BROWSERS = ("Chrome", "Edge", "Brave", "Opera GX")
_PROFILE_DIRS = ("Default", "Profile 1", "Profile 2", "Profile 3", "Profile 4")
_CHROME_CACHE = ("Cache", "Code Cache", "GPUCache", "Service Worker",
                 "Local Storage", "Session Storage", "IndexedDB")
_FIREFOX_CACHE = ("cache2", "storage", "startupCache")
_COOKIE_FILES = ("Cookies", "Network/Cookies", "Network/Cookies-journal")
_FIREFOX_COOKIES = ("cookies.sqlite", "cookies.sqlite-wal", "cookies.sqlite-shm")


def default_temp_targets(env: Mapping[str, str]) -> list[Path]:
    windir = Path(env.get("WINDIR", r"C:\Windows"))
    appdata = Path(env.get("APPDATA", ""))
    return [
        Path(env.get("TEMP", "")),
        windir / "Temp",
        appdata / "Microsoft" / "Windows" / "Recent",
        windir / "Prefetch",
    ]


def _salvage_directory(item: Path) -> tuple[int, int, int]:
    """Best-effort recursive delete used when rmtree hits a locked file.

    Removes every file it can and each directory that ends up empty;
    locked files and the directories still holding them are skipped.
    """
    removed = freed = skipped = 0

    def onerror(_err: OSError) -> None:
        nonlocal skipped
        skipped += 1

    for root, _dirs, files in os.walk(item, topdown=False, onerror=onerror):
        directory = Path(root)
        for name in files:
            target = directory / name
            try:
                size = target.stat().st_size
                target.unlink()
            except OSError:
                skipped += 1
            else:
                removed += 1
                freed += size
        try:
            directory.rmdir()
        except OSError:
            pass
        else:
            removed += 1
    return removed, freed, skipped


def clear_directory(path: Path) -> tuple[int, int, int]:
    removed = freed = skipped = 0
    if not path.exists():
        return 0, 0, 0
    try:
        entries = list(path.iterdir())
    except OSError:
        return 0, 0, 1
    for entry in entries:
        try:
            if entry.is_dir() and not entry.is_symlink():
                size = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
                shutil.rmtree(entry)
            else:
                size = entry.stat().st_size
                entry.unlink()
            removed += 1
            freed += size
        except OSError:
            if entry.is_dir() and not entry.is_symlink():
                r, f, s = _salvage_directory(entry)
                removed += r
                freed += f
                skipped += s
            else:
                skipped += 1
    return removed, freed, skipped


def chromium_profiles(user_data: Path) -> list[Path]:
    if not user_data.is_dir():
        return []
    try:
        return sorted(d for d in user_data.iterdir()
                      if d.is_dir() and (d / "Preferences").exists())
    except OSError:
        return []


def browser_cleanup_targets(browser: str, env: Mapping[str, str]) -> list[Path]:
    targets: list[Path] = []
    if browser == "Firefox":
        profiles = Path(env.get("APPDATA", "")) / "Mozilla" / "Firefox" / "Profiles"
        if not profiles.is_dir():
            return []
        for profile in sorted(profiles.iterdir()):
            if not profile.is_dir():
                continue
            targets += [profile / name
                        for name in _FIREFOX_CACHE + _FIREFOX_COOKIES]
        return targets
    if browser in _CHROMIUM_BROWSERS:
        if browser == "Chrome":
            user_data = Path(env.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
        elif browser == "Edge":
            user_data = Path(env.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "User Data"
        elif browser == "Brave":
            user_data = Path(env.get("LOCALAPPDATA", "")) / "BraveSoftware" / "Brave-Browser" / "User Data"
        else:
            user_data = Path(env.get("APPDATA", "")) / "Opera Software" / "Opera GX Stable"
        for profile in chromium_profiles(user_data):
            targets += [profile / name for name in _CHROME_CACHE + _COOKIE_FILES]
    return targets


def remove_target(path: Path) -> tuple[bool, int]:
    try:
        if path.is_dir() and not path.is_symlink():
            size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            shutil.rmtree(path)
            return True, size
        if path.is_file():
            size = path.stat().st_size
            path.unlink()
            return True, size
        return False, 0
    except OSError:
        return False, 0


def format_summary(removed: int, freed: int, skipped: int) -> str:
    mb = freed / (1024 * 1024)
    return (f"Removed {removed} items · {mb:.1f} MB freed · "
            f"{skipped} skipped (locked or in use)")


def browser_launch_command(browser: str, env: Mapping[str, str]) -> list[str] | None:
    pf = Path(env.get("PROGRAMFILES", ""))
    pf86 = Path(env.get("PROGRAMFILES(X86)", ""))
    local = Path(env.get("LOCALAPPDATA", ""))
    candidates = {
        "Chrome": [pf / "Google/Chrome/Application/chrome.exe",
                   pf86 / "Google/Chrome/Application/chrome.exe",
                   local / "Google/Chrome/Application/chrome.exe"],
        "Edge": [pf86 / "Microsoft/Edge/Application/msedge.exe",
                 pf / "Microsoft/Edge/Application/msedge.exe"],
        "Firefox": [pf / "Mozilla Firefox/firefox.exe",
                    pf86 / "Mozilla Firefox/firefox.exe",
                    local / "Mozilla Firefox/firefox.exe"],
    }[browser]
    for candidate in candidates:
        if candidate.exists():
            return [str(candidate)]
    return None


def is_process_running(image: str) -> bool:
    result = runner.run(["tasklist", "/FI", f"IMAGENAME eq {image}"], timeout=30)
    return result.returncode == 0 and "No tasks" not in result.stdout


def close_process(image: str) -> None:
    runner.run(["taskkill", "/IM", image, "/F"], timeout=30)


class SpeedupFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=16)
        ttk.Label(self, text="Windows Speedup", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            self, wraplength=660, style="Dim.TLabel",
            text="Clears %TEMP%, Windows\\Temp, Recent and Prefetch, and can clean "
                 "each browser's cache and cookies/site data individually "
                 "(history, passwords and settings are never touched).",
        ).pack(anchor="w", pady=(6, 12))

        self._temp_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(self, text="Temp files, Prefetch, Recent",
                        variable=self._temp_var).pack(anchor="w")

        browser_box = ttk.Labelframe(
            self, text="Browser caches (select individually)", padding=10)
        browser_box.pack(anchor="w", pady=(8, 0))
        self._browser_vars: dict[str, tk.BooleanVar] = {}
        for browser in ("Chrome", "Edge", "Firefox"):
            var = tk.BooleanVar(value=False)
            self._browser_vars[browser] = var
            ttk.Checkbutton(browser_box, text=browser, variable=var).pack(
                side="left", padx=(0, 14))

        self._bin_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text="Recycle Bin", variable=self._bin_var).pack(
            anchor="w", pady=(8, 0))

        actions = ttk.Frame(self)
        actions.pack(anchor="w", pady=(14, 6))
        self._clean_button = ttk.Button(
            actions, text="Clean Temp Data", style="Accent.TButton",
            command=lambda: self._start(reboot=False))
        self._clean_button.pack(side="left", padx=(0, 8))
        self._reboot_button = ttk.Button(
            actions, text="Clean Temp & Reboot", style="Danger.TButton",
            command=lambda: self._start(reboot=True))
        self._reboot_button.pack(side="left")
        self._cancel_button = ttk.Button(
            actions, text="Cancel Reboot", command=self._cancel_reboot)
        self._cancel_countdown = None
        self._seconds_left = 0

        ttk.Button(self, text="Restart selected browsers",
                   command=self._restart_browsers).pack(anchor="w", pady=(0, 4))

        self.status = widgets.StatusPane(self)
        self.status.pack(fill="x", pady=(10, 0))

    def _selected_browsers(self) -> list[str]:
        return [name for name, var in self._browser_vars.items() if var.get()]

    def _start(self, reboot: bool) -> None:
        if not widgets.guard_admin(self.status):
            return
        if reboot and not widgets.confirm(
                self, "Reboot", "Clean temp data now and reboot in 10 seconds?"):
            return
        browsers = self._selected_browsers()
        clear_recycle = self._bin_var.get()
        self._set_buttons_state("disabled")
        self.status.set_working(
            "Cleaning temp folders"
            + (f" and {', '.join(browsers)}" if browsers else "") + "...")
        tasks.BackgroundTask(
            self,
            work=lambda: self._work(browsers, clear_recycle),
            on_done=lambda result: self._on_done(result, reboot),
            on_error=self._on_error,
        ).start()

    def _work(self, browsers: list[str], clear_recycle: bool) -> dict:
        env = dict(os.environ)
        # Close selected browsers first so files they hold open (temp
        # downloads, session files) are actually deletable below.
        was_running: dict[str, bool] = {}
        for browser in browsers:
            image = BROWSER_PROCESSES[browser]
            was_running[browser] = is_process_running(image)
            if was_running[browser]:
                close_process(image)
        removed = freed = skipped = 0
        for target in default_temp_targets(env):
            r, f, s = clear_directory(target)
            removed += r
            freed += f
            skipped += s
        cleaned_browsers = []
        for browser in browsers:
            for target in browser_cleanup_targets(browser, env):
                did_remove, size = remove_target(target)
                if did_remove:
                    removed += 1
                    freed += size
            cleaned_browsers.append(browser)
            if was_running[browser]:
                command = browser_launch_command(browser, env)
                if command:
                    try:
                        runner.start_detached(command)
                    except OSError:
                        pass
        if clear_recycle:
            runner.run_powershell(
                "Clear-RecycleBin -Force -ErrorAction SilentlyContinue")
        return {"removed": removed, "freed": freed, "skipped": skipped,
                "browsers": cleaned_browsers}

    def _on_done(self, result: dict, reboot: bool) -> None:
        self._set_buttons_state("normal")
        summary = format_summary(result["removed"], result["freed"], result["skipped"])
        if result["browsers"]:
            summary += " · " + ", ".join(result["browsers"]) + " cache/cookies cleared"
        if not reboot:
            self.status.set_success(summary)
            return
        shutdown = runner.run(["shutdown", "/r", "/t", "10"], timeout=30)
        if shutdown.returncode != 0:
            self.status.set_error(
                f"Cleaning done ({summary}) but reboot scheduling failed: "
                f"{shutdown.stderr.strip() or shutdown.stdout.strip()}")
            return
        self._start_countdown(summary)

    def _on_error(self, exc: BaseException) -> None:
        self._set_buttons_state("normal")
        self.status.set_error(f"Cleaning failed: {exc}")

    def _set_buttons_state(self, state: str) -> None:
        self._clean_button.configure(state=state)
        self._reboot_button.configure(state=state)

    def _start_countdown(self, summary: str) -> None:
        self._seconds_left = 10
        self._set_buttons_state("disabled")
        self._cancel_button.pack(side="left", padx=(8, 0))
        self.status.set_working(f"{summary} — rebooting in 10s...")
        self._cancel_countdown = self.after(1000, self._tick, summary)

    def _tick(self, summary: str) -> None:
        if self._seconds_left <= 0:
            self.status.set_working("Rebooting now...")
            return
        self.status.set_working(
            f"{summary} — rebooting in {self._seconds_left}s...")
        self._seconds_left -= 1
        self._cancel_countdown = self.after(1000, self._tick, summary)

    def _cancel_reboot(self) -> None:
        if self._cancel_countdown is not None:
            self.after_cancel(self._cancel_countdown)
            self._cancel_countdown = None
        self._cancel_button.pack_forget()
        self._set_buttons_state("normal")
        result = runner.run(["shutdown", "/a"], timeout=30)
        if result.returncode == 0:
            self.status.set_success("Reboot cancelled.")
        else:
            self.status.set_error(
                f"Could not cancel reboot: "
                f"{result.stderr.strip() or result.stdout.strip()}")

    def _restart_browsers(self) -> None:
        selected = self._selected_browsers()
        if not selected:
            self.status.set_error("Select at least one browser first.")
            return
        for browser in selected:
            image = BROWSER_PROCESSES[browser]
            if is_process_running(image):
                close_process(image)
        for browser in selected:
            command = browser_launch_command(browser, dict(os.environ))
            if command:
                try:
                    runner.start_detached(command)
                except OSError:
                    pass
        self.status.set_success(f"Browsers restarted: {', '.join(selected)}.")


def create(parent: ttk.Frame) -> ttk.Frame:
    return SpeedupFrame(parent)
