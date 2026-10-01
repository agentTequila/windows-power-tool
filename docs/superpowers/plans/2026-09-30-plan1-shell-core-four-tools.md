# Windows Power Tool — Plan 1: Shell, Core, and Original 4 Tools

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the runnable Windows Power Tool app — sidebar shell, shared core (theme/admin/runner/tasks/widgets), and the original four tools (USB Guard, Speedup, Log Collector, System Info) — plus a portable elevated exe.

**Architecture:** Modular package `power_tool/` using vanilla tkinter/ttk with zero third-party runtime dependencies. Each tool is a module exposing `create(parent: ttk.Frame) -> ttk.Frame`; the shell swaps frames from a registry. All external commands run hidden via `core/runner.py`; long work runs on `core/tasks.py` BackgroundTask with main-thread polling.

**Tech Stack:** Python 3.14 (stdlib only: tkinter, unittest, subprocess, winreg, ctypes), PyInstaller 6.22 for packaging.

## Global Constraints

- Windows 10/11 only; UI language English.
- No third-party runtime dependencies; tests use stdlib `unittest` (no pytest, no pip installs).
- **Never execute any command on the dev host without asking the user first** (unittest runs, git, pyinstaller, launching the app). Every "Run:" step below is preceded by an ask. The user has stated this host is not a test environment.
- USB Guard registry: `HKLM\SYSTEM\CurrentControlSet\Services\USBSTOR\Start`, 64-bit view; `4` = disabled, `3` = enabled (Windows default).
- Speedup temp targets exactly: `%TEMP%`, `%WINDIR%\Temp`, Recent (`%APPDATA%\Microsoft\Windows\Recent`), Prefetch (`%WINDIR%\Prefetch`). Locked files are skipped automatically and counted, never errors.
- Reboot delay exactly **10 seconds**, visible countdown, with a working Cancel (`shutdown /a`).
- Browser cleaning touches only: `Cache`, `Code Cache`, `Service Worker`, `Cookies`, `Local Storage` (+ Firefox equivalents `cache2`, `storage`, `startupCache`, `cookies.sqlite*`). Never history, passwords, bookmarks, downloads, site settings.
- Log Collector logs: Application, System, Security, Setup. Levels: Critical(1), Error(2), Warning(3), Information(4), Verbose(5). Formats: txt / csv / evtx, user picks one per run.
- Exe build: PyInstaller onefile, `console=False`, `uac_admin=True`, output `dist/WindowsPowerTool.exe`.
- After every task: commit (ask user for approval before running git).

## File Structure

```
Windows Power Tool/
  run.py                      # thin launcher: from power_tool.main import main
  build.spec                  # PyInstaller spec
  requirements.txt            # pyinstaller (dev only)
  README.md
  .gitignore                  # build/, dist/, __pycache__/, *.pyc, .venv/
  power_tool/
    __init__.py
    main.py                   # app shell: sidebar, frame switching, theme toggle, admin badge
    core/
      __init__.py
      theme.py                # palettes, apply_theme, observe, settings persistence
      admin.py                # is_admin()
      runner.py               # run(), run_powershell(), start_detached() — CREATE_NO_WINDOW
      tasks.py                # BackgroundTask (worker thread + main-thread polling)
      widgets.py              # StatusPane, confirm, guard_admin, copy_text
    tools/
      __init__.py             # REGISTRY: [(group, [(label, module), ...]), ...]
      usb_guard.py            # Task 5 (placeholder in Task 4)
      speedup.py              # Task 6 (placeholder in Task 4)
      log_collector.py        # Task 7 (placeholder in Task 4)
      system_info.py          # Task 8 (placeholder in Task 4)
  tests/
    test_theme.py  test_admin.py  test_runner.py  test_tasks.py  test_widgets.py
    test_usb_guard.py  test_speedup.py  test_log_collector.py  test_system_info.py
  docs/
    manual-test-checklist.md  # Task 9
    superpowers/specs/2026-09-30-windows-power-tool-design.md   # already written
```

Run tests from repo root: `python -m unittest discover -s tests -t . -v`
Run app from repo root: `python run.py`

---

### Task 1: Package scaffold + theme core

**Files:**
- Create: `power_tool/__init__.py`, `power_tool/core/__init__.py`, `power_tool/tools/__init__.py`, `run.py`
- Create: `power_tool/core/theme.py`
- Test: `tests/test_theme.py`

**Interfaces:**
- Produces: `theme.PALETTES: dict[str, dict[str, str]]`, `theme.get_palette(name: str) -> dict`, `theme.settings_path() -> Path`, `theme.load_theme_name(path: Path | None = None) -> str`, `theme.save_theme_name(name: str, path: Path | None = None) -> None`, `theme.current_palette() -> dict`, `theme.observe(cb: Callable[[dict], None]) -> None`, `theme.apply_theme(root, name: str) -> dict` (sets `theme._current`, configures ttk styles, notifies observers). Palette keys (both themes must have identical key sets): `bg, panel, panel2, fg, dim, accent, accent_fg, success, danger, warn, border, entry_bg`.
- `power_tool/tools/__init__.py` exposes `REGISTRY: list[tuple[str, list[tuple[str, module]]]]` (starts empty, filled in Task 4).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_theme.py
import json
import tempfile
import unittest
from pathlib import Path

from power_tool.core import theme


class PaletteTests(unittest.TestCase):
    def test_both_palettes_have_identical_keys(self):
        self.assertEqual(set(theme.PALETTES["dark"].keys()), set(theme.PALETTES["light"].keys()))

    def test_palette_keys_match_spec(self):
        expected = {"bg", "panel", "panel2", "fg", "dim", "accent", "accent_fg",
                    "success", "danger", "warn", "border", "entry_bg"}
        self.assertEqual(set(theme.PALETTES["dark"].keys()), expected)

    def test_get_palette_returns_copy(self):
        pal = theme.get_palette("dark")
        pal["bg"] = "mutated"
        self.assertNotEqual(theme.PALETTES["dark"]["bg"], "mutated")

    def test_get_palette_unknown_raises(self):
        with self.assertRaises(KeyError):
            theme.get_palette("neon")


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "settings.json"
        self.addCleanup(self.tmp.cleanup)

    def test_load_missing_file_returns_default(self):
        self.assertEqual(theme.load_theme_name(self.path), theme.DEFAULT_THEME)

    def test_load_corrupt_file_returns_default(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(theme.load_theme_name(self.path), theme.DEFAULT_THEME)

    def test_load_invalid_theme_name_returns_default(self):
        self.path.write_text(json.dumps({"theme": "neon"}), encoding="utf-8")
        self.assertEqual(theme.load_theme_name(self.path), theme.DEFAULT_THEME)

    def test_save_then_load_roundtrip(self):
        theme.save_theme_name("light", self.path)
        self.assertEqual(theme.load_theme_name(self.path), "light")

    def test_save_creates_parent_dirs(self):
        nested = Path(self.tmp.name) / "a" / "b" / "settings.json"
        theme.save_theme_name("dark", nested)
        self.assertTrue(nested.exists())

    def test_save_unknown_name_raises(self):
        with self.assertRaises(ValueError):
            theme.save_theme_name("neon", self.path)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -t . -v` — **ask user for approval first**
Expected: FAIL — `ModuleNotFoundError: No module named 'power_tool'`

- [ ] **Step 3: Write the scaffold and theme implementation**

```python
# run.py
from power_tool.main import main

if __name__ == "__main__":
    main()
```

```python
# power_tool/__init__.py
```

```python
# power_tool/core/__init__.py
```

```python
# power_tool/tools/__init__.py
REGISTRY: list = []
```

```python
# power_tool/core/theme.py
import json
import os
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable

PALETTES = {
    "dark": {
        "bg": "#1e1f26", "panel": "#26272f", "panel2": "#2e2f3a",
        "fg": "#e6e6ea", "dim": "#9a9aa8", "accent": "#4f8cff",
        "accent_fg": "#ffffff", "success": "#3fbf6f", "danger": "#e05555",
        "warn": "#e0a13f", "border": "#3a3b47", "entry_bg": "#17181d",
    },
    "light": {
        "bg": "#f4f5f8", "panel": "#ffffff", "panel2": "#eceef3",
        "fg": "#1b1c22", "dim": "#5f6070", "accent": "#2f6fe0",
        "accent_fg": "#ffffff", "success": "#1f9d55", "danger": "#d13b3b",
        "warn": "#b57a17", "border": "#d4d6de", "entry_bg": "#ffffff",
    },
}
DEFAULT_THEME = "dark"

_observers: list[Callable[[dict], None]] = []
_current: dict = dict(PALETTES[DEFAULT_THEME])


def settings_path() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "WindowsPowerTool" / "settings.json"


def get_palette(name: str) -> dict:
    return dict(PALETTES[name])


def current_palette() -> dict:
    return dict(_current)


def load_theme_name(path: Path | None = None) -> str:
    p = path or settings_path()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return DEFAULT_THEME
    name = data.get("theme", DEFAULT_THEME)
    return name if name in PALETTES else DEFAULT_THEME


def save_theme_name(name: str, path: Path | None = None) -> None:
    if name not in PALETTES:
        raise ValueError(f"unknown theme: {name}")
    p = path or settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"theme": name}), encoding="utf-8")


def observe(cb: Callable[[dict], None]) -> None:
    _observers.append(cb)


