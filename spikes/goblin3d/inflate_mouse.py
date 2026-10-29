"""Spike: King Mouse made solid, smooth and fine for Blender, the way inflate_king.py made the Goblin King.

BelleDaBest drew him as a very big white mouse in a purple royal vest trimmed with gold, blue trousers, grey boots and
huge white fists; in the second frame his mouth is wide open and his claws are out. The model keeps all of that, and
fills in what a front-on sprite can't show, touched up the way the kids' art is (the design stays theirs):

- round mouse ears, grey with pink insides, where the sprite has grey tips;
- a snout, so his nose and mouth stand forward of his face;
- a jaw that drops, and a mouse's two front teeth (rodent yellow);
- three claws on each fist that slide out (BEWARE THE CLAWS) and back in;
- a pink tail, curling up by his side.

    uv run --no-sync --with numpy python spikes/goblin3d/inflate_mouse.py    # writes spikes/goblin3d/king_mouse/mouse_mesh.json

build_mouse.py, run inside Blender, rigs and animates him.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from inflate_king import K, SIZE, epx, pillow, poisson

HERE = Path(__file__).parent
OUT = HERE / "king_mouse"
SPRITE = HERE.parents[1] / "src" / "ptg" / "data" / "sprites" / "king_mouse.png"

OUTLINE = (24, 20, 37)
WHITE, PALE = (255, 255, 255), (192, 203, 220)
GREY, SLATE, DUSK, NAVY = (139, 155, 180), (90, 105, 136), (58, 68, 102), (38, 43, 68)
PINK, PURPLE, DARK = (181, 80, 136), (104, 56, 108), (62, 39, 49)
YELLOW, ORANGE = (254, 231, 97), (254, 174, 52)
BLUE = (18, 78, 137)

# Every colour he's painted in and the one its shadow side takes, all from his own sprite: the white fur shades to the
# pale grey she drew down his arms, pink to purple and purple to the vest's dark lining, as she shaded the vest, the
# gold braid to its orange, the blue to the navy of his claws, the grey boots to their darker edge.
SHADES = {
    WHITE: PALE, GREY: SLATE, SLATE: DUSK, PINK: PURPLE, PURPLE: DARK, DARK: DARK,
    YELLOW: ORANGE, ORANGE: ORANGE, BLUE: NAVY, OUTLINE: OUTLINE,
}
# What reduce.py counts heavier when it shrinks him, so the small things survive: eyes, nose and mouth, his teeth and
# the gold, his claws.
HEAVIER = {OUTLINE: 2.5, YELLOW: 1.3, GREY: 1.6}


def snout(x: float, y: float) -> float:
    """His head sits forward of his collar, and his nose and mouth further still."""
    return 2.0 + 1.6 * math.exp(-((x - 12) ** 2 / (2 * 1.5 ** 2) + (y - 5.4) ** 2 / (2 * 1.3 ** 2)))


def mirror(pixels: set) -> set:
    return {(SIZE - 1 - x, y) for x, y in pixels}


SHOULDER_L = {(3, 5), (4, 5), (4, 6)}
WRIST_L = {(x, 12) for x in range(1, 6)}
FOREARM_L = {(x, 11) for x in range(1, 5)}

# Each part, as in inflate_king.py: its bone, how far it swells, how soon (flat), its back's colour, how much of the
# swelling goes behind, where its middle sits (mid), and pixels it grows into, hidden, so joins don't open.
PARTS = {
    "head":   dict(bone="head", depth=4.0, flat=1.0, back=WHITE, behind=0.9, mid=snout,
                   grow=[({(x, 8) for x in range(10, 14)}, WHITE)]),
    "torso":  dict(bone="torso", depth=3.6, flat=0.8, back=PURPLE, behind=0.8,
                   grow=[({(x, 4) for x in range(8, 16)} | {(x, 5) for x in (8, 15)}, DARK)]),
    "arm_l":  dict(bone="arm_l", depth=2.4, flat=0.7, back=WHITE, mid=lambda x, y: 0.6,
                   grow=[(SHOULDER_L | WRIST_L, WHITE)]),
    "arm_r":  dict(bone="arm_r", depth=2.4, flat=0.7, back=WHITE, mid=lambda x, y: 0.6,
                   grow=[(mirror(SHOULDER_L | WRIST_L), WHITE)]),
    "fist_l": dict(bone="fist_l", depth=2.6, flat=0.8, back=WHITE, mid=lambda x, y: 0.9,
                   grow=[(FOREARM_L, WHITE)]),
    "fist_r": dict(bone="fist_r", depth=2.6, flat=0.8, back=WHITE, mid=lambda x, y: 0.9,
                   grow=[(mirror(FOREARM_L), WHITE)]),
    "leg_l":  dict(bone="leg_l", depth=1.6, flat=0.6, back=BLUE,
                   grow=[({(x, 16) for x in range(7, 11)}, None)]),
    "leg_r":  dict(bone="leg_r", depth=1.6, flat=0.6, back=BLUE,
                   grow=[({(x, 16) for x in range(13, 17)}, None)]),
    "boot_l": dict(bone="leg_l", depth=1.8, flat=0.6, back=SLATE, mid=lambda x, y: 0.8),
    "boot_r": dict(bone="leg_r", depth=1.8, flat=0.6, back=SLATE, mid=lambda x, y: 0.8),
}

# The tail, through these points (x, y, depth): from behind his hips, out past his right boot, curling up by his side.
TAIL = [(13.5, 16.0, -2.5), (17.5, 18.6, -3.0), (21.8, 19.6, -2.0), (25.0, 17.4, -1.2), (26.0, 13.4, -0.8),
        (24.9, 10.4, -0.4)]

# The bones (x right, y down, z toward the viewer, in sprite pixels): parent, pivot, and where they point.
BONES = {
    "root":    (None,      (12, 22, 0),        (12, 19, 0)),
    "torso":   ("root",    (12, 17, 0),        (12, 8, 0)),
    "head":    ("torso",   (12, 7.6, 0),       (12, 1, 0)),
    "jaw":     ("head",    (12, 7.0, 2.5),     (12, 8.5, 2.5)),
    "mouth":   ("head",    (12, 6.3, 2.5),     (12, 8.0, 2.5)),
    "ear_l":   ("head",    (8.6, 2.6, -0.3),   (7.0, -0.3, -0.3)),
    "ear_r":   ("head",    (15.4, 2.6, -0.3),  (17.0, -0.3, -0.3)),
    "arm_l":   ("torso",   (4.2, 6.5, 0.6),    (3.4, 11.8, 0.8)),
    "fist_l":  ("arm_l",   (3.4, 11.8, 0.8),   (4.5, 15.2, 1.0)),
    "claws_l": ("fist_l",  (4.5, 14.6, 1.3),   (4.5, 17.6, 1.8)),
    "arm_r":   ("torso",   (19.8, 6.5, 0.6),   (20.6, 11.8, 0.8)),
    "fist_r":  ("arm_r",   (20.6, 11.8, 0.8),  (19.5, 15.2, 1.0)),
    "claws_r": ("fist_r",  (19.5, 14.6, 1.3),  (19.5, 17.6, 1.8)),
    "leg_l":   ("root",    (8.0, 17, 0),       (7.5, 22, 0)),
    "leg_r":   ("root",    (16.0, 17, 0),      (16.5, 22, 0)),
    **{f"tail_{n + 1}": ("root" if n == 0 else f"tail_{n}", TAIL[n], TAIL[n + 1]) for n in range(len(TAIL) - 1)},
}


# -- the sprite ----------------------------------------------------------------------------------------------------

def part_of(x: int, y: int, rgb: tuple) -> str:
    side = "l" if x < 12 else "r"
    if 8 <= x <= 15 and 2 <= y <= 7 and rgb in (WHITE, OUTLINE):
        return "head"
    if rgb in (WHITE, PALE) and (x <= 6 or x >= 17) and 6 <= y <= 15:
        return f"{'arm' if y <= 11 else 'fist'}_{side}"
    if rgb == GREY:
        return "ear"
    if y >= 17:
        return f"{'boot' if rgb in (SLATE, DUSK) else 'leg'}_{side}"
    return "torso"


def load() -> dict[tuple[int, int], tuple[str, tuple]]:
    """The first frame as part and colour per pixel. The outline goes, except his eyes, nose and mouth (dark pixels
    inside his face); so does the shading she drew down each side (the light does that now). Her grey ear tips go too:
    the round ears are drawn separately. The dark crease across each fist is filled in, so the fist is one round
    lump."""
    sheet = Image.open(SPRITE).convert("RGBA")
    pixels = {(x, y): sheet.getpixel((x, y))[:3] for y in range(SIZE) for x in range(SIZE)
              if sheet.getpixel((x, y))[3] >= 128}

    def in_face(x, y):
        return all(pixels.get(n) in (WHITE, OUTLINE) for n in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))

    out = {}
    for (x, y), rgb in pixels.items():
        part = part_of(x, y, rgb)
        if part == "ear" or (rgb == OUTLINE and not (part == "head" and in_face(x, y))):
            continue
        out[(x, y)] = (part, {PALE: WHITE, DUSK: SLATE}.get(rgb, rgb))
    for x, y in {(4, 13), (5, 13)}:
        out[(x, y)] = ("fist_l", WHITE)
    for x, y in mirror({(4, 13), (5, 13)}):
        out[(x, y)] = ("fist_r", WHITE)
    return out


def fine() -> list[list]:
    pixels = load()
    grid = [[pixels.get((x, y)) for x in range(SIZE)] for y in range(SIZE)]
    for _ in range(int(math.log2(K))):
        grid = epx(grid)
    # Her eyes, nose and mouth are single pixels: an eighth of a pixel bigger, they hold steady when he's shrunk small
    # (much bigger and, shrunk to twice the sprite's size, an eye can come out as a little cross).
    dark = [(i, j) for j, row in enumerate(grid) for i, c in enumerate(row) if c == ("head", OUTLINE)]
    for i, j in dark:
        for di, dj in ((1, 0), (0, 1), (1, 1)):
            if grid[j + dj][i + di] == ("head", WHITE):
                grid[j + dj][i + di] = ("head", OUTLINE)
    return grid


def surface(mask: np.ndarray, spec: dict):
    """How far forward a part's front is at any point (x, y), as pillow() will build it: for things laid on it."""
    pad = np.pad(mask, 1)
    u = poisson(pad[:-1, :-1] & pad[:-1, 1:] & pad[1:, :-1] & pad[1:, 1:])
    swell = spec["depth"] * np.sqrt(1 - (1 - np.clip(u / (spec["flat"] * u.max()), 0, 1)) ** 2)
    mid = spec.get("mid", lambda x, y: 0.0)

    def z(x, y):
        i = min(max(round(x * K), 0), swell.shape[1] - 1)
        j = min(max(round(y * K), 0), swell.shape[0] - 1)
        return mid(x, y) + swell[j, i]
    return z


