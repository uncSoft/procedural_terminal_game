"""Turning a thing over: a window with its 3D model in it (ptg.model3d), drawn as you watch, that you turn with the
mouse or the keys. Drag it round, and let go with a flick to set it spinning; the arrows turn it and tip it toward you
or away; space starts or stops it turning on its own; + and - zoom, or the mouse wheel; r puts it back.

The pack opens one on anything that has a model (t, or the "Turn it over" under its words: see panels.InventoryScreen):
every item with a sprite has one, made from it (ptg/item_model.py: as it comes into the game). The debug screen's 3D
tab shows every one turning, the view without the window (ui/debug.py).

Where else a model turns, the sprite's place kept for it (its 2D art is still everywhere else: tiles, Here, the shop,
the stage, the story):

    FoundScreen     the first time a thing is ever yours (Game.first_finds): its card, the model big and turning
    the pack        the one you've picked, turning beside the shelf of tiles (panels.InventoryScreen)
    its card        a thing's card, a coloured word or a picture clicked (panels.InfoScreen)

    uv run python -m ptg.ui.model_view jar_o_light     # just the window, without a game
"""

from __future__ import annotations

import math
import sys
import time

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from .. import glossary, inventory, model3d, sound
from ..content import load_content
from ..game import Game
from ..sprites import image_text
from .panels import DIM, SOFT, WORDS, Clickable, Panel, Picture, box_rows, ornate, whereabouts
from .theme import CRT
from .widgets import power_lines

SPIN = 30.0  # degrees a second it turns on its own
SHOWN = 45.0  # how fast a thing turns where it's shown off (a card, the pack): a little brisker than in the window
CALM = 24  # frames a second a model's drawn at where it's beside other things (the pack, a card): as smooth as made
DRAG = 5.0  # degrees it turns for each column the mouse is dragged across it (and tips, for each row up or down)
FRICTION = 2.5  # how quickly a flicked spin dies away: by e^-FRICTION a second
TILT = (-30.0, 75.0)  # how far it tips: from a little below to nearly straight down on it
ZOOM = (0.6, 2.5)


class ModelView(Widget):
    """A model, drawn afresh many times a second: its animation playing (the bugs flying round the jar), and turned
    however you've turned it."""

    DEFAULT_CSS = """
    ModelView { width: 100%; height: 1fr; content-align: center middle; }
    """

    def __init__(self, key: str = "", spin: float = SPIN, fps: int = 0, **kwargs) -> None:
        super().__init__(**kwargs)
        self.model: model3d.Model | None = None
        self.spin = spin  # degrees a second it turns on its own
        self.fps = fps  # frames a second it's drawn at, at most (0: as many as its animation has)
        self.spinning = True
        self.swing = 0.0  # degrees a second it's still turning from a flick of the mouse
        self.dragging = False
        self.moved = 0.0  # when the mouse last turned it
        self.last = time.monotonic()
        self.picture = Text()
        if key:
            self.show(key)

    def show(self, key: str) -> None:
        """Another model in it (the debug screen's 3D tab shows one after another), from the front, turning."""
        self.model = model3d.load(key)
        self.started = time.monotonic()
        self.spinning = True
        self.reset()
        if self.is_mounted:
            self.tick()

    def reset(self) -> None:
        self.yaw, self.pitch, self.zoom, self.swing = 0.0, self.model.pitch, 1.0, 0.0

    def on_mount(self) -> None:
        fps = self.model.fps if self.model else 24
        self.set_interval(1 / min(fps, self.fps or fps), self.tick)
        self.tick()

    def tick(self) -> None:
        now = time.monotonic()
        step, self.last = now - self.last, now
        if self.model is None:
            return
        if not self.dragging:
            self.yaw += (self.spin if self.spinning else 0.0) * step + self.swing * step
            self.swing *= math.exp(-FRICTION * step)
        width, height = self.content_size
        if not width or not height or not self.is_on_screen:  # not laid out yet, or out of sight (another tab)
            return
        side = max(8, min(width, 2 * height))  # square, in pixels: two to a row of cells
        side -= side % 2
        frame = int((now - self.started) * self.model.fps)
        self.picture = image_text(model3d.render(self.model, frame, self.yaw, self.pitch, side, self.zoom))
        self.refresh()

    def render(self) -> Text:
        return self.picture

    # -- the mouse -------------------------------------------------------------------------------------------------

    def on_mouse_down(self, event: events.MouseDown) -> None:
        self.dragging, self.spinning, self.swing = True, False, 0.0
        self.capture_mouse()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if not self.dragging:
            return
        now = time.monotonic()
        turn = -event.delta_x * DRAG  # its front follows the mouse
        self.yaw += turn
        self.pitch = min(max(self.pitch + event.delta_y * DRAG, TILT[0]), TILT[1])
        self.swing = turn / max(now - self.moved, 1 / 60) if event.delta_x else self.swing
        self.moved = now

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self.dragging:
            self.dragging = False
            self.release_mouse()
            if time.monotonic() - self.moved > 0.12:  # held still before letting go: it stays put
                self.swing = 0.0

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        self.zoom_by(1.1)

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        self.zoom_by(1 / 1.1)

    def zoom_by(self, factor: float) -> None:
        self.zoom = min(max(self.zoom * factor, ZOOM[0]), ZOOM[1])


