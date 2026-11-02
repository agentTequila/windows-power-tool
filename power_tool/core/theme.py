import json
import os
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable

PALETTES = {
    "dark": {
        "bg": "#0f1116", "panel": "#161a22", "panel2": "#1f2531",
        "fg": "#e8ebf2", "dim": "#8b94a7", "accent": "#5b8def",
        "accent_fg": "#ffffff", "success": "#3ddc97", "danger": "#ff6b6b",
        "warn": "#f2b84b", "border": "#283040", "entry_bg": "#0b0e13",
    },
    "light": {
        "bg": "#f4f6fb", "panel": "#ffffff", "panel2": "#e9edf5",
        "fg": "#131722", "dim": "#5c687c", "accent": "#2f6fed",
        "accent_fg": "#ffffff", "success": "#12805c", "danger": "#c43d3d",
        "warn": "#9a6300", "border": "#d7dde9", "entry_bg": "#ffffff",
    },
}
DEFAULT_THEME = "dark"

FONT = "Segoe UI"

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
    cache = getattr(root, "_wpt_check_images", None)
    if not isinstance(cache, dict):
        cache = {}
        root._wpt_check_images = cache
    # Permanent per-name cache by design: ttk elements pin the original
    # images, so regenerating them kills rendering (the original bug).
    if name in cache:
        images = cache[name]
    else:
        images = _tick_images(p)
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
    style.configure("Sidebar.TFrame", background=p["panel"])
    style.configure("Topbar.TFrame", background=p["panel"])
    style.configure("Content.TFrame", background=p["bg"])
    style.configure("Divider.TFrame", background=p["border"])
    style.configure("Status.TFrame", background=p["panel"])

    style.configure("TLabel", background=p["bg"], foreground=p["fg"],
                    font=(FONT, 10))
    style.configure("Panel.TLabel", background=p["panel"], foreground=p["fg"],
                    font=(FONT, 10))
    style.configure("PanelDim.TLabel", background=p["panel"],
                    foreground=p["dim"], font=(FONT, 10))
    style.configure("Topbar.TLabel", background=p["panel"],
                    foreground=p["fg"])
    style.configure("AppTitle.TLabel", background=p["panel"],
                    foreground=p["fg"], font=(FONT, 15, "bold"))
    style.configure("Dim.TLabel", background=p["bg"], foreground=p["dim"],
                    font=(FONT, 10))
    style.configure("Title.TLabel", background=p["bg"], foreground=p["fg"],
                    font=(FONT, 20, "bold"))
    style.configure("Chip.TLabel", background=p["panel2"],
                    foreground=p["dim"], font=(FONT, 8), padding=(8, 3))
    style.configure("ChipSuccess.TLabel", background=p["panel2"],
                    foreground=p["success"], font=(FONT, 8), padding=(8, 3))
    style.configure("ChipError.TLabel", background=p["panel2"],
                    foreground=p["danger"], font=(FONT, 8), padding=(8, 3))
    style.configure("SidebarHeading.TLabel", background=p["panel"],
                    foreground=p["dim"], font=(FONT, 8, "bold"))
    style.configure("PanelHeading.TLabel", background=p["panel"],
                    foreground=p["dim"], font=(FONT, 8, "bold"))
    style.configure("Idle.TLabel", background=p["panel"], foreground=p["dim"],
                    font=(FONT, 9))
    style.configure("Working.TLabel", background=p["panel"],
                    foreground=p["accent"], font=(FONT, 9))
    style.configure("Success.TLabel", background=p["panel"],
                    foreground=p["success"], font=(FONT, 9))
    style.configure("Error.TLabel", background=p["panel"],
                    foreground=p["danger"], font=(FONT, 9))
    style.configure("Warn.TLabel", background=p["panel"],
                    foreground=p["warn"], font=(FONT, 9))

    style.configure("Accent.TButton", background=p["accent"],
                    foreground=p["accent_fg"], padding=(14, 7),
                    font=(FONT, 9, "bold"), borderwidth=0, focusthickness=0,
                    relief="flat")
    style.map("Accent.TButton",
              background=[("active", _shade(p["accent"], 0.86)),
                          ("pressed", _shade(p["accent"], 0.78))],
              foreground=[("active", p["accent_fg"]),
                          ("disabled", p["dim"])])
    style.configure("Danger.TButton", background=p["danger"],
                    foreground=p["accent_fg"], padding=(14, 7),
                    font=(FONT, 9, "bold"), borderwidth=0, focusthickness=0,
                    relief="flat")
    style.map("Danger.TButton",
              background=[("active", _shade(p["danger"], 0.86)),
                          ("pressed", _shade(p["danger"], 0.78))],
              foreground=[("active", p["accent_fg"]),
                          ("disabled", p["dim"])])
    style.configure("TButton", background=p["panel2"], foreground=p["fg"],
                    padding=(12, 6), font=(FONT, 9), borderwidth=0,
                    focusthickness=0, relief="flat")
    style.map("TButton",
              background=[("active", _shade(p["panel2"], 1.16)),
                          ("pressed", _shade(p["panel2"], 0.9))],
              foreground=[("active", p["fg"]), ("disabled", p["dim"])])
    style.configure("Ghost.TButton", background=p["panel"],
                    foreground=p["fg"], padding=(10, 6), font=(FONT, 9),
                    borderwidth=0, focusthickness=0, relief="flat")
    style.map("Ghost.TButton",
              background=[("active", p["panel2"])],
              foreground=[("active", p["accent"])])

    style.configure("TCheckbutton", background=p["bg"], foreground=p["fg"],
                    font=(FONT, 10))
    style.map("TCheckbutton",
              background=[("active", p["panel2"])],
              foreground=[("active", p["fg"]), ("disabled", p["dim"])])
    _apply_tick_indicator(style, root, name, p)
    style.configure("TRadiobutton", background=p["bg"], foreground=p["fg"],
                    font=(FONT, 10))
    style.map("TRadiobutton",
              background=[("active", p["panel2"])],
              foreground=[("active", p["fg"]), ("disabled", p["dim"])])

    style.configure("TEntry", fieldbackground=p["entry_bg"],
                    foreground=p["fg"], insertcolor=p["fg"],
                    bordercolor=p["border"], lightcolor=p["border"],
                    darkcolor=p["border"], borderwidth=1, relief="flat",
                    padding=(7, 5))
    style.map("TEntry", bordercolor=[("focus", p["accent"])])
    style.configure("TCombobox", fieldbackground=p["entry_bg"],
                    background=p["panel2"], foreground=p["fg"],
                    arrowcolor=p["dim"], bordercolor=p["border"],
                    lightcolor=p["border"], darkcolor=p["border"],
                    borderwidth=1, relief="flat", padding=(6, 4))
    style.map("TCombobox",
              fieldbackground=[("readonly", p["entry_bg"])],
              bordercolor=[("focus", p["accent"])])
    style.configure("TSpinbox", fieldbackground=p["entry_bg"],
                    background=p["panel2"], foreground=p["fg"],
                    arrowcolor=p["dim"], bordercolor=p["border"],
                    borderwidth=1, relief="flat", padding=(6, 4))
    style.map("TSpinbox", bordercolor=[("focus", p["accent"])])

    style.configure("TLabelframe", background=p["bg"],
                    bordercolor=p["border"], lightcolor=p["border"],
                    darkcolor=p["border"], borderwidth=1,
                    relief="solid", padding=12)
    style.configure("TLabelframe.Label", background=p["bg"],
                    foreground=p["dim"], font=(FONT, 9, "bold"))
    style.configure("TNotebook", background=p["bg"],
                    bordercolor=p["border"], lightcolor=p["border"],
                    darkcolor=p["border"], borderwidth=0, relief="flat")
    style.configure("TNotebook.Tab", background=p["panel2"],
                    foreground=p["dim"], padding=(16, 8),
                    font=(FONT, 9), borderwidth=0, relief="flat")
    style.map("TNotebook.Tab",
              background=[("selected", p["panel"]),
                          ("active", p["panel2"])],
              foreground=[("selected", p["fg"]),
                          ("active", p["fg"])])

    style.configure("Treeview", background=p["panel"], foreground=p["fg"],
                    fieldbackground=p["panel"], bordercolor=p["border"],
                    lightcolor=p["border"], darkcolor=p["border"],
                    borderwidth=0, relief="flat", rowheight=28,
                    font=(FONT, 9))
    style.configure("Treeview.Heading", background=p["panel"],
                    foreground=p["dim"], font=(FONT, 8, "bold"),
                    bordercolor=p["border"], lightcolor=p["border"],
                    darkcolor=p["border"], borderwidth=0, relief="flat",
                    padding=(8, 7))
    style.map("Treeview.Heading",
              background=[("active", p["panel2"])],
              foreground=[("active", p["fg"])])
    style.map("Treeview",
              background=[("selected", p["accent"])],
              foreground=[("selected", p["accent_fg"])])

    style.configure("Horizontal.TProgressbar", background=p["accent"],
                    troughcolor=p["panel2"], bordercolor=p["panel2"],
                    lightcolor=p["panel2"], darkcolor=p["panel2"],
                    borderwidth=0, thickness=6)
    style.configure("TScrollbar", background=p["panel2"],
                    troughcolor=p["bg"], bordercolor=p["border"],
                    lightcolor=p["border"], darkcolor=p["border"],
                    arrowcolor=p["dim"], width=10, arrowsize=10,
                    relief="flat", borderwidth=0)
    style.map("TScrollbar",
              background=[("active", p["border"])],
              arrowcolor=[("active", p["fg"])])

    style.configure("Sidebar.TButton", background=p["panel"],
                    foreground=p["fg"], anchor="w", padding=(12, 7),
                    font=(FONT, 10), borderwidth=0, focusthickness=0,
                    relief="flat")
    style.map("Sidebar.TButton",
              background=[("active", p["panel2"])],
              foreground=[("active", p["fg"])])
    style.configure("Active.Sidebar.TButton", background=p["accent"],
                    foreground=p["accent_fg"], anchor="w", padding=(12, 7),
                    font=(FONT, 10, "bold"), borderwidth=0,
                    focusthickness=0, relief="flat")
    style.map("Active.Sidebar.TButton",
              background=[("active", _shade(p["accent"], 0.86))],
              foreground=[("active", p["accent_fg"])])

    for cb in list(_observers):
        try:
            cb(dict(palette))
        except tk.TclError:
            _observers.remove(cb)
    return dict(palette)
