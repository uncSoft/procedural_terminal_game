"""An item's sprite made into the 3D model the game turns over (model3d.py), straight from its pixels, with no
Blender. How each item is made is listed in data/models/ways.toml, a line an item.

The ways, from the most automatic:

    slab    the drawing given depth, every pixel a block (the way Minecraft draws what's in your hand): swords, keys,
            cards, a floppy disk. Its front and back are the drawing as drawn (the back mirrored, as it would be);
            its sides take the colour of the pixel they edge, a shade darker where they turn from the light.
    puffed  the drawing as a relief, thicker toward its middle in steps of a pixel (as pixel art is built in voxels):
            soft, round, lumpy things seen from the side, bread, a skull, a vest, a rubber duck.
    turned  a round thing turned on a lathe from the sprite, row by row (a potion, a pot, a torch), each row as wide
            as drawn and shaded the way that row is drawn: its glint on the left, its colour, its shadow on the right,
            so the light stays put as it turns. Whatever's drawn on its front (a heart) is painted on; its outline
            goes round it, as drawn.
    jar     a glass jar as the sprites draw one, its outline only, pale down its lit side: the lid turned, and what's
            in it floating inside (a fairy, a baby, rubies), each piece turned to face you, at its own depth, so they
            move round each other as the jar turns.
    ring, dice, cheese
            shaped by hand in the sprite's colours, where the sprite can only hint at the shape: a ring that wobbles
            as it turns, two dice with their pips, a cheese wheel with a wedge cut out of it.
    blender made in Blender by its own build script (the Jar o' Light: spikes/goblin3d/build_jar.py "live")

Whichever way, anything small drawn apart from the thing (a sparkle, steam, a speech bubble) stays where it was drawn,
beside it however it's turned, and twinkles as the sprite's frames do. Everything is in the sprite's own colours.

A new item gets its model as it comes into the game: importing it from the Monster & Item Maker (library.apply, which
`ptg import` and the maker's "add it to the game" both use) makes the model of everything it draws, a new item's way
guessed from what it is and how it's drawn (guess: a weapon or a key a slab, a potion turned, a loaf puffed...) and
written into ways.toml, where a better one can be put; one drawn again is made again its own way. A sprite put in by
hand has its model made by `ptg models`, and until then the game makes it as it's wanted (model3d.load), so a thing
with a sprite always turns over. tests/test_model3d.py fails while any item is left without its model.

    uv run ptg models                     # make every model that's missing, or older than its sprite
    uv run ptg models pickle torch        # make these again (after changing their lines in ways.toml)
    uv run ptg models --all               # make every one again (after changing how a way works)
    uv run ptg models --sheet models.png  # every model beside its sprite, to look over

Each writes data/models/<item>.json, which the pack offers to turn over ("t").
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import tomllib
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw

from . import integrity
from .content import ItemDef, load_content

WAYS_FILE = "ways.toml"  # in data/models: how each item's model is made
SIZE = 24  # a sprite's frame
LIGHT, LIT_FROM = (-0.602, 0.501, 0.622), 0.25  # from the top left, as the sprites are lit (and the jar)
APART = 0.3  # a piece drawn apart from the biggest, this much its size or more, is part of the thing; smaller, it's
#              a sparkle, steam or a speech bubble, and stays put


@dataclass
class Making:
    """Where models are being made: the data folder their sprites are read from and they're written to (the game's,
    or a copy an import checks), the names of things not in the game's content yet (a new item being imported), and
    whether they're written at all (else kept: made as the game wants one, model3d.load)."""

    folder: Path
    names: dict
    write: bool = True
    ways: dict = field(default_factory=dict)  # ways decided here, over ways.toml's: a guess, or a slab to fall back on
    made: dict | None = None  # the last model made, as written


NOW = Making(integrity.data_folder(), {})


@contextmanager
def making(folder: Path | None = None, names: dict | None = None, write: bool = True):
    """Make models in this folder (the game's data, unless it says), knowing these names, written or not."""
    global NOW
    before, NOW = NOW, Making(folder or integrity.data_folder(), names or {}, write)
    try:
        yield NOW
    finally:
        NOW = before


def sprite_path(key: str) -> Path:
    return NOW.folder / "sprites" / f"item_{key}.png"


def drawn(key: str) -> bool:
    """Whether the item has a sprite to make a model from."""
    return sprite_path(key).is_file()


def hexed(rgb: tuple) -> str:
    return "#%02x%02x%02x" % rgb[:3]


def bright(rgb: tuple) -> float:
    return 0.3 * rgb[0] + 0.59 * rgb[1] + 0.11 * rgb[2]


