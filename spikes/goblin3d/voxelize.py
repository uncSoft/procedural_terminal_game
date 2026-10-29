"""Spike: the goblin sprite made solid, ready for Blender.

Reads the first frame of goblin.png and builds it out of cubes, one per pixel, puffed out front and back: the head
is a dome, the tunic a barrel, the arms, legs and ears thin. The dark outline is left off (a sprite tool draws its
own around the render) and the face is drawn on the front only, with the part's own colour behind it, so the back of
the head is plain green. Each part hangs from a pivot (neck, shoulders, hips) so Blender can swing it.

    uv run python spikes/goblin3d/voxelize.py      # writes spikes/goblin3d/goblin_voxels.json

build_goblin.py, run inside Blender, turns the JSON into a rigged, animated model.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
SPRITE = HERE.parents[1] / "src" / "ptg" / "data" / "sprites" / "goblin.png"
SIZE = 24
OUTLINE = (24, 20, 37)

# Every part: what it hangs from, where its pivot is (in pixels, from the sprite's top left corner), the colour behind
# its front face, and how it's puffed out. "dome" rounds both ways (a head), "barrel" rounds side to side (a body),
# "slab" is a fixed thickness; depth is how many cubes it reaches out in front of its middle (and behind).
PARTS = {
    "root":  {"parent": None,    "pivot": (12, 23)},
    "torso": {"parent": "root",  "pivot": (12, 20),   "base": (184, 111, 80), "shape": "barrel", "depth": 4},
    "head":  {"parent": "torso", "pivot": (12, 14),   "base": (99, 199, 77),  "shape": "dome",   "depth": 6},
    "ear_l": {"parent": "head",  "pivot": (6, 6.5),   "base": (99, 199, 77),  "shape": "slab",   "depth": 0},
    "ear_r": {"parent": "head",  "pivot": (18, 6.5),  "base": (99, 199, 77),  "shape": "slab",   "depth": 0},
    "arm_l": {"parent": "torso", "pivot": (4.5, 16),  "base": (99, 199, 77),  "shape": "slab",   "depth": 1},
    "arm_r": {"parent": "torso", "pivot": (19.5, 16), "base": (99, 199, 77),  "shape": "slab",   "depth": 1},
    "leg_l": {"parent": "root",  "pivot": (8, 20),    "base": (99, 199, 77),  "shape": "slab",   "depth": 1},
    "leg_r": {"parent": "root",  "pivot": (16, 20),   "base": (99, 199, 77),  "shape": "slab",   "depth": 1},
}
HEM = (116, 63, 57)  # the tunic's hem and the boots are dark brown all the way round
HEM_ROW, BOOT_ROW = 19, 22
# Shading the artist drew down a part's sides (dark green on the head, dark brown on the tunic) turns to stripes once
# the sides are solid, so it becomes the part's own colour and Blender's light does the shading. The inner ears, the
# tunic's folds, its hem and the boots keep their dark colour: they're drawing, not shade.
SHADE = {(62, 137, 72): (99, 199, 77), (116, 63, 57): (184, 111, 80)}


def part_of(x: int, y: int) -> str:
    """Which part a pixel of the goblin belongs to."""
    if y >= 20:
        return "leg_l" if x < 12 else "leg_r"
    if y >= 14:
        return "arm_l" if x <= 4 else "arm_r" if x >= 19 else "torso"
    if y <= 7 and (x <= 5 or x >= 18):
        return "ear_l" if x < 12 else "ear_r"
    return "head"


def load() -> dict[tuple[int, int], tuple]:
    """The first frame's pixels without the outline: dark pixels on the edge go, and so does every dark pixel
    outside the head (lines between parts). Dark pixels inside the head are the face (pupils, mouth) and stay."""
    sheet = Image.open(SPRITE).convert("RGBA")
    pixels = {(x, y): sheet.getpixel((x, y))[:3] for y in range(SIZE) for x in range(SIZE)
              if sheet.getpixel((x, y))[3] >= 128}

    def on_edge(x, y):
        return any((x + dx, y + dy) not in pixels for dx in (-1, 0, 1) for dy in (-1, 0, 1))

    kept = {(x, y): rgb for (x, y), rgb in pixels.items()
            if rgb != OUTLINE or (part_of(x, y) == "head" and not on_edge(x, y))}

    def on_side(x, y):  # the first or last pixel of its part in its row
        row = [xx for xx, yy in kept if yy == y and part_of(xx, yy) == part_of(x, y)]
        return x in (min(row), max(row))

    return {(x, y): SHADE[rgb] if rgb in SHADE and y not in (HEM_ROW, BOOT_ROW) and not part_of(x, y).startswith("ear")
            and on_side(x, y) else rgb for (x, y), rgb in kept.items()}


def depths(pixels: dict, part: str) -> dict[tuple[int, int], tuple[int, int]]:
    """How far each of a part's pixels reaches behind and in front of the middle, as (back, front) cube counts."""
    spec = PARTS[part]
    mine = [p for p in pixels if part_of(*p) == part]
    if spec["shape"] == "slab":
        reach = {p: (-spec["depth"], spec["depth"]) for p in mine}
        if part.startswith("leg"):  # boots poke forward a cube for toes
            reach.update({(x, y): (-1, 2) for x, y in mine if y == BOOT_ROW})
        return reach
    if spec["shape"] == "barrel":
        reach = {}
        for y in {y for _, y in mine}:
            row = sorted(x for x, yy in mine if yy == y)
            middle, half = (row[0] + row[-1]) / 2, (row[-1] - row[0]) / 2 + 0.5
            for x in row:
                h = round(spec["depth"] * math.sqrt(max(0.0, 1 - ((x - middle) / half) ** 2)))
                reach[(x, y)] = (-max(h, 1), max(h, 1))
        return reach
    # A dome: depth follows each pixel's distance from the edge of the head (ears count as head here, so the head
    # stays full where they join), on a circle's curve so the sides are steep and the face is round.
    solid = {p for p in pixels if part_of(*p) in (part, "ear_l", "ear_r")}
    outside = [(x, y) for x in range(-1, SIZE + 1) for y in range(-1, SIZE + 1) if (x, y) not in solid]
    dist = {p: min(math.dist(p, q) for q in outside) for p in mine}
    deepest = max(dist.values())
    reach = {}
    for p, d in dist.items():
        h = round(spec["depth"] * math.sqrt(1 - (1 - d / deepest) ** 2))
        reach[p] = (-max(h, 1), max(h, 1))
    return reach