class ModelScreen(Panel):
    """A thing to turn over, in a window over the game."""

    BINDINGS = [Binding("left", "turn(-15)", show=False, priority=True),
                Binding("right", "turn(15)", show=False, priority=True),
                Binding("up", "tilt(10)", show=False, priority=True),
                Binding("down", "tilt(-10)", show=False, priority=True),
                Binding("space", "spin", "Spin", priority=True),
                Binding("plus,equals_sign", "zoom(1.15)", show=False),
                Binding("minus", "zoom(0.87)", show=False),
                Binding("r", "reset", "Reset", show=False)]
    size_class = "card"

    def __init__(self, key: str, title: str) -> None:
        super().__init__()
        self.key = key
        self.title = title

    def compose(self) -> ComposeResult:
        with Vertical(classes="panel-box model-box") as box:
            box.border_title = self.title
            yield ModelView(self.key, id="model-view")
            yield Static(Text("drag or arrows turn it · space spins · + - zoom · r resets · esc closes", style=DIM),
                         id="model-hint")

    @property
    def view(self) -> ModelView:
        return self.query_one(ModelView)

    def action_turn(self, step: float) -> None:
        """Its front toward the right (a positive step) or the left."""
        self.view.spinning = False
        self.view.swing = 0.0
        self.view.yaw -= step

    def action_tilt(self, step: float) -> None:
        """Tip its top toward you (a positive step: you see more of its lid) or away."""
        self.view.pitch = min(max(self.view.pitch + step, TILT[0]), TILT[1])

    def action_spin(self) -> None:
        self.view.spinning = not self.view.spinning
        self.view.swing = 0.0

    def action_zoom(self, factor: float) -> None:
        self.view.zoom_by(factor)

    def action_reset(self) -> None:
        self.view.reset()
        self.view.spinning = True


class FoundScreen(Panel):
    """The first time a thing is ever yours (Game.first_finds: taken, bought, won, given), its card: held up to the
    light, as a hero holds up what they've found, its model big and turning (drag it to turn it over yourself), with
    what it is and does and where it's gone. A thing with no model has its picture. Enter, space or a click carries
    on, and a turn's other finds have theirs after it."""

    BINDINGS = [Binding("enter,space", "close", "Carry on", priority=True),
                Binding("left", "turn(-20)", show=False, priority=True),
                Binding("right", "turn(20)", show=False, priority=True)]
    size_class = "card"
    opening_sound = None  # (its own fanfare)

    def __init__(self, game: Game, key: str) -> None:
        super().__init__()
        self.game = game
        self.key = key

    def compose(self) -> ComposeResult:
        content = self.game.content
        item = content.item(self.key)
        with Vertical(classes="panel-box found-box") as box:
            box.border_title = "Found"
            banner = Text("✧ ✦ ", style="bold #ffd166")
            banner.append(" NEW ", style="bold #10122a on #ffd166")
            banner.append(" ✦ ✧   ", style="bold #ffd166")
            banner.append(item.name, style="bold #4cff8a")
            yield Static(banner, id="found-banner")
            if self.turning:
                yield ModelView(self.key, spin=SHOWN, id="found-model")
            else:
                rows = max(8, box_rows(self.app.size.height) - 14)
                yield Picture(self.key, "item", 40, rows, content=content, sprites=self.game.config.art == "sprites",
                              id="found-picture")
            with VerticalScroll(id="found-words"):
                yield Static(self._words(), id="found-text")
            with Horizontal(classes="panel-action"):
                yield Clickable(Text(" ▶ Carry on  [enter] ", style="bold #ffb000"), action="screen.close",
                                classes="card-verb")
                hint = "drag it, or ← →, to turn it over" if self.turning else ""
                yield Static(Text(hint, style=DIM), id="found-hint")

    @property
    def turning(self) -> bool:
        """Whether it has a model to turn (sprites on): else its picture."""
        return model3d.available(self.key) and self.game.config.art == "sprites"

    def _words(self) -> Text:
        """What it is (its kind and what it does, its powers), its tale, and where it's gone now: your pack, your
        hand, your back, or a counter."""
        content, state = self.game.content, self.game.state
        item = content.item(self.key)
        text = Text(glossary.item_stats(item) + "\n", style=SOFT)
        text.append_text(power_lines(content, self.key))
        if item.desc:
            text.append(item.desc + "\n", style=f"italic {WORDS}")
        where = whereabouts(self.game, self.key)
        counter = inventory.PICKUPS.get(self.key)  # (a bomb or a small key: how many you have now)
        where += [f"{getattr(state.player, counter)} {counter} now"] if counter else []
        if where:
            text.append("\n→ " + " · ".join(where), style="#ffb000")
        text.rstrip()
        return text

    def on_mount(self) -> None:  # (Panel's own on_mount runs after this one: Textual calls each class's)
        box = self.box
        box.border_title = ornate(str(box.border_title))
        box.styles.border_title_align = "center"
        sound.play("rare_drop")

    def action_turn(self, step: float) -> None:
        for view in self.query(ModelView):
            view.spinning, view.swing = False, 0.0
            view.yaw -= step


class Preview(App):
    """Just the window, without a game: to look at a model."""

    CSS_PATH = "app.tcss"

    def __init__(self, key: str) -> None:
        super().__init__()
        self.key = key

    def on_mount(self) -> None:
        self.register_theme(CRT)
        self.theme = "crt"
        self.push_screen(ModelScreen(self.key, load_content().item(self.key).name), lambda _: self.exit())


if __name__ == "__main__":
    Preview(sys.argv[1] if len(sys.argv) > 1 else "jar_o_light").run()