def apply_theme(root: tk.Misc, name: str) -> dict:
    global _current
    palette = get_palette(name)
    _current = palette
    p = palette
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", background=p["bg"], foreground=p["fg"],
                    fieldbackground=p["entry_bg"], bordercolor=p["border"])
    style.configure("TFrame", background=p["bg"])
    style.configure("Panel.TFrame", background=p["panel"])
    style.configure("TLabel", background=p["bg"], foreground=p["fg"])
    style.configure("Panel.TLabel", background=p["panel"], foreground=p["fg"])
    style.configure("PanelDim.TLabel", background=p["panel"], foreground=p["dim"])
    style.configure("PanelTitle.TLabel", background=p["panel"], foreground=p["fg"],
                    font=("Segoe UI", 13, "bold"))
    style.configure("Dim.TLabel", background=p["bg"], foreground=p["dim"])
    style.configure("Title.TLabel", background=p["bg"], foreground=p["fg"],
                    font=("Segoe UI", 14, "bold"))
    style.configure("Idle.TLabel", background=p["panel"], foreground=p["dim"])
    style.configure("Working.TLabel", background=p["panel"], foreground=p["accent"])
    style.configure("Success.TLabel", background=p["panel"], foreground=p["success"])
    style.configure("Error.TLabel", background=p["panel"], foreground=p["danger"])
    style.configure("Accent.TButton", background=p["accent"], foreground=p["accent_fg"],
                    padding=(12, 6))
    style.map("Accent.TButton", foreground=[("disabled", p["dim"])])
    style.configure("Danger.TButton", background=p["danger"], foreground=p["accent_fg"],
                    padding=(12, 6))
    style.map("Danger.TButton", foreground=[("disabled", p["dim"])])
    style.configure("TButton", padding=(10, 5))
    style.configure("TCheckbutton", background=p["bg"], foreground=p["fg"])
    style.map("TCheckbutton", foreground=[("disabled", p["dim"])])
    style.configure("TRadiobutton", background=p["bg"], foreground=p["fg"])
    style.configure("TEntry", fieldbackground=p["entry_bg"], foreground=p["fg"])
    style.configure("TLabelframe", background=p["bg"], foreground=p["fg"],
                    bordercolor=p["border"])
    style.configure("TLabelframe.Label", background=p["bg"], foreground=p["dim"])
    style.configure("Treeview", background=p["panel"], foreground=p["fg"],
                    fieldbackground=p["panel"], rowheight=24)
    style.configure("Treeview.Heading", background=p["panel2"], foreground=p["fg"])
    style.map("Treeview", background=[("selected", p["accent"])],
              foreground=[("selected", p["accent_fg"])])
    style.configure("Sidebar.TButton", background=p["panel"], foreground=p["fg"],
                    anchor="w", padding=(14, 8))
    style.map("Sidebar.TButton", background=[("active", p["panel2"])])
    style.configure("Active.Sidebar.TButton", background=p["accent"],
                    foreground=p["accent_fg"], anchor="w", padding=(14, 8))

    for cb in list(_observers):
        try:
            cb(dict(palette))
        except tk.TclError:
            _observers.remove(cb)
    return dict(palette)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -t . -v` — **ask user for approval first**
Expected: `Ran 10 tests ... OK`

- [ ] **Step 5: Commit (ask user for approval first)**

```bash
git add run.py power_tool tests
git commit -m "feat: scaffold package and theme core with palettes and settings"
```

---

### Task 2: admin, runner, tasks core modules

**Files:**
- Create: `power_tool/core/admin.py`, `power_tool/core/runner.py`, `power_tool/core/tasks.py`
- Test: `tests/test_admin.py`, `tests/test_runner.py`, `tests/test_tasks.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `admin.is_admin() -> bool`
  - `runner.Result(returncode: int, stdout: str, stderr: str)` (NamedTuple)
  - `runner.run(args: Sequence[str], timeout: int = 120) -> Result` — never raises; timeout/OSError become `Result(-1, "", reason)`
  - `runner.run_powershell(script: str, timeout: int = 300) -> Result` — prepends `powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command`
  - `runner.start_detached(args: Sequence[str]) -> int` — returns PID, raises `OSError` if the binary is missing (caller handles)
  - `tasks.BackgroundTask(app, work, on_done, on_error=None, poll_ms=100)` with `.start()`; `on_done(result)` / `on_error(exc)` always called on the main thread

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_admin.py
import unittest
from unittest.mock import patch

from power_tool.core import admin


class AdminTests(unittest.TestCase):
    def test_is_admin_true(self):
        with patch.object(admin.ctypes, "windll") as wl:
            wl.shell32.IsUserAnAdmin.return_value = 1
            self.assertTrue(admin.is_admin())

    def test_is_admin_false(self):
        with patch.object(admin.ctypes, "windll") as wl:
            wl.shell32.IsUserAnAdmin.return_value = 0
            self.assertFalse(admin.is_admin())

    def test_is_admin_swallows_exception(self):
        with patch.object(admin.ctypes, "windll") as wl:
            wl.shell32.IsUserAnAdmin.side_effect = OSError("boom")
            self.assertFalse(admin.is_admin())


if __name__ == "__main__":
    unittest.main()
```

```python
# tests/test_runner.py
import sys
import unittest

from power_tool.core import runner


