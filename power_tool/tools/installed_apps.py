import csv
import os
import shlex
import shutil
import tkinter as tk
import winreg
from functools import partial
from pathlib import Path
from tkinter import filedialog, ttk

from power_tool.core import runner, tasks, widgets

UNINSTALL_PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"

CSV_HEADER = ["Name", "Version", "Publisher", "Size", "Installed",
              "UninstallString"]

FOLDER_ROOT_KEYS = ("PROGRAMFILES", "PROGRAMFILES(X86)", "ProgramData",
                    "LOCALAPPDATA", "APPDATA")


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
                try:
                    sub = winreg.OpenKey(
                        root, winreg.EnumKey(root, index))
                except OSError:
                    continue
                with sub:
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


def remove_path(path: Path) -> tuple[bool, int]:
    """Delete *path*, returning (ok, bytes_freed). Never raises."""
    try:
        if path.is_dir():
            size = sum(
                child.stat().st_size
                for child in path.rglob("*")
                if child.is_file()
            )
            shutil.rmtree(path)
            return True, size
        if path.is_file():
            size = path.stat().st_size
            path.unlink()
            return True, size
        return False, 0
    except OSError:
        return False, 0


def scan_leftover_folders(display_name: str, publisher: str,
                          roots: list[Path]) -> list[dict]:
    """One level of folders under each root.

    Exact (case-insensitive) folder-name match against the display name is
    high confidence; a match against the publisher is low confidence and is
    only used when the publisher is at least 4 characters. Generic short
    display names never trigger a scan.
    """
    target = display_name.strip().lower()
    if len(target) < 4:
        return []
    findings: list[dict] = []
    for root in roots:
        try:
            entries = list(root.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            name = entry.name.lower()
            if name == target:
                findings.append({
                    "path": entry,
                    "kind": "folder",
                    "confidence": "high",
                    "label": str(entry),
                })
                continue
            if (len(publisher.strip()) >= 4
                    and name == publisher.strip().lower()):
                findings.append({
                    "path": entry,
                    "kind": "folder",
                    "confidence": "low",
                    "label": str(entry),
                })
    return findings


def _folder_roots() -> list[Path]:
    """Build the folder scan roots from the environment at call time."""
    roots: list[Path] = []
    for key in FOLDER_ROOT_KEYS:
        value = os.environ.get(key)
        if value:
            roots.append(Path(value))
    return roots


def _scan_registry_hive(hive, root: str, view: int,
                        display_name: str) -> list[str]:
    """Leaf subkey names under one hive whose DisplayName matches exactly,
    case-insensitively."""
    target = display_name.strip().lower()
    matches: list[str] = []
    try:
        with winreg.OpenKey(hive, root, 0, winreg.KEY_READ | view) as key:
            count = winreg.QueryInfoKey(key)[0]
            for index in range(count):
                try:
                    subname = winreg.EnumKey(key, index)
                    with winreg.OpenKey(key, subname, 0,
                                        winreg.KEY_READ | view) as sub:
                        value = _get(sub, "DisplayName")
                except OSError:
                    continue
                if value and str(value).strip().lower() == target:
                    matches.append(subname)
    except OSError:
        pass
    return matches


def scan_leftover_registry(display_name: str) -> list[str]:
    """Re-walk the uninstall hives; subkey paths whose DisplayName equals
    *display_name* (case-insensitive exact only)."""
    found: list[str] = []
    for hive, root, view in _hives():
        for subname in _scan_registry_hive(hive, root, view, display_name):
            path = f"{root}\\{subname}"
            if path not in found:
                found.append(path)
    return found


def delete_registry_key(hive, subpath: str) -> bool:
    try:
        winreg.DeleteKey(hive, subpath)
        return True
    except OSError:
        return False


def default_checked(findings: list[dict]) -> list[bool]:
    """Dialog defaults: high-confidence findings ticked, low unticked."""
    return [finding.get("confidence") == "high" for finding in findings]


def _gather_findings(app: dict) -> list[dict]:
    name = str(app.get("name", ""))
    publisher = str(app.get("publisher", ""))
    findings = scan_leftover_folders(name, publisher, _folder_roots())
    for hive, root, view in _hives():
        for subname in _scan_registry_hive(hive, root, view, name):
            path = f"{root}\\{subname}"
            findings.append({
                "kind": "registry",
                "path": path,
                "hive": hive,
                "label": path,
                "confidence": "high",
            })
    return findings


def _delete_findings(selected: list[dict]) -> tuple[int, int, int]:
    removed = 0
    freed = 0
    skipped = 0
    for finding in selected:
        if finding["kind"] == "folder":
            ok, size = remove_path(Path(finding["path"]))
            if ok:
                removed += 1
                freed += size
            else:
                skipped += 1
        elif finding["kind"] == "registry":
            if delete_registry_key(finding["hive"], finding["path"]):
                removed += 1
            else:
                skipped += 1
    return removed, freed, skipped


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
        self._scan_button = ttk.Button(
            buttons, text="Scan leftovers", command=self._scan_leftovers)
        self._scan_button.pack(side="left")

        self.status = widgets.StatusPane(self)
        self.status.pack(fill="x", pady=(10, 0))

        self._all_apps: list[dict] = []
        self._visible: list[dict] = []
        self._refresh()

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for button in (self._refresh_button, self._export_button,
                       self._uninstall_button, self._scan_button):
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
        else:
            self.status.set_success(f"{len(self._all_apps)} apps found.")

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
        if widgets.confirm(self, "Scan leftovers",
                           f"Scan for leftovers of {app['name']} now?"):
            self._scan_leftovers_for(app)

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

    def _scan_leftovers(self) -> None:
        app = self._selected_app()
        if app is None:
            self.status.set_warn("Select an app first.")
            return
        self._scan_leftovers_for(app)

    def _scan_leftovers_for(self, app: dict) -> None:
        """Start a leftover scan for *app*; no tree selection required."""
        self._set_busy(True)
        self.status.set_working("Scanning for leftovers...")
        tasks.BackgroundTask(
            self, work=partial(_gather_findings, app),
            on_done=lambda findings: self._on_scan_done(findings, app),
            on_error=self._scan_error).start()

    def _on_scan_done(self, findings: list[dict], app: dict) -> None:
        self._set_busy(False)
        if not findings:
            self.status.set_success("No leftovers found.")
            return
        LeftoverDialog(
            self, findings,
            on_remove=lambda selected: self._remove_leftovers(selected, app))

    def _remove_leftovers(self, selected: list[dict], app: dict) -> None:
        if not selected:
            self.status.set_idle("Nothing selected.")
            return
        # Safety order: guard_admin FIRST, then confirm listing the items,
        # and only then is any deletion scheduled.
        if not widgets.guard_admin(self.status):
            return
        listed = "\n".join(finding["label"] for finding in selected)
        if not widgets.confirm(
                self, "Remove leftovers",
                f"Remove {len(selected)} selected leftover item(s)?\n{listed}"):
            self.status.set_idle("Leftover removal cancelled.")
            return
        self._set_busy(True)
        self.status.set_working("Removing selected leftovers...")
        tasks.BackgroundTask(
            self, work=partial(_delete_findings, selected),
            on_done=self._on_remove_done,
            on_error=self._remove_error).start()

    def _on_remove_done(self, result: tuple[int, int, int]) -> None:
        removed, freed, skipped = result
        self._set_busy(False)
        self.status.set_success(
            f"Removed {removed} items · {freed / (1024 * 1024):.1f} "
            f"MB freed · {skipped} skipped.")

    def _scan_error(self, exc: BaseException) -> None:
        self._set_busy(False)
        self.status.set_error(f"Leftover scan failed: {exc}")

    def _remove_error(self, exc: BaseException) -> None:
        self._set_busy(False)
        self.status.set_error(f"Leftover removal failed: {exc}")


class LeftoverDialog(tk.Toplevel):
    def __init__(self, parent, findings: list[dict], on_remove):
        super().__init__(parent)
        self.title("Remove leftover items")
        self.transient(parent)
        self.grab_set()
        self._findings = findings
        self._on_remove = on_remove
        self._vars: list[tk.BooleanVar] = []
        ttk.Label(
            self,
            text="Leftover items found. Uncheck anything you want to keep.",
        ).pack(anchor="w", padx=12, pady=(10, 6))
        for finding, checked in zip(findings, default_checked(findings)):
            var = tk.BooleanVar(value=checked)
            self._vars.append(var)
            ttk.Checkbutton(self, text=finding["label"],
                            variable=var).pack(anchor="w", padx=24, pady=2)
        buttons = ttk.Frame(self)
        buttons.pack(anchor="e", padx=12, pady=(10, 12))
        ttk.Button(buttons, text="Close", command=self.destroy).pack(
            side="right", padx=(6, 0))
        ttk.Button(buttons, text="Remove selected", style="Danger.TButton",
                   command=self._do_remove).pack(side="right")
        self.wait_window(self)

    def _do_remove(self) -> None:
        selected = [finding for finding, var
                    in zip(self._findings, self._vars) if var.get()]
        self.destroy()
        self._on_remove(selected)


def create(parent: ttk.Frame) -> ttk.Frame:
    return InstalledAppsFrame(parent)
