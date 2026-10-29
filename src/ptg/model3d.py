"""3D models drawn as you watch: a thing you can pick up and turn over (every item with a sprite has one).

A model is the flat faces of a thing, made from its sprite (spikes/goblin3d/item_model.py) or in Blender (the Jar o'
Light: build_jar.py's "live" step), kept in ptg/data/models/<key>.json with any animation baked a frame at a time. render() draws it into pixels from any angle,
with no graphics card and no image protocol: each face is turned and tipped to the view, lit or shaded in the sprite's
own two colours for it (as the bosses' frames are), and the faces are painted from the farthest to the nearest. The
pixels are shown in half blocks like any sprite (sprites.image_text), so it works wherever the game does, a browser too.

Its paints say how each face is lit:

    light   its lit colour where it faces the light (from the top left, as the sprites are), else its shade; and a
            glint where it faces the light squarely (more than `glint_from`), if it has one: a round thing shaded
            the way a sprite shades it, highlight, colour and shadow
    facing  lit where it faces you, or up (more square-on than `square`), shaded as it turns away: a lid's rim
    flat    its own colour from every side: things that glow, and pixel art given depth

A part is a solid shape (points, faces, each face's paint) or a spark (a point of light that flashes: its size, a frame
at a time, 0 out), and may move ("path": where it is, a frame at a time), beat ("scales": how it's stretched), hang off
another part ("parent", at "at"), or always face you ("billboard": a bug whose wings stay either side of it, as drawn,
whichever way you turn the jar). A see-through part ("outline": glass) is only drawn as an outline round it, as
thick as a pixel of the sprite, pale on its lit side and dark on the other, the way the sprite draws its glass; a solid
one may have an outline round it too ("edge": its colour), as a sprite has. And an "overlay" isn't turned at all: a few
of the sprite's pixels that stay where they were drawn (a sparkle beside a potion), a frame of them at a time.

    uv run python -m ptg.model3d jar_o_light       # how long a frame takes, and a few saved to look at
"""

from __future__ import annotations

import json
import math
import sys
import time
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

from PIL import Image, ImageChops, ImageDraw

FOLDER = "models"  # in ptg/data


def rgba(hex_colour: str) -> tuple[int, int, int, int]:
    return int(hex_colour[1:3], 16), int(hex_colour[3:5], 16), int(hex_colour[5:7], 16), 255


@dataclass
class Paint:
    lit: tuple
    shade: tuple
    rule: str  # light, facing or flat (see the module docstring)
    square: float = 0.0
    glint: tuple | None = None
    glint_from: float = 0.8


@dataclass
class Part:
    name: str
    verts: list  # (x, y, z) in pixels about the part's own middle: x to the right, y up, z toward the front
    faces: list  # each a few indices into verts, round it anticlockwise as seen from outside
    paints: list  # each face's paint, an index into Model.paints
    outline: bool = False
    billboard: bool = False
    parent: str = ""
    at: tuple = (0.0, 0.0, 0.0)
    path: list | None = None  # where it is, a frame at a time (else at `at`)
    scales: list | None = None  # how it's stretched, a frame at a time
    spark: bool = False
    sizes: list | None = None  # a spark's size, a frame at a time
    paint: int = 0  # a spark's paint
    edge: tuple | None = None  # an outline round it, this colour
    overlay: list | None = None  # pixels that stay put, (x, y, colour) a frame at a time: x right, y up, top left
    hold: int = 1  # frames an overlay's each frame is shown for


@dataclass
class Model:
    name: str
    frames: int
    fps: int
    span: float  # how many pixels of the model fit across the picture at zoom 1
    pitch: float  # how far down it's looked at, in degrees, to begin with
    centre: tuple  # the point it turns about, in the middle of the picture
    light: tuple  # toward the light, as seen (x right, y up, z toward you)
    lit_from: float  # how square-on to the light a face must be to be lit
    outline: dict  # an outline's colours, lit and shade, and how far down the lit side goes ("upper")
    paints: list
    parts: list


def path_of(key: str):
    return resources.files("ptg") / "data" / FOLDER / f"{key}.json"


def available(key: str) -> bool:
    """Whether there's a model of this thing to turn over."""
    return path_of(key).is_file()