class RunTests(unittest.TestCase):
    def test_run_captures_output(self):
        result = runner.run([sys.executable, "-c", "print('hello')"], timeout=30)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "hello")

    def test_run_timeout_returns_error_result(self):
        result = runner.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1)
        self.assertEqual(result.returncode, -1)
        self.assertIn("timed out", result.stderr)

    def test_run_missing_binary_returns_error_result(self):
        result = runner.run(["definitely_not_a_real_binary_xyz_123"])
        self.assertEqual(result.returncode, -1)
        self.assertTrue(result.stderr)

    def test_run_does_not_leak_console_output(self):
        self.assertTrue(runner.CREATE_NO_WINDOW > 0)

    def test_run_powershell_prepends_flags(self):
        result = runner.run_powershell("Write-Output 'ps-ok'", timeout=60)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("ps-ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
```

```python
# tests/test_tasks.py
import unittest

from power_tool.core import tasks


class FakeApp:
    def after(self, ms, cb):
        return "after-id"


class BackgroundTaskTests(unittest.TestCase):
    def test_done_callback_receives_result(self):
        seen = []
        task = tasks.BackgroundTask(FakeApp(), work=lambda: 42, on_done=seen.append)
        task._run()
        task._poll()
        self.assertEqual(seen, [42])

    def test_error_callback_receives_exception(self):
        seen = []

        def boom():
            raise RuntimeError("kaboom")

        task = tasks.BackgroundTask(FakeApp(), work=boom, on_done=lambda r: None,
                                    on_error=seen.append)
        task._run()
        task._poll()
        self.assertEqual(len(seen), 1)
        self.assertIsInstance(seen[0], RuntimeError)

    def test_poll_reschedules_while_running(self):
        calls = []

        class PollApp:
            def after(self, ms, cb):
                calls.append(ms)

        task = tasks.BackgroundTask(PollApp(), work=lambda: 1, on_done=lambda r: None)
        task._poll()
        self.assertEqual(calls, [100])

    def test_start_spawns_daemon_thread(self):
        task = tasks.BackgroundTask(FakeApp(), work=lambda: "done", on_done=lambda r: None)
        task.start()
        task._thread.join(timeout=5)
        self.assertTrue(task._done)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -t . -v` — **ask user for approval first**
Expected: FAIL — `ModuleNotFoundError: No module named 'power_tool.core.admin'`

- [ ] **Step 3: Write the implementations**

```python
# power_tool/core/admin.py
import ctypes


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False
```

```python
# power_tool/core/runner.py
import subprocess
from typing import NamedTuple, Sequence

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

POWERSHELL: list[str] = [
    "powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
]


class Result(NamedTuple):
    returncode: int
    stdout: str
    stderr: str


def _decode(data) -> str:
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data or ""


def run(args: Sequence[str], timeout: int = 120) -> Result:
    try:
        cp = subprocess.run(list(args), capture_output=True, timeout=timeout,
                            creationflags=CREATE_NO_WINDOW)
        return Result(cp.returncode, _decode(cp.stdout), _decode(cp.stderr))
    except subprocess.TimeoutExpired:
        return Result(-1, "", f"Command timed out after {timeout}s")
    except OSError as exc:
        return Result(-1, "", str(exc))


def run_powershell(script: str, timeout: int = 300) -> Result:
    return run(POWERSHELL + [script], timeout=timeout)


def start_detached(args: Sequence[str]) -> int:
    proc = subprocess.Popen(list(args))
    return proc.pid
```

```python
# power_tool/core/tasks.py
import sys
import threading
from typing import Any, Callable, Optional


class BackgroundTask:
    def __init__(self, app, work: Callable[[], Any],
                 on_done: Callable[[Any], None],
                 on_error: Optional[Callable[[BaseException], None]] = None,
                 poll_ms: int = 100):
        self._app = app
        self._work = work
        self._on_done = on_done
        self._on_error = on_error
        self._poll_ms = poll_ms
        self._result: Any = None
        self._error: Optional[BaseException] = None
        self._done = False
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()
        self._app.after(self._poll_ms, self._poll)

    def _run(self) -> None:
        try:
            self._result = self._work()
        except BaseException as exc:
            self._error = exc
        finally:
            self._done = True

    def _poll(self) -> None:
        if not self._done:
            self._app.after(self._poll_ms, self._poll)
            return
        if self._error is not None:
            if self._on_error is not None:
                self._on_error(self._error)
            else:
                print(f"BackgroundTask failed: {self._error}", file=sys.stderr)
        else:
            self._on_done(self._result)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -t . -v` — **ask user for approval first**
Expected: `Ran 22 tests ... OK` (10 theme + 3 admin + 5 runner + 4 tasks)

- [ ] **Step 5: Commit (ask user for approval first)**

```bash
git add power_tool/core tests
git commit -m "feat: add admin check, safe command runner, background task helper"
```

---

### Task 3: Shared widgets (StatusPane, confirm, guard_admin, copy_text)

**Files:**
- Create: `power_tool/core/widgets.py`
- Test: `tests/test_widgets.py`

**Interfaces:**
- Consumes: `admin.is_admin()` (Task 2), ttk styles registered by `theme.apply_theme` (Task 1).
- Produces:
  - `widgets.StatusPane(parent) -> StatusPane` with methods `set_idle(text="Ready")`, `set_working(text="Working...")`, `set_success(text)`, `set_error(text)`; label text readable via `status._label.cget("text")` (tests) — expose a public `text()` getter too.
  - `widgets.confirm(parent, title, message) -> bool`
  - `widgets.guard_admin(status: StatusPane) -> bool` — True if elevated, else sets error status and returns False
  - `widgets.copy_text(widget, text) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_widgets.py
import unittest
import tkinter as tk
from unittest.mock import patch

from power_tool.core import theme, widgets


class StatusPaneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        theme.apply_theme(self.root, "dark")
        self.status = widgets.StatusPane(self.root)
        self.status.pack()

    def test_starts_idle_ready(self):
        self.assertEqual(self.status.text(), "Ready")

    def test_set_success_updates_text_and_style(self):
        self.status.set_success("All good")
        self.assertEqual(self.status.text(), "All good")

    def test_set_error_updates_text(self):
        self.status.set_error("Boom failed")
        self.assertEqual(self.status.text(), "Boom failed")

    def test_set_working_updates_text(self):
        self.status.set_working("Crunching")
        self.assertEqual(self.status.text(), "Crunching")


class GuardAdminTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        theme.apply_theme(self.root, "dark")
        self.status = widgets.StatusPane(self.root)

    def test_guard_passes_when_admin(self):
        with patch("power_tool.core.admin.is_admin", return_value=True):
            self.assertTrue(widgets.guard_admin(self.status))

    def test_guard_blocks_and_sets_error_when_not_admin(self):
        with patch("power_tool.core.admin.is_admin", return_value=False):
            self.assertFalse(widgets.guard_admin(self.status))
        self.assertIn("administrator", self.status.text().lower())


class CopyTextTests(unittest.TestCase):
    def test_copy_text_sets_clipboard(self):
        root = tk.Tk()
        root.withdraw()
        try:
            widgets.copy_text(root, "copied-value")
            self.assertEqual(root.clipboard_get(), "copied-value")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -t . -v` — **ask user for approval first**
Expected: FAIL — `ModuleNotFoundError: No module named 'power_tool.core.widgets'`

- [ ] **Step 3: Write the implementation**

```python
# power_tool/core/widgets.py
from tkinter import messagebox, ttk

from power_tool.core import admin


class StatusPane(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, style="Panel.TFrame", padding=(10, 8))
        self._label = ttk.Label(self, text="Ready", style="Idle.TLabel")
        self._label.pack(fill="x")

    def text(self) -> str:
        return str(self._label.cget("text"))

    def _show(self, text: str, style: str) -> None:
        self._label.configure(text=text, style=style)

    def set_idle(self, text: str = "Ready") -> None:
        self._show(text, "Idle.TLabel")

    def set_working(self, text: str = "Working...") -> None:
        self._show(text, "Working.TLabel")

    def set_success(self, text: str) -> None:
        self._show(text, "Success.TLabel")

    def set_error(self, text: str) -> None:
        self._show(text, "Error.TLabel")


def confirm(parent, title: str, message: str) -> bool:
    return messagebox.askyesno(title, message, icon="warning", parent=parent)


def guard_admin(status: StatusPane) -> bool:
    if admin.is_admin():
        return True
    status.set_error("Run as administrator required — restart the app as administrator.")
    return False


def copy_text(widget, text: str) -> None:
    widget.clipboard_clear()
    widget.clipboard_append(text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -t . -v` — **ask user for approval first**
Expected: `Ran 29 tests ... OK` (22 previous + 7 new)

- [ ] **Step 5: Commit (ask user for approval first)**

```bash
git add power_tool/core/widgets.py tests/test_widgets.py
git commit -m "feat: add status pane, confirm dialog, admin guard widgets"
```

---

### Task 4: App shell (sidebar, frame switching, theme toggle) + tool placeholders

**Files:**
- Create: `power_tool/main.py`
- Create: `power_tool/tools/usb_guard.py`, `power_tool/tools/speedup.py`, `power_tool/tools/log_collector.py`, `power_tool/tools/system_info.py` (placeholders)
- Modify: `power_tool/tools/__init__.py` (fill REGISTRY)
- Test: `tests/test_registry.py`

**Interfaces:**
- Consumes: `theme.load_theme_name/save_theme_name/apply_theme` (Task 1), `admin.is_admin()` (Task 2), `REGISTRY` convention.
- Produces:
  - Tool module contract for ALL later tasks: module exposes `create(parent: ttk.Frame) -> ttk.Frame`.
  - `tools.REGISTRY = [("Core", [(label, module), ...])]` — later plans append groups here.
  - `main.PowerToolApp(tk.Tk)` with `show_tool(key: str)`, `toggle_theme()`; `main.main()` starts the loop. Key = `module.__name__` (e.g. `"power_tool.tools.usb_guard"`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_registry.py
import unittest

from power_tool.tools import REGISTRY

EXPECTED_KEYS = [
    "power_tool.tools.usb_guard",
    "power_tool.tools.speedup",
    "power_tool.tools.log_collector",
    "power_tool.tools.system_info",
]


class RegistryTests(unittest.TestCase):
    def test_core_group_lists_four_tools_in_order(self):
        self.assertEqual(REGISTRY[0][0], "Core")
        keys = [module.__name__ for _, module in REGISTRY[0][1]]
        self.assertEqual(keys, EXPECTED_KEYS)

    def test_every_tool_exposes_create(self):
        for _, modules in REGISTRY:
            for label, module in modules:
                self.assertTrue(callable(getattr(module, "create", None)),
                                f"{label} missing create()")

    def test_tool_labels_are_human_readable(self):
        labels = [label for _, modules in REGISTRY for label, _ in modules]
        self.assertIn("USB Guard", labels)
        self.assertIn("Log Collector", labels)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s tests -t . -v` — **ask user for approval first**
Expected: FAIL — `IndexError: list index out of range` (REGISTRY empty)

- [ ] **Step 3: Write placeholders, registry, and the shell**

```python
# power_tool/tools/usb_guard.py
from tkinter import ttk


def create(parent: ttk.Frame) -> ttk.Frame:
    frame = ttk.Frame(parent, padding=16)
    ttk.Label(frame, text="USB Guard", style="Title.TLabel").pack(anchor="w")
    ttk.Label(frame, text="Coming soon.", style="Dim.TLabel").pack(anchor="w", pady=(6, 0))
    return frame
```

```python
# power_tool/tools/speedup.py
from tkinter import ttk


def create(parent: ttk.Frame) -> ttk.Frame:
    frame = ttk.Frame(parent, padding=16)
    ttk.Label(frame, text="Windows Speedup", style="Title.TLabel").pack(anchor="w")
    ttk.Label(frame, text="Coming soon.", style="Dim.TLabel").pack(anchor="w", pady=(6, 0))
    return frame
```

```python
# power_tool/tools/log_collector.py
from tkinter import ttk


def create(parent: ttk.Frame) -> ttk.Frame:
    frame = ttk.Frame(parent, padding=16)
    ttk.Label(frame, text="Log Collector", style="Title.TLabel").pack(anchor="w")
    ttk.Label(frame, text="Coming soon.", style="Dim.TLabel").pack(anchor="w", pady=(6, 0))
    return frame
```

```python
# power_tool/tools/system_info.py
from tkinter import ttk


def create(parent: ttk.Frame) -> ttk.Frame:
    frame = ttk.Frame(parent, padding=16)
    ttk.Label(frame, text="System Info", style="Title.TLabel").pack(anchor="w")
    ttk.Label(frame, text="Coming soon.", style="Dim.TLabel").pack(anchor="w", pady=(6, 0))
    return frame
```

```python
# power_tool/tools/__init__.py
from power_tool.tools import log_collector, speedup, system_info, usb_guard

REGISTRY: list = [
    ("Core", [
        ("USB Guard", usb_guard),
        ("Windows Speedup", speedup),
        ("Log Collector", log_collector),
        ("System Info", system_info),
    ]),
]
```

```python
# power_tool/main.py
import tkinter as tk
from tkinter import ttk

from power_tool.core import admin, theme
from power_tool.tools import REGISTRY


class PowerToolApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Windows Power Tool")
        self.geometry("1100x740")
        self.minsize(940, 620)
        self._theme_name = theme.load_theme_name()
        self._current_key: str | None = None
        self._tool_frames: dict[str, ttk.Frame] = {}
        self._sidebar_buttons: dict[str, ttk.Button] = {}
        self._modules = {module.__name__: module
                         for _, modules in REGISTRY for _, module in modules}
        self._build_topbar()
        self._build_body()
        theme.apply_theme(self, self._theme_name)
        self._theme_button.configure(
            text="Light mode" if self._theme_name == "dark" else "Dark mode")
        if self._modules:
            self.show_tool(next(iter(self._modules)))

    def _build_topbar(self) -> None:
        bar = ttk.Frame(self, style="Panel.TFrame", padding=(14, 8))
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        bar.grid_columnconfigure(1, weight=1)
        ttk.Label(bar, text="Windows Power Tool",
                  style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w")
        elevated = admin.is_admin()
        ttk.Label(
            bar,
            text="Running as Administrator" if elevated else "Not elevated",
            style="Success.TLabel" if elevated else "Error.TLabel",
        ).grid(row=0, column=2, padx=(0, 10))
        self._theme_button = ttk.Button(bar, text="Theme", command=self.toggle_theme)
        self._theme_button.grid(row=0, column=3)

    def _build_body(self) -> None:
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(1, weight=1)

        sidebar = ttk.Frame(self, style="Panel.TFrame", width=236, padding=(10, 12))
        sidebar.grid(row=1, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        self._content = ttk.Frame(self)
        self._content.grid(row=1, column=1, sticky="nsew")
        self._content.grid_rowconfigure(0, weight=1)
        self._content.grid_columnconfigure(0, weight=1)

        row = 0
        for group_name, modules in REGISTRY:
            ttk.Label(sidebar, text=group_name.upper(),
                      style="PanelDim.TLabel").grid(row=row, column=0,
                                                    sticky="w", pady=(12, 4))
            row += 1
            for label, module in modules:
                key = module.__name__
                button = ttk.Button(sidebar, text=label, style="Sidebar.TButton",
                                    command=lambda k=key: self.show_tool(k))
                button.grid(row=row, column=0, sticky="ew", pady=1)
                self._sidebar_buttons[key] = button
                row += 1

    def show_tool(self, key: str) -> None:
        if key == self._current_key:
            return
        if key not in self._tool_frames:
            frame = self._modules[key].create(self._content)
            frame.grid(row=0, column=0, sticky="nsew")
            frame.grid_remove()
            self._tool_frames[key] = frame
        for other_key, frame in self._tool_frames.items():
            if other_key != key:
                frame.grid_remove()
        self._tool_frames[key].grid()
        if self._current_key in self._sidebar_buttons:
            self._sidebar_buttons[self._current_key].configure(style="Sidebar.TButton")
        self._sidebar_buttons[key].configure(style="Active.Sidebar.TButton")
        self._current_key = key

    def toggle_theme(self) -> None:
        self._theme_name = "light" if self._theme_name == "dark" else "dark"
        theme.save_theme_name(self._theme_name)
        theme.apply_theme(self, self._theme_name)
        self._theme_button.configure(
            text="Light mode" if self._theme_name == "dark" else "Dark mode")


def main() -> None:
    app = PowerToolApp()
    app.mainloop()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -t . -v` — **ask user for approval first**
Expected: `Ran 32 tests ... OK`

- [ ] **Step 5: Manual smoke — ask user to run `python run.py` and report**

Expected: window opens with dark theme, sidebar shows 4 tools under CORE, clicking each shows its placeholder, theme toggle switches dark/light and persists across restart, top-right shows "Running as Administrator".

- [ ] **Step 6: Commit (ask user for approval first)**

```bash
git add power_tool/main.py power_tool/tools tests/test_registry.py
git commit -m "feat: app shell with sidebar navigation, theme toggle, admin badge"
```

---

### Task 5: USB Guard tool

**Files:**
- Modify: `power_tool/tools/usb_guard.py` (replace placeholder entirely)
- Test: `tests/test_usb_guard.py`

**Interfaces:**
- Consumes: `widgets.guard_admin`, `widgets.StatusPane`, `widgets.confirm` (Task 3), tool contract `create(parent) -> ttk.Frame` (Task 4).
- Produces:
  - `usb_guard.KEY_PATH = r"SYSTEM\CurrentControlSet\Services\USBSTOR"`
  - `usb_guard.VALUE_NAME = "Start"`, `usb_guard.ENABLED = 3`, `usb_guard.DISABLED = 4`
  - `usb_guard.read_state() -> int | None` (None if key/value unreadable)
  - `usb_guard.write_state(value: int) -> None` (raises OSError on failure)
  - `usb_guard.create(parent) -> ttk.Frame` — indicator + Disable/Enable buttons

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_usb_guard.py
import unittest
from unittest.mock import patch

from power_tool.tools import usb_guard


class FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class ReadStateTests(unittest.TestCase):
    @patch.object(usb_guard, "winreg")
    def test_read_state_returns_dword_value(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        fake_winreg.QueryValueEx.return_value = (4, 4)
        self.assertEqual(usb_guard.read_state(), 4)

    @patch.object(usb_guard, "winreg")
    def test_read_state_returns_none_when_key_missing(self, fake_winreg):
        fake_winreg.OpenKey.side_effect = FileNotFoundError("no key")
        self.assertIsNone(usb_guard.read_state())

    @patch.object(usb_guard, "winreg")
    def test_read_state_uses_64bit_view_and_hklm(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        fake_winreg.QueryValueEx.return_value = (3, 4)
        usb_guard.read_state()
        args = fake_winreg.OpenKey.call_args[0]
        self.assertEqual(args[0], fake_winreg.HKEY_LOCAL_MACHINE)
        self.assertEqual(args[1], usb_guard.KEY_PATH)
        self.assertEqual(args[2], 0)


class WriteStateTests(unittest.TestCase):
    @patch.object(usb_guard, "winreg")
    def test_write_state_disables(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        usb_guard.write_state(usb_guard.DISABLED)
        args = fake_winreg.SetValueEx.call_args[0]
        self.assertEqual(args[1], usb_guard.VALUE_NAME)
        self.assertEqual(args[4], 4)
        self.assertEqual(args[3], fake_winreg.REG_DWORD)

    @patch.object(usb_guard, "winreg")
    def test_write_state_enables(self, fake_winreg):
        fake_winreg.OpenKey.return_value = FakeKey()
        usb_guard.write_state(usb_guard.ENABLED)
        self.assertEqual(fake_winreg.SetValueEx.call_args[0][4], 3)

    @patch.object(usb_guard, "winreg")
    def test_write_state_propagates_oserror(self, fake_winreg):
        fake_winreg.OpenKey.side_effect = PermissionError("denied")
        with self.assertRaises(OSError):
            usb_guard.write_state(usb_guard.DISABLED)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -t . -v` — **ask user for approval first**
Expected: FAIL — `AttributeError: module 'power_tool.tools.usb_guard' has no attribute 'KEY_PATH'`

- [ ] **Step 3: Write the implementation**

```python
# power_tool/tools/usb_guard.py
import tkinter as tk
from tkinter import ttk

import winreg

from power_tool.core import widgets

KEY_PATH = r"SYSTEM\CurrentControlSet\Services\USBSTOR"
VALUE_NAME = "Start"
ENABLED = 3
DISABLED = 4
_READ_FLAGS = winreg.KEY_READ | winreg.KEY_WOW64_64KEY
_WRITE_FLAGS = winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY


def read_state() -> int | None:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, KEY_PATH, 0, _READ_FLAGS) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return int(value)
    except (OSError, ValueError):
        return None


def write_state(value: int) -> None:
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, KEY_PATH, 0, _WRITE_FLAGS) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_DWORD, value)


class UsbGuardFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=16)
        ttk.Label(self, text="USB Guard", style="Title.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(
            self, wraplength=660, style="Dim.TLabel",
            text="Disable USB storage drives so they still show in This PC but open "
                 "as Access Denied. Keyboards, mice, printers and network adapters "
                 "are not affected.",
        ).grid(row=1, column=0, sticky="w", pady=(6, 12))

        strip = ttk.Frame(self, style="Panel.TFrame", padding=12)
        strip.grid(row=2, column=0, sticky="ew")
        self._indicator = ttk.Label(strip, text="●", style="Idle.TLabel")
        self._indicator.pack(side="left")
        self._state_label = ttk.Label(strip, text="", style="Idle.TLabel")
        self._state_label.pack(side="left", padx=(8, 0))
        self.grid_columnconfigure(0, weight=1)

        buttons = ttk.Frame(self)
        buttons.grid(row=3, column=0, sticky="w", pady=(14, 4))
        ttk.Button(buttons, text="Disable USB Storage", style="Danger.TButton",
                   command=self._disable).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Enable USB Storage", style="Accent.TButton",
                   command=self._enable).pack(side="left")

        ttk.Label(
            self, wraplength=660, style="Dim.TLabel",
            text="Replug an already-connected drive after changing this setting. "
                 "No reboot needed.",
        ).grid(row=4, column=0, sticky="w", pady=(4, 12))

        self.status = widgets.StatusPane(self)
        self.status.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        self.refresh(silent=True)

    def refresh(self, silent: bool = False) -> None:
        state = read_state()
        if state is None:
            self._indicator.configure(style="Error.TLabel")
            self._state_label.configure(
                text="State unknown — USBSTOR registry key not found",
                style="Error.TLabel")
        elif state == DISABLED:
            self._indicator.configure(style="Error.TLabel")
            self._state_label.configure(text="USB storage: DISABLED",
                                        style="Error.TLabel")
            if not silent:
                self.status.set_success(
                    "USB storage disabled. Replug drives to apply.")
        elif state == ENABLED:
            self._indicator.configure(style="Success.TLabel")
            self._state_label.configure(text="USB storage: ENABLED",
                                        style="Success.TLabel")
            if not silent:
                self.status.set_success("USB storage enabled.")
        else:
            self._indicator.configure(style="Idle.TLabel")
            self._state_label.configure(
                text=f"USB storage: unexpected Start value {state}",
                style="Idle.TLabel")

    def _set(self, value: int) -> None:
        if not widgets.guard_admin(self.status):
            return
        try:
            write_state(value)
        except OSError as exc:
            self.status.set_error(f"Registry write failed: {exc}")
            self.refresh(silent=True)
            return
        self.refresh()

    def _disable(self) -> None:
        self._set(DISABLED)

    def _enable(self) -> None:
        self._set(ENABLED)


