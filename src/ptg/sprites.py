"""Pixel-art sprites drawn with half-block characters.

Each terminal cell shows two pixels: "▀" in the top pixel's colour on a background of the bottom pixel's
colour. That works in any terminal with 24-bit colour, inside Textual's layout, with no image protocol.
Sprites are PNG strips in ptg/data/sprites: frames side by side with a transparent background. Frames are
square unless the PNG says otherwise (the build tool stores a "frames" count). Anything without a sprite,
or a player who prefers it, gets the ASCII art instead.

Pixel art doesn't shrink well, so a sprite can have a hand-made small version in ptg/data/sprites/small (items
are drawn 12 pixels wide in the inventory and in loot cards; the Monster & Item Maker draws them). Without one, a
sprite drawn at half size is halved block by block (see halve, which the maker page copies), which keeps its lines
whole but is no match for a version drawn by hand.

Poses are made from a sprite's own frames at draw time, so every sprite gets them for free:

    idle     the sprite's own animation
    windup   rears up, with a pulsing red-orange glow (a heavy blow is coming)
    dizzy    stars circling its head (stunned)
    calm     greyed out (pacified)
    lunge    lurches forward, tinted red (attacking)
    shake    rattles side to side
    death    dissolves in an ordered dither, frame by frame (0-5)

    uv run python -m ptg.sprites goblin troll      # preview sprites in your terminal
"""

from __future__ import annotations

import sys
from functools import lru_cache
from importlib import resources

from rich.color import Color
from rich.style import Style
from rich.text import Text

try:
    from PIL import Image
except ImportError:  # sprites are optional; the game falls back to ASCII art
    Image = None

DEFAULT_WIDTH = 24
SMALL = 12  # how wide items are drawn small; a hand-made small version is this size
OUTLINE = 40  # colours darker than this are outline: they barely show on a dark terminal
DEATH_FRAMES = 6
BAYER = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))
GLOW = ((228, 59, 68), (254, 174, 52))
STAR = (254, 231, 97)
# Effects recolour a sprite in a few fixed shades, picked by how light each pixel is: greyed out when calm, flushed
# red when it lunges, white when it's hit. Few fixed colours keep a GPU terminal's glyph cache small (see palette).
GREYS = ((46, 48, 62), (82, 86, 104), (122, 126, 144), (166, 170, 186), (210, 212, 222))
REDS = ((96, 26, 40), (150, 38, 52), (204, 58, 66), (236, 104, 98), (250, 160, 150))
LIGHTS = ((200, 206, 224), (232, 234, 244), (255, 255, 255))


@lru_cache(maxsize=128)
def frames(key: str, width: int = DEFAULT_WIDTH) -> tuple | None:
    """The frames of a sprite `width` pixels wide, or None if there isn't one: its hand-made small version if
    that's the size, otherwise the sprite scaled (halved block by block, or nearest neighbour for other sizes)."""
    if Image is None:
        return None
    small = _strip(key, small=True)
    if small and small[0].width == width:
        return small
    sheet = _strip(key)
    if sheet is None:
        return None
    return tuple(_fit(frame, width) for frame in sheet)


