"""Spike: the Humongous Fungus made solid, smooth and fine for Blender, the way inflate_thornmother.py made the
Thornmother.

Its sprite (a stand-in in the game's palette, till the kids draw it): a broad cap glowing cyan, four white spots across
it, mid-blue down its shadowed sides and a dark blue rim; a pale stalk with two yellow eyes and a flat frown, shaded
grey down its right side; and a grey skirt round its foot on the floor. Its second frame breathes: the cap sinks a
pixel and the stalk squats. The model keeps all of that and fills in what the flat front view can't show:

- a round cap, flattened front to back as the other bosses' bodies are, its rim a thick dark lip, its gills under it;
- a round stalk with the face on its front: the eyes square and set evenly either side of its middle, sized so they
  shrink to clean blocks; the frown curved down a little at its ends; and a mouth that opens;
- a round skirt on the floor;
- clouds of spores, each on a bone of its own, that it breathes out from under its cap;
- the threads it has grown through the bed, which it pulls tight either side of it before it strikes.

It's built 1.11 times as big as drawn, so it stands as tall as the other bosses (its sprite leaves rows empty above it).

    uv run --no-sync --with numpy python spikes/goblin3d/inflate_fungus.py   # writes humongous_fungus/fungus_mesh.json

build_fungus.py, run inside Blender, rigs and animates it.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image

from inflate_abbot import add
from inflate_king import SIZE
from inflate_mouse import decal
from inflate_serpentis import mirror, mirrored, tube

HERE = Path(__file__).parent
OUT = HERE / "humongous_fungus"
SPRITE = HERE.parents[1] / "src" / "ptg" / "data" / "sprites" / "humongous_fungus.png"

OUTLINE = (24, 20, 37)
CYAN, BLUE, NAVY = (44, 232, 245), (0, 153, 219), (18, 78, 137)
WHITE = (255, 255, 255)
PALE, GREY, SLATE = (192, 203, 220), (139, 155, 180), (58, 68, 102)
YELLOW = (254, 231, 97)

# Every colour it's painted in and the one its shadow side takes, all from its sprite: the cap's cyan to the blue it
# was drawn with down its shadowed sides, that blue to the rim's dark blue, the pale stalk to the grey down its right
# side, the grey skirt to the slate of its frown, the white spores to pale. Its eyes and its frown keep theirs.
SHADES = {CYAN: BLUE, BLUE: NAVY, NAVY: NAVY, WHITE: PALE, PALE: GREY, GREY: SLATE, SLATE: SLATE, YELLOW: YELLOW,
          OUTLINE: OUTLINE}
# What reduce.py counts heavier when it shrinks it, so the small things survive: the spots, spores and threads, its
# eyes, its frown and its open mouth.
HEAVIER = {WHITE: 2.4, YELLOW: 1.2, SLATE: 1.6, OUTLINE: 2.0}
GROUND = 23  # the bottom of its skirt, on the floor
GROW = 1.11  # how much bigger than drawn
VIEW = math.tan(math.radians(12))  # it's seen from 12 degrees above (build_fungus.ELEVATION)


def level(on, x: float, y: float, cx: float, cy: float) -> float:
    """Where (x, y), on a curved surface whose front is on(x, y) forward, looks to be from a little above, as a row
    level with the middle (cx, cy) of what's drawn there: what sits further forward looks lower. A shape drawn by these
    rows looks as it was drawn (an eye on the round stalk would otherwise lean, its inner side lower)."""
    return y + (on(x, y) - on(cx, cy)) * VIEW


# -- the sprite ----------------------------------------------------------------------------------------------------

def sprite() -> dict[tuple[int, int], tuple]:
    sheet = Image.open(SPRITE).convert("RGBA")
    return {(x, y): sheet.getpixel((x, y))[:3] for y in range(SIZE) for x in range(SIZE)
            if sheet.getpixel((x, y))[3] >= 128}


PIXELS = sprite()
SPOT_PIXELS = {(4, 6), (9, 6), (14, 6), (19, 6)}
EYE_PIXELS = {(x, y) for x in (8, 9, 13, 14) for y in (15, 16)}
MOUTH_PIXELS = {(x, 19) for x in range(9, 15)}
assert all(PIXELS.get(p) == WHITE for p in SPOT_PIXELS), "its spots aren't where they were drawn"
assert all(PIXELS.get(p) == YELLOW for p in EYE_PIXELS), "its eyes aren't where they were drawn"
assert all(PIXELS.get(p) == SLATE for p in MOUTH_PIXELS), "its frown isn't where it was drawn"


# -- its cap -------------------------------------------------------------------------------------------------------

# The dome, as the sprite's outline has it: an ellipse from its top (the top of row 3) out to its widest (row 7), 22
# pixels across, then straight down to the dark lip, rows 10 to 12, which bulges a little and rounds under. Under it
# the gills slope down and in to the stalk. How deep it is for its width: flattened, as the other bosses' bodies are.
CAP_TOP, CAP_WIDEST, CAP_HALF = 2.9, 7.5, 11.0
RIM_TOP, RIM_BOTTOM = 10.0, 13.0
DEEP_CAP = 0.45
LIP = [(10.0, 11.0), (10.5, 11.15), (11.0, 11.25), (11.5, 11.3), (12.0, 11.25), (12.4, 11.1), (12.7, 10.85),
       (12.9, 10.45), (RIM_BOTTOM, 10.0)]
GILLS = [(13.15, 9.0), (13.3, 7.8), (13.45, 6.6), (13.55, 5.6), (13.65, 4.8)]  # hidden behind the lip from above
SPOT_UP = 0.6  # the spots sit forward on the dome, so from a little above they look lower than drawn: raised to make up


def dome_half_width(y: float) -> float:
    """The cap's half-width at row y, down to the top of its lip."""
    if y >= CAP_WIDEST:
        return CAP_HALF
    v = (CAP_WIDEST - y) / (CAP_WIDEST - CAP_TOP)
    return CAP_HALF * math.sqrt(max(1 - v * v, 0.0))


