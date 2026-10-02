import csv
import shlex
import tkinter as tk
import winreg
from tkinter import filedialog, ttk

from power_tool.core import runner, tasks, widgets

UNINSTALL_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"

CSV_HEADER = ["Name", "Version", "Publisher", "Size", "Installed",
              "UninstallString"]


def _hives():
    return [
        (winreg.HKEY_LOCAL_MACHINE, UNINSTALL_PATH, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, UNINSTALL_PATH, winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, UNINSTALL_PATH, winreg.KEY_WOW64_64KEY),
    ]


def _get(sub, name, default=None):
    try:
        value, _ = winreg.QueryValueEx(sub, name)
        return value
    except OSError:
        return default


def gather_apps() -> list[dict]:
    apps = []
    seen = set()
    for hive, path, view in _hives():
        try:
            root = winreg.OpenKey(hive, path, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with root:
            count = winreg.QueryInfoKey(root)[0]
            for index in range(count):
                with winreg.OpenKey(root, winreg.EnumKey(root, index)) as sub:
                    name = _get(sub, "DisplayName")
                    if not name:
                        continue
                    try:
                        if int(_get(sub, "SystemComponent", 0) or 0) == 1:
                            continue
                    except (TypeError, ValueError):
                        pass
                    version = str(_get(sub, "DisplayVersion") or "")
                    publisher = str(_get(sub, "Publisher") or "")
                    dedupe = (str(name).lower(), version, publisher)
                    if dedupe in seen:
                        continue
                    seen.add(dedupe)
                    apps.append({
                        "name": str(name),
                        "version": version,
                        "publisher": publisher,
                        "size_kb": _get(sub, "EstimatedSize") or 0,
                        "installed": str(_get(sub, "InstallDate") or ""),
                        "uninstall": str(_get(sub, "UninstallString") or ""),
                    })
    apps.sort(key=lambda app: app["name"].lower())
    return apps


def format_size(size_kb) -> str:
    try:
        kb = int(size_kb or 0)
    except (TypeError, ValueError):
        return ""
    if kb <= 0:
        return ""
    if kb >= 1024:
        return f"{kb / 1024:.1f} MB"
    return f"{kb} KB"


def format_date(raw) -> str:
    text = str(raw or "")
    if len(text) == 8 and text.isdigit():
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    return text


def filter_apps(apps: list[dict], query: str) -> list[dict]:
    cleaned = str(query or "").strip().lower()
    if not cleaned:
        return list(apps)
    return [app for app in apps
            if cleaned in app["name"].lower()
            or cleaned in app["publisher"].lower()]


def uninstall_command(uninstall_string: str) -> list[str]:
    text = str(uninstall_string or "").strip()
    if not text:
        raise ValueError("no uninstall command")
    return [token.strip('"') for token in shlex.split(text, posix=False)]


def write_csv(path: str, apps: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        for app in apps:
            writer.writerow([
                app["name"], app["version"], app["publisher"],
                format_size(app["size_kb"]), format_date(app["installed"]),
                app["uninstall"],
            ])


class InstalledAppsFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=16)
        ttk.Label(self, text="Installed Apps",
                  style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            self, wraplength=660, style="Dim.TLabel",
            text="Every program registered in the Windows uninstall hives. "
                 "Search filters live; Uninstall starts the program's own "
                 "uninstaller after confirmation.",
        ).pack(anchor="w", pady=(6, 12))

        search_row = ttk.Frame(self)
        search_row.pack(fill="x", pady=(0, 8))
        ttk.Label(search_row, text="Search:").pack(side="left")
        self._query = tk.StringVar()
        self._query.trace_add("write", lambda *_: self._refilter())
        ttk.Entry(search_row, textvariable=self._query,
                  width=40).pack(side="left", padx=8)

        tree_row = ttk.Frame(self)
        tree_row.pack(fill="both", expand=True)
        columns = ("name", "version", "publisher", "size", "installed")
        self._tree = ttk.Treeview(tree_row, columns=columns,
                                  show="headings", height=14)
        headings = {"name": ("Name", 260), "version": ("Version", 100),
                    "publisher": ("Publisher", 170), "size": ("Size", 90),
                    "installed": ("Installed", 110)}
        for key, (label, width) in headings.items():
            self._tree.heading(key, text=label)
            self._tree.column(key, width=width, anchor="w")
        scroll = ttk.Scrollbar(tree_row, orient="vertical",
                               command=self._tree.yview)
        self._tree.configure(yscrollcommand=scroll.set)
        self._tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        buttons = ttk.Frame(self)
        buttons.pack(anchor="w", pady=(10, 0))
        self._refresh_button = ttk.Button(
            buttons, text="Refresh", style="Accent.TButton",
            command=self._refresh)
        self._refresh_button.pack(side="left", padx=(0, 8))
        self._export_button = ttk.Button(buttons, text="Export CSV",
                                         command=self._export)
        self._export_button.pack(side="left", padx=(0, 8))
        self._uninstall_button = ttk.Button(
            buttons, text="Uninstall", style="Danger.TButton",
            command=self._uninstall)
        self._uninstall_button.pack(side="left")

        self.status = widgets.StatusPane(self)
        self.status.pack(fill="x", pady=(10, 0))

        self._all_apps: list[dict] = []
        self._visible: list[dict] = []
        self._refresh()

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for button in (self._refresh_button, self._export_button,
                       self._uninstall_button):
            button.configure(state=state)

    def _refresh(self) -> None:
        self._set_busy(True)
        self.status.set_working("Reading uninstall registry hives...")
        tasks.BackgroundTask(
            self, work=gather_apps,
            on_done=self._load_done, on_error=self._load_error).start()

    def _load_done(self, apps: list[dict]) -> None:
        self._all_apps = apps
        self._set_busy(False)
        self._refilter()
        self.status.set_success(f"{len(apps)} apps found.")

    def _load_error(self, exc: BaseException) -> None:
        self._set_busy(False)
        self.status.set_error(f"Reading apps failed: {exc}")

    def _refilter(self) -> None:
        self._visible = filter_apps(self._all_apps, self._query.get())
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        for index, app in enumerate(self._visible):
            self._tree.insert("", "end", iid=str(index), values=(
                app["name"], app["version"], app["publisher"],
                format_size(app["size_kb"]), format_date(app["installed"])))
        if self._query.get().strip():
            self.status.set_idle(
                f"{len(self._visible)} of {len(self._all_apps)} apps match")

    def _selected_app(self) -> dict | None:
        selection = self._tree.selection()
        if not selection:
            return None
        return self._visible[int(selection[0])]

    def _uninstall(self) -> None:
        app = self._selected_app()
        if app is None:
            self.status.set_warn("Select an app first.")
            return
        if not widgets.guard_admin(self.status):
            return
        if not widgets.confirm(self, "Uninstall program",
                               f"Start the uninstaller for {app['name']}?"):
            self.status.set_idle("Uninstall cancelled.")
            return
        try:
            command = uninstall_command(app["uninstall"])
        except ValueError:
            self.status.set_error(
                "This app has no uninstall command — remove it from "
                "Windows Settings instead.")
            return
        try:
            runner.start_detached(command)
        except OSError as exc:
            self.status.set_error(f"Could not start uninstaller: {exc}")
            return
        self.status.set_success(
            f"Uninstaller started for {app['name']}. Follow its prompts.")

    def _export(self) -> None:
        if not self._visible:
            self.status.set_warn("Nothing to export.")
            return
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="installed_apps.csv")
        if not path:
            return
        try:
            write_csv(path, self._visible)
        except OSError as exc:
            self.status.set_error(f"Export failed: {exc}")
            return
        self.status.set_success(
            f"Exported {len(self._visible)} apps to {path}")


def create(parent: ttk.Frame) -> ttk.Frame:
    return InstalledAppsFrame(parent)
