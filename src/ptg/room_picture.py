"""Pictures of rooms: what you see from the doorway you came in by, drawn in code from the room itself.

The engine owns the room (see layout): its walls, exits, decor, features, fixture, monster and items. This draws
them as pixel art in one-point perspective, for the story card you get the first time you walk into a room and
for the Look panel (F4):

    walls, floor, ceiling     the dungeon's own look: the Crypt's bricks and candles, the Warren's earth, timber
                              and torches, the Ruins' marble (broken, under the stars, if the room's decor says sky)
    exits                     doorways in the walls they're in: dark if unexplored, planked if locked
    decor                     the room map's water, pillars, tables, cages, shelves, plants, fungus, roots...
    features                  small props by their kind (a pew, a barrel, a cauldron, a throne, a coffin...)
    fixture, monster, items   their own sprites, smaller further back
    light                     the lantern you carry, candles and torches, glowing things, moonlight

Sizes are a stage set's, not a surveyor's: drawn to the scale of the floor plan a goblin would be two pixels wide,
so things are bigger than the plan says, and a monster steps toward the middle so it doesn't stand in a doorway.
Every colour is snapped to one the sprites use (sprites.palette()), so a GPU terminal's glyph cache meets nothing
new (see PTGApp.action_redraw).

    uv run python -m ptg.room_picture 7       # every room on the first floor of seed 7, in your terminal
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass

from rich.text import Text

from . import layout, sprites
from .content import Content
from .models import GameState, Room
from .sprites import Image

WIDTH, HEIGHT = layout.WIDTH, layout.HEIGHT
CX, CY = WIDTH // 2 + 1, HEIGHT // 2 + 1  # the room's centre cell, where a fixture stands


def _rgb(hexcode: str) -> tuple:
    return tuple(int(hexcode[i:i + 2], 16) for i in (1, 3, 5))


def _ramp(*hexcodes: str) -> list:
    return [_rgb(h) for h in hexcodes]


DARK = _rgb("#181425")
FLAME = _ramp("#be4a2f", "#f77622", "#feae34", "#fee761")


@dataclass(frozen=True)
class Look:
    """How a dungeon is drawn. Ramps run dark to light; the warm ones are for what candles and torches light."""
    wall: list
    wall_warm: list
    floor: list
    floor_warm: list
    ceiling: list
    water: list
    wood: list
    stone: list
    moss: list
    walls: str  # bricks | earth | marble
    ground: str  # flags | dirt | mosaic
    above: str  # vault | rock
    ambient: float
    lantern: float
    sconces: str  # candles | torches | ""
    fog: float
    accent: str  # the story card's border


LOOKS = {
    "sunken_crypt": Look(
        wall=_ramp("#181425", "#262b44", "#3a4466", "#5a6988", "#8b9bb4"),
        wall_warm=_ramp("#181425", "#3e2731", "#733e39", "#b86f50", "#e4a672"),
        floor=_ramp("#181425", "#262b44", "#3a4466", "#5a6988"),
        floor_warm=_ramp("#181425", "#3e2731", "#733e39", "#b86f50"),
        ceiling=_ramp("#181425", "#262b44", "#3a4466"),
        water=_ramp("#181425", "#124e89", "#0099db", "#2ce8f5"),
        wood=_ramp("#3e2731", "#733e39", "#b86f50", "#c28569"),
        stone=_ramp("#262b44", "#3a4466", "#5a6988", "#8b9bb4", "#c0cbdc"),
        moss=_ramp("#193c3e", "#265c42", "#3e8948", "#63c74d"),
        walls="bricks", ground="flags", above="vault", ambient=0.10, lantern=0.70, sconces="candles", fog=0.45,
        accent="#0099db"),
    "goblin_warren": Look(
        wall=_ramp("#181425", "#3e2731", "#733e39", "#b86f50", "#c28569"),
        wall_warm=_ramp("#181425", "#733e39", "#be4a2f", "#d77643", "#e4a672"),
        floor=_ramp("#181425", "#3e2731", "#733e39", "#b86f50"),
        floor_warm=_ramp("#181425", "#733e39", "#be4a2f", "#d77643"),
        ceiling=_ramp("#181425", "#3e2731", "#733e39"),
        water=_ramp("#181425", "#193c3e", "#265c42", "#3e8948"),
        wood=_ramp("#3e2731", "#733e39", "#be4a2f", "#d77643"),
        stone=_ramp("#2e303e", "#525668", "#7a7e90", "#a6aaba", "#d2d4de"),
        moss=_ramp("#3e2731", "#733e39", "#c2a078", "#e4a672"),  # straw
        walls="earth", ground="dirt", above="rock", ambient=0.12, lantern=0.65, sconces="torches", fog=0.40,
        accent="#d77643"),
    "overgrown_ruins": Look(
        wall=_ramp("#262b44", "#525668", "#7a7e90", "#a6aaba", "#d2d4de"),
        wall_warm=_ramp("#262b44", "#525668", "#7a7e90", "#a6aaba", "#d2d4de"),
        floor=_ramp("#181425", "#2e303e", "#525668", "#7a7e90", "#a6aaba"),
        floor_warm=_ramp("#181425", "#2e303e", "#525668", "#7a7e90", "#a6aaba"),
        ceiling=_ramp("#181425", "#262b44", "#3a4466"),
        water=_ramp("#181425", "#124e89", "#0099db", "#2ce8f5", "#96e6ff"),
        wood=_ramp("#3e2731", "#733e39", "#b86f50", "#c28569"),
        stone=_ramp("#2e303e", "#525668", "#7a7e90", "#a6aaba", "#d2d4de"),
        moss=_ramp("#193c3e", "#265c42", "#3e8948", "#63c74d"),
        walls="marble", ground="mosaic", above="vault", ambient=0.30, lantern=0.45, sconces="", fog=0.30,
        accent="#63c74d"),
}
DEFAULT_LOOK = LOOKS["sunken_crypt"]  # for a dungeon added without a look of its own


def look_of(theme: str) -> Look:
    return LOOKS.get(theme, DEFAULT_LOOK)


# --- pixel helpers ------------------------------------------------------------------------------------------

def _hash01(*keys) -> float:
    """A repeatable pseudo-random number in [0, 1) for these keys."""
    h = 2166136261
    for k in keys:
        h = ((h ^ (int(k) & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 0x5BD1E995) & 0xFFFFFFFF
    h ^= h >> 15
    return h / 4294967296


def _noise(x: float, y: float, seed: int = 0) -> float:
    """Smooth value noise in [0, 1)."""
    xi, yi = math.floor(x), math.floor(y)
    xf, yf = x - xi, y - yi
    xf, yf = xf * xf * (3 - 2 * xf), yf * yf * (3 - 2 * yf)
    top = _hash01(xi, yi, seed) + (_hash01(xi + 1, yi, seed) - _hash01(xi, yi, seed)) * xf
    bottom = _hash01(xi, yi + 1, seed) + (_hash01(xi + 1, yi + 1, seed) - _hash01(xi, yi + 1, seed)) * xf
    return top + (bottom - top) * yf


def _bayer(x: int, y: int) -> float:
    return (sprites.BAYER[y % 4][x % 4] + 0.5) / 16


def _pick(shades: list, level: float, x: int, y: int, dither: float = 0.45) -> tuple:
    """The shade for a light level in [0, 1]: flat bands, ordered-dithered only where one meets the next."""
    value = max(0.0, min(1.0, level)) * (len(shades) - 1)
    return shades[max(0, min(len(shades) - 1, math.floor(value + 0.5 + (_bayer(x, y) - 0.5) * dither)))]


def _darker(colour: tuple, k: float) -> tuple:
    return sprites._nearest(tuple(int(c * k) for c in colour))


# --- where things are, seen from the door you came in by ----------------------------------------------------

class View:
    """Room cells as (a, z): a across (negative is left), z away from you; and which wall each side's door is in."""

    SIDES = {
        "south": {"north": "back", "west": "left", "east": "right", "south": "behind"},
        "north": {"south": "back", "east": "left", "west": "right", "north": "behind"},
        "west": {"east": "back", "north": "left", "south": "right", "west": "behind"},
        "east": {"west": "back", "south": "left", "north": "right", "east": "behind"},
    }

    def __init__(self, room: Room) -> None:
        self.came = room.entered_from if room.entered_from in self.SIDES else "south"
        across = self.came in ("south", "north")
        self.depth, self.half = (float(HEIGHT), WIDTH / 2) if across else (float(WIDTH), HEIGHT / 2)
        self.side = self.SIDES[self.came]

    def cell(self, x: float, y: float) -> tuple[float, float]:
        return {"south": (x - CX, HEIGHT + 0.5 - y), "north": (CX - x, y - 0.5),
                "west": (y - CY, x - 0.5), "east": (CY - y, WIDTH + 0.5 - x)}[self.came]

    def grid_at(self, a: float, z: float) -> tuple[float, float]:
        return {"south": (a + CX, HEIGHT + 0.5 - z), "north": (CX - a, z + 0.5),
                "west": (z + 0.5, a + CY), "east": (WIDTH + 0.5 - z, CY - a)}[self.came]


