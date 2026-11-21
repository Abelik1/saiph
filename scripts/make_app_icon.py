# SPDX-License-Identifier: AGPL-3.0-or-later
"""Draw the desktop app icon from Saiph's mark (frontend/src/workspace/waves.tsx).

Three stars joined by a string, at rest, on a dark tile so it reads on light and
dark taskbars. Writes assets/orion-mini-icon.png and the multi-size .ico.
Run with Pillow: python scripts/make_app_icon.py
"""
from __future__ import annotations

import colorsys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SIZE = 1024
SS = 4  # supersampling for smooth curves
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def hsl(h: float, s: float, l: float) -> tuple[int, int, int]:
    r, g, b = colorsys.hls_to_rgb(h / 360, l / 100, s / 100)
    return round(r * 255), round(g * 255), round(b * 255)


# Default theme tokens (frontend/src/design-system/tokens.css, families.css).
WAVE_1 = hsl(188, 86, 53)    # --primary
WAVE_2 = hsl(188, 92, 69)    # cyan star
WAVE_3 = hsl(255, 92, 76)    # --violet
STAR = hsl(222, 100, 97)     # --wave-star
TILE_TOP = hsl(222, 58, 11)
TILE_BOTTOM = hsl(222, 70, 5)  # --background


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def quad(p0, p1, p2, steps=1200):
    for i in range(steps + 1):
        t = i / steps
        yield tuple((1 - t) ** 2 * a + 2 * (1 - t) * t * b + t * t * c for a, b, c in zip(p0, p1, p2))


def pose(a: float):
    """SaiphMark's string: two quadratic halves held at the middle star."""
    return [((8, 29), (14 + 0.55 * a, 24.5 + 0.83 * a), (20, 20)),
            ((20, 20), (26 - 0.55 * a, 15.5 - 0.83 * a), (32, 11))]


def draw() -> Image.Image:
    w = SIZE * SS
    # The mark spans 24 units of its 40-unit box; it fills ~62% of the tile here.
    scale = w * 0.62 / 24
    to_px = lambda x, y: ((x - 20) * scale + w / 2, (y - 20) * scale + w / 2)

    tile = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    grad = Image.new("RGBA", (1, w))
    for y in range(w):
        grad.putpixel((0, y), lerp(TILE_TOP, TILE_BOTTOM, y / (w - 1)) + (255,))
    grad = grad.resize((w, w))
    mask = Image.new("L", (w, w), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, w - 1), radius=round(w * 0.22), fill=255)
    tile.paste(grad, (0, 0), mask)

    # Soft cyan glow behind the middle star.
    glow = Image.new("RGBA", (w, w), WAVE_2 + (0,))
    gmask = Image.new("L", (w, w), 0)
    cx, cy = to_px(20, 20)
    r = 12 * scale
    ImageDraw.Draw(gmask).ellipse((cx - r, cy - r, cx + r, cy + r), fill=120)
    glow.putalpha(gmask.filter(ImageFilter.GaussianBlur(r * 0.45)))

    mark = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    d = ImageDraw.Draw(mark)

    def string(a: float, width: float, alpha: int):
        points = [to_px(*p) for half in pose(a) for p in quad(*half)]
        n = len(points) - 1
        rr = width * scale / 2
        layer = Image.new("RGBA", (w, w), (0, 0, 0, 0))
        brush = ImageDraw.Draw(layer)
        for i, (x, y) in enumerate(points):  # a round brush along the curve: smooth, round caps
            t = i / n
            colour = lerp(WAVE_1, STAR, t * 2) if t < 0.5 else lerp(STAR, WAVE_3, t * 2 - 1)
            brush.ellipse((x - rr, y - rr, x + rr, y + rr), fill=colour + (255,))
        layer.putalpha(layer.getchannel("A").point(lambda v: v * alpha // 255))
        mark.alpha_composite(layer)

    string(0, 0.9, 110)    # resting echo
    string(2.4, 1.9, 255)  # the string as the app draws it at rest; slightly bolder for small sizes
    for (x, y), radius, colour in (((8, 29), 2.8, WAVE_2), ((20, 20), 3.2, STAR), ((32, 11), 2.8, WAVE_3)):
        px, py = to_px(x, y)
        rr = radius * scale
        d.ellipse((px - rr, py - rr, px + rr, py + rr), fill=colour + (255,))

    halo = mark.filter(ImageFilter.GaussianBlur(6 * scale / 10))
    halo.putalpha(halo.getchannel("A").point(lambda v: v * 0.45))

    out = Image.alpha_composite(tile, glow)
    out = Image.alpha_composite(out, halo)
    out = Image.alpha_composite(out, mark)
    out.putalpha(ImageChops.multiply(out.getchannel("A"), mask))
    return out.resize((SIZE, SIZE), Image.LANCZOS)


def main() -> None:
    icon = draw()
    icon.save(ROOT / "assets" / "orion-mini-icon.png", optimize=True)
    icon.save(ROOT / "assets" / "orion-mini-icon.ico", sizes=[(s, s) for s in ICO_SIZES], bitmap_format="bmp")  # BMP frames, as Windows tooling expects


if __name__ == "__main__":
    main()
