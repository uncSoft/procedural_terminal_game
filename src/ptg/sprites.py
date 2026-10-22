"""Pixel-art sprites drawn with half-block characters.

Each terminal cell shows two pixels: "▀" in the top pixel's colour on a background of the bottom pixel's
colour. That works in any terminal with 24-bit colour, inside Textual's layout, with no image protocol.
Sprites are PNG strips in ptg/data/sprites (frames side by side, square, transparent background); anything
without a sprite, or a player who prefers it, gets the ASCII art instead.

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


@lru_cache(maxsize=128)
def frames(key: str, width: int = DEFAULT_WIDTH) -> tuple | None:
    """The frames of a sprite, scaled (nearest neighbour) to `width` pixels wide, or None if there isn't one."""
    if Image is None:
        return None
    path = resources.files("ptg") / "data" / "sprites" / f"{key}.png"
    if not path.is_file():
        return None
    with path.open("rb") as f:
        sheet = Image.open(f).convert("RGBA")
        sheet.load()
    size = sheet.height
    count = max(1, sheet.width // size)
    out = []
    for i in range(count):
        frame = sheet.crop((i * size, 0, (i + 1) * size, size))
        if frame.width != width:
            frame = frame.resize((width, width), Image.NEAREST)
        out.append(frame)
    return tuple(out)


def frame_count(key: str) -> int:
    found = frames(key)
    return len(found) if found else 0


@lru_cache(maxsize=256)
def _render(key: str, frame: int, width: int, flash: bool) -> Text | None:
    found = frames(key, width)
    if not found:
        return None
    img = found[frame % len(found)]
    pixels = img.load()
    text = Text(no_wrap=True, overflow="crop")
    for y in range(0, img.height, 2):
        for x in range(img.width):
            top = _colour(pixels[x, y], flash)
            bottom = _colour(pixels[x, y + 1], flash) if y + 1 < img.height else None
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


def _colour(pixel: tuple, flash: bool) -> Color | None:
    r, g, b, alpha = pixel
    if alpha < 128:
        return None
    if flash:  # a white hit-flash that keeps a hint of the original colour
        r, g, b = (255 - (255 - r) // 4, 255 - (255 - g) // 4, 255 - (255 - b) // 4)
    return Color.from_rgb(r, g, b)


def sprite_text(key: str, frame: int = 0, width: int = DEFAULT_WIDTH, flash: bool = False) -> Text | None:
    """The sprite as Rich text, or None so the caller can fall back to ASCII art."""
    text = _render(key, frame, width, flash)
    return text.copy() if text is not None else None


def main(keys: list[str]) -> None:
    from rich.console import Console

    from .content import load_content

    console = Console()
    content = load_content()
    keys = keys or [*content.monsters, "campfire"]
    for key in keys:
        text = sprite_text(key)
        console.print(f"[bold]{key}[/]  ({frame_count(key)} frames)")
        console.print(text if text is not None else content.monsters.get(key).art if key in content.monsters else "?")


if __name__ == "__main__":
    main(sys.argv[1:])