def create(parent: ttk.Frame) -> ttk.Frame:
    return UsbGuardFrame(parent)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -t . -v` — **ask user for approval first**
Expected: `Ran 38 tests ... OK`

- [ ] **Step 5: Manual test — ask user to run `python run.py`**

Expected: indicator shows **USB storage: ENABLED** (green) on a default system; Disable turns it red/DISABLED (a real USB drive plugged in beforehand shows Access Denied on double-click); Enable restores it; no console window ever flashes.

- [ ] **Step 6: Commit (ask user for approval first)**

```bash
git add power_tool/tools/usb_guard.py tests/test_usb_guard.py
git commit -m "feat: USB Guard tool with registry-backed enable/disable indicator"
```

---

### Task 6: Windows Speedup tool

**Files:**
- Modify: `power_tool/tools/speedup.py` (replace placeholder entirely)
- Test: `tests/test_speedup.py`

**Interfaces:**
- Consumes: `runner.run/start_detached`, `tasks.BackgroundTask`, `widgets.guard_admin/confirm/StatusPane` (Tasks 2–3), tool contract (Task 4).
- Produces:
  - `speedup.default_temp_targets(env: Mapping[str, str]) -> list[Path]` — exactly `%TEMP%`, `%WINDIR%\Temp`, Recent, Prefetch
  - `speedup.clear_directory(path: Path) -> tuple[int, int, int]` — (removed_items, freed_bytes, skipped); never raises
  - `speedup.chromium_profiles(user_data: Path) -> list[Path]` — profile dirs containing a `Preferences` file
  - `speedup.browser_cleanup_targets(browser: str, env: Mapping[str, str]) -> list[Path]` — browser in `{"Chrome", "Edge", "Firefox"}`
  - `speedup.remove_target(path: Path) -> tuple[bool, int]` — (removed, freed_bytes); missing path → (False, 0)
  - `speedup.is_process_running(image: str) -> bool`, `speedup.close_process(image: str) -> None`
  - `speedup.browser_launch_command(browser: str, env: Mapping[str, str]) -> list[str] | None`
  - `speedup.format_summary(removed: int, freed: int, skipped: int) -> str`
  - `speedup.create(parent) -> ttk.Frame`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_speedup.py
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from power_tool.tools import speedup


class TempTargetTests(unittest.TestCase):
    def test_exactly_four_expected_targets(self):
        env = {
            "TEMP": r"C:\Users\me\AppData\Local\Temp",
            "WINDIR": r"C:\Windows",
            "APPDATA": r"C:\Users\me\AppData\Roaming",
        }
        targets = speedup.default_temp_targets(env)
        self.assertEqual(len(targets), 4)
        self.assertEqual(targets[0], Path(env["TEMP"]))
        self.assertEqual(targets[1], Path(r"C:\Windows\Temp"))
        self.assertEqual(targets[2],
                         Path(env["APPDATA"]) / "Microsoft" / "Windows" / "Recent")
        self.assertEqual(targets[3], Path(r"C:\Windows\Prefetch"))


class ClearDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)

    def test_missing_directory_returns_zeros(self):
        self.assertEqual(speedup.clear_directory(self.path / "nope"), (0, 0, 0))

    def test_removes_files_and_counts_bytes(self):
        (self.path / "a.txt").write_text("x" * 100, encoding="utf-8")
        removed, freed, skipped = speedup.clear_directory(self.path)
        self.assertEqual((removed, freed, skipped), (1, 100, 0))
        self.assertFalse((self.path / "a.txt").exists())

    def test_removes_subdirectories(self):
        sub = self.path / "sub"
        sub.mkdir()
        (sub / "b.txt").write_text("y" * 50, encoding="utf-8")
        removed, freed, skipped = speedup.clear_directory(self.path)
        self.assertEqual((removed, freed, skipped), (1, 50, 0))

    def test_locked_file_is_skipped_not_raised(self):
        (self.path / "locked.txt").write_text("z" * 10, encoding="utf-8")
        with patch.object(Path, "unlink",
                          side_effect=PermissionError("in use")):
            removed, freed, skipped = speedup.clear_directory(self.path)
        self.assertEqual((removed, freed), (0, 0))
        self.assertEqual(skipped, 1)
        self.assertTrue((self.path / "locked.txt").exists())


class ChromiumProfilesTests(unittest.TestCase):
    def test_only_dirs_with_preferences_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            user_data = Path(tmp)
            (user_data / "Default").mkdir()
            (user_data / "Default" / "Preferences").write_text("{}", encoding="utf-8")
            (user_data / "Profile 1").mkdir()
            (user_data / "Profile 1" / "Preferences").write_text("{}", encoding="utf-8")
            (user_data / "System Profile").mkdir()
            profiles = speedup.chromium_profiles(user_data)
            names = sorted(p.name for p in profiles)
            self.assertEqual(names, ["Default", "Profile 1"])

    def test_missing_user_data_returns_empty(self):
        self.assertEqual(
            speedup.chromium_profiles(Path(r"C:\no\such\dir\here")), [])


class BrowserTargetTests(unittest.TestCase):
    def test_chrome_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            user_data = Path(tmp) / "User Data"
            default = user_data / "Default"
            default.mkdir(parents=True)
            (default / "Preferences").write_text("{}", encoding="utf-8")
            targets = speedup.browser_cleanup_targets(
                "Chrome", {"LOCALAPPDATA": tmp})
            names = {p.name for p in targets}
            self.assertIn("Cache", names)
            self.assertIn("Code Cache", names)
            self.assertIn("Service Worker", names)
            self.assertIn("Local Storage", names)
            self.assertIn("Cookies", names)
            for target in targets:
                self.assertIn("Default", str(target))
            self.assertNotIn("History", names)
            self.assertNotIn("Login Data", names)

    def test_firefox_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "Mozilla" / "Firefox" / "Profiles" / "abc.default"
            profile.mkdir(parents=True)
            targets = speedup.browser_cleanup_targets("Firefox", {"APPDATA": tmp})
            names = {p.name for p in targets}
            self.assertIn("cache2", names)
            self.assertIn("storage", names)
            self.assertIn("cookies.sqlite", names)
            self.assertNotIn("places.sqlite", names)  # history stays

    def test_missing_browser_dirs_return_empty(self):
        targets = speedup.browser_cleanup_targets(
            "Edge", {"LOCALAPPDATA": r"C:\no\such\dir"})
        self.assertEqual(targets, [])


class RemoveTargetTests(unittest.TestCase):
    def test_removes_file_with_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "Cookies"
            f.write_text("data", encoding="utf-8")
            removed, freed = speedup.remove_target(f)
            self.assertTrue(removed)
            self.assertEqual(freed, 4)

    def test_removes_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "Cache"
            d.mkdir()
            (d / "f").write_text("abc", encoding="utf-8")
            removed, freed = speedup.remove_target(d)
            self.assertTrue(removed)
            self.assertEqual(freed, 3)
            self.assertFalse(d.exists())

    def test_missing_path_returns_false_zero(self):
        self.assertEqual(speedup.remove_target(Path(r"C:\no\such\file")), (False, 0))


class SummaryTests(unittest.TestCase):
    def test_format_summary(self):
        text = speedup.format_summary(12, 5 * 1024 * 1024, 3)
        self.assertIn("12", text)
        self.assertIn("5.0 MB", text)
        self.assertIn("3", text)

    def test_format_summary_zero(self):
        text = speedup.format_summary(0, 0, 0)
        self.assertIn("0", text)


class LaunchCommandTests(unittest.TestCase):
    def test_chrome_finds_installed_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "Google" / "Chrome" / "Application" / "chrome.exe"
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"MZ")
            env = {"PROGRAMFILES": tmp, "PROGRAMFILES(X86)": r"C:\none",
                   "LOCALAPPDATA": r"C:\none"}
            cmd = speedup.browser_launch_command("Chrome", env)
            self.assertIsNotNone(cmd)
            self.assertEqual(cmd[0], str(exe))

    def test_returns_none_when_not_installed(self):
        env = {"PROGRAMFILES": r"C:\no\such", "PROGRAMFILES(X86)": r"C:\no\such2",
               "LOCALAPPDATA": r"C:\no\such3"}
        self.assertIsNone(speedup.browser_launch_command("Firefox", env))


class ProcessHelperTests(unittest.TestCase):
    @patch.object(speedup, "runner")
    def test_is_process_running_true(self, fake_runner):
        from power_tool.core.runner import Result
        fake_runner.run.return_value = Result(0, "chrome.exe", "")
        self.assertTrue(speedup.is_process_running("chrome.exe"))

    @patch.object(speedup, "runner")
    def test_is_process_running_false_when_no_tasks(self, fake_runner):
        from power_tool.core.runner import Result
        fake_runner.run.return_value = Result(0, "INFO: No tasks are running.", "")
        self.assertFalse(speedup.is_process_running("chrome.exe"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -t . -v` — **ask user for approval first**
