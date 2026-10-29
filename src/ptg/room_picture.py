"""Pictures of rooms: what you see from the doorway you came in by, drawn in code from the room itself.

The engine owns the room (see layout): its walls, exits, decor, features, fixture, monster and items. This draws
them as pixel art in one-point perspective, for the story card you get the first time you walk into a room and
for the Look panel (F4):

    walls, floor, ceiling     the dungeon's own look: the Crypt's bricks and candles, the Warren's earth, timber
                              and torches, the Ruins' marble (broken, under the stars, if the room's decor says sky)
    exits                     doorways in the walls they're in: dark if unexplored, planked and barred if locked
    decor                     the room map's water, pillars, tables, cages, shelves, plants, fungus, roots...
    features                  small props by their kind (a pew, a barrel, a cauldron, a throne, a coffin...)
    fixture, monster          their own sprites, smaller further back; a shop is its keeper behind her counter,
                              her wares (their small pictures) on the shelf above her, or on the counter beside
                              her in a picture too short for the shelf, never drawn over her
    items                     their small pictures, with a glint: never smaller in a picture as tall as the story
                              card's, halved in a shorter one where whoever's in the room would be
    light                     the lantern you carry, candles and torches, glowing things, moonlight

Sizes are a stage set's, not a surveyor's: drawn to the scale of the floor plan a goblin would be two pixels wide,
so things are bigger than the plan says. Whoever is in the room stands where the room map has them, but stepped
aside from the fixture, and a step or two rather than hide most of a feature or an item; they're drawn last, so
nothing hides them. Items step aside from them and the fixture rather than lose more than a quarter to either, and a
feature from them rather than lose half (see Picture._stand). Nothing you can do something with is cut off at the
picture's edges or lost in the dark (see Picture._fit).
Every colour is snapped to one the sprites use (sprites.palette()), so a GPU terminal's glyph cache meets nothing
new (see PTGApp.action_redraw).

    uv run python -m ptg.room_picture 7       # every room on the first floor of seed 7, in your terminal
"""

from __future__ import annotations

import math
import sys
import threading
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache

from rich.style import Style
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
BRASS = _ramp("#feae34", "#fee761")  # a locked door's bands and lock, the colour of a locked way on the maps


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
    walls: str  # bricks | earth | marble | bubbles
    ground: str  # flags | dirt | mosaic
    above: str  # vault | rock
    ambient: float
    lantern: float
    sconces: str  # candles | torches | ""
    fog: float
    accent: str  # the story card's border
    props: list | None = None  # stone props and doorframes, if not in `stone`: two steps above dark walls, to stand out

    @property
    def prop_stone(self) -> list:
        return self.props or self.stone


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
        walls="bricks", ground="flags", above="vault", ambient=0.17, lantern=0.70, sconces="candles", fog=0.38,
        accent="#0099db", props=_ramp("#3a4466", "#5a6988", "#8b9bb4", "#c0cbdc", "#ffffff")),
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
    "norfel": Look(  # Metroid's Norfair: purple rock all bubbles, lit from below by pools of glowing poison
        wall=_ramp("#181425", "#68386c", "#b55088", "#f6757a", "#e8b796"),
        wall_warm=_ramp("#181425", "#68386c", "#b55088", "#f6757a", "#e8b796"),
        floor=_ramp("#181425", "#3e2731", "#68386c", "#b55088"),
        floor_warm=_ramp("#181425", "#68386c", "#b55088", "#f6757a"),
        ceiling=_ramp("#181425", "#3e2731", "#68386c"),
        water=_ramp("#68386c", "#b55088", "#f6757a", "#ead4aa"),  # poison, glowing
        wood=_ramp("#3e2731", "#733e39", "#b86f50", "#c28569"),
        stone=_ramp("#262b44", "#3a4466", "#5a6988", "#8b9bb4", "#c0cbdc"),  # grey pillars with pale caps
        moss=_ramp("#193c3e", "#265c42", "#3e8948", "#63c74d"),  # a vent's crystals
        walls="bubbles", ground="dirt", above="rock", ambient=0.34, lantern=0.55, sconces="", fog=0.30,
        accent="#b55088"),
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


@lru_cache(maxsize=4096)
def _shadow(colour: tuple, k: float) -> tuple:
    """A colour in shadow, `k` as bright, but never so dark it's lost in the black of an unexplored doorway: only
    what was outline to start with (darker than sprites.OUTLINE) goes that dark."""
    darker = tuple(int(c * k) for c in colour)
    if sprites._light(colour) < sprites.OUTLINE:
        return sprites._nearest(darker)
    return min(_lit_palette(), key=lambda c: sum((c[i] - darker[i]) ** 2 for i in range(3)))


