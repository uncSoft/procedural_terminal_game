"""Spike: the Drowned Abbot made solid, smooth and fine for Blender, the way inflate_serpentis.py made Serpentis.

His sprite: a tall gold mitre with a blue front and a gold point rising out of its band; a pale, drowned face with two
cyan eyes glowing in dark sockets and a lank beard hanging in three points; a blue cope falling like a bell to the
floor, a gold stole hung round his neck and down his front, his drowned hands showing at his sides, and his hem soaked
through and dripping. The model keeps all of that and fills in what the flat front view can't show:

- a mitre with depth, its blue front set back between the gold;
- a face that juts out over his chest, sunken round the eyes, with a mouth that opens when he chants (shut, it's
  hidden, as in his sprite);
- a round cope, falling in folds to a hem that can flare;
- wide sleeves under the cope, so his arms can rise out of it;
- the censer his tell has him raise, gold, hanging on its chain from his hand on the viewer's right;
- drips under his hem and his censer, and splashes of the black water for when he lands and when he strikes.

    uv run --no-sync --with numpy python spikes/goblin3d/inflate_abbot.py    # writes spikes/goblin3d/drowned_abbot/abbot_mesh.json

build_abbot.py, run inside Blender, rigs and animates him.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from inflate_king import K, SIZE, epx, pillow
from inflate_mouse import decal, surface
from inflate_serpentis import chain, mirror, mirrored, tube

HERE = Path(__file__).parent
OUT = HERE / "drowned_abbot"
SPRITE = HERE.parents[1] / "src" / "ptg" / "data" / "sprites" / "drowned_abbot.png"

OUTLINE = (24, 20, 37)
BLUE, NAVY = (18, 78, 137), (38, 43, 68)
GOLD, AMBER = (254, 231, 97), (254, 174, 52)
PALE, GREY = (192, 203, 220), (139, 155, 180)
WATER, GLOW = (0, 153, 219), (44, 232, 245)

# Every colour he's painted in and the one its shadow side takes, all from his sprite: the cope's blue to the navy he
# was drawn with down its shadowed side, gold to the amber down his mitre's, his pale face to its grey. The water and
# his eyes stay bright.
SHADES = {BLUE: NAVY, NAVY: NAVY, GOLD: AMBER, AMBER: AMBER, PALE: GREY, GREY: GREY, WATER: WATER, GLOW: GLOW,
          OUTLINE: OUTLINE}
# What reduce.py counts heavier when it shrinks him, so the small things survive: his eyes and their sockets, his
# hands and the water, the thin gold of his stole and the censer's chain.
HEAVIER = {GLOW: 3.0, OUTLINE: 1.6, WATER: 1.6, GOLD: 1.5}
GROUND = 23  # the bottom of the drips under his hem


# -- the sprite ----------------------------------------------------------------------------------------------------

def sprite() -> dict[tuple[int, int], tuple]:
    sheet = Image.open(SPRITE).convert("RGBA")
    return {(x, y): sheet.getpixel((x, y))[:3] for y in range(SIZE) for x in range(SIZE)
            if sheet.getpixel((x, y))[3] >= 128}


PIXELS = sprite()
SOCKETS = {(8, 7), (15, 7)}  # the dark of his eye sockets, drawn over his face below


def load() -> dict[tuple[int, int], tuple[str, tuple]]:
    """The first frame's mitre and face as part and colour per pixel. Everything else (his cope, sleeves and hands,
    the water) is built round, below."""
    out = {}
    for (x, y), rgb in PIXELS.items():
        if y <= 5 and rgb in (GOLD, AMBER, BLUE):
            out[(x, y)] = ("mitre", rgb)
        elif 6 <= y <= 9 and (rgb in (PALE, GREY, GLOW) or (x, y) in SOCKETS):
            out[(x, y)] = ("head", PALE if rgb in (GLOW, OUTLINE) else rgb)  # his eyes are drawn over his face
    return out


def fine() -> list[list]:
    pixels = load()
    grid = [[pixels.get((x, y)) for x in range(SIZE)] for y in range(SIZE)]
    for _ in range(int(math.log2(K))):
        grid = epx(grid)
    return grid


def blur(a: np.ndarray, sigma: float) -> np.ndarray:
    r = int(3 * sigma)
    kernel = np.exp(-np.arange(-r, r + 1) ** 2 / (2 * sigma ** 2))
    kernel /= kernel.sum()
    a = np.apply_along_axis(lambda row: np.convolve(row, kernel, mode="same"), 1, a)
    return np.apply_along_axis(lambda col: np.convolve(col, kernel, mode="same"), 0, a)


def mitre_mid(colour: list[list], mask: np.ndarray):
    """His mitre sits on his head with its band round his brow and leans back to its point; its blue front is set
    back between the gold."""
    blue = blur(np.array([[1.0 if m and c == BLUE else 0.0 for c, m in zip(row, line)]
                          for row, line in zip(colour, mask)]), 0.35 * K)

    def mid(x, y):
        i = min(max(round(x * K), 0), SIZE * K - 1)
        j = min(max(round(y * K), 0), SIZE * K - 1)
        return 0.6 - 0.32 * (5.8 - y) - 0.35 * blue[j, i]
    return mid


def head_mid(x: float, y: float) -> float:
    """His face juts out over his chest, more the lower down; it's sunken round his eyes, with a stub of a nose."""
    jut = 0.9 + 1.3 * min(max((y - 6.0) / 3.5, 0.0), 1.0)
    nose = 0.3 * math.exp(-((x - 12) ** 2 + (y - 8.0) ** 2) / (2 * 0.5 ** 2))
    sockets = sum(0.35 * math.exp(-((x - sx) ** 2 / (2 * 0.8 ** 2) + (y - 7.5) ** 2 / (2 * 0.5 ** 2)))
                  for sx in (9.0, 15.0))
    return jut + nose - sockets


