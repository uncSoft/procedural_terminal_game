"""Spike: the Rot Gill made solid, smooth and fine for Blender, the way inflate_thornmother.py made the Thornmother.

Its sprite (a stand-in drawn in the game's palette; the kids may draw it again): a round green frill of gills, striped
light and dark, round a dark purple mouth with two yellow eyes in it; pink poison dripping from the mouth; a dark green
stalk under it. The model keeps all of that and fills in what the flat front view can't show:

- the frill as a ball of gills, each a rib of its own on its own bone, lime and green in turn as drawn, closed over the
  pink flesh under them, so they can ripple, and all open at once (its tell) to show the flesh between them;
- fewer, wider gills than the sprite's one-pixel stripes, so they still read as stripes at 40 pixels;
- a mouth that stretches open, with a throat in it when it does, and its eyes as squarish decals, so they stay dots
  when it's shrunk small;
- its drips as blunt tubes hanging off its lip, kept well above the floor;
- a stalk that bends, its foot planted;
- a glob of poison to spit and the splat it makes, and drops thrown up when it lands.

It's a smaller thing than the bosses (it fights beside three others), so it's built a little under the sprite's own
scale (SCALE): about three quarters of a boss's height once framed the same way.

    uv run --no-sync --with numpy python spikes/goblin3d/inflate_rot_gill.py         # rot_gill/rot_gill_mesh.json
    uv run --no-sync --with numpy python spikes/goblin3d/inflate_rot_gill.py sheet   # rot_gill/sheet.png, to review

build_rot_gill.py, run inside Blender, rigs and animates it.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from inflate_abbot import add, lathe
from inflate_king import SIZE
from inflate_mouse import decal
from inflate_serpentis import mirror, mirrored, tube

HERE = Path(__file__).parent
OUT = HERE / "rot_gill"
SPRITE = HERE.parents[1] / "src" / "ptg" / "data" / "sprites" / "rot_gill.png"

OUTLINE = (24, 20, 37)
GREEN, LIME, MOSS = (62, 137, 72), (99, 199, 77), (38, 92, 66)
PURPLE, PINK, YELLOW = (104, 56, 108), (181, 80, 136), (254, 231, 97)

# Every colour it's painted in and the one its shadow side takes, all from its sprite: lime gills to the green between
# them, green to the dark green of its stalk. Its poison stays pink all round, as drawn (shaded purple, a drip a pixel
# wide or a glob in front of its mouth is lost against the mouth), and its eyes stay bright.
SHADES = {LIME: GREEN, GREEN: MOSS, MOSS: MOSS, PINK: PINK, PURPLE: PURPLE, YELLOW: YELLOW, OUTLINE: OUTLINE}
# What reduce.py counts heavier when it shrinks it, so the small things survive: its eyes, its drips.
HEAVIER = {YELLOW: 2.6, PINK: 1.25}  # (pink no heavier: a hairline of flesh between two gills would win a pixel)
GROUND = 23  # the bottom of its stalk: the floor
SCALE = 0.92  # the whole model, about the foot of its stalk: three quarters of a boss's height once framed


# -- the sprite ----------------------------------------------------------------------------------------------------

def sprite() -> dict[tuple[int, int], tuple]:
    sheet = Image.open(SPRITE).convert("RGBA")
    return {(x, y): sheet.getpixel((x, y))[:3] for y in range(SIZE) for x in range(SIZE)
            if sheet.getpixel((x, y))[3] >= 128}


PIXELS = sprite()
assert PIXELS[(10, 12)] == PIXELS[(13, 12)] == YELLOW, "its eyes aren't where they were drawn"
assert all(PIXELS[(x, 13)] == PURPLE for x in range(8, 16)), "its mouth isn't where it was drawn"
assert all(PIXELS[(x, 21)] == MOSS for x in range(9, 15)), "its stalk isn't where it was drawn"


# -- its flesh: the ball under the gills ---------------------------------------------------------------------------

# Its outline as drawn: 18 pixels across at its widest, from row 5 to about row 20 where its stalk goes in; round on
# top and fuller below. The flesh is that, less the gills' thickness.
CX, YC = 12.0, 12.6  # its middle
R, TOP, BOTTOM = 8.4, 7.0, 6.8  # the flesh's half-width, and how far it reaches up and down from its middle
P_TOP, P_BOTTOM = 2.0, 2.6  # how square it is above and below its middle (2: round)
SKIN = 0.08  # how far the gills sit off the flesh
RIB = 0.42  # how thick a gill is down its middle


def meridian(t: float) -> tuple[float, float, tuple[float, float]]:
    """The flesh's outline from its bottom (t = -1) round its side to its top (t = 1): its half-width and height there,
    and which way it faces (outward, down) there."""
    a = t * math.pi / 2
    p, b, sign = (P_TOP, TOP, -1) if t >= 0 else (P_BOTTOM, BOTTOM, 1)
    w = R * abs(math.cos(a)) ** (2 / p)
    dy = b * abs(math.sin(a)) ** (2 / p)
    nw, ny = (w / R) ** (p - 1) / R, sign * (dy / b) ** (p - 1) / b
    n = math.hypot(nw, ny)
    return w, YC + sign * dy, (nw / n, ny / n)


def half_width(y: float, grow: float = 0.0) -> float:
    """How wide the flesh is at height y, from its middle, or the gills' fronts when grown by their thickness."""
    p, b = (P_TOP, TOP) if y <= YC else (P_BOTTOM, BOTTOM)
    u = min(abs(y - YC) / (b + grow), 1.0)
    return (R + grow) * (1 - u ** p) ** (1 / p)