class Lens:
    """One composition for every room: the far wall a little above the middle, the floor filling the lower half,
    the side walls running out past the edges."""

    def __init__(self, w: int, h: int, view: View) -> None:
        self.w, self.h = w, h
        self.depth, self.half = view.depth, view.half
        self.d = 0.7 * self.depth
        self.sb = self.s(self.depth)
        self.kx = 0.62 * w / self.half
        self.yh, self.yn, self.yt = 0.30 * h, h + 1.0, -0.10 * h

    def s(self, z: float) -> float:
        """How much smaller things are at depth z (1 at the door you came in by)."""
        return self.d / (max(z, -0.5 * self.d) + self.d)

    def x(self, a: float, s: float) -> float:
        return self.w / 2 + a * self.kx * s

    def floor_y(self, s: float) -> float:
        return self.yh + (self.yn - self.yh) * s

    def ceil_y(self, s: float) -> float:
        return self.yh - (self.yh - self.yt) * s

    def at(self, a: float, z: float, v: float = 0.0) -> tuple[float, float]:
        """Where a point v of the way up the walls, at (a, z), lands on the picture."""
        s = self.s(z)
        fy = self.floor_y(s)
        return self.x(a, s), fy - v * (fy - self.ceil_y(s))

    def scale(self, z: float) -> float:
        """How big a sprite should be here: 1 is full size."""
        return self.s(z) * 1.15 * self.h / 32


# --- props: a room's features, drawn by their kind ---------------------------------------------------------