def titulus(x: float, y: float) -> tuple | None:
    """The gold point rising out of his mitre's band into the blue, a little bigger than drawn, so it survives."""
    return GOLD if 3.3 <= y <= 5.0 and abs(x - 12) <= 0.42 + 0.6 * (y - 3.3) / 1.7 else None


def beard(x: float, y: float) -> tuple | None:
    """His lank beard, hanging in the three points the sprite drew under his face, a little longer."""
    for cx, base, tip, colour in ((12.0, 1.0, 10.4, PALE), (8.5, 0.65, 10.2, PALE), (15.5, 0.65, 10.2, GREY)):
        if 8.9 <= y <= tip and abs(x - cx) <= base * (tip - y) / (tip - 9.0):
            return colour
    return None


PARTS = {
    "mitre": dict(bone="mitre", depth=2.0, flat=0.6, back=AMBER, behind=1.0, paint=titulus,
                  grow=[({(x, 6) for x in range(8, 16)}, GOLD)]),  # down behind his brow, so no gap shows
    "head": dict(bone="head", depth=2.4, flat=0.9, back=GREY, behind=0.8, mid=head_mid, paint=beard),
}


# -- the cope ------------------------------------------------------------------------------------------------------

# Its half-width down from his collar to the hem, as the sprite's outline has it (the sleeves make it wider at his
# elbows), and how deep it is for its width: a flattened bell.
ROBE = [(9.6, 3.4), (9.9, 4.5), (10.3, 5.4), (10.6, 6.0), (11.5, 7.0), (12.5, 7.6), (13.5, 7.9), (14.5, 8.0),
        (16.5, 8.0), (17.5, 8.3), (18.5, 8.8), (19.5, 9.3), (20.5, 10.0), (21.5, 10.8), (22.0, 11.0)]
DEEP = 0.38
FOLDS, FOLD = 8, 0.035  # folds round it, falling from its middle, and how deep at the hem
HEM_TOP = 21.0
HEM = {x: {WATER: WATER, BLUE: BLUE, NAVY: NAVY}[PIXELS[(x, 21)]] for x in range(1, 23)}  # the sodden hem, as drawn


def half_width(y: float) -> float:
    ys, ws = zip(*ROBE)
    return float(np.interp(y, ys, ws))