def shell(x: float, y: float) -> float:
    """How far forward the gills' fronts reach at (x, y): for things laid over them."""
    w = half_width(y, SKIN + RIB)
    return math.sqrt(max(w * w - (x - CX) ** 2, 0.0))


FLESH_TOP = 8.5  # above this the flesh is green, like the gills' tops, so their tips can part without a pink speck


def flesh(sides: int = 64, rings: int = 48) -> dict:
    """The ball under the gills: pink, seen only when they open; dark green at the bottom, where the stalk goes in, and
    green on top, where the gills are all green and their thin tips meet."""
    verts, faces, colours = [], [], []
    ts = np.linspace(-1, 1, rings + 1)
    for t in ts[1:-1]:
        w, y, _ = meridian(float(t))
        for k in range(sides):
            a = 2 * math.pi * k / sides
            verts.append((CX + w * math.sin(a), y, w * math.cos(a)))
    bottom, top = len(verts), len(verts) + 1
    verts += [(CX, YC + BOTTOM, 0.0), (CX, YC - TOP, 0.0)]

    def paint(t):
        y = meridian(t)[1]
        return GREEN if y < FLESH_TOP else MOSS if y > 18.8 else PINK

    for n in range(rings - 2):
        r0, r1 = n * sides, (n + 1) * sides
        mid = float(ts[n + 1] + ts[n + 2]) / 2
        for k in range(sides):
            faces.append([r0 + k, r0 + (k + 1) % sides, r1 + (k + 1) % sides, r1 + k])
            colours.append(paint(mid))
    last = (rings - 2) * sides
    for k in range(sides):
        faces.append([bottom, (k + 1) % sides, k])
        colours.append(MOSS)
        faces.append([top, last + k, last + (k + 1) % sides])
        colours.append(GREEN)
    return dict(bone="flesh", smooth=False, recalc=True, verts=verts, faces=faces, colours=colours)


# -- its gills -----------------------------------------------------------------------------------------------------

N = 20  # gills round it: fewer than the sprite's one-pixel stripes, so each is a stripe of two at 48 pixels
T_FOOT, T_TIP = -0.83, 0.985  # where they run from (into its stalk) and to (its top)
CAP_Y, BASE_Y = 7.3, 18.7  # above and below these they're all green, as drawn: its top and its underside


