"""A creature watched up close (JT: "tapping the bosses showing the higher res animations, as well as in the
bestiary"): tapped on the stage in a fight, in any layout, or its picture in the bestiary. Its own animations play at
the biggest size the screen has room for, one after another, its entrance, its idle, its attack, its windup; its name,
what it is (MonsterDef.epithet) and which animation this is under them. A tap on it plays the next; a tap outside it,
Esc or Enter closes it. A creature without animations of its own stands in its poses (sprites.posed), as big as fits.
In a terminal it's drawn in half blocks; on the web the art layer draws it at its own pixels (ui/art_layer.py)."""

from __future__ import annotations

from functools import lru_cache
from typing import ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Click
from textual.screen import ModalScreen
from textual.widgets import Static

from .. import sprites
from ..content import Content
from . import art_layer
from .effects import show_frame

PLAYLIST = (("entrance", 1), ("idle", 2), ("attack", 1), ("windup", 2))  # (its clip, times through) in turn
POSES = ("idle", "windup", "dizzy", "lunge")  # what a creature without clips stands in, a beat each
POSE_BEATS = 18  # frames a pose holds (at sprites.CLIP_FPS)
BACK = (14, 12, 26)  # what it's drawn on
WORDS_ROWS = 4  # under it: its name, what it is, which animation, how to go on


@lru_cache(maxsize=64)
def window(key: str, size: int) -> tuple[int, int]:
    """The columns a creature's clips at `size` use, all of them together (a frame is mostly the room it drops in from
    and swings through): from the leftmost pixel any frame draws to the rightmost."""
    boxes = [box for sizes in sprites.clips(key).values() for clip in sizes if clip.size == size
             for frame in clip.frames if (box := frame.getbbox())]
    return (min(b[0] for b in boxes), max(b[2] for b in boxes)) if boxes else (0, size)


def biggest(key: str, columns: int, rows: int) -> int:
    """The biggest size of a creature's clips whose frames (as much of them as anything uses: window) fit `columns`
    across and `rows` rows down (two pixels a row); else its smallest, if that's short enough (its middle shown);
    0 if it has none."""
    sizes = sorted({clip.size for clip in sprites.clips(key).get("idle", ())}, reverse=True)
    for size in sizes:
        left, right = window(key, size)
        if size <= 2 * rows and right - left <= columns:
            return size
    return sizes[-1] if sizes and sizes[-1] <= 2 * rows else 0


def cropped(frame, left: int, right: int, columns: int):
    """A clip's frame cut to the columns its clips use, and to `columns` round their middle if that's still too wide."""
    if right - left > columns:
        middle = (left + right) // 2
        left, right = middle - columns // 2, middle - columns // 2 + columns
    return frame.crop((max(0, left), 0, min(frame.width, right), frame.height))


def on_back(image):
    """A frame on the viewer's ground (its transparent parts aren't the terminal's own colour)."""
    ground = sprites.Image.new("RGBA", image.size, (*BACK, 255))
    ground.alpha_composite(image.convert("RGBA"))
    return ground


