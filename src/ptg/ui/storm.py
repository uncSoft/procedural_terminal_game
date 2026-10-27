"""The title's storm on the screen: its frames (title_scene.py's colour grids) made once into ready-made lines, and a
widget that shows one frame or another without any work in between.

A frame of the storm is about 4,600 cells, each two pixels of its own two colours. Handed to a Static as text, every
frame was measured and laid out again (a quarter of a tenth of a second, on the screen's thread, six times a second),
and turning the picture into text in the first place took far longer: the rain hiccupped, and the thunder drifted
from the flash. Made once into Strips (runs of cells in the same two colours merged into one segment), a frame costs
nothing to show: StormView only hands Textual the lines it already has.
"""

from __future__ import annotations

from functools import lru_cache

from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip
from textual.widget import Widget

HALF = "▀"  # the top pixel in the foreground colour, the bottom one in the background colour


@lru_cache(maxsize=8192)
def _pair(top: str, bottom: str) -> Style:
    return Style(color=top, bgcolor=bottom)


def lines(grid: list[list[str]]) -> list[Strip]:
    """A frame's rows of colours as one Strip for each row of cells (two rows of pixels)."""
    out = []
    width = len(grid[0]) if grid else 0
    for y in range(0, len(grid) - 1, 2):
        segments, style, run = [], None, 0
        for top, bottom in zip(grid[y], grid[y + 1]):
            pair = _pair(top, bottom)
            if pair is style:
                run += 1
                continue
            if run:
                segments.append(Segment(HALF * run, style))
            style, run = pair, 1
        if run:
            segments.append(Segment(HALF * run, style))
        out.append(Strip(segments, width))
    return out


class StormView(Widget):
    """Shows a frame made by `lines`: show() swaps one for another, and the screen draws only that."""

    DEFAULT_CSS = """
    StormView {
        width: auto;
        height: auto;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.frame: list[Strip] = []

    def show(self, frame: list[Strip]) -> None:
        if frame is self.frame:
            return
        resized = not self.frame or len(frame) != len(self.frame) or \
            (frame and frame[0].cell_length != self.frame[0].cell_length)
        self.frame = frame
        self.refresh(layout=resized)

    def get_content_width(self, container, viewport) -> int:
        return self.frame[0].cell_length if self.frame else 0

    def get_content_height(self, container, viewport, width: int) -> int:
        return len(self.frame)

    def render_line(self, y: int) -> Strip:
        return self.frame[y] if y < len(self.frame) else Strip.blank(self.size.width)