def phi(k: int) -> float:
    """Which way gill k faces, round from the viewer (0) toward the viewer's right."""
    return 2 * math.pi * k / N


def gill(k: int, across: int = 6, along: int = 48) -> dict:
    """Gill k: a rib over the flesh from its foot by the stalk to its top, a twentieth of the way round, thick down its
    middle and thin at its edges, where it meets the next. Lime and green in turn, from the lime one facing the viewer,
    and all green on top and underneath; its back, against the flesh, green."""
    ss, ts = np.linspace(-1, 1, across + 1), np.linspace(T_FOOT, T_TIP, along + 1)
    verts, index = [], {}

    def thick(s, t):
        ends = min(1.0, (t - T_FOOT) / 0.12, (T_TIP - t) / 0.2)
        return RIB * max(1 - abs(s) ** 4, 0.0) ** 0.5 * max(ends, 0.0) ** 0.5

    def vert(i, j, front):
        s, t = float(ss[i]), float(ts[j])
        rib = thick(s, t) if front else 0.0
        key = (i, j, rib > 0)
        if key not in index:
            w, y, (nw, ny) = meridian(t)
            a = phi(k) + s * math.pi / N
            out = SKIN + rib
            index[key] = len(verts)
            verts.append((CX + (w + out * nw) * math.sin(a), y + out * ny, (w + out * nw) * math.cos(a)))
        return index[key]

    def paint(t):
        y = meridian(t)[1]
        if y < CAP_Y or y > BASE_Y:
            return GREEN
        return LIME if k % 2 == 0 else GREEN

    faces, colours = [], []
    for j in range(along):
        colour = paint(float(ts[j] + ts[j + 1]) / 2)
        for i in range(across):
            corners = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            faces.append([vert(a, b, True) for a, b in corners])
            colours.append(colour)
            faces.append([vert(a, b, False) for a, b in reversed(corners)])
            colours.append(GREEN)
    faces = [list(dict.fromkeys(f)) for f in faces]
    keep = [n for n, f in enumerate(faces) if len(f) >= 3]
    return dict(bone=f"gill_{k:02d}", smooth=False, recalc=True, verts=verts,
                faces=[faces[n] for n in keep], colours=[colours[n] for n in keep])


def gill_bone(k: int) -> tuple:
    """A gill's bone: from its foot straight up, so it stretches upward; its z axis outward, so its x runs across it."""
    w, y, _ = meridian(T_FOOT)
    a = phi(k)
    foot = (CX + w * math.sin(a), y, w * math.cos(a))
    return foot, (foot[0], YC - TOP, foot[2]), (math.sin(a), 0.0, math.cos(a))


# -- its face ------------------------------------------------------------------------------------------------------

# Raised from where the sprite has them: from a little above, a face this far forward looks lower than drawn.
LIFT = 1.2
MOUTH = (12.0, 13.0 - LIFT)  # its middle
MOUTH_HALF = (4.0, 3.0)  # 8 pixels across and 6 down, as drawn
MOUTH_TOP, MOUTH_BOTTOM = MOUTH[1] - MOUTH_HALF[1], MOUTH[1] + MOUTH_HALF[1]
# A pixel further apart than drawn: so they fall square on two pixels with a gap between when it's shrunk to 40 (the
# 40-pixel grid isn't even under the 256-pixel render: at the sprite's spacing one eye came out wider than the other).
EYES = [(12 - 1.96, 12.5 - LIFT), (12 + 1.96, 12.5 - LIFT)]
# How far the mouth stands proud of the gills: stretched open, its top half moves down to where the ball is further
# forward, and must stay in front of it.
MOUTH_PROUD = 0.3


def in_mouth(x: float, y: float) -> bool:
    return abs((x - MOUTH[0]) / MOUTH_HALF[0]) ** 2.4 + abs((y - MOUTH[1]) / MOUTH_HALF[1]) ** 2.4 <= 1


