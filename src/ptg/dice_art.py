"""A pixel-art d20, drawn in code so it can show any number, tumble, and glow.

The die is an icosahedron seen face-on: a hexagon showing ten faces, the light central one holding the
number, the other nine shaded as if lit from the top left. Numbers use a 3x5 pixel font and always sit on
the face with a pixel of margin, so a 20 never runs into an edge. Tumbling frames are the same die turned
in 90 degree steps and bounced, which reads as a roll. It comes in two sizes: SIZE, and SMALL_SIZE for a tiny
screen (the smallest that still holds a 20 on its face).
"""

from __future__ import annotations

import math
from functools import lru_cache

from rich.text import Text

from .sprites import Image, image_text

SIZE = 31  # odd, so the centre is a whole pixel: spokes stay one pixel wide and numbers centre exactly
SMALL_SIZE = 27  # two rows shorter, for a tiny screen; smaller than this, a 20 no longer fits on its face
FACE_RATIO = 0.74  # how far the number face's corners reach towards the rim
FACE = (238, 232, 252)
LIT, SHADED = (198, 178, 238), (104, 78, 162)  # the other faces range between these
LIGHT = (-0.5, -0.87)  # from the top left
EDGE = (64, 44, 104)
OUTLINE = (24, 20, 37)
INK = (36, 22, 58)
GOLD = (255, 209, 102)
SPARK = (255, 247, 214)  # a critical's sparkles, at their brightest
CRIMSON = (228, 59, 68)