def on_cap(x: float, y: float) -> float:
    """How far forward the cap's front is at (x, y)."""
    w = dome_half_width(y)
    return DEEP_CAP * math.sqrt(max(w * w - (x - 12) ** 2, 0.0))


def cap_profile() -> list[tuple[float, float, tuple]]:
    """(row, half-width, colour of the band from the ring before), from its top to under it."""
    out = []
    for n in range(1, 25):  # the dome, evenly round its curve (its very top closed flat)
        phi = (math.pi / 2) * n / 24
        out.append((CAP_WIDEST - (CAP_WIDEST - CAP_TOP) * math.cos(phi), CAP_HALF * math.sin(phi), CYAN))
    out += [(8.3, CAP_HALF, CYAN), (9.2, CAP_HALF, CYAN)]
    out += [(y, w, CYAN if y == RIM_TOP else NAVY) for y, w in LIP]
    out += [(y, w, CYAN) for y, w in GILLS]  # the gills, painted as the cap: always in shadow, so blue
    return out


def lathe(profile: list, deep: float, weigh, sides: int = 96, cx: float = 12.0, cz: float = 0.0) -> dict:
    """A round part turned on an upright axis at (cx, cz), squashed front to back by `deep`: rings of (row,
    half-width, colour of the band from the ring before), top to bottom, closed flat at both ends. weigh(y) gives the
    bones at row y."""
    verts, faces, colours, weights = [], [], [], []
    for y, w, _ in profile:
        for k in range(sides):
            a = 2 * math.pi * k / sides
            verts.append((cx + w * math.sin(a), y, cz + deep * w * math.cos(a)))
            weights.append(weigh(y))
    for n in range(1, len(profile)):
        r0, r1 = (n - 1) * sides, n * sides
        for k in range(sides):
            faces.append([r0 + k, r1 + k, r1 + (k + 1) % sides, r0 + (k + 1) % sides])
            colours.append(profile[n][2])
    end = (len(profile) - 1) * sides
    faces += [list(range(sides)), list(range(end + sides - 1, end - 1, -1))]
    colours += [profile[1][2], profile[-1][2]]
    return dict(smooth=False, recalc=True, verts=verts, faces=faces, colours=colours, weights=weights)


