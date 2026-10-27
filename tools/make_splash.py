"""Turns any picture (a painting, a screenshot, an image model's output) into splash art for the terminal.

A terminal cell shows two pixels, one over the other (see ptg/sprites.py), so a splash W pixels wide and H tall takes
W columns and H/2 rows. The title's storm is drawn at most 160 columns wide and the stage 140 by 30 rows (ui/plan.py),
so 160 pixels across is as big as the game draws a picture; 16:9 art at that width is 160x90, 45 rows.

A floor's card (ui/panels.py FloorScreen) draws the widest of its splash's sizes that fits the screen. With --floor,
every one of SIZES is made from the picture itself, which looks far better than the biggest shrunk at draw time (the
card does that only for a screen too small for any of them).

The picture is shrunk by averaging, its darks lifted (painted dungeons are mostly near-black, which would all become
the palette's darkest colour), then each pixel snapped to the nearest of the sprites' own colours (sprites.palette),
measured in Lab so it keeps its hue. Keeping to those colours matters beyond the look: a terminal that draws with the
GPU caches each pair of colours it meets, and a picture with colours of its own fills that cache (see sprites.palette).
That's done at twice the size and halved block by block, as the sprites are, so small bright things survive. Last, a
lone pixel unlike all four neighbours, three of which agree, takes their colour: the speckle a shrink leaves.

    uv run python tools/make_splash.py picture.jpg out.png                  # 160 wide
    uv run python tools/make_splash.py picture.jpg out.png --width 96       # for a smaller screen
    uv run python tools/make_splash.py picture.jpg out.png --show           # and print it here (in a wide terminal)
    uv run python tools/make_splash.py picture.jpg out.png --endesga        # Endesga 32 only, no extras
    uv run python tools/make_splash.py picture.jpg out.png --calm           # flatter shapes, less speckle
    uv run python tools/make_splash.py picture.jpg --floor norfel           # a floor's card: data/splash/norfel/

A single picture also gets out-x8.png, eight times the size, to look at in a picture viewer.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageEnhance

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from ptg import sprites  # noqa: E402
from ptg.library import ENDESGA  # noqa: E402

WIDTH = 160
SIZES = (160, 128, 96, 64, 40)  # a floor's card art, widest first: a big screen, a laptop's, a small window, a phone
SPLASH = Path(__file__).resolve().parent.parent / "src" / "ptg" / "data" / "splash"


def lab(rgb: tuple) -> tuple:
    """sRGB to CIE Lab (D65)."""
    def linear(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    r, g, b = (linear(c) for c in rgb)
    x = f((0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047)
    y = f(0.2126 * r + 0.7152 * g + 0.0722 * b)
    z = f((0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883)
    return 116 * y - 16, 500 * (x - y), 200 * (y - z)


@lru_cache(maxsize=2)
def palette(endesga: bool) -> tuple:
    colours = [tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) for h in ENDESGA] if endesga else sprites.palette()
    return tuple((c, lab(c)) for c in colours)


@lru_cache(maxsize=65536)
def nearest(rgb: tuple, endesga: bool) -> tuple:
    L, a, b = lab(rgb)
    return min(palette(endesga), key=lambda p: (L - p[1][0]) ** 2 + (a - p[1][1]) ** 2 + (b - p[1][2]) ** 2)[0]


def lift(img, top: int, gamma: float):
    """The brightest 1% up to `top`, everything under it brought up by `gamma` (under 1 lifts the darks most)."""
    light = sorted(sum(p) / 3 for p in img.get_flattened_data())
    high = max(1.0, light[int(len(light) * 0.99)])
    return img.point(lambda v: round(top * min(1.0, v / high) ** gamma))


def tidy(img):
    """A lone pixel unlike all four of its neighbours, three of which agree, takes their colour."""
    source, out = img.load(), img.copy()
    target = out.load()
    for y in range(1, img.height - 1):
        for x in range(1, img.width - 1):
            around = [source[x - 1, y], source[x + 1, y], source[x, y - 1], source[x, y + 1]]
            if source[x, y] not in around:
                colour, count = Counter(around).most_common(1)[0]
                if count >= 3:
                    target[x, y] = colour
    return out


def flatten(img):
    """Each pixel the commonest colour of the nine round it (its own in a tie). Pillow's ModeFilter won't do: it
    votes each of red, green and blue apart, and makes colours that aren't in the palette."""
    source, out = img.load(), img.copy()
    target = out.load()
    for y in range(img.height):
        for x in range(img.width):
            around = Counter(source[x + dx, y + dy] for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                             if 0 <= x + dx < img.width and 0 <= y + dy < img.height)
            colour, count = around.most_common(1)[0]
            if count > around[source[x, y]]:
                target[x, y] = colour
    return out


