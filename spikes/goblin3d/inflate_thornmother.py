"""Spike: the Thornmother made solid, smooth and fine for Blender, the way inflate_abbot.py made the Drowned Abbot.

Her sprite: a gold face with two dark eyes and a flat mouth, in a pink bloom of petals, purple in their shadows; a
green bulb of a body spotted with lime; thin thorny vines for arms, bent up beside her face; and roots splayed under
her to the floor. The model keeps all of that and fills in what the flat front view can't show:

- each petal a petal of its own, round her face and tipped back from it, so they can close over it in a bud and open
  again, and flare;
- a face that sits forward of her body, with a mouth that opens (shut, it's the line she was drawn with);
- a round body, its lime spots on its front;
- vines with thorns on them, which can uncurl and stretch to lash;
- roots on bones of their own, planted, so her body can sink and rise on them;
- bits of leaf thrown up when she lands, and shards where her vine cracks.

    uv run --no-sync --with numpy python spikes/goblin3d/inflate_thornmother.py   # writes thornmother/thornmother_mesh.json

build_thornmother.py, run inside Blender, rigs and animates her.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from inflate_abbot import add
from inflate_king import K, SIZE, epx, pillow
from inflate_mouse import cells, decal, surface
from inflate_serpentis import chain, mirror, mirrored, tube

HERE = Path(__file__).parent
OUT = HERE / "thornmother"
SPRITE = HERE.parents[1] / "src" / "ptg" / "data" / "sprites" / "thornmother.png"

OUTLINE = (24, 20, 37)
GREEN, DARK, LIME = (62, 137, 72), (38, 92, 66), (99, 199, 77)
PINK, PLUM = (181, 80, 136), (104, 56, 108)
GOLD = (254, 231, 97)

# Every colour she's painted in and the one its shadow side takes, all from her sprite: her green to the dark green she
# was drawn with down her shadowed side, her petals' pink to their purple. Her face, her spots and the dark keep theirs.
SHADES = {GREEN: DARK, DARK: DARK, LIME: LIME, PINK: PLUM, PLUM: PLUM, GOLD: GOLD, OUTLINE: OUTLINE}
# What reduce.py counts heavier when it shrinks her, so the small things survive: her eyes and mouth, her spots.
HEAVIER = {OUTLINE: 2.2, LIME: 2.0}
GROUND = 23  # the bottom of the roots splayed under her


# -- the sprite ----------------------------------------------------------------------------------------------------

def sprite() -> dict[tuple[int, int], tuple]:
    sheet = Image.open(SPRITE).convert("RGBA")
    return {(x, y): sheet.getpixel((x, y))[:3] for y in range(SIZE) for x in range(SIZE)
            if sheet.getpixel((x, y))[3] >= 128}


PIXELS = sprite()
EYES = {(9, 6), (14, 6)}
MOUTH_PIXELS = {(x, 8) for x in range(10, 14)}
assert all(PIXELS[p] == OUTLINE for p in EYES | MOUTH_PIXELS), "her face isn't where it was drawn"


def fine() -> list[list]:
    """Her face, scaled up the pixel-art way. Everything else is built round, below."""
    grid = [[("face", GOLD) if PIXELS.get((x, y)) == GOLD or (x, y) in EYES | MOUTH_PIXELS else None
             for x in range(SIZE)] for y in range(SIZE)]
    for _ in range(int(math.log2(K))):
        grid = epx(grid)
    return grid


def face_mid(x: float, y: float) -> float:
    """Her face sits forward of her body's top, tipped up a little toward whoever looks down at her."""
    return 4.4 + 0.18 * (y - 6.5)


FACE = dict(bone="head", depth=1.0, flat=0.8, back=GOLD, behind=0.8, mid=face_mid)
FACE_UP = 0.5  # her face sits forward, so from a little above it looks lower than drawn: it's raised to make up


# -- her petals ----------------------------------------------------------------------------------------------------

