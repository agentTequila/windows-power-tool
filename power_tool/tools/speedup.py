import os
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from power_tool.core import runner, tasks, widgets

_PROFILE_DIRS = ("Default", "Profile 1", "Profile 2", "Profile 3", "Profile 4")
_CHROME_CACHE = ("Cache", "Code Cache", "GPUCache", "Service Worker",
                 "Local Storage", "Session Storage", "IndexedDB")
_FIREFOX_CACHE = ("cache2", "storage", "startupCache")
_COOKIE_FILES = ("Cookies", "Network/Cookies")
_CHROMIUM_BROWSERS = ("Chrome", "Edge", "Brave", "Opera GX")


def default_temp_targets(env: dict) -> list:
    return [
        Path(env["TEMP"]),
        Path(env["WINDIR"]) / "Temp",
        Path(env["APPDATA"]) / "Microsoft" / "Windows" / "Recent",
        Path(env["WINDIR"]) / "Prefetch",
    ]


def clear_directory(path) -> tuple:
    """Delete files under path (recursive). Returns (removed, freed, skipped)."""
    path = Path(path)
    if not path.exists():
        return (0, 0, 0)
    removed = freed = skipped = 0
    for item in list(path.iterdir()):
        try:
            if item.is_dir():
                size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                shutil.rmtree(item)
                removed += 1
                freed += size
            else:
                size = item.stat().st_size
                item.unlink()
                removed += 1
                freed += size
        except OSError:
            skipped += 1
    return (removed, freed, skipped)


def chromium_profiles(user_data: Path) -> list:
    profiles = []
    if not user_data.exists():
        return profiles
    for name in _PROFILE_DIRS:
        profile = user_data / name
        if (profile / "Preferences").exists():
            profiles.append(profile)
    return profiles