def cap() -> dict:
    return dict(bone="cap", **lathe(cap_profile(), DEEP_CAP, lambda y: {"cap": 1.0}, sides=128))


def spots() -> dict:
    """Its four white spots across the dome, a little bigger than its single pixels and square, and counted heavy
    when it's shrunk (HEAVIER), so none is ever lost when it's small. As the cap breathes they glint, a dot or a
    little block (round ones come out as crosses)."""
    centres = [(x + 0.5, y + 0.5 - SPOT_UP) for x, y in sorted(SPOT_PIXELS)]

    def inside(x, y):
        return WHITE if any(abs((x - cx) / 0.6) ** 12 + abs((level(on_cap, x, y, cx, cy) - cy) / 0.6) ** 12 <= 1
                            for cx, cy in centres) else None
    return decal(inside, on_cap, 0.1, "cap")


# -- its stalk and face --------------------------------------------------------------------------------------------

STALK_HALF, DEEP_STALK = 5.0, 0.55
STALK = [(12.6, 5.0), (14.0, 5.0), (16.0, 5.0), (18.0, 5.0), (19.8, 5.0), (20.6, 5.15), (21.6, 5.4)]
FACE_UP = 0.35  # its face sits forward on the stalk, so from a little above it looks lower than drawn: raised
# Its eyes, evenly either side of its middle (drawn half a pixel to the left), each a little over two pixels across,
# and a touch lower than drawn: sized and placed so that, shrunk, each comes out a square block at every size the
# game shows it at (2, 2, 3 and 4 pixels at 40, 48, 64 and 84). reduce.py puts each big pixel in the small one its
# left edge falls in, so they're nudged a hair to the right (half a big pixel) to come out alike.
EYE_APART, EYE_HALF, EYE_RIGHTWARD = 2.5, 1.1, 0.085
EYES = (12 - EYE_APART + EYE_RIGHTWARD, 12 + EYE_APART + EYE_RIGHTWARD)
EYE_Y = 16.0 - FACE_UP + 0.175
MOUTH_Y = 19.5 - FACE_UP


def on_stalk(x: float, y: float) -> float:
    return DEEP_STALK * math.sqrt(max(STALK_HALF ** 2 - (x - 12) ** 2, 0.0))


def stalk() -> dict:
    profile = [(y, w, PALE) for y, w in STALK]
    return dict(bone="stalk", **lathe(profile, DEEP_STALK, lambda y: {"stalk": 1.0}))


def eye(side: str) -> dict:
    """A square yellow eye, two pixels across as drawn and a little more: shrunk, square ones come out as blocks,
    where rounder ones come out as crosses. It glows, so it keeps its colour all round."""
    ex = EYES[0] if side == "l" else EYES[1]

    def inside(x, y):
        dy = level(on_stalk, x, y, ex, EYE_Y) - EYE_Y
        return YELLOW if abs((x - ex) / EYE_HALF) ** 12 + abs(dy / EYE_HALF) ** 12 <= 1 else None
    return decal(inside, on_stalk, 0.08, f"eye_{side}")


def frown(x: float, y: float) -> tuple | None:
    """Its mouth, six pixels across as drawn and a little thicker, its ends turned down."""
    if abs(x - 12) > 3.0:
        return None
    mid = MOUTH_Y + 0.45 * ((x - 12) / 3.0) ** 2
    return SLATE if abs(level(on_stalk, x, y, 12, MOUTH_Y) - mid) <= 0.55 else None


def gape(x: float, y: float) -> tuple | None:
    """Its mouth open as wide as it goes, down from the frown: the bone squeezes it shut."""
    y = level(on_stalk, x, y, 12, MOUTH_Y)
    return OUTLINE if ((x - 12) / 2.3) ** 2 + ((y - (MOUTH_Y + 0.25)) / 1.5) ** 2 <= 1 and y >= MOUTH_Y - 0.6 \
        else None


# -- its skirt -----------------------------------------------------------------------------------------------------

# Round its foot on the floor, rows 21 and 22 as drawn, 14 pixels across, its top edge rounded. Flattened front to back
# like the rest, so its front doesn't come down below the floor in the picture by much.
DEEP_BASE = 0.42
BASE = [(20.95, 5.2), (21.0, 6.0), (21.12, 6.6), (21.35, 6.92), (21.7, 7.05), (22.4, 7.05), (22.75, 6.95),
        (22.92, 6.75), (GROUND, 6.4)]