# Where each petal's tip reaches, as the sprite's bloom has them on the viewer's left (the right is the same): the tall
# one beside the top, the shorter one at the very top, the ones fanning down her side, and the low one under her side
# lobe. How wide each is.
C = (12.0, 6.6)  # the middle of her face, where the petals spring from
# They reach a little higher than drawn, since from a little above her they look a little shorter.
PETALS = {"t": ((12.0, 0.55), 3.0), "tl": ((8.0, -0.4), 3.8), "ml": ((4.2, 1.4), 3.6), "sl": ((1.9, 4.2), 4.0),
          "ll": ((3.2, 7.1), 3.0)}
TILT, CUP = 0.22, 0.35
ROOM = 2  # pixels of room above the sprite's top for the petals  # how far back the petals lean, per pixel out; how far their edges come forward
ORDER = ["ll", "sl", "ml", "tl", "t", "tr", "mr", "sr", "lr"]  # left to right round her face


def petals() -> dict:
    """Every petal: (tip, width), the viewer's right mirrored from the left."""
    out = dict(PETALS)
    for name, ((x, y), w) in PETALS.items():
        if name != "t":
            out[name[:-1] + "r"] = ((mirror(x), y), w)
    return out


def base(tip: tuple) -> np.ndarray:
    return np.array(C) + 0.15 * (np.array(tip) - np.array(C))


def petal_shape(a: float) -> float:
    """A petal's half-width along it (0 at its base, 1 at its tip) as a share of its widest: blunt at the base (hidden
    behind her face), round at the tip."""
    if a >= 0.55:
        return math.sqrt(max(1 - ((a - 0.55) / 0.45) ** 2, 0.0))
    return 0.45 + 0.55 * math.sin(math.pi / 2 * a / 0.55)


def petal(name: str, tip: tuple, width: float) -> tuple[dict, tuple, tuple]:
    """A petal as a thin pillow from its base to its tip, leaning back from her face, its edges cupped forward. Pink,
    in shadow (purple) near her face's top corners and its base, as drawn; pink behind."""
    b = base(tip)
    d = (np.array(tip) - b) / np.linalg.norm(np.array(tip) - b)
    p = np.array((-d[1], d[0]))
    length = float(np.linalg.norm(np.array(tip) - b))
    lift = 0.15 * (ORDER.index(name) % 2)  # every other one a little forward, so they overlap in turn
    if name in ("ll", "lr"):
        lift += 0.9  # the low ones lie in front of her shoulders

    def along(x, y):
        q = np.array((x, y)) - b
        return float(q @ d) / length, float(q @ p)

    def inside(x, y):
        a, s = along(x, y)
        if not 0 <= a <= 1 or abs(s) > width / 2 * petal_shape(a):
            return None
        corner = min(((x - cx) / 1.0) ** 2 + ((y - 4.1) / 0.9) ** 2 for cx in (6.9, 17.1))
        return PLUM if a < 0.22 or corner <= 1 else PINK

    def mid(x, y):
        a, s = along(x, y)
        return 3.0 + lift - TILT * a * length + CUP * (s / (width / 2)) ** 2

    # Built on the sprite's grid moved down by ROOM, so the tips can reach above its top.
    mask, colour = cells(lambda x, y: inside(x, y - ROOM))
    verts, faces, colours = pillow(mask, colour, dict(depth=0.3, flat=0.5, back=PINK, behind=1.0,
                                                      mid=lambda x, y: mid(x, y - ROOM)))
    verts = [(x, y - ROOM, z) for x, y, z in verts]
    bone = (tuple(b) + (mid(*b),), tuple(tip) + (mid(*tip),))
    return dict(bone=f"petal_{name}", smooth=True, verts=verts, faces=faces, colours=colours), *bone


# -- her body ------------------------------------------------------------------------------------------------------

# Its half-width down from its top (hidden behind her face) to its bottom among her roots, as the sprite's outline has
# it: broad shoulders, tapering. How deep it is for its width: a little flattened.
BODY = [(7.7, 0.3), (8.0, 4.6), (8.5, 6.2), (9.0, 7.0), (9.5, 7.6), (10.0, 7.95), (10.8, 8.05), (11.5, 7.9),
        (12.5, 7.5), (13.5, 7.2), (14.5, 7.05), (15.5, 6.9), (16.5, 6.5), (17.3, 5.8), (17.8, 4.8), (18.3, 3.6),
        (18.8, 2.9), (19.3, 2.3), (19.7, 1.5), (20.0, 0.3)]
