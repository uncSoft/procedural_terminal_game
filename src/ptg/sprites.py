"""Pixel-art sprites drawn with half-block characters.

Each terminal cell shows two pixels: "▀" in the top pixel's colour on a background of the bottom pixel's
colour. That works in any terminal with 24-bit colour, inside Textual's layout, with no image protocol.
Sprites are PNG strips in ptg/data/sprites: frames side by side with a transparent background. The PNG stores how
many frames it holds (the build tool and the maker write a "frames" count); a picture editor may drop that, and then
frames are taken to be the game's own 24 pixels wide (12 for a small version), or square for art taller than that.
Anything without a sprite, or a player who prefers it, gets the ASCII art instead.

Pixel art doesn't shrink well, so a sprite can have a hand-made small version in ptg/data/sprites/small (drawn 12
pixels wide where there's no room for the full 24: see ui/widgets.py art_for; the Monster & Item Maker draws them).
Without one, a sprite drawn at half size is halved block by block (see halve, which the maker page copies), which
keeps its lines whole but is no match for a version drawn by hand.

Poses are made from a sprite's own frames at draw time, so every sprite gets them for free:

    idle     the sprite's own animation
    windup   rears up, with a pulsing red-orange glow (a heavy blow is coming)
    dizzy    stars circling its head (stunned)
    calm     just as it is: characters are always in their own colours (a calm one says so in words, not in grey)
    lunge    lurches forward, tinted red (attacking)
    shake    rattles side to side
    death    dissolves in an ordered dither, frame by frame (0-5)

    uv run python -m ptg.sprites goblin troll      # preview sprites in your terminal

A floor can have splash art too, a picture for its card (ui/panels.py FloorScreen): data/splash/<theme>/ holds it in
several sizes, each made from the original picture by tools/make_splash.py (see splash).

And a monster can have clips: animations made for it elsewhere, frame by frame (the Blender pipeline in
spikes/goblin3d turns a sprite into a model, animates it and renders it back into pixels), in data/clips/<monster>/,
each in several sizes (see clips; tools/make_clip.py writes them). The stage plays a boss's entrance from one when a
fight with it starts (encounter.Fight).
"""

from __future__ import annotations

import sys
import warnings
from dataclasses import dataclass
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
# Effects recolour a sprite in a few fixed shades, picked by how light each pixel is: flushed red when it lunges, white
# when it's hit, grey as it dies. Few fixed colours keep a GPU terminal's glyph cache small (see palette).
GREYS = ((46, 48, 62), (82, 86, 104), (122, 126, 144), (166, 170, 186), (210, 212, 222))
REDS = ((96, 26, 40), (150, 38, 52), (204, 58, 66), (236, 104, 98), (250, 160, 150))
LIGHTS = ((200, 206, 224), (232, 234, 244), (255, 255, 255))
# Fixtures whose last frame shows them used up (a looted chest, a shrine with its candles out): the room picture draws
# that frame once they're spent, and it's left out of their idle animation.
SPENT = ("chest", "shrine")


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
        count = count_frames(sheet, small, f"sprites/{'small/' if small else ''}{key}.png")
        sheet = sheet.convert("RGBA")
        sheet.load()
    frame_width = sheet.width // count
    return tuple(sheet.crop((i * frame_width, 0, (i + 1) * frame_width, sheet.height)) for i in range(count))