def base() -> dict:
    return dict(bone="base", **lathe([(y, w, GREY) for y, w in BASE], DEEP_BASE, lambda y: {"base": 1.0}))


# -- spores and threads --------------------------------------------------------------------------------------------

def ball(centre: tuple, r: float, colour: tuple, bone: str, rings: int = 7, sides: int = 12) -> dict:
    """A round lump."""
    cx, cy, cz = centre
    verts = [(cx, cy - r, cz)]
    for n in range(1, rings):
        b = math.pi * n / rings
        for k in range(sides):
            a = 2 * math.pi * k / sides
            verts.append((cx + r * math.sin(b) * math.sin(a), cy - r * math.cos(b), cz + r * math.sin(b) * math.cos(a)))
    verts.append((cx, cy + r, cz))
    faces = [[0, 1 + (k + 1) % sides, 1 + k] for k in range(sides)]
    for n in range(rings - 2):
        r0, r1 = 1 + n * sides, 1 + (n + 1) * sides
        faces += [[r0 + k, r0 + (k + 1) % sides, r1 + (k + 1) % sides, r1 + k] for k in range(sides)]
    last, bottom = 1 + (rings - 2) * sides, len(verts) - 1
    faces += [[last + k, last + (k + 1) % sides, bottom] for k in range(sides)]
    return dict(smooth=False, recalc=True, verts=verts, faces=faces, colours=[colour] * len(faces),
                weights=[{bone: 1.0}] * len(verts))


