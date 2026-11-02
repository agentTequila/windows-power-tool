"""Generate the sidebar icon set (dev-only, requires Pillow).

Run from the repo root:
    python assets/generate_icons.py

Icons are drawn at 4x and downsampled so they stay crisp at 18 px. Three
variants per tool: normal for dark, normal for light, and the active white.
"""

import os

from PIL import Image, ImageDraw

SIZE = 72          # drawing canvas (4x the 18 px display size)
DISPLAY = 18
STROKE = 7

COLORS = {
    "normal_dark": (139, 148, 167, 255),
    "normal_light": (92, 104, 124, 255),
    "active": (255, 255, 255, 255),
}


def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    return image, ImageDraw.Draw(image)


def _line(draw, points, color):
    draw.line(points, fill=color, width=STROKE, joint="curve")
    radius = STROKE // 2
    for x, y in (points[0], points[-1]):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius),
                     fill=color)


def _round_rect(draw, box, color, radius=8):
    draw.rounded_rectangle(box, radius=radius, outline=color, width=STROKE)


def draw_lock(color):
    image, draw = _canvas()
    _round_rect(draw, (18, 32, 54, 62), color, radius=8)
    draw.arc((22, 10, 50, 42), 180, 360, fill=color, width=STROKE)
    _line(draw, [(22, 26), (22, 34)], color)
    _line(draw, [(50, 26), (50, 34)], color)
    draw.ellipse((33, 43, 39, 49), fill=color)
    return image


def draw_bolt(color):
    image, draw = _canvas()
    points = [(42, 8), (22, 38), (35, 38), (30, 64), (52, 32), (39, 32)]
    draw.polygon(points, outline=color, width=STROKE)
    return image


def draw_log(color):
    image, draw = _canvas()
    _round_rect(draw, (18, 10, 54, 62), color, radius=6)
    for y in (26, 36, 46):
        _line(draw, [(27, y), (45, y)], color)
    return image


def draw_monitor(color):
    image, draw = _canvas()
    _round_rect(draw, (8, 14, 64, 48), color, radius=5)
    _line(draw, [(36, 48), (36, 58)], color)
    _line(draw, [(24, 60), (48, 60)], color)
    _line(draw, [(20, 24), (36, 24)], color)
    return image


def draw_globe(color):
    image, draw = _canvas()
    draw.ellipse((10, 10, 62, 62), outline=color, width=STROKE)
    _line(draw, [(12, 36), (60, 36)], color)
    draw.arc((22, 10, 50, 62), 90, 270, fill=color, width=STROKE)
    return image


def draw_search(color):
    image, draw = _canvas()
    draw.ellipse((10, 10, 46, 46), outline=color, width=STROKE)
    _line(draw, [(43, 43), (60, 60)], color)
    draw.ellipse((22, 22, 34, 34), outline=color, width=STROKE)
    return image


def draw_terminal(color):
    image, draw = _canvas()
    _round_rect(draw, (8, 14, 64, 58), color, radius=6)
    _line(draw, [(22, 27), (31, 36), (22, 45)], color)
    _line(draw, [(38, 45), (50, 45)], color)
    return image


def draw_apps(color):
    image, draw = _canvas()
    for x in (12, 40):
        for y in (12, 40):
            _round_rect(draw, (x, y, x + 20, y + 20), color, radius=4)
    return image


def draw_users(color):
    image, draw = _canvas()
    draw.ellipse((14, 12, 34, 32), outline=color, width=STROKE)
    draw.arc((8, 30, 42, 66), 180, 360, fill=color, width=STROKE)
    draw.ellipse((42, 16, 57, 31), outline=color, width=STROKE)
    draw.arc((38, 32, 66, 60), 180, 360, fill=color, width=STROKE)
    return image


def draw_activity(color):
    image, draw = _canvas()
    for y in (20, 36, 52):
        draw.ellipse((10, y - 3, 16, y + 3), fill=color)
        _line(draw, [(23, y), (60, y)], color)
    return image


def draw_gear(color):
    image, draw = _canvas()
    draw.ellipse((20, 20, 52, 52), outline=color, width=STROKE)
    draw.ellipse((31, 31, 41, 41), outline=color, width=STROKE)
    for angle_points in (
            [(36, 6), (36, 16)], [(36, 56), (36, 66)],
            [(6, 36), (16, 36)], [(56, 36), (66, 36)],
            [(15, 15), (22, 22)], [(50, 50), (57, 57)],
            [(15, 57), (22, 50)], [(50, 22), (57, 15)]):
        _line(draw, angle_points, color)
    return image


def draw_disk(color):
    image, draw = _canvas()
    draw.ellipse((12, 10, 60, 26), outline=color, width=STROKE)
    _line(draw, [(12, 18), (12, 52)], color)
    _line(draw, [(60, 18), (60, 52)], color)
    draw.arc((12, 44, 60, 60), 0, 180, fill=color, width=STROKE)
    return image


def draw_restore(color):
    image, draw = _canvas()
    draw.arc((12, 12, 60, 60), 40, 320, fill=color, width=STROKE)
    _line(draw, [(48, 8), (58, 18), (46, 22)], color)
    _line(draw, [(36, 30), (36, 38), (44, 38)], color)
    return image


def draw_key(color):
    image, draw = _canvas()
    draw.ellipse((8, 26, 34, 52), outline=color, width=STROKE)
    _line(draw, [(32, 39), (62, 39)], color)
    _line(draw, [(50, 39), (50, 49)], color)
    _line(draw, [(58, 39), (58, 47)], color)
    return image


ICONS = {
    "usb_guard": draw_lock,
    "speedup": draw_bolt,
    "log_collector": draw_log,
    "system_info": draw_monitor,
    "network": draw_globe,
    "ip_scanner": draw_search,
    "console": draw_terminal,
    "installed_apps": draw_apps,
    "users_groups": draw_users,
    "processes": draw_activity,
    "services": draw_gear,
    "disk_cleanup": draw_disk,
    "restore_point": draw_restore,
    "license_info": draw_key,
}


def build(out_dir: str | None = None) -> str:
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "icons")
    for variant, color in COLORS.items():
        target = os.path.join(out_dir, variant)
        os.makedirs(target, exist_ok=True)
        for stem, painter in ICONS.items():
            image = painter(color)
            image = image.resize((DISPLAY, DISPLAY), Image.LANCZOS)
            image.save(os.path.join(target, f"{stem}.png"))
    return out_dir


def main() -> None:
    path = build()
    print(f"Wrote {len(ICONS) * len(COLORS)} icons under {path}")


if __name__ == "__main__":
    main()