@lru_cache(maxsize=1)
def _lit_palette() -> tuple:
    return tuple(c for c in sprites.palette() if sprites._light(c) >= sprites.OUTLINE)


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
    "hole": [".mmmmmm.", "mkkkkkkm", ".nkkkkn."],
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
# Half-size props drawn by hand, for those that halved block by block (sprites.halve) come out one flat colour.
PROPS_HALF = {
    "shelf": ["aaaaaa", "aRuGPa", "aaaaaa", "acBRua"],
    "cage": ["mmmmm", "M.M.M", "mmmmm"],
    "bones": [".BB...", "BkB.e.", "eBeBBe"],
    "grate": ["nmnmn", "mnmnm"],
    "hole": ["mkkm", ".kk."],
    "bedroll": ["BRRuRR", "RRRuRR"],
    "boots": ["b..b.", "bc.bc", "aa.aa"],
}
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
                 "▥": "cage", "&": "junk", "ð": "sack", "‡": "rack", "Ø": "gong", "●": "puffball", "≈": "bedroll",
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
    colours.update({str(5 + i): look.prop_stone[i] for i in range(5)})
    colours.update({"g": look.moss[1], "G": look.moss[2], "h": look.moss[-1]})
    return colours


def prop_image(kind: str, look: Look, name: str = "", spent: bool = False):
    """A feature's prop: a fixture's sprite for chests, fountains and altars, otherwise its little drawing. A `spent`
    one looks it: a chest emptied, an altar's candles out, a fountain dry."""
    if kind in SPRITE_PROPS:
        return fixture_image(SPRITE_PROPS[kind], look, spent or (kind == "fountain" and "dry" in name.lower()))
    if kind == "fungus":
        return _mushroom(sum(map(ord, name)))
    img = _grid_image(PROPS[kind], prop_colours(look))
    if any(word in name.lower() for word in ("toppled", "fallen")) and kind in ("statue", "bell", "coffin"):
        img = img.transpose(Image.Transpose.ROTATE_90)
    return img


def fixture_image(key: str, look: Look, spent: bool = False):
    """A fixture's sprite as it stands: its first frame, or once it's been used, its used-up last frame (see
    sprites.SPENT), or for a fountain, drained."""
    frames = sprites._strip(key)
    img = (frames[-1] if spent and key in sprites.SPENT else frames[0]).copy()
    if key == "fountain" and spent:
        _dry(img, look)
    return img


def prop_at(kind: str, look: Look, factor: float, name: str = "", spent: bool = False):
    """A prop at a scale (see _at_scale), from its half-size drawing (PROPS_HALF) where it has one."""
    if factor < 0.75 and kind in PROPS_HALF:
        half = _grid_image(PROPS_HALF[kind], prop_colours(look))
        return half if factor >= 0.375 else sprites.halve(half)
    return _at_scale(prop_image(kind, look, name, spent), factor)


def _unlit(kind: str, spent: bool) -> bool:
    """Whether a prop that would give light has gone out: a used altar's candles, like a used shrine's."""
    return spent and SPRITE_PROPS.get(kind) in sprites.SPENT