Expected: FAIL — `AttributeError: module 'power_tool.tools.speedup' has no attribute 'default_temp_targets'`

- [ ] **Step 3: Write the implementation**

```python
# power_tool/tools/speedup.py
import os
import shutil
from pathlib import Path
from typing import Mapping

import tkinter as tk
from tkinter import ttk

from power_tool.core import runner, tasks, widgets

BROWSER_PROCESSES = {"Chrome": "chrome.exe", "Edge": "msedge.exe",
                     "Firefox": "firefox.exe"}


def default_temp_targets(env: Mapping[str, str]) -> list[Path]:
    windir = Path(env.get("WINDIR", r"C:\Windows"))
    appdata = Path(env.get("APPDATA", ""))
    return [
        Path(env.get("TEMP", "")),
        windir / "Temp",
        appdata / "Microsoft" / "Windows" / "Recent",
        windir / "Prefetch",
    ]


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
            targets += [
                profile / "cache2", profile / "storage", profile / "startupCache",
                profile / "cookies.sqlite", profile / "cookies.sqlite-wal",
                profile / "cookies.sqlite-shm",
            ]
        return targets
    if browser == "Chrome":
        user_data = Path(env.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
    else:
        user_data = Path(env.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "User Data"
    for profile in chromium_profiles(user_data):
        targets += [
            profile / "Cache", profile / "Code Cache", profile / "Service Worker",
            profile / "Local Storage", profile / "Network" / "Cookies",
            profile / "Network" / "Cookies-journal",
        ]
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


def is_process_running(image: str) -> bool:
    result = runner.run(["tasklist", "/FI", f"IMAGENAME eq {image}"], timeout=30)
    return result.returncode == 0 and "No tasks" not in result.stdout


def close_process(image: str) -> None:
    runner.run(["taskkill", "/IM", image, "/F"], timeout=30)


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
        if str(candidate) and candidate.exists():
            return [str(candidate)]
    return None


def format_summary(removed: int, freed: int, skipped: int) -> str:
    mb = freed / (1024 * 1024)
    return (f"Removed {removed} items · {mb:.1f} MB freed · "
            f"{skipped} skipped (locked or in use)")


class SpeedupFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=16)
        ttk.Label(self, text="Windows Speedup", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            self, wraplength=660, style="Dim.TLabel",
            text="Clears %TEMP%, Windows\\Temp, Recent and Prefetch, and optionally "
                 "cleans each browser's cache and cookies/site data (history, "
                 "passwords and settings are never touched).",
        ).pack(anchor="w", pady=(6, 12))

        browser_box = ttk.Labelframe(self, text="Browsers (cache + cookies/site data)",
                                     padding=10)
        browser_box.pack(anchor="w", pady=(0, 12))
        self._browser_vars: dict[str, tk.BooleanVar] = {}
        for browser in ("Firefox", "Chrome", "Edge"):
            var = tk.BooleanVar(value=False)
            self._browser_vars[browser] = var
            ttk.Checkbutton(browser_box, text=browser, variable=var).pack(
                side="left", padx=(0, 14))

        actions = ttk.Frame(self)
        actions.pack(anchor="w", pady=(0, 6))
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
        self._set_buttons_state("disabled")
        self.status.set_working(
            "Cleaning temp folders"
            + (f" and {', '.join(browsers)}" if browsers else "") + "...")
        tasks.BackgroundTask(
            self,
            work=lambda: self._work(browsers),
            on_done=lambda result: self._on_done(result, reboot),
            on_error=self._on_error,
        ).start()

    def _work(self, browsers: list[str]) -> dict:
        env = dict(os.environ)
        removed = freed = skipped = 0
        for target in default_temp_targets(env):
            r, f, s = clear_directory(target)
            removed += r
            freed += f
            skipped += s
        cleaned_browsers = []
        for browser in browsers:
            was_running = is_process_running(BROWSER_PROCESSES[browser])
            if was_running:
                close_process(BROWSER_PROCESSES[browser])
            for target in browser_cleanup_targets(browser, env):
                did_remove, size = remove_target(target)
                if did_remove:
                    removed += 1
                    freed += size
            cleaned_browsers.append(browser)
            if was_running:
                command = browser_launch_command(browser, env)
                if command:
                    try:
                        runner.start_detached(command)
                    except OSError:
                        pass
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


def create(parent: ttk.Frame) -> ttk.Frame:
    return SpeedupFrame(parent)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -t . -v` — **ask user for approval first**
Expected: `Ran 57 tests ... OK`

- [ ] **Step 5: Manual test — ask user to run `python run.py`**

Expected: Clean Temp Data fills status with item/MB/skipped summary without reboot; checked browsers (if running) close then reopen; Clean Temp & Reboot shows the 10s countdown in the status bar and the Cancel Reboot button — clicking it cancels (`shutdown /a` confirms) and status turns green "Reboot cancelled."; unchecking all browsers still cleans temp only.

- [ ] **Step 6: Commit (ask user for approval first)**

```bash
git add power_tool/tools/speedup.py tests/test_speedup.py
git commit -m "feat: Windows Speedup with temp cleanup, browser cache/cookies, 10s reboot countdown"
```

---

### Task 7: Log Collector tool

**Files:**
- Modify: `power_tool/tools/log_collector.py` (replace placeholder entirely)
- Test: `tests/test_log_collector.py`

**Interfaces:**
- Consumes: `runner.run/run_powershell`, `tasks.BackgroundTask`, `widgets.*` (Tasks 2–3), tool contract (Task 4).
- Produces:
  - `log_collector.LOGS = ["Application", "System", "Security", "Setup"]`
  - `log_collector.LEVELS = {"Critical": 1, "Error": 2, "Warning": 3, "Information": 4, "Verbose": 5}`
  - `log_collector.parse_minutes(text: str) -> int` — strips, requires positive int, raises `ValueError` otherwise
  - `log_collector.build_xpath(levels: list[int], minutes: int) -> str`
  - `log_collector.build_ps_query(logs: list[str], levels: list[int], minutes: int) -> str` — script ending in `$events` variable (event array)
  - `log_collector.build_text_script(logs, levels, minutes, out_path: Path) -> str` / `build_csv_script(...) -> str` — each ends with `Write-Output ('COLLECTED=' + $events.Count)`
  - `log_collector.parse_count(stdout: str) -> int`
  - `log_collector.collect_evtx(logs, levels, minutes, out_dir: Path) -> tuple[list[Path], list[str]]`
  - `log_collector.collect_text_csv(logs, levels, minutes, out_dir: Path, fmt: str) -> tuple[Path, int, str]` — fmt is `"txt"` or `"csv"`; returns (path, count, error_text)
  - `log_collector.default_output_dir(base: Path, now=None) -> Path` — `base / "Logs_yyyyMMdd_HHmmss"`
  - `log_collector.create(parent) -> ttk.Frame`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_log_collector.py
import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from power_tool.tools import log_collector


