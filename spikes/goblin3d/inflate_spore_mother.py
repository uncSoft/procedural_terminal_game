"""Spike: the Spore Mother made solid, smooth and fine for Blender, the way inflate_thornmother.py made the Thornmother.

Her sprite (a stand-in drawn in the game's palette, till the kids draw her): a pink toadstool cap with two white
spots, violet round its rim; a plump, round cream body under it; and a soft green glow in her middle with a white glint
in it, like a lamp in a window, which dims in her second frame. The model keeps all of that and fills in what the flat
front view can't show:

- a round cap, turned on a lathe, its rim curled under and violet beneath, so it can tip, puff up and butt like a
  ram's head;
- a round body under it, turned the same way, which squashes and stretches as she breathes and lands;
- her glow as a lamp in her middle: a dim green, a bright green over it that grows and shrinks as it pulses, and the
  white glint, each laid flat just in front of her, so it can pulse without sinking into her;
- spores puffed up out of her cap when she shows off, and burst from it where she butts.

Where the sprite draws something on her front (her spots, her glow), it's put where it looks drawn from the camera's
12 degrees above: things forward of her middle look lower from up there, so they're raised to make up for it.

    uv run --no-sync --with numpy python spikes/goblin3d/inflate_spore_mother.py   # spore_mother/spore_mother_mesh.json

build_spore_mother.py, run inside Blender, rigs and animates her.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from inflate_abbot import add
from inflate_king import K, SIZE
from inflate_mouse import catmull, decal

HERE = Path(__file__).parent
OUT = HERE / "spore_mother"

OUTLINE = (24, 20, 37)
PINK, VIOLET = (246, 117, 122), (181, 80, 136)
WHITE, CREAM = (255, 255, 255), (234, 212, 170)
GREEN, DARK_GREEN = (99, 199, 77), (62, 137, 72)

# Every colour she's painted in and the one its shadow side takes, all from her sprite: her cap's pink to the violet
# she was drawn with round its rim. Her cream body has no shade drawn, so it keeps its cream; her spots, her glow and
# her glint shine whichever way they face.
SHADES = {PINK: VIOLET, VIOLET: VIOLET, CREAM: CREAM, WHITE: WHITE, GREEN: GREEN, DARK_GREEN: DARK_GREEN,
          OUTLINE: OUTLINE}
# What reduce.py counts heavier when it shrinks her, so the small things survive: her spots and glint, her glow.
HEAVIER = {WHITE: 3.0, GREEN: 1.6, DARK_GREEN: 1.6}
GROUND = 23  # the bottom of her body, as drawn: a pixel lower than the King's boots
TAN = math.tan(math.radians(12))  # from 12 degrees above, a thing this much nearer looks this much lower, per pixel


# -- turning on a lathe ------------------------------------------------------------------------------------------------

def lathe(profile: list, deep: float, paint, bone: str, steps: int = 6, sides: int = 128) -> dict:
    """A round thing turned on an upright axis through x = 12: profile is (y, radius) from its top to its bottom, as
    smooth as a curve through them; it's `deep` times as deep as it is wide. paint(a, y, r, u) colours it by how far
    round from its front (a, in radians), how far down (y), how wide it is there (r) and how far along the profile
    (u, counted in points). A radius of 0 closes it in a point."""
    path = catmull(profile, steps)
    verts, faces, colours, rings = [], [], [], []
    for _, (y, r) in path:
        if r <= 1e-6:
            verts.append((12.0, float(y), 0.0))
            rings.append([len(verts) - 1] * sides)
            continue
        start = len(verts)
        for k in range(sides):
            a = 2 * math.pi * k / sides
            verts.append((12 + r * math.sin(a), float(y), deep * r * math.cos(a)))
        rings.append(list(range(start, start + sides)))
    for n in range(1, len(path)):
        r0, r1 = rings[n - 1], rings[n]
        y, r = (path[n - 1][1] + path[n][1]) / 2
        u = (path[n - 1][0] + path[n][0]) / 2
        for k in range(sides):
            face = list(dict.fromkeys([r0[k], r1[k], r1[(k + 1) % sides], r0[(k + 1) % sides]]))
            if len(face) < 3:
                continue
            faces.append(face)
            colours.append(paint(2 * math.pi * (k + 0.5) / sides, float(y), float(r), u))
    return dict(bone=bone, smooth=False, recalc=True, verts=verts, faces=faces, colours=colours)


def outer(profile: list, upto: int, steps: int = 6):
    """The radius down the outside of a profile (its points before `upto`), by y: for what's laid on its front."""
    path = [p for u, p in catmull(profile, steps) if u <= upto - 1]
    ys, rs = np.array([p[0] for p in path]), np.array([p[1] for p in path])
    return lambda y: float(np.interp(y, ys, rs))


