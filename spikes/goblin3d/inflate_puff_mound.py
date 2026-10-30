"""Spike: the Puff Mound made solid, smooth and fine for Blender, the way inflate_abbot.py made the Drowned Abbot.

Its sprite (a stand-in drawn in the game's palette, which the kids may draw again): a pale cream puffball with a white
highlight on its top, pocked with brown, two small dark eyes, and a few pale spores drifting over it. It's one of the
four that fight for the Humongous Fungus, so it's mostly seen small, and it's a smaller thing than the bosses: about
three quarters of their height. The model keeps all of that and fills in what the flat front view can't show:

- a round puffball turned on a lathe from the sprite's outline (a touch bigger than drawn, to stand its three
  quarters), pinched to a short base on the floor, its white cap painted on where the sprite has it;
- its eyes and pocks laid on its front, each where the sprite has it once seen from 12 degrees above (which takes
  things on its front down by their depth);
- a mouth that opens when it wheezes and puffs (shut, it's gone, as in its sprite);
- its spores, squarish, so they stay a pixel at the smallest size, each on a bone of its own;
- the lobes of the cloud it bursts out, each on a bone of its own too.

    uv run --no-sync --with numpy python spikes/goblin3d/inflate_puff_mound.py    # writes puff_mound/puff_mound_mesh.json

build_puff_mound.py, run inside Blender, rigs and animates it.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from inflate_king import K, SIZE, epx, pillow
from inflate_mouse import catmull, cells

HERE = Path(__file__).parent
OUT = HERE / "puff_mound"
SPRITE = HERE.parents[1] / "src" / "ptg" / "data" / "sprites" / "puff_mound.png"

OUTLINE = (24, 20, 37)
WHITE, CREAM = (255, 255, 255), (234, 212, 170)
BROWN, SLATE = (194, 133, 105), (58, 68, 102)

# Every colour it's painted in and the one its shadow side takes, all from its sprite: its white cap shades to the
# cream the rest of it was drawn in, as the sprite has it down the cap's far side. The cream, its pocks, its eyes and
# its mouth keep theirs.
SHADES = {WHITE: CREAM, CREAM: CREAM, BROWN: BROWN, SLATE: SLATE, OUTLINE: OUTLINE}
# What reduce.py counts heavier when it shrinks it, so the small things survive: its eyes, its mouth, its pocks.
HEAVIER = {SLATE: 2.5, OUTLINE: 2.0, BROWN: 2.5}
GROUND = 23  # the bottom of its base: the sprite's last row of it is 22
TAN = math.tan(math.radians(12))  # the camera looks down 12 degrees: a thing d pixels forward looks d * TAN lower
SCALE = 1.04  # the model's size for the sprite's, about the middle of its base
DEEP = 0.92  # how deep it is for how wide: a puffball, nearly round

# Its outline, as (half-width, height) from the top of its cap down to its base on the floor: round on top, widest a
# little below its middle, pinched to its base, as the sprite has it (smoothed, and SCALE bigger).
PROFILE = [(0.0, 6.0), (2.9, 6.35), (4.8, 7.1), (6.25, 8.2), (7.45, 9.5), (8.35, 10.9), (9.0, 12.4), (9.35, 14.0),
           (9.35, 15.6), (8.95, 17.2), (8.15, 18.7), (7.05, 20.0), (5.75, 21.1), (4.4, 21.95), (3.35, 22.55),
           (2.85, 23.0)]

# Its face and pocks, where they're seen in the picture (sprite pixels, SCALE bigger about the base), each put where
# it falls in the middle of a pixel at 40 and at 48 in both the frames the stage stands it in (its Idle's first and
# middle, a breath apart), so they hold still there rather than boil: its eyes a little closer than drawn, its pocks
# near where they're drawn but for the one beside its eye, which moves out to its side (so the two don't run together
# small), and the mouth under its eyes. Eyes and pocks are near-squares (a superellipse of power 8): rounder ones
# come out as little crosses at 84. The eyes' size, place and weight (HEAVIER) were found together, by trying them
# against the way reduce.py shrinks the frames: one pixel at 40 and 48, a 2x2 blob at 84, in both those frames.
EYES = [(10.25, 11.376), (13.8, 11.376)]
EYE = (0.47, 0.47)  # half-width and half-height
POCKS = [(8.71, 13.66), (16.2, 13.8), (17.23, 16.94), (11.48, 17.97)]
POCK = (0.47, 0.47)
MOUTH = (12.0, 14.4)
GAPE = (1.2, 0.9)  # the mouth open as wide as it goes: its bone squeezes it shut

SPORES, LOBES = 14, 6
# A spore's half-size across, up and deep: about 1.7 pixels across (9 of the 256-pixel render's), so it covers half a
# pixel or more at 40 wherever it is, yet can sit as one pixel at 40 and 48 both; and as tall in the picture once its
# top shows from 12 degrees above.
SPORE = (0.83, 0.78, 0.7)
LOBE = 1.0  # a cloud lobe's radius; its bone grows it
NEST = (12.0, 12.0, 0.0)  # where the spores and lobes are made: inside it, out of sight


# -- the sprite ----------------------------------------------------------------------------------------------------

def sprite() -> dict[tuple[int, int], tuple]:
    sheet = Image.open(SPRITE).convert("RGBA")
    return {(x, y): sheet.getpixel((x, y))[:3] for y in range(SIZE) for x in range(SIZE)
            if sheet.getpixel((x, y))[3] >= 128}


PIXELS = sprite()


def cap_grid() -> list[list]:
    """The sprite's white cap and its cream, scaled up the pixel-art way: "W", "C" or None in each fine cell. Its eyes
    and pocks take the colour round them; the spores (above row 6) aren't part of it. Cells just outside take their
    nearest neighbour's, so the model's edge, a little outside the sprite's, has a colour too."""
    def kind(x, y):
        rgb = PIXELS.get((x, y))
        if rgb is None or rgb == OUTLINE or y < 6:
            return None
        if rgb == WHITE:
            return "W"
        if rgb == CREAM:
            return "C"
        around = [kind(x + dx, y + dy) for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1))
                  if PIXELS.get((x + dx, y + dy)) in (WHITE, CREAM)]
        return max(set(around), key=around.count) if around else "C"

    grid = [[kind(x, y) for x in range(SIZE)] for y in range(SIZE)]
    for _ in range(int(math.log2(K))):
        grid = epx(grid)
    n = len(grid)
    for _ in range(3 * K):
        grown = [row[:] for row in grid]
        for j in range(n):
            for i in range(n):
                if grid[j][i] is None:
                    near = [grid[b][a] for a, b in ((i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1))
                            if 0 <= a < n and 0 <= b < n and grid[b][a]]
                    if near:
                        grown[j][i] = max(set(near), key=near.count)
        grid = grown
    return grid