# -- the touch-ups ---------------------------------------------------------------------------------------------------

def cells(inside) -> tuple[np.ndarray, list[list]]:
    """A fine mask over the sprite of the cells whose middles `inside(x, y)` gives a colour for."""
    mask = np.zeros((SIZE * K, SIZE * K), bool)
    colour = [[None] * (SIZE * K) for _ in range(SIZE * K)]
    for j in range(SIZE * K):
        for i in range(SIZE * K):
            c = inside((i + 0.5) / K, (j + 0.5) / K)
            if c:
                mask[j, i], colour[j][i] = True, c
    return mask, colour


def decal(inside, on, lift: float, bone: str) -> dict:
    """A thin shape laid over the face `lift` pixels proud of it: his teeth, his open mouth, his chin."""
    mask, colour = cells(inside)
    verts, faces, colours = pillow(mask, colour, dict(depth=0.05, flat=0.4, back=None,
                                                      mid=lambda x, y: on(x, y) + lift))
    return dict(bone=bone, smooth=True, verts=verts, faces=faces, colours=colours)


def ear(cx: float, cy: float, inward: float) -> dict:
    """A round ear, grey with a pink middle nearer his head, lying a little behind his face. Built on a grid of its
    own, since it pokes above the sprite's top edge."""
    r, size = 1.9, 5
    left, top = cx - size / 2, cy - size / 2

    def inside(x, y):
        x, y = x + left, y + top
        if (x - cx) ** 2 + (y - cy) ** 2 > r ** 2:
            return None
        return PINK if (x - cx - 0.4 * inward) ** 2 + (y - cy - 0.35) ** 2 <= (0.6 * r) ** 2 else GREY

    mask = np.zeros((size * K, size * K), bool)
    colour = [[None] * (size * K) for _ in range(size * K)]
    for j in range(size * K):
        for i in range(size * K):
            c = inside((i + 0.5) / K, (j + 0.5) / K)
            if c:
                mask[j, i], colour[j][i] = True, c
    verts, faces, colours = pillow(mask, colour, dict(depth=0.45, flat=0.5, back=GREY, mid=lambda x, y: -0.3))
    return dict(smooth=True, verts=[(x + left, y + top, z) for x, y, z in verts], faces=faces, colours=colours)