@lru_cache(maxsize=8)
def load(key: str) -> Model:
    data = json.loads(path_of(key).read_text())
    names = list(data["paints"])
    paints = [Paint(rgba(p["lit"]), rgba(p["shade"]), p["rule"], p.get("square", 0.0),
                    rgba(p["glint"]) if p.get("glint") else None, p.get("glint_from", 0.8))
              for p in data["paints"].values()]
    parts = []
    for p in data["parts"]:
        faces = [tuple(f) for f in p.get("faces", [])]
        paint = p.get("paint", [])
        parts.append(Part(
            name=p["name"], verts=[tuple(v) for v in p.get("verts", [])], faces=faces,
            paints=[names.index(name) for name in paint] if isinstance(paint, list) else [],
            outline=p.get("outline", False), billboard=p.get("billboard", False), parent=p.get("parent", ""),
            at=tuple(p.get("at", (0.0, 0.0, 0.0))), path=p.get("path"), scales=p.get("scales"),
            spark=p.get("spark", False), sizes=p.get("sizes"),
            paint=names.index(paint) if isinstance(paint, str) else 0,
            edge=rgba(p["edge"]) if p.get("edge") else None,
            overlay=[[(x, y, rgba(c)) for x, y, c in pixels] for pixels in p["overlay"]] if p.get("overlay") else None,
            hold=p.get("hold", 1)))
    light = data["light"]
    length = math.sqrt(sum(c * c for c in light))
    return Model(name=data["name"], frames=data["frames"], fps=data["fps"], span=data["span"], pitch=data["pitch"],
                 centre=tuple(data["centre"]), light=tuple(c / length for c in light), lit_from=data["lit_from"],
                 outline=data.get("outline", {}), paints=paints, parts=parts)


# -- drawing -------------------------------------------------------------------------------------------------------

def _times(a: tuple, b: tuple) -> tuple:
    """Two 3x3 matrices (rows) multiplied."""
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def _apply(m: tuple, v: tuple) -> tuple:
    return (m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2], m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
            m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2])


def _shifted(mask: Image.Image, dx: int, dy: int) -> Image.Image:
    return ImageChops.offset(mask, dx, dy)


def _grown(mask: Image.Image) -> Image.Image:
    """The mask a pixel bigger all round (to the sides and up and down, not the corners)."""
    out = mask
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        out = ImageChops.lighter(out, _shifted(mask, dx, dy))
    return out