# -- her cap -----------------------------------------------------------------------------------------------------------

# Its outside, from the middle of its top out to its widest and down round its curled rim; then its underside back in
# to the middle. As wide as drawn (16 pixels), round.
CAP = [(6.15, 0.0), (6.2, 1.6), (6.35, 3.0), (6.7, 4.3), (7.2, 5.4), (7.8, 6.35), (8.5, 7.1), (9.3, 7.65),
       (10.15, 7.95), (10.95, 8.0), (11.65, 7.8), (12.25, 7.3), (12.6, 6.6), (12.8, 5.6), (12.9, 4.2), (12.95, 2.5),
       (13.0, 0.0)]
RIM = 12  # the point where her rim turns under
CAP_DEEP = 1.0
PIVOT = 12.8  # where her cap sits on her, under its middle
# Her cap is tipped back from upright by this much: from 12 degrees above, it's then seen nearly as she was drawn, the
# front of its rim no lower than its sides and her cream neck showing under its middle, and not much of its top.
TIP = math.radians(9)


def tip(v: tuple) -> tuple:
    """A point on her cap tipped back about its pivot (its top away from the viewer, the front of its rim up)."""
    x, y, z = v
    h = PIVOT - y
    return (x, PIVOT - (h * math.cos(TIP) + z * math.sin(TIP)), z * math.cos(TIP) - h * math.sin(TIP))


def seen(v: tuple) -> float:
    """How far down the picture a point looks from 12 degrees above, in the sprite's pixels: nearer ones look lower."""
    return v[1] + TAN * v[2]


def band(x: float) -> float:
    """Where the violet starts, down the picture, as the sprite draws it: a pixel above her cap's bottom edge under its
    middle, rising up its sides to three pixels at its edge."""
    return 12.0 - 3.0 * max(0.0, (abs(x - 12) - 3.0) / 5.0) ** 1.3


def cap_paint(a: float, y: float, r: float, u: float) -> tuple:
    """Violet underneath and round its rim, where the sprite's band is (seen from in front, as it rests; the same
    round the back), pink above."""
    if u >= RIM:
        return VIOLET
    front = tip((12 + r * math.sin(a), y, CAP_DEEP * r * abs(math.cos(a))))
    return VIOLET if seen(front) >= band(front[0]) else PINK


def tipped(part: dict) -> dict:
    return {**part, "verts": [tip(v) for v in part["verts"]]}


def cap() -> dict:
    return tipped(lathe(CAP, CAP_DEEP, cap_paint, "cap"))


cap_radius = outer(CAP, RIM)


def on_cap(x: float, y: float) -> float:
    """How far forward her cap's front is at (x, y), upright."""
    return CAP_DEEP * math.sqrt(max(cap_radius(y) ** 2 - (x - 12) ** 2, 0.0))


# Her two white spots, where they look drawn (the middles of the sprite's pixels), squarish so they stay dots small
# and blobs big, and a little bigger than her single pixels so they survive.
SPOTS = [(8.5, 8.5), (15.5, 9.5)]
SPOT = 0.68


def spots() -> dict:
    """Laid on her cap upright, where they'll be seen as drawn once it's tipped back."""
    def inside(x, y):
        at = seen(tip((x, y, on_cap(x, y))))
        return WHITE if any(abs((x - sx) / SPOT) ** 4 + abs((at - sy) / SPOT) ** 4 <= 1 for sx, sy in SPOTS) \
            else None
    return tipped(decal(inside, on_cap, 0.06, "cap"))


