"""Spike: the Goblin King made solid, smooth and fine, ready for Blender.

The goblin test (voxelize.py) built a cube per pixel, which looks lumpy once it's turned and shrunk back down. The
King is built finer. The sprite is scaled up 8 times the pixel-art way (EPX, which rounds off diagonal steps without
blurring). Each part is then inflated like a balloon: a height that's zero on the part's edge and swells smoothly
toward its middle (the Poisson trick from sketch-to-3D tools). The surface is smooth enough to light, and it still
has the sprite's colours.

The crown is a ring round his head with the sprite's crown drawn on it. The cape gets a back the sprite never showed.
He also gets the sceptre his tell talks about: a frying pan.

    uv run --no-sync --with numpy python spikes/goblin3d/inflate_king.py     # writes spikes/goblin3d/king/king_mesh.json

build_king.py, run inside Blender, rigs and animates it.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).parent
OUT = HERE / "king"
SPRITE = HERE.parents[1] / "src" / "ptg" / "data" / "sprites" / "goblin_king.png"
SIZE, K = 24, 8  # the sprite's size, and how many times finer the model is

OUTLINE = (24, 20, 37)
GREEN, DARK_GREEN = (99, 199, 77), (62, 137, 72)
RED, DARK_RED = (228, 59, 68), (162, 38, 51)
BROWN, DARK_BROWN = (184, 111, 80), (116, 63, 57)
YELLOW, ORANGE = (254, 231, 97), (254, 174, 52)
WHITE = (255, 255, 255)
IRON, STEEL, SHINE = (58, 68, 102), (90, 105, 136), (139, 155, 180)
HEM_ROW, CAPE_HEM_ROW = 18, 21

# Every colour the model is painted in, and the darker one its shadow side takes when lit: the artist's own pairs
# (green and dark green, red and dark red, ...), the rest from the same palette (ENDESGA 32).
SHADES = {
    GREEN: DARK_GREEN, RED: DARK_RED, BROWN: DARK_BROWN, YELLOW: ORANGE,
    DARK_RED: (62, 39, 49), DARK_BROWN: (62, 39, 49), WHITE: (192, 203, 220), OUTLINE: OUTLINE,
    IRON: (38, 43, 68), STEEL: IRON, SHINE: STEEL,
}

# Each part: the bone it follows, how far it swells in front of its middle at the fullest (sprite pixels), how soon
# it gets there (1: a dome all the way; small: a slab with rounded edges), the colour of its back (None: the same as
# its front), how much of the swelling goes behind, and where its middle sits (depth, by x and y). "grow" adds pixels
# hidden inside a neighbour so the joins don't open up as parts turn: (pixels, colour or None for the sprite's).
PARTS = {
    "head":   dict(bone="head", depth=6.0, flat=1.0, back=GREEN,
                   grow=[({(x, y) for x in range(7, 17) for y in (1, 2)}, GREEN),
                         ({(x, 13) for x in range(8, 16)}, None)]),
    "ear_l":  dict(bone="ear_l", depth=0.9, flat=0.35, back=GREEN, mid=lambda x, y: 0.4 - 0.3 * (5 - x),
                   grow=[({(x, y) for x in (5, 6) for y in range(5, 9)}, GREEN)]),
    "ear_r":  dict(bone="ear_r", depth=0.9, flat=0.35, back=GREEN, mid=lambda x, y: 0.4 - 0.3 * (x - 19),
                   grow=[({(x, y) for x in (17, 18) for y in range(5, 9)}, GREEN)]),
    "torso":  dict(bone="torso", depth=5.0, flat=0.8, back=BROWN, behind=0.7,
                   grow=[({(x, 12) for x in range(8, 16)}, None)]),
    "arm_l":  dict(bone="arm_l", depth=0.55, flat=0.3, back=DARK_RED, mid=lambda x, y: 1.5 - 2.5 * ((6 - x) / 5) ** 2),
    "arm_r":  dict(bone="arm_r", depth=0.55, flat=0.3, back=DARK_RED, mid=lambda x, y: 1.5 - 2.5 * ((x - 18) / 5) ** 2),
    "hand_l": dict(bone="arm_l", depth=0.8, flat=0.7, back=GREEN, mid=lambda x, y: 2.1),
    "hand_r": dict(bone="arm_r", depth=0.8, flat=0.7, back=GREEN, mid=lambda x, y: 2.1),
    "leg_l":  dict(bone="leg_l", depth=1.3, flat=0.6, back=None,
                   grow=[({(x, y) for x in (7, 8) for y in (17, 18)}, None)]),
    "leg_r":  dict(bone="leg_r", depth=1.3, flat=0.6, back=None,
                   grow=[({(x, y) for x in (15, 16) for y in (17, 18)}, None)]),
    "boot_l": dict(bone="leg_l", depth=1.4, flat=0.6, back=DARK_BROWN, mid=lambda x, y: 0.7,
                   grow=[({(7, 20), (8, 20)}, None)]),
    "boot_r": dict(bone="leg_r", depth=1.4, flat=0.6, back=DARK_BROWN, mid=lambda x, y: 0.7,
                   grow=[({(15, 20), (16, 20)}, None)]),
}

# The bones, in sprite pixels (x right, y down, z toward the viewer): parent, pivot, and where they point.
HAND_L = (4.5, 17.5, 2.1)
ARM_L = (HAND_L[0] - 6, HAND_L[1] - 13)
PAN_AXIS = (ARM_L[0] / math.hypot(*ARM_L), ARM_L[1] / math.hypot(*ARM_L), 0.0)  # the pan carries on down the arm
PAN_HANDLE, PAN_RADIUS = 3.6, 3.3
PAN_CENTRE = tuple(h + a * (PAN_HANDLE + PAN_RADIUS - 0.1) for h, a in zip(HAND_L, PAN_AXIS))
BONES = {
    "root":  (None,    (12, 22, 0),      (12, 19, 0)),
    "torso": ("root",  (12, 18.5, 0),    (12, 13, 0)),
    "head":  ("torso", (12, 12.5, 0),    (12, 3, 0)),
    "crown": ("head",  (12, 2.5, 0),     (12, -0.5, 0)),
    "ear_l": ("head",  (5.5, 6.5, 0.5),  (0.5, 5, -1)),
    "ear_r": ("head",  (18.5, 6.5, 0.5), (23.5, 5, -1)),
    "arm_l": ("torso", (6, 13, 1),       HAND_L),
    "arm_r": ("torso", (18, 13, 1),      (19.5, 17.5, 2.1)),
    "pan":   ("arm_l", HAND_L,           PAN_CENTRE),
    "cape":  ("torso", (12, 13, -4.5),   (12, 21, -4.5)),
    "leg_l": ("root",  (7.5, 18.5, 0),   (7.5, 22, 0)),
    "leg_r": ("root",  (16.5, 18.5, 0),  (16.5, 22, 0)),
}


# -- the sprite ----------------------------------------------------------------------------------------------------

def part_of(x: int, y: int, rgb: tuple) -> str:
    """Which part a pixel of the King belongs to. The cape's sides are his sleeves: they hang from his shoulders and
    swing with his arms, and his hands poke out of them."""
    side = "l" if x < 12 else "r"
    if y <= 2:
        return "crown"
    if 4 <= y <= 8 and (x <= 4 or x >= 19):
        return f"ear_{side}"
    if y == 17 and rgb == DARK_GREEN and (x < 6 or x > 17):
        return f"hand_{side}"
    if rgb in (RED, DARK_RED):
        return f"arm_{side}"
    if y <= 12:
        return "head"
    if y >= 19:
        return f"leg_{side}"
    return "torso"


def load() -> dict[tuple[int, int], tuple[str, tuple]]:
    """The first frame as part and colour per pixel. The outline goes (a sprite tool draws its own), except the dark
    pixels inside his head: they're his mouth and pupils. The shading the artist drew down each part's sides goes
    too, since the light will do it, but drawing stays: the tunic's hem, the boots, the cape's hem."""
    sheet = Image.open(SPRITE).convert("RGBA")
    pixels = {(x, y): sheet.getpixel((x, y))[:3] for y in range(SIZE) for x in range(SIZE)
              if sheet.getpixel((x, y))[3] >= 128}

    def on_edge(x, y):
        return any((x + dx, y + dy) not in pixels for dx in (-1, 0, 1) for dy in (-1, 0, 1))

    out = {}
    for (x, y), rgb in pixels.items():
        part = part_of(x, y, rgb)
        if rgb == OUTLINE and (part != "head" or on_edge(x, y)):
            continue
        if rgb == DARK_GREEN:
            rgb = GREEN
        elif rgb == ORANGE:
            rgb = YELLOW
        elif rgb == DARK_BROWN and part == "torso" and y != HEM_ROW:
            rgb = BROWN
        elif rgb == DARK_RED and part.startswith("arm") and y != CAPE_HEM_ROW:
            rgb = RED
        out[(x, y)] = (part, rgb)
    for x, y in [p for p, (part, _) in out.items() if part.startswith("leg") and p[1] == CAPE_HEM_ROW]:
        out[(x, y)] = ("boot_" + out[(x, y)][0][-1], out[(x, y)][1])  # the boots get toes of their own
    return out


def epx(grid: list[list]) -> list[list]:
    """Scale2x (EPX): every pixel becomes four, and a corner takes its neighbours' colour where they agree, so steps
    on a diagonal round off and nothing new is mixed in."""
    h, w = len(grid), len(grid[0])

    def at(x, y):
        return grid[y][x] if 0 <= x < w and 0 <= y < h else None

    out = [[None] * (2 * w) for _ in range(2 * h)]
    for y in range(h):
        for x in range(w):
            p, a, b, c, d = grid[y][x], at(x, y - 1), at(x + 1, y), at(x - 1, y), at(x, y + 1)
            out[2 * y][2 * x] = a if c == a and c != d and a != b else p
            out[2 * y][2 * x + 1] = b if a == b and a != c and b != d else p
            out[2 * y + 1][2 * x] = c if d == c and d != b and c != a else p
            out[2 * y + 1][2 * x + 1] = d if b == d and b != a and d != c else p
    return out


def fine() -> list[list]:
    pixels = load()
    grid = [[pixels.get((x, y)) for x in range(SIZE)] for y in range(SIZE)]
    for _ in range(int(math.log2(K))):
        grid = epx(grid)
    return grid


# -- inflating ---------------------------------------------------------------------------------------------------

def poisson(free: np.ndarray) -> np.ndarray:
    """Solves -laplacian(u) = 1 on the free corners with u = 0 everywhere else (conjugate gradients). Its square root
    is a smooth, round swelling: a circle gives a half sphere."""
    def apply(u):
        pad = np.pad(u, 1)
        return np.where(free, 4 * u - pad[:-2, 1:-1] - pad[2:, 1:-1] - pad[1:-1, :-2] - pad[1:-1, 2:], 0.0)

    u = np.zeros(free.shape)
    r = free.astype(float)
    p, rs = r.copy(), (r * r).sum()
    for _ in range(4 * sum(free.shape)):
        ap = apply(p)
        alpha = rs / (p * ap).sum()
        u += alpha * p
        r -= alpha * ap
        new = (r * r).sum()
        if new < 1e-12 * free.sum():
            break
        p, rs = r + (new / rs) * p, new
    return u


def pillow(mask: np.ndarray, colour: list, spec: dict):
    """A part as a closed, smooth surface: a front sheet and a back sheet over the part's fine pixels, swelling apart
    in the middle and meeting on the edge. Vertices are sprite pixels (x, y, depth); faces are wound to face out."""
    h, w = mask.shape
    pad = np.pad(mask, 1)
    free = pad[:-1, :-1] & pad[:-1, 1:] & pad[1:, :-1] & pad[1:, 1:]  # corners with the part on every side
    u = poisson(free)
    v = np.clip(u / (spec["flat"] * u.max()), 0, 1)
    swell = spec["depth"] * np.sqrt(1 - (1 - v) ** 2)
    mid = spec.get("mid", lambda x, y: 0.0)
    behind = spec.get("behind", 1.0)
    verts, front, back = [], {}, {}

    def corner(i, j, sheet):
        if swell[j, i] == 0:
            sheet = front
        if (i, j) not in sheet:
            x, y = i / K, j / K
            z = mid(x, y) + (swell[j, i] if sheet is front else -behind * swell[j, i])
            sheet[(i, j)] = len(verts)
            if swell[j, i] == 0:
                back[(i, j)] = len(verts)
            verts.append((x, y, z))
        return sheet[(i, j)]

    faces, colours = [], []
    for j, i in zip(*np.nonzero(mask)):
        corners = [(i, j), (i, j + 1), (i + 1, j + 1), (i + 1, j)]  # this order faces the viewer (Blender's -Y)
        faces.append([corner(a, b, front) for a, b in corners])
        colours.append(colour[j][i])
        faces.append([corner(a, b, back) for a, b in reversed(corners)])
        colours.append(spec["back"] or colour[j][i])
    return verts, faces, colours


def crown_ring(grid: list[list], radius: float, depth: float, segments: int = 64):
    """The crown as a band round his head: each fine cell of the sprite's crown, wrapped so its middle is in front and
    its edges at his temples (the back is the front again, mirrored). Every cell is a little block, walls only where
    it has no neighbour; build_king.py turns the faces out."""
    cells = {}
    for k in range(segments):
        a = 2 * math.pi * (k + 0.5) / segments
        i = min(int((12 + radius * math.sin(a)) * K), 17 * K - 1)
        for j in range(3 * K):
            cell = grid[j][i]
            if cell and cell[0] == "crown":
                cells[(k, j)] = cell[1]
    verts, index = [], {}

    def vert(k, j, wall):
        key = (k % segments, j, wall)
        if key not in index:
            a = 2 * math.pi * key[0] / segments
            scale = 1.0 if wall else 0.88
            index[key] = len(verts)
            verts.append((12 + radius * scale * math.sin(a), j / K, depth * scale * math.cos(a)))
        return index[key]

    faces, colours = [], []
    for (k, j), colour in cells.items():
        quads = [[(k, j, 1), (k + 1, j, 1), (k + 1, j + 1, 1), (k, j + 1, 1)],
                 [(k, j, 0), (k, j + 1, 0), (k + 1, j + 1, 0), (k + 1, j, 0)]]
        if (k, j - 1) not in cells:
            quads.append([(k, j, 0), (k + 1, j, 0), (k + 1, j, 1), (k, j, 1)])
        if (k, j + 1) not in cells:
            quads.append([(k, j + 1, 1), (k + 1, j + 1, 1), (k + 1, j + 1, 0), (k, j + 1, 0)])
        if ((k - 1) % segments, j) not in cells:
            quads.append([(k, j, 1), (k, j + 1, 1), (k, j + 1, 0), (k, j, 0)])
        if ((k + 1) % segments, j) not in cells:
            quads.append([(k + 1, j, 0), (k + 1, j + 1, 0), (k + 1, j + 1, 1), (k + 1, j, 1)])
        for quad in quads:
            faces.append([vert(*c) for c in quad])
            colours.append(colour)
    return verts, faces, colours


def cape_back():
    """The cape's back, which the sprite never shows: a sheet behind him from his shoulders nearly to the floor,
    flaring toward the hem, curling forward at the sides to tuck in behind his sleeves. Red outside, its dark lining
    in."""
    def span(y):  # the cape's columns in row y (from, to), a little inside the sleeves
        flare = (y - 13) / 8
        return 6 - 3 * flare, 19 + 3 * flare

    mask = np.zeros((SIZE * K, SIZE * K), bool)
    for j in range(13 * K, 22 * K):
        left, right = span(j / K)
        mask[j, int(left * K):int(right * K)] = True

    def mid(x, y):
        left, right = span(min(max(y, 13), 22))
        half = (right - left) / 2
        return -4.6 + 3.1 * min(abs(x - (left + right) / 2) / half, 1) ** 4

    colour = [[DARK_RED] * (SIZE * K) for _ in range(SIZE * K)]
    return pillow(mask, colour, dict(depth=0.35, flat=0.3, back=RED, mid=mid))


def frying_pan(segments: int = 28):
    """His sceptre: an iron frying pan with a shiny rim and a gold band round its wooden handle, hanging from his
    left hand down the line of his arm. The bowl opens away from the viewer, so it faces them once he raises it,
    which is most of the time."""
    axis = np.array(PAN_AXIS)
    side, out = np.array((axis[1], -axis[0], 0.0)), np.array((0.0, 0.0, -1.0))
    hand, centre = np.array(HAND_L), np.array(PAN_CENTRE)
    verts, faces, colours = [], [], []

    def ring(at, radius, n, a_dir, b_dir):
        start = len(verts)
        for s in range(n):
            a = 2 * math.pi * s / n
            verts.append(tuple(at + radius * (math.cos(a) * a_dir + math.sin(a) * b_dir)))
        return list(range(start, start + n))

    # The handle: a round rod, wood then a gold band, capped at both ends.
    bands = [(-0.6, BROWN), (2.8, YELLOW), (PAN_HANDLE, None)]
    rings = [ring(hand + axis * s, 0.42, 10, side, out) for s, _ in bands]
    for (_, colour), r0, r1 in zip(bands, rings, rings[1:]):
        for s in range(10):
            faces.append([r0[s], r0[(s + 1) % 10], r1[(s + 1) % 10], r1[s]])
            colours.append(colour)
    faces += [rings[0][::-1], rings[-1]]
    colours += [BROWN, YELLOW]
    # The bowl: a profile turned round its middle, from the back's centre out, up the wall, over the rim, and in.
    profile = [(0, -0.3, IRON), (3.0, -0.3, IRON), (3.3, 0.0, IRON), (3.4, 0.7, SHINE), (3.0, 0.7, STEEL),
               (2.8, 0.1, STEEL), (0, 0.1, None)]
    loops = []
    for r, z, _ in profile:
        if r == 0:
            verts.append(tuple(centre + z * out))
            loops.append([len(verts) - 1] * segments)
        else:
            loops.append(ring(centre + z * out, r, segments, axis, side))
    for (_, _, colour), l0, l1 in zip(profile, loops, loops[1:]):
        for s in range(segments):
            t = (s + 1) % segments
            face = list(dict.fromkeys([l0[s], l0[t], l1[t], l1[s]]))
            faces.append(face)
            colours.append(colour)
    return verts, faces, colours


# -- the lot -----------------------------------------------------------------------------------------------------

def build() -> dict:
    grid = fine()
    parts = {}
    for name, spec in PARTS.items():
        mask = np.array([[bool(c) and c[0] == name for c in row] for row in grid])
        colour = [[c[1] if c else None for c in row] for row in grid]
        for pixels, fill in spec.get("grow", []):
            for x, y in pixels:
                for j in range(y * K, (y + 1) * K):
                    for i in range(x * K, (x + 1) * K):
                        if not mask[j, i]:
                            mask[j, i] = True
                            colour[j][i] = fill or (grid[j][i][1] if grid[j][i] else spec["back"])
        verts, faces, colours = pillow(mask, colour, spec)
        parts[name] = dict(bone=spec["bone"], smooth=True, verts=verts, faces=faces, colours=colours)
    # The crown sits just outside his head, as deep as his head is where it's worn.
    worn = max(z for x, y, z in parts["head"]["verts"] if abs(x - 12) <= 0.5 and 1 <= y <= 3)
    parts["crown"] = dict(bone="crown", smooth=False, recalc=True,
                          **dict(zip(("verts", "faces", "colours"), crown_ring(grid, 5.0, worn + 0.4))))
    parts["cape"] = dict(bone="cape", smooth=True, **dict(zip(("verts", "faces", "colours"), cape_back())))
    parts["pan"] = dict(bone="pan", smooth=False, recalc=True,
                        **dict(zip(("verts", "faces", "colours"), frying_pan())))
    hexed = {name: {**part, "colours": ["#%02x%02x%02x" % c for c in part["colours"]],
                    "verts": [[round(c, 4) for c in v] for v in part["verts"]]} for name, part in parts.items()}
    return {
        "sprite": "goblin_king", "size": SIZE, "fine": K, "ground": 22, "centre": 12,
        "shades": {"#%02x%02x%02x" % lit: "#%02x%02x%02x" % dark for lit, dark in SHADES.items()},
        "outline": "#%02x%02x%02x" % OUTLINE,
        "bones": {name: {"parent": parent, "head": list(head), "tail": list(tail)}
                  for name, (parent, head, tail) in BONES.items()},
        "parts": hexed,
    }


def main() -> None:
    data = build()
    OUT.mkdir(exist_ok=True)
    path = OUT / "king_mesh.json"
    path.write_text(json.dumps(data, separators=(",", ":")))
    print(f"-> {path} ({path.stat().st_size // 1024} KB)")
    for name, part in data["parts"].items():
        print(f"  {name:7} {part['bone']:6} {len(part['verts']):6} verts {len(part['faces']):6} faces "
              f"{sorted(set(part['colours']))}")


if __name__ == "__main__":
    main()