def count_frames(sheet, small: bool = False, name: str = "a sprite") -> int:
    """How many frames a strip holds: the count stored in the PNG, or else as many 24-pixel frames as fit (12 for a
    small version), or square ones if the art is taller than that. A strip whose width doesn't divide evenly gets a
    warning, since the frames would be cut in the wrong places."""
    stored = int(sheet.info.get("frames") or 0)
    if stored:
        return stored
    size = SMALL if small else DEFAULT_WIDTH
    width, height = sheet.size
    if height <= size and width % size == 0:
        return width // size
    if width > height and width % height:
        warnings.warn(f"{name} is {width}x{height} pixels with no frame count stored, so its frames can't be told "
                      f"apart: make it {size} pixels a frame, or keep the PNG's 'frames' text", stacklevel=2)
    return max(1, width // height)


def has_small(key: str) -> bool:
    """Whether a sprite has a hand-made small version."""
    return Image is not None and _strip(key, small=True) is not None


def fill(key: str, width: int = DEFAULT_WIDTH) -> float:
    """How much of its frame a sprite's art takes up at `width` (its small version at SMALL): the share of the frame
    inside the box round its pixels, all frames together (0 without a sprite). Art in under half its frame looks
    small on cards and in rooms."""
    found = frames(key, width)
    boxes = [box for frame in found or () if (box := frame.getbbox())]
    if not boxes:
        return 0.0
    width = max(box[2] for box in boxes) - min(box[0] for box in boxes)
    height = max(box[3] for box in boxes) - min(box[1] for box in boxes)
    return width * height / (found[0].width * found[0].height)


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


def idle_frames(key: str) -> list[int]:
    """The frames a sprite's idle animation cycles through: all of them, but a used-up fixture's last (see SPENT)."""
    count = frame_count(key)
    return list(range(max(1, count - (key in SPENT and count > 1))))


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
    """A copy of `img` in the given pose (see the module docstring), or `img` itself when the pose changes nothing
    (idle, calm)."""
    if pose == "windup":
        return _glow(_shift(img, 0, -1), GLOW[frame % 2])
    if pose == "dizzy":
        return _stars(img, frame)
    if pose == "lunge":
        return _recolour(_shift(img, 0, 1 + frame % 2), lambda r, g, b: _shade(REDS, r, g, b))
    if pose == "shake":
        return _shift(img, (-1, 1)[frame % 2], 0)
    if pose == "death":
        return _dissolve(img, min(frame, DEATH_FRAMES - 1))
    return img


def image_text(img, flash: bool = False, snap: bool = False) -> Text:
    """Any RGBA image as half-block text. With `snap`, colours an effect made up (a flash, a tint, a grey) become
    the nearest colour the sprites are drawn in (see palette). Neighbouring cells alike are one run of text in one
    style: a fight's frame is a few hundred pieces rather than one a cell, which the screen lays out four times as
    fast, and a terminal or a browser is sent a quarter of (docs/plans/performance.md)."""
    pixels = img.load()
    width, height = img.size
    text = Text(no_wrap=True, overflow="crop")
    for y in range(0, height, 2):
        run: list[str] = []
        style = None
        for x in range(width):
            ch, cell = _cell(pixels[x, y], pixels[x, y + 1] if y + 1 < height else None, flash, snap)
            if run and cell is not style and cell != style:
                text.append("".join(run), style)
                run = []
            style = cell
            run.append(ch)
        if run:
            text.append("".join(run), style)
        if y + 2 < height:
            text.append("\n")
    return text


@lru_cache(maxsize=16384)
def _cell(top: tuple, bottom: tuple | None, flash: bool, snap: bool) -> tuple[str, Style | None]:
    """A cell's half-block and its style, from its two pixels (RGBA): the same few hundred pairs come up over and
    over, so each is worked out once."""
    upper = _colour(top, flash, snap)
    lower = _colour(bottom, flash, snap) if bottom is not None else None
    if upper and lower:
        return "▀", Style(color=upper, bgcolor=lower)
    if upper:
        return "▀", Style(color=upper)
    if lower:
        return "▄", Style(color=lower)
    return " ", None


def engrave(img, words: dict[int, str], ink: tuple = (24, 20, 37)) -> Text:
    """The image as half-block text with words carved into it (a name on a tombstone): each of `words` is centred on
    that row of cells, in `ink` on the colour of the stone beneath."""
    lines = image_text(img, snap=True).split("\n")
    pixels = img.load()
    for row, word in words.items():
        if not 0 <= row < len(lines) or not word:
            continue
        word = word[:img.width]
        start = (img.width - len(word)) // 2
        carved = lines[row][:start]
        for x, ch in enumerate(word, start):
            r, g, b, alpha = pixels[x, min(2 * row, img.height - 1)]
            stone = Color.from_rgb(*_nearest((r, g, b))) if alpha >= 128 else None
            carved.append(ch, Style(color=Color.from_rgb(*ink), bgcolor=stone))
        carved.append_text(lines[row][start + len(word):])
        lines[row] = carved
    return Text("\n", no_wrap=True, overflow="crop").join(lines)


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


# --- splash art: a floor's picture, on its card -------------------------------------

SPLASH_LEAST = 32  # the narrowest a splash is drawn, shrunk: on a screen too small for that, a card is words only


@lru_cache(maxsize=16)
def _splashes(key: str) -> tuple:
    """A theme's splash art in every size it comes in, widest first: the PNGs in data/splash/<key>/ (any names)."""
    folder = resources.files("ptg") / "data" / "splash" / key
    if Image is None or not folder.is_dir():
        return ()
    found = []
    for path in folder.iterdir():
        if path.name.endswith(".png"):
            with path.open("rb") as f:
                img = Image.open(f).convert("RGBA")
                img.load()
            found.append(img)
    return tuple(sorted(found, key=lambda img: img.width, reverse=True))


def splash_sizes(key: str) -> tuple:
    """The sizes, (width, height) in pixels, a theme's splash art comes in, widest first (none without any)."""
    return tuple(img.size for img in _splashes(key))


@lru_cache(maxsize=8)
def splash(key: str, width: int):
    """A theme's splash art `width` pixels across, or None: that size if it comes in it, else the next size up
    averaged down and snapped back to the palette. That's blurrier than a size made from the picture itself, so a card
    asks for one of splash_sizes when it can, and this only when the screen's too small for all of them."""
    for img in reversed(_splashes(key)):
        if img.width == width:
            return img
        if img.width > width:
            small = img.resize((width, max(2, round(width * img.height / img.width / 2) * 2)), Image.BOX)
            pixels = small.load()
            for y in range(small.height):
                for x in range(small.width):
                    r, g, b, alpha = pixels[x, y]
                    pixels[x, y] = (*_nearest((r, g, b)), 255 if alpha >= 128 else 0)
            return small
    return None


def splash_text(key: str, width: int) -> Text | None:
    """A theme's splash art `width` pixels across as half-block text (see splash), or None."""
    art = splash(key, width)
    return image_text(art, snap=True) if art is not None else None


# --- clips: a monster's own animations, made elsewhere --------------------------------

CLIP_FPS = 12  # the most frames a second the stage plays a clip at: each frame is the whole stage, sent to a browser


@dataclass(frozen=True)
class Clip:
    """One of a monster's animations at one size: its frames, the frames a second it was made for, and (for an
    entrance) the frame its feet land on, where the fight's sting goes (0: none)."""

    frames: tuple
    fps: float = CLIP_FPS
    land: int = 0

    @property
    def size(self) -> int:
        return self.frames[0].height


@lru_cache(maxsize=32)
def clips(key: str) -> dict[str, tuple[Clip, ...]]:
    """A monster's clips by name ("entrance", "idle"), each in every size it comes in, smallest first: the PNG strips
    in data/clips/<key>/, named <clip>.<size>.png, their frame count, frames a second and landing frame kept in the
    PNG's text. Most monsters have none: a clip is for the moments worth the work (docs/plans/combat-and-balance.md
    §4), and the code's own poses do for the rest."""
    folder = resources.files("ptg") / "data" / "clips" / key
    if Image is None or not folder.is_dir():
        return {}
    found: dict[str, list[Clip]] = {}
    for path in folder.iterdir():
        if not path.name.endswith(".png"):
            continue
        with path.open("rb") as f:
            sheet = Image.open(f)
            info = dict(sheet.info)
            count = count_frames(sheet, name=f"clips/{key}/{path.name}")
            sheet = sheet.convert("RGBA")
            sheet.load()
        width = sheet.width // count
        frames = tuple(sheet.crop((i * width, 0, (i + 1) * width, sheet.height)) for i in range(count))
        clip = Clip(frames, float(info.get("fps") or CLIP_FPS), int(info.get("land") or 0))
        found.setdefault(path.name.split(".")[0], []).append(clip)
    return {name: tuple(sorted(sizes, key=lambda c: c.size)) for name, sizes in found.items()}


def art_box(frames) -> tuple | None:
    """The box round the art in all of `frames` together (left, top, right, bottom), or None if they're empty."""
    boxes = [box for frame in frames if (box := frame.getbbox())]
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


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
    keys = keys or [*content.monsters, "campfire", "shrine", "fountain", "chest", "stairs", "mirror", "sunglasses",
                    "tombstone", "crown"]
    for key in keys:
        text = sprite_text(key)
        console.print(f"[bold]{key}[/]  ({frame_count(key)} frames)")
        console.print(text if text is not None else content.monsters.get(key).art if key in content.monsters else "?")


if __name__ == "__main__":
    main(sys.argv[1:])