# -- her body ----------------------------------------------------------------------------------------------------------

# Its outside, from its top (up inside her cap) to the bottom she sits on, as wide as drawn: plump and round, widest
# a little below her middle, tucked in at the bottom.
BODY = [(12.3, 0.0), (12.35, 1.6), (12.6, 2.6), (13.2, 3.4), (14.0, 4.1), (14.8, 4.75), (15.6, 5.3), (16.5, 5.75),
        (17.5, 6.0), (18.5, 6.0), (19.5, 5.75), (20.4, 5.2), (21.2, 4.4), (21.9, 3.4), (22.45, 2.3), (22.8, 1.3),
        (23.0, 0.0)]
BODY_DEEP = 0.95


def body() -> dict:
    return lathe(BODY, BODY_DEEP, lambda a, y, r, u: CREAM, "body")


# -- her glow ----------------------------------------------------------------------------------------------------------

# Where it looks drawn: a round glow six pixels across under her middle, the glint up and left in it, toward the light.
GLOW_AT, GLOW_R = (12.0, 19.0), 3.05
GLINT_AT, GLINT = (11.5, 18.5), 0.64
FRONT = BODY_DEEP * 6.0  # how far forward her body comes, at her middle
LIFTS = {"dim": 0.15, "glow": 0.25, "glint": 0.35}  # each a little in front of the one under it


def disc(shape, colour: tuple, lift: float, bone: str) -> dict:
    """A flat disc facing the viewer just in front of her body, its shape as it's seen from above: things in front
    look lower, so it's laid that much higher."""
    depth = FRONT + lift
    return decal(lambda x, y: colour if shape(x, y + TAN * depth) else None, lambda x, y: FRONT, lift, bone)


def round_glow(x: float, y: float) -> bool:
    return (x - GLOW_AT[0]) ** 2 + (y - GLOW_AT[1]) ** 2 <= GLOW_R ** 2


def glint(x: float, y: float) -> bool:
    return abs((x - GLINT_AT[0]) / GLINT) ** 4 + abs((y - GLINT_AT[1]) / GLINT) ** 4 <= 1


def model_y(seen: float, lift: float) -> float:
    """Where on her a disc must go to be seen at `seen`."""
    return seen - TAN * (FRONT + lift)


# -- spores ------------------------------------------------------------------------------------------------------------

def ball(centre: tuple, radius: float, colour: tuple, bone: str) -> dict:
    """A little round spore."""
    cx, cy, cz = centre
    profile = [(cy - radius * math.cos(math.pi * s / 6), radius * math.sin(math.pi * s / 6)) for s in range(7)]
    verts, faces, colours = [], [], []
    rings = []
    for y, r in profile:
        if r < 1e-6:
            verts.append((cx, y, cz))
            rings.append([len(verts) - 1] * 10)
            continue
        start = len(verts)
        verts += [(cx + r * math.sin(2 * math.pi * k / 10), y, cz + r * math.cos(2 * math.pi * k / 10))
                  for k in range(10)]
        rings.append(list(range(start, start + 10)))
    for r0, r1 in zip(rings, rings[1:]):
        for k in range(10):
            face = list(dict.fromkeys([r0[k], r1[k], r1[(k + 1) % 10], r0[(k + 1) % 10]]))
            if len(face) >= 3:
                faces.append(face)
                colours.append(colour)
    return dict(verts=verts, faces=faces, colours=colours, weights=[{bone: 1.0}] * len(verts))


CROWN = tip((12.0, CAP[0][0], 0.0))  # the top of her cap
# Where the top of her cap is when her butt lands (build_spore_mother.py's attack, frame 8: the build says if it moves).
BURST_AT = (28.15, 7.0, -1.15)
# Spores thrown up out of her cap in a fan when she shows off, and burst out where her butt lands, away from her. Each
# lot lives on a bone where it starts, which spreads them as it grows (0 hides them): the puff's rides on her cap, the
# burst's stays where it hit while she bounces back.
# Three apiece, five pixels apart, so the outline round each doesn't run them together when she's small.
PUFF = [(-4.6, -3.0, 0.8), (0.2, -5.8, 1.0), (4.8, -2.6, 0.8)]
BURST = [(0.6, -4.6, 1.0), (3.2, -0.6, 1.0), (1.8, 3.8, 1.0)]


