"""Spike: Serpentis made solid, smooth and fine for Blender, the way inflate_mouse.py made King Mouse.

BelleDaBest drew her as a poison snake queen: a teal snake's face with angry crimson brows, white eyes, a wide black
mouth and a red tongue lolling out of it, under a great crimson crown of hooked, white-tipped spines; a banded
coral-snake body (yellow belly, black bands, orange sides) rising out of her coils, which curl up on both sides of her
like a bowl; thin orange arms raised out to her sides (higher in the second frame, where her tongue flicks the other
way). The model keeps all of that and fills in what the flat front view can't show, touched up the way the kids' art
is (the design stays hers):

- a crown that stands behind her head as a curved frill, with ribs running out to each white spine;
- a snake's head, broad and flat, her snout standing forward;
- a jaw that drops wide, and a viper's two white fangs that swing down out of the roof of her mouth;
- a forked tongue that curls to either side;
- a round body, banded all the way round, and her coils as two serpent tails (as Typhon had, in her war), each
  tapering to a point;
- three-fingered hands on her thin arms.

    uv run --no-sync --with numpy python spikes/goblin3d/inflate_serpentis.py    # writes spikes/goblin3d/serpentis/serpentis_mesh.json

build_serpentis.py, run inside Blender, rigs and animates her.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from inflate_king import K, SIZE, epx, pillow
from inflate_mouse import catmull, cells, decal, surface

HERE = Path(__file__).parent
OUT = HERE / "serpentis"
SPRITE = HERE.parents[1] / "src" / "ptg" / "data" / "sprites" / "serpentis.png"

OUTLINE = (24, 20, 37)
WHITE = (255, 255, 255)
CRIMSON, MAROON = (162, 38, 51), (122, 31, 40)
TEAL, GREEN = (25, 60, 62), (38, 92, 66)
TONGUE = (255, 0, 68)
GOLD, AMBER = (255, 186, 82), (254, 174, 52)  # her belly's two yellows: the paler one lit, the deeper one shaded
ORANGE, EMBER, RUST = (247, 118, 34), (245, 98, 0), (189, 75, 0)

# Every colour she's painted in and the one its shadow side takes, all from her own sprite: crimson to the maroon she
# drew under her crown, green to the teal of her face, her tongue to crimson, the pale belly yellow to the deeper one
# (she drew one tail in each), and the ember of her sides to the rust she drew down their shadowed edges. Her thin arms
# stay bright orange all round, to stand out from her coils.
SHADES = {
    CRIMSON: MAROON, MAROON: MAROON, GREEN: TEAL, TEAL: TEAL, WHITE: WHITE, OUTLINE: OUTLINE,
    TONGUE: CRIMSON, GOLD: AMBER, AMBER: AMBER, ORANGE: ORANGE, EMBER: RUST, RUST: RUST,
}
# What reduce.py counts heavier when it shrinks her, so the small things survive: her eyes and fangs, her tongue, her
# thin arms.
HEAVIER = {WHITE: 2.5, TONGUE: 1.5, ORANGE: 1.5}


def mirror(x: float) -> float:
    return 2 * 12 - x


# -- the sprite ----------------------------------------------------------------------------------------------------

def load() -> dict[tuple[int, int], tuple[str, tuple]]:
    """The first frame's crown and face as part and colour per pixel. Everything else (her tongue, body, coils and
    arms) is built round, below. Her face is evened up where her tongue hid it: the lower lip and chin are drawn
    whole, the same on both sides, and the mouth runs on under where the tongue came out."""
    sheet = Image.open(SPRITE).convert("RGBA")
    pixels = {(x, y): sheet.getpixel((x, y))[:3] for y in range(SIZE) for x in range(SIZE)
              if sheet.getpixel((x, y))[3] >= 128}
    out = {}
    for (x, y), rgb in pixels.items():
        if y <= 5 and rgb in (CRIMSON, MAROON, WHITE):
            if (x, y) not in SPINE_PIXELS:
                out[(x, y)] = ("crown", rgb)
        elif 5 <= y <= 10 and 7 <= x <= 16 and rgb in (TEAL, GREEN, WHITE, OUTLINE, CRIMSON):
            out[(x, y)] = ("head", TEAL if rgb == WHITE else rgb)  # her eyes are drawn over the face, below
    chin = {(8, 11): GREEN, (9, 11): TEAL, (14, 11): TEAL, (15, 11): GREEN,
            (10, 12): GREEN, (11, 12): TEAL, (12, 12): TEAL, (13, 12): GREEN,
            **{(x, 11): OUTLINE for x in range(10, 14)}}
    out.update({p: ("head", c) for p, c in chin.items()})
    return out


def fine() -> list[list]:
    pixels = load()
    grid = [[pixels.get((x, y)) for x in range(SIZE)] for y in range(SIZE)]
    for _ in range(int(math.log2(K))):
        grid = epx(grid)
    return grid


def head_mid(x: float, y: float) -> float:
    """Her head sits forward of her neck, broad and flat, and her snout further still."""
    return 1.2 + 1.3 * math.exp(-((x - 12) ** 2 / (2 * 2.6 ** 2) + (y - 9.6) ** 2 / (2 * 1.7 ** 2)))


# The spines' tips, where the crown's ribs run out to.
# Her crown's spines, as she drew them on its left (the right is the same): from the crown out to a white tip. Two
# stubs stand on top; from each end of its top bar and its lower bar a hook curls down and back up.
SPINES = [
    [(9.2, 1.3), (8.0, 0.65), (6.9, 0.5)],
    [(5.6, 1.6), (4.4, 2.5), (3.1, 2.6), (2.3, 2.1), (1.9, 1.5)],
    [(6.2, 4.0), (4.8, 4.75), (3.5, 5.5), (2.5, 5.3), (2.0, 4.6)],
]
SPINES += [[(mirror(x), y) for x, y in spine] for spine in SPINES]
SPINE_PIXELS = {(6, 0), (7, 0), (8, 0), (1, 1), (2, 1), (2, 2), (3, 2), (4, 2), (1, 4), (2, 4), (4, 4), (2, 5), (3, 5),
                (4, 5)}  # the crown pixels the spines stand in for
SPINE_PIXELS |= {(SIZE - 1 - x, y) for x, y in SPINE_PIXELS}


def crown_mid(x: float, y: float) -> float:
    """The crown stands behind her head and curves back at the sides, like a hood; ribs run out from behind her head
    toward each spine, with grooves between."""
    ribs = 0.0
    for spine in SPINES:
        sx, sy = spine[0]
        dx, dy = sx - 12, sy - 6.5
        length = math.hypot(dx, dy)
        along = ((x - 12) * dx + (y - 6.5) * dy) / length
        if 0 < along < length:
            across = abs((x - 12) * dy - (y - 6.5) * dx) / length
            ribs = max(ribs, math.exp(-across ** 2 / (2 * 0.35 ** 2)))
    return -1.6 - 0.022 * (x - 12) ** 2 + 0.35 * ribs


def spines() -> dict:
    """Her crown's spines as horns, round and thick enough to survive shrinking, each with a white tip: the sprite's
    one-pixel spines and their single white pixels wear away when it's smoothed."""
    verts, faces, colours = [], [], []
    for spine in SPINES:
        pts = [(x, y, crown_mid(x, y) + 0.3) for x, y in spine]
        path = catmull(pts, 6)
        length = sum(float(np.linalg.norm(q[1] - p[1])) for p, q in zip(path, path[1:]))
        radii = [0.62] * (len(spine) - 2) + [0.58, 0.48]
        part = tube(pts, radii, lambda s, a, end=length: WHITE if s > end - 0.7 else CRIMSON,
                    lambda u: {"crown": 1.0}, steps=6, sides=10, tip=0.55)
        base = len(verts)
        verts += part["verts"]
        faces += [[base + i for i in f] for f in part["faces"]]
        colours += part["colours"]
    return dict(bone="crown", smooth=False, recalc=True, verts=verts, faces=faces, colours=colours)