def mouth_decal() -> dict:
    """Its mouth shut, as drawn, laid over the gills: its bone stretches it down to open it."""
    return decal(lambda x, y: PURPLE if in_mouth(x, y) else None, shell, MOUTH_PROUD, "jaw")


def on_mouth(x: float, y: float) -> float:
    return shell(x, y) + MOUTH_PROUD


def eyes_decal() -> dict:
    """Two yellow eyes in its mouth, a little bigger than its single pixels: nearly square, since anything rounder
    shrinks to a cross at 84 whenever it falls across a pixel's corner."""
    def inside(x, y):
        return YELLOW if any(abs((x - ex) / 0.66) ** 8 + abs((y - ey) / 0.8) ** 8 <= 1 for ex, ey in EYES) else None
    return decal(inside, on_mouth, 0.12, "face")


def throat_decal() -> dict:
    """The dark of its throat, in the lower half of its mouth, below its eyes: its bone grows it as the mouth opens."""
    def inside(x, y):
        return OUTLINE if ((x - 12) / 2.1) ** 2 + ((y - (MOUTH[1] + 1.4)) / 1.05) ** 2 <= 1 else None
    return decal(inside, on_mouth, 0.12, "throat")


# -- its drips -----------------------------------------------------------------------------------------------------

# Two, off its lip, as drawn: one from under its mouth, one from its lower corner. They hang straight down in front of
# its lower gills, blunt, and end well above the floor; their tops are tucked behind the mouth's edge.
DRIPS = {"l": (11.5, MOUTH_BOTTOM - 0.3), "r": (14.5, MOUTH_BOTTOM - 1.1)}
DRIP_END = 19.0 - LIFT - 0.4


def drip_z(x: float, top: float) -> float:
    return on_mouth(x, top) - 0.75


def drip(side: str) -> dict:
    x, top = DRIPS[side]
    z = drip_z(x, top)
    length = DRIP_END - top
    pts = [(x, top, z), (x, top + 0.45 * length, z), (x, top + 0.8 * length, z), (x, DRIP_END, z)]
    return dict(bone=f"drip_{side}", **tube(pts, [0.62, 0.64, 0.74, 0.7], lambda s, a: PINK,
                                             lambda u, b=f"drip_{side}": {b: 1.0}, steps=5, sides=10, tip=0.3))


# -- its stalk -----------------------------------------------------------------------------------------------------

# From inside the ball down to the floor: as wide as drawn (six pixels), a little wider at its foot.
STALK = [(17.4, 0.0), (17.4, 2.6), (19.0, 2.75), (20.5, 2.85), (21.6, 2.95), (22.3, 3.1), (22.8, 3.25),
         (23.0, 3.05), (23.0, 0.0)]
PLANTED, CARRIED = 22.4, 19.8  # below the first it's held by the floor, above the second by the ball


def stalk() -> dict:
    part = lathe(STALK, CX, 0.0, lambda y: MOSS, "body", sides=24)
    part["weights"] = []
    for _, y, _ in part["verts"]:
        t = min(max((PLANTED - y) / (PLANTED - CARRIED), 0.0), 1.0)
        part["weights"].append({"root": 1.0} if t == 0 else {"body": 1.0} if t == 1 else {"root": 1 - t, "body": t})
    return part


# -- poison: the glob it spits, the splat, the drops when it lands -------------------------------------------------

GLOB = (12.0, MOUTH[1] + 0.8, 9.0)  # where the glob starts: just inside its mouth
SPLAT = (29.8, 14.6, 13.0)  # where the glob bursts: out to the viewer's right (all within 1.5 times its height), as
#                            far forward as it was spat
SPRAY_BURST = [(1.4, -2.2), (2.0, 0.2), (1.2, 2.2), (-0.6, -2.6), (-0.4, 2.4), (0.6, -3.2)]
SPLASH_L = (5.6, 22.3, 1.8)  # drops thrown up off the floor beside its stalk when it lands
SPRAY_OUT = [(-2.0, -0.9), (-3.0, -2.6), (-1.0, -3.6), (0.6, -2.4), (-3.8, -1.0)]