PROPS = {
    "table": ["cccccccccccc", "bbbbbbbbbbbb", ".a........a.", ".a........a.", ".a........a."],
    "pew": ["c..............c", "cccccccccccccccc", "b..............b", "cccccccccccccccc", "bbbbbbbbbbbbbbbb",
            "a.a..........a.a", "a.a..........a.a"],
    "bench": ["gGhgGgGhgGgG", "888888888888", "777777777777", ".66......66.", ".66......66.", ".55......55."],
    "barrel": ["..bbbbbb..", ".bccccccb.", ".mMmmmmMm.", ".bccccccb.", ".bccccccb.", ".bccccccb.", ".mMmmmmMm.",
               ".abbbbbba.", "..aaaaaa.."],
    "cauldron": ["....s...s...", "...s...s....", "....s...s...", ".MMMMMMMMMM.", "MgGhGgGhGgGm", ".Mmmmmmmmmn.",
                 "Mmmmmmmmmmnn", "Mmmmmmmmmmnn", ".mmmmmmmmnn.", "..nnnnnnnn..", "..n.fF.f.n..", ".fFYYFYFYFf."],
    "statue": ["....88....", "...8998...", "....88....", "..788887..", ".78899887.", ".7.8998.7.", "...8998...",
               "...7887...", "...7..7...", "..666666..", ".55555555.", ".56666665."],
    "candle": [".Y.", "FYF", ".B.", ".B.", "mMm", ".m.", ".m.", ".m.", "mmm"],
    "lantern": ["..m..", ".mMm.", "mYFYm", "mFYFm", "mYFYm", ".mmm."],
    "wardrobe": ["bbbbbbbb", "bcccbccc", "bcccbccc", "bcmcbcmc", "bcccbccc", "bcccbccc", "bbbbbbbb", "a......a"],
    "basin": ["7~~~~~~~~7", ".7~=~~~~7.", "..777777..", "...6666...", "....66....", "...5555..."],
    "trough": ["bccccccccccb", "ab~~~=~~~~ba", "aabbbbbbbbaa", ".a........a."],
    "crate": ["bbbbbbbb", "bmbbbbmb", "bccccccb", "bcmccmcb", "bccccccb", "bmbbbbmb", "bbbbbbbb"],
    "bones": ["...BBB......", "..BkBkB.....", "..BBBBB.B..B", ".BeB.BBeBBeB", "BeBBeBBeBBB."],
    "rail": ["cccccccccccccccc", "b..b..b..b..b..b", "b..b..b..b..b..b", "a..a..a..a..a..a"],
    "case": ["eMMMMMMMMe", "M=.k.k..=M", "M.k...k..M", "Mk..k...kM", "MMMMMMMMMM", "ab......ba", "ab......ba"],
    "grate": ["nmnmnmnmnm", "mnmnmnmnmn", "nmnmnmnmnm"],
    "hole": [".kkkkkk.", "kkkkkkkk", ".kkkkkk."],
    "mosaic": ["uRyuRyuR", "RyuRyuRy", "yuRyuRyu"],
    "cart": ["..bbbbbbbbb.", ".bcccccccccb", ".bbbbbbbbbb.", "..a......a..", ".mMm....mMm.", "..m......m.."],
    "shelf": ["aaaaaaaaaaaa", "aRuPcBRuGcBa", "aaaaaaaaaaaa", "acBRu.GPcRua", "aaaaaaaaaaaa", "aGcRBuPc.Bua",
              "aaaaaaaaaaaa", "a..........a"],
    "niche": ["..7777..", ".788887.", "78kkkk87", "7kBBkkk7", "7kBkBkk7", "7kBBBkk7", "77777777"],
    "coffin": ["...bbbbbb...", "..bccccccb..", ".bccccccccb.", "bcccccdccccb", ".bccccccccb.", "..bbbbbbbb.."],
    "bell": ["....qq....", "...qQQq...", "..qQQQQq..", "..qQqQQq..", ".qQQQQQQq.", ".qQQQkQQq.", "bbbbbbbbbb"],
    "rope": ["..cddc..", ".cd..dc.", "cd.cc.dc", "c.d..d.c", ".cddddc."],
    "vines": ["..g.h..g.", ".gGgGhgG.", "gGh.gGgGg", ".gGgGg.hg", "gG.gGhgGg"],
    "plates": ["..eeeeee..", ".eBBBBBBe.", "..eeeeee..", ".eBBBBBBe.", "..eeeeee..", ".eBBBBBBe.", "..eeeeee.."],
    "cage": ["mmmmmmmmmm", "m.m.m.m.mm", "m.m.m.m.mm", "m.m.m.m.mm", "m.m.m.m.mm", "mmmmmmmmmm"],
    "junk": ["....R.....", "..cbm.y...", ".BmcbRbm..", "cbmyRcbmc.", "bmcbmBcbmb"],
    "sack": ["...bb...", "..qbbq..", ".qqqqqq.", "qqqQqqqq", "qqqqqqQq", ".bbbbbb."],
    "rack": ["aaaaaaaaaaaa", "aMa.Ma.aMa.a", "aMa.Ma.aMa.a", "aMa.Ma.aMa.a", "aba.ba.aba.a", "aaaaaaaaaaaa",
             "a..........a"],
    "gong": ["a........a", "aaaaaaaaaa", "a..qQQq..a", "a.qQyyQq.a", "a.qyQQyq.a", "a.qQyyQq.a", "a..qqqq..a",
             "a........a"],
    "puffball": ["...eeee...", "..eBBBBe..", ".eBBeBBBe.", ".eBBBBeBe.", ".eBeBBBBe.", "..eBBBBe..", "...ssss..."],
    "bedroll": ["..RRRRRRRR..", ".RuRRRRRRuR.", "RRuRRRRRRuRR", ".RRRRRRRRRR."],
    "boots": ["bb...bb...", "bb...bb.bb", "bbc..bbcbb", "bbbb.bbbbb", "aaaa.aaaaa"],
    "forge": ["..fF.Yf.F...", ".FYfFYFfYF..", "mMMMMMMMMMMm", "mrfFrfFrFfrm", "mmmmmmmmmmmm", ".mm......mm."],
    "throne": ["..b....b....", "..bc..cb....", "..bccccb.b..", "..bRRRRbcb..", "..bbbbbbbb..", ".bccccccccb.",
               ".bRRRRRRRRb.", ".b..b..b..b.", "bccccccccccb", "bbbbbbbbbbbb", "b..b....b..b"],
    "chandelier": [".Y..Y..Y..Y.", ".B..B..B..B.", "qqqqqqqqqqqq", ".q.q.q.q.q.."],
    "orrery": ["....qq....", "..qq..qq..", ".q..yy..q.", "q..yYYy..q", ".q..yy..q.", "..qq..qq..", "....qq....",
               "....aa....", "...aaaa..."],
    "telescope": ["........qq", "......qqQ.", "....qqq...", "...qq.....", "....a.....", "...a.a....", "..a...a..."],
    "lectern": ["BBBBBe..", ".eBBBBe.", "..bbbb..", "...bb...", "...bb...", "...bb...", "..bbbb.."],
    "plinth": [".gGhg...", "g8888Gg.", ".7777g..", ".7777...", ".6666...", "555555.."],
    "sword": ["...e..", "..Me..", "..Me..", "..M...", "yyyyyy", "..b...", "..b...", ".aaaa."],
    "stump": [".bbbb.", "bcccab", "bckkab", "bckkcb", "bccccb", ".bbbb."],
    "nest": ["...eBBe...", ".bcbcbcbc.", "bcbcbcbcbc", ".bbbbbbbb."],
    "sap": ["..yyy...", ".yYYyyy.", "..yyy..."],
    "heart": ["..vv...vv..", ".vVVv.vVVv.", "vVVVVvVVVVv", "vVVzVVVVVVv", ".vVVVVVVVv.", "..vVVVVVv..",
              "...vVVVv...", "....vVv....", "....bab....", "...ba.ab..."],
    "cloche": ["..eeee..", ".e....e.", "e..gG..e", "e.gGhg.e", "eeeeeeee"],
    "pit": ["...bccb...", "..bcbbcb..", ".bcgbcbcb.", "bbcbbcbbcb"],
    "basket": [".c....c.", "..cddc..", "cdcdcdcd", "dcdcdcdc", "cdcdcdcd", ".cccccc."],
    "rock": ["...6776...", ".67788876.", "6778888776", "5667777665", ".55666655."],
    "bin": [".R.y.M.", "mMMMMMm", "mmmmmmm", "mmnmmnm", "mmmmmmm", ".nnnnn."],
    "saddle": ["..bb......", ".bccb...bb", "bccccbbbcb", "bcccccccb.", ".bbbbbbb..", "..a....a.."],
}
FLAT = {"grate", "hole", "mosaic", "sap"}  # lie on the floor: never sunk, never in front of anything
PROP_OF_WORD = {"pew": "pew", "bench": "bench", "altar": "altar", "case": "case", "trough": "trough",
                "mosaic": "mosaic", "drain": "grate", "gap": "hole", "wall": "rack", "niche": "niche",
                "skulls": "niche", "creepers": "vines", "vine": "vines", "lantern": "lantern", "throne": "throne",
                "chandelier": "chandelier", "fountain": "fountain", "chest": "chest", "box": "chest",
                "cloche": "cloche", "compost": "pit", "pit": "pit", "basket": "basket", "rock": "rock", "bin": "bin",
                "saddle": "saddle", "ledge": ""}
PHRASES = {"burial": "niche", "potting": "table"}  # words that settle what a feature is wherever they come
PROP_OF_GLYPH = {"π": "table", "θ": "barrel", "Ö": "cauldron", "Ω": "statue", "ı": "candle", "▯": "wardrobe",
                 "∪": "basin", "%": "bones", "≡": "chest", "◊": "fountain", "Å": "bell", "═": "rail",
                 "▒": "grate", "Ð": "cart", "▤": "shelf", "▭": "coffin", "§": "rope", "╥": "altar", "°": "plates",
                 "#": "cage", "&": "junk", "ð": "sack", "‡": "rack", "Ø": "gong", "●": "puffball", "≈": "bedroll",
                 "ь": "boots", "♨": "forge", "Ħ": "throne", "¥": "chandelier", "☼": "orrery", "/": "telescope",
                 "¶": "lectern", "♣": "fungus", "▪": "plinth", "†": "sword", "o": "stump", "ö": "nest", "~": "sap",
                 "♥": "heart", "◘": "basin", "⁘": "table", "▫": "mosaic"}
GLOWS = {"candle": 1.0, "lantern": 1.0, "cauldron": 1.0, "forge": 1.0, "chandelier": 1.0, "altar": 1.0,
         "heart": 0.0}  # props that give light, and how warm it is
SPRITE_PROPS = {"chest": "chest", "fountain": "fountain", "altar": "shrine"}  # props that are fixture sprites