DIGITS = {
    "0": ("111", "101", "101", "101", "111"), "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"), "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"), "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"), "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"), "9": ("111", "101", "111", "001", "111"),
    "?": ("111", "001", "011", "000", "010"),
}
# The same pixels for words, 3 across (M, N and W wider, to read as themselves) and 5 down: the dice screen's target
# and verdict, stamped big (see lettering).
LETTERS = {
    "A": ("010", "101", "111", "101", "101"), "B": ("110", "101", "110", "101", "110"),
    "C": ("011", "100", "100", "100", "011"), "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "111", "100", "111"), "F": ("111", "100", "111", "100", "100"),
    "G": ("011", "100", "111", "101", "011"), "H": ("101", "101", "111", "101", "101"),
    "I": ("111", "010", "010", "010", "111"), "J": ("001", "001", "001", "101", "010"),
    "K": ("101", "101", "110", "101", "101"), "L": ("100", "100", "100", "100", "111"),
    "M": ("10001", "11011", "10101", "10001", "10001"), "N": ("1001", "1101", "1011", "1001", "1001"),
    "O": ("010", "101", "101", "101", "010"), "P": ("110", "101", "110", "100", "100"),
    "Q": ("010", "101", "101", "111", "011"), "R": ("110", "101", "111", "110", "101"),
    "S": ("011", "100", "010", "001", "110"), "T": ("111", "010", "010", "010", "010"),
    "U": ("101", "101", "101", "101", "011"), "V": ("101", "101", "101", "010", "010"),
    "W": ("10001", "10001", "10101", "11011", "10001"), "X": ("101", "101", "010", "101", "101"),
    "Y": ("101", "101", "010", "010", "010"), "Z": ("111", "001", "010", "100", "111"),
    "!": ("010", "010", "010", "000", "010"), "'": ("010", "010", "000", "000", "000"),
    "-": ("000", "000", "111", "000", "000"), "+": ("000", "010", "111", "010", "000"),
    ".": ("000", "000", "000", "000", "010"), **DIGITS,
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


@lru_cache(maxsize=2)
def _blank(size: int = SIZE) -> "Image.Image":
    """The die with an empty face, `size` pixels across."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()
    c = (size - 1) / 2
    radius = size / 2 - 1

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
    for y in range(size):
        for x in range(size):
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


@lru_cache(maxsize=2)
def _number_top(size: int = SIZE) -> int:
    """The lowest row where a two-digit number fits on the face with a pixel of clear face all round."""
    px = _blank(size).load()
    left = (size - 7) // 2

    def clear(top: int) -> bool:
        return all(px[x, y][:3] == FACE for y in range(top - 1, top + 6) for x in range(left - 1, left + 8)
                   if not (y in (top - 1, top + 5) and x in (left - 1, left + 7)))  # corners may touch
    return next(top for top in range(size - 6, 0, -1) if clear(top))


def _ring(img, colour: tuple) -> None:
    """Paint a one-pixel ring just outside the opaque pixels."""
    px = img.load()
    solid = {(x, y) for y in range(img.height) for x in range(img.width) if px[x, y][3]}
    for y in range(img.height):
        for x in range(img.width):
            if (x, y) not in solid and any((x + dx, y + dy) in solid for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                px[x, y] = (*colour, 255)


def _burst(canvas, centre: tuple[float, float], radius: float, frame: int) -> None:
    """A critical's light around the die (`frame` 1-3, spreading): eight gold rays from its rim, a sparkle between
    each pair."""
    px = canvas.load()

    def put(x: float, y: float, colour: tuple) -> None:
        x, y = round(x), round(y)
        if 0 <= x < canvas.width and 0 <= y < canvas.height:
            px[x, y] = (*colour, 255)

    for k in range(8):
        angle = math.radians(k * 45 - 90)
        for r in range(int(radius) + 1, int(radius) + 1 + frame + 1):
            put(centre[0] + r * math.cos(angle), centre[1] + r * math.sin(angle), GOLD if r % 2 else SPARK)
        angle = math.radians(k * 45 - 67.5)
        x, y = centre[0] + (radius + frame) * math.cos(angle), centre[1] + (radius + frame) * math.sin(angle)
        for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)) if frame >= 2 else ((0, 0),):
            put(x + dx, y + dy, SPARK if (dx, dy) == (0, 0) else GOLD)


def die_image(value: int | None, turn: int = 0, bounce: int = 0, glow: tuple | None = None, dim: bool = False,
              size: int = SIZE, pad: int = 0, burst: int = 0):
    """The die showing `value` (None shows "?"), turned `turn` quarter-turns, raised `bounce` pixels (0-2), `size`
    pixels across, with `pad` pixels of room all round (for `burst`, a critical's light: see _burst)."""
    img = _blank(size).copy()
    px = img.load()
    label = "?" if value is None else str(value)
    left, top = (size - (len(label) * 4 - 1)) // 2, _number_top(size)
    for i, ch in enumerate(label):
        for row, bits in enumerate(DIGITS[ch]):
            for col, bit in enumerate(bits):
                if bit == "1":
                    px[left + i * 4 + col, top + row] = (*INK, 255)
    if turn % 4:
        img = img.rotate(-90 * (turn % 4))
    canvas = Image.new("RGBA", (size + 2 + 2 * pad, size + 3 + 2 * pad), (0, 0, 0, 0))  # room for the glow, and to
    # bounce
    if burst:
        _burst(canvas, (pad + 1 + (size - 1) / 2, pad + 2 + (size - 1) / 2), size / 2, burst)
    canvas.alpha_composite(img, (1 + pad, 2 - bounce + pad))
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
def d20(value: int | None, turn: int = 0, bounce: int = 0, glow: tuple | None = None, dim: bool = False,
        size: int = SIZE, pad: int = 0, burst: int = 0) -> Text:
    """The die as half-block text, in its own colours. They aren't snapped to the sprites' (see sprites.palette),
    which have nothing near its violet; they are a fixed few already (the faces, edges and number, the glows, and the
    same greyed), whatever it shows and however it's turned, so a GPU terminal's glyph cache stays small anyway."""
    return image_text(die_image(value, turn, bounce, glow, dim, size, pad, burst))


def _advance(ch: str) -> int:
    """How far a letter moves the pen: its pixels and a pixel's gap (a space, two)."""
    return len(LETTERS[ch][0]) + 1 if ch in LETTERS else 2


def lettering_width(words: str, scale: int = 1) -> int:
    """How many columns `words` take in lettering (with the shadow's column)."""
    return sum(_advance(ch) for ch in words.upper()) * scale - scale + 1


@lru_cache(maxsize=64)
def lettering(words: str, colour: tuple, scale: int = 1, shadow: tuple | None = None) -> Text:
    """`words` in the dice's pixel letters (LETTERS: capitals, digits, a little punctuation; anything else a gap),
    each pixel `scale` across and down, in `colour`, with a drop shadow a pixel down and right if `shadow` is given:
    as half-block text, (5 x scale + 1) / 2 rows tall."""
    img = Image.new("RGBA", (lettering_width(words, scale), 5 * scale + 1), (0, 0, 0, 0))
    px = img.load()
    for offset, ink in ((1, shadow), (0, colour)) if shadow else ((0, colour),):
        x = 0
        for ch in words.upper():
            for row, bits in enumerate(LETTERS.get(ch, ())):
                for col, bit in enumerate(bits):
                    if bit == "1":
                        for dy in range(scale):
                            for dx in range(scale):
                                px[x + col * scale + dx + offset, row * scale + dy + offset] = (*ink, 255)
            x += _advance(ch) * scale
    return image_text(img)