def glob() -> dict:
    """A round glob of poison."""
    verts, faces, colours, weights = [], [], [], []
    for (cx, cy, cz), r in ((GLOB, 1.3),):
        profile = [(cy + r * math.cos(a), r * math.sin(a)) for a in np.linspace(math.pi, 0, 9)]
        part = lathe(profile, cx, cz, lambda y: PINK, "glob", sides=12)
        add({**part, "weights": [{"glob": 1.0}] * len(part["verts"])}, verts, faces, colours, weights)
    return dict(bone="glob", smooth=False, recalc=True, verts=verts, faces=faces, colours=colours, weights=weights)


def splash(at: tuple, spray: list, bone: str, size: float = 1.0) -> dict:
    verts, faces, colours, weights = [], [], [], []
    for dx, dy in spray:
        out = np.array((dx, dy, 0.0)) / math.hypot(dx, dy)
        centre = np.array(at) + (dx, dy, 0.0)
        add(tube([tuple(centre - 0.6 * size * out), tuple(centre), tuple(centre + 0.4 * size * out)],
                 [0.42 * size, 0.66 * size, 0.5 * size], lambda s, a: PINK, lambda u: {bone: 1.0}, steps=3, sides=8,
                 tip=0.45 * size),
            verts, faces, colours, weights)
    return dict(bone=bone, smooth=False, recalc=True, verts=verts, faces=faces, colours=colours, weights=weights)


# -- the rig -------------------------------------------------------------------------------------------------------

def bones() -> dict:
    """(parent, head, tail, z axis or None) in sprite pixels: x right, y down, z toward the viewer."""
    face_z = on_mouth(*MOUTH)
    out = {
        "root":   (None,   (CX, GROUND, 0.0),     (CX, 20.0, 0.0), None),
        "body":   ("root", (CX, CARRIED, 0.0),    (CX, 5.0, 0.0), None),
        "flesh":  ("body", (CX, YC, 0.0),         (CX, YC - TOP, 0.0), None),
        "face":   ("body", (CX, MOUTH_TOP, face_z), (CX, MOUTH_BOTTOM, face_z), None),
        "jaw":    ("face", (CX, MOUTH_TOP, face_z), (CX, MOUTH_BOTTOM, face_z), None),
        "throat": ("jaw",  (CX, MOUTH[1] + 1.4, face_z), (CX, MOUTH[1] + 3.4, face_z), None),
    }
    for side, (x, top) in DRIPS.items():
        z = drip_z(x, top)
        out[f"drip_{side}"] = ("jaw", (x, top, z), (x, DRIP_END, z), None)
    for k in range(N):
        foot, tip, z = gill_bone(k)
        out[f"gill_{k:02d}"] = ("body", foot, tip, z)
    out["glob"] = ("root", GLOB, (GLOB[0], GLOB[1] - 2, GLOB[2]), None)
    out["splat"] = ("root", SPLAT, (SPLAT[0], SPLAT[1] - 2, SPLAT[2]), None)
    out["splash_l"] = ("root", SPLASH_L, (SPLASH_L[0], SPLASH_L[1] - 2, SPLASH_L[2]), None)
    out["splash_r"] = ("root", (mirror(SPLASH_L[0]), *SPLASH_L[1:]), (mirror(SPLASH_L[0]), SPLASH_L[1] - 2,
                                                                      SPLASH_L[2]), None)
    return out


def scaled(p) -> tuple:
    """A point of the model, scaled about the foot of its stalk."""
    x, y, z = p
    return (CX + SCALE * (x - CX), GROUND - SCALE * (GROUND - y), SCALE * z)


# -- the lot -------------------------------------------------------------------------------------------------------

