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
