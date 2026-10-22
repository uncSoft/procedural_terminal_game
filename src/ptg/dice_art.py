"""A pixel-art d20, drawn in code so it can show any number, tumble, and glow.

The die is an icosahedron seen face-on: a hexagon showing ten faces, the light central one holding the
number, the other nine shaded as if lit from the top left. Numbers use a 3x5 pixel font and always sit on
the face with a pixel of margin, so a 20 never runs into an edge. Tumbling frames are the same die turned
in 90 degree steps and bounced, which reads as a roll.
"""

from __future__ import annotations

import math
from functools import lru_cache

from rich.text import Text

from .sprites import Image, image_text

SIZE = 31  # odd, so the centre is a whole pixel: spokes stay one pixel wide and numbers centre exactly
FACE_RATIO = 0.74  # how far the number face's corners reach towards the rim
FACE = (238, 232, 252)
LIT, SHADED = (198, 178, 238), (104, 78, 162)  # the other faces range between these
LIGHT = (-0.5, -0.87)  # from the top left
EDGE = (64, 44, 104)
OUTLINE = (24, 20, 37)
INK = (36, 22, 58)
GOLD = (255, 209, 102)
CRIMSON = (228, 59, 68)

DIGITS = {
    "0": ("111", "101", "101", "101", "111"), "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"), "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"), "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"), "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"), "9": ("111", "101", "111", "001", "111"),
    "?": ("111", "001", "011", "000", "010"),
}


def _inside_hex(dx: float, dy: float, radius: float) -> bool:
    return abs(dx) <= radius * math.sqrt(3) / 2 and abs(dy) <= radius - abs(dx) / math.sqrt(3)


def _inside_triangle(p, a, b, c) -> bool:
    def side(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
    d1, d2, d3 = side(p, a, b), side(p, b, c), side(p, c, a)
    return not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0))


def _near_segment(p, a, b, width: float = 0.55) -> bool:
    (px, py), (ax, ay), (bx, by) = p, a, b
    length2 = (bx - ax) ** 2 + (by - ay) ** 2
    t = max(0.0, min(1.0, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / length2)) if length2 else 0.0
    return math.hypot(px - (ax + t * (bx - ax)), py - (ay + t * (by - ay))) < width


def _shade(triangle, centre: float) -> tuple:
    """A face's colour: brighter the more it turns towards the light."""
    dx = sum(p[0] for p in triangle) / 3 - centre
    dy = sum(p[1] for p in triangle) / 3 - centre
    lit = max(0.0, min(1.0, 0.5 + 0.6 * (dx * LIGHT[0] + dy * LIGHT[1]) / (math.hypot(dx, dy) or 1)))
    return tuple(round(s + (l - s) * lit) for s, l in zip(SHADED, LIT))


@lru_cache(maxsize=1)
def _blank() -> "Image.Image":
    """The die with an empty face."""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    px = img.load()
    c = (SIZE - 1) / 2
    radius = SIZE / 2 - 1

    def point(r: float, degrees: float) -> tuple[float, float]:
        return c + r * math.cos(math.radians(degrees)), c + r * math.sin(math.radians(degrees))

    rim = [point(radius, -90 + 60 * k) for k in range(6)]  # top, then clockwise
    apex, right, left = (point(FACE_RATIO * radius, a) for a in (-90, 30, 150))
    spokes = [(apex, rim[5]), (apex, rim[0]), (apex, rim[1]), (right, rim[1]), (right, rim[2]), (right, rim[3]),
              (left, rim[3]), (left, rim[4]), (left, rim[5])]
    edges = [(apex, left), (left, right), (right, apex), *spokes]
    others = [(apex, rim[0], rim[5]), (apex, rim[0], rim[1]), (apex, rim[5], left), (apex, rim[1], right),
              (left, rim[3], right), (left, rim[5], rim[4]), (right, rim[1], rim[2]), (left, rim[4], rim[3]),
              (right, rim[2], rim[3])]
    shades = [(triangle, _shade(triangle, c)) for triangle in others]
    for y in range(SIZE):
        for x in range(SIZE):
            if not _inside_hex(x - c, y - c, radius):
                continue
            if any(_near_segment((x, y), a, b) for a, b in edges):
                colour = EDGE
            elif _inside_triangle((x, y), apex, left, right):
                colour = FACE
            else:
                colour = next((shade for triangle, shade in shades if _inside_triangle((x, y), *triangle)), SHADED)
            px[x, y] = (*colour, 255)
    _ring(img, OUTLINE)
    return img


@lru_cache(maxsize=1)
def _number_top() -> int:
    """The lowest row where a two-digit number fits on the face with a pixel of clear face all round."""
    px = _blank().load()
    left = (SIZE - 7) // 2

    def clear(top: int) -> bool:
        return all(px[x, y][:3] == FACE for y in range(top - 1, top + 6) for x in range(left - 1, left + 8)
                   if not (y in (top - 1, top + 5) and x in (left - 1, left + 7)))  # corners may touch
    return next(top for top in range(SIZE - 6, 0, -1) if clear(top))


def _ring(img, colour: tuple) -> None:
    """Paint a one-pixel ring just outside the opaque pixels."""
    px = img.load()
    solid = {(x, y) for y in range(img.height) for x in range(img.width) if px[x, y][3]}
    for y in range(img.height):
        for x in range(img.width):
            if (x, y) not in solid and any((x + dx, y + dy) in solid for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                px[x, y] = (*colour, 255)


def die_image(value: int | None, turn: int = 0, bounce: int = 0, glow: tuple | None = None, dim: bool = False):
    """The die showing `value` (None shows "?"), turned `turn` quarter-turns, raised `bounce` pixels (0-2)."""
    img = _blank().copy()
    px = img.load()
    label = "?" if value is None else str(value)
    left, top = (SIZE - (len(label) * 4 - 1)) // 2, _number_top()
    for i, ch in enumerate(label):
        for row, bits in enumerate(DIGITS[ch]):
            for col, bit in enumerate(bits):
                if bit == "1":
                    px[left + i * 4 + col, top + row] = (*INK, 255)
    if turn % 4:
        img = img.rotate(-90 * (turn % 4))
    canvas = Image.new("RGBA", (SIZE + 2, SIZE + 3), (0, 0, 0, 0))  # room for the glow, and to bounce
    canvas.alpha_composite(img, (1, 2 - bounce))
    if glow:
        _ring(canvas, glow)
    if dim:
        pixels = canvas.load()
        for y in range(canvas.height):
            for x in range(canvas.width):
                r, g, b, a = pixels[x, y]
                if a:
                    lum = (r * 3 + g * 6 + b) // 10
                    pixels[x, y] = (lum * 2 // 5, lum * 2 // 5, lum // 2, a)
    return canvas


@lru_cache(maxsize=512)
def d20(value: int | None, turn: int = 0, bounce: int = 0, glow: tuple | None = None, dim: bool = False) -> Text:
    return image_text(die_image(value, turn, bounce, glow, dim))