def frames(key: str) -> list[Image.Image]:
    sheet = Image.open(sprite_path(key)).convert("RGBA")
    return [sheet.crop((SIZE * i, 0, SIZE * (i + 1), SIZE)) for i in range(max(1, sheet.width // SIZE))]


def pixels(image: Image.Image) -> dict[tuple[int, int], tuple]:
    return {(x, y): image.getpixel((x, y))[:3] for y in range(SIZE) for x in range(SIZE)
            if image.getpixel((x, y))[3] >= 128}


def outline_of(drawn: dict) -> tuple:
    """The colour its edge is drawn in: the commonest among the pixels with nothing beside them."""
    edge = Counter(c for (x, y), c in drawn.items()
                   if any((x + dx, y + dy) not in drawn for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))))
    return edge.most_common(1)[0][0]


def pieces(drawn: dict) -> list[set]:
    """The drawing's separate pieces (pixels touching, corners too), the biggest first."""
    seen, found = set(), []
    for start in drawn:
        if start in seen:
            continue
        seen.add(start)
        stack, piece = [start], set()
        while stack:
            x, y = stack.pop()
            piece.add((x, y))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    q = (x + dx, y + dy)
                    if q in drawn and q not in seen:
                        seen.add(q)
                        stack.append(q)
        found.append(piece)
    return sorted(found, key=len, reverse=True)


def split(drawn: dict) -> tuple[dict, set]:
    """The thing itself (its big pieces), and the small things drawn apart from it."""
    found = pieces(drawn)
    kept = set().union(*[p for p in found if len(p) >= APART * len(found[0])])
    return {p: drawn[p] for p in kept}, set(drawn) - kept


def darker(colour: tuple, palette: set, edge: tuple) -> tuple:
    """The sprite's own colour nearest to `colour` in shadow (or its outline, if it has nothing darker)."""
    target = tuple(0.68 * c for c in colour)
    darks = [c for c in palette if bright(c) < 0.9 * bright(colour)]
    return min(darks, key=lambda c: sum((a - b) ** 2 for a, b in zip(c, target))) if darks else edge


class Mesh:
    """Points and faces, each face with its paint: each face round anticlockwise as seen from outside."""

    def __init__(self) -> None:
        self.verts: list[tuple] = []
        self.index: dict[tuple, int] = {}
        self.faces: list[list[int]] = []
        self.paint: list[str] = []

    def face(self, points: list, paint: str) -> None:
        corners = []
        for p in points:
            p = tuple(round(c, 4) for c in p)
            if p not in self.index:
                self.index[p] = len(self.verts)
                self.verts.append(p)
            corners.append(self.index[p])
        self.faces.append(corners)
        self.paint.append(paint)

    def part(self, name: str, **more) -> dict:
        return {"name": name, "verts": self.verts, "faces": self.faces, "paint": self.paint, **more}


class Paints(dict):
    def flat(self, colour: tuple) -> str:
        name = hexed(colour)
        self[name] = {"lit": name, "shade": name, "rule": "flat"}
        return name

    def lit(self, name: str, lit: tuple, shade: tuple, glint: tuple | None = None, glint_from: float = 0.76) -> str:
        self[name] = {"lit": hexed(lit), "shade": hexed(shade), "rule": "light",
                      **({"glint": hexed(glint), "glint_from": glint_from} if glint else {})}
        return name


def sparkles(strip: list[Image.Image], centre_x: float) -> list[dict]:
    """The small things drawn apart from the thing, frame by frame, to stay where they were drawn."""
    shown = []
    for image in strip:
        drawn = pixels(image)
        _, apart = split(drawn)
        shown.append([[x - centre_x, SIZE - y, hexed(drawn[(x, y)])] for x, y in sorted(apart)])
    return [{"name": "sparkle", "overlay": shown, "hold": 12}] if any(shown) else []


def save(key: str, parts: list, paints: Paints, centre: tuple, span: float, pitch: float, count: int = 1,
         outline: dict | None = None) -> dict:
    drawn_from = stamp(key)
    name = NOW.names.get(key) or load_content().item(key).name
    model = {"name": name, "made": way_of(key),
             "sprite": drawn_from,  # (a redrawn sprite: make it again)
             "frames": count, "fps": 24, "span": round(span, 2),
             "pitch": pitch, "centre": [round(c, 3) for c in centre], "light": LIGHT, "lit_from": LIT_FROM,
             **({"outline": outline} if outline else {}), "paints": dict(paints), "parts": parts}
    NOW.made = model
    faces = sum(len(p.get("faces", [])) for p in parts)
    if not NOW.write:
        return {"faces": faces}
    path = NOW.folder / "models" / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model, separators=(",", ":")))
    return {"kb": round(path.stat().st_size / 1024, 1), "faces": faces}


def stamp(key: str) -> str:
    """The sprite a model is made from, as a stamp of its file: a redrawn one gets its model made again."""
    return hashlib.sha1(sprite_path(key).read_bytes()).hexdigest()[:12]


def framing(drawn: dict | set, extra: float = 9) -> tuple[tuple, float]:
    """What it turns about (the middle of what's drawn) and how much of the model the picture shows."""
    xs, ys = [x for x, _ in drawn], [y for _, y in drawn]
    centre = ((min(xs) + max(xs) + 1) / 2 - SIZE / 2, SIZE - (min(ys) + max(ys) + 1) / 2, 0.0)
    return centre, max(max(xs) - min(xs), max(ys) - min(ys)) + extra


# -- a slab, or a relief -------------------------------------------------------------------------------------------

