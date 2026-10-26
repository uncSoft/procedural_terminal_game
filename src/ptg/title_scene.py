"""The title screen's picture: a castle on a crag in a thunderstorm, drawn in code like the rooms (room_picture.py), in
the sprites' own palette (Endesga 32), at whatever size the screen has room for.

Everything is drawn once as materials and shades (sky, cloud, stone, roof, rock, ground...), not colours: the light
decides the colours. Each material climbs its own ramp of the palette as the light comes up, so one drawing gives the
dark (the castle a silhouette against the night, a few windows lit), the dim afterglow, and the flash (the stone
white-grey against a white sky, every brick showing). On top of that, per frame: the rain, the bolt, and for the
length of a flash, something standing on the ridge in the foreground (one of the game's own monsters, black against
the sky) that wasn't there a moment ago.

    scene = Scene(width, height)               # pixels; a terminal cell is one pixel wide and two tall
    scene.text(light=DARK, rain=pixels)        # a frame as half-block text (lights: DARK, DIM, BRIGHT, FLASH),
                                               # the rain fallen so far (the whole height round is where it began)
    scene.strike(seed)                         # a new bolt and a new creature for the next flash
"""

from __future__ import annotations

import math
import random
from functools import lru_cache

from rich.text import Text

from . import sprites

try:
    from PIL import Image
except ImportError:  # pragma: no cover (PIL comes with the game; without it there's no picture, just the title)
    Image = None

DARK, DIM, BRIGHT, FLASH = 0, 1, 2, 3
LIGHTS = (DARK, DIM, BRIGHT, FLASH)
LIFT = {DARK: 0, DIM: 1, BRIGHT: 2, FLASH: 4}  # how far up its ramp each light takes a material

# Each material's ramp, darkest first (Endesga 32): its shade is where it sits on it in the dark.
COOL = ("#181425", "#262b44", "#3a4466", "#5a6988", "#8b9bb4", "#c0cbdc", "#ffffff")
RAMPS = {
    "sky": COOL, "cloud": COOL, "far": COOL, "stone": COOL, "rain": COOL,
    "ground": ("#181425", "#181425", "#262b44", "#262b44", "#3a4466"),  # the foreground: always against the light
    "rock": ("#181425", "#3e2731", "#733e39", "#b86f50", "#c28569", "#e4a672"),
    "roof": ("#181425", "#3e2731", "#733e39", "#a22633", "#be4a2f", "#d77643"),
    "flag": ("#3e2731", "#a22633", "#e43b44", "#e43b44", "#f6757a"),
    "glass": ("#181425", "#181425", "#262b44", "#3a4466", "#5a6988"),  # a window with no one behind it
}
LIT = ("#f77622", "#feae34", "#fee761")  # a window someone's awake behind: warm in any light
MOON = ("#c0cbdc", "#ead4aa", "#ffffff")
BOLT, GLOW = "#ffffff", "#2ce8f5"
# Who the flash shows on the ridge, in turn: the game's own, at their scariest.
WATCHERS = ("drowned_abbot", "goblin_king", "thornmother", "skeleton", "wight", "ghoul", "king_mouse",
            "serpentis", "troll", "ghost")


def _hash(x: int, y: int, seed: int) -> float:
    n = (x * 374761393 + y * 668265263 + seed * 2147483647) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return (n ^ (n >> 16)) / 0xFFFFFFFF


def _noise(x: float, y: float, seed: int) -> float:
    """Smooth value noise in 0..1."""
    xi, yi = math.floor(x), math.floor(y)
    fx, fy = x - xi, y - yi
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b = _hash(xi, yi, seed), _hash(xi + 1, yi, seed)
    c, d = _hash(xi, yi + 1, seed), _hash(xi + 1, yi + 1, seed)
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


def _fbm(x: float, y: float, seed: int, octaves: int = 3) -> float:
    total, amp, norm = 0.0, 1.0, 0.0
    for i in range(octaves):
        total += amp * _noise(x * 2 ** i, y * 2 ** i, seed + i * 17)
        norm += amp
        amp *= 0.5
    return total / norm


def _rgb(hex_colour: str) -> tuple[int, int, int, int]:
    return int(hex_colour[1:3], 16), int(hex_colour[3:5], 16), int(hex_colour[5:7], 16), 255