class ParseMinutesTests(unittest.TestCase):
    def test_strips_and_parses(self):
        self.assertEqual(log_collector.parse_minutes("  10 "), 10)

    def test_zero_rejected(self):
        with self.assertRaises(ValueError):
            log_collector.parse_minutes("0")

    def test_negative_rejected(self):
        with self.assertRaises(ValueError):
            log_collector.parse_minutes("-5")

    def test_text_rejected(self):
        with self.assertRaises(ValueError):
            log_collector.parse_minutes("ten")

    def test_float_rejected(self):
        with self.assertRaises(ValueError):
            log_collector.parse_minutes("10.5")

    def test_empty_rejected(self):
        with self.assertRaises(ValueError):
            log_collector.parse_minutes("")


class BuildXpathTests(unittest.TestCase):
    def test_single_level(self):
        xpath = log_collector.build_xpath([2], 10)
        self.assertEqual(
            xpath,
            "*[System[TimeCreated[timediff(@systemtime) <= 600000] and (Level=2)]]")

    def test_multiple_levels(self):
        xpath = log_collector.build_xpath([1, 2, 3], 60)
        self.assertIn("3600000", xpath)
        self.assertIn("(Level=1 or Level=2 or Level=3)", xpath)

    def test_minutes_conversion(self):
        xpath = log_collector.build_xpath([4], 1440)
        self.assertIn("86400000", xpath)


class BuildPsQueryTests(unittest.TestCase):
    def test_contains_logs_levels_and_starttime(self):
        script = log_collector.build_ps_query(["Application", "System"], [1, 2], 10)
        self.assertIn("'Application'", script)
        self.assertIn("'System'", script)
        self.assertIn("Get-WinEvent", script)
        self.assertIn("AddMinutes(-10)", script)
        self.assertIn("$levels = @(1,2)", script)

    def test_text_script_has_output_path_and_count(self):
        script = log_collector.build_text_script(
            ["Application"], [1], 5, Path(r"C:\out\events.txt"))
        self.assertIn(r"C:\out\events.txt", script)
        self.assertIn("COLLECTED=", script)
        self.assertIn("Format-List", script)

    def test_csv_script_uses_export_csv(self):
        script = log_collector.build_csv_script(
            ["System"], [2, 3], 15, Path(r"C:\out\events.csv"))
        self.assertIn("Export-Csv", script)
        self.assertIn(r"C:\out\events.csv", script)
        self.assertIn("COLLECTED=", script)


class ParseCountTests(unittest.TestCase):
    def test_extracts_count(self):
        self.assertEqual(log_collector.parse_count("noise\nCOLLECTED=42\n"), 42)

    def test_missing_count_returns_zero(self):
        self.assertEqual(log_collector.parse_count("no marker here"), 0)


class DefaultOutputDirTests(unittest.TestCase):
    def test_timestamped_name(self):
        now = datetime.datetime(2026, 9, 30, 14, 5, 9)
        path = log_collector.default_output_dir(Path(r"C:\Users\me\Desktop"), now)
        self.assertEqual(path.name, "Logs_20260930_140509")
        self.assertEqual(path.parent, Path(r"C:\Users\me\Desktop"))


