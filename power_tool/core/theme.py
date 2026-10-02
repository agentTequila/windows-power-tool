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


def _shade(hex_color: str, factor: float) -> str:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    clamp = lambda v: max(0, min(255, int(v * factor)))
    return "#%02x%02x%02x" % (clamp(r), clamp(g), clamp(b))


def _draw_line(img: tk.PhotoImage, x0: int, y0: int, x1: int, y1: int,
               color: str) -> None:
    steps = max(abs(x1 - x0), abs(y1 - y0), 1)
    for i in range(steps + 1):
        x = round(x0 + (x1 - x0) * i / steps)
        y = round(y0 + (y1 - y0) * i / steps)
        img.put(color, to=(x, y, min(x + 1, 12), min(y + 1, 12)))


def _tick_images(p: dict) -> dict:
    width = height = 13

    def box() -> tk.PhotoImage:
        img = tk.PhotoImage(width=width, height=height)
        img.put(p["border"], to=(0, 0, width - 1, height - 1))
        img.put(p["entry_bg"], to=(1, 1, width - 2, height - 2))
        return img

    on = box()
    _draw_line(on, 3, 7, 5, 9, p["accent"])
    _draw_line(on, 5, 9, 10, 4, p["accent"])
    return {"on": on, "off": box()}


def _apply_tick_indicator(style: ttk.Style, root: tk.Misc, name: str,
                          p: dict) -> None:
    element = f"wpt.tick.{name}"
    images = _tick_images(p)
    cache = getattr(root, "_wpt_check_images", None)
    if not isinstance(cache, dict):
        cache = {}
        root._wpt_check_images = cache
    cache[name] = images
    if element not in style.element_names():
        style.element_create(
            element, "image", images["off"],
            ("selected", images["on"]),
            ("pressed", images["on"]),
            ("alternate", images["off"]),
            ("disabled", images["off"]),
            ("active", images["off"]))
    style.layout("TCheckbutton", [
        ("Checkbutton.padding", {"sticky": "nswe", "children": [
            (element, {"side": "left", "sticky": ""}),
            ("Checkbutton.focus", {"side": "left", "sticky": "w",
                                   "children": [
                                       ("Checkbutton.label",
                                        {"sticky": "nswe"})]})]})])


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
    style.configure("Warn.TLabel", background=p["panel"], foreground=p["warn"])
    style.configure("Accent.TButton", background=p["accent"], foreground=p["accent_fg"],
                    padding=(12, 6))
    style.map("Accent.TButton",
              background=[("active", _shade(p["accent"], 0.85))],
              foreground=[("active", p["accent_fg"]), ("disabled", p["dim"])])
    style.configure("Danger.TButton", background=p["danger"], foreground=p["accent_fg"],
                    padding=(12, 6))
    style.map("Danger.TButton",
              background=[("active", _shade(p["danger"], 0.85))],
              foreground=[("active", p["accent_fg"]), ("disabled", p["dim"])])
    style.configure("TButton", padding=(10, 5))
    style.map("TButton",
              background=[("active", p["panel2"])],
              foreground=[("active", p["fg"]), ("disabled", p["dim"])])
    style.configure("TCheckbutton", background=p["bg"], foreground=p["fg"])
    style.map("TCheckbutton",
              background=[("active", p["panel2"])],
              foreground=[("active", p["fg"]), ("disabled", p["dim"])])
    _apply_tick_indicator(style, root, name, p)
    style.configure("TRadiobutton", background=p["bg"], foreground=p["fg"])
    style.map("TRadiobutton",
              background=[("active", p["panel2"])],
              foreground=[("active", p["fg"]), ("disabled", p["dim"])])
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
    style.map("Active.Sidebar.TButton",
              background=[("active", _shade(p["accent"], 0.85))],
              foreground=[("active", p["accent_fg"])])

    for cb in list(_observers):
        try:
            cb(dict(palette))
        except tk.TclError:
            _observers.remove(cb)
    return dict(palette)
