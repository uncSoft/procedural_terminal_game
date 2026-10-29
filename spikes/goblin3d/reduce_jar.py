"""Spike: the Jar o' Light's big frames shrunk for a preview, the way reduce.py shrinks a boss's, with its glass drawn
the way the sprite draws it.

build_jar.py renders what's in the jar (its lid, bugs and sparks) from every turn, and the glass alone once
(jar_o_light/glass.png): the glass is see-through, so the frames show only its outline, as the sprite does. Each frame
is shrunk by reduce.py (the commonest colour under each new pixel, the small bright things counted heavier) without its
dark outline; then the glass's outline goes round it, a pixel wide, pale down the jar's lit left side and slate
elsewhere, and the lid sits over it unoutlined, as drawn.

    uv run --no-sync --with numpy python spikes/goblin3d/reduce_jar.py              # frames_48, _64 and _96
    uv run --no-sync --with numpy python spikes/goblin3d/reduce_jar.py 40 128       # any sizes
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

import reduce as boss

HERE = Path(__file__).parent
JAR = HERE / "jar_o_light"


def glass_at(n: int) -> np.ndarray:
    """Where the glass is, shrunk to n: the cells it covers at least half of."""
    alpha = np.asarray(Image.open(JAR / "glass.png").convert("RGBA"))[..., 3] >= 128
    h, w = alpha.shape
    return alpha.reshape(n, h // n, n, w // n).mean((1, 3)) >= 0.5 if h % n == 0 else \
        np.asarray(Image.fromarray(alpha.astype(np.uint8) * 255).resize((n, n), Image.BOX)) >= 128


def grow(mask: np.ndarray) -> np.ndarray:
    pad = np.pad(mask, 1)
    return mask | pad[:-2, 1:-1] | pad[2:, 1:-1] | pad[1:-1, :-2] | pad[1:-1, 2:]


def outline(glass: np.ndarray, slate: tuple, pale: tuple, width: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """The ring of pixels round the glass, `width` deep, and its colour: pale where it faces left (and up-left) on the
    jar's upper part, where the light falls; slate elsewhere."""
    n = glass.shape[0]
    ring = glass.copy()
    for _ in range(width):
        ring = grow(ring)
    ring &= ~glass
    reach = width + 1
    pad = np.pad(glass, reach)
    inward = np.zeros((n, n, 2))
    for dy in range(-reach, reach + 1):
        for dx in range(-reach, reach + 1):
            if dx or dy:
                there = np.roll(np.roll(pad, -dy, 0), -dx, 1)[reach:-reach, reach:-reach]
                inward[..., 0] += dx * there
                inward[..., 1] += dy * there
    rows = np.nonzero(glass.any(1))[0]
    top, bottom = rows[0], rows[-1]
    ys = np.arange(n)[:, None].repeat(n, 1)
    length = np.hypot(inward[..., 0], inward[..., 1]) + 1e-9
    lit = (inward[..., 0] > 0.35 * length) & (inward[..., 1] >= -0.3 * length) & (ys < top + 0.62 * (bottom - top))
    colour = np.where(lit[..., None], pale, slate)
    return ring, colour


def shrink(path: Path, n: int, colours: np.ndarray, weights: np.ndarray, glass: np.ndarray,
           ring: np.ndarray, ring_colour: np.ndarray) -> Image.Image:
    small = np.asarray(boss.reduce(Image.open(path), n, colours, weights)).copy()
    dark = (small[..., :3] == boss.rgb(boss.OUTLINE)).all(-1)
    small[dark] = 0  # reduce.py's own outline: the jar has the glass's instead
    content = small[..., 3] > 0
    out = np.zeros_like(small)
    show = ring & ~content
    out[show, :3] = ring_colour[show]
    out[show, 3] = 255
    out[content] = small[content]
    return Image.fromarray(out, "RGBA")


def main() -> None:
    sizes = [int(a) for a in sys.argv[1:]] or [48, 64, 96]
    colours, weights = boss.palette(JAR)
    model = json.loads((JAR / "jar_mesh.json").read_text())
    slate, pale = boss.rgb(model["outline"]), boss.rgb(model["lit_outline"])
    source = JAR / "frames_hd"
    paths = sorted(source.rglob("*.png"))
    for n in sizes:
        glass = glass_at(n)
        ring, ring_colour = outline(glass, slate, pale, max(1, round(n / 48)))  # as thick as a sprite pixel
        target = JAR / f"frames_{n}"
        for path in paths:
            out = target / path.relative_to(source)
            out.parent.mkdir(parents=True, exist_ok=True)
            shrink(path, n, colours, weights, glass, ring, ring_colour).save(out)
        print(f"{len(paths)} frames -> {target} ({n}x{n})")


if __name__ == "__main__":
    main()