def depth_map(drawn: dict, puffed: bool, thick: float) -> dict:
    """How far each pixel stands out in front (and behind): all the same for a slab; for a relief, more the further
    it is from the edge, in steps."""
    if not puffed:
        return {p: thick / 2 for p in drawn}
    far, edge = {}, [p for p in drawn if any((p[0] + dx, p[1] + dy) not in drawn
                                             for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))]
    for p in edge:
        far[p] = 1
    frontier = edge
    while frontier:
        nxt = []
        for x, y in frontier:
            for q in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if q in drawn and q not in far:
                    far[q] = far[(x, y)] + 1
                    nxt.append(q)
        frontier = nxt
    most = thick / 2 + 1.5
    return {p: min(most, 0.6 + 0.5 * (far[p] - 1)) for p in drawn}


def relief(key: str, puffed: bool = False, thick: float = 2.0, pitch: float = 10, **_) -> dict:
    strip = frames(key)
    whole = pixels(strip[0])
    drawn, _ = split(whole)
    edge = outline_of(whole)
    palette = set(whole.values())
    depth = depth_map(drawn, puffed, thick)
    mesh, paints = Mesh(), Paints()

    def at(x: float, y: float, z: float) -> tuple:  # a corner of the sprite's pixels (y down) in the model (y up)
        return x - SIZE / 2, SIZE - y, z

    for y in range(SIZE):  # its front and back: each row's runs of one colour, as far out
        x = 0
        while x < SIZE:
            if (x, y) not in drawn:
                x += 1
                continue
            colour, h = drawn[(x, y)], depth[(x, y)]
            end = x + 1
            while drawn.get((end, y)) == colour and depth.get((end, y)) == h:
                end += 1
            paint = paints.flat(colour)
            mesh.face([at(x, y + 1, h), at(end, y + 1, h), at(end, y, h), at(x, y, h)], paint)
            mesh.face([at(x, y, -h), at(end, y, -h), at(end, y + 1, -h), at(x, y + 1, -h)], paint)
            x = end
    def wall(x: int, y: int, way: tuple, low: float, high: float) -> list:
        """A pixel's side facing `way`, from `low` to `high` out, its corners round anticlockwise from outside."""
        return {(-1, 0): [at(x, y + 1, low), at(x, y + 1, high), at(x, y, high), at(x, y, low)],
                (1, 0): [at(x + 1, y + 1, high), at(x + 1, y + 1, low), at(x + 1, y, low), at(x + 1, y, high)],
                (0, -1): [at(x, y, low), at(x, y, high), at(x + 1, y, high), at(x + 1, y, low)],
                (0, 1): [at(x, y + 1, high), at(x, y + 1, low), at(x + 1, y + 1, low), at(x + 1, y + 1, high)]}[way]

    for (x, y), colour in drawn.items():  # its sides: where it has nothing beside it, or something less far out
        h = depth[(x, y)]
        paint = paints.lit(f"side {hexed(colour)}", colour, darker(colour, palette, edge))
        for way in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            beside = depth.get((x + way[0], y + way[1]), 0.0)
            if beside < h:
                mesh.face(wall(x, y, way, beside, h), paint)  # in front
                mesh.face(wall(x, y, way, -h, -beside), paint)  # and behind
    centre, span = framing(whole)
    extra = sparkles(strip, SIZE / 2)
    return save(key, [mesh.part("body"), *extra], paints, centre, span, pitch, 12 * len(strip) if extra else 1)


# -- turned --------------------------------------------------------------------------------------------------------

def bands_of(rows: dict, drawn: dict, edge: tuple, paints: Paints, prefix: str = "") -> tuple[list, float]:
    """A turned thing's bands, row by row: (row, radius, paint, what's drawn on its front by column), and its axis."""
    axis = Counter((min(xs) + max(xs) + 1) / 2 for xs in rows.values()).most_common(1)[0][0]
    bands = []
    for y in sorted(rows):
        left, right = min(rows[y]), max(rows[y])
        line = [drawn.get((x, y), edge) for x in range(left, right + 1)]
        lead = next((i for i, c in enumerate(line) if c != edge), len(line))
        trail = len(line) - next((i for i, c in enumerate(reversed(line)) if c != edge), len(line))
        inside = line[lead:trail]
        radius = max((right + 1 - left) / 2 - 1, 0.5)  # inside its outline, which goes round it
        if not inside:  # a line of outline across it (round a bottle's lip): a dark ring; or its very top or bottom
            if bands and y + 1 in rows:
                bands.append((y, radius, paints.flat(edge), {}))
            continue
        base = Counter(inside).most_common(1)[0][0]
        glint = next((c for c in inside[:2] if c != base and bright(c) > bright(base)), None)
        shade = next((c for c in reversed(inside[-2:]) if c != base and bright(c) < bright(base)), base)
        paint = paints.lit(f"{prefix}row {y}", base, shade, glint)
        drawn_on = {left + lead + i: c for i, c in enumerate(inside)
                    if 2 <= i < len(inside) - 2 and c not in (base, glint, shade)}
        bands.append((y, radius, paint, drawn_on))
    return bands, axis


