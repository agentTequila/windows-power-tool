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