CAP = cap_grid()


def cap(x: float, y: float) -> tuple:
    """The colour the sprite has at picture point (x, y) of the model."""
    xs, ys = 12 + (x - 12) / SCALE, GROUND - (GROUND - y) / SCALE
    i = min(max(int(xs * K), 0), SIZE * K - 1)
    j = min(max(int(ys * K), 0), SIZE * K - 1)
    return WHITE if CAP[j][i] == "W" else CREAM


# -- the puffball --------------------------------------------------------------------------------------------------

def rings(count: int = 76) -> list[tuple[float, float]]:
    """(half-width, height) at `count` points evenly round its outline, from the top of its cap to its base."""
    path = np.array([p for _, p in catmull(PROFILE, 32)])
    along = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))])
    at = np.linspace(0.0, along[-1], count)
    return list(zip(np.interp(at, along, path[:, 0]), np.interp(at, along, path[:, 1])))


RINGS = rings()
_RS, _YS = np.array([r for r, _ in RINGS]), np.array([y for _, y in RINGS])


def radius(y: float) -> float:
    return float(np.interp(y, _YS, _RS, left=0.0, right=0.0))


def front(x: float, y: float) -> float:
    """How far forward its front is at (x, y), as made."""
    r = radius(y)
    return DEEP * math.sqrt(max(r * r - (x - 12) ** 2, 0.0))


def weigh(y: float) -> dict:
    """Which bones a point at height y follows: its base stays on the floor (root), its middle squashes and swells
    (body), its cap rides on that and wobbles on its own (top), shared where they meet so it bends smoothly."""
    def smooth(t):
        return t * t * (3 - 2 * t)
    if y >= 22.4:
        return {"root": 1.0}
    if y >= 21.2:
        t = smooth((y - 21.2) / 1.2)
        return {"root": t, "body": 1 - t} if t > 0 else {"body": 1.0}
    if y >= 17.5:
        return {"body": 1.0}
    if y >= 13.5:
        t = smooth((17.5 - y) / 4.0)
        return {"top": t, "body": 1 - t} if t > 0 else {"body": 1.0}
    return {"top": 1.0}