def build() -> dict:
    parts = {"flesh": flesh()}
    for k in range(N):
        parts[f"gill_{k:02d}"] = gill(k)
    parts["mouth"] = mouth_decal()
    parts["throat"] = throat_decal()
    parts["eyes"] = {**eyes_decal(), "smooth": False}  # smoothing would round and shrink them: crosses at 84
    parts["drip_l"], parts["drip_r"] = drip("l"), drip("r")
    parts["stalk"] = stalk()
    parts["glob"] = glob()
    parts["splat"] = splash(SPLAT, SPRAY_BURST, "splat")
    parts["splash_l"] = splash(SPLASH_L, SPRAY_OUT, "splash_l", 0.9)
    parts["splash_r"] = mirrored(parts["splash_l"], {"splash_l": "splash_r"})

    def hexed(c):
        return "#%02x%02x%02x" % c

    return {
        "sprite": "rot_gill", "size": SIZE, "ground": GROUND, "centre": CX, "scale": SCALE, "gills": N,
        "shades": {hexed(lit): hexed(dark) for lit, dark in SHADES.items()},
        "outline": hexed(OUTLINE),
        "heavier": {hexed(c): w for c, w in HEAVIER.items()},
        "bones": {name: {"parent": parent, "head": [round(c, 4) for c in scaled(head)],
                         "tail": [round(c, 4) for c in scaled(tail)],
                         **({"z": [round(float(c), 4) for c in z]} if z else {})}
                  for name, (parent, head, tail, z) in bones().items()},
        "parts": {name: {**part, "colours": [hexed(c) for c in part["colours"]],
                         "verts": [[round(float(c), 4) for c in scaled(v)] for v in part["verts"]]}
                  for name, part in parts.items()},
    }


# -- the review sheet ----------------------------------------------------------------------------------------------

def sheet(sizes=(48, 84), every: int = 3, zoom: int = 4, across: int = 12) -> Path:
    """Every third frame of each clip at 48 and at 84, four times as big, on the dark: a row (or two) a clip and size,
    each frame numbered."""
    clips = ["Entrance", "Idle", "Windup", "Attack"]
    rows = []
    for n in sizes:
        for clip in clips:
            paths = sorted((OUT / f"frames_{n}" / clip / "0").glob("*.png"))[::every]
            for start in range(0, len(paths), across):
                label = f"{clip} {n}" + ("" if start == 0 else " (on)")
                frames = [(int(p.stem), Image.open(p).convert("RGBA")) for p in paths[start:start + across]]
                rows.append((label, n, frames))
    label, gap, head = 150, 8, 18
    width = label + max(len(frames) * (n * zoom + gap) for _, n, frames in rows)
    height = sum(n * zoom + head + gap for _, n, _ in rows)
    out = Image.new("RGBA", (width, height), (24, 22, 36, 255))
    draw = ImageDraw.Draw(out)
    y = 0
    for name, n, frames in rows:
        side = n * zoom
        draw.text((8, y + head + side // 2 - 6), name, fill=(230, 230, 240, 255))
        for i, (number, frame) in enumerate(frames):
            x = label + i * (side + gap)
            cell = Image.new("RGBA", (side, side), (46, 44, 66, 255))
            cell.alpha_composite(frame.resize((side, side), Image.NEAREST))
            out.paste(cell, (x, y + head))
            draw.text((x + 2, y + 3), str(number), fill=(170, 170, 190, 255))
        y += side + head + gap
    path = OUT / "sheet.png"
    out.save(path)
    return path


def main() -> None:
    if sys.argv[1:] == ["sheet"]:
        print(f"-> {sheet()}")
        return
    data = build()
    OUT.mkdir(exist_ok=True)
    path = OUT / "rot_gill_mesh.json"
    path.write_text(json.dumps(data, separators=(",", ":")))
    print(f"-> {path} ({path.stat().st_size // 1024} KB)")
    for name, part in data["parts"].items():
        print(f"  {name:9} {part['bone']:9} {len(part['verts']):6} verts {len(part['faces']):6} faces "
              f"{sorted(set(part['colours']))}")


if __name__ == "__main__":
    main()