def fold(y: float) -> float:
    return FOLD * min(max((y - 16.5) / 5.5, 0.0), 1.0)


def on_robe(x: float, y: float) -> float:
    """How far forward the cope's front is at (x, y)."""
    w = half_width(y)
    s = min(abs(x - 12) / w, 1.0)
    return DEEP * w * math.sqrt(1 - s * s)


def robe_paint(a: float, y: float) -> tuple:
    """Blue, with the gold stole down his front where it was drawn, the collar in shadow under his face, and the hem
    soaked and glinting with the water."""
    x = 12 + half_width(y) * math.sin(a)
    if y >= HEM_TOP:
        return HEM[min(max(int(x), 1), 22)]
    if y < 10.1:
        return NAVY
    if math.cos(a) > 0.2 and PIXELS.get((int(x), int(y))) == GOLD:
        return GOLD
    return BLUE


def robe_weight(y: float) -> dict:
    """The hem stays on the floor when he bobs or leans; his shoulders go with his chest."""
    if y >= HEM_TOP:
        return {"hem": 1.0}
    if y >= 19.0:
        t = (y - 19.0) / (HEM_TOP - 19.0)
        return {"hem": t, "body": 1 - t} if t else {"body": 1.0}
    if y > 14.0:
        return {"body": 1.0}
    if y >= 12.0:
        t = (14.0 - y) / 2.0
        return {"chest": t, "body": 1 - t} if t else {"body": 1.0}
    return {"chest": 1.0}


def robe(sides: int = 128) -> dict:
    rings = list(np.linspace(9.6, 22.0, 63))
    verts, faces, colours, weights = [], [], [], []
    for y in rings:
        w, f = half_width(y), fold(y)
        for k in range(sides):
            a = 2 * math.pi * k / sides
            r = w * (1 + f * math.cos(FOLDS * a))
            verts.append((12 + r * math.sin(a), y, DEEP * r * math.cos(a)))
            weights.append(robe_weight(y))
    for n in range(1, len(rings)):
        r0, r1 = (n - 1) * sides, n * sides
        for k in range(sides):
            faces.append([r0 + k, r1 + k, r1 + (k + 1) % sides, r0 + (k + 1) % sides])
            colours.append(robe_paint(2 * math.pi * (k + 0.5) / sides, (rings[n - 1] + rings[n]) / 2))
    end = (len(rings) - 1) * sides
    faces += [list(range(sides)), list(range(end + sides - 1, end - 1, -1))]
    colours += [NAVY, NAVY]
    return dict(bone="body", smooth=False, recalc=True, verts=verts, faces=faces, colours=colours, weights=weights)


def drips() -> dict:
    """The water dripping off his hem onto the floor, where the sprite drew it."""
    verts, faces, colours, weights = [], [], [], []
    for x in (2.5, 6.5, 10.5, 13.5, 17.5, 21.5):
        z = on_robe(x, 21.8) * (1 + fold(21.8))
        end = 22.75 - (z - 2.0) * math.tan(math.radians(12))  # the nearer ones shorter: from above, all end level
        part = tube([(x, 21.5, z - 0.2), (x, (21.2 + end) / 2, z), (x, end - 0.3, z)], [0.5, 0.48, 0.42],
                    lambda s, a: WATER, lambda u: {"hem": 1.0}, steps=4, sides=8, tip=0.3)
        add(part, verts, faces, colours, weights)
    return dict(bone="hem", smooth=False, recalc=True, verts=verts, faces=faces, colours=colours, weights=weights)


def add(part: dict, verts: list, faces: list, colours: list, weights: list) -> None:
    base = len(verts)
    verts += part["verts"]
    faces += [[base + i for i in f] for f in part["faces"]]
    colours += part["colours"]
    weights += part["weights"]


# -- his arms ------------------------------------------------------------------------------------------------------

# A sleeve, from inside his cope at the shoulder out to its wide cuff at his side (the viewer's left; the right is the
# same), and his hand hanging out of it, where the sprite shows it.
ARM = [(8.2, 10.9, 0.2), (5.5, 13.6, 0.6), (3.7, 15.0, 0.95)]
HAND = [(3.5, 14.9, 1.0), (3.0, 15.8, 1.1), (2.7, 16.6, 1.15)]
HAND_TIP = (2.5, 17.3, 1.15)