class Scene:
    """The castle in the storm, `width` x `height` pixels (see the module's docstring)."""

    def __init__(self, width: int, height: int, seed: int = 7) -> None:
        self.w, self.h, self.seed = width, height, seed
        self.s = height / 60  # the castle's scale: drawn for a scene 60 pixels tall
        self.mat: list[list[tuple[str, int]]] = [[("sky", 0)] * width for _ in range(height)]
        self.horizon = int(height * 0.74)
        self.bolt: list[tuple[int, int, bool]] = []  # (x, y, core) the next flash's bolt
        self.watcher: str | None = None
        self.watcher_at: tuple[int, int] = (0, 0)
        self._bases: dict[int, Image.Image] = {}
        self._draw()
        self.strike(seed)

    # --- drawing the materials, back to front ------------------------------------------------------------------

    def put(self, x: int, y: int, material: str, shade: int) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            self.mat[y][x] = (material, shade)

    def _draw(self) -> None:
        self._sky()
        self._moon()
        self._clouds()
        self._hills()
        self._crag()
        self._castle()
        self._foreground()

    def at(self, x: float) -> int:
        """A castle-plan x (pixels from the castle's middle, for a scene 60 pixels tall) on this scene."""
        return round(self.w * 0.6 + x * self.s)

    def _sky(self) -> None:
        """Darkest at the top, paler at the horizon: three bands, dithered into each other (no stripes)."""
        bayer = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))
        for y in range(self.h):
            level = 2.6 * min(1.0, y / max(1, self.horizon))
            for x in range(self.w):
                band = int(level + (bayer[y % 4][x % 4] / 16 - 0.5) * 0.5)  # (dithered only near a band's edge)
                self.mat[y][x] = ("sky", max(0, min(2, band)))

    def _moon(self) -> None:
        cx, cy, r = self.w * 0.83, self.h * 0.16, max(2.5, 4.5 * self.s)
        for y in range(int(cy - r - 2), int(cy + r + 3)):
            for x in range(int(cx - r - 2), int(cx + r + 3)):
                d = math.hypot(x - cx, y - cy)
                if d <= r:
                    crater = _hash(x, y, 3) > 0.84 and d < r - 1
                    self.put(x, y, "moon", 0 if crater else (2 if d < r * 0.5 else 1))
                elif d <= r + 1.5 and 0 <= y < self.h and 0 <= x < self.w:
                    self.put(x, y, "sky", 3)  # its halo

    def _clouds(self) -> None:
        top = int(self.h * 0.42)
        for y in range(top):
            for x in range(self.w):
                n = _fbm(x / (16 * self.s + 4), y / (4 * self.s + 2) + 3, self.seed)
                edge = 0.5 + 0.2 * (y / top)  # thinning out lower down
                if n > edge:
                    lining = n - edge < 0.045  # the ragged edge catches the moon (and the flash)
                    self.put(x, y, "cloud", 3 if lining else (2 if n < edge + 0.12 else 1))

    def _hills(self) -> None:
        for x in range(self.w):
            ridge = self.horizon - int((2 + 4 * _fbm(x / 20, 0.5, self.seed + 5)) * self.s)
            for y in range(ridge, self.h):
                self.put(x, y, "far", 1 if y > ridge else 2)

    def _crag(self) -> None:
        """The rock the castle stands on: as wide as the castle at the top, flaring out as it goes down, lit on its
        left face, its strata running across it in cracks."""
        top, cx = self.horizon - int(6 * self.s), self.at(1)
        for y in range(top, self.h):
            t = (y - top) / max(1, self.h - top)
            left = cx - (23 + 26 * t ** 1.4 + 3 * _noise(y / 3, 1, self.seed + 9)) * self.s
            right = cx + (25 + 30 * t ** 1.4 + 3 * _noise(y / 3, 7, self.seed + 9)) * self.s
            for x in range(int(left), int(right) + 1):
                shade = 1 if x < cx - 0.2 * (cx - left) else 0
                if _noise((x + y * 1.6) / 5, y / 2.2, self.seed + 11) < 0.24:  # a crack along the strata
                    shade = 0 if shade else 1
                if x <= left + 1:
                    shade = 2  # the edge the moon catches
                self.put(x, y, "rock", shade)

    def _castle(self) -> None:
        base = self.horizon - int(6 * self.s)
        self._wall(-18, 21, base, 8)
        # (left, width, height, roof): left to right, for a scene 60 pixels tall
        for left, width, height, roof in ((-21, 5, 15, 6), (-11, 3, 12, 0), (-5, 11, 20, 7), (8, 3, 13, 0),
                                          (12, 6, 22, 8), (20, 3, 11, 4)):
            self._tower(left, width, base, height, roof)
        self._gate(0.5, base, 4, 6)

    def _wall(self, x0: float, x1: float, base: int, height: float) -> None:
        left, right, top = self.at(x0), self.at(x1), base - int(height * self.s)
        for y in range(top, base + 1):
            for x in range(left, right + 1):
                self._stone(x, y, left, right, top)
        for x in range(left, right + 1):  # its battlements
            if (x - left) % 3 != 2:
                self.put(x, top - 1, "stone", 1)

    def _tower(self, x0: float, width: float, base: int, height: float, roof: float) -> None:
        left, right, top = self.at(x0), self.at(x0 + width), base - int(height * self.s)
        for y in range(top, base + 1):
            for x in range(left, right + 1):
                self._stone(x, y, left, right, top)
        mid = (left + right) / 2
        if roof:  # a cone, and a flag on its tip
            peak = top - int(roof * self.s)
            for y in range(peak, top):
                half = (right - left + 3) / 2 * (y - peak + 1) / (top - peak)
                for x in range(round(mid - half), round(mid + half) + 1):
                    self.put(x, y, "roof", 2 if x < mid - half / 3 else (1 if x <= mid + half / 3 else 0))
            pole = round(mid)
            tall = max(2, int(3 * self.s))
            for dy in range(1, tall + 1):
                self.put(pole, peak - dy, "stone", 3)
            for dx in range(1, max(2, int(3 * self.s)) + 1):
                self.put(pole + dx, peak - tall + (dx // 2) % 2, "flag", 1)
        else:  # battlements
            for x in range(left - 1, right + 2):
                if (x - left) % 2 == 0:
                    self.put(x, top - 1, "stone", 1)
        storey = max(4, int(6 * self.s))
        for i, wy in enumerate(range(top + 2, base - 3, storey)):  # a window a storey, some of them lit
            lit = _hash(left, i, self.seed + 21) > 0.45
            for dy in range(max(2, int(2 * self.s))):
                self.put(round(mid), wy + dy, "window" if lit else "glass", 0 if dy else 1)

    def _stone(self, x: int, y: int, left: int, right: int, top: int) -> None:
        """Masonry, rounded by the light: the left edge catches the moon, the right is in shadow; mortar between
        courses two pixels high, each course's joints set off from the last."""
        across = (x - left) / max(1, right - left)
        shade = 2 if across < 0.25 else (1 if across < 0.7 else 0)
        row, course = (y - top) % 3, (y - top) // 3
        if row == 2 or (x - left + 2 * (course % 2)) % 4 == 3:
            shade = max(0, shade - 1)  # mortar
        if x == left:
            shade = 3  # moonlit edge
        self.put(x, y, "stone", shade)

    def _gate(self, x0: float, base: int, width: float, height: float) -> None:
        cx, half, top = self.at(x0), width * self.s / 2, base - int(height * self.s)
        for y in range(top, base + 1):
            for x in range(int(cx - half), int(cx + half) + 1):
                dx = (x - cx) / max(0.5, half)
                if y >= top + half * (1 - math.sqrt(max(0.0, 1 - dx * dx))):
                    self.put(x, y, "glass", 0)

    def ridge(self, x: int) -> int:
        """The top of the near ground at x: a ridge rising to the left, where the watcher stands."""
        rise = (3 + 4 * _fbm(x / 14, 2.5, self.seed + 31)) * self.s
        hill = max(0.0, 1 - x / (self.w * 0.34)) * 14 * self.s
        return self.h - int(rise + hill)

    def _foreground(self) -> None:
        """The near ground (always against the light), a dead tree on the ridge."""
        for x in range(self.w):
            top = self.ridge(x)
            for y in range(top, self.h):
                self.put(x, y, "ground", 1 if y == top else 0)
        tree = int(self.w * 0.05)
        self._tree(tree, self.ridge(tree), int(20 * self.s))
        spot = int(self.w * 0.2)
        self.watcher_at = (spot, self.ridge(spot))

    def _tree(self, x: int, y: int, height: int) -> None:
        rng = random.Random(self.seed + 41)

        def branch(bx: float, by: float, angle: float, length: float, depth: int) -> None:
            for _ in range(max(1, int(length))):
                bx += math.cos(angle)
                by -= math.sin(angle)
                self.put(int(bx), int(by), "ground", 1)
                if depth == 0:
                    self.put(int(bx) + 1, int(by), "ground", 1)
            if depth < 3 and length > 2:
                for turn in (-0.7, 0.55):
                    branch(bx, by, angle + turn + rng.uniform(-0.25, 0.25), length * 0.6, depth + 1)

        branch(x, y, math.pi / 2 - 0.05, height * 0.5, 0)

    # --- a flash's bolt, and who it shows -------------------------------------------------------------------------

    def strike(self, seed: int) -> None:
        """A new bolt, from the clouds down to the tallest tower's spire or the hills, branching; and the next
        watcher on the ridge."""
        rng = random.Random(seed)
        spire = (self.at(15), self.horizon - int((6 + 22 + 8 + 3) * self.s))  # the tall tower's flagpole
        if rng.random() < 0.25:
            end = (spire[0], max(2, spire[1]))
        else:
            side = rng.choice((rng.randrange(int(self.w * 0.25), max(int(self.w * 0.25) + 1, self.at(-28))),
                               rng.randrange(min(self.w - 3, self.at(30)), self.w - 2)))
            end = (side, self.horizon - int(3 * self.s))
        x, y = end[0] + rng.randint(-int(10 * self.s) - 2, int(10 * self.s) + 2), 0
        path = []
        while y < end[1]:
            path.append((x, y, True))
            y += 1
            x += rng.choice((-1, 0, 1)) + (1 if x < end[0] and rng.random() < 0.35 else 0) - \
                (1 if x > end[0] and rng.random() < 0.35 else 0)
            if rng.random() < 0.07 and y < end[1] * 0.7:  # a branch, fizzling out
                bx, by, direction = x, y, rng.choice((-1, 1))
                for _ in range(rng.randint(3, 6 + int(4 * self.s))):
                    bx += direction * rng.choice((0, 1, 1))
                    by += 1
                    path.append((bx, by, False))
        self.bolt = path
        self.watcher = WATCHERS[seed % len(WATCHERS)]

    # --- colours --------------------------------------------------------------------------------------------------

    def colour(self, material: str, shade: int, light: int) -> str:
        if material == "window":
            return LIT[min(2, shade + (light == FLASH))]
        if material == "moon":
            return MOON[shade]
        ramp = RAMPS[material]
        return ramp[min(len(ramp) - 1, shade + LIFT[light])]

    def base(self, light: int):
        """The scene in a light, without the rain, the bolt or the watcher (kept: they're reused every frame)."""
        if light not in self._bases:
            img = Image.new("RGBA", (self.w, self.h))
            px = img.load()
            for y in range(self.h):
                for x in range(self.w):
                    px[x, y] = _rgb(self.colour(*self.mat[y][x], light))
            self._bases[light] = img
        return self._bases[light]

    def image(self, light: int = DARK, rain: int = 0, bolt: bool = False, watcher: bool = False):
        img = self.base(light).copy()
        px = img.load()
        drop = _rgb(RAMPS["rain"][min(6, 2 + LIFT[light])])
        span = self.w + self.h // 2
        for i in range(int(self.w * self.h / 70)):  # the rain: short slanting streaks, `rain` pixels further down
            x0, y0 = int(_hash(i, 1, self.seed) * span), int(_hash(i, 2, self.seed) * self.h) + rain
            for k in range(2):
                y = (y0 + k) % self.h  # (wrapping round: fallen the whole height, it's where it started)
                x = (x0 - y // 2) % span
                if x < self.w and self.mat[y][x][0] != "window":
                    px[x, y] = drop
        if watcher and self.watcher:
            self._watcher(img, light)
        if bolt:
            for x, y, core in self.bolt:
                for dx, dy in ((0, 0), (-1, 0), (1, 0)) if core else ((0, 0),):
                    if 0 <= x + dx < self.w and 0 <= y + dy < self.h:
                        px[x + dx, y + dy] = _rgb(BOLT if (dx, dy) == (0, 0) else GLOW)
        return img

    def _watcher(self, img, light: int) -> None:
        """Whoever the flash shows on the ridge: black against the sky (at the flash's height, their own colours)."""
        frames = sprites.frames(self.watcher, max(8, int(20 * self.s)))
        if not frames:
            return
        figure = frames[0]
        bottom = max(y for y in range(figure.height) for x in range(figure.width) if figure.getpixel((x, y))[3] > 128)
        fx, fy = self.watcher_at[0] - figure.width // 2, self.watcher_at[1] - bottom
        dark = _rgb("#181425")
        fpx, px = figure.load(), img.load()
        for y in range(figure.height):
            for x in range(figure.width):
                r, g, b, a = fpx[x, y]
                if a > 128 and 0 <= fx + x < self.w and 0 <= fy + y < self.h:
                    px[fx + x, fy + y] = (r, g, b, 255) if light == FLASH else dark

    def text(self, light: int = DARK, rain: int = 0, bolt: bool = False, watcher: bool = False) -> Text:
        return sprites.image_text(self.image(light, rain, bolt, watcher), snap=True)


@lru_cache(maxsize=4)
def scene(width: int, height: int) -> Scene | None:
    """The scene at a size (one is kept for each of the last few sizes asked for), or None without PIL."""
    if Image is None or width < 20 or height < 12:
        return None
    return Scene(width, height)