class CreatureView(ModalScreen[None]):
    """The creature up close (see the module's docstring)."""

    DEFAULT_CSS = """
    CreatureView { align: center middle; background: #070814 85%; }
    CreatureView #creature-box { width: auto; height: auto; max-width: 100%; max-height: 100%; padding: 0 1;
                                 background: #0e0c1a; border: round #6c8cff; }
    CreatureView #creature-art { width: auto; height: auto; }
    CreatureView .creature-words { width: 100%; height: auto; text-align: center; }
    """
    BINDINGS: ClassVar = [Binding("escape,enter,q", "close", "Close", show=False),
                          Binding("space,right", "next", "Next", show=False)]

    def __init__(self, content: Content, key: str, name: str = "") -> None:
        super().__init__()
        self.content, self.key = content, key
        monster = content.monster(key)
        self.creature = name or monster.name
        self.epithet = monster.epithet
        self.playlist: list[tuple[str, int]] = []
        self.clips: dict = {}
        self.poses: list = []
        self.place, self.frame, self.times = 0, 0, 0
        self.shown = None
        self.crop: tuple | None = None  # (the columns its clips use, from and to; the most it may take)
        self.last = None  # the frame shown last (a pose holds one: it isn't drawn again)
        self.web = False  # the art layer draws it (on the web), its cells (columns, rows) a block under it
        self.cells = (0, 0)

    def compose(self) -> ComposeResult:
        with Vertical(id="creature-box"):
            yield Static(id="creature-art")
            yield Static(classes="creature-words", id="creature-name")
            yield Static(classes="creature-words", id="creature-playing")

    def on_mount(self) -> None:
        width, height = self.app.size
        columns, rows = width - 6, height - 4 - WORDS_ROWS  # (less its frame and padding, and the words under it)
        self.web = art_layer.active(self.app)
        if self.web:  # (the whole room for it, the biggest clip that fits at the layer's pixels: the page fits it)
            self.cells = (columns, rows)
            columns, rows = columns * art_layer.SCALE, rows * art_layer.SCALE
        size = biggest(self.key, columns, rows)
        self.crop = (*window(self.key, size), columns) if size else None
        if size:
            self.clips = {name: next(c for c in sizes if c.size == size)
                          for name, sizes in sprites.clips(self.key).items() if any(c.size == size for c in sizes)}
            self.playlist = [(name, times) for name, times in PLAYLIST if name in self.clips]
        else:
            found = sprites._strip(self.key) or ()
            box = sprites.art_box(found) if found else None
            if box:
                w, h = box[2] - box[0], box[3] - box[1]
                scale = max(1, min(4, columns // max(1, w), (2 * rows) // max(1, h)))
                self.poses = [sprites.posed(found[0], pose, 0).crop(box).resize((w * scale, h * scale),
                                                                                 sprites.Image.NEAREST)
                              for pose in POSES]
            self.playlist = [(pose, 1) for pose in POSES[:len(self.poses)]]
        name = Text(self.creature, style="bold #ffb000")
        if self.epithet:
            name.append(f"\n{self.epithet}", style="italic #e8dcb2")
        self.query_one("#creature-name", Static).update(name)
        self.refresh_playing()
        self.tick()
        self.set_interval(1 / sprites.CLIP_FPS, self.tick)

    def frames(self) -> tuple:
        """The frames of what's playing now."""
        if not self.playlist:
            return ()
        name = self.playlist[self.place][0]
        if self.clips:
            return self.clips[name].frames
        return (self.poses[self.place],) * POSE_BEATS

    def tick(self) -> None:
        """The next frame; at the end of a clip, again (as many times as the playlist says), then the next clip."""
        frames = self.frames()
        if not frames:
            self.query_one("#creature-art", Static).update(Text("(no picture yet)", style="#6c6f99"))
            return
        if self.frame >= len(frames):
            self.frame, self.times = 0, self.times + 1
            if self.times >= self.playlist[self.place][1]:
                self.advance()
                frames = self.frames()
        source = frames[self.frame]
        if source is self.last and self.shown is not None:  # (a pose held: nothing new to draw or send)
            self.frame += 1
            return
        self.last = source
        image = on_back(cropped(source, *self.crop) if self.clips else source)
        art = self.query_one("#creature-art", Static)
        if self.web:
            if self.shown is None:
                self.shown = show_frame(art, art_layer.placeholder(*self.cells), self.shown)
            art_layer.show(self.app, "creature", art, image)
        else:
            self.shown = show_frame(art, sprites.image_text(image), self.shown)
        self.frame += 1

    def advance(self) -> None:
        self.place, self.frame, self.times = (self.place + 1) % len(self.playlist), 0, 0
        self.refresh_playing()

    def refresh_playing(self) -> None:
        line = Text()
        for i, (name, _) in enumerate(self.playlist):
            line.append(f" {name} ", style="bold #10122a on #6c8cff" if i == self.place else "#6c6f99")
        line.append("\ntap it for the next · tap outside or Esc to close", style="#6c6f99")
        self.query_one("#creature-playing", Static).update(line)

    def action_next(self) -> None:
        if self.playlist:
            self.advance()

    def action_close(self) -> None:
        self.dismiss(None)

    def on_click(self, event: Click) -> None:
        box = self.query_one("#creature-box")
        if box.region.contains(event.screen_x, event.screen_y):
            self.action_next()
        else:
            self.action_close()

    def on_unmount(self) -> None:
        art_layer.hide(self.app, "creature")
