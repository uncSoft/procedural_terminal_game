"""Spike: the Sporefang Matriarch made solid, smooth and fine for Blender, the way inflate_thornmother.py made the
Thornmother.

JT drew her as a huge purple spider: a great dome of a back, pink where the light catches it and striped with two
glowing green chevrons, a band of shadow under it; below that her face, eight yellow eyes slanting down to two purple
jaws with pale curved fangs, a drop of green venom at each tip; four legs a side, pink above their green knees and
purple below, three a side planted and the back pair raised beside her dome; red toadstools (and one green) growing
from her shoulder, her back and her legs. Her other frames bob her down a pixel, bend a raised leg, lengthen the venom
and light her middle eyes white. The model keeps all of that and fills in what the flat front view can't show:

- her back as a dome that swells toward you and away behind her, and her face in front of it and below;
- her chevrons painted on as thin as she drew them (scaled up the pixel-art way, they swelled into a green mass);
- eight eyes as squarish dots (round ones shrink to crosses), four a side, slanting down as she drew them, the
  middle pair able to flash white;
- jaws that spread and snap, each with a curved fang and a drop of venom that swells, stretches and falls;
- legs as round tubes on three bones each (femur, tibia, tarsus), which build_matriarch.py plants with IK; as thin
  as she drew them, so the outline still runs between them, and set where they fall on every other pixel at 40;
- toadstools with round caps turned to face you, a white spot on each, on stems, on bones of their own;
- the silk line she drops in on, spores shaken loose when she lands, and venom sprayed when she bites.

She's drawn a few rows shorter than the King's sprite, so the model is built 12% bigger than drawn (SCALE), to stand
as tall as the other bosses in the same frame; thin parts (legs, fangs, stems, her line) keep their own widths.

    uv run --no-sync --with numpy python spikes/goblin3d/inflate_matriarch.py          # sporefang_matriarch/matriarch_mesh.json
    uv run --no-sync --with numpy python spikes/goblin3d/inflate_matriarch.py check    # every frame looked over
    uv run --no-sync --with numpy python spikes/goblin3d/inflate_matriarch.py sheet    # sporefang_matriarch/sheet.png

build_matriarch.py, run inside Blender, rigs and animates her.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from inflate_abbot import add
from inflate_king import K, SIZE, epx, pillow
from inflate_mouse import catmull, cells, decal, surface
from inflate_serpentis import chain, mirror, mirrored, tube

HERE = Path(__file__).parent
OUT = HERE / "sporefang_matriarch"
SPRITE = HERE.parents[1] / "src" / "ptg" / "data" / "sprites" / "the_sporefang_matriarch.png"

OUTLINE = (24, 20, 37)
PURPLE, PINK, DARK = (104, 56, 108), (181, 80, 136), (62, 39, 49)
GREEN, MOSS, FOREST = (99, 199, 77), (62, 137, 72), (38, 92, 66)
RED, CRIMSON, SALMON = (228, 59, 68), (162, 38, 51), (246, 117, 122)
WHITE, PALE = (255, 255, 255), (192, 203, 220)
CREAM, TAN = (234, 212, 170), (228, 166, 114)
YELLOW, ORANGE = (254, 231, 97), (254, 174, 52)

# Every colour she's painted in and the one its shadow side takes, all from her sprite: purple to the dark she drew
# under her dome, pink to purple, the red caps to the darker red down their right sides, the salmon cap to red, the
# green cap to its forest green, white to the pale of her fangs, the cream stems to tan. Her markings, her eyes and her
# venom glow, so they keep theirs.
SHADES = {
    PURPLE: DARK, PINK: PURPLE, DARK: DARK, GREEN: GREEN, MOSS: FOREST, FOREST: FOREST, RED: CRIMSON,
    CRIMSON: CRIMSON, SALMON: RED, WHITE: PALE, PALE: PALE, CREAM: TAN, TAN: TAN, YELLOW: YELLOW, ORANGE: ORANGE,
    OUTLINE: OUTLINE,
}
# What reduce.py counts heavier when it shrinks her, so the small things survive: her eyes most, her fangs and their
# white tips, the spots on her caps; her green (markings, knees, venom) a little.
HEAVIER = {YELLOW: 3.0, ORANGE: 3.0, WHITE: 1.8, PALE: 1.5, GREEN: 1.15, RED: 1.2}
GROUND = 22
SCALE = 1.12  # built this much bigger than drawn, about the middle of the floor under her
TAN12 = math.tan(math.radians(12))  # the camera looks down 12 degrees


def seen(x: float, y: float, z: float) -> tuple:
    """A point drawn at (x, y) on the sprite, at depth z: from 12 degrees up a point toward the viewer looks lower
    (one away looks higher), so it's raised (or lowered) by as much, to be seen where it was drawn."""
    return (x, y - z * TAN12, z)


