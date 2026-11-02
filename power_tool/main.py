import os
import sys
import tkinter as tk
from tkinter import ttk

from power_tool import __version__
from power_tool.core import admin, theme
from power_tool.tools import REGISTRY


def _asset_path(name: str) -> str:
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", name)


def _icon_path() -> str:
    return _asset_path("icon.ico")


def _apply_icon(root: tk.Tk) -> None:
    path = _icon_path()
    if not os.path.isfile(path):
        return
    try:
        root.iconbitmap(path)
    except (tk.TclError, OSError, TypeError):
        pass


def _load_logo() -> tk.PhotoImage | None:
    """The topbar mark; None when the asset is missing or unreadable."""
    path = _asset_path("icon-256.png")
    if not os.path.isfile(path):
        return None
    try:
        image = tk.PhotoImage(file=path)
    except (tk.TclError, OSError):
        return None
    factor = max(1, image.width() // 26)
    return image.subsample(factor, factor) if factor > 1 else image


def _load_tool_icons() -> dict[str, dict[str, tk.PhotoImage]]:
    """Load the three sidebar icon variants; missing files are skipped."""
    stems = {module.__name__.rsplit(".", 1)[-1]
             for _, modules in REGISTRY for _, module in modules}
    icons: dict[str, dict[str, tk.PhotoImage]] = {}
    for variant in ("normal_dark", "normal_light", "active"):
        loaded: dict[str, tk.PhotoImage] = {}
        for stem in stems:
            path = _asset_path(os.path.join("icons", variant, f"{stem}.png"))
            if not os.path.isfile(path):
                continue
            try:
                loaded[stem] = tk.PhotoImage(file=path)
            except (tk.TclError, OSError):
                continue
        icons[variant] = loaded
    return icons


class PowerToolApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        _apply_icon(self)
        self.title(f"Windows Power Tool {__version__}")
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        width = min(1180, max(1000, screen_w - 80))
        height = min(780, max(660, screen_h - 100))
        self.geometry(f"{width}x{height}"
                      f"+{max(0, (screen_w - width) // 2)}"
                      f"+{max(0, (screen_h - height) // 2)}")
        self.minsize(min(1000, width), min(660, height))
        self._theme_name = theme.load_theme_name()
        self._current_key: str | None = None
        self._tool_frames: dict[str, ttk.Frame] = {}
        self._sidebar_buttons: dict[str, ttk.Button] = {}
        self._modules = {module.__name__: module
                         for _, modules in REGISTRY for _, module in modules}
        self._logo_image = None
        self._icons = _load_tool_icons()
        self._build_topbar()
        self._build_body()
        theme.apply_theme(self, self._theme_name)
        self._theme_button.configure(text=self._theme_button_text())
        if self._modules:
            self.show_tool(next(iter(self._modules)))

    def _theme_button_text(self) -> str:
        return "Light mode" if self._theme_name == "dark" else "Dark mode"

    def _icon_for(self, key: str,
                  active: bool = False) -> tk.PhotoImage | None:
        stem = key.rsplit(".", 1)[-1]
        if active:
            return self._icons.get("active", {}).get(stem)
        variant = "normal_dark" if self._theme_name == "dark" else "normal_light"
        return self._icons.get(variant, {}).get(stem)

    def _build_topbar(self) -> None:
        bar = ttk.Frame(self, style="Topbar.TFrame", padding=(18, 12))
        bar.grid(row=0, column=0, columnspan=3, sticky="ew")
        bar.grid_columnconfigure(3, weight=1)

        column = 0
        logo = _load_logo()
        if logo is not None:
            self._logo_image = logo
            ttk.Label(bar, image=logo, style="Topbar.TLabel").grid(
                row=0, column=column, padx=(0, 12))
            column += 1
        ttk.Label(bar, text="Windows Power Tool",
                  style="AppTitle.TLabel").grid(row=0, column=column,
                                               sticky="w")
        column += 1
        ttk.Label(bar, text=f"v{__version__}", style="Chip.TLabel").grid(
            row=0, column=column, padx=(10, 0), sticky="w")
        column += 1

        elevated = admin.is_admin()
        ttk.Label(
            bar,
            text="●  Administrator" if elevated else "●  Not elevated",
            style="ChipSuccess.TLabel" if elevated else "ChipError.TLabel",
        ).grid(row=0, column=column, padx=(0, 10), sticky="e")
        column += 1
        self._theme_button = ttk.Button(
            bar, text="Theme", style="Ghost.TButton",
            command=self.toggle_theme)
        self._theme_button.grid(row=0, column=column, sticky="e")

        ttk.Frame(self, style="Divider.TFrame", height=1).grid(
            row=1, column=0, columnspan=3, sticky="ew")

    def _build_body(self) -> None:
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(2, weight=1)

        sidebar = ttk.Frame(self, style="Sidebar.TFrame", width=248,
                            padding=(12, 16))
        sidebar.grid(row=2, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        divider = ttk.Frame(self, style="Divider.TFrame", width=1)
        divider.grid(row=2, column=1, sticky="ns")

        self._content = ttk.Frame(self, style="Content.TFrame")
        self._content.grid(row=2, column=2, sticky="nsew")
        self._content.grid_rowconfigure(0, weight=1)
        self._content.grid_columnconfigure(0, weight=1)

        row = 0
        for group_name, modules in REGISTRY:
            ttk.Label(sidebar, text=group_name.upper(),
                      style="SidebarHeading.TLabel").grid(
                          row=row, column=0, sticky="w", padx=4,
                          pady=(16 if row else 0, 6))
            row += 1
            for label, module in modules:
                key = module.__name__
                icon = self._icon_for(key)
                options = {"image": icon, "compound": "left"} if icon else {}
                button = ttk.Button(sidebar, text=label,
                                    style="Sidebar.TButton",
                                    command=lambda k=key: self.show_tool(k),
                                    **options)
                button.grid(row=row, column=0, sticky="ew", pady=1, padx=6)
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
            old = self._sidebar_buttons[self._current_key]
            old.configure(style="Sidebar.TButton",
                          image=self._icon_for(self._current_key) or "")
        self._sidebar_buttons[key].configure(
            style="Active.Sidebar.TButton",
            image=self._icon_for(key, active=True) or "")
        self._current_key = key

    def toggle_theme(self) -> None:
        self._theme_name = "light" if self._theme_name == "dark" else "dark"
        theme.save_theme_name(self._theme_name)
        theme.apply_theme(self, self._theme_name)
        self._theme_button.configure(text=self._theme_button_text())
        for key, button in self._sidebar_buttons.items():
            button.configure(
                image=self._icon_for(key, key == self._current_key) or "")


def main() -> None:
    app = PowerToolApp()
    app.mainloop()