def prop_kind(name: str) -> str:
    """What a feature looks like, from its name, the noun winning: "a half-sunken pew" is a pew, "a vine-covered
    plinth" a plinth. Anything else is a crate; "" is nothing to draw (a ledge is just the wall)."""
    words = name.lower().replace("'", " ").replace("-", " ").split()
    for word in words:
        if word in PHRASES:
            return PHRASES[word]
    for word in reversed(words):
        if word in PROP_OF_WORD:
            return PROP_OF_WORD[word]
        if word in layout.FEATURE_GLYPHS:
            return PROP_OF_GLYPH.get(layout.FEATURE_GLYPHS[word], "crate")
    return "crate"


def _grid_image(rows: list[str], colours: dict):
    img = Image.new("RGBA", (len(rows[0]), len(rows)), (0, 0, 0, 0))
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch != ".":
                img.putpixel((x, y), (*colours[ch], 255))
    return img


def prop_colours(look: Look) -> dict:
    """The letters props are drawn in: wood, stone (by dungeon), metal, brass, flame, moss, bone, water, cloth."""
    fixed = {"a": "#3e2731", "b": "#733e39", "c": "#b86f50", "d": "#c28569", "n": "#2e303e", "m": "#525668",
             "M": "#a6aaba", "q": "#c2a078", "Q": "#e4a672", "y": "#feae34", "Y": "#fee761", "r": "#be4a2f",
             "f": "#f77622", "F": "#feae34", "B": "#ead4aa", "e": "#c0cbdc", "~": "#0099db", "=": "#2ce8f5",
             "s": "#8b9bb4", "R": "#e43b44", "u": "#124e89", "p": "#f6757a", "P": "#b55088", "i": "#68386c",
             "k": "#181425", "v": "#3e8948", "V": "#63c74d", "z": "#b4ffd6"}
    colours = {k: _rgb(v) for k, v in fixed.items()}
    colours.update({str(5 + i): look.stone[i] for i in range(5)})
    colours.update({"g": look.moss[1], "G": look.moss[2], "h": look.moss[-1]})
    return colours


def prop_image(kind: str, look: Look, name: str = "", spent: bool = False):
    """A feature's prop: a fixture's sprite for chests, fountains and altars, otherwise its little drawing."""
    if kind in SPRITE_PROPS:
        frames = sprites._strip(SPRITE_PROPS[kind])
        img = (frames[-1] if kind == "chest" and spent else frames[0]).copy()
        if kind == "fountain" and ("dry" in name.lower() or spent):
            _dry(img, look)
        return img
    if kind == "fungus":
        return _mushroom(sum(map(ord, name)))
    img = _grid_image(PROPS[kind], prop_colours(look))
    if any(word in name.lower() for word in ("toppled", "fallen")) and kind in ("statue", "bell", "coffin"):
        img = img.transpose(Image.Transpose.ROTATE_90)
    return img