def spores(at: tuple, spray: list, radius: float, bone: str) -> dict:
    verts, faces, colours, weights = [], [], [], []
    for dx, dy, dz in spray:
        add(ball((at[0] + dx, at[1] + dy, at[2] + dz), radius, GREEN, bone), verts, faces, colours, weights)
    return dict(bone=bone, smooth=False, recalc=True, verts=verts, faces=faces, colours=colours, weights=weights)


# -- the rig -----------------------------------------------------------------------------------------------------------

def bones() -> dict:
    """Parent, pivot and where each points (x right, y down, z toward the viewer, in sprite pixels). Her glow and glint
    grow and shrink about their middles; the burst hangs on no bone of hers, where her butt lands."""
    glow = (GLOW_AT[0], model_y(GLOW_AT[1], LIFTS["glow"]), FRONT + LIFTS["glow"])
    glint = (GLINT_AT[0], model_y(GLINT_AT[1], LIFTS["glint"]), FRONT + LIFTS["glint"])

    def up(p, by):
        return (p[0], p[1] - by, p[2])
    return {
        "root":  (None,   (12, GROUND, 0), (12, 20, 0)),
        "body":  ("root", (12, GROUND, 0), (12, PIVOT, 0)),
        "cap":   ("body", (12, PIVOT, 0),  CROWN),
        "glow":  ("body", glow,            up(glow, 2)),
        "glint": ("body", glint,           up(glint, 1)),
        "puff":  ("cap",  CROWN,           tip((12, CAP[0][0] - 3, 0))),
        "burst": (None,   BURST_AT,        up(BURST_AT, 3)),
    }


# -- the lot -----------------------------------------------------------------------------------------------------------

def build() -> dict:
    parts = {
        "body": body(),
        "cap": cap(),
        "spots": spots(),
        "dim": disc(round_glow, DARK_GREEN, LIFTS["dim"], "body"),
        "glow": disc(round_glow, GREEN, LIFTS["glow"], "glow"),
        "glint": disc(glint, WHITE, LIFTS["glint"], "glint"),
        "puff": spores(CROWN, PUFF, 1.0, "puff"),
        "burst": spores(BURST_AT, BURST, 1.0, "burst"),
    }

    def hexed(c):
        return "#%02x%02x%02x" % c

    return {
        "sprite": "spore_mother", "size": SIZE, "fine": K, "ground": GROUND, "centre": 12,
        "shades": {hexed(lit): hexed(dark) for lit, dark in SHADES.items()},
        "outline": hexed(OUTLINE),
        "heavier": {hexed(c): w for c, w in HEAVIER.items()},
        "bones": {name: {"parent": parent, "head": [float(c) for c in head], "tail": [float(c) for c in tail]}
                  for name, (parent, head, tail) in bones().items()},
        "parts": {name: {**part, "colours": [hexed(c) for c in part["colours"]],
                         "verts": [[round(float(c), 4) for c in v] for v in part["verts"]]}
                  for name, part in parts.items()},
    }


def main() -> None:
    data = build()
    OUT.mkdir(exist_ok=True)
    path = OUT / "spore_mother_mesh.json"
    path.write_text(json.dumps(data, separators=(",", ":")))
    print(f"-> {path} ({path.stat().st_size // 1024} KB)")
    for name, part in data["parts"].items():
        print(f"  {name:6} {part['bone']:6} {len(part['verts']):6} verts {len(part['faces']):6} faces "
              f"{sorted(set(part['colours']))}")
    cap_seen = [seen(v) for v in data["parts"]["cap"]["verts"]]
    print(f"  her cap looks {min(cap_seen):.2f} to {max(cap_seen):.2f} down the picture (drawn: 6 to 13)")


if __name__ == "__main__":
    main()