def browser_cleanup_targets(browser: str, env: dict) -> list:
    targets = []
    if browser in _CHROMIUM_BROWSERS:
        base = Path(env.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
        if browser == "Edge":
            base = Path(env.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "User Data"
        elif browser == "Brave":
            base = Path(env.get("LOCALAPPDATA", "")) / "BraveSoftware" / "Brave-Browser" / "User Data"
        elif browser == "Opera GX":
            base = Path(env.get("APPDATA", "")) / "Opera Software" / "Opera GX Stable"
        for profile in chromium_profiles(base):
            for name in _CHROME_CACHE:
                targets.append(profile / name)
            for name in _COOKIE_FILES:
                targets.append(profile / name)
    elif browser == "Firefox":
        profiles_dir = Path(env.get("APPDATA", "")) / "Mozilla" / "Firefox" / "Profiles"
        if profiles_dir.exists():
            for profile in profiles_dir.iterdir():
                if not profile.is_dir():
                    continue
                for name in _FIREFOX_CACHE:
                    targets.append(profile / name)
                targets.append(profile / "cookies.sqlite")
    return targets


def remove_target(target) -> tuple:
    target = Path(target)
    if not target.exists():
        return (False, 0)
    try:
        if target.is_dir():
            freed = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
            shutil.rmtree(target)
        else:
            freed = target.stat().st_size
            target.unlink()
        return (True, freed)
    except OSError:
        return (False, 0)


def format_summary(removed: int, freed: int, skipped: int) -> str:
    mb = freed / (1024 * 1024)
    parts = [f"Removed {removed} items", f"freed {mb:.1f} MB"]
    if skipped:
        parts.append(f"skipped {skipped} locked files")
    return ", ".join(parts) + "."


def browser_launch_command(browser: str, env: dict) -> list | None:
    candidates = {
        "Chrome": [
            Path(env.get("PROGRAMFILES", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(env.get("PROGRAMFILES(X86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(env.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        ],
        "Edge": [
            Path(env.get("PROGRAMFILES(X86)", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            Path(env.get("PROGRAMFILES", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        ],
        "Firefox": [
            Path(env.get("PROGRAMFILES", "")) / "Mozilla Firefox" / "firefox.exe",
            Path(env.get("PROGRAMFILES(X86)", "")) / "Mozilla Firefox" / "firefox.exe",
        ],
    }
    for candidate in candidates.get(browser, []):
        if candidate.exists():
            return [str(candidate)]
    return None


def is_process_running(name: str) -> bool:
    result = runner.run(["tasklist", "/FI", f"IMAGENAME eq {name}"])
    if result.returncode != 0:
        return False
    return name.lower() in result.stdout.lower()


class SpeedupFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=16)
        ttk.Label(self, text="Windows Speedup", style="Title.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(
            self, wraplength=660, style="Dim.TLabel",
            text="Clear temp files, browser caches and recycle bin. Locked files "
                 "are skipped, never force-deleted.",
        ).grid(row=1, column=0, sticky="w", pady=(6, 12))

        self._temp_var = tk.BooleanVar(value=True)
        self._bin_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self, text="Temp files, Prefetch, Recent",
                        variable=self._temp_var).grid(row=2, column=0, sticky="w")

        browsers_box = ttk.Labelframe(self, text="Browser caches", padding=8)
        browsers_box.grid(row=3, column=0, sticky="w", pady=(8, 0))
        self._browser_vars = {}
        for name in ("Chrome", "Edge", "Firefox"):
            var = tk.BooleanVar(value=True)
            self._browser_vars[name] = var
            ttk.Checkbutton(browsers_box, text=name, variable=var).pack(
                side="left", padx=(0, 12))

        ttk.Checkbutton(self, text="Recycle Bin",
                        variable=self._bin_var).grid(row=4, column=0, sticky="w",
                                                     pady=(8, 0))

        self._run_button = ttk.Button(self, text="Run Cleanup",
                                      style="Accent.TButton", command=self._run)
        self._run_button.grid(row=5, column=0, sticky="w", pady=(14, 4))

        ttk.Button(self, text="Restart browsers after cleanup",
                   command=self._restart_browsers).grid(row=6, column=0, sticky="w")

        self.status = widgets.StatusPane(self)
        self.status.grid(row=7, column=0, sticky="ew", pady=(14, 0))
        self._task = None
        self._busy = False

    def _selected_browsers(self) -> list[str]:
        return [name for name, var in self._browser_vars.items() if var.get()]

    def _gather_targets(self, env: dict) -> list:
        targets = []
        if self._temp_var.get():
            targets.extend(default_temp_targets(env))
        for browser in self._selected_browsers():
            targets.extend(browser_cleanup_targets(browser, env))
        return targets

    def _run(self) -> None:
        if self._busy:
            return
        if not widgets.guard_admin(self.status):
            return
        self._busy = True
        self._run_button.state(["disabled"])
        self.status.set_working("Cleaning up...")
        env = dict(os.environ)
        targets = self._gather_targets(env)
        self._task = tasks.BackgroundTask(
            self, lambda: self._cleanup(targets),
            self._on_done, self._on_error)
        self._task.start()

    def _cleanup(self, targets: list) -> str:
        removed = freed = skipped = 0
        for target in targets:
            if Path(target).is_dir():
                r, f, s = clear_directory(target)
            else:
                ok, f = remove_target(target)
                r, s = (1, 0) if ok else (0, 1)
            removed += r
            freed += f
            skipped += s
        if self._bin_var.get():
            runner.run_powershell("Clear-RecycleBin -Force -ErrorAction SilentlyContinue")
        return format_summary(removed, freed, skipped)

    def _on_done(self, result) -> None:
        self._busy = False
        self._run_button.state(["!disabled"])
        self.status.set_success(str(result))

    def _on_error(self, exc: BaseException) -> None:
        self._busy = False
        self._run_button.state(["!disabled"])
        self.status.set_error(f"Cleanup failed: {exc}")

    def _restart_browsers(self) -> None:
        selected = self._selected_browsers()
        if not selected:
            self.status.set_error("Select at least one browser first.")
            return
        names = {"Chrome": "chrome.exe", "Edge": "msedge.exe",
                 "Firefox": "firefox.exe"}
        for browser in selected:
            exe = names[browser]
            if is_process_running(exe):
                runner.run(["taskkill", "/IM", exe, "/F"])
        for browser in selected:
            cmd = browser_launch_command(browser, dict(os.environ))
            if cmd:
                runner.start_detached(cmd)
        self.status.set_success(
            f"Browsers restarted: {', '.join(selected)}.")


def create(parent: ttk.Frame) -> ttk.Frame:
    return SpeedupFrame(parent)