def puffball(sides: int = 112) -> dict:
    """The lathe: a point on top, a ring at each height round its outline, a flat base. Each face painted as the sprite
    has the place it's seen at (its back as its front)."""
    verts, faces, colours, weights = [], [], [], []
    verts.append((12.0, RINGS[0][1], 0.0))
    weights.append(weigh(RINGS[0][1]))
    starts = []
    for r, y in RINGS[1:]:
        starts.append(len(verts))
        for k in range(sides):
            a = 2 * math.pi * k / sides
            verts.append((12 + r * math.sin(a), y, DEEP * r * math.cos(a)))
            weights.append(weigh(y))
    base = len(verts)
    verts.append((12.0, RINGS[-1][1], 0.0))
    weights.append(weigh(RINGS[-1][1]))

    def paint(face):
        x, y, z = np.mean([verts[i] for i in face], axis=0)
        return cap(x, y + abs(z) * TAN)

    for k in range(sides):
        face = [0, starts[0] + (k + 1) % sides, starts[0] + k]
        faces.append(face)
        colours.append(paint(face))
    for r0, r1 in zip(starts, starts[1:]):
        for k in range(sides):
            face = [r0 + k, r0 + (k + 1) % sides, r1 + (k + 1) % sides, r1 + k]
            faces.append(face)
            colours.append(paint(face))
    last = starts[-1]
    for k in range(sides):
        faces.append([base, last + k, last + (k + 1) % sides])
        colours.append(CREAM)
    return dict(bone="body", smooth=False, recalc=True, verts=verts, faces=faces, colours=colours, weights=weights)


# -- what's on its front -------------------------------------------------------------------------------------------

def made_at(x: float, seen: float) -> float:
    """The height on its front that's seen at height `seen` in the picture, at x."""
    y = seen
    for _ in range(20):
        y = seen - front(x, y) * TAN
    return y


def squarish(cx: float, cy: float, hw: float, hh: float, colour: tuple, power: float = 8):
    """A superellipse drawn on the picture: a near-square, so it stays a blob big and a dot small."""
    def shape(x, y):
        return colour if abs((x - cx) / hw) ** power + abs((y - cy) / hh) ** power <= 1 else None
    return shape


def oval(cx: float, cy: float, hw: float, hh: float, colour: tuple):
    def shape(x, y):
        return colour if ((x - cx) / hw) ** 2 + ((y - cy) / hh) ** 2 <= 1 else None
    return shape


def decal(shapes: list, lift: float, bone: str | None = None, smooth: bool = True) -> dict:
    """Shapes drawn on the picture, laid on its front `lift` pixels proud of it: each fine cell of its front painted as
    the picture has the place it's seen at. On one bone, or (none given) following its front's bones. Smoothed (its
    fine steps rounded off in Blender) unless it's a near-square whose edges are placed to the pixel."""
    def inside(x, y):
        z = front(x, y)
        if z <= 0.5:
            return None
        seen = y + z * TAN
        for shape in shapes:
            c = shape(x, seen)
            if c:
                return c
        return None

    mask, colour = cells(inside)
    verts, faces, colours = pillow(mask, colour, dict(depth=0.05, flat=0.4, back=None,
                                                      mid=lambda x, y: front(x, y) + lift))
    part = dict(bone=bone or "body", smooth=smooth, verts=verts, faces=faces, colours=colours)
    if bone is None:
        part["weights"] = [weigh(v[1]) for v in verts]
    return part


def on_front(x: float, seen: float, lift: float) -> tuple[float, float, float]:
    y = made_at(x, seen)
    return (x, y, front(x, y) + lift)


# -- spores and the cloud --------------------------------------------------------------------------------------------

def ball(centre: tuple, half: tuple, power: float, colour: tuple, bone: str, rows: int, around: int) -> dict:
    """A ball (power 2) or a rounded cube (power 4 or more) of half-size `half` (across, up, deep) at `centre`, on its
    bone."""
    cx, cy, cz = centre

    def point(lat, lon):
        d = np.array((math.sin(lat) * math.sin(lon), -math.cos(lat), math.sin(lat) * math.cos(lon)))
        d /= np.sum(np.abs(d) ** power) ** (1 / power)
        return (cx + half[0] * d[0], cy + half[1] * d[1], cz + half[2] * d[2])

    verts = [point(0.0, 0.0)]
    for i in range(1, rows):
        for j in range(around):
            verts.append(point(math.pi * i / rows, 2 * math.pi * j / around))
    verts.append(point(math.pi, 0.0))
    bottom = len(verts) - 1
    faces = [[0, 1 + (j + 1) % around, 1 + j] for j in range(around)]
    for i in range(rows - 2):
        r0, r1 = 1 + i * around, 1 + (i + 1) * around
        faces += [[r0 + j, r0 + (j + 1) % around, r1 + (j + 1) % around, r1 + j] for j in range(around)]
    last = 1 + (rows - 2) * around
    faces += [[bottom, last + j, last + (j + 1) % around] for j in range(around)]
    return dict(bone=bone, smooth=False, recalc=True, verts=verts, faces=faces, colours=[colour] * len(faces))