class CollectEvtxTests(unittest.TestCase):
    @patch.object(log_collector, "runner")
    def test_builds_wevtutil_command_per_log(self, fake_runner):
        from power_tool.core.runner import Result
        fake_runner.run.return_value = Result(0, "", "")
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            paths, errors = log_collector.collect_evtx(
                ["Application", "System"], [1, 2], 10, out_dir)
        self.assertEqual(errors, [])
        self.assertEqual(len(paths), 2)
        self.assertEqual(paths[0].name, "Application.evtx")
        calls = fake_runner.run.call_args_list
        first_args = calls[0][0][0]
        self.assertEqual(first_args[0], "wevtutil")
        self.assertEqual(first_args[1], "epl")
        self.assertEqual(first_args[2], "Application")
        self.assertTrue(any(arg.startswith("/q:*[System") for arg in first_args))

    @patch.object(log_collector, "runner")
    def test_collects_errors_from_failed_logs(self, fake_runner):
        from power_tool.core.runner import Result
        fake_runner.run.return_value = Result(1, "", "Access denied")
        with tempfile.TemporaryDirectory() as tmp:
            paths, errors = log_collector.collect_evtx(["Security"], [1], 10,
                                                       Path(tmp))
        self.assertEqual(paths, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("Access denied", errors[0])


class CollectTextCsvTests(unittest.TestCase):
    @patch.object(log_collector, "runner")
    def test_txt_collects_count(self, fake_runner):
        from power_tool.core.runner import Result
        fake_runner.run_powershell.return_value = Result(0, "COLLECTED=7\n", "")
        with tempfile.TemporaryDirectory() as tmp:
            path, count, error = log_collector.collect_text_csv(
                ["Application"], [1, 2, 3], 10, Path(tmp), "txt")
        self.assertEqual(path.name, "events.txt")
        self.assertEqual(count, 7)
        self.assertEqual(error, "")
        self.assertTrue(path.exists())

    @patch.object(log_collector, "runner")
    def test_csv_returns_error_on_failure(self, fake_runner):
        from power_tool.core.runner import Result
        fake_runner.run_powershell.return_value = Result(1, "", "boom")
        with tempfile.TemporaryDirectory() as tmp:
            path, count, error = log_collector.collect_text_csv(
                ["System"], [1], 10, Path(tmp), "csv")
        self.assertEqual(count, 0)
        self.assertIn("boom", error)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -t . -v` — **ask user for approval first**
Expected: FAIL — `AttributeError: module 'power_tool.tools.log_collector' has no attribute 'parse_minutes'`

- [ ] **Step 3: Write the implementation**

```python
# power_tool/tools/log_collector.py
import datetime
import re
from pathlib import Path
from typing import Sequence

import tkinter as tk
from tkinter import filedialog, ttk

from power_tool.core import runner, tasks, widgets

LOGS = ["Application", "System", "Security", "Setup"]
LEVELS = {"Critical": 1, "Error": 2, "Warning": 3, "Information": 4, "Verbose": 5}
FORMATS = {"Text (.txt)": "txt", "CSV (.csv)": "csv", "Native EVTX (.evtx)": "evtx"}


def parse_minutes(text: str) -> int:
    stripped = text.strip()
    if not stripped.isdigit():
        raise ValueError("minutes must be a whole number")
    minutes = int(stripped)
    if minutes <= 0:
        raise ValueError("minutes must be greater than zero")
    return minutes


def build_xpath(levels: Sequence[int], minutes: int) -> str:
    milliseconds = minutes * 60 * 1000
    level_clause = ""
    if levels:
        level_clause = " and (" + " or ".join(f"Level={n}" for n in levels) + ")"
    return (f"*[System[TimeCreated[timediff(@systemtime) <= {milliseconds}]"
            f"{level_clause}]]")


def build_ps_query(logs: Sequence[str], levels: Sequence[int], minutes: int) -> str:
    logs_ps = ",".join(f"'{name}'" for name in logs)
    levels_ps = ",".join(str(n) for n in levels)
    return (
        f"$logs = @({logs_ps}); "
        f"$levels = @({levels_ps}); "
        f"$start = (Get-Date).AddMinutes(-{minutes}); "
        "$events = @(Get-WinEvent -FilterHashtable "
        "@{LogName=$logs; Level=$levels; StartTime=$start} "
        "-ErrorAction SilentlyContinue); "
    )


def build_text_script(logs, levels, minutes, out_path: Path) -> str:
    return (build_ps_query(logs, levels, minutes)
            + f"$events | Format-List * | Out-File -FilePath '{out_path}' "
              "-Encoding utf8; "
            + "Write-Output ('COLLECTED=' + $events.Count)")


def build_csv_script(logs, levels, minutes, out_path: Path) -> str:
    return (build_ps_query(logs, levels, minutes)
            + "$events | Select-Object TimeCreated, Id, LevelDisplayName, "
              f"ProviderName, LogName, Message | Export-Csv -FilePath '{out_path}' "
              "-NoTypeInformation -Encoding UTF8; "
            + "Write-Output ('COLLECTED=' + $events.Count)")


def parse_count(stdout: str) -> int:
    match = re.search(r"COLLECTED=(\d+)", stdout)
    return int(match.group(1)) if match else 0


def default_output_dir(base: Path, now: datetime.datetime | None = None) -> Path:
    stamp = (now or datetime.datetime.now()).strftime("%Y%m%d_%H%M%S")
    return Path(base) / f"Logs_{stamp}"


def collect_evtx(logs: Sequence[str], levels: Sequence[int], minutes: int,
                 out_dir: Path) -> tuple[list[Path], list[str]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    xpath = build_xpath(levels, minutes)
    paths: list[Path] = []
    errors: list[str] = []
    for log in logs:
        dest = out_dir / f"{log}.evtx"
        result = runner.run(["wevtutil", "epl", log, str(dest), f"/q:{xpath}",
                             "/ow:true"], timeout=300)
        if result.returncode == 0:
            paths.append(dest)
        else:
            detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
            errors.append(f"{log}: {detail}")
    return paths, errors


def collect_text_csv(logs: Sequence[str], levels: Sequence[int], minutes: int,
                     out_dir: Path, fmt: str) -> tuple[Path, int, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / ("events.csv" if fmt == "csv" else "events.txt")
    out_path.write_text("", encoding="utf-8")
    if fmt == "csv":
        script = build_csv_script(logs, levels, minutes, out_path)
    else:
        script = build_text_script(logs, levels, minutes, out_path)
    result = runner.run_powershell(script, timeout=600)
    if result.returncode != 0:
        return out_path, 0, result.stderr.strip() or result.stdout.strip()
    return out_path, parse_count(result.stdout), ""


class LogCollectorFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=16)
        ttk.Label(self, text="Log Collector", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            self, wraplength=660, style="Dim.TLabel",
            text="Collect Windows Event Viewer logs for the last N minutes, filtered "
                 "by level, as a report or a native EVTX file.",
        ).pack(anchor="w", pady=(6, 12))

        logs_box = ttk.Labelframe(self, text="Logs", padding=10)
        logs_box.pack(anchor="w", pady=(0, 10))
        self._log_vars: dict[str, tk.BooleanVar] = {}
        for name in LOGS:
            var = tk.BooleanVar(value=(name in ("Application", "System")))
            self._log_vars[name] = var
            ttk.Checkbutton(logs_box, text=name, variable=var).pack(
                side="left", padx=(0, 12))

        levels_box = ttk.Labelframe(self, text="Levels", padding=10)
        levels_box.pack(anchor="w", pady=(0, 10))
        self._level_vars: dict[str, tk.BooleanVar] = {}
        for name in LEVELS:
            var = tk.BooleanVar(value=(name in ("Critical", "Error", "Warning")))
            self._level_vars[name] = var
            ttk.Checkbutton(levels_box, text=name, variable=var).pack(
                side="left", padx=(0, 12))

        time_row = ttk.Frame(self)
        time_row.pack(anchor="w", pady=(0, 10))
        ttk.Label(time_row, text="Time frame:").pack(side="left")
        self._minutes_var = tk.StringVar(value="10")
        minutes_entry = ttk.Entry(time_row, textvariable=self._minutes_var, width=8)
        minutes_entry.pack(side="left", padx=(6, 4))
        ttk.Label(time_row, text="minutes").pack(side="left")
        for preset in (10, 30, 60, 1440):
            ttk.Button(
                time_row, text=str(preset),
                command=lambda p=preset: self._minutes_var.set(str(p)),
            ).pack(side="left", padx=(6, 0))

        format_row = ttk.Frame(self)
        format_row.pack(anchor="w", pady=(0, 10))
        ttk.Label(format_row, text="Format:").pack(side="left")
        self._format_var = tk.StringVar(value="Text (.txt)")
        for label in FORMATS:
            ttk.Radiobutton(format_row, text=label, value=label,
                            variable=self._format_var).pack(side="left",
                                                             padx=(8, 0))

        dest_row = ttk.Frame(self)
        dest_row.pack(anchor="w", fill="x", pady=(0, 10))
        ttk.Label(dest_row, text="Save to:").pack(side="left")
        desktop = Path.home() / "Desktop"
        self._dest_var = tk.StringVar(value=str(default_output_dir(desktop)))
        ttk.Entry(dest_row, textvariable=self._dest_var).pack(
            side="left", fill="x", expand=True, padx=6)
        ttk.Button(dest_row, text="Browse", command=self._browse).pack(side="left")

        self._collect_button = ttk.Button(
            self, text="Collect Logs", style="Accent.TButton", command=self._start)
        self._collect_button.pack(anchor="w")

        self.status = widgets.StatusPane(self)
        self.status.pack(fill="x", pady=(12, 0))

    def _browse(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self._dest_var.get(),
                                         parent=self)
        if chosen:
            self._dest_var.set(chosen)

    def _gather_input(self) -> dict:
        logs = [name for name, var in self._log_vars.items() if var.get()]
        if not logs:
            raise ValueError("select at least one log")
        levels = [LEVELS[name] for name, var in self._level_vars.items() if var.get()]
        if not levels:
            raise ValueError("select at least one level")
        minutes = parse_minutes(self._minutes_var.get())
        fmt = FORMATS[self._format_var.get()]
        raw_dest = self._dest_var.get().strip()
        if not raw_dest:
            raise ValueError("choose a destination folder")
        out_dir = Path(raw_dest)
        return {"logs": logs, "levels": levels, "minutes": minutes,
                "fmt": fmt, "out_dir": out_dir}

    def _start(self) -> None:
        if not widgets.guard_admin(self.status):
            return
        try:
            config = self._gather_input()
        except ValueError as exc:
            self.status.set_error(str(exc))
            return
        self._collect_button.configure(state="disabled")
        self.status.set_working(
            f"Collecting last {config['minutes']} minutes from "
            f"{', '.join(config['logs'])}...")
        tasks.BackgroundTask(
            self,
            work=lambda: self._work(config),
            on_done=self._on_done,
            on_error=self._on_error,
        ).start()

    def _work(self, config: dict) -> dict:
        if config["fmt"] == "evtx":
            paths, errors = collect_evtx(config["logs"], config["levels"],
                                         config["minutes"], config["out_dir"])
            return {"paths": [str(p) for p in paths], "count": None,
                    "errors": errors}
        path, count, error = collect_text_csv(
            config["logs"], config["levels"], config["minutes"],
            config["out_dir"], config["fmt"])
        errors = [error] if error else []
        return {"paths": [str(path)], "count": count, "errors": errors}

    def _on_done(self, result: dict) -> None:
        self._collect_button.configure(state="normal")
        if result["errors"]:
            self.status.set_error(" | ".join(result["errors"]))
            return
        files = ", ".join(result["paths"])
        if result["count"] is None:
            self.status.set_success(f"EVTX export complete: {files}")
        else:
            self.status.set_success(
                f"Collected {result['count']} events → {files}")

    def _on_error(self, exc: BaseException) -> None:
        self._collect_button.configure(state="normal")
        self.status.set_error(f"Collection failed: {exc}")


def create(parent: ttk.Frame) -> ttk.Frame:
    return LogCollectorFrame(parent)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -t . -v` — **ask user for approval first**
Expected: `Ran 76 tests ... OK`

- [ ] **Step 5: Manual test — ask user to run `python run.py`**

Expected: with no checkboxes ticked → red "select at least one log"; minutes "abc" → red error; Text format over last 10 minutes → green "Collected N events → C:\Users\...\Desktop\Logs_...\events.txt"; EVTX format produces `Application.evtx`/`System.evtx` that opens in Event Viewer; presets 10/30/60/1440 fill the box; Browse changes destination.

- [ ] **Step 6: Commit (ask user for approval first)**

```bash
git add power_tool/tools/log_collector.py tests/test_log_collector.py
git commit -m "feat: Log Collector with log/level filters, minutes window, txt/csv/evtx output"
```

---

### Task 8: System Info tool

**Files:**
- Modify: `power_tool/tools/system_info.py` (replace placeholder entirely)
- Test: `tests/test_system_info.py`

**Interfaces:**
- Consumes: `runner.run_powershell`, `tasks.BackgroundTask`, `widgets.*`, `theme.observe/current_palette` (Tasks 1–3), tool contract (Task 4).
- Produces:
  - `system_info.COLLECT_SCRIPT: str` — single PowerShell script printing one JSON object
  - `system_info.parse_report(stdout: str) -> dict` — `json.loads`, raises `ValueError` on garbage
  - `system_info.format_report(data: dict) -> str` — human-readable multi-section text
  - `system_info.gather() -> dict` — runs the script (300s timeout), raises `RuntimeError` on failure
  - `system_info.create(parent) -> ttk.Frame`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_system_info.py
import json
import unittest

from power_tool.tools import system_info

FIXTURE = {
    "hostname": "DESKTOP-TEST01",
    "generated": "2026-09-30 14:05:09",
    "os": {"caption": "Microsoft Windows 11 Pro", "version": "10.0.26100",
           "build": "26100", "arch": "64-bit"},
    "hardware": {"manufacturer": "Dell Inc.", "model": "Latitude 5440",
                 "totalRam": 17179869184},
    "cpu": [{"name": "Intel Core i7-1355U", "cores": 10, "logical": 12}],
    "ram": [{"slot": "DIMM A", "size": 8589934592, "speed": 3200,
             "maker": "Samsung"}],
    "network": [{"interface": "Ethernet", "mac": "AA:BB:CC:DD:EE:FF",
                 "ipv4": ["192.168.1.50"], "ipv6": ["fe80::1"]}],
    "disks": [{"device": "C:", "label": "Windows", "fs": "NTFS",
               "total": 512110190592, "free": 107374182400, "type": "Fixed"}],
    "users": [{"name": "admin", "full": "Local Admin", "enabled": True,
               "groups": ["Administrators"]},
              {"name": "guest1", "full": "", "enabled": False, "groups": ["Users"]}],
    "boot": "2026-09-30T08:00:00",
}


class ParseReportTests(unittest.TestCase):
    def test_parses_json(self):
        data = system_info.parse_report(json.dumps(FIXTURE))
        self.assertEqual(data["hostname"], "DESKTOP-TEST01")

    def test_rejects_garbage(self):
        with self.assertRaises(ValueError):
            system_info.parse_report("powershell noise not json")


class FormatReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = system_info.format_report(FIXTURE)

    def test_contains_hostname(self):
        self.assertIn("DESKTOP-TEST01", self.text)

    def test_contains_os_and_model(self):
        self.assertIn("Microsoft Windows 11 Pro", self.text)
        self.assertIn("Latitude 5440", self.text)

    def test_contains_cpu_and_ram(self):
        self.assertIn("Intel Core i7-1355U", self.text)
        self.assertIn("16.0 GB", self.text)

    def test_contains_ip_and_mac(self):
        self.assertIn("192.168.1.50", self.text)
        self.assertIn("AA:BB:CC:DD:EE:FF", self.text)

    def test_contains_users_with_groups(self):
        self.assertIn("admin", self.text)
        self.assertIn("Administrators", self.text)
        self.assertIn("guest1", self.text)
        self.assertIn("disabled", self.text.lower())

    def test_contains_disk_with_free_space(self):
        self.assertIn("C:", self.text)
        self.assertIn("NTFS", self.text)

    def test_size_formatting(self):
        self.assertIn("476.9 GB", self.text)      # total disk
        self.assertIn("10.0 GB", self.text)       # free
        self.assertIn("8.0 GB", self.text)        # dimm


class FormatUptimeTests(unittest.TestCase):
    def test_formats_uptime(self):
        text = system_info.format_uptime("2026-09-30T08:00:00",
                                         "2026-09-30T14:05:09")
        self.assertIn("6h", text)
        self.assertIn("5m", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -t . -v` — **ask user for approval first**
Expected: FAIL — `AttributeError: module 'power_tool.tools.system_info' has no attribute 'parse_report'`

- [ ] **Step 3: Write the implementation**

```python
# power_tool/tools/system_info.py
import json
from datetime import datetime
from typing import Mapping

import tkinter as tk
from tkinter import ttk

from power_tool.core import runner, tasks, theme, widgets

COLLECT_SCRIPT = r"""
$os = Get-CimInstance Win32_OperatingSystem
$cs = Get-CimInstance Win32_ComputerSystem
$cpu = @(Get-CimInstance Win32_Processor | ForEach-Object {
  [ordered]@{ name = $_.Name; cores = $_.NumberOfCores; logical = $_.NumberOfLogicalProcessors }
})
$ram = @(Get-CimInstance Win32_PhysicalMemory | ForEach-Object {
  [ordered]@{ slot = $_.DeviceLocator; size = [int64]$_.Capacity; speed = $_.Speed; maker = $_.Manufacturer }
})
$network = @(Get-NetIPConfiguration | Where-Object { $_.NetAdapter } | ForEach-Object {
  [ordered]@{
    interface = $_.InterfaceAlias
    mac       = $_.NetAdapter.MacAddress
    ipv4      = @($_.IPv4Address | ForEach-Object { $_.IPAddress })
    ipv6      = @($_.IPv6Address | ForEach-Object { $_.IPAddress })
  }
})
$disks = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=2 or DriveType=3' | ForEach-Object {
  [ordered]@{
    device = $_.DeviceID
    label  = $_.VolumeName
    fs     = $_.FileSystem
    total  = [int64]$_.Size
    free   = [int64]$_.FreeSpace
    type   = if ($_.DriveType -eq 2) { 'Removable' } else { 'Fixed' }
  }
})
$users = @(Get-LocalUser | ForEach-Object {
  $u = $_
  $groups = @()
  foreach ($g in Get-LocalGroup) {
    try { Get-LocalGroupMember -Group $g.Name -Member $u.Name -ErrorAction Stop | Out-Null
          $groups += $g.Name } catch {}
  }
  [ordered]@{ name = $u.Name; full = $u.FullName; enabled = [bool]$u.Enabled; groups = @($groups) }
})
$result = [ordered]@{
  hostname  = $env:COMPUTERNAME
  generated = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
  os        = [ordered]@{ caption = $os.Caption; version = $os.Version; build = $os.BuildNumber; arch = $os.OSArchitecture }
  hardware  = [ordered]@{ manufacturer = $cs.Manufacturer; model = $cs.Model; totalRam = [int64]$cs.TotalPhysicalMemory }
  cpu       = $cpu
  ram       = $ram
  network   = $network
  disks     = $disks
  users     = $users
  boot      = $os.LastBootUpTime.ToString('yyyy-MM-ddTHH:mm:ss')
}
ConvertTo-Json -InputObject $result -Depth 6 -Compress
"""


def parse_report(stdout: str) -> dict:
    try:
        data = json.loads(stdout)
    except ValueError as exc:
        raise ValueError(f"unexpected PowerShell output: {stdout[:200]}") from exc
    if not isinstance(data, dict):
        raise ValueError("report JSON is not an object")
    return data


def _gb(num_bytes) -> str:
    if not num_bytes:
        return "0 B"
    return f"{num_bytes / (1024 ** 3):.1f} GB"


def format_uptime(boot: str, now: str) -> str:
    boot_dt = datetime.fromisoformat(boot)
    now_dt = datetime.fromisoformat(now)
    delta = now_dt - boot_dt
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes}m"


def format_report(data: Mapping) -> str:
    lines: list[str] = []
    lines.append("=" * 62)
    lines.append(f"SYSTEM INFO — {data.get('hostname', '?')}")
    lines.append(f"Generated: {data.get('generated', '?')}")
    lines.append("=" * 62)

    os_info = data.get("os", {})
    lines.append("")
    lines.append("--- Operating System ---")
    lines.append(f"  Edition : {os_info.get('caption', '?')}")
    lines.append(f"  Version : {os_info.get('version', '?')} (build {os_info.get('build', '?')})")
    lines.append(f"  Arch    : {os_info.get('arch', '?')}")

    boot = data.get("boot")
    if boot:
        try:
            uptime = format_uptime(boot, str(datetime.now().replace(microsecond=0)))
        except ValueError:
            uptime = "unknown"
        lines.append(f"  Booted  : {boot.replace('T', ' ')} (up {uptime})")

    hw = data.get("hardware", {})
    lines.append("")
    lines.append("--- Hardware ---")
    lines.append(f"  Model   : {hw.get('manufacturer', '?')} {hw.get('model', '')}")
    lines.append(f"  RAM     : {_gb(hw.get('totalRam'))} total")
    for module in data.get("ram", []):
        lines.append(f"    - {module.get('slot', '?')}: {_gb(module.get('size'))} "
                     f"{module.get('speed', '?')} MHz ({module.get('maker', '?')})")
    for cpu in data.get("cpu", []):
        lines.append(f"  CPU     : {cpu.get('name', '?')}")
        lines.append(f"            {cpu.get('cores', '?')} cores / "
                     f"{cpu.get('logical', '?')} logical")

    lines.append("")
    lines.append("--- Network ---")
    for iface in data.get("network", []):
        lines.append(f"  {iface.get('interface', '?')}  [{iface.get('mac', '?')}]")
        for ip in iface.get("ipv4", []) or []:
            lines.append(f"    IPv4 : {ip}")
        for ip in iface.get("ipv6", []) or []:
            lines.append(f"    IPv6 : {ip}")

    lines.append("")
    lines.append("--- Storage ---")
    for disk in data.get("disks", []):
        total = disk.get("total") or 0
        free = disk.get("free") or 0
        pct = (free / total * 100) if total else 0.0
        lines.append(f"  {disk.get('device', '?')} {disk.get('label', '')} "
                     f"({disk.get('type', '?')}, {disk.get('fs', '?')}) "
                     f"— {_gb(total)} total, {_gb(free)} free ({pct:.0f}%)")

    lines.append("")
    lines.append("--- Local Users ---")
    for user in data.get("users", []):
        state = "enabled" if user.get("enabled") else "disabled"
        groups = ", ".join(user.get("groups", []) or []) or "none"
        full = user.get("full") or ""
        name = user.get("name", "?")
        lines.append(f"  {name}{f' ({full})' if full else ''} — {state} — {groups}")

    lines.append("")
    return "\n".join(lines)


def gather() -> dict:
    result = runner.run_powershell(COLLECT_SCRIPT, timeout=300)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(f"PowerShell failed: {detail}")
    return parse_report(result.stdout)


class SystemInfoFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=16)
        ttk.Label(self, text="System Info", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            self, wraplength=660, style="Dim.TLabel",
            text="Hostname, OS, network interfaces, users and groups, hardware, "
                 "storage (including removable) and uptime.",
        ).pack(anchor="w", pady=(6, 12))

        buttons = ttk.Frame(self)
        buttons.pack(anchor="w", pady=(0, 10))
        self._show_button = ttk.Button(
            buttons, text="Show System Info", style="Accent.TButton",
            command=self._start)
        self._show_button.pack(side="left", padx=(0, 8))
        self._copy_button = ttk.Button(buttons, text="Copy to Clipboard",
                                       state="disabled", command=self._copy)
        self._copy_button.pack(side="left", padx=(0, 8))
        self._save_button = ttk.Button(buttons, text="Save as TXT",
                                       state="disabled", command=self._save)
        self._save_button.pack(side="left")

        palette = theme.current_palette()
        self._output = tk.Text(
            self, wrap="none", height=26, font=("Consolas", 10),
            bg=palette["entry_bg"], fg=palette["fg"], insertbackground=palette["fg"],
            relief="flat", padx=10, pady=8, state="disabled")
        self._output.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(self, command=self._output.yview)
        self._output.configure(yscrollcommand=scroll.set)
        theme.observe(self._on_theme)

        self.status = widgets.StatusPane(self)
        self.status.pack(fill="x", pady=(10, 0))
        self._report_text = ""

    def _on_theme(self, palette: dict) -> None:
        self._output.configure(bg=palette["entry_bg"], fg=palette["fg"],
                               insertbackground=palette["fg"])

    def _start(self) -> None:
        if not widgets.guard_admin(self.status):
            return
        self._show_button.configure(state="disabled")
        self.status.set_working("Collecting system information...")
        tasks.BackgroundTask(self, work=gather, on_done=self._on_done,
                             on_error=self._on_error).start()

    def _on_done(self, data: dict) -> None:
        try:
            self._report_text = format_report(data)
        except Exception as exc:
            self._show_button.configure(state="normal")
            self.status.set_error(f"Formatting failed: {exc}")
            return
        self._output.configure(state="normal")
        self._output.delete("1.0", "end")
        self._output.insert("1.0", self._report_text)
        self._output.configure(state="disabled")
        self._show_button.configure(state="normal")
        self._copy_button.configure(state="normal")
        self._save_button.configure(state="normal")
        self.status.set_success("System information collected.")

    def _on_error(self, exc: BaseException) -> None:
        self._show_button.configure(state="normal")
        self.status.set_error(f"Collection failed: {exc}")

    def _copy(self) -> None:
        widgets.copy_text(self, self._report_text)
        self.status.set_success("Report copied to clipboard.")

    def _save(self) -> None:
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".txt",
            filetypes=[("Text files", "*.txt")],
            initialfile="system_info.txt")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self._report_text)
        except OSError as exc:
            self.status.set_error(f"Save failed: {exc}")
            return
        self.status.set_success(f"Saved to {path}")


def create(parent: ttk.Frame) -> ttk.Frame:
    return SystemInfoFrame(parent)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -t . -v` — **ask user for approval first**
Expected: `Ran 87 tests ... OK`

- [ ] **Step 5: Manual test — ask user to run `python run.py`**

Expected: Show System Info fills the pane with all sections (network incl. IPv6, users with Administrators/Users groups, RAM modules, external drives listed as Removable); Copy puts text on clipboard; Save writes a .txt; theme toggle recolors the text pane.

- [ ] **Step 6: Commit (ask user for approval first)**

```bash
git add power_tool/tools/system_info.py tests/test_system_info.py
git commit -m "feat: System Info collector with formatted hardware/network/user report"
```

---

### Task 9: Repo docs — README, .gitignore, requirements, manual test checklist

**Files:**
- Create: `README.md`, `.gitignore`, `requirements.txt`, `docs/manual-test-checklist.md`

**Interfaces:**
- Consumes: nothing (docs only).
- Produces: documentation reflecting the four implemented tools; checklist reused for every future plan.

- [ ] **Step 1: Write `.gitignore`**

```
build/
dist/
__pycache__/
*.pyc
.venv/
*.log
```

- [ ] **Step 2: Write `requirements.txt`**

```
# Dev/build dependency only — the app itself uses only the Python standard library.
pyinstaller>=6.0
```

- [ ] **Step 3: Write `README.md`**

```markdown
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
```

- [ ] **Step 4: Write `docs/manual-test-checklist.md`**

```markdown
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
```

- [ ] **Step 5: Commit (ask user for approval first)**

```bash
git add README.md .gitignore requirements.txt docs/manual-test-checklist.md
git commit -m "docs: add README, gitignore, requirements, manual test checklist"
```

---

### Task 10: PyInstaller build → portable exe

**Files:**
- Create: `build.spec`

**Interfaces:**
- Consumes: `run.py` (Task 1).
- Produces: `dist/WindowsPowerTool.exe` — onefile, windowed, `uac_admin`.

- [ ] **Step 1: Write `build.spec`**

```python
# build.spec — run with: pyinstaller --noconfirm build.spec
from PyInstaller.utils.hooks import collect_submodules

hidden_imports = collect_submodules("power_tool")

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="WindowsPowerTool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
)
```

- [ ] **Step 2: Build — ask user for approval, then run**

Run: `pyinstaller --noconfirm build.spec` — **ask user for approval first**
Expected: `Building EXE from EXE-0.toc... completed successfully` and `dist\WindowsPowerTool.exe` exists (~15–20 MB, near the size of your existing exes).

- [ ] **Step 3: User smoke test**

Ask the user to run `dist\WindowsPowerTool.exe` and confirm:
- UAC prompt appears; app opens elevated with the admin badge
- All four tools work identically to the source version
- Theme toggle persists across exe restarts
- No `dist\build` artifacts or console windows visible

- [ ] **Step 4: Commit (ask user for approval first)**

```bash
git add build.spec
git commit -m "build: add PyInstaller spec for portable elevated exe"
```

---

## Plan 1 Completion Gate

Before moving to Plan 2 (admin extras: Network, Installed Apps, Users & Groups, Processes, Services, Disk & Cleanup, Restore Point, License Info):

1. `python -m unittest discover -s tests -t . -v` → all OK (run only with user approval)
2. Every box in `docs/manual-test-checklist.md` checked by the user
3. `dist\WindowsPowerTool.exe` built and smoke-tested by the user

