"""Generate assets/icon.ico and assets/icon-256.png — D1 "Checker + Bolt".

Dev-only tool (requires Pillow). Run from anywhere:
    python assets/generate_icon.py
Deterministic: same code -> identical .ico bytes (per Pillow version).
"""
from __future__ import annotations

import io
import os
import struct

from PIL import Image, ImageDraw

CANVAS = 128
SIZES = (16, 24, 32, 48, 64, 128, 256)
UNIFORM_BELOW = 33  # sizes <= 24 use uniform panes / no bolt; 32+ full design

ACCENT = (79, 140, 255, 255)   # #4f8cff
DIM = (42, 53, 80, 255)        # #2a3550
TILE = (30, 31, 38, 255)       # #1e1f26
WHITE = (255, 255, 255, 255)

_SUPERSAMPLE = 4

# x, y, w, h, is_accent in 128-unit design space
PANES = (
    (22, 22, 42, 42, True),
    (66, 22, 40, 42, False),
    (22, 66, 42, 40, False),
    (66, 66, 40, 40, True),
)
BOLT = (
    (74, 74), (64, 94), (72, 94),
    (69, 108), (86, 86), (77, 86),
)


def _render(size: int) -> Image.Image:
    big = size * _SUPERSAMPLE
    scale = big / CANVAS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        (4 * scale, 4 * scale, 124 * scale, 124 * scale),
        radius=26 * scale, fill=TILE)
    uniform = size < UNIFORM_BELOW
    for (x, y, w, h, is_accent) in PANES:
        color = ACCENT if (uniform or is_accent) else DIM
        draw.rounded_rectangle(
            (x * scale, y * scale, (x + w) * scale, (y + h) * scale),
            radius=8 * scale, fill=color)
    if not uniform:
        draw.polygon([(px * scale, py * scale) for (px, py) in BOLT],
                     fill=WHITE)
    return img.resize((size, size), Image.LANCZOS)


def _ico_bytes(images: dict[int, Image.Image]) -> bytes:
    ordered = [images[s] for s in sorted(images)]
    sizes = sorted(images)
    header = struct.pack("<HHH", 0, 1, len(sizes))
    entries = b""
    blobs = b""
    offset = 6 + 16 * len(sizes)
    for size, img in zip(sizes, ordered):
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png = buf.getvalue()
        entries += struct.pack(
            "<BBBBHHII",
            size % 256, size % 256, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    return header + entries + blobs


def build(out_dir: str | None = None) -> str:
    if out_dir is None:
        out_dir = os.path.dirname(os.path.abspath(__file__))
    images = {size: _render(size) for size in SIZES}
    ico_path = os.path.join(out_dir, "icon.ico")
    with open(ico_path, "wb") as handle:
        handle.write(_ico_bytes(images))
    images[256].save(os.path.join(out_dir, "icon-256.png"))
    return ico_path


def main() -> None:
    path = build()
    print(f"Wrote {path} ({os.path.getsize(path)} bytes)")
    print(f"Wrote {os.path.join(os.path.dirname(path), 'icon-256.png')}")


if __name__ == "__main__":
    main()