def lathe(mesh: Mesh, bands: list, axis: float, paints: Paints, sides: int = 48) -> None:
    def at(r: float, a: float, y: float) -> tuple:  # r out from its axis, a round from its front, at height y
        return r * math.sin(a), y, r * math.cos(a)

    angles = [2 * math.pi * k / sides for k in range(sides + 1)]
    for n, (y, r, paint, drawn_on) in enumerate(bands):
        top, bottom = SIZE - y, SIZE - y - 1
        for a0, a1 in zip(angles, angles[1:]):
            middle = (a0 + a1) / 2
            column = math.floor(axis + r * math.sin(middle))
            here = paints.flat(drawn_on[column]) if math.cos(middle) > 0.25 and column in drawn_on else paint
            mesh.face([at(r, a0, top), at(r, a0, bottom), at(r, a1, bottom), at(r, a1, top)], here)
        above = bands[n - 1] if n and bands[n - 1][0] == y - 1 else None
        below = bands[n + 1] if n + 1 < len(bands) and bands[n + 1][0] == y + 1 else None
        for a0, a1 in zip(angles, angles[1:]):
            if above is None:  # its top
                mesh.face([at(0, a0, top), at(r, a0, top), at(r, a1, top)], paint)
            elif above[1] < r:  # a ledge, looking up, where it's wider than the row above
                mesh.face([at(above[1], a0, top), at(r, a0, top), at(r, a1, top), at(above[1], a1, top)], paint)
            if below is None:  # its bottom
                mesh.face([at(0, a0, bottom), at(r, a1, bottom), at(r, a0, bottom)], paint)
            elif below[1] < r:  # a ledge, looking down, where it's wider than the row below
                mesh.face([at(below[1], a1, bottom), at(r, a1, bottom), at(r, a0, bottom), at(below[1], a0, bottom)],
                          paint)


def turned(key: str, pitch: float = 12, **_) -> dict:
    strip = frames(key)
    whole = pixels(strip[0])
    edge = outline_of(whole)
    body = pieces(whole)[0]
    rows: dict[int, list[int]] = {}
    for x, y in body:
        rows.setdefault(y, []).append(x)
    mesh, paints = Mesh(), Paints()
    bands, axis = bands_of(rows, whole, edge, paints)
    lathe(mesh, bands, axis, paints)
    shown = []  # everything but the body stays where it was drawn
    for image in strip:
        drawn = pixels(image)
        apart = set(drawn) - pieces(drawn)[0]
        shown.append([[x - axis, SIZE - y, hexed(drawn[(x, y)])] for x, y in sorted(apart)])
    extra = [{"name": "sparkle", "overlay": shown, "hold": 12}] if any(shown) else []
    ys = sorted(rows)
    widest = max(r for _, r, _, _ in bands)
    centre = (0.0, SIZE - (ys[0] + ys[-1] + 1) / 2, 0.0)
    span = max(2 * widest + 2, ys[-1] - ys[0] + 1) + 9
    return save(key, [mesh.part("body", edge=hexed(edge)), *extra], paints, centre, span, pitch,
                12 * len(strip) if extra else 1)


# -- a jar -----------------------------------------------------------------------------------------------------------

