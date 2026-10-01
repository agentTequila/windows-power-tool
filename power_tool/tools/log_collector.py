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