@lru_cache(maxsize=256)
def _strip(key: str, small: bool = False) -> tuple | None:
    """A sprite strip's frames at their own size."""
    folder = resources.files("ptg") / "data" / "sprites"
    path = (folder / "small" if small else folder) / f"{key}.png"
    if not path.is_file():
        return None
    with path.open("rb") as f:
        sheet = Image.open(f)
        count = int(sheet.info.get("frames") or 0)
        sheet = sheet.convert("RGBA")
        sheet.load()
    count = count or max(1, sheet.width // sheet.height)
    frame_width = sheet.width // count
    return tuple(sheet.crop((i * frame_width, 0, (i + 1) * frame_width, sheet.height)) for i in range(count))


def has_small(key: str) -> bool:
    """Whether a sprite has a hand-made small version."""
    return Image is not None and _strip(key, small=True) is not None


def _fit(frame, width: int):
    if frame.width == width:
        return frame
    if frame.width == 2 * width:
        return halve(frame)
    return frame.resize((width, max(2, round(frame.height * width / frame.width))), Image.NEAREST)


def halve(img):
    """Half size, block by block. Each 2x2 block takes its most common colour (the lighter one in a tie), leaving
    out the outline when there's colour too, so thin lines stay whole; it's see-through only if all four are."""
    out = Image.new("RGBA", (img.width // 2, img.height // 2), (0, 0, 0, 0))
    source, target = img.load(), out.load()
    for y in range(out.height):
        for x in range(out.width):
            solid = [source[2 * x + dx, 2 * y + dy][:3] for dy in (0, 1) for dx in (0, 1)
                     if source[2 * x + dx, 2 * y + dy][3] >= 128]
            if solid:
                colour = [p for p in solid if _light(p) >= OUTLINE] or solid
                target[x, y] = (*max(set(colour), key=lambda p: (colour.count(p), _light(p))), 255)
    return out


def _light(rgb: tuple) -> float:
    r, g, b = rgb
    return 0.3 * r + 0.59 * g + 0.11 * b


def frame_count(key: str) -> int:
    found = frames(key)
    return len(found) if found else 0


def sprite_text(key: str, frame: int = 0, width: int = DEFAULT_WIDTH, flash: bool = False,
                pose: str = "idle") -> Text | None:
    """The sprite as Rich text, or None so the caller can fall back to ASCII art."""
    text = _render(key, frame, width, flash, pose)
    return text.copy() if text is not None else None


@lru_cache(maxsize=512)
def _render(key: str, frame: int, width: int, flash: bool, pose: str) -> Text | None:
    found = frames(key, width)
    if not found:
        return None
    base = found[0] if pose == "death" else found[frame % len(found)]
    return image_text(posed(base, pose, frame), flash, snap=True)


def posed(img, pose: str, frame: int = 0):
    """A copy of `img` in the given pose (see the module docstring)."""
    if pose == "windup":
        return _glow(_shift(img, 0, -1), GLOW[frame % 2])
    if pose == "dizzy":
        return _stars(img, frame)
    if pose == "calm":
        return _recolour(img, lambda r, g, b: _shade(GREYS, r, g, b, 0.85))
    if pose == "lunge":
        return _recolour(_shift(img, 0, 1 + frame % 2), lambda r, g, b: _shade(REDS, r, g, b))
    if pose == "shake":
        return _shift(img, (-1, 1)[frame % 2], 0)
    if pose == "death":
        return _dissolve(img, min(frame, DEATH_FRAMES - 1))
    return img


def image_text(img, flash: bool = False, snap: bool = False) -> Text:
    """Any RGBA image as half-block text. With `snap`, colours an effect made up (a flash, a tint, a grey) become
    the nearest colour the sprites are drawn in (see palette)."""
    pixels = img.load()
    text = Text(no_wrap=True, overflow="crop")
    for y in range(0, img.height, 2):
        for x in range(img.width):
            top = _colour(pixels[x, y], flash, snap)
            bottom = _colour(pixels[x, y + 1], flash, snap) if y + 1 < img.height else None
            if top and bottom:
                text.append("▀", Style(color=top, bgcolor=bottom))
            elif top:
                text.append("▀", Style(color=top))
            elif bottom:
                text.append("▄", Style(color=bottom))
            else:
                text.append(" ")
        if y + 2 < img.height:
            text.append("\n")
    return text


def side_by_side(texts: list[Text], gap: int = 3) -> Text:
    """Several half-block images next to each other (they should be the same height)."""
    columns = [t.split("\n") for t in texts]
    out = Text(no_wrap=True, overflow="crop")
    for row in range(max(len(c) for c in columns)):
        for i, column in enumerate(columns):
            if row < len(column):
                out.append_text(column[row])
            if i < len(columns) - 1:
                out.append(" " * gap)
        if row < max(len(c) for c in columns) - 1:
            out.append("\n")
    return out


# --- pixel helpers ------------------------------------------------------------------

def _colour(pixel: tuple, flash: bool, snap: bool = False) -> Color | None:
    r, g, b, alpha = pixel
    if alpha < 128:
        return None
    if flash:  # a white hit-flash
        r, g, b = _shade(LIGHTS, r, g, b)
    if snap:
        r, g, b = _nearest((r, g, b))
    return Color.from_rgb(r, g, b)


@lru_cache(maxsize=1)
def palette() -> tuple:
    """Every colour the sprites are drawn in. Effects keep to these, because a terminal that draws with the GPU
    caches each character in each pair of colours it meets: made-up shades on top of the art fill that cache, and a
    full one garbles the screen (see PTGApp.action_redraw)."""
    folder = resources.files("ptg") / "data" / "sprites"
    keys = [(p.name[:-4], False) for p in folder.iterdir() if p.name.endswith(".png")]
    if (folder / "small").is_dir():
        keys += [(p.name[:-4], True) for p in (folder / "small").iterdir() if p.name.endswith(".png")]
    colours = {pixel[:3] for key, small in keys for frame in _strip(key, small) or ()
               for pixel in frame.get_flattened_data() if pixel[3] >= 128}
    return tuple(sorted(colours | {GLOW[0], GLOW[1], STAR, *GREYS, *REDS, *LIGHTS}))


@lru_cache(maxsize=4096)
def _nearest(rgb: tuple) -> tuple:
    return min(palette(), key=lambda c: (c[0] - rgb[0]) ** 2 + (c[1] - rgb[1]) ** 2 + (c[2] - rgb[2]) ** 2)


def _shift(img, dx: int, dy: int):
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(img, (dx, dy))
    return out


def _shade(shades: tuple, r: int, g: int, b: int, dim: float = 1.0) -> tuple:
    """The one of `shades` (darkest first) as light as this pixel."""
    light = (0.3 * r + 0.59 * g + 0.11 * b) * dim / 256
    return shades[min(len(shades) - 1, int(light * len(shades)))]


def _recolour(img, fn):
    out = img.copy()
    px = out.load()
    for y in range(out.height):
        for x in range(out.width):
            r, g, b, a = px[x, y]
            if a:
                px[x, y] = (*fn(r, g, b), a)
    return out


def _glow(img, colour: tuple):
    """A one-pixel ring of colour just outside the sprite's silhouette."""
    out = img.copy()
    src, px = img.load(), out.load()
    for y in range(img.height):
        for x in range(img.width):
            if src[x, y][3]:
                continue
            near = any(0 <= x + dx < img.width and 0 <= y + dy < img.height and src[x + dx, y + dy][3]
                       for dx in (-1, 0, 1) for dy in (-1, 0, 1))
            if near:
                px[x, y] = (*colour, 255)
    return out


def _stars(img, frame: int):
    """Three stars circling just above the top of the sprite."""
    out = img.copy()
    px = out.load()
    solid = [(x, y) for y in range(img.height) for x in range(img.width) if px[x, y][3]]
    if not solid:
        return out
    top = min(y for _, y in solid)
    xs = [x for x, y in solid if y <= top + 3]
    centre = (min(xs) + max(xs)) // 2
    orbit = [(-6, 1), (-3, -1), (0, -2), (3, -1), (6, 1), (3, 2), (0, 2), (-3, 2)]
    for i in range(3):
        ox, oy = orbit[(frame * 2 + i * 3) % len(orbit)]
        x, y = centre + ox, max(0, top + oy)
        if 0 <= x < img.width:
            px[x, y] = (*STAR, 255)
    return out


def _dissolve(img, step: int):
    """Ordered-dither dissolve: each step removes more pixels, drifts down and, from the third, turns grey."""
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    src, px = img.load(), out.load()
    threshold = step * 16 / (DEATH_FRAMES - 1)
    drop = step // 2
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = src[x, y]
            if not a or BAYER[y % 4][x % 4] < threshold or y + drop >= img.height:
                continue
            px[x, y + drop] = (*((r, g, b) if step < 2 else _shade(GREYS, r, g, b, 1 - step * 0.08)), a)
    return out


def main(keys: list[str]) -> None:
    from rich.console import Console

    from .content import load_content

    console = Console()
    content = load_content()
    keys = keys or [*content.monsters, "campfire", "shrine", "fountain", "chest", "stairs", "mirror", "sunglasses"]
    for key in keys:
        text = sprite_text(key)
        console.print(f"[bold]{key}[/]  ({frame_count(key)} frames)")
        console.print(text if text is not None else content.monsters.get(key).art if key in content.monsters else "?")


if __name__ == "__main__":
    main(sys.argv[1:])
