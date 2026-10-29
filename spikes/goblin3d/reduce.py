"""Spike: a boss's big frames shrunk to sprite size, in its palette, with the game's outline round them.

build_king.py (and build_mouse.py) render 256-pixel frames in nothing but the palette's colours (each lit or in
shadow). Shrinking takes the commonest colour under each new pixel, so nothing blends, with the small things that
would otherwise vanish (the King's mouth and pupils, his teeth, his eyes) counted a little heavier. Then the dark
outline goes round, one pixel, as the game's sprites are drawn.

    uv run --no-sync --with numpy python spikes/goblin3d/reduce.py                  # king/frames_hd -> king/frames_48, _64
    uv run --no-sync --with numpy python spikes/goblin3d/reduce.py 40 96            # any sizes
    uv run --no-sync --with numpy python spikes/goblin3d/reduce.py king_mouse 44 52 # another boss's folder

The palette comes from the boss's *_mesh.json, and so do the weights, when it gives them ("heavier").
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).parent
KING = HERE / "king"
OUTLINE = "#181425"
HEAVIER = {"#181425": 2.0, "#ffffff": 2.0, "#fee761": 1.3}  # the King's mouth and pupils, teeth, eyes and gold


def rgb(hex_colour: str) -> tuple:
    return tuple(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))


def palette(model: Path) -> tuple[np.ndarray, np.ndarray]:
    """Every colour the boss can be drawn in (lit, shadowed, outline) and how much each counts."""
    mesh = json.loads(next(model.glob("*_mesh.json")).read_text())
    shades, heavier = mesh["shades"], mesh.get("heavier", HEAVIER)
    colours = sorted({*shades, *shades.values(), OUTLINE})
    return np.array([rgb(c) for c in colours]), np.array([heavier.get(c, 1.0) for c in colours])


def reduce(img: Image.Image, n: int, colours: np.ndarray, weights: np.ndarray) -> Image.Image:
    pixels = np.asarray(img.convert("RGBA"))
    h, w = pixels.shape[:2]
    solid = (pixels[..., 3] >= 128).reshape(-1)
    near = ((pixels[..., :3].reshape(-1, 1, 3).astype(int) - colours[None]) ** 2).sum(-1).argmin(1)
    ys, xs = np.divmod(np.arange(h * w), w)
    cell = (ys * n // h) * n + xs * n // w
    votes = np.bincount(cell[solid] * len(colours) + near[solid], weights=weights[near[solid]],
                        minlength=n * n * len(colours)).reshape(n * n, len(colours))
    cover = np.bincount(cell[solid], minlength=n * n) / np.bincount(cell, minlength=n * n)
    out = np.zeros((n * n, 4), np.uint8)
    kept = cover >= 0.5
    out[kept, :3] = colours[votes[kept].argmax(1)]
    out[kept, 3] = 255
    out = out.reshape(n, n, 4)
    filled = out[..., 3] > 0
    pad = np.pad(filled, 1)
    edge = (pad[:-2, 1:-1] | pad[2:, 1:-1] | pad[1:-1, :-2] | pad[1:-1, 2:]) & ~filled
    out[edge] = (*rgb(OUTLINE), 255)
    return Image.fromarray(out, "RGBA")


def main() -> None:
    args = sys.argv[1:]
    model = HERE / args.pop(0) if args and not args[0].isdigit() else KING
    sizes = [int(a) for a in args] or [48, 64]
    colours, weights = palette(model)
    source = model / "frames_hd"
    paths = sorted(source.rglob("*.png"))
    for n in sizes:
        target = model / f"frames_{n}"
        for path in paths:
            out = target / path.relative_to(source)
            out.parent.mkdir(parents=True, exist_ok=True)
            reduce(Image.open(path), n, colours, weights).save(out)
        print(f"{len(paths)} frames -> {target} ({n}x{n})")


if __name__ == "__main__":
    main()