def _dry(img, look: Look) -> None:
    """A fountain with no water left: its blues turn to stone."""
    px = img.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, alpha = px[x, y]
            if alpha and b > r + 40:
                px[x, y] = (*look.stone[1 if y > img.height // 2 else 2], alpha)


def _tuft(seed: int, look: Look):
    """A clump of grass or leaves, sometimes in flower."""
    shapes = [["..g.h.", ".hg.g.", ".ggGg.", "gGgGgh"], ["h...", "g.h.", "gGg.", "GgGg"],
              [".p..", "hgh.", "gGgh", "GgGg"], ["...h..", ".h.gp.", "hg.gG.", "gGgGgG"]]
    return _grid_image(shapes[int(_hash01(seed, 7) * len(shapes))], prop_colours(look))


def _mushroom(seed: int):
    rows = [".=~~=.", "=~==~=", "..BB..", "..BB.."] if _hash01(seed, 3) < 0.5 else [".~=.", "~==~", ".B..", ".B.."]
    return _grid_image(rows, prop_colours(DEFAULT_LOOK))


def _at_scale(img, factor: float):
    """Full size, halved or quartered: pixel art only shrinks cleanly by halves."""
    if factor >= 0.75:
        return img
    img = sprites.halve(img)
    return img if factor >= 0.375 else sprites.halve(img)


# --- the picture -------------------------------------------------------------------------------------------

@dataclass
class Light:
    a: float
    z: float
    v: float
    power: float
    radius: float
    warm: float = 1.0


class Picture:
    """One room, drawn: surfaces, then decor and everything standing in the room back to front, then reflections
    and flames. `kind` says what each pixel shows (wall, floor, water, sky, void, locked, ceiling, object)."""

    def __init__(self, state: GameState, content: Content, w: int, h: int, room: Room | None = None) -> None:
        self.state, self.content, self.room = state, content, room or state.room
        self.look = look_of(state.theme)
        archetype = content.archetypes.get(self.room.archetype)
        self.sky = bool(archetype) and "sky" in archetype.decor.split()
        self.view = View(self.room)
        self.lens = Lens(w, h, self.view)
        self.w, self.h = w, h
        self.seed = int(_hash01(state.seed, state.floor, self.room.id) * 1e6)
        self.img = Image.new("RGB", (w, h), DARK)
        self.px = self.img.load()
        self.kind = [[""] * w for _ in range(h)]
        self.info = [[None] * w for _ in range(h)]
        self.lights: list[Light] = []
        self.flames: list[tuple[float, float, float, int]] = []  # (a, z, v, size)
        self.doors = self._doors()

    def draw(self):
        self._sconces()
        self._feature_lights()
        self._surfaces()
        self._door_frames()
        self._decals()
        self._objects()
        self._reflections()
        self._flames()
        return self.img

    # light ----------------------------------------------------------------------------------------------
    def light(self, a: float, z: float, v: float) -> tuple[float, float]:
        """How lit a point is, and how much of that is warm (candle or torch) light."""
        look, view = self.look, self.view
        na, nz = a / view.half, z / view.depth
        level = look.ambient + (0.25 if self.sky else 0.0) * (0.6 + 0.4 * v)
        level += look.lantern * max(0.0, 1 - 0.9 * nz) ** 1.6 * (1 - 0.2 * abs(na))
        warm = 0.0
        for lt in self.lights:
            da, dz, dv = (a - lt.a) / (2 * view.half), (z - lt.z) / view.depth, (v - lt.v) * 0.5
            dist = math.sqrt(da * da + dz * dz + dv * dv)
            if dist < lt.radius:
                glow = lt.power * (1 - dist / lt.radius) ** 2
                level += glow
                warm += glow * lt.warm
        return level * (1 - look.fog * nz), warm

    def shade(self, shades: list, warm_shades: list, a: float, z: float, v: float, x: int, y: int,
              bias: float = 0.0, dither: float = 0.45) -> tuple:
        level, warm = self.light(a, z, v)
        cx, cy = (x - self.w / 2) / (self.w / 2), (y - self.h / 2) / (self.h / 2)
        level = (level + bias) * (1 - 0.18 * cx * cx - 0.12 * cy * cy)  # a soft vignette
        if warm > 0.32 or (warm > 0.22 and _bayer(x, y) > 0.5):
            return _pick(warm_shades, level, x, y, dither)
        return _pick(shades, level, x, y, dither)

    # what's where ---------------------------------------------------------------------------------------
    def _doors(self) -> dict:
        """Each exit you can see, by wall: where along it (a on the far wall, z on a side wall), and if it's locked."""
        doors = {}
        for direction, exit_ in self.room.exits.items():
            wall = self.view.side[direction]
            if wall != "behind":
                a, z = self.view.cell(*layout.DOORS[direction])
                doors[wall] = (a if wall == "back" else z, exit_.locked)
        return doors

    def _door_half(self, wall: str) -> float:
        return 0.09 * 2 * self.view.half if wall == "back" else 0.12 * self.view.depth

    def _sconces(self) -> None:
        """Candles or torches on the walls, away from the doors."""
        if not self.look.sconces:
            return
        view, torch = self.view, self.look.sconces == "torches"
        for wall, t in (("left", 0.32), ("left", 0.78), ("right", 0.32), ("right", 0.78), ("back", -0.55),
                        ("back", 0.55)):
            if wall == "back":
                a, z = t * view.half, view.depth - 0.05
                along = a
            else:
                a, z = (-view.half + 0.05 if wall == "left" else view.half - 0.05), t * view.depth
                along = z
            if wall in self.doors and abs(along - self.doors[wall][0]) < self._door_half(wall) * 1.8:
                continue
            self.lights.append(Light(a, z, 0.55, 0.55 if torch else 0.42, 0.30 if torch else 0.24))
            self.flames.append((a, z, 0.55, 2 if torch else 1))

    def _feature_lights(self) -> None:
        room = self.room
        for feature in room.features:
            kind = prop_kind(feature.name)
            if not feature.hidden and kind in GLOWS:
                a, z = self.view.cell(*feature.pos)
                self.lights.append(Light(a, z, 0.2, 0.6, 0.30, warm=GLOWS[kind]))
        if room.fixture == "shrine":
            a, z = self.view.cell(CX, CY)
            self.lights.append(Light(a, z, 0.2, 0.55, 0.30))
        for y, line in enumerate(room.grid):
            for x, ch in enumerate(line):
                if ch == "♣" and _hash01(x, y, 5) < 0.6:
                    a, z = self.view.cell(x, y)
                    self.lights.append(Light(a, z, 0.05, 0.30, 0.16, warm=0.0))
                elif ch == "^":
                    a, z = self.view.cell(x, y)
                    self.lights.append(Light(a, z, 0.02, 0.35, 0.16))

    def _glyph(self, x: int, y: int) -> str:
        grid = self.room.grid
        return grid[y][x] if 0 <= y < len(grid) and 0 <= x < len(grid[y]) else "#"

    # surfaces -------------------------------------------------------------------------------------------
    def wall_top(self, wall: str, along: float) -> float:
        """How high a wall stands (1 is the ceiling): rooms open to the sky have broken walls."""
        if not self.sky:
            return 1.0
        n = _noise(along * 0.9, {"back": 3.0, "left": 5.0, "right": 7.0}[wall], self.seed)
        step = 0.06 * math.floor(_hash01(math.floor(along * 1.6), self.seed, 11) * 3)
        return 0.42 + 0.30 * n + step

    def _surfaces(self) -> None:
        """Every pixel's wall, floor, ceiling or sky, with its pattern and light."""
        lens, view = self.lens, self.view
        tiles = [[None] * self.w for _ in range(self.h)]
        for x in range(self.w):
            dx = x + 0.5 - self.w / 2
            if abs(dx) <= lens.kx * view.half * lens.sb:
                wall, sw = "back", lens.sb
            else:
                wall, sw = ("left" if dx < 0 else "right"), abs(dx) / (lens.kx * view.half)
            top, bottom = lens.ceil_y(sw), lens.floor_y(sw)
            a_wall = dx / (lens.kx * sw) if wall == "back" else (-view.half if wall == "left" else view.half)
            z_wall = view.depth if wall == "back" else lens.d / sw - lens.d
            along = a_wall if wall == "back" else z_wall
            standing = self.wall_top(wall, along)
            for y in range(self.h):
                yc = y + 0.5
                if yc > bottom:
                    s = (yc - lens.yh) / (lens.yn - lens.yh)
                    a, z = dx / (lens.kx * s), lens.d / s - lens.d
                    wet = self._wet(*view.grid_at(a, z)) > 0.42
                    self.info[y][x] = ("water" if wet else "floor", a, z, 0.0, "")
                    tiles[y][x] = self._floor_tile(a, z)
                elif yc >= top:
                    v = (bottom - yc) / (bottom - top)
                    if v > standing:
                        self.info[y][x] = ("sky", a_wall, z_wall, v, "")
                        continue
                    door = self._in_door(wall, along, v)
                    self.info[y][x] = (door or "wall", a_wall, z_wall, v, wall)
                    if not door:
                        tiles[y][x] = self._wall_tile(wall, along, v)
                elif self.sky:
                    self.info[y][x] = ("sky", 0.0, view.depth, 1.0, "")
                else:
                    s = (lens.yh - yc) / (lens.yh - lens.yt)
                    a, z = dx / (lens.kx * s), lens.d / s - lens.d
                    self.info[y][x] = ("ceiling", a, z, 1.0, "")
                    tiles[y][x] = ("c", math.floor(z / 1.4), 0)
        for y in range(self.h):
            for x in range(self.w):
                self._paint(x, y, tiles)

    def _wet(self, x: float, y: float) -> float:
        """How much water is here, blended between cells so pools come out round rather than square."""
        x0, y0 = math.floor(x), math.floor(y)
        tx, ty = x - x0, y - y0

        def at(cx: int, cy: int) -> float:
            return 1.0 if self._glyph(cx, cy) == "~" else 0.0

        top = at(x0, y0) * (1 - tx) + at(x0 + 1, y0) * tx
        bottom = at(x0, y0 + 1) * (1 - tx) + at(x0 + 1, y0 + 1) * tx
        return top * (1 - ty) + bottom * ty

    def _floor_tile(self, a: float, z: float):
        flags = self.look.ground == "flags"
        size = 1.5 if flags else 1.0
        row = math.floor(z / size)
        return ("f", row, math.floor((a + (row % 2) * size / 2 * flags) / size))

    def _wall_tile(self, wall: str, along: float, v: float):
        bricks = self.look.walls == "bricks"
        row = math.floor(v * (7 if bricks else 4))
        length = 2 * self.view.half / (11 if bricks else 6)
        return (wall, row, math.floor((along + (row % 2) * length / 2) / length))

    def _in_door(self, wall: str, along: float, v: float) -> str:
        if wall not in self.doors:
            return ""
        centre, locked = self.doors[wall]
        u = (along - centre) / self._door_half(wall)
        if abs(u) > 1:
            return ""
        arch = 0.10 * math.sqrt(max(0.0, 1 - u * u)) if self.look.walls != "earth" else 0.0
        return ("locked" if locked else "void") if v <= 0.56 + arch else ""

    def _mortar(self, x: int, y: int, tiles) -> bool:
        """Where one brick, flagstone or tile meets the next: one pixel of mortar, however far away it is."""
        tile = tiles[y][x]
        for nx, ny in ((x + 1, y), (x, y + 1)):
            if nx < self.w and ny < self.h:
                other = tiles[ny][nx]
                if other is not None and other[0] == tile[0] and other != tile \
                        and self.info[ny][nx][0] == self.info[y][x][0]:
                    return True
        return False

    def _paint(self, x: int, y: int, tiles) -> None:
        cell = self.info[y][x]
        if cell is None:
            return
        kind, a, z, v, wall = cell
        look = self.look
        self.kind[y][x] = kind
        if kind == "sky":
            self.px[x, y] = self._sky(x, y)
        elif kind == "void":  # the dark beyond an unexplored door, a faint floor deep inside
            self.px[x, y] = look.floor[1] if (0.62 - v) / 0.62 > 0.85 and _bayer(x, y) < 0.5 else DARK
        elif kind == "locked":
            plank = math.floor((a if wall == "back" else z) * 2.2)
            band = abs(v - 0.15) < 0.035 or abs(v - 0.45) < 0.035  # iron bands
            self.px[x, y] = _rgb("#525668") if band else self.shade(look.wood, look.wood, a, z, v, x, y,
                                                                    -0.05 * (plank % 2))
        elif kind == "wall":
            self.px[x, y] = self._wall(x, y, a, z, v, wall, tiles)
        elif kind in ("floor", "water"):
            self.px[x, y] = self._floor(x, y, a, z, tiles) if kind == "floor" else self._water(x, y, a, z)
        elif kind == "ceiling":
            bias = 0.12 if self._mortar(x, y, tiles) else -0.05  # the vault's ribs
            if look.above == "rock":
                bias = (_noise(a * 0.9, z * 0.9, 12) - 0.5) * 0.3
            self.px[x, y] = self.shade(look.ceiling, look.ceiling, a, z, 1.0, x, y, bias)

    def _tint(self, tile) -> float:
        return _hash01(*[hash(t) & 0xFFFF for t in tile], self.seed)

    def _wall(self, x: int, y: int, a: float, z: float, v: float, wall: str, tiles) -> tuple:
        look = self.look
        tint = self._tint(tiles[y][x])
        bias = (-0.07 if tint < 0.25 else (0.05 if tint > 0.85 else 0.0))
        bias += 0.06 if wall == "back" else -0.12  # the far wall faces your light; the side walls don't
        if self._edge(x, y):
            return self.shade(look.wall, look.wall, a, z, v, x, y, bias - 0.4, dither=0)
        mortar = self._mortar(x, y, tiles)
        if look.walls == "earth":
            if self._beam(wall, a, z, v):
                return self.shade(look.wood, look.wood, a, z, v, x, y, -0.05)
            bias = (_noise((a if wall == "back" else z) * 0.9, v * 3.5, 9) - 0.5) * 0.28
            mortar = False
        colour = self.shade(look.wall, look.wall_warm, a, z, v, x, y, bias - (0.22 if mortar else 0.0))
        if look.walls == "marble" and self._moss(wall, a, z, v, x):
            colour = _pick(look.moss, self.light(a, z, v)[0] * 0.9, x, y)
        return colour

    def _floor(self, x: int, y: int, a: float, z: float, tiles) -> tuple:
        look = self.look
        mortar = self._mortar(x, y, tiles)
        bias = (-0.06 if self._tint(tiles[y][x]) < 0.3 else 0.0) + 0.14 * (1 - z / self.view.depth) + 0.06
        if look.ground == "dirt":
            bias, mortar = (_noise(a * 1.1, z * 1.1, 4) - 0.5) * 0.3, False
        elif look.ground == "mosaic":
            bias += 0.04 if sum(tiles[y][x][1:]) % 2 else -0.03
        colour = self.shade(look.floor, look.floor_warm, a, z, 0.0, x, y, bias - (0.2 if mortar else 0.0))
        if look.ground == "dirt" and _hash01(x, y, 21) < 0.025:
            colour = _pick(look.moss, self.light(a, z, 0)[0], x, y)  # straw
        if look.ground == "mosaic" and _noise(a * 0.7, z * 0.7, 23) > (0.5 if mortar else 0.68):
            colour = _pick(look.moss, self.light(a, z, 0)[0] * 0.8, x, y)  # moss creeping over the tiles
        return colour

    def _water(self, x: int, y: int, a: float, z: float) -> tuple:
        level, _ = self.light(a, z, 0.0)
        ripple = _hash01(math.floor(z * 5), math.floor((a + 7 * math.floor(z * 5)) * 1.3), 31) < 0.12
        return _pick(self.look.water, level * 0.55 + (0.35 if ripple else 0.0), x, y)

    def _edge(self, x: int, y: int) -> bool:
        """Where two walls meet, or a wall meets the floor or ceiling: a dark line that shows the room's shape."""
        wall = self.info[y][x][4]
        for nx in (x - 1, x + 1):
            other = self.info[y][nx] if 0 <= nx < self.w else None
            if other and other[0] == "wall" and other[4] != wall and wall != "back":
                return True
        below = self.info[y + 1][x] if y + 1 < self.h else None
        above = self.info[y - 1][x] if y > 0 else None
        return bool(below and below[0] in ("floor", "water")) or bool(above and above[0] == "ceiling")

    def _beam(self, wall: str, a: float, z: float, v: float) -> bool:
        """Timber props holding up a goblin tunnel."""
        if v > 0.9:
            return True
        if wall == "back":
            return any(abs(a - p * self.view.half) < 0.07 * self.view.half for p in (-0.7, 0.7))
        return any(abs(z - p * self.view.depth) < 0.04 * self.view.depth for p in (0.18, 0.62))

    def _moss(self, wall: str, a: float, z: float, v: float, x: int) -> bool:
        along = a if wall == "back" else z
        if v < 0.18 and _noise(along * 1.5, 1.0, 17) > 0.45:
            return True
        vine = _hash01(x, 41, self.seed) < 0.22  # hanging from the top of a broken wall
        return vine and self.wall_top(wall, along) - v < 0.12 + 0.35 * _hash01(x, 43, self.seed)

    def _sky(self, x: int, y: int) -> tuple:
        if _hash01(x, y, 51) < 0.03:
            return _rgb("#ffffff") if _hash01(x, y, 52) < 0.4 else _rgb("#8b9bb4")
        return _pick(self.look.ceiling, 0.2 + 0.75 * y / (self.h * 0.6), x, y, dither=0.3)

    def _door_frames(self) -> None:
        """Pull the doorways' frames out of the dark."""
        frame = self.look.wood if self.look.walls == "earth" else self.look.stone
        for y in range(self.h):
            for x in range(self.w):
                if self.kind[y][x] == "wall" and any(
                        0 <= x + dx < self.w and 0 <= y + dy < self.h and self.kind[y + dy][x + dx] in ("void", "locked")
                        for dx, dy in ((1, 0), (-1, 0), (0, -1))):
                    _, a, z, v, _ = self.info[y][x]
                    self.px[x, y] = self.shade(frame, self.look.wall_warm, a, z, v, x, y, 0.15)

    # things on the floor and standing in the room -------------------------------------------------------
    def _decals(self) -> None:
        """Flat things on the floor: bones, rubble, roots, embers."""
        lens, look = self.lens, self.look
        for gy, line in enumerate(self.room.grid):
            for gx, ch in enumerate(line):
                if ch not in "%:≀^":
                    continue
                a, z = self.view.cell(gx, gy)
                s = lens.s(z)
                cx, cy = lens.x(a, s), lens.floor_y(s)
                level = self.light(a, z, 0)[0]
                for i in range({"%": 3, ":": 4, "≀": 6, "^": 2}[ch]):
                    x = round(cx + (_hash01(gx, gy, i, 81) - 0.5) * lens.kx * s * 1.6)
                    y = round(cy - 0.5 + (_hash01(gx, gy, i, 82) - 0.5) * 2)
                    if not (0 <= x < self.w and 0 <= y < self.h) or self.kind[y][x] not in ("floor", "water"):
                        continue
                    self.px[x, y] = {"%": _rgb("#ead4aa") if level > 0.35 else _rgb("#8b9bb4"),
                                     ":": _pick(look.stone, level, x, y), "≀": _pick(look.wood, level * 0.9, x, y),
                                     "^": FLAME[1 + i % 2]}[ch]

    def _objects(self) -> None:
        """The decor, then the things you can do something with (features, the fixture, items, the monster), each
        back to front: scenery never hides what matters, as on the room map."""
        room, view, lens, look = self.room, self.view, self.lens, self.look
        scenery, things = [], []  # (z, draw)
        tables = {(gx, gy) for gy, line in enumerate(room.grid) for gx, ch in enumerate(line) if ch == "="}
        decor = {"π": "table", "&": "junk", "▤": "shelf", "#": "cage"}
        for gy, line in enumerate(room.grid):
            for gx, ch in enumerate(line):
                a, z = view.cell(gx, gy)
                inside = 1 <= gx <= WIDTH and 1 <= gy <= HEIGHT
                if not inside or z < (2.0 if ch in "#▤" else 1.2):  # right beside you: out of the picture
                    continue
                if ch == "O":
                    scenery.append((z, lambda a=a, z=z: self._pillar(a, z)))
                elif ch == "=":
                    scenery.append((z + 0.01, lambda gx=gx, gy=gy: self._table(gx, gy, tables)))
                elif ch == "\"" and _hash01(gx, gy, 91) < 0.8:
                    img = _tuft(gx * 31 + gy, look)
                    scenery.append((z, lambda a=a, z=z, img=img: self._place(_at_scale(img, lens.scale(z) * 1.4), a,
                                                                              z)))
                elif ch == "♣":
                    img = _mushroom(gx * 17 + gy)
                    scenery.append((z, lambda a=a, z=z, img=img: self._place(_at_scale(img, lens.scale(z) * 1.4), a,
                                                                              z, lit=True)))
                elif ch in decor:
                    img = prop_image(decor[ch], look)
                    scenery.append((z, lambda a=a, z=z, img=img: self._place(_at_scale(img, lens.scale(z) * 1.2), a,
                                                                              z)))
        for feature in room.features:
            if not feature.hidden and prop_kind(feature.name):
                things.append(self._feature(feature))
        if room.fixture:
            a, z = view.cell(CX, CY)
            frames = sprites._strip(room.fixture)
            img = (frames[-1] if room.fixture == "chest" and room.fixture_used else frames[0]).copy()
            if room.fixture == "fountain" and room.fixture_used:
                _dry(img, look)
            things.append((z, lambda a=a, z=z, img=img: self._place(_at_scale(img, lens.scale(z) * 1.2), a, z,
                                                                     lit=room.fixture == "shrine", framed=True)))
        for key, (gx, gy) in zip(room.items, room.item_spots):
            small = sprites.frames(f"item_{key}", sprites.SMALL)
            if small:
                a, z = view.cell(gx, gy)
                things.append((z, lambda a=a, z=z, img=small[0]: self._item(img, a, z)))
        if room.monster:
            frames = sprites._strip(room.monster.key)
            if frames:
                a, z = view.cell(*room.monster_pos)
                a, z = a * 0.5, max(z, 0.3 * view.depth)  # it faces you from the middle, not from a doorway
                img = sprites.posed(frames[0], "idle" if room.monster.hostile else "calm")
                things.append((z, lambda a=a, z=z, img=img: self._place(_at_scale(img, lens.scale(z) * 1.25), a, z,
                                                                         lit=True, framed=True)))
        for layer in (scenery, things):
            for _, draw in sorted(layer, key=lambda t: -t[0]):
                draw()

    def _feature(self, feature) -> tuple:
        a, z = self.view.cell(*feature.pos)
        kind = prop_kind(feature.name)
        spent = feature.searched or bool(feature.used)
        img = prop_image(kind, self.look, feature.name, spent)
        gx, gy = feature.pos
        sunk = kind not in FLAT and any(self._glyph(gx + dx, gy + dy) == "~"
                                        for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)))
        factor = self.lens.scale(z) * (0.75 if kind in SPRITE_PROPS else 1.6)
        return (z + (0.3 if kind in FLAT else 0.0),
                lambda: self._place(_at_scale(img, factor), a, z, lit=kind in GLOWS, sunk=sunk, framed=True))

    def _place(self, img, a: float, z: float, lit: bool = False, sunk: bool = False, framed: bool = False) -> None:
        """A sprite standing on the floor at (a, z), a step darker in shadow (unless it gives light itself). One
        standing in water loses its lower third to it; a `framed` one is kept wholly inside the picture."""
        sx, sy = self.lens.at(a, z)
        left, top = round(sx - img.width / 2), round(sy - img.height)
        if framed:
            left = max(0, min(self.w - img.width, left))
        level, _ = self.light(a, z, 0.3)
        cut = img.height - max(1, img.height // 3) if sunk else img.height
        src = img.load()
        for y in range(cut):
            for x in range(img.width):
                r, g, b, alpha = src[x, y]
                tx, ty = left + x, top + y
                if alpha < 128 or not (0 <= tx < self.w and 0 <= ty < self.h):
                    continue
                colour = (r, g, b)
                if not lit:
                    colour = _darker(colour, 0.5) if level < 0.22 else (_darker(colour, 0.72) if level < 0.42 else colour)
                self.px[tx, ty] = colour
                self.kind[ty][tx] = "object"
        if sunk:  # a ripple where it meets the water
            for x in range(img.width):
                tx, ty = left + x, top + cut
                if 0 <= tx < self.w and 0 <= ty < self.h and src[x, cut - 1][3] >= 128:
                    self.px[tx, ty] = self.look.water[2]
                    self.kind[ty][tx] = "object"

    def _item(self, img, a: float, z: float) -> None:
        """Something lying on the floor, with a glint to catch your eye."""
        img = _at_scale(img, self.lens.scale(z) * 0.7)
        self._place(img, a, z, lit=True)
        sx, sy = self.lens.at(a, z)
        x, y = round(sx + img.width / 2), round(sy - img.height)
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[x, y] = _rgb("#ffffff")

    def _pillar(self, a: float, z: float) -> None:
        """A round stone column, floor to ceiling (or broken off, under the sky), lit from the left."""
        lens, look = self.lens, self.look
        s = lens.s(z - 0.45)
        half = 0.5 * max(1.0, self.view.half / 12.5 * 2.2)
        x0, x1 = round(lens.x(a - half, s)), round(lens.x(a + half, s))
        x1 = max(x0 + 2, x1)
        bottom, ceiling = lens.floor_y(s), lens.ceil_y(s)
        standing = 1.0 if not self.sky else 0.45 + 0.4 * _hash01(round(a * 10), round(z * 10), 61)
        top = bottom - standing * (bottom - ceiling)
        for y in range(max(0, math.floor(top)), min(self.h, math.ceil(bottom))):
            v = (bottom - y - 0.5) / (bottom - ceiling)
            flare = 1 if (v < 0.06 or (not self.sky and v > 0.93)) else 0  # a base and a capital
            for x in range(x0 - flare, x1 + flare):
                if not 0 <= x < self.w:
                    continue
                t = (x + 0.5 - x0) / (x1 - x0)
                round_ = 0.16 if t < 0.34 else (-0.22 if t > 0.72 else 0.0)
                colour = self.shade(look.stone, look.wall_warm, a, z - 0.5, v, x, y, round_ + 0.06 * flare, dither=0)
                if self.sky and top - y > -1.5 and _hash01(x, y, 62) < 0.5:
                    colour = _pick(look.moss, 0.7, x, y)
                self.px[x, y] = colour
                self.kind[y][x] = "object"

    def _table(self, gx: int, gy: int, tables: set) -> None:
        """A long goblin table, a slab per cell of the room map so it works from any door: a top scattered with
        food, a dark edge, and legs where the table ends."""
        lens, look, view = self.lens, self.look, self.view
        top_v, apron = 0.16, 2
        a, z = view.cell(gx, gy)
        corners = [view.cell(gx + dx, gy + dy) for dx, dy in ((-0.5, -0.7), (0.5, -0.7), (0.5, 0.7), (-0.5, 0.7))]
        for x, y in self._inside([lens.at(ca, cz, top_v) for ca, cz in corners]):
            colour = self.shade(look.wood, look.wood, a, z, 0.2, x, y, 0.16)
            if _hash01(x, y, 71) < 0.08:  # scraps of food
                colour = _rgb("#e4a672") if _hash01(x, y, 72) < 0.5 else _rgb("#63c74d")
            self.px[x, y] = colour
            self.kind[y][x] = "object"
        near = sorted(corners, key=lambda c: c[1])[:2]  # the edge facing you
        (xa, ya), (xb, yb) = (lens.at(ca, cz, top_v) for ca, cz in near)
        edge = round(max(ya, yb))
        for x in range(round(min(xa, xb)), round(max(xa, xb)) + 1):
            for y in range(edge + 1, edge + 1 + apron):
                if 0 <= x < self.w and 0 <= y < self.h:
                    self.px[x, y] = self.shade(look.wood, look.wood, a, z, 0.1, x, y, -0.18, dither=0)
                    self.kind[y][x] = "object"
        for dx in (-1, 1):
            if (gx + dx, gy) in tables:
                continue
            ca, cz = min((view.cell(gx + dx * 0.4, gy + dy * 0.6) for dy in (-1, 1)), key=lambda c: c[1])
            lx, _ = lens.at(ca, cz, top_v)
            _, fy = lens.at(ca, cz, 0.0)
            for y in range(edge + 1 + apron, round(fy)):
                if 0 <= round(lx) < self.w and 0 <= y < self.h:
                    self.px[round(lx), y] = look.wood[0]
                    self.kind[y][round(lx)] = "object"

    def _inside(self, polygon):
        """The pixels whose centres fall inside a polygon on the picture."""
        xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
        for y in range(max(0, math.floor(min(ys))), min(self.h, math.ceil(max(ys)) + 1)):
            for x in range(max(0, math.floor(min(xs))), min(self.w, math.ceil(max(xs)) + 1)):
                cx, cy, inside = x + 0.5, y + 0.5, False
                for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
                    if (y1 > cy) != (y2 > cy) and cx < x1 + (cy - y1) * (x2 - x1) / (y2 - y1):
                        inside = not inside
                if inside:
                    yield x, y

    # finishing touches ----------------------------------------------------------------------------------
    def _reflections(self) -> None:
        """Still water mirrors what stands above it, broken up by ripples."""
        for x in range(self.w):
            line = None
            for y in range(self.h - 1):
                if self.kind[y][x] in ("wall", "object", "void", "locked", "sky") and \
                        self.kind[y + 1][x] in ("floor", "water"):
                    line = y + 1
            if line is None:
                continue
            for y in range(line, self.h):
                mirror = 2 * line - y - 1
                if self.kind[y][x] == "water" and (y - line) % 2 == 0 and 0 <= mirror < self.h and \
                        self.kind[mirror][x] in ("wall", "object", "sky", "void"):
                    r, g, b = self.px[x, mirror]
                    self.px[x, y] = _pick(self.look.water, (0.3 * r + 0.59 * g + 0.11 * b) / 255 * 1.3, x, y)

    def _flames(self) -> None:
        """The candles and torches on the walls (hidden by anything standing in front), and under the sky, the moon
        and drifting petals."""
        for a, z, v, size in self.flames:
            sx, sy = self.lens.at(a, z, v)
            x, y = round(sx), round(sy)
            parts = [(0, 2, _rgb("#525668")), (0, 1, _rgb("#ead4aa") if size == 1 else _rgb("#733e39")),
                     (0, 0, FLAME[3]), (0, -1, FLAME[2])]
            if size > 1:
                parts += [(dx, dy, FLAME[1]) for dx, dy in ((-1, 0), (1, 0), (0, -2)) if _hash01(x, y, dx, dy) < 0.7]
            for dx, dy, colour in parts:
                if 0 <= x + dx < self.w and 0 <= y + dy < self.h and self.kind[y + dy][x + dx] != "object":
                    self.px[x + dx, y + dy] = colour
        if not self.sky:
            return
        cx, cy, r = self.w * 0.80, self.h * 0.12, max(2.0, self.h / 14)
        for y in range(self.h):
            for x in range(self.w):
                if self.kind[y][x] == "sky" and math.hypot(x + 0.5 - cx, y + 0.5 - cy) <= r:
                    self.px[x, y] = _rgb("#a6aaba") if _hash01(x, y, 111) < 0.18 else _rgb("#e8eaf4")
        for i in range(self.w * self.h // 260):
            x, y = int(_hash01(i, 101, self.seed) * self.w), int(_hash01(i, 102, self.seed) * self.h * 0.8)
            if self.kind[y][x] != "object":
                self.px[x, y] = _rgb("#f6757a") if _hash01(i, 103) < 0.7 else _rgb("#faa096")


def draw(state: GameState, content: Content, width: int, height: int, room: Room | None = None):
    """The room you're in (or another on this floor) as an RGB image, or None without Pillow. `height` should be
    even: two pixels to a row."""
    if Image is None:
        return None
    return Picture(state, content, width, height, room).draw()


def picture_text(state: GameState, content: Content, width: int, height: int, room: Room | None = None) -> Text | None:
    """The room you're in (or another on this floor) as half-block text, `width` cells across and height / 2 rows."""
    img = draw(state, content, width, height, room)
    return None if img is None else sprites.image_text(img.convert("RGBA"), snap=True)


def main(argv: list[str]) -> None:
    from rich.console import Console

    from .content import load_content
    from .world import generate

    console = Console()
    content = load_content()
    state = generate(int(argv[0]) if argv else 7, content=content)
    for room in state.rooms:
        state.room_id = room.id
        console.print(f"[bold]{room.name}[/] ({room.archetype})")
        console.print(picture_text(state, content, 72, 30))


if __name__ == "__main__":
    main(sys.argv[1:])