def jar(key: str, pitch: float = 8, **_) -> dict:
    """The glass is the colours its sides are drawn in, from each edge in; the rows above the glass are its lid; what's
    between its sides is what's in it."""
    strip = frames(key)
    whole = pixels(strip[0])
    rows: dict[int, list[int]] = {}
    for x, y in whole:
        rows.setdefault(y, []).append(x)
    low = [y for y in rows if y > SIZE // 2]
    glass_colours = {whole[(min(rows[y]), y)] for y in low} | {whole[(max(rows[y]), y)] for y in low}
    first = min(y for y in rows if whole[(min(rows[y]), y)] in glass_colours)
    glass, inside = {}, {}
    for y in sorted(rows):
        if y < first:
            continue
        left, right = min(rows[y]), max(rows[y])
        x = left
        while (x, y) in whole and whole[(x, y)] in glass_colours:
            glass[(x, y)] = whole[(x, y)]
            x += 1
        x2 = right
        while (x2, y) in whole and whole[(x2, y)] in glass_colours and x2 >= x:
            glass[(x2, y)] = whole[(x2, y)]
            x2 -= 1
        for xi in range(x, x2 + 1):
            if (xi, y) in whole:
                inside[(xi, y)] = whole[(xi, y)]
    lid = {p: c for p, c in whole.items() if p[1] < first}
    left_side = Counter(whole[(min(rows[y]), y)] for y in rows if first <= y < first + 8)
    right_side = Counter(whole[(max(rows[y]), y)] for y in rows if y >= first)
    mesh, paints = Mesh(), Paints()

    lid_rows: dict[int, list[int]] = {}
    for x, y in lid:
        lid_rows.setdefault(y, []).append(x)
    glass_rows = {y: [min(rows[y]), max(rows[y])] for y in rows if y >= first}
    axis = Counter((xs[0] + xs[1] + 1) / 2 for xs in glass_rows.values()).most_common(1)[0][0]
    if lid_rows:
        lid_bands = []
        for y in sorted(lid_rows):  # the lid has no outline drawn round it: it's turned as wide as drawn
            line = [lid[(x, y)] for x in sorted(lid_rows[y])]
            base = Counter(line).most_common(1)[0][0]
            ends = [c for c in (line[0], line[-1]) if c != base]
            shade = ends[0] if ends else base
            lid_bands.append((y, (max(lid_rows[y]) + 1 - min(lid_rows[y])) / 2,
                              paints.lit(f"lid {y}", base, shade), {}))
        lathe(mesh, lid_bands, axis, paints)
    shell = Mesh()  # the glass, for its outline: inside the outline drawn round it
    clear = paints.flat(right_side.most_common(1)[0][0])  # (never drawn: the glass is only its outline)
    lathe(shell, [(y, max((xs[1] + 1 - xs[0]) / 2 - 1, 0.5), clear, {}) for y, xs in sorted(glass_rows.items())],
          axis, paints)
    parts = [mesh.part("lid"), shell.part("glass", outline=True)]
    for n, piece in enumerate(pieces(inside)):  # what's in it, each piece facing you, somewhere inside
        cx = (min(x for x, _ in piece) + max(x for x, _ in piece) + 1) / 2
        cy = (min(y for _, y in piece) + max(y for _, y in piece) + 1) / 2
        half = (max(x for x, _ in piece) + 1 - min(x for x, _ in piece)) / 2
        left, right = glass_rows.get(int(cy), [axis - 4, axis + 3])
        inner = (right + 1 - left) / 2 - 1.5  # how far in from the glass it can float
        room = max(0.0, (inner - half) ** 2 - (cx - axis) ** 2) if inner > half else 0.0
        z = math.sqrt(room) * math.sin(2.4 * n + 1.0) * 0.8 if len(piece) < 40 else 0.0
        bit = Mesh()
        for (x, y) in piece:
            colour = paints.flat(inside[(x, y)])
            x0, x1, y0, y1 = x - cx, x + 1 - cx, cy - y, cy - y - 1
            bit.face([(x0, y1, 0.4), (x1, y1, 0.4), (x1, y0, 0.4), (x0, y0, 0.4)], colour)
            bit.face([(x0, y0, -0.4), (x1, y0, -0.4), (x1, y1, -0.4), (x0, y1, -0.4)], colour)
        parts.append(bit.part(f"inside {n}", billboard=True, at=[cx - axis, SIZE - cy, round(z, 3)]))
    ys = sorted(rows)
    centre = (0.0, SIZE - (ys[0] + ys[-1] + 1) / 2, 0.0)
    span = max(max(xs[1] - xs[0] for xs in glass_rows.values()), ys[-1] - ys[0]) + 9
    outline = {"lit": hexed(left_side.most_common(1)[0][0]), "shade": hexed(right_side.most_common(1)[0][0]),
               "upper": 0.62}
    return save(key, parts, paints, centre, span, pitch, outline=outline)


# -- by hand ---------------------------------------------------------------------------------------------------------

def cheese(key: str = "cheese_wheel", pitch: float = 28, **_) -> dict:
    """A squat wheel, its top yellow with an orange rim, its rind orange, and a wedge cut out of it at the front on
    the right, as drawn: the cut faces pale, with holes in them."""
    top, rim, rind = (254, 231, 97), (254, 174, 52), (247, 118, 34)
    cut, cut_shade, hole, edge = (234, 212, 170), (228, 166, 114), (194, 133, 105), (24, 20, 37)
    radius, height, inner = 10.0, 6.0, 8.6
    start, stop = math.radians(75), math.radians(15 + 360)  # what's left of it: the wedge from 15 to 75 is gone
    steps = 40
    mesh, paints = Mesh(), Paints()

    def at(r: float, a: float, y: float) -> tuple:
        return r * math.sin(a), y, r * math.cos(a)

    angles = [start + (stop - start) * i / steps for i in range(steps + 1)]
    for a0, a1 in zip(angles, angles[1:]):
        mesh.face([at(radius, a0, height), at(radius, a0, 0), at(radius, a1, 0), at(radius, a1, height)],
                  paints.lit("rind", rim, rind))
        mesh.face([at(0, a0, height), at(inner, a0, height), at(inner, a1, height)], paints.lit("top", top, rim))
        mesh.face([at(inner, a0, height), at(radius, a0, height), at(radius, a1, height), at(inner, a1, height)],
                  paints.lit("rim", rim, rind))
        mesh.face([at(0, a0, 0), at(radius, a1, 0), at(radius, a0, 0)], paints.lit("rind", rim, rind))
    holes = {start: [(0.55, 0.55), (0.82, 0.2), (0.25, 0.3)], stop: [(0.4, 0.6), (0.7, 0.35), (0.9, 0.75)]}
    across, up = 8, 4
    for a, flip in ((start, False), (stop, True)):  # the two cut faces, in cells, some of them holes
        for i in range(across):
            for j in range(up):
                r0, r1 = radius * i / across, radius * (i + 1) / across
                y0, y1 = height * j / up, height * (j + 1) / up
                is_hole = any(r0 <= fr * radius < r1 and y0 <= fy * height < y1 for fr, fy in holes[a])
                paint = paints.flat(hole) if is_hole else paints.lit("cut", cut, cut_shade)
                corners = [at(r0, a, y0), at(r1, a, y0), at(r1, a, y1), at(r0, a, y1)]
                mesh.face(corners[::-1] if flip else corners, paint)
    return save(key, [mesh.part("body", edge=hexed(edge))], paints, (0.0, height / 2, 0.0), 2 * radius + 8, pitch)


def turn_about(points: list, x_turn: float, y_turn: float) -> list:
    """Points tipped `x_turn` degrees about the x axis (top toward you), then turned `y_turn` about the upright."""
    ax, ay = math.radians(x_turn), math.radians(y_turn)
    out = []
    for x, y, z in points:
        y, z = y * math.cos(ax) - z * math.sin(ax), y * math.sin(ax) + z * math.cos(ax)
        x, z = x * math.cos(ay) + z * math.sin(ay), -x * math.sin(ay) + z * math.cos(ay)
        out.append((x, y, z))
    return out


def ring(key: str = "a_ring_probably_importan", pitch: float = 10, **_) -> dict:
    """A gold ring with a little red stone, lying tipped toward you, as drawn: it wobbles like a dropped coin as it
    turns."""
    gold, gold_shade, glint, stone, stone_shade = (254, 231, 97), (247, 118, 34), (255, 255, 255), (255, 0, 68), \
        (228, 59, 68)
    edge = (24, 20, 37)
    big, small, around, across = 7.0, 1.6, 40, 10
    mesh, paints = Mesh(), Paints()
    band = paints.lit("gold", gold, gold_shade, glint, glint_from=0.9)

    middle = (0.0, 11.5, 0.0)  # where it's drawn

    def point(u: float, v: float) -> tuple:
        r = big + small * math.cos(v)
        x, y, z = turn_about([(r * math.sin(u), small * math.sin(v), r * math.cos(u))], 45, 0)[0]
        return x + middle[0], y + middle[1], z + middle[2]

    for i in range(around):
        u0, u1 = 2 * math.pi * i / around, 2 * math.pi * (i + 1) / around
        for j in range(across):
            v0, v1 = 2 * math.pi * j / across, 2 * math.pi * (j + 1) / across
            mesh.face([point(u0, v0), point(u1, v0), point(u1, v1), point(u0, v1)], band)
    # the stone: a little block on the ring's outside, at its front
    cx, cy, cz = (a + b for a, b in zip(turn_about([(0.0, 0.0, big + small + 0.6)], 45, 0)[0], middle))
    s = 0.9
    corners = [(cx + dx * s, cy + dy * s, cz + dz * s) for dx in (-1, 1) for dy in (-1, 1) for dz in (-1, 1)]
    paint = paints.lit("stone", stone, stone_shade)
    for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
        mesh.face([corners[i] for i in face], paint)
    whole = pixels(frames(key)[0])
    extra = sparkles(frames(key), SIZE / 2)
    centre, span = framing(whole)
    return save(key, [mesh.part("body", edge=hexed(edge)), *extra], paints, centre, span, pitch,
                12 * len(frames(key)) if extra else 1)


PIPS = {1: [(4, 4)], 2: [(1, 1), (7, 7)], 3: [(1, 1), (4, 4), (7, 7)], 4: [(1, 1), (7, 1), (1, 7), (7, 7)],
        5: [(1, 1), (7, 1), (4, 4), (1, 7), (7, 7)], 6: [(1, 1), (1, 4), (1, 7), (7, 1), (7, 4), (7, 7)]}


def dice(key: str = "weighted_dice", pitch: float = 18, **_) -> dict:
    """Two dice, cream with black pips, every face numbered as a die's is (opposite faces add up to seven): the big
    one showing six, the small one behind it three, as drawn."""
    face_colour, face_shade, pip, edge = (234, 212, 170), (228, 166, 114), (24, 20, 37), (24, 20, 37)
    mesh, paints = Mesh(), Paints()
    cream, black = paints.lit("face", face_colour, face_shade), paints.flat(pip)

    def die(middle: tuple, size: float, turn: float, faces: dict) -> None:
        """faces: front, back, left, right, top, bottom -> the number on it."""
        cell = size / 9
        h = size / 2
        frames_of = {  # each face: its corner, and the two directions across it (anticlockwise, seen from outside)
            "front": ((-h, -h, h), (cell, 0, 0), (0, cell, 0)), "back": ((h, -h, -h), (-cell, 0, 0), (0, cell, 0)),
            "left": ((-h, -h, -h), (0, 0, cell), (0, cell, 0)), "right": ((h, -h, h), (0, 0, -cell), (0, cell, 0)),
            "top": ((-h, h, h), (cell, 0, 0), (0, 0, -cell)), "bottom": ((-h, -h, -h), (cell, 0, 0), (0, 0, cell)),
        }
        for name, (corner, across, up) in frames_of.items():
            dots = set(PIPS[faces[name]])
            for i in range(9):
                for j in range(9):
                    quad = [tuple(corner[k] + across[k] * a + up[k] * b for k in range(3))
                            for a, b in ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))]
                    quad = [(x + middle[0], y + middle[1], z + middle[2])
                            for x, y, z in turn_about([(x, y, z) for x, y, z in quad], 0, turn)]
                    mesh.face(quad, black if (i, 8 - j) in dots else cream)

    die((-3.5, 8.5, 1.5), 9.5, 12, {"front": 6, "back": 1, "left": 4, "right": 3, "top": 5, "bottom": 2})
    die((5.0, 16.0, -3.0), 8.5, -28, {"front": 3, "back": 4, "left": 2, "right": 5, "top": 1, "bottom": 6})
    extra = sparkles(frames(key), SIZE / 2)
    centre, span = framing(pixels(frames(key)[0]))
    return save(key, [mesh.part("body", edge=hexed(edge)), *extra], paints, centre, span + 2, pitch,
                12 * len(frames(key)) if extra else 1)