def drawn_x(x: float) -> float:
    """Where to draw something so that, once she's scaled up, it stands at x."""
    return 12 + (x - 12) / SCALE


def scaled(p) -> tuple:
    return (12 + (p[0] - 12) * SCALE, GROUND + (p[1] - GROUND) * SCALE, p[2] * SCALE)


# -- the sprite ----------------------------------------------------------------------------------------------------

def sprite() -> dict[tuple[int, int], tuple]:
    sheet = Image.open(SPRITE).convert("RGBA")
    return {(x, y): sheet.getpixel((x, y))[:3] for y in range(SIZE) for x in range(SIZE)
            if sheet.getpixel((x, y))[3] >= 128}


PIXELS = sprite()
# Her dome, row by row (first and last column), down to the band of shadow under it; and a row more, hidden behind her
# face, so no gap opens between them as she moves.
DOME = {2: (9, 14), 3: (8, 14), 4: (7, 15), 5: (7, 16), 6: (7, 16), 7: (6, 17), 8: (7, 16), 9: (8, 15), 10: (8, 15)}
FACE = {10: (7, 16), 11: (8, 15), 12: (7, 16), 13: (8, 15), 14: (8, 15)}
# Her chevrons, through the middles of the pixels she drew them with.
CHEVRONS = [[(9.5, 3.5), (10.5, 4.5), (11.5, 5.5), (12.5, 5.5), (13.5, 4.5), (14.5, 3.5)],
            [(9.5, 6.5), (10.5, 7.5), (11.5, 8.5), (12.5, 8.5), (13.5, 7.5), (14.5, 6.5)]]
CHEVRON = 0.44  # half their width: one pixel across, once she's scaled up
assert all(PIXELS[(int(x), int(y))] == GREEN for line in CHEVRONS for x, y in line), "her chevrons aren't as drawn"
assert all(PIXELS[(x, 9)] == DARK for x in range(8, 16)), "her dome isn't where it was drawn"
assert PIXELS[(9, 11)] == YELLOW and PIXELS[(10, 13)] == ORANGE, "her eyes aren't where they were drawn"


def drawn(rows: dict, colour) -> list[list]:
    """Some rows of the sprite, recoloured by colour(x, y, drawn), scaled up the pixel-art way."""
    grid = [[None] * SIZE for _ in range(SIZE)]
    for y, (first, last) in rows.items():
        for x in range(first, last + 1):
            grid[y][x] = colour(x, y, PIXELS.get((x, y)))
    for _ in range(int(math.log2(K))):
        grid = epx(grid)
    return grid


def dome_colour(x: int, y: int, rgb: tuple) -> tuple:
    if y == 10:
        return DARK  # hidden behind her face
    return rgb if rgb in (PURPLE, PINK, DARK) else PURPLE  # chevrons painted on after; the little toadstool built on


def face_colour(x: int, y: int, rgb: tuple) -> tuple:
    return rgb if rgb in (PURPLE, PINK, DARK) else PURPLE  # her eyes are laid on it, below