def render(model: Model, frame: int, yaw: float, pitch: float | None = None, size: int = 64,
           zoom: float = 1.0) -> Image.Image:
    """The model at `frame` of its animation, turned `yaw` degrees round (from the front, turning it to show its
    left side), looked at `pitch` degrees from above, `size` pixels square, with a transparent background."""
    pitch = model.pitch if pitch is None else pitch
    a, e = math.radians(yaw), math.radians(pitch)
    ca, sa, ce, se = math.cos(a), math.sin(a), math.cos(e), math.sin(e)
    view = ((ca, 0.0, -sa), (-sa * se, ce, -ca * se), (sa * ce, se, ca * ce))  # turned by -yaw, then tipped
    tipped = ((1.0, 0.0, 0.0), (0.0, ce, -se), (0.0, se, ce))  # the view of a part that turns to face you
    facing_you = ((ca, 0.0, sa), (0.0, 1.0, 0.0), (-sa, 0.0, ca))  # such a part's turn, in the model
    up = (0.0, ce, se)  # which way is up, as seen
    k = size / model.span * zoom
    half = size / 2
    f = frame % model.frames
    cx, cy, cz = model.centre
    lx, ly, lz = model.light
    lit_from = model.lit_from
    paints = model.paints

    still = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    placed: dict[str, tuple] = {}  # where each part is, its turn, and if it faces you: for the parts hanging off it
    shapes = []  # (depth, points, colour, whether they're single pixels), to paint far to near
    glass = []  # the see-through parts' faces seen from the front, for their outline
    edged: dict[tuple, list] = {}  # the solid parts' faces seen from the front, by the colour of the outline round them
    overlays = []
    for part in model.parts:
        if part.overlay:
            overlays.append(part.overlay[(f // part.hold) % len(part.overlay)])
            continue
        if part.parent:
            where, turn, faces = placed[part.parent]
            offset = _apply(turn, part.at)
            where = (where[0] + offset[0], where[1] + offset[1], where[2] + offset[2])
        else:
            where = tuple(part.path[f]) if part.path else part.at
            turn, faces = (facing_you, True) if part.billboard else (still, False)
        placed[part.name] = (where, turn, faces)
        sx_, sy_, sz_ = part.scales[f] if part.scales else (1.0, 1.0, 1.0)
        m = tipped if faces else view
        m = tuple((row[0] * sx_, row[1] * sy_, row[2] * sz_) for row in m)  # stretched first, then turned
        b = _apply(view, (where[0] - cx, where[1] - cy, where[2] - cz))
        if part.spark:
            size_now = part.sizes[f] if part.sizes else 1.0
            if size_now > 0.05:  # a pixel of light, or a cross of them as it flashes
                x, y = round(half + k * b[0]), round(half - k * b[1])
                arm = max(1, round(0.5 * size_now * k - 0.5)) if size_now > 1.1 else 0
                points = [(x, y), *[(x + dx * i, y + dy * i) for i in range(1, arm + 1)
                                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))]]
                shapes.append((b[2], points, paints[part.paint].lit, True))
            continue
        (m00, m01, m02), (m10, m11, m12), (m20, m21, m22) = m
        b0, b1, b2 = b
        seen = [(m00 * x + m01 * y + m02 * z + b0, m10 * x + m11 * y + m12 * z + b1, m20 * x + m21 * y + m22 * z + b2)
                for x, y, z in part.verts]
        screen = [(half + k * vx, half - k * vy) for vx, vy, _ in seen]
        for face, paint_index in zip(part.faces, part.paints or [0] * len(part.faces)):
            p0, p1, p2 = seen[face[0]], seen[face[1]], seen[face[2]]
            if len(face) == 4:  # the cross of its diagonals: right even where an edge has shrunk to nothing
                p3 = seen[face[3]]
                ux, uy, uz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
                vx, vy, vz = p3[0] - p1[0], p3[1] - p1[1], p3[2] - p1[2]
            else:
                ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
                vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
            nz = ux * vy - uy * vx
            if nz <= 0:  # facing away: the near side of the part covers it
                continue
            points = [screen[i] for i in face]
            if part.outline:
                glass.append(points)
                continue
            if part.edge:
                edged.setdefault(part.edge, []).append(points)
            paint = paints[paint_index]
            if paint.rule == "flat":
                colour = paint.lit
            else:
                nx, ny = uy * vz - uz * vy, uz * vx - ux * vz
                length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
                if paint.rule == "light":
                    towards = (nx * lx + ny * ly + nz * lz) / length
                    colour = (paint.glint if paint.glint and towards > paint.glint_from else
                              paint.lit if towards > lit_from else paint.shade)
                else:
                    lit = nz / length > paint.square or (ny * up[1] + nz * up[2]) / length > 0.6
                    colour = paint.lit if lit else paint.shade
            depth = sum(seen[i][2] for i in face) / len(face)
            shapes.append((depth, points, colour, False))

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    width = max(1, round(0.75 * k))  # an outline as thick as a pixel of the sprite, near enough
    if glass:
        _outline(image, glass, model.outline, width)
    for colour, faces in edged.items():
        _outline(image, faces, {"lit": colour, "shade": colour, "upper": 0.0}, width)
    draw = ImageDraw.Draw(image)
    for _, points, colour, pixels in sorted(shapes, key=lambda s: s[0]):
        if pixels:
            draw.point(points, fill=colour)
        else:
            draw.polygon(points, fill=colour)
    for pixels in overlays:  # drawn where they were drawn, however it's turned
        for x, y, colour in pixels:
            left, top = half + k * (x - cx), half - k * (y - cy)
            x0, y0 = round(left), round(top)  # at least a pixel, however small it's drawn
            draw.rectangle((x0, y0, max(x0, round(left + k) - 1), max(y0, round(top + k) - 1)), fill=colour)
    return image


def _outline(image: Image.Image, faces: list, colours: dict, width: int) -> None:
    """A see-through part as the sprite draws its glass: its outline only, `width` pixels round it, in the lit
    colour down its left side as far as `upper` of the way down it, and the shade colour elsewhere."""
    mask = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(mask)
    for points in faces:
        draw.polygon(points, fill=255)
    box = mask.getbbox()
    if not box:
        return
    grown = mask
    for _ in range(width):
        grown = _grown(grown)
    ring = ImageChops.subtract(grown, mask)
    left, top, right, bottom = box
    lit_side = Image.new("L", image.size, 0)
    ImageDraw.Draw(lit_side).rectangle((0, 0, (left + right) / 2, top + colours["upper"] * (bottom - top)), fill=255)
    lit, shade = (rgba(c) if isinstance(c, str) else c for c in (colours["lit"], colours["shade"]))
    image.paste(shade, mask=ring)
    image.paste(lit, mask=ImageChops.multiply(ring, lit_side))


# -- trying it -----------------------------------------------------------------------------------------------------

def main(key: str = "jar_o_light", size: str = "64") -> None:
    model = load(key)
    n = int(size)
    started = time.perf_counter()
    count = 96
    for i in range(count):
        render(model, i, yaw=i * 7.5, size=n)
    each = (time.perf_counter() - started) / count
    print(f"{model.name}: {sum(len(p.faces) for p in model.parts)} faces, {n}x{n} pixels: "
          f"{each * 1000:.1f} ms a frame ({1 / each:.0f} a second)")
    sheet = Image.new("RGBA", (n * 4, n), (70, 70, 80, 255))
    for i, yaw in enumerate((0, 45, 90, 180)):
        sheet.alpha_composite(render(model, i * 12, yaw, size=n), (i * n, 0))
    sheet.save(f"{key}_turning.png")
    print(f"-> {key}_turning.png")


if __name__ == "__main__":
    main(*sys.argv[1:])
