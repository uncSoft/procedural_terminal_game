"""The art layer (docs/plans/mobile-view.md §2): on the web, a picture is drawn as an image over the cells it would
have filled, at its own pixels, instead of in half blocks (two pixels a cell). The game sends the page the image and
where it goes, in cells, through the side channel the browser sound uses (Textual's web driver's write_meta, passed on
by ptg serve's on_meta); the page draws it on a canvas over those cells (web/app_index.html). The cells under it hold
a plain block of the picture's ground, so the terminal sends next to nothing for them.

On when ptg serve says so (PTG_ART=web) and the game is on the web; a terminal keeps half blocks. A picture's widget
asks `active`, draws `placeholder` into its cells, and `show`s each frame; `hide` takes it away (a screen closing, a
fight's moment playing in half blocks for now)."""

from __future__ import annotations

import base64
import io
import os

from rich.style import Style
from rich.text import Text

MESSAGE = "ptg_art"  # the game's message to ptg serve, passed on to the page
SCALE = 4  # art pixels to a cell's width on the web (twice that to its height: square pixels); the page fits them
GROUND = "#0e0c1a"  # the cells under a picture


def active(app) -> bool:
    """Whether pictures go to the page as images: served (ptg serve sets PTG_ART=web) and on the web."""
    return os.environ.get("PTG_ART") == "web" and bool(getattr(app, "is_web", False))


def placeholder(columns: int, rows: int, ground: str = GROUND) -> Text:
    """The cells a picture covers: a block of its ground, `columns` by `rows`."""
    line = Text(" " * max(1, columns), style=Style(bgcolor=ground))
    return Text("\n").join([line] * max(1, rows))


def png(image) -> str:
    """An image as the page takes it: PNG, in base 64 (a stage's frame is a few kilobytes: mobile-view.md §2)."""
    out = io.BytesIO()
    image.save(out, "PNG", optimize=False)
    return base64.b64encode(out.getvalue()).decode()


def _send(app, message: dict) -> None:
    driver = getattr(app, "_driver", None)
    write = getattr(driver, "write_meta", None)
    if write is not None:
        write({"type": MESSAGE, **message})


def show(app, art_id: str, widget, image, chips: list | None = None, rows: int | None = None,
         fill: bool = False) -> None:
    """`image` (or its `png`, made ready) drawn over `widget`'s cells (where it is on the screen now; its first `rows`
    of them, if said), fitted to them, its pixels kept square and sharp, or with `fill`, stretched to them all (a
    picture drawn for cells two pixels tall, as the half blocks would have stretched it); `chips`, words over it (a
    foe's next move: (column, row, words, ground, ink) inside the widget)."""
    region = widget.content_region
    height = region.height if rows is None else min(rows, region.height)
    if not region.width or height <= 0:
        return
    _send(app, {"do": "show", "id": art_id, "region": [region.x, region.y, region.width, height],
                "screen": [app.size.width, app.size.height], "png": image if isinstance(image, str) else png(image),
                "chips": chips or [], "fill": fill})


def hide(app, art_id: str) -> None:
    """The picture `art_id` taken away (its widget's gone, or covered, or showing half blocks for a moment)."""
    _send(app, {"do": "hide", "id": art_id})