def claws(side: str) -> dict:
    """Three big claws curving down out of the bottom of a fist and hooking toward the viewer: steel grey, with the
    dark outline round them once shrunk, and chunky enough to survive shrinking. They live on their own bone, which shrinks them into the fist to sheathe them."""
    sign = 1 if side == "l" else -1
    verts, faces, colours = [], [], []
    for dx, dy, fan in [(-1.0, 0.0, -16), (0.0, 0.25, 0), (1.0, 0.0, 16)]:
        base = np.array((12 + sign * (4.5 + dx - 12), 14.6 + dy, 1.3))
        a = math.radians(sign * fan)
        down = np.array((math.sin(a), math.cos(a), 0.0))
        start = len(verts)
        rings = 7
        for s in range(rings):
            t = s / (rings - 1)
            centre = base + 3.4 * (t * down + 0.45 * t * t * np.array((0, -0.3, 1.0)))
            radius = 0.72 * (1 - t) ** 0.7
            if s == rings - 1:
                verts.append(tuple(centre))
                break
            for k in range(8):
                b = 2 * math.pi * k / 8
                verts.append(tuple(centre + radius * np.array((math.cos(b), 0.0, math.sin(b)))))
        for s in range(rings - 2):
            for k in range(8):
                r0, r1 = start + 8 * s, start + 8 * (s + 1)
                faces.append([r0 + k, r0 + (k + 1) % 8, r1 + (k + 1) % 8, r1 + k])
        tip, last = len(verts) - 1, start + 8 * (rings - 2)
        faces += [[last + k, last + (k + 1) % 8, tip] for k in range(8)]
        faces.append(list(range(start + 7, start - 1, -1)))
        colours += [GREY] * (len(faces) - len(colours))
    return dict(bone=f"claws_{side}", smooth=False, recalc=True, verts=verts, faces=faces, colours=colours)