WAYS = {"slab": lambda key, **o: relief(key, puffed=False, **o), "puffed": lambda key, **o: relief(key, puffed=True, **o),
        "turned": turned, "jar": jar, "cheese": cheese, "ring": ring, "dice": dice}


def catalogue() -> dict:
    """How each item is made: its way, and anything else it says (a slab's thickness, how far it's looked down at)."""
    path = NOW.folder / "models" / WAYS_FILE
    listed = tomllib.loads(path.read_text()) if path.is_file() else {}
    return {key: ({"way": entry} if isinstance(entry, str) else dict(entry)) for key, entry in listed.items()}


def way_of(key: str) -> str:
    return NOW.ways.get(key) or (catalogue().get(key) or {"way": "slab"})["way"]


def make(key: str) -> dict:
    """Its model, made its way (ways.toml), into the folder being made in. A way that can't be made from its drawing
    (a turned thing drawn as a square) falls back on a slab, which can always be made, and says so."""
    entry = dict(catalogue().get(key) or {})
    entry.pop("way", None)
    way = way_of(key)
    if way == "blender":
        return {"skipped": "made in Blender (see its build script)"}
    try:
        return WAYS[way](key, **entry)
    except (ValueError, IndexError, KeyError, ZeroDivisionError):
        if way == "slab":
            raise
        NOW.ways[key] = "slab"
        return {**WAYS["slab"](key), "fell_back": f"{way} didn't fit its drawing"}