def sleeve() -> dict:
    return dict(bone="arm_l", **tube(ARM, [1.05, 1.05, 1.35], lambda s, a: BLUE, chain(["arm_l", "forearm_l"]),
                                     steps=8, sides=16))


def hand() -> dict:
    """A drowned hand, long-fingered, hanging out of the sleeve."""
    verts, faces, colours, weights = [], [], [], []
    add(tube(HAND, [0.55, 0.6, 0.5], lambda s, a: WATER, lambda u: {"hand_l": 1.0}, steps=5, sides=10),
        verts, faces, colours, weights)
    for dx in (-0.32, 0.0, 0.32):
        start = np.array(HAND[-1]) + (dx, -0.2, 0.0)
        pts = [tuple(start), tuple(start + (0.3 * dx, 0.6, 0.05)), tuple(start + (0.5 * dx, 1.0, 0.0))]
        add(tube(pts, [0.24, 0.2, 0.16], lambda s, a: WATER, lambda u: {"hand_l": 1.0}, steps=3, sides=8, tip=0.2),
            verts, faces, colours, weights)
    return dict(bone="hand_l", smooth=False, recalc=True, verts=verts, faces=faces, colours=colours, weights=weights)


# -- his censer ----------------------------------------------------------------------------------------------------

# It hangs from his hand on the viewer's right: chain, then the censer, gold, a lid with a knob on it, a rim, a round
# bowl and a little foot. A drip of the black water hangs under it.
GRIP = (mirror(HAND_TIP[0]), HAND_TIP[1] - 0.4, 1.4)
CENSER_X, CENSER_Z = GRIP[0] + 0.1, 2.0
CHAIN_END = (CENSER_X, GRIP[1] + 0.8, CENSER_Z)
CENSER = [(CHAIN_END[1] + h, r) for h, r in (
    (0.0, 0.0), (0.05, 0.3), (0.25, 0.34), (0.55, 0.62), (0.85, 0.98), (0.95, 1.12), (1.05, 1.15), (1.15, 1.08),
    (1.3, 1.15), (1.7, 1.25), (2.1, 1.12), (2.45, 0.8), (2.6, 0.48), (2.7, 0.62), (2.88, 0.58), (2.95, 0.0))]
CENSER_BOTTOM = (CENSER_X, CENSER[-1][0], CENSER_Z)  # (height, radius) above, down from its knob


def lathe(profile: list, cx: float, cz: float, paint, bone: str, sides: int = 16) -> dict:
    """A round thing turned on an upright axis at (cx, cz): radius by height."""
    verts, faces, colours = [], [], []
    for y, r in profile:
        for k in range(sides):
            a = 2 * math.pi * k / sides
            verts.append((cx + r * math.sin(a), y, cz + r * math.cos(a)))
    for n in range(1, len(profile)):
        r0, r1 = (n - 1) * sides, n * sides
        for k in range(sides):
            faces.append([r0 + k, r1 + k, r1 + (k + 1) % sides, r0 + (k + 1) % sides])
            colours.append(paint((profile[n - 1][0] + profile[n][0]) / 2))
    return dict(bone=bone, smooth=False, recalc=True, verts=verts, faces=faces, colours=colours)


def censer() -> dict:
    rim = CHAIN_END[1] + 0.9, CHAIN_END[1] + 1.2
    return lathe(CENSER, CENSER_X, CENSER_Z, lambda y: AMBER if rim[0] <= y <= rim[1] else GOLD, "censer")


def censer_chain() -> dict:
    return dict(bone="chain", **tube([GRIP, (CENSER_X, CHAIN_END[1] - 0.35, 1.7), (CENSER_X, CHAIN_END[1] + 0.1, CENSER_Z)],
                                     [0.32, 0.32, 0.32],
                                     lambda s, a: GOLD, lambda u: {"chain": 1.0}, steps=4, sides=8))