DEEP = 0.5
SPOTS = [(8.5, 10.5), (15.5, 10.5), (9.5, 13.5), (14.5, 13.5), (7.5, 16.5), (16.5, 16.5)]
SPOT = 0.72  # a little bigger than her single pixels, so they survive


def half_width(y: float) -> float:
    ys, ws = zip(*BODY)
    return float(np.interp(y, ys, ws))


def on_body(x: float, y: float) -> float:
    """How far forward her body's front is at (x, y)."""
    w = half_width(y)
    s = min(abs(x - 12) / w, 1.0)
    return DEEP * w * math.sqrt(1 - s * s)


def body(sides: int = 128) -> dict:
    rings = list(np.linspace(BODY[0][0], BODY[-1][0], 63))
    verts, faces, colours = [], [], []
    for y in rings:
        w = half_width(y)
        for k in range(sides):
            a = 2 * math.pi * k / sides
            verts.append((12 + w * math.sin(a), y, DEEP * w * math.cos(a)))
    for n in range(1, len(rings)):
        r0, r1 = (n - 1) * sides, n * sides
        y = (rings[n - 1] + rings[n]) / 2
        for k in range(sides):
            faces.append([r0 + k, r1 + k, r1 + (k + 1) % sides, r0 + (k + 1) % sides])
            a = 2 * math.pi * (k + 0.5) / sides
            x = 12 + half_width(y) * math.sin(a)
            spot = math.cos(a) > 0.3 and any(math.hypot(x - sx, y - sy) <= SPOT for sx, sy in SPOTS)
            colours.append(LIME if spot else GREEN)
    end = (len(rings) - 1) * sides
    faces += [list(range(sides)), list(range(end + sides - 1, end - 1, -1))]
    colours += [GREEN, GREEN]
    return dict(bone="body", smooth=False, recalc=True, verts=verts, faces=faces, colours=colours)


# -- her vines -----------------------------------------------------------------------------------------------------

# A vine on the viewer's left (the right is the same): out of her side in front of her body's edge, out to an elbow,
# then up and in to a tip beside her bloom. Its bones: upper arm to the elbow, forearm to halfway up, hand to the tip.
VINE = [(6.4, 12.4, 2.4), (3.6, 12.4, 2.2), (0.9, 11.6, 1.8), (1.1, 9.9, 1.7), (2.2, 8.6, 1.7), (3.5, 7.4, 1.8)]
VINE_RADII = [0.8, 0.62, 0.58, 0.55, 0.5, 0.42]
THORNS = [((2.6, 12.8, 2.0), (-0.5, 1.0, 0.0), "arm_l"), ((0.5, 11.2, 1.75), (-1.0, -0.3, 0.0), "forearm_l"),
          ((1.4, 9.0, 1.7), (-0.8, -0.6, 0.0), "forearm_l")]


def vine() -> dict:
    verts, faces, colours, weights = [], [], [], []
    add(tube(VINE, VINE_RADII, lambda s, a: GREEN,
             chain(["arm_l", "arm_l", "forearm_l", "forearm_l", "hand_l"]), steps=8, sides=12, tip=0.45),
        verts, faces, colours, weights)
    for at, out, bone in THORNS:
        out = np.array(out) / np.linalg.norm(out)
        start = np.array(at) - 0.2 * out
        add(tube([tuple(start), tuple(start + 0.45 * out)], [0.34, 0.2], lambda s, a: GREEN,
                 lambda u, bone=bone: {bone: 1.0}, steps=2, sides=8, tip=0.45),
            verts, faces, colours, weights)
    return dict(bone="arm_l", smooth=False, recalc=True, verts=verts, faces=faces, colours=colours, weights=weights)