def build(key: str) -> dict | None:
    """Its model, made as it's wanted and kept, not written (model3d.load: a sprite with no model, or a newer one): its
    way, or a guess at one. None for one made in Blender, or no sprite."""
    content = load_content()
    if not drawn(key) or way_of(key) == "blender" or key not in content.items:
        return None
    with making(NOW.folder, NOW.names, write=False) as now:
        if key not in catalogue():
            now.ways[key] = guess(content.item(key), frames(key)[0])
        make(key)
        return now.made


# -- a new item's way ------------------------------------------------------------------------------------------------

TURNED = {"potion", "flask", "bottle", "vial", "bomb", "pot", "stewpot", "torch", "hat", "helmet", "urn", "cup",
          "goblet", "lantern", "candle", "bell", "barrel", "water", "pure"}  # names of round, upright things
SOFT = {"food", "cloth", "leather", "smelly", "sticky", "meat", "buttery", "flappy", "fur", "plush"}  # tags
SOFT_NAMES = {"rubber", "plush", "bread", "loaf", "cake", "pie", "egg", "skull", "duck", "chicken", "fish"}
FLAT_NAMES = {"key", "card", "cards", "book", "scroll", "map", "letter", "page", "disk", "coin"}


def guess(item: ItemDef, frame: Image.Image) -> str:
    """A new item's way, from what it is and how it's drawn (the first frame of its sprite): a glass jar with
    something in it, a jar; a round, upright thing drawn symmetrical (a potion, a pot, a bomb), turned; a key, a
    page, a blade, or anything drawn as a flat rectangle (a book, a card, a chip), a slab; armor, food and soft
    things, puffed; else a thin drawing a slab and a full one puffed. It picks what was picked by hand for nine
    items in ten (tests/test_model3d.py): a better way goes in its line in ways.toml, and `ptg models <item>`."""
    tags, words = set(item.tags), set(item.name.lower().replace("'", " ").replace("-", " ").split())
    body, _ = split(pixels(frame))
    if not body:
        return "slab"
    xs, ys = [x for x, _ in body], [y for _, y in body]
    fill = len(body) / ((max(xs) - min(xs) + 1) * (max(ys) - min(ys) + 1))
    middle = (min(xs) + max(xs)) / 2
    mirrored = {(round(2 * middle - x), y) for x, y in body}
    symmetric = len(set(body) & mirrored) / len(set(body) | mirrored)
    if "jar" in words or ("bottle" in words and "liquid" not in tags):
        return "jar"
    if symmetric >= 0.75 and (tags & {"liquid", "glass", "pot"} or words & TURNED):
        return "turned"
    if words & SOFT_NAMES:
        return "puffed"
    if item.kind == "key" or "paper" in tags or words & FLAT_NAMES:
        return "slab"
    if item.kind == "weapon" and (fill < 0.45 or {"sharp", "metal"} <= tags):
        return "slab"
    if fill >= 0.7 and symmetric >= 0.75 and item.kind == "trinket" and not tags & SOFT:
        return "slab"  # (a flat rectangle: a book, a card, a disk, a sheet, a chip)
    if item.kind == "armor" or tags & SOFT:
        return "puffed"
    return "slab" if fill < 0.42 else "puffed"