# A cloud of spores: a round lump with two smaller ones beside it, about its middle. Each cloud lives on a bone of its
# own, which carries it and grows it (0 hides it). They rest under the cap, either side of the stalk.
CLOUDS = [
    [(0.0, 0.0, 0.0, 1.15), (-1.0, 0.35, 0.15, 0.85), (0.95, 0.4, -0.1, 0.78)],
    [(0.0, 0.0, 0.0, 1.1), (0.9, -0.4, 0.1, 0.82), (-0.85, 0.45, -0.15, 0.74)],
    [(0.0, 0.0, 0.0, 1.15), (-0.7, -0.65, 0.1, 0.72), (1.0, 0.25, 0.05, 0.82)],
    [(0.0, 0.0, 0.0, 1.05), (0.7, 0.6, 0.1, 0.78), (-0.95, 0.15, -0.1, 0.76)],
]
PUFFS = 8
PUFF_AT = [(7.0 if n < PUFFS // 2 else 17.0, 13.6, 0.5) for n in range(PUFFS)]


def cloud(n: int) -> dict:
    bone = f"puff_{n + 1}"
    cx, cy, cz = PUFF_AT[n]
    verts, faces, colours, weights = [], [], [], []
    for dx, dy, dz, r in CLOUDS[n % len(CLOUDS)]:
        add(ball((cx + dx, cy + dy, cz + dz), r, WHITE, bone), verts, faces, colours, weights)
    return dict(bone=bone, smooth=False, recalc=True, verts=verts, faces=faces, colours=colours, weights=weights)


# The threads it has grown through the bed: one either side, from inside its stalk low down, out and down to where
# it's anchored in the floor, a little behind it (so from a little above it doesn't come down below the floor). Drawn
# taut, it's a straight line under strain. Each is on a bone from the stalk to its anchor, which pulls it out (and
# back in: 0 hides it). The one on the viewer's left:
THREAD_R = 0.55
THREAD = ((7.4, 18.9, -0.2), (-2.6, GROUND - 0.95 * THREAD_R, -1.0))


def thread() -> dict:
    return dict(bone="thread_l", **tube(list(THREAD), [THREAD_R, THREAD_R * 0.85], lambda s, a: WHITE,
                                        lambda u: {"thread_l": 1.0}, steps=6, sides=10, tip=0.3))


# -- the rig -------------------------------------------------------------------------------------------------------

def bones() -> dict:
    """Each bone's parent, pivot and where it points (x right, y down, z toward the viewer, in pixels as drawn). The
    face's bones sit on the face, so squeezing an eye or the mouth never sinks it into the stalk."""
    def r(p):
        return (mirror(p[0]), *p[1:])
    eye_z = [on_stalk(x, EYE_Y) + 0.08 for x in EYES]
    mouth_z = on_stalk(12, MOUTH_Y)
    out = {
        "root":  (None,    (12, GROUND, 0),             (12, 20, 0)),
        "base":  ("root",  (12, GROUND, 0),             (12, 20.95, 0)),
        "stalk": ("root",  (12, 21.2, 0),               (12, 13.4, 0)),
        "cap":   ("stalk", (12, 13.4, 0),               (12, CAP_TOP, 0)),
        "eye_l": ("stalk", (EYES[0], EYE_Y, eye_z[0]),  (EYES[0], EYE_Y - 1, eye_z[0])),
        "eye_r": ("stalk", (EYES[1], EYE_Y, eye_z[1]),  (EYES[1], EYE_Y - 1, eye_z[1])),
        "mouth": ("stalk", (12, MOUTH_Y, mouth_z + 0.08), (12, MOUTH_Y - 1, mouth_z + 0.08)),
        "gape":  ("stalk", (12, MOUTH_Y - 0.6, mouth_z + 0.14), (12, MOUTH_Y + 1.4, mouth_z + 0.14)),
        "glow":  (None,    (12, GROUND + 3, 0),         (12, GROUND + 2, 0)),  # no flesh: it lights the cap
    }
    for n in range(PUFFS):  # free of the rest, so its fall and squash don't carry them
        x, y, z = PUFF_AT[n]
        out[f"puff_{n + 1}"] = (None, (x, y, z), (x, y - 1.5, z))
    out["thread_l"] = ("root", *THREAD)
    out["thread_r"] = ("root", *(r(p) for p in THREAD))
    return out


SWAP = {"thread_l": "thread_r"}


def grown(v: tuple) -> tuple:
    """A point of the model as drawn, GROW times bigger about the middle of its foot."""
    x, y, z = v
    return 12 + GROW * (x - 12), GROUND - GROW * (GROUND - y), GROW * z


# -- the lot -------------------------------------------------------------------------------------------------------

def build() -> dict:
    parts = {
        "cap": cap(), "spots": spots(), "stalk": stalk(), "base": base(),
        "eye_l": eye("l"), "eye_r": eye("r"),
        "mouth": decal(frown, on_stalk, 0.08, "mouth"),
        "gape": decal(gape, on_stalk, 0.14, "gape"),
    }
    for n in range(PUFFS):
        parts[f"puff_{n + 1}"] = cloud(n)
    parts["thread_l"] = thread()
    parts["thread_r"] = mirrored(parts["thread_l"], SWAP)

    def hexed(c):
        return "#%02x%02x%02x" % c

    return {
        "sprite": "humongous_fungus", "size": SIZE, "fine": 8, "ground": GROUND, "centre": 12, "grow": GROW,
        "shades": {hexed(lit): hexed(dark) for lit, dark in SHADES.items()},
        "outline": hexed(OUTLINE),
        "heavier": {hexed(c): w for c, w in HEAVIER.items()},
        "bones": {name: {"parent": parent, "head": [round(float(c), 4) for c in grown(head)],
                         "tail": [round(float(c), 4) for c in grown(tail)]}
                  for name, (parent, head, tail) in bones().items()},
        "parts": {name: {**part, "colours": [hexed(c) for c in part["colours"]],
                         "verts": [[round(float(c), 4) for c in grown(v)] for v in part["verts"]]}
                  for name, part in parts.items()},
    }


def main() -> None:
    data = build()
    OUT.mkdir(exist_ok=True)
    path = OUT / "fungus_mesh.json"
    path.write_text(json.dumps(data, separators=(",", ":")))
    print(f"-> {path} ({path.stat().st_size // 1024} KB)")
    for name, part in data["parts"].items():
        print(f"  {name:10} {part['bone']:10} {len(part['verts']):6} verts {len(part['faces']):6} faces "
              f"{sorted(set(part['colours']))}")


if __name__ == "__main__":
    main()