def catmull(points: list, steps: int) -> list[tuple[float, np.ndarray]]:
    """A smooth curve through the points: (where along it, counted in points; the point)."""
    p = [np.array(points[0]) * 2 - np.array(points[1])] + [np.array(q) for q in points] + \
        [np.array(points[-1]) * 2 - np.array(points[-2])]
    out = []
    for n in range(len(points) - 1):
        p0, p1, p2, p3 = p[n:n + 4]
        for s in range(steps):
            t = s / steps
            out.append((n + t, 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                                      + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)))
    out.append((len(points) - 1.0, np.array(points[-1])))
    return out


def tail() -> dict:
    """A pink tube along TAIL, thinning to a round tip. Each stretch follows its own bone, shared with the next near the
    joints so it bends smoothly when it lashes."""
    path = catmull(TAIL, 14)
    bones = len(TAIL) - 1
    verts, faces, weights = [], [], []
    sides = 10
    for n, (u, centre) in enumerate(path):
        ahead = path[min(n + 1, len(path) - 1)][1] - path[max(n - 1, 0)][1]
        ahead /= np.linalg.norm(ahead)
        side = np.cross(ahead, (0, 0, 1.0))
        side /= np.linalg.norm(side)
        up = np.cross(side, ahead)
        radius = 0.8 - 0.42 * (u / bones) ** 1.3
        b = min(int(u), bones - 1)
        frac = u - b
        w = {f"tail_{b + 1}": 1.0}
        if frac < 0.3 and b > 0:
            w = {f"tail_{b}": 0.5 * (1 - frac / 0.3), f"tail_{b + 1}": 0.5 + 0.5 * frac / 0.3}
        elif frac > 0.7 and b < bones - 1:
            w = {f"tail_{b + 1}": 1 - 0.5 * (frac - 0.7) / 0.3, f"tail_{b + 2}": 0.5 * (frac - 0.7) / 0.3}
        for k in range(sides):
            a = 2 * math.pi * k / sides
            verts.append(tuple(centre + radius * (math.cos(a) * side + math.sin(a) * up)))
            weights.append(w)
    for n in range(len(path) - 1):
        r0, r1 = n * sides, (n + 1) * sides
        faces += [[r0 + k, r1 + k, r1 + (k + 1) % sides, r0 + (k + 1) % sides] for k in range(sides)]
    end = (len(path) - 1) * sides
    verts.append(tuple(path[-1][1] + 0.35 * (path[-1][1] - path[-2][1]) / np.linalg.norm(path[-1][1] - path[-2][1])))
    weights.append({f"tail_{bones}": 1.0})
    faces += [[end + k, end + (k + 1) % sides, len(verts) - 1] for k in range(sides)]
    faces.append(list(range(sides - 1, -1, -1)))
    return dict(bone="tail_1", smooth=False, recalc=True, verts=verts, faces=faces, colours=[PINK] * len(faces),
                weights=weights)