# -- her roots -----------------------------------------------------------------------------------------------------

# Three a side, as drawn, from inside her body out and down to the floor: the outer one past the sprite's edge, the
# inner one to the corner of the frame, the middle one short, under her. Each on its own bone, held by her body where it
# leaves it, so she can sink and rise on them while they stay put.
ROOTS = {
    "o": ([(6.0, 15.0, 1.0), (3.6, 17.9, 0.7), (1.2, 20.4, 0.4), (-0.3, 22.25, 0.2)], [0.95, 0.85, 0.7, 0.55], 0.45),
    "i": ([(8.0, 17.0, 2.2), (5.8, 19.3, 1.8), (3.8, 21.3, 1.3), (2.9, 22.15, 1.0)], [0.85, 0.75, 0.62, 0.5], 0.4),
    "m": ([(11.2, 19.0, 1.5), (10.4, 20.5, 1.6), (9.8, 21.45, 1.6)], [0.6, 0.5, 0.42], 0.35),
}


def root(kind: str) -> dict:
    points, radii, tip = ROOTS[kind]
    bone = f"rt_{kind}_l"

    def weigh(u):
        t = min(u / 0.9, 1.0)
        return {bone: 1.0} if t >= 1 else {"body": 1 - t, bone: t} if t else {"body": 1.0}
    return dict(bone=bone, **tube(points, radii, lambda s, a: GREEN, weigh, steps=8, sides=12, tip=tip))


# -- leaves and shards ---------------------------------------------------------------------------------------------

# Bits thrown up and out from a point: leaves at either side when she lands, and shards where her vine cracks. Each
# lives on a bone at that point, which spreads them as it grows (0 hides them).
SPLASH_L = (1.0, 22.0, 0.8)
SPRAY_OUT = [(-2.2, -0.9), (-3.4, -2.8), (-1.2, -4.0), (0.6, -2.6), (-4.4, -1.0)]  # thrown off to the viewer's left
BURST = (30.5, 13.3, 1.8)  # where the tip of her vine cracks
SPRAY_BURST = [(1.2, -2.4), (1.8, 0.0), (1.0, 2.4), (-0.8, -2.8), (-0.6, 2.8), (1.6, -3.2)]


def splash(at: tuple, spray: list, bone: str) -> dict:
    verts, faces, colours, weights = [], [], [], []
    for dx, dy in spray:
        out = np.array((dx, dy, 0.0)) / math.hypot(dx, dy)
        centre = np.array(at) + (dx, dy, 0.0)
        add(tube([tuple(centre - 0.6 * out), tuple(centre), tuple(centre + 0.4 * out)], [0.4, 0.62, 0.48],
                 lambda s, a: LIME, lambda u: {bone: 1.0}, steps=3, sides=8, tip=0.5),
            verts, faces, colours, weights)
    return dict(bone=bone, smooth=False, recalc=True, verts=verts, faces=faces, colours=colours, weights=weights)


# -- the rig -------------------------------------------------------------------------------------------------------

def bones(mouth_z: float, petal_bones: dict) -> dict:
    def r(p):
        return (mirror(p[0]), *p[1:])
    out = {
        "root":      (None,        (12, GROUND, 0),   (12, 20, 0)),
        "body":      ("root",      (12, 19.8, 0),     (12, 9.0, 0)),
        "head":      ("body",      (12, 9.4, 2.0),    (12, 4.0, 2.0)),
        "mouth":     ("head",      (12, 9.0 - FACE_UP, mouth_z), (12, 7.2 - FACE_UP, mouth_z)),
    }
    for name in ORDER:
        out[f"petal_{name}"] = ("head", *petal_bones[name])
    for side, f in (("l", lambda p: p), ("r", r)):
        out[f"arm_{side}"] = ("body", f(VINE[0]), f(VINE[2]))
        out[f"forearm_{side}"] = (f"arm_{side}", f(VINE[2]), f(VINE[4]))
        out[f"hand_{side}"] = (f"forearm_{side}", f(VINE[4]), f(VINE[5]))
        for kind, (points, _, _) in ROOTS.items():
            out[f"rt_{kind}_{side}"] = ("root", f(points[0]), f(points[-1]))
        out[f"splash_{side}"] = ("root", f(SPLASH_L), f((SPLASH_L[0], SPLASH_L[1] - 2, SPLASH_L[2])))
    out["burst"] = ("root", BURST, (BURST[0], BURST[1] - 2, BURST[2]))
    return out