def voxels() -> dict[str, list]:
    """Every part's cubes as [x, y, z, colour]: x and y are the sprite's pixel, z is depth (positive is toward the
    viewer). The front cube gets the pixel's own colour; the rest get the part's base colour."""
    pixels = load()
    out = {}
    for part, spec in PARTS.items():
        if part == "root":
            continue
        cubes = []
        for (x, y), (back, front) in sorted(depths(pixels, part).items()):
            base = HEM if y in (HEM_ROW, BOOT_ROW) else spec["base"]
            for z in range(back, front + 1):
                cubes.append([x, y, z, "#%02x%02x%02x" % (pixels[(x, y)] if z == front else base)])
        out[part] = cubes
    return out


def main() -> None:
    cubes = voxels()
    data = {
        "sprite": "goblin",
        "size": SIZE,
        "parts": {part: {"parent": spec["parent"], "pivot": spec["pivot"], "voxels": cubes.get(part, [])}
                  for part, spec in PARTS.items()},
    }
    path = HERE / "goblin_voxels.json"
    path.write_text(json.dumps(data))
    colours = sorted({c for part in cubes.values() for *_, c in part})
    print(f"{sum(len(c) for c in cubes.values())} cubes in {len(cubes)} parts, {len(colours)} colours -> {path}")
    for part, c in cubes.items():
        print(f"  {part:6} {len(c):5} cubes")


if __name__ == "__main__":
    main()