PARTS = {
    "crown": dict(bone="crown", depth=1.0, flat=0.5, back=MAROON, behind=1.0, mid=crown_mid,
                  grow=[({(x, y) for x in range(8, 16) for y in range(4, 9)}, CRIMSON)]),
    "head": dict(bone="head", depth=3.0, flat=1.0, back=TEAL, behind=0.9, mid=head_mid),
}


# -- the round parts -------------------------------------------------------------------------------------------------

def frame_at(path: list, n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Which way the tube runs at path point n, and two directions square to it: `side`, and `up`, which faces the
    viewer when the tube runs across the picture."""
    ahead = path[min(n + 1, len(path) - 1)][1] - path[max(n - 1, 0)][1]
    ahead = ahead / np.linalg.norm(ahead)
    side = np.cross(ahead, (0, 0, 1.0))
    side /= np.linalg.norm(side)
    return ahead, side, np.cross(side, ahead)


def tube(points: list, radii: list, paint, weigh, steps: int = 12, sides: int = 14, tip: float = 0.0) -> dict:
    """A round tube through the points (x, y, depth), its radius running through `radii`, closed flat at its start and
    ending in a point `tip` pixels on (or flat). paint(s, a) colours it by how far along it is in pixels (s) and how
    far round from its front (a, in degrees); weigh(u) gives its bones near point u (counted in points)."""
    path = catmull(points, steps)
    verts, faces, colours, weights, s = [], [], [], [], 0.0
    for n, (u, centre) in enumerate(path):
        if n:
            s += float(np.linalg.norm(centre - path[n - 1][1]))
        b = min(int(u), len(radii) - 2)
        radius = radii[b] + (radii[b + 1] - radii[b]) * (u - b)
        ahead, side, up = frame_at(path, n)
        for k in range(sides):
            a = 2 * math.pi * k / sides
            verts.append(tuple(centre + radius * (math.cos(a) * side + math.sin(a) * up)))
            weights.append(weigh(u))
        if n:
            r0, r1 = (n - 1) * sides, n * sides
            for k in range(sides):
                faces.append([r0 + k, r1 + k, r1 + (k + 1) % sides, r0 + (k + 1) % sides])
                round_from_front = abs((360 * (k + 0.5) / sides - 90 + 180) % 360 - 180)
                colours.append(paint(s, round_from_front))
    end = (len(path) - 1) * sides
    ahead = frame_at(path, len(path) - 1)[0]
    if tip:
        verts.append(tuple(path[-1][1] + tip * ahead))
        weights.append(weigh(path[-1][0]))
        faces += [[end + k, end + (k + 1) % sides, len(verts) - 1] for k in range(sides)]
    else:
        faces.append(list(range(end, end + sides)))
    faces.append(list(range(sides - 1, -1, -1)))
    colours += [paint(s, 180)] * (len(faces) - len(colours))
    return dict(smooth=False, recalc=True, verts=verts, faces=faces, colours=colours, weights=weights)


def chain(bones: list, blend: float = 0.3):
    """Weights for a tube along a chain of bones, one a stretch between points, shared near the joints so it bends
    smoothly."""
    def weigh(u):
        b = min(int(u), len(bones) - 1)
        frac = u - b
        if frac < blend and b > 0 and bones[b - 1] != bones[b]:
            return {bones[b - 1]: 0.5 * (1 - frac / blend), bones[b]: 0.5 + 0.5 * frac / blend}
        if frac > 1 - blend and b < len(bones) - 1 and bones[b + 1] != bones[b]:
            t = (frac - (1 - blend)) / blend
            return {bones[b]: 1 - 0.5 * t, bones[b + 1]: 0.5 * t}
        return {bones[b]: 1.0}
    return weigh


def mirrored(part: dict, swap: dict) -> dict:
    """A part flipped to her other side, its bones swapped for the other side's."""
    return {**part, "verts": [(mirror(x), y, z) for x, y, z in part["verts"]],
            "faces": [face[::-1] for face in part["faces"]],
            "weights": [{swap.get(b, b): w for b, w in ws.items()} for ws in part["weights"]],
            **({"bone": swap.get(part["bone"], part["bone"])} if "bone" in part else {})}


def belly(band, width: float = 48):
    """Her colouring: a yellow belly banded black, orange sides and back."""
    def paint(s, a):
        if a < width:
            return OUTLINE if band(s) else GOLD
        return EMBER
    return paint


# Her body, from where it sits in her coils up into the back of her head. Her bands run from just under her chin down,
# a pixel deep and a pixel apart, as she drew them.
NECK = [(12, 20.9, 0.4), (12, 17.5, 0.4), (12, 14.2, 0.6), (12, 11.4, 1.0), (12, 9.4, 0.6)]


def neck() -> dict:
    def band(s):
        return 20.9 - s >= 13.5 and (20.9 - s) % 2 < 1
    return dict(bone="body_1", **tube(NECK, [2.45, 2.3, 2.2, 2.1, 1.9], belly(band, width=42),
                                       chain(["body_1", "body_2", "body_3", "head"]), sides=18))


# Her coils: two serpent tails out of the bottom of her body, along the floor and curling up her sides to a point.
# They're as thin as she drew them: once outlined, her coils, arms and body need every pixel of the gaps between them.
COIL = [(12, 20.4, 0.8), (10.2, 20.4, 0.8), (8.0, 20.3, 1.0), (6.0, 19.4, 0.8), (4.6, 17.6, 0.2), (4.1, 15.4, -0.3),
        (4.0, 13.5, -0.6), (4.4, 12.0, -0.8)]
COIL_RADII = [1.55, 1.55, 1.5, 1.45, 1.3, 1.1, 0.85, 0.45]
# Which stretches of the coil each tail bone runs along: the floor, the bend up, her side, the tip.
TAIL_BONES = [(1, 3), (3, 4), (4, 5), (5, 7)]


def coil() -> dict:
    return dict(bone="tail_l_1", **tube(COIL, COIL_RADII, belly(lambda s: s % 2.1 >= 1.15, width=42),
                                        chain(["root", "tail_l_1", "tail_l_1", "tail_l_2", "tail_l_3", "tail_l_4",
                                               "tail_l_4"]), tip=0.7))


# Her arm, from inside her body at the shoulder, out and up to the hand, as she drew it in her first frame.
ARM = [(10.6, 15.6, 1.0), (8.6, 15.4, 1.2), (7.7, 14.5, 1.4), (7.2, 13.4, 1.5), (6.6, 12.4, 1.5), (5.7, 11.4, 1.5)]


def arm() -> dict:
    return dict(bone="arm_l", **tube(ARM, [0.68, 0.66, 0.64, 0.62, 0.6, 0.6], lambda s, a: ORANGE,
                                     chain(["arm_l", "arm_l", "forearm_l", "forearm_l", "forearm_l"]), sides=8))


def hand() -> dict:
    """Three long fingers at the end of her arm, fanned out and up, clear of her coils."""
    parts = []
    wrist = np.array(ARM[-1])
    for fan in (5, 30, 55):
        a = math.radians(180 + fan)
        out = np.array((math.cos(a), math.sin(a), 0.0))
        pts = [tuple(wrist + d * out + (0, 0, 0.15 * d)) for d in (0.0, 0.8, 1.6, 2.2)]
        parts.append(tube(pts, [0.5, 0.4, 0.3, 0.2], lambda s, a: ORANGE, lambda u: {"hand_l": 1.0},
                          steps=4, sides=8, tip=0.3))
    verts, faces, colours, weights = [], [], [], []
    for p in parts:
        base = len(verts)
        verts += p["verts"]
        faces += [[base + i for i in f] for f in p["faces"]]
        colours += p["colours"]
        weights += p["weights"]
    return dict(bone="hand_l", smooth=False, recalc=True, verts=verts, faces=faces, colours=colours, weights=weights)


TONGUE_ROOT = 11.0


def tongue(z: float) -> dict:
    """Out of her mouth and straight down (her poses curl it to one side or the other), thinning to a fork."""
    pts = [(12, TONGUE_ROOT - 0.4, z - 0.6), (12, TONGUE_ROOT + 0.6, z), (12, 12.4, z + 0.2), (12, 14.4, z + 0.2),
           (12, 16.0, z + 0.2)]
    body = tube(pts, [0.62, 0.62, 0.55, 0.45, 0.4], lambda s, a: TONGUE,
                chain(["tongue_1", "tongue_1", "tongue_2", "tongue_3"]), sides=10)
    verts, faces, colours, weights = body["verts"], body["faces"], body["colours"], body["weights"]
    for fan in (-28, 28):
        a = math.radians(fan)
        out = np.array((math.sin(a), math.cos(a), 0.0))
        start = np.array((12, 15.8, z + 0.2))
        prong = tube([tuple(start + d * out) for d in (0.0, 0.6, 1.2)], [0.36, 0.3, 0.22], lambda s, a: TONGUE,
                     lambda u: {"tongue_3": 1.0}, steps=4, sides=8, tip=0.35)
        base = len(verts)
        verts = verts + prong["verts"]
        faces = faces + [[base + i for i in f] for f in prong["faces"]]
        colours = colours + prong["colours"]
        weights = weights + prong["weights"]
    return dict(bone="tongue_1", smooth=False, recalc=True, verts=verts, faces=faces, colours=colours,
                weights=weights)


def fang(x: float, z: float) -> dict:
    """A viper's fang, hanging from the roof of her mouth and curving a little back in: it lives on its own bone, which
    shrinks it up into her mouth to fold it away."""
    inward = 1 if x < 12 else -1
    pts = [(x, 10.0, z), (x + 0.1 * inward, 10.7, z + 0.05), (x + 0.3 * inward, 11.4, z + 0.05)]
    part = tube(pts, [0.42, 0.34, 0.2], lambda s, a: WHITE, lambda u: {f"fang_{'l' if x < 12 else 'r'}": 1.0},
                steps=5, sides=8, tip=0.35)
    return dict(bone=f"fang_{'l' if x < 12 else 'r'}", **part)


# The bones (x right, y down, z toward the viewer, in sprite pixels): parent, pivot, and where they point. Her tongue
# hangs off her jaw, so it drops when her mouth opens.
FANG_Z = 5.75  # just proud of her whole mouth (5.46 at most), so they stay in front of it when it stretches open
TONGUE_Z = 5.9
BONES = {
    "root":      (None,        (12, 22, 0),            (12, 19, 0)),
    "body_1":    ("root",      (12, 20.9, 0.4),        (12, 17.5, 0.4)),
    "body_2":    ("body_1",    (12, 17.5, 0.4),        (12, 14.2, 0.6)),
    "body_3":    ("body_2",    (12, 14.2, 0.6),        (12, 11.4, 1.0)),
    "head":      ("body_3",    (12, 11.4, 1.0),        (12, 4.0, 1.0)),
    "crown":     ("head",      (12, 6.5, -1.6),        (12, 0.5, -1.6)),
    "jaw":       ("head",      (12, 11.0, 3.5),        (12, 12.8, 3.5)),
    "mouth":     ("head",      (12, 10.0, 3.5),        (12, 12.0, 3.5)),
    "fang_l":    ("head",      (10.3, 10.0, FANG_Z),   (10.6, 11.4, FANG_Z)),
    "fang_r":    ("head",      (13.7, 10.0, FANG_Z),   (13.4, 11.4, FANG_Z)),
    "tongue_1":  ("jaw",       (12, TONGUE_ROOT, TONGUE_Z), (12, 12.4, TONGUE_Z)),
    "tongue_2":  ("tongue_1",  (12, 12.4, TONGUE_Z),   (12, 14.4, TONGUE_Z)),
    "tongue_3":  ("tongue_2",  (12, 14.4, TONGUE_Z),   (12, 16.0, TONGUE_Z)),
    "arm_l":     ("body_2",    ARM[0],                 ARM[2]),
    "forearm_l": ("arm_l",     ARM[2],                 ARM[-1]),
    "hand_l":    ("forearm_l", ARM[-1],                (4.0, 10.2, 1.7)),
    "arm_r":     ("body_2",    (mirror(ARM[0][0]), *ARM[0][1:]), (mirror(ARM[2][0]), *ARM[2][1:])),
    "forearm_r": ("arm_r",     (mirror(ARM[2][0]), *ARM[2][1:]), (mirror(ARM[-1][0]), *ARM[-1][1:])),
    "hand_r":    ("forearm_r", (mirror(ARM[-1][0]), *ARM[-1][1:]), (mirror(4.0), 10.2, 1.7)),
    **{f"tail_l_{n}": ("root" if n == 1 else f"tail_l_{n - 1}", COIL[a], COIL[b])
       for n, (a, b) in enumerate(TAIL_BONES, 1)},
    **{f"tail_r_{n}": ("root" if n == 1 else f"tail_r_{n - 1}", (mirror(COIL[a][0]), *COIL[a][1:]),
                       (mirror(COIL[b][0]), *COIL[b][1:])) for n, (a, b) in enumerate(TAIL_BONES, 1)},
}
SWAP = {**{f"{b}_l": f"{b}_r" for b in ("arm", "forearm", "hand")},
        **{f"tail_l_{n}": f"tail_r_{n}" for n in range(1, 5)}}


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
                            colour[j][i] = fill
        masks[name] = mask
        verts, faces, colours = pillow(mask, colour, spec)
        parts[name] = dict(bone=spec["bone"], smooth=True, verts=verts, faces=faces, colours=colours)
    face = surface(masks["head"], PARTS["head"])

    def chin(x, y):  # her lower lip and chin, under her mouth
        if not masks["head"][min(int(y * K), SIZE * K - 1), int(x * K)] or y < 11.0:
            return None
        return OUTLINE if 10 <= x < 14 and y < 12 else (GREEN if x < 10.5 or x >= 13.5 else TEAL)

    def gape(x, y):  # her open mouth, as she drew it: wide at the top, narrowing down
        return OUTLINE if ((x - 12) / 3.0) ** 2 + ((y - 10.0) / 2.0) ** 2 <= 1 and y >= 10.0 else None

    parts["spines"] = spines()
    parts["jaw"] = decal(chin, face, 0.10, "jaw")
    parts["mouth"] = decal(gape, face, 0.05, "mouth")
    # Her eyes, a little bigger than her single pixels and the same both sides (smoothing wore one away more than the
    # other), with a snake's slit in each: too fine to show once she's shrunk, but there up close.
    def eyes(x, y):
        for ex in (9.5, 14.5):
            if ((x - ex) / 0.13) ** 2 + ((y - 8.5) / 0.4) ** 2 <= 1:
                return OUTLINE
            if ((x - ex) / 0.6) ** 2 + ((y - 8.5) / 0.5) ** 2 <= 1:
                return WHITE
        return None

    parts["eyes"] = decal(eyes, face, 0.06, "head")
    parts["fang_l"], parts["fang_r"] = fang(10.3, FANG_Z), fang(13.7, FANG_Z)
    parts["tongue"] = tongue(TONGUE_Z)
    parts["neck"] = neck()
    parts["coil_l"] = coil()
    parts["coil_r"] = mirrored(parts["coil_l"], SWAP)
    parts["arm_l"], parts["hand_l"] = arm(), hand()
    parts["arm_r"], parts["hand_r"] = mirrored(parts["arm_l"], SWAP), mirrored(parts["hand_l"], SWAP)

    def hexed(c):
        return "#%02x%02x%02x" % c

    return {
        "sprite": "serpentis", "size": SIZE, "fine": K, "ground": 22, "centre": 12,
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
    path = OUT / "serpentis_mesh.json"
    path.write_text(json.dumps(data, separators=(",", ":")))
    print(f"-> {path} ({path.stat().st_size // 1024} KB)")
    for name, part in data["parts"].items():
        print(f"  {name:8} {part['bone']:9} {len(part['verts']):6} verts {len(part['faces']):6} faces "
              f"{sorted(set(part['colours']))}")


if __name__ == "__main__":
    main()