def segment_distance(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    t = float(np.clip((p - a) @ (b - a) / ((b - a) @ (b - a)), 0, 1))
    return float(np.linalg.norm(p - a - t * (b - a)))


def chevrons(grid: list[list]) -> None:
    """Her chevrons painted onto her dome's fine pixels, as thin as she drew them."""
    lines = [[np.array(p) for p in line] for line in CHEVRONS]
    for j, row in enumerate(grid):
        for i, c in enumerate(row):
            if c is None:
                continue
            p = np.array(((i + 0.5) / K, (j + 0.5) / K))
            if any(segment_distance(p, a, b) <= CHEVRON for line in lines for a, b in zip(line, line[1:])):
                row[i] = GREEN


# Her dome swells toward you from a middle well behind her face, and as far again behind; her face is a lower, flatter
# swelling in front of it (flat and tipped up a little, so most of it faces you and stays lit, down to her jaws). From
# a little above, her dome's top shows over its front edge, so it's lowered a little, and her face (well forward) looks
# lower than drawn, so it's raised.
DOME_SPEC = dict(depth=4.4, flat=1.0, back=PINK, behind=1.25, mid=lambda x, y: -3.2)
FACE_SPEC = dict(depth=1.7, flat=0.6, back=PURPLE, behind=1.2, mid=lambda x, y: 1.6 + 0.3 * (y - 12))
DOME_DOWN, FACE_UP = 0.35, 0.5

# Her eight eyes, four a side, slanting down toward her jaws as she drew them (the outer top one added): where, how big
# (half-width, half-height: squarish, so they stay dots small and blobs big), and their colour.
EYES = [((8.6, 10.55), (0.37, 0.39), YELLOW), ((9.55, 11.5), (0.44, 0.46), YELLOW),
        ((10.55, 12.5), (0.48, 0.5), YELLOW), ((10.6, 13.55), (0.4, 0.38), ORANGE)]
GLINT = 2  # the eye she lit white in her other frames


def squarish(x: float, y: float, centre: tuple, half: tuple) -> bool:
    return abs((x - centre[0]) / half[0]) ** 4 + abs((y - centre[1]) / half[1]) ** 4 <= 1


# -- jaws, fangs and venom -----------------------------------------------------------------------------------------

JAW = (10.0, 15.35)  # the middle of the jaw on the viewer's left, as drawn (row 15, columns 9 and 10)
JAW_Z = 2.7
FANG = [(9.75, 15.5, 3.0), (9.45, 16.5, 3.2), (9.55, 17.55, 3.3), (10.15, 18.3, 3.3), (10.75, 18.65, 3.2)]
FANG_RADII = [0.62, 0.6, 0.56, 0.5, 0.44]
DRIP = [(10.8, 18.95, 3.2), (10.8, 19.45, 3.2), (10.8, 20.0, 3.2)]  # the venom under its tip, as drawn (row 19)


def jaw() -> dict:
    """The purple jaw (chelicera) the fang hangs from, a low swelling of its own."""
    centre, half = JAW, (1.05, 0.8)
    mask, colour = cells(lambda x, y: PURPLE if ((x - centre[0]) / half[0]) ** 2 + ((y - centre[1]) / half[1]) ** 2
                         <= 1 else None)
    verts, faces, colours = pillow(mask, colour, dict(depth=0.6, flat=0.6, back=PURPLE, behind=1.2,
                                                      mid=lambda x, y: JAW_Z + 0.4 * (y - centre[1])))
    verts = [seen(x, y, JAW_Z + 0.4)[:2] + (z,) for x, y, z in verts]
    return dict(bone="fang_l", smooth=True, verts=verts, faces=faces, colours=colours,
                weights=[{"fang_l": 1.0}] * len(verts))


def fang() -> dict:
    """Pale, curving in to a white tip, thick enough to survive shrinking."""
    points = [seen(*p) for p in FANG]
    path = catmull(points, 8)
    length = sum(float(np.linalg.norm(q[1] - p[1])) for p, q in zip(path, path[1:]))
    return dict(bone="fang_l", **tube(points, [r / SCALE for r in FANG_RADII],
                                      lambda s, a: WHITE if s > length - 0.95 else PALE,
                                      lambda u: {"fang_l": 1.0}, steps=8, sides=10, tip=0.3))


def drip() -> dict:
    """A drop of venom hanging from the fang's tip: blunt, round at the bottom."""
    return dict(bone="drip_l", **tube([seen(*p) for p in DRIP], [0.32, 0.56, 0.47], lambda s, a: GREEN,
                                      lambda u: {"drip_l": 1.0}, steps=6, sides=10, tip=0.25))


# -- legs ------------------------------------------------------------------------------------------------------------

# Her legs on the viewer's left (the right mirror them), through these points (x, y as drawn, depth): from the hip
# inside her body out to a knee, down to a lower joint and on to the foot. Which point is the knee and which the lower
# joint. 1 is the back pair, raised beside her dome, its tip in the air, its knee and joint well back (so it's seen as
# short as she drew it but can reach higher when she raises it); 2 the outer, 3 the middle, 4 the front pair, its
# knee well forward (so it's long enough to strike with). Where she drew each planted leg straight down (the tibia
# below its knee, the tarsus to the floor, a pixel further out) they're set, a little wider than drawn, where once
# scaled they fall on every other pixel at 40 and on single pixels at 48 and 64.
TIBIA = {2: drawn_x(1.72), 3: drawn_x(4.32), 4: drawn_x(6.52)}
TARSUS = {2: drawn_x(0.6), 3: drawn_x(3.2), 4: drawn_x(5.4)}
LEGS = {
    1: ([(7.9, 8.4, -1.6), (6.4, 6.9, -3.2), (4.6, 5.5, -4.6), (3.8, 4.0, -4.9), (3.6, 3.2, -5.0),
         (3.5, 2.0, -3.4)], 2, 4),
    2: ([(8.8, 10.8, 0.2), (6.4, 9.5, 0.3), (3.9, 9.5, 0.5), (TIBIA[2], 11.2, 0.6), (TIBIA[2], 14.4, 0.7),
         (TARSUS[2] + 0.2, 16.2, 0.8), (TARSUS[2], 17.6, 0.8), (TARSUS[2], 19.8, 0.8), (TARSUS[2], 22.0, 0.8)], 2, 6),
    3: ([(9.0, 12.6, 0.8), (7.0, 12.3, 1.1), (5.45, 12.5, 1.4), (TIBIA[3], 14.5, 1.4), (TARSUS[3] + 0.3, 16.5, 1.1),
         (TARSUS[3], 19.0, 0.9), (TARSUS[3], 22.0, 0.8)], 2, 4),
    4: ([(9.4, 14.2, 1.4), (TIBIA[4] + 0.1, 15.5, 4.0), (TIBIA[4], 16.9, 3.4), (TARSUS[4] + 0.3, 18.5, 2.4),
         (TARSUS[4], 20.3, 0.9), (TARSUS[4], 22.0, 0.8)], 1, 3),
}
LEG_RADIUS = 0.6  # once scaled: 1.2 pixels across, so one pixel at 48 and never less than one at 40
PLANTED = (2, 3, 4)


def leg_points(n: int) -> list[tuple]:
    """Leg n's points, each placed to be seen where it was drawn, but a planted foot on the floor."""
    points = LEGS[n][0]
    return [p if n in PLANTED and i == len(points) - 1 else seen(*p) for i, p in enumerate(points)]


def along(points: list, steps: int) -> list[float]:
    """How far along a tube through the points (as tube() measures it) each point is, in pixels."""
    path = catmull(points, steps)
    out, s = [0.0], 0.0
    for (u0, p0), (u1, p1) in zip(path, path[1:]):
        s += float(np.linalg.norm(p1 - p0))
        if int(u1) != int(u0) and u1 == int(u1):
            out.append(s)
    return out


def leg(n: int) -> dict:
    """Leg n on the viewer's left: pink to its lower joint, green at the knee and the joint, purple below."""
    points = leg_points(n)
    _, knee, joint = LEGS[n]
    bones = [f"{'femur' if i < knee else 'tibia' if i < joint else 'tarsus'}_{n}l" for i in range(len(points) - 1)]
    at = along(points, 8)
    s_knee, s_joint = at[knee], at[joint]

    def paint(s, a):
        if abs(s - s_knee) < 0.55 or (n in PLANTED and abs(s - s_joint) < 0.45):
            return GREEN
        return PINK if s < s_joint or n not in PLANTED else PURPLE
    radius = LEG_RADIUS / SCALE
    radii = [radius + 0.06] + [radius] * (len(points) - 1)
    return dict(bone=f"femur_{n}l", **tube(points, radii, paint, chain(bones, blend=0.25), steps=8, sides=10,
                                           tip=0.0 if n in PLANTED else 0.3))


def pole(n: int) -> tuple:
    """Where leg n's knee bends toward: out past it, away from the line from hip to foot."""
    points = leg_points(n)
    _, knee, _ = LEGS[n]
    hip, k, foot = (np.array(points[i]) for i in (0, knee, -1))
    out = k - (hip + foot) / 2
    return tuple(k + 4.0 * out / np.linalg.norm(out))


# -- toadstools ------------------------------------------------------------------------------------------------------

# Each toadstool: its stem's points (x, y as drawn, depth: from inside what it grows on, out), where its cap sits, the
# cap's radius, colour and white spot (as a share of its radius), what it grows on and its stem's colour. As drawn: on
# her raised leg (the salmon one, its stem tan), on her dome's right shoulder, a little one low on her dome, and one on
# each outer leg (the right red, the left green), their stems showing under or beside their caps. Those on her dome
# take their depth from it (None): rooted in it, the cap just proud of it.
TOADSTOOLS = {
    1: ([(3.75, 4.9, -2.7), (2.7, 5.1, -2.4), (1.8, 5.0, -2.1)], (1.15, 4.25, -1.9), 1.3, SALMON, 0.4, "tibia_1l",
        TAN),
    2: ([(15.2, 5.1, None), (16.0, 4.4, None)], (16.6, 3.1, None), 1.3, RED, 0.4, "abdomen", CREAM),
    3: ([(8.6, 9.0, None), (8.75, 8.2, None)], (9.0, 7.45, None), 1.0, RED, 0.0, "abdomen", CREAM),
    4: ([(TIBIA[2] + 0.3, 11.9, 0.6), (21.9, 11.7, 0.8), (22.6, 11.1, 1.0)], (23.0, 10.15, 1.2), 1.3, RED, 0.4,
        "tibia_2r", CREAM),
    5: ([(TIBIA[2] + 0.3, 13.7, 0.7), (1.9, 13.6, 0.9), (1.2, 13.0, 1.0)], (0.95, 12.1, 1.2), 1.3, MOSS, 0.4,
        "tibia_2l", CREAM),
}
TOADSTOOLS[4] = ([(mirror(TIBIA[2] + 0.3), 11.9, 0.6), *TOADSTOOLS[4][0][1:]], *TOADSTOOLS[4][1:])
ROOTED, PROUD = -0.7, 0.7  # how far behind her dome's surface a stem starts, and in front of it a cap sits
STEM = 0.5  # its radius, once scaled


def placed(number: int, dome) -> tuple[list, tuple]:
    """A toadstool's stem points and cap, placed to be seen where drawn, those on her dome on its surface."""
    stem, cap = TOADSTOOLS[number][:2]
    if cap[2] is None:
        stem = [(x, y, dome(x, y) + ROOTED + (PROUD - ROOTED) * i / len(stem)) for i, (x, y, _) in enumerate(stem)]
        cap = (cap[0], cap[1], dome(*stem[0][:2]) + PROUD)
        return [seen(x, y + DOME_DOWN, z) for x, y, z in stem], seen(cap[0], cap[1] + DOME_DOWN, cap[2])
    return [seen(*p) for p in stem], seen(*cap)


def frame(axis: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    u = np.cross(axis, (0.0, 1.0, 0.0))
    if np.linalg.norm(u) < 1e-6:
        u = np.cross(axis, (1.0, 0.0, 0.0))
    u /= np.linalg.norm(u)
    return u, np.cross(axis, u)


def toadstool(number: int, dome) -> dict:
    """A stem, and a round cap on it turned mostly toward the viewer (as she drew them: a round cap with its white spot
    in the middle), the rest of the way along the stem; cream under the cap. On a bone of its own."""
    _, _, radius, colour, spot, _, stalk = TOADSTOOLS[number]
    stem, cap = placed(number, dome)
    bone = f"ts_{number}"
    cap = np.array(cap)
    grow = cap[:2] - np.array(stem[0][:2])
    grow = np.array((*(grow / np.linalg.norm(grow)), 0.0))
    axis = 0.4 * grow + 0.92 * np.array((0.0, 0.0, 1.0))
    axis /= np.linalg.norm(axis)
    u, v = frame(axis)
    verts, faces, colours, weights = [], [], [], []
    add(tube(stem + [tuple(cap - 0.2 * axis)], [STEM / SCALE] * (len(stem) + 1), lambda s, a: stalk,
             lambda w: {bone: 1.0}, steps=4, sides=8), verts, faces, colours, weights)
    height, rings, sides = 0.72 * radius, 8, 16
    base = cap - 0.25 * radius * axis
    start = len(verts)
    verts.append(tuple(base + height * axis))  # its top
    for r in range(1, rings + 1):
        theta = (math.pi / 2) * r / rings
        for k in range(sides):
            phi = 2 * math.pi * k / sides
            verts.append(tuple(base + height * math.cos(theta) * axis
                               + radius * math.sin(theta) * (math.cos(phi) * u + math.sin(phi) * v)))
    verts.append(tuple(base - 0.12 * radius * axis))  # the middle of its underside
    weights += [{bone: 1.0}] * (len(verts) - start)

    def ring(r, k):
        return start + 1 + (r - 1) * sides + k % sides

    for k in range(sides):
        faces.append([start, ring(1, k), ring(1, k + 1)])
        colours.append(WHITE if spot else colour)
    for r in range(1, rings):
        theta = (math.pi / 2) * (r + 0.5) / rings
        for k in range(sides):
            faces.append([ring(r, k), ring(r + 1, k), ring(r + 1, k + 1), ring(r, k + 1)])
            colours.append(WHITE if math.sin(theta) < spot else colour)
    under = len(verts) - 1
    for k in range(sides):
        faces.append([ring(rings, k), under, ring(rings, k + 1)])
        colours.append(CREAM)
    return dict(bone=bone, smooth=False, recalc=True, verts=verts, faces=faces, colours=colours, weights=weights)


# -- silk, spores and venom ----------------------------------------------------------------------------------------

SILK_X, SILK_Z = drawn_x(12.6), -4.6  # a little off her middle, so at 40 it never falls between two pixels
SILK_TOP, SILK_END = -48.0, 3.4


def silk() -> dict:
    points = [(SILK_X, SILK_TOP, SILK_Z), (SILK_X, -20.0, SILK_Z), (SILK_X, SILK_END, SILK_Z)]
    return dict(bone="silk", **tube(points, [0.55 / SCALE] * 3, lambda s, a: WHITE, lambda u: {"silk": 1.0},
                                    steps=4, sides=8))


def bits(at: tuple, spray: list, colour: tuple, bone: str, size: float = 0.5) -> dict:
    """Little round bits thrown out from a point: spores, drops of venom. They live on a bone at that point, which
    spreads them as it grows (0 hides them)."""
    verts, faces, colours, weights = [], [], [], []
    for dx, dy in spray:
        out = np.array((dx, dy, 0.0)) / math.hypot(dx, dy)
        centre = np.array(at) + (dx, dy, 0.0)
        add(tube([tuple(centre - 0.4 * out), tuple(centre), tuple(centre + 0.3 * out)],
                 [0.7 * size, size, 0.8 * size], lambda s, a: colour, lambda u: {bone: 1.0}, steps=3, sides=8,
                 tip=0.4 * size), verts, faces, colours, weights)
    return dict(bone=bone, smooth=False, recalc=True, verts=verts, faces=faces, colours=colours, weights=weights)


# Spores shaken off four of her caps when she lands, up and out from each.
SPORES = {1: [(-1.5, -0.6), (-0.6, -1.9), (0.9, -1.6), (-2.2, 0.6)], 2: [(1.6, -0.8), (0.4, -1.9), (-1.0, -1.5),
                                                                           (2.2, 0.4)],
          4: [(1.6, -0.9), (0.5, -1.9), (2.1, 0.6), (-0.8, -1.6)], 5: [(-1.6, -0.9), (-0.5, -1.9), (-2.1, 0.6),
                                                                     (0.8, -1.6)]}
BURST = (12.0, 19.0, 3.4)  # between her fang tips, where the venom sprays when she bites
SPRAY = [(-2.9, -0.5), (2.9, -0.5), (-2.1, -2.0), (2.1, -2.0), (-3.7, 0.7), (3.7, 0.7), (0.0, -2.6)]


# -- the rig -------------------------------------------------------------------------------------------------------

def bones(face, dome) -> dict:
    out = {
        "root":    (None,      (12, GROUND, 0),          (12, GROUND - 3, 0)),
        "body":    ("root",    (12, 16.0, -0.5),         (12, 8.0, -0.5)),
        "abdomen": ("body",    (12, 9.8, -2.0),          (12, 2.5, -3.2)),
        "head":    ("body",    (12, 15.0, 1.5),          (12, 9.5, 1.5)),
        "silk":    ("root",    (SILK_X, SILK_TOP, SILK_Z), (SILK_X, SILK_END, SILK_Z)),
    }
    jaw_top = seen(JAW[0], JAW[1] - 0.6, JAW_Z + 0.6)
    tip = seen(*FANG[-1])
    drip_top, drip_end = seen(*DRIP[0]), seen(*DRIP[-1])
    for side, f in (("l", lambda p: p), ("r", lambda p: (mirror(p[0]), *p[1:]))):
        out[f"fang_{side}"] = ("head", f(jaw_top), f(tip))
        out[f"drip_{side}"] = (f"fang_{side}", f(drip_top), f(drip_end))
    (gx, gy), _, _ = EYES[GLINT]
    for side, x in (("l", gx), ("r", mirror(gx))):
        z = face(x, gy)
        out[f"glint_{side}"] = ("head", (x, gy - FACE_UP, z), (x, gy - FACE_UP - 1.0, z))
    out["burst"] = ("head", seen(*BURST), seen(BURST[0], BURST[1] - 2, BURST[2]))
    for n, (_, knee, joint) in LEGS.items():
        pts = leg_points(n)
        for side, f in (("l", lambda p: tuple(p)), ("r", lambda p: (mirror(p[0]), *p[1:]))):
            out[f"femur_{n}{side}"] = ("body", f(pts[0]), f(pts[knee]))
            out[f"tibia_{n}{side}"] = (f"femur_{n}{side}", f(pts[knee]), f(pts[joint]))
            out[f"tarsus_{n}{side}"] = (f"tibia_{n}{side}", f(pts[joint]), f(pts[-1]))
            foot = f(pts[-1])
            out[f"foot_{n}{side}"] = ("root" if n in PLANTED else "body", foot, (foot[0], foot[1] - 1.5, foot[2]))
            p = f(pole(n))
            out[f"pole_{n}{side}"] = ("body", p, (p[0], p[1] - 1.0, p[2]))
    for number, spec in TOADSTOOLS.items():
        stem, cap = placed(number, dome)
        out[f"ts_{number}"] = (spec[5], stem[0], cap)
        if number in SPORES:
            out[f"puff_{number}"] = (f"ts_{number}", cap, (cap[0], cap[1] - 1.5, cap[2]))
    return out


SWAP = {f"{b}_{n}l": f"{b}_{n}r" for b in ("femur", "tibia", "tarsus") for n in LEGS} | {
    "fang_l": "fang_r", "drip_l": "drip_r"}


# -- the lot -------------------------------------------------------------------------------------------------------

def build() -> dict:
    parts = {}
    grid = drawn(DOME, dome_colour)
    chevrons(grid)
    mask = np.array([[bool(c) for c in row] for row in grid])
    verts, faces, colours = pillow(mask, grid, DOME_SPEC)
    parts["dome"] = dict(bone="abdomen", smooth=True, verts=[(x, y + DOME_DOWN, z) for x, y, z in verts],
                         faces=faces, colours=colours)
    dome = surface(mask, DOME_SPEC)

    grid = drawn(FACE, face_colour)
    mask = np.array([[bool(c) for c in row] for row in grid])
    verts, faces, colours = pillow(mask, grid, FACE_SPEC)
    parts["face"] = dict(bone="head", smooth=True, verts=verts, faces=faces, colours=colours)
    face = surface(mask, FACE_SPEC)

    def eyes(x, y):
        for centre, half, colour in EYES:
            if squarish(x, y, centre, half) or squarish(x, y, (mirror(centre[0]), centre[1]), half):
                return colour
        return None

    parts["eyes"] = decal(eyes, face, 0.06, "head")
    centre, half, _ = EYES[GLINT]
    for side, cx in (("l", centre[0]), ("r", mirror(centre[0]))):
        parts[f"glint_{side}"] = decal(lambda x, y, cx=cx: WHITE if squarish(x, y, (cx, centre[1]), half) else None,
                                       face, 0.1, f"glint_{side}")
    for name in ("face", "eyes", "glint_l", "glint_r"):
        parts[name]["verts"] = [(x, y - FACE_UP, z) for x, y, z in parts[name]["verts"]]

    parts["jaw_l"], parts["fang_l"], parts["drip_l"] = jaw(), fang(), drip()
    for name in ("jaw", "fang", "drip"):
        parts[f"{name}_r"] = mirrored(parts[f"{name}_l"], SWAP)
    for n in LEGS:
        parts[f"leg_{n}l"] = leg(n)
        parts[f"leg_{n}r"] = mirrored(parts[f"leg_{n}l"], SWAP)
    for number in TOADSTOOLS:
        parts[f"toadstool_{number}"] = toadstool(number, dome)
    for number, spray in SPORES.items():
        _, cap = placed(number, dome)
        parts[f"puff_{number}"] = bits(cap, spray, CREAM, f"puff_{number}", size=0.5)
    parts["silk"] = silk()
    parts["burst"] = bits(seen(*BURST), SPRAY, GREEN, "burst", size=0.62)
    for part in parts.values():
        part["verts"] = [scaled(v) for v in part["verts"]]
        if "weights" in part and all(w == {part["bone"]: 1.0} for w in part["weights"]):
            del part["weights"]  # a part on one bone needs none: build_model() gives it all to its bone

    def hexed(c):
        return "#%02x%02x%02x" % c

    return {
        "sprite": "the_sporefang_matriarch", "size": SIZE, "fine": K, "ground": GROUND, "centre": 12,
        "scale": SCALE,
        "shades": {hexed(lit): hexed(dark) for lit, dark in SHADES.items()},
        "outline": hexed(OUTLINE),
        "heavier": {hexed(c): w for c, w in HEAVIER.items()},
        "bones": {name: {"parent": parent, "head": [round(float(c), 4) for c in scaled(head)],
                         "tail": [round(float(c), 4) for c in scaled(tail)]}
                  for name, (parent, head, tail) in bones(face, dome).items()},
        "parts": {name: {**part, "colours": [hexed(c) for c in part["colours"]],
                         "verts": [[round(float(c), 4) for c in v] for v in part["verts"]]}
                  for name, part in parts.items()},
    }


def main() -> None:
    data = build()
    OUT.mkdir(exist_ok=True)
    path = OUT / "matriarch_mesh.json"
    path.write_text(json.dumps(data, separators=(",", ":")))
    print(f"-> {path} ({path.stat().st_size // 1024} KB)")
    for name, part in data["parts"].items():
        print(f"  {name:12} {part['bone']:9} {len(part['verts']):6} verts {len(part['faces']):6} faces "
              f"{sorted(set(part['colours']))}")


# -- looking the frames over ---------------------------------------------------------------------------------------

CLIPS = ("Entrance", "Idle", "Attack", "Windup")
SIZES = (40, 48, 64, 84)


def frames(size: int, clip: str) -> list[Image.Image]:
    folder = OUT / f"frames_{size}" / clip / "0"
    return [Image.open(p).convert("RGBA") for p in sorted(folder.glob("*.png"))]


def check() -> None:
    """Each size's standing height and widest width, the entrance's landing frame (as tools/make_clip.py finds it),
    and every frame with anything below the idle's feet or touching the frame's sides or bottom."""
    for size in SIZES:
        idle = frames(size, "Idle")
        if not idle:
            continue
        stand = idle[0].getbbox()
        feet = max(f.getbbox()[3] for f in idle)
        widest, problems = (0, None), []
        for clip in CLIPS:
            for n, im in enumerate(frames(size, clip)):
                box = im.getbbox()
                if box is None:
                    continue
                if box[2] - box[0] > widest[0]:
                    widest = (box[2] - box[0], f"{clip} {n}")
                if box[3] > feet:
                    problems.append(f"{clip} {n}: {box[3] - feet} px below the feet")
                if box[0] == 0 or box[2] == size or box[3] == size:
                    problems.append(f"{clip} {n}: at the edge {box}")
        boxes = [f.getbbox() for f in frames(size, "Entrance")]
        last = boxes[-1][3]
        land = next((i for i, b in enumerate(boxes) if b is not None and b[3] >= last - 1), 0)
        print(f"{size}: standing {stand[3] - stand[1]} tall, {stand[2] - stand[0]} wide {stand}; widest "
              f"{widest[0]} ({widest[1]}), {widest[0] / (stand[3] - stand[1]):.2f}x its height; feet row {feet}; "
              f"entrance lands on {land}; " + ", ".join(f"{c} {len(frames(size, c))}" for c in CLIPS))
        for p in problems:
            print("   ", p)


def sheet(sizes: tuple = (48, 84), every: int = 3, scale: int = 4) -> Path:
    """Every third frame of each clip at 48 and at 84, four times as big, on a dark ground, a labelled row each."""
    label = 64
    rows = []
    for size in sizes:
        for clip in CLIPS:
            shots = frames(size, clip)
            rows.append((f"{clip} {size}", size, [(n, shots[n]) for n in range(0, len(shots), every)]))
    width = label + max(len(r[2]) * (r[1] * scale + 4) for r in rows)
    height = sum(r[1] * scale + 18 for r in rows)
    out = Image.new("RGBA", (width, height), (34, 32, 46, 255))
    draw = ImageDraw.Draw(out)
    y = 0
    for name, size, shots in rows:
        draw.text((4, y + 4), name, fill=(220, 220, 230, 255))
        for i, (n, im) in enumerate(shots):
            x = label + i * (size * scale + 4)
            cell = Image.new("RGBA", (size, size), (52, 50, 66, 255))
            cell.alpha_composite(im)
            out.alpha_composite(cell.resize((size * scale, size * scale), Image.NEAREST), (x, y + 14))
            draw.text((x + 2, y + 2), str(n), fill=(160, 160, 175, 255))
        y += size * scale + 18
    path = OUT / "sheet.png"
    out.save(path)
    print(f"-> {path} ({out.width}x{out.height})")
    return path


if __name__ == "__main__":
    task = sys.argv[1] if len(sys.argv) > 1 else "build"
    {"build": main, "check": check, "sheet": sheet}[task]()