def spore(n: int) -> dict:
    """A spore: cream, as drawn, and every third one white, to glitter."""
    return ball(NEST, SPORE, 6.0, WHITE if n % 3 == 0 else CREAM, f"spore_{n}", 8, 12)


def lobe(n: int) -> dict:
    return ball(NEST, (LOBE, LOBE, LOBE), 2.0, WHITE, f"lobe_{n}", 10, 16)


# -- the rig -------------------------------------------------------------------------------------------------------

def bones(eyes: list, mouth: tuple) -> dict:
    """(x right, y down, z toward the viewer, in sprite pixels): parent, pivot, and where they point. Its base hangs
    off the root, its middle off a pivot a pixel up, its cap off its widest; its eyes and mouth ride its cap. Spores
    and lobes are free of it all."""
    up = lambda p: (p[0], p[1] - 1.0, p[2])  # noqa: E731
    out = {
        "root": (None, (12, GROUND, 0), (12, GROUND - 3, 0)),
        "body": ("root", (12, GROUND - 1, 0), (12, 15.0, 0)),
        "top": ("body", (12, 15.0, 0), (12, 6.0, 0)),
        "eye_l": ("top", eyes[0], up(eyes[0])),
        "eye_r": ("top", eyes[1], up(eyes[1])),
        "mouth": ("top", mouth, up(mouth)),
    }
    for n in range(1, SPORES + 1):
        out[f"spore_{n}"] = (None, NEST, up(NEST))
    for n in range(1, LOBES + 1):
        out[f"lobe_{n}"] = (None, NEST, up(NEST))
    return out


# -- the lot -------------------------------------------------------------------------------------------------------

def build() -> dict:
    parts = {"puffball": puffball()}
    eyes = []
    for side, (x, seen) in zip("lr", EYES):
        parts[f"eye_{side}"] = decal([squarish(x, seen, *EYE, SLATE)], 0.07, f"eye_{side}", smooth=False)
        eyes.append(on_front(x, seen, 0.07))
    parts["pocks"] = decal([squarish(x, y, *POCK, BROWN) for x, y in POCKS], 0.06, smooth=False)
    parts["mouth"] = decal([oval(*MOUTH, *GAPE, OUTLINE)], 0.09, "mouth")
    mouth = on_front(*MOUTH, 0.09)
    for n in range(1, SPORES + 1):
        parts[f"spore_{n}"] = spore(n)
    for n in range(1, LOBES + 1):
        parts[f"lobe_{n}"] = lobe(n)

    def hexed(c):
        return "#%02x%02x%02x" % c

    return {
        "sprite": "puff_mound", "size": SIZE, "fine": K, "ground": GROUND, "centre": 12,
        "shades": {hexed(lit): hexed(dark) for lit, dark in SHADES.items()},
        "outline": hexed(OUTLINE),
        "heavier": {hexed(c): w for c, w in HEAVIER.items()},
        "nest": list(NEST),
        "bones": {name: {"parent": parent, "head": [round(float(c), 4) for c in head],
                         "tail": [round(float(c), 4) for c in tail]}
                  for name, (parent, head, tail) in bones(eyes, mouth).items()},
        "parts": {name: {**part, "colours": [hexed(c) for c in part["colours"]],
                         "verts": [[round(float(c), 4) for c in v] for v in part["verts"]]}
                  for name, part in parts.items()},
    }


def main() -> None:
    data = build()
    OUT.mkdir(exist_ok=True)
    path = OUT / "puff_mound_mesh.json"
    path.write_text(json.dumps(data, separators=(",", ":")))
    print(f"-> {path} ({path.stat().st_size // 1024} KB)")
    for name, part in data["parts"].items():
        print(f"  {name:9} {part['bone']:8} {len(part['verts']):6} verts {len(part['faces']):6} faces "
              f"{sorted(set(part['colours']))}")


if __name__ == "__main__":
    main()
