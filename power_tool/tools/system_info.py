from tkinter import ttk


def create(parent: ttk.Frame) -> ttk.Frame:
    frame = ttk.Frame(parent, padding=16)
    ttk.Label(frame, text="System Info", style="Title.TLabel").pack(anchor="w")
    ttk.Label(frame, text="Coming soon.", style="Dim.TLabel").pack(anchor="w", pady=(6, 0))
    return frame