def _dry(img, look: Look) -> None:
    """A fountain with no water left: its blues turn to stone."""
    px = img.load()
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, alpha = px[x, y]
            if alpha and b > r + 40:
                px[x, y] = (*look.prop_stone[1 if y > img.height // 2 else 2], alpha)


def _tuft(seed: int, look: Look):
    """A clump of grass or leaves, sometimes in flower."""
    shapes = [["..g.h.", ".hg.g.", ".ggGg.", "gGgGgh"], ["h...", "g.h.", "gGg.", "GgGg"],
              [".p..", "hgh.", "gGgh", "GgGg"], ["...h..", ".h.gp.", "hg.gG.", "gGgGgG"]]
    return _grid_image(shapes[int(_hash01(seed, 7) * len(shapes))], prop_colours(look))


def _mushroom(seed: int):
    rows = [".=~~=.", "=~==~=", "..BB..", "..BB.."] if _hash01(seed, 3) < 0.5 else [".~=.", "~==~", ".B..", ".B.."]
    return _grid_image(rows, prop_colours(DEFAULT_LOOK))


def _trimmed(img):
    """A sprite without the empty rows over its head and under its feet (its frame's, not its own)."""
    box = img.getbbox()
    return img.crop((0, box[1], img.width, box[3])) if box and (box[1] or box[3] < img.height) else img


def _whole(img, height: int):
    """Someone in a room, as big as they are, however far back they stand: the empty rows over their head and under
    their feet trimmed off, and halved only if they still don't fit a picture that tall (a tiny stage). Marked whole,
    so nothing after makes them smaller (see Picture._fit). Pixel art halved loses its faces and teeth: it's for
    nothing but a stage too short for them."""
    img = _trimmed(img)
    while img.height > height and img.height >= 4:
        img = _trimmed(sprites.halve(img))
    img = img.copy()  # (never the sprite's own frame: that's shared, cached, and must stay as it is)
    img.info["whole"] = True
    return img


def _at_scale(img, factor: float):
    """Full size, halved or quartered: pixel art only shrinks cleanly by halves."""
    if factor >= 0.75:
        return img
    img = sprites.halve(img)
    return img if factor >= 0.375 else sprites.halve(img)


# How much it matters for whoever's in the room to stand in front of each (see Picture._crowding): a little for each
# bit of it they'd hide, and dearly for any more than they may: a quarter of the fixture (less what's in front of it
# already), half of a feature or an item, or a quarter of one nearer you than them (which they're drawn over).
CROWDING = {"fixture": 1.0, "feature": 0.4, "door": 0.3, "item": 0.25}
DEARLY = {"fixture": 30.0, "feature": 4.0, "item": 4.0}
FIGURE = 1.25  # how big whoever's in the room (or a shopkeeper) is drawn, against the lens's scale
FULL = 30  # a picture this tall or more (the story card, a tall Look panel): items never smaller than their small ones


def _overlap(box: tuple, other: tuple) -> float:
    """How much of `other` a box covers, from 0 to 1. Boxes are (left, top, right, bottom)."""
    width = min(box[2], other[2]) - max(box[0], other[0])
    height = min(box[3], other[3]) - max(box[1], other[1])
    area = (other[2] - other[0]) * (other[3] - other[1])
    return width * height / area if width > 0 and height > 0 and area else 0.0


# --- the picture -------------------------------------------------------------------------------------------

@dataclass
class Light:
    a: float
    z: float
    v: float
    power: float
    radius: float
    warm: float = 1.0


@dataclass
class Placed:
    """A sprite drawn in the picture: what it is (`tag`: occupant, fixture, feature, item or decor), the image as
    drawn, the box its solid pixels fill, (left, top, right, bottom) on the picture, and how far away it stands."""
    tag: str
    img: object
    box: tuple
    z: float = 0.0
    pixels: int = 0  # how many of its pixels were drawn (inside the picture)


class Picture:
    """One room, drawn: surfaces, then decor and everything standing in the room back to front, then whoever is in
    it, then reflections and flames. `kind` says what each pixel shows (wall, floor, water, sky, void, locked,
    ceiling, object); `placed` lists the sprites drawn, and `owner` which of them each pixel shows (-1 for none)."""

    def __init__(self, state: GameState, content: Content, w: int, h: int, room: Room | None = None,
                 frame: int = 0) -> None:
        self.state, self.content, self.room = state, content, room or state.room
        self.frame = frame  # which frame of their idle animation whoever's here and what lies about are drawn in
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
        self.placed: list[Placed] = []
        self.owner = [[-1] * w for _ in range(h)]
        self.centre: tuple | None = None  # the box the fixture (or a shop's stall) fills, if there's one
        self.plans: list[Placed] = []  # where the features, the fixture and the items will stand, before they're drawn
        self.standing: tuple | None = None  # the box whoever's in the room will fill, once that's settled
        self.figure: int | None = None  # how wide they're drawn, when they're whole (see _figure)
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

    def showing(self, index: int) -> float:
        """How much of a placed sprite is still in sight once everything's drawn (1 if none of it was covered)."""
        shown = sum(row.count(index) for row in self.owner)
        return shown / max(1, self.placed[index].pixels)

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
        """Each exit you can see, by wall: where along it (a on the far wall, z on a side wall), and if it's locked.
        `ways` says which way each one goes."""
        doors, self.ways = {}, {}
        for direction, exit_ in self.room.exits.items():
            wall = self.view.side[direction]
            if wall != "behind":
                a, z = self.view.cell(*layout.DOORS[direction])
                doors[wall] = (a if wall == "back" else z, exit_.locked)
                self.ways[wall] = direction
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
            if not feature.hidden and kind in GLOWS and not _unlit(kind, feature.searched or bool(feature.used)):
                a, z = self.view.cell(*feature.pos)
                self.lights.append(Light(a, z, 0.2, 0.6, 0.30, warm=GLOWS[kind]))
        if room.fixture == "shrine" and not room.fixture_used:
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
        elif kind == "locked":  # planks never lost in the dark, with brass bands and a lock: a way you can't take
            along = a if wall == "back" else z
            u = (along - self.doors[wall][0]) / self._door_half(wall)
            if abs(u) < 0.2 and 0.22 < v < 0.34:
                self.px[x, y] = DARK if abs(u) < 0.07 and v < 0.29 else BRASS[1]  # the lock, and its keyhole
            elif abs(v - 0.12) < 0.04 or abs(v - 0.46) < 0.04:
                self.px[x, y] = BRASS[0]
            else:
                level = self.light(a, z, v)[0] - 0.06 * (math.floor(along * 2.2) % 2)
                self.px[x, y] = _pick(look.wood, max(0.4, level), x, y)
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
        elif look.walls == "bubbles":
            bias, mortar = self._bubble(a if wall == "back" else z, v), False
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

    def _bubble(self, along: float, v: float) -> float:
        """Norfair's rock: round cells packed in staggered rows, each with a dark rim and a lit cap at its top left,
        and the dark rock showing between them. How much lighter (or darker) it is here."""
        rows = 4
        w = v * rows
        row = math.floor(w)
        u = along / (2 * self.view.half / 7) + (row % 2) * 0.5
        cell = math.floor(u)
        dx, dy = u - cell - 0.5, (w - row - 0.5) * 1.15
        r = 0.42 + 0.1 * _hash01(row, cell, 61)
        d = math.hypot(dx, dy)
        if d > r:
            return -0.14  # (between the bubbles)
        if d > r - 0.09:
            return -0.24  # (a bubble's rim)
        return 0.2 if dx < -0.05 and dy > 0.05 and d < r * 0.55 else 0.04  # (its cap, lit: v runs up the wall)

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
        frame = self.look.wood if self.look.walls == "earth" else self.look.prop_stone
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
        """The decor, then the things you can do something with (features, the fixture, items), each back to front:
        scenery never hides what matters, as on the room map. Whoever is in the room comes last, so nothing hides them,
        but where they stand is settled first (see _stand), for items to keep clear of them."""
        room, view, lens, look = self.room, self.view, self.lens, self.look
        scenery, things = [], []  # (z, draw)
        tables = {(gx, gy) for gy, line in enumerate(room.grid) for gx, ch in enumerate(line) if ch == "="}
        decor = {"π": "table", "&": "junk", "▤": "shelf", layout.CAGE: "cage", "#": "cage"}  # (an older save's cages)
        for gy, line in enumerate(room.grid):
            for gx, ch in enumerate(line):
                a, z = view.cell(gx, gy)
                inside = 1 <= gx <= WIDTH and 1 <= gy <= HEIGHT
                if not inside or z < (2.0 if ch in ("#", "▤", layout.CAGE) else 1.2):  # right beside you: not seen
                    continue
                if ch == "O":
                    scenery.append((z, lambda a=a, z=z: self._pillar(a, z)))
                elif ch == "=":
                    scenery.append((z + 0.01, lambda gx=gx, gy=gy: self._table(gx, gy, tables)))
                elif ch == "\"" and _hash01(gx, gy, 91) < 0.8:
                    img = _at_scale(_tuft(gx * 31 + gy, look), lens.scale(z) * 1.4)
                    scenery.append((z, lambda a=a, z=z, img=img: self._place(img, a, z, tag="decor")))
                elif ch == "♣":
                    img = _at_scale(_mushroom(gx * 17 + gy), lens.scale(z) * 1.4)
                    scenery.append((z, lambda a=a, z=z, img=img: self._place(img, a, z, lit=True, tag="decor")))
                elif ch in decor:
                    img = prop_at(decor[ch], look, lens.scale(z) * 1.2)
                    scenery.append((z, lambda a=a, z=z, img=img: self._place(img, a, z, tag="decor")))
        for feature in room.features:
            if not feature.hidden and prop_kind(feature.name):
                things.append(self._feature(feature))
        if room.shop or room.fixture:
            a, z = view.cell(CX, CY)
            if room.shop:
                img, lit = self._stall(a, z), True
            else:
                img = _at_scale(fixture_image(room.fixture, look, room.fixture_used), lens.scale(z) * 1.2)
                lit = room.fixture == "shrine" and not room.fixture_used
            self.centre = self._box(img, a, z)  # known before anything's drawn, for what's around it to keep clear of
            self.plans.append(Placed("fixture", img, self.centre, z))
            things.append((z, lambda a=a, z=z, img=img, lit=lit: self._place(img, a, z, lit=lit, framed=True,
                                                                              tag="fixture")))
        figure = self._figure() if room.monster else None  # (how big they are, before the items: half that)
        for key, (gx, gy) in zip(room.items, layout.item_spots(room)):
            small = sprites.frames(f"item_{key}", sprites.SMALL)
            if small:
                things.append(self._item(small[self.frame % len(small)], *view.cell(gx, gy)))
        occupant = self._stand(*figure) if figure else None
        for layer in (scenery, things):
            for _, draw in sorted(layer, key=lambda t: -t[0]):
                draw()
        if occupant:
            self._place(*occupant, lit=True, framed=True, tag="occupant")

    def _feature(self, feature) -> tuple:
        """A feature as a prop of its kind, standing where the room map has it, unless that's in front of the fixture
        (see _aside)."""
        a, z = self.view.cell(*feature.pos)
        kind = prop_kind(feature.name)
        spent = feature.searched or bool(feature.used)
        factor = self.lens.scale(z) * (0.75 if kind in SPRITE_PROPS else 1.6)
        img = prop_at(kind, self.look, factor, feature.name, spent)
        gx, gy = feature.pos
        sunk = kind not in FLAT and any(self._glyph(gx + dx, gy + dy) == "~"
                                        for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)))
        lit = kind in GLOWS and not _unlit(kind, spent)
        order = z + (0.3 if kind in FLAT else 0.0)
        plan = Placed("feature", img, self._box(img, a, z), order)
        self.plans.append(plan)
        return order, lambda: self._place(img, self._aside(img, a, z, item=False, plan=plan), z, lit=lit, sunk=sunk,
                                          framed=True, tag="feature")

    def _stall(self, a: float, z: float):
        """A shop standing at (a, z): her wares on the shelf above her, if the picture has the height for that at full
        size; else on the counter either side of her."""
        factor = self.lens.scale(z) * FIGURE  # she stands where whoever's in a room would
        img = shop_stall(self.room.shop)
        if factor < 0.75 or img.height > self.lens.at(a, z)[1] + 4:
            img = _at_scale(shop_stall(self.room.shop, self.w * (1 if factor >= 0.75 else 2)), factor)
        return img

    def _figure(self) -> tuple | None:
        """Whoever is in the room as they'll be drawn, and where the room map has them, (their picture, a, z): full
        size whenever the picture's tall enough for them (see _whole) and they'd fill no more than half its width,
        else as far off as they stand. None without a sprite."""
        room, view, lens = self.room, self.view, self.lens
        frames = sprites._strip(room.monster.key)
        if not frames:
            return None
        a, z = view.cell(*room.monster_pos)
        z = max(z, 0.3 * view.depth)
        frame = frames[self.frame % len(frames)]
        img = _whole(frame, self.h)  # in their own colours, calm or not: characters always are
        if img.width < frame.width or img.width > self.w // 2:  # (a picture too small for them whole: as far
            # off as they stand, as it always was)
            return self._fit(_at_scale(frame, lens.scale(z) * FIGURE), a, z, framed=True)[0], a, z
        self.figure = img.width  # (whole: what lies about is half that)
        return img, a, z

    def _stand(self, img, a: float, z: float) -> tuple | None:
        """Where whoever is in the room stands, (their picture, a, z): where the room map has them (so the picture
        agrees with what you're told) unless that's right under your nose. Rather than stand in front of the fixture
        they step aside, as far as it takes; and a step or two, rather than hide most of a feature or an item, or much
        of one nearer you than them, which they'd be drawn over (see _crowding). Settled before anything's drawn."""
        x0, _, x1, _ = img.getbbox() or (0, 0, img.width, 0)
        home, doors = self._fit(img, a, z, framed=True)[1], list(self.door_boxes().values())
        fixture = next((p for p in self.plans if p.tag == "fixture"), None)
        in_front = sum(_overlap(p.box, fixture.box) for p in self.plans if p.z < fixture.z) if fixture else 0.0
        spare = 0.25 - in_front  # of the fixture, a quarter less what's in front of it already

        def cost(c: float) -> float:
            moved = abs(self._fit(img, c, z, framed=True)[1] - home) / max(1, x1 - x0)  # in their own widths
            return self._crowding(img, c, z, doors, spare) + 0.15 * moved + 2 * max(0.0, moved - 1)

        a = min(self._steps(a), key=cost)
        self.standing = self._box(img, a, z)
        return img, a, z

    def _steps(self, a: float) -> list[float]:
        """Places across the room a step aside from `a` might be, nearest first."""
        half = self.view.half
        return sorted((c for c in (a + i * half / 25 for i in range(-50, 51)) if abs(c) <= half),
                      key=lambda c: abs(c - a))

    def _covered(self) -> float | None:
        """How much of the fixture what's in front of it so far covers, whoever's in the room included, from 0 (None if
        it's not drawn yet, or there's no fixture)."""
        drawn = next((i for i, p in enumerate(self.placed) if p.tag == "fixture"), None)
        if drawn is None:
            return None
        them = _overlap(self.standing, self.centre) if self.standing else 0.0
        return them + sum(_overlap(p.box, self.centre) for p in self.placed[drawn + 1:] if p.tag != "occupant")

    def _aside(self, img, a: float, z: float, item: bool = True, plan: Placed | None = None) -> float:
        """Where across the floor something standing at (a, z) goes so that, with whatever's in front of the fixture
        already, it hides no more than a quarter of it; and if it's an `item`, so that it loses no more than a quarter
        of itself to the fixture standing in front of it, or to whoever's in the room (drawn over everything); a
        feature only gives way to them rather than lose half of itself. Where it is, if it can; else the nearest place
        that does, and neither covers nor is covered by more than a quarter of any other item or feature (drawn, or
        still to be: `plan` is this one's own), if there's one; else the one that hides least."""
        already = self._covered()  # None: the fixture's still to be drawn, over this (or there's none)
        them = self.standing
        if them is None and (self.centre is None or (already is None and not item)):
            return a

        def hidden(c: float) -> float:
            box = self._box(img, c, z)
            lost = _overlap(them, box) * (1.0 if item else 0.5) if them else 0.0
            if self.centre is not None and already is not None:
                lost = max(lost, already + _overlap(box, self.centre))
            elif self.centre is not None and item:
                lost = max(lost, _overlap(self.centre, box))
            return lost

        if hidden(a) <= 0.25:
            return a
        here = [p.box for p in self.placed + self.plans if p.tag in ("item", "feature") and p is not plan]

        def apart(c: float) -> bool:  # neither over nor under a quarter of another item or feature
            box = self._box(img, c, z)
            return all(_overlap(box, other) <= 0.25 and _overlap(other, box) <= 0.25 for other in here)

        clear = [c for c in self._steps(a) if hidden(c) <= 0.25]
        return next((c for c in clear if apart(c)), clear[0] if clear else min(self._steps(a), key=hidden))

    def _box(self, img, a: float, z: float) -> tuple:
        """The box a framed sprite standing at (a, z) fills on the picture, (left, top, right, bottom)."""
        img, left, top = self._fit(img, a, z, framed=True)
        x0, y0, x1, y1 = img.getbbox() or (0, 0, 0, 0)
        return left + x0, top + y0, left + x1, top + y1

    def _crowding(self, img, a: float, z: float, doors: list, spare: float = 0.25) -> float:
        """How much someone standing at (a, z) would hide (see CROWDING): the fixture above all (`spare` of it, a
        quarter less what's in front of it already, is as much as it should lose to them), then features, items and
        doorways."""
        box = self._box(img, a, z)
        cost = sum(CROWDING["door"] * _overlap(box, door) for door in doors)
        for plan in self.plans:
            hidden = _overlap(box, plan.box)
            most = spare if plan.tag == "fixture" else (0.25 if plan.z < z else 0.5)
            cost += CROWDING[plan.tag] * hidden + DEARLY[plan.tag] * max(0.0, hidden - most)
        return cost

    def door_boxes(self) -> dict[str, tuple]:
        """The box each doorway you can see fills on the picture, (left, top, right, bottom), by wall."""
        boxes: dict[str, tuple] = {}
        for y in range(self.h):
            for x in range(self.w):
                cell = self.info[y][x]
                if cell and cell[0] in ("void", "locked"):
                    x0, y0, x1, y1 = boxes.get(cell[4], (x, y, x + 1, y + 1))
                    boxes[cell[4]] = (min(x0, x), min(y0, y), max(x1, x + 1), max(y1, y + 1))
        return boxes

    def door_marks(self) -> list[tuple[str, int, int]]:
        """Which way each doorway you can see goes, and where to say so in the picture as half-block text: (way,
        column, row), just inside the top of the doorway."""
        marks = []
        for wall, (x0, y0, x1, y1) in self.door_boxes().items():
            marks.append((self.ways[wall], (x0 + x1 - 1) // 2, min(y1 - 1, y0 + 2) // 2))
        return marks

    def _fit(self, img, a: float, z: float, framed: bool) -> tuple:
        """Where a sprite standing at (a, z) goes on the picture: (the sprite, its left, its top). A `framed` one is
        kept wholly inside: moved in from the sides, and if it's taller than the picture above its feet, moved down
        (as if it stood a little nearer), or a size smaller if it's taller than the whole picture or would have to
        come down more than a third of its height."""
        sx, sy = self.lens.at(a, z)
        while framed and img.height >= 4 and not img.info.get("whole") and (
                img.height > self.h or img.height - sy > img.height / 3):
            img = sprites.halve(img)
        left, top = round(sx - img.width / 2), round(sy - img.height)
        if framed:
            left, top = max(0, min(self.w - img.width, left)), max(0, top)
        return img, left, top

    def _place(self, img, a: float, z: float, lit: bool = False, sunk: bool = False, framed: bool = False,
               tag: str = "") -> Placed:
        """A sprite standing on the floor at (a, z), a step darker in shadow (unless it gives light itself). One
        standing in water loses its lower third to it. A `framed` one, something you can do something with, is kept
        wholly inside the picture (see _fit) and only ever a little shadowed."""
        img, left, top = self._fit(img, a, z, framed)
        level, _ = self.light(a, z, 0.3)
        dim = 1.0 if lit else (0.5 if level < 0.22 else (0.72 if level < 0.42 else 1.0))
        dim = max(dim, 0.72) if framed else dim
        x0, y0, x1, y1 = img.getbbox() or (0, 0, 0, 0)
        placed = Placed(tag, img, (left + x0, top + y0, left + x1, top + y1), z)
        index = len(self.placed)
        self.placed.append(placed)
        cut = img.height - max(1, img.height // 3) if sunk else img.height
        src = img.load()
        for y in range(cut):
            for x in range(img.width):
                r, g, b, alpha = src[x, y]
                tx, ty = left + x, top + y
                if alpha < 128 or not (0 <= tx < self.w and 0 <= ty < self.h):
                    continue
                self.px[tx, ty] = (r, g, b) if dim == 1.0 else _shadow((r, g, b), dim)
                self.kind[ty][tx] = "object"
                self.owner[ty][tx] = index
                placed.pixels += 1
        if sunk:  # a ripple where it meets the water
            for x in range(img.width):
                tx, ty = left + x, top + cut
                if 0 <= tx < self.w and 0 <= ty < self.h and src[x, cut - 1][3] >= 128:
                    self.px[tx, ty] = self.look.water[2]
                    self.kind[ty][tx] = "object"
                    self.owner[ty][tx] = index
                    placed.pixels += 1
        return placed

    def _item(self, img, a: float, z: float) -> tuple:
        """Something lying on the floor, in its small picture, with a glint to catch your eye: (z, how to draw it). In
        a picture as tall as the story card's (FULL) it's always that size, never a speck; in a shorter one it's halved
        when whoever's in the room is (or with nobody there, wherever they would be), so a potion is never as big as
        Lucky Lenny beside it. It's moved
        aside, if it must be, rather than lie over a quarter of the fixture or lose a quarter of itself behind it, or
        under whoever's in the room."""
        smaller = self.figure < sprites.DEFAULT_WIDTH if self.figure else self.lens.scale(z) * FIGURE < 0.75
        if self.h < FULL and smaller:  # (half whoever's in the room: never as big as Lucky Lenny beside it)
            img = sprites.halve(img)
        plan = Placed("item", img, self._box(img, self._aside(img, a, z), z), z)
        self.plans.append(plan)

        def draw() -> None:
            placed = self._place(img, self._aside(img, a, z, plan=plan), z, lit=True, framed=True, tag="item")
            x, y = placed.box[2], placed.box[1]
            if 0 <= x < self.w and 0 <= y < self.h:
                self.px[x, y] = _rgb("#ffffff")
                self.owner[y][x] = len(self.placed) - 1

        return z, draw

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


COMPASS = Style(bold=True, color="#fee761", bgcolor="#181425")  # a doorway's way, marked on it
WOOD = {"edge": _rgb("#181425"), "dark": _rgb("#3e2731"), "board": _rgb("#733e39"), "plank": _rgb("#b86f50"),
        "top": _rgb("#c28569"), "shine": _rgb("#e4a672")}


def shop_stall(shop, width: int | None = None) -> Image.Image:
    """A shop as it stands: the shopkeeper behind her counter, and her wares, each its own small picture side by side,
    none of them drawn over her: on the shelf above her, or given a `width`, on the counter either side of her (as
    many as fit that wide), for a picture without the height for the shelf."""
    keeper = (sprites._strip(shop.keeper) or [Image.new("RGBA", (24, 24))])[0]
    icons = [frames[0] for w in shop.wares[:4] if (frames := sprites.frames(f"item_{w.item}", sprites.SMALL))]
    if width is None:
        width, shelf = max(keeper.width + 8, len(icons) * 13 + 3), 13
        spots = [(width - (len(icons) * 13 - 1)) // 2 + i * 13 for i in range(len(icons))]
    else:
        icons = icons[:2 * max(0, (width - keeper.width - 8) // 26)]
        side = (len(icons) + 1) // 2 * 13  # the left side has the odd one out
        width, shelf = keeper.width + 8 + 2 * side, 0
        middle = width // 2
        spots = [middle - keeper.width // 2 - 4 - (i + 1) * 13 + 1 for i in range(side // 13)]
        spots += [middle + keeper.width // 2 + 4 + i * 13 for i in range(len(icons) - len(spots))]
    ground = shelf + keeper.height  # where she stands (her feet behind the counter)
    img = Image.new("RGBA", (width, ground + 2), (0, 0, 0, 0))
    px = img.load()

    def plank(y0: int, y1: int, x0: int, x1: int, front: bool) -> None:
        for y in range(y0, y1):
            for x in range(x0, x1):
                edge = x in (x0, x1 - 1) or y in (y0, y1 - 1)
                if edge:
                    colour = WOOD["edge"]
                elif not front:
                    colour = WOOD["shine"] if y == y0 + 1 else WOOD["plank"]
                else:  # the counter's front: boards, darker low down
                    colour = WOOD["board"] if (x - x0) % 6 == 0 else (WOOD["dark"] if y >= y1 - 2 else WOOD["plank"])
                px[x, y] = (*colour, 255)

    if shelf:
        plank(shelf - 1, shelf + 2, 0, width, front=False)
    img.alpha_composite(keeper, ((width - keeper.width) // 2, ground - keeper.height))
    plank(ground - 7, ground - 5, 1, width - 1, front=False)  # the counter top, at her waist
    plank(ground - 6, ground + 2, 2, width - 2, front=True)
    stand = shelf - 1 if shelf else ground - 7  # each ware stands on the shelf, or on the counter
    for x0, icon in zip(spots, icons):
        img.alpha_composite(icon, (x0, stand - icon.getbbox()[3] if icon.getbbox() else stand - 12))
    return img


def draw(state: GameState, content: Content, width: int, height: int, room: Room | None = None):
    """The room you're in (or another on this floor) as an RGB image, or None without Pillow. `height` should be
    even: two pixels to a row."""
    if Image is None:
        return None
    return Picture(state, content, width, height, room).draw()


PICTURES = 48  # room pictures kept: walking back into a room, or a fight's end, draws it again for free
_pictures: OrderedDict = OrderedDict()
_pictures_lock = threading.Lock()  # (the stage's second idle frame is drawn on a worker thread)


def picture_text(state: GameState, content: Content, width: int, height: int, room: Room | None = None,
                 compass: bool = False, frame: int = 0) -> Text | None:
    """The room you're in (or another on this floor) as half-block text, `width` cells across and height / 2 rows.
    With `compass`, each doorway you can see is marked with the way it goes (N, E, S or W), as on the floor map.
    `frame`: which frame of their idle animation whoever's here and what lies about are in (the stage swaps two).
    The same room drawn the same size again comes from those kept (a room's picture is a fifth of a second's work on
    the game's thread, every time you walk in: docs/plans/performance.md)."""
    if Image is None:
        return None
    room = room or state.room
    key = (id(content), state.seed, state.floor, state.theme, width, height, compass, frame,
           room.model_dump_json(exclude={"history", "description"}))
    with _pictures_lock:
        kept = _pictures.get(key)
        if kept is not None:
            _pictures.move_to_end(key)
            return kept.copy()
    text = _picture_text(state, content, width, height, room, compass, frame)
    with _pictures_lock:
        _pictures[key] = text
        while len(_pictures) > PICTURES:
            _pictures.popitem(last=False)
    return text.copy()


def _picture_text(state: GameState, content: Content, width: int, height: int, room: Room, compass: bool,
                  frame: int) -> Text:
    picture = Picture(state, content, width, height, room, frame)
    text = sprites.image_text(picture.draw().convert("RGBA"), snap=True)
    if not compass:
        return text
    lines = text.split("\n")
    for way, column, row in picture.door_marks():
        if 0 <= row < len(lines) and 0 <= column < len(lines[row]):
            line = lines[row]
            lines[row] = Text.assemble(line[:column], (way[0].upper(), COMPASS), line[column + 1:])
    return Text("\n", no_wrap=True, overflow="crop").join(lines)


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