def censer_drip() -> dict:
    bottom = CENSER_BOTTOM[1]
    return dict(bone="drip", **tube([(CENSER_X, bottom - 0.15, CENSER_Z), (CENSER_X, bottom + 0.35, CENSER_Z)], [0.36, 0.3],
                                    lambda s, a: WATER, lambda u: {"drip": 1.0}, steps=3, sides=8, tip=0.3))


# -- the splashes --------------------------------------------------------------------------------------------------

# Drops of the black water thrown up and out from a point on the floor: when he lands (at either side of his hem) and
# where his censer strikes. Each lives on a bone at that point, which spreads them as it grows (0 hides them).
SPLASH_L = (1.0, 22.5, 2.2)
SPLASH_HIT = (28.2, 22.3, 2.0)
SPRAY_OUT = [(-2.2, -0.9), (-3.4, -2.8), (-1.2, -4.0), (0.6, -2.6), (-4.4, -1.0)]  # thrown off to the viewer's left
SPRAY_BOTH = [(-3.0, -1.0), (-2.0, -3.4), (0.0, -4.4), (2.0, -3.4), (3.0, -1.0)]


def splash(at: tuple, spray: list, bone: str) -> dict:
    verts, faces, colours, weights = [], [], [], []
    for dx, dy in spray:
        out = np.array((dx, dy, 0.0)) / math.hypot(dx, dy)
        centre = np.array(at) + (dx, dy, 0.0)
        add(tube([tuple(centre - 0.7 * out), tuple(centre), tuple(centre + 0.5 * out)], [0.5, 0.78, 0.6],
                 lambda s, a: WATER, lambda u: {bone: 1.0}, steps=3, sides=8, tip=0.45),
            verts, faces, colours, weights)
    return dict(bone=bone, smooth=False, recalc=True, verts=verts, faces=faces, colours=colours, weights=weights)


# -- the rig -------------------------------------------------------------------------------------------------------

# The bones (x right, y down, z toward the viewer, in sprite pixels): parent, pivot, and where they point. The hem and
# the cope's middle hang off the root apart, so he can bob and lean with his hem staying put.
MOUTH = (12, 8.85)


def bones(mouth_z: float) -> dict:
    def r(p):
        return (mirror(p[0]), *p[1:])
    return {
        "root":      (None,        (12, GROUND, 0),      (12, 20, 0)),
        "hem":       ("root",      (12, GROUND, 0),      (12, 19, 0)),
        "body":      ("root",      (12, 21.0, 0),        (12, 13.5, 0)),
        "chest":     ("body",      (12, 13.5, 0),        (12, 10.0, 0)),
        "head":      ("chest",     (12, 10.0, 1.0),      (12, 5.8, 1.0)),
        "mitre":     ("head",      (12, 5.8, 0.0),       (12, 0.0, 0.0)),
        "mouth":     ("head",      (*MOUTH, mouth_z),    (MOUTH[0], MOUTH[1] + 0.8, mouth_z)),
        "arm_l":     ("chest",     ARM[0],               ARM[1]),
        "forearm_l": ("arm_l",     ARM[1],               ARM[2]),
        "hand_l":    ("forearm_l", ARM[2],               HAND_TIP),
        "arm_r":     ("chest",     r(ARM[0]),            r(ARM[1])),
        "forearm_r": ("arm_r",     r(ARM[1]),            r(ARM[2])),
        "hand_r":    ("forearm_r", r(ARM[2]),            r(HAND_TIP)),
        "chain":     ("hand_r",    GRIP,                 CHAIN_END),
        "censer":    ("chain",     CHAIN_END,            CENSER_BOTTOM),
        "drip":      ("censer",    (CENSER_X, CENSER_BOTTOM[1] - 0.15, CENSER_Z), (CENSER_X, CENSER_BOTTOM[1] + 0.8, CENSER_Z)),
        "splash_l":  ("root",      SPLASH_L,             (SPLASH_L[0], SPLASH_L[1] - 2, SPLASH_L[2])),
        "splash_r":  ("root",      r(SPLASH_L),          (mirror(SPLASH_L[0]), SPLASH_L[1] - 2, SPLASH_L[2])),
        "splash_hit": ("root",     SPLASH_HIT,           (SPLASH_HIT[0], SPLASH_HIT[1] - 2, SPLASH_HIT[2])),
    }