SWAP = {**{f"{b}_l": f"{b}_r" for b in ("arm", "forearm", "hand", "rt_o", "rt_i", "rt_m", "splash")}}


# -- the lot -------------------------------------------------------------------------------------------------------

def build() -> dict:
    grid = fine()
    mask = np.array([[bool(c) for c in row] for row in grid])
    colour = [[c[1] if c else None for c in row] for row in grid]
    verts, faces, colours = pillow(mask, colour, FACE)
    parts = {"face": dict(bone="head", smooth=True, verts=verts, faces=faces, colours=colours)}
    face = surface(mask, FACE)

    def eyes(x, y):  # squarish (round ones shrink to crosses at 84), a little bigger than her single pixels
        return OUTLINE if any(abs((x - ex) / 0.58) ** 4 + abs((y - 6.5) / 0.72) ** 4 <= 1 for ex in (9.5, 14.5)) else None

    def gape(x, y):  # her mouth, open as wide as it goes, up from her face's bottom edge: the bone squeezes it shut
        return OUTLINE if y <= 9.0 and ((x - 12) / 2.1) ** 2 + ((y - 9.0) / 1.8) ** 2 <= 1 else None

    mouth_z = face(12, 8.5) + 0.1
    parts["eyes"] = decal(eyes, face, 0.06, "head")
    parts["mouth"] = decal(gape, face, 0.1, "mouth")
    for name in ("face", "eyes", "mouth"):
        parts[name]["verts"] = [(x, y - FACE_UP, z) for x, y, z in parts[name]["verts"]]

    petal_bones = {}
    for name, (tip, width) in petals().items():
        parts[f"petal_{name}"], *petal_bones[name] = petal(name, tip, width)
    parts["body"] = body()
    parts["vine_l"] = vine()
    parts["vine_r"] = mirrored(parts["vine_l"], SWAP)
    for kind in ROOTS:
        parts[f"root_{kind}_l"] = root(kind)
        parts[f"root_{kind}_r"] = mirrored(parts[f"root_{kind}_l"], SWAP)
    parts["splash_l"] = splash(SPLASH_L, SPRAY_OUT, "splash_l")
    parts["splash_r"] = mirrored(parts["splash_l"], SWAP)
    parts["burst"] = splash(BURST, SPRAY_BURST, "burst")

    def hexed(c):
        return "#%02x%02x%02x" % c

    return {
        "sprite": "thornmother", "size": SIZE, "fine": K, "ground": GROUND, "centre": 12,
        "shades": {hexed(lit): hexed(dark) for lit, dark in SHADES.items()},
        "outline": hexed(OUTLINE),
        "heavier": {hexed(c): w for c, w in HEAVIER.items()},
        "bones": {name: {"parent": parent, "head": [float(c) for c in head], "tail": [float(c) for c in tail]}
                  for name, (parent, head, tail) in bones(mouth_z, petal_bones).items()},
        "parts": {name: {**part, "colours": [hexed(c) for c in part["colours"]],
                         "verts": [[round(float(c), 4) for c in v] for v in part["verts"]]}
                  for name, part in parts.items()},
    }


def main() -> None:
    data = build()
    OUT.mkdir(exist_ok=True)
    path = OUT / "thornmother_mesh.json"
    path.write_text(json.dumps(data, separators=(",", ":")))
    print(f"-> {path} ({path.stat().st_size // 1024} KB)")
    for name, part in data["parts"].items():
        print(f"  {name:11} {part['bone']:10} {len(part['verts']):6} verts {len(part['faces']):6} faces "
              f"{sorted(set(part['colours']))}")


if __name__ == "__main__":
    main()