def listed_as(key: str, way: str) -> None:
    """Its line in ways.toml, for a new item: its way, guessed (an item listed already keeps its own)."""
    path = NOW.folder / "models" / WAYS_FILE
    text = path.read_text() if path.is_file() else ""
    if key in tomllib.loads(text):
        return
    note = f"  # (guessed as it came in: change it, then ptg models {key})"
    path.write_text(text.rstrip("\n") + f'\n{key} = "{way}"{note}\n')


def wanted(keys: list[str] | None = None) -> list[str]:
    """The items whose models are missing or older than their sprites (of these, or of every item with a sprite):
    what `ptg models` makes."""
    content = load_content() if NOW.folder == integrity.data_folder() else None
    candidates = keys if keys is not None else sorted(
        p.name[len("item_"):-len(".png")] for p in (NOW.folder / "sprites").glob("item_*.png"))
    out = []
    for key in candidates:
        if not drawn(key) or way_of(key) == "blender" or (content is not None and key not in content.items):
            continue
        path = NOW.folder / "models" / f"{key}.json"
        if not path.is_file() or json.loads(path.read_text()).get("sprite") != stamp(key):
            out.append(key)
    return out


def settle(items: list[tuple[ItemDef, Image.Image]], folder: Path | None = None, dry_run: bool = False) -> list[str]:
    """The models of items just drawn (an import's: each item, and the first frame of its new sprite), made: a new
    item's way guessed and written into ways.toml first. What came of each, in a line, for the import to say."""
    said = []
    with making(folder, {item.key: item.name for item, _ in items}):
        listed = catalogue()
        for item, frame in items:
            key = item.key
            if key in listed and (listed[key]["way"] == "blender" or (not dry_run and not wanted([key]))):
                continue  # (made in Blender; or made from this very sprite already: nothing to say)
            way = listed[key]["way"] if key in listed else guess(item, frame)
            if key not in listed and not dry_run:
                listed_as(key, way)
            guessed = "" if key in listed else f" (a guess: change its line in models/{WAYS_FILE})"
            if dry_run:
                said.append(f"Would make {item.name}'s 3D model: {_a(way)}{guessed}.")
                continue
            fell = make(key).get("fell_back")
            said.append(f"Made {item.name}'s 3D model: {_a(way_of(key))}{f' ({fell})' if fell else guessed}.")
    return said


def _a(way: str) -> str:
    said = {"slab": "a slab", "puffed": "puffed", "turned": "turned", "jar": "a jar"}
    return said.get(way, f"shaped by hand ({way})")


def sheet(path: Path, turns: tuple = (0, 50, 130)) -> None:
    """Every model beside its sprite, from a few sides, to look over."""
    from . import model3d

    keys = sorted(k for k in catalogue() if model3d.available(k))
    cell, label = 72, 12
    per_row = 3
    width = per_row * (cell * (len(turns) + 1) + 12)
    rows = -(-len(keys) // per_row)
    out = Image.new("RGBA", (width, rows * (cell + label)), (40, 40, 52, 255))
    draw = ImageDraw.Draw(out)
    for n, key in enumerate(keys):
        x0, y0 = (n % per_row) * (cell * (len(turns) + 1) + 12), (n // per_row) * (cell + label)
        sprite = frames(key)[0].resize((cell, cell), Image.NEAREST)
        out.alpha_composite(sprite, (x0, y0))
        model = model3d.load(key)
        for i, yaw in enumerate(turns, 1):
            out.alpha_composite(model3d.render(model, 0, yaw, size=cell), (x0 + i * cell, y0))
        draw.text((x0 + 2, y0 + cell), f"{key[:28]} ({catalogue()[key]['way']})", fill=(210, 210, 220, 255))
    out.save(path)
    print(f"-> {path} ({len(keys)} models)")


def main(argv: list[str]) -> int:
    """`ptg models`: see the module's docstring."""
    if argv[:1] == ["--sheet"]:
        sheet(Path(argv[1]) if len(argv) > 1 else Path("models.png"))
        return 0
    if argv == ["--all"]:
        keys = [k for k in catalogue() if way_of(k) != "blender" and drawn(k)]
    else:
        keys = argv or wanted()
    if not keys:
        print("Every item with a sprite has its model, made from its sprite as it's drawn now.")
        return 0
    content = load_content()
    for key in keys:
        if key not in content.items or not drawn(key):
            print(f"{key:28} no such item with a sprite")
            continue
        if key not in catalogue():
            listed_as(key, guess(content.item(key), frames(key)[0]))
        print(f"{key:28} {way_of(key):8} {make(key)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