SWAP = {"arm_l": "arm_r", "forearm_l": "forearm_r", "hand_l": "hand_r", "splash_l": "splash_r"}


# -- the lot -------------------------------------------------------------------------------------------------------

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
        paint = spec.get("paint")
        for j in range(SIZE * K):
            for i in range(SIZE * K):
                c = paint and paint((i + 0.5) / K, (j + 0.5) / K)
                if c and (mask[j, i] or name == "head"):
                    mask[j, i] = True
                    colour[j][i] = c
        if name == "mitre":
            spec["mid"] = mitre_mid(colour, mask)
        masks[name] = mask
        verts, faces, colours = pillow(mask, colour, spec)
        parts[name] = dict(bone=spec["bone"], smooth=True, verts=verts, faces=faces, colours=colours)
    face = surface(masks["head"], PARTS["head"])

    # His eyes: dark sockets, each with its eye glowing in its inner half, as drawn; a little bigger than his single
    # pixels, and the same both sides.
    def eyes(x, y):
        for socket, eye in ((9.0, 9.55), (15.0, 14.45)):
            if ((x - eye) / 0.52) ** 2 + ((y - 7.5) / 0.5) ** 2 <= 1:
                return GLOW
            if ((x - socket) / 1.05) ** 2 + ((y - 7.5) / 0.62) ** 2 <= 1:
                return OUTLINE
        return None

    def gape(x, y):  # his mouth, open as wide as it goes: the bone squeezes it shut
        return OUTLINE if ((x - MOUTH[0]) / 1.7) ** 2 + ((y - MOUTH[1]) / 0.75) ** 2 <= 1 else None

    mouth_z = face(*MOUTH) + 0.12
    parts["eyes"] = decal(eyes, face, 0.06, "head")
    parts["mouth"] = decal(gape, face, 0.12, "mouth")
    parts["robe"] = robe()
    parts["drips"] = drips()
    parts["sleeve_l"], parts["hand_l"] = sleeve(), hand()
    parts["sleeve_r"], parts["hand_r"] = mirrored(parts["sleeve_l"], SWAP), mirrored(parts["hand_l"], SWAP)
    parts["chain"], parts["censer"], parts["censer_drip"] = censer_chain(), censer(), censer_drip()
    parts["splash_l"] = splash(SPLASH_L, SPRAY_OUT, "splash_l")
    parts["splash_r"] = mirrored(parts["splash_l"], SWAP)
    parts["splash_hit"] = splash(SPLASH_HIT, SPRAY_BOTH, "splash_hit")

    def hexed(c):
        return "#%02x%02x%02x" % c

    return {
        "sprite": "drowned_abbot", "size": SIZE, "fine": K, "ground": GROUND, "centre": 12,
        "shades": {hexed(lit): hexed(dark) for lit, dark in SHADES.items()},
        "outline": hexed(OUTLINE),
        "heavier": {hexed(c): w for c, w in HEAVIER.items()},
        "bones": {name: {"parent": parent, "head": list(head), "tail": list(tail)}
                  for name, (parent, head, tail) in bones(mouth_z).items()},
        "parts": {name: {**part, "colours": [hexed(c) for c in part["colours"]],
                         "verts": [[round(float(c), 4) for c in v] for v in part["verts"]]}
                  for name, part in parts.items()},
    }


def main() -> None:
    data = build()
    OUT.mkdir(exist_ok=True)
    path = OUT / "abbot_mesh.json"
    path.write_text(json.dumps(data, separators=(",", ":")))
    print(f"-> {path} ({path.stat().st_size // 1024} KB)")
    for name, part in data["parts"].items():
        print(f"  {name:11} {part['bone']:10} {len(part['verts']):6} verts {len(part['faces']):6} faces "
              f"{sorted(set(part['colours']))}")


if __name__ == "__main__":
    main()