def splash(picture, width: int = WIDTH, top: int = 190, gamma: float = 0.8, colour: float = 1.3,
           endesga: bool = False, soft: bool = False, calm: bool = False):
    """The picture `width` pixels across (and an even number tall, so it fills whole rows of cells). It's snapped at
    twice the size and halved block by block (sprites.halve), which keeps small bright things (eyes in the dark, a
    glowing mushroom) that averaging straight down would blur away; `soft` averages straight down. A busy picture
    (brickwork, moss) can be `calm`: each pixel takes the commonest colour round it before halving, which leaves
    flat shapes, at the cost of thin lines like bars."""
    height = max(2, round(width * picture.height / picture.width / 2) * 2)
    scale = 1 if soft else 2
    small = picture.convert("RGB").resize((width * scale, height * scale), Image.BOX)
    small = ImageEnhance.Color(lift(small, top, gamma)).enhance(colour)
    pixels = small.load()
    for y in range(small.height):
        for x in range(small.width):
            pixels[x, y] = nearest(pixels[x, y], endesga)
    if calm:
        small = flatten(tidy(small))
    if not soft:
        small = sprites.halve(tidy(small).convert("RGBA")).convert("RGB")
    return tidy(small)


def report(art, path: Path) -> None:
    used = {art.getpixel((x, y)) for y in range(art.height) for x in range(art.width)}
    pairs = {(art.getpixel((x, y)), art.getpixel((x, y + 1))) for y in range(0, art.height, 2) for x in range(art.width)}
    print(f"{path}: {art.width}x{art.height} pixels, {art.width} columns x {art.height // 2} rows, "
          f"{len(used)} colours, {len(pairs)} pairs of them")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("picture", type=Path)
    parser.add_argument("out", type=Path, nargs="?", help="the splash, one pixel per half-cell (a .png)")
    parser.add_argument("--floor", help="a theme's key (themes.toml): its card's every size, into data/splash/<key>/")
    parser.add_argument("--width", type=int, default=WIDTH, help=f"pixels, which is columns (default {WIDTH})")
    parser.add_argument("--top", type=int, default=190, help="how light the brightest 1%% become, 0-255 (190)")
    parser.add_argument("--gamma", type=float, default=0.8, help="under 1 lifts the darks, over 1 deepens them (0.8)")
    parser.add_argument("--colour", type=float, default=1.3, help="saturation before snapping (1.3)")
    parser.add_argument("--endesga", action="store_true", help="snap to Endesga 32 only, not the sprites' extras")
    parser.add_argument("--soft", action="store_true", help="average straight down instead of halving block by block")
    parser.add_argument("--calm", action="store_true", help="flatten busy texture into shapes (loses thin lines)")
    parser.add_argument("--show", action="store_true", help="print it as the game draws it")
    args = parser.parse_args()
    if bool(args.out) == bool(args.floor):
        parser.error("give either an out.png or --floor, not both")

    picture = Image.open(args.picture)
    look = (args.top, args.gamma, args.colour, args.endesga, args.soft, args.calm)
    if args.floor:
        folder = SPLASH / args.floor
        folder.mkdir(parents=True, exist_ok=True)
        for width in SIZES:
            art = splash(picture, width, *look)
            art.save(folder / f"{width}.png")
            report(art, folder / f"{width}.png")
        return
    art = splash(picture, args.width, *look)
    art.save(args.out)
    art.resize((art.width * 8, art.height * 8), Image.NEAREST).save(args.out.with_name(f"{args.out.stem}-x8.png"))
    report(art, args.out)
    if args.show:
        from rich.console import Console
        Console(width=art.width).print(sprites.image_text(art.convert("RGBA")))


if __name__ == "__main__":
    main()