# -- the lot -----------------------------------------------------------------------------------------------------

def build() -> dict:
    grid = fine()
    parts, masks = {}, {}
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
        masks[name] = mask
        verts, faces, colours = pillow(mask, colour, spec)
        parts[name] = dict(bone=spec["bone"], smooth=True, verts=verts, faces=faces, colours=colours)
    face = surface(masks["head"], PARTS["head"])

    def chin(x, y):  # the bit of his face below his mouth
        return WHITE if masks["head"][int(y * K), int(x * K)] and 7.0 <= y < 8.0 and 9.6 <= x < 14.4 else None

    parts["jaw"] = decal(chin, face, 0.10, "jaw")
    parts["mouth"] = decal(lambda x, y: OUTLINE if ((x - 12) / 1.85) ** 2 + ((y - 7.0) / 1.0) ** 2 <= 1 and y >= 6.3
                           else None, face, 0.05, "mouth")
    # The teeth stand flat, just proud of his whole mouth: the open mouth stretches down but keeps the depth of the
    # face it was laid on, which is further forward higher up, and the teeth must stay in front of it.
    proud = max(face(x / 4, y / 4) for x in range(40, 57) for y in range(25, 33)) + 0.2
    parts["teeth"] = decal(lambda x, y: YELLOW if 6.5 <= y < 7.9 and (11.0 <= x < 11.95 or 12.05 <= x < 13.0)
                           else None, lambda x, y: proud, 0.0, "head")
    parts["ear_l"] = dict(bone="ear_l", **ear(7.3, 1.0, inward=1))
    parts["ear_r"] = dict(bone="ear_r", **ear(16.7, 1.0, inward=-1))
    parts["claws_l"], parts["claws_r"] = claws("l"), claws("r")
    parts["tail"] = tail()

    def hexed(c):
        return "#%02x%02x%02x" % c

    return {
        "sprite": "king_mouse", "size": SIZE, "fine": K, "ground": 22, "centre": 12,
        "shades": {hexed(lit): hexed(dark) for lit, dark in SHADES.items()},
        "outline": hexed(OUTLINE),
        "heavier": {hexed(c): w for c, w in HEAVIER.items()},
        "bones": {name: {"parent": parent, "head": list(head), "tail": list(tail)}
                  for name, (parent, head, tail) in BONES.items()},
        "parts": {name: {**part, "colours": [hexed(c) for c in part["colours"]],
                         "verts": [[round(float(c), 4) for c in v] for v in part["verts"]]}
                  for name, part in parts.items()},
    }


def main() -> None:
    data = build()
    OUT.mkdir(exist_ok=True)
    path = OUT / "mouse_mesh.json"
    path.write_text(json.dumps(data, separators=(",", ":")))
    print(f"-> {path} ({path.stat().st_size // 1024} KB)")
    for name, part in data["parts"].items():
        print(f"  {name:8} {part['bone']:8} {len(part['verts']):6} verts {len(part['faces']):6} faces "
              f"{sorted(set(part['colours']))}")


if __name__ == "__main__":
    main()
