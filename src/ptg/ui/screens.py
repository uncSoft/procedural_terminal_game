"""Title, settings and intro screens."""

from __future__ import annotations

import random
import time

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Label, Select, Static

from .. import sound, title_scene
from ..config import (
    APPLE_HELP,
    DEFAULT_CLAUDE_MODEL,
    DEFAULT_URLS,
    Config,
    hosted,
    load_game,
    read_save,
)
from ..llm import LLMError
from ..llm.narrator import intro
from ..llm.openai_compat import OpenAICompatLLM
from ..meta import run_summary
from ..models import GameState
from . import storm
from .panels import Panel
from .storm import StormView
from .widgets import Clickable

CLAUDE_MODELS = [DEFAULT_CLAUDE_MODEL, "claude-sonnet-5-5", "claude-haiku-5-5"]

COMPACT_TITLE = """\
╔═╗┬─┐┌─┐┌─┐┌─┐┌┬┐┬ ┬┬─┐┌─┐┬    ╔╦╗┌─┐┬─┐┌┬┐┬┌┐┌┌─┐┬    ╔═╗┌─┐┌┬┐┌─┐
╠═╝├┬┘│ ││  ├┤  │││ │├┬┘├─┤│     ║ ├┤ ├┬┘│││││││├─┤│    ║ ╦├─┤│││├┤
╩  ┴└─└─┘└─┘└─┘─┴┘└─┘┴└─┴ ┴┴─┘   ╩ └─┘┴└─┴ ┴┴┘└┘┴ ┴┴─┘  ╚═╝┴ ┴┴ ┴└─┘"""
TITLE_WORDS = ((0, 30), (32, 54), (56, 68))  # where each word of the name is, in COMPACT_TITLE's columns


def stacked_title() -> str:
    """The name's three words one under another, each centred: for a screen too narrow for it in a line (a phone
    held upright)."""
    lines = [line.ljust(68) for line in COMPACT_TITLE.split("\n")]
    widest = max(b - a for a, b in TITLE_WORDS)
    return "\n".join(" " * ((widest - (b - a)) // 2) + line[a:b].rstrip() for a, b in TITLE_WORDS for line in lines)


STACKED_TITLE = stacked_title()


def describe_backend(config: Config) -> str:
    if config.backend == "offline":
        return "Offline (no AI narrator)"
    if config.backend == "anthropic":
        return f"Claude: {config.model or DEFAULT_CLAUDE_MODEL}"
    return f"{config.model or 'auto-detected model'} at {config.url}"


class TitleScreen(Screen):
    """The title: the castle in the storm (title_scene.py) under the game's name, and the menu in a row beneath it.
    The rain falls; every few seconds lightning strikes, the castle lights up, something stands on the ridge for as
    long as the flash lasts, and the thunder lands with it (or rolls in after, further off). The title's music loops
    while it shows. A screen too small for the picture shows just the name.

    Every frame is made before the storm starts (the rain's in each light, and several whole strikes, each with its
    own bolt, watcher and distance), all in a tenth of a second, as ready-made lines (ui/storm.py): from then on a
    beat only swaps one for another, so nothing the screen does waits on drawing, and the thunder keeps time."""

    BINDINGS = [Binding("n", "new", "Play"), Binding("c", "continue", "Continue"), Binding("s", "setup", "Settings")]
    BEAT = 0.15  # seconds a frame of the rain (served, slower: each frame goes down the wire to the browser)
    SERVED_BEAT = 0.4
    PHASES = 8  # the rain's frames, in turn
    STRIKES = 6  # strikes made ready, played in turn
    # A strike, frame by frame: (light, bolt, watcher, seconds). A first flicker, a moment's dark, the flash itself,
    # its afterglow, and the dark again.
    STRIKE = ((title_scene.BRIGHT, True, False, 0.07), (title_scene.DARK, False, False, 0.06),
              (title_scene.FLASH, True, True, 0.14), (title_scene.BRIGHT, False, True, 0.2),
              (title_scene.DIM, False, False, 0.45))
    FLASH_AT = 0.13  # when the flash comes, from the strike's start: what the thunder's timed to
    THUNDER_AFTER = (0.0, 0.35, 0.9)  # how long after the flash the thunder comes, struck close, near or far
    CHROME = 13  # rows besides the picture: the name, the tagline, the menu, what's under it, the footer
    STACKED_CHROME = 23  # the same on a phone held upright: the name in three lines, the menu two by two
    TEXT_SIZE = "Text too small or too big? Cmd + or − (Ctrl on Windows) in a browser; your terminal's own font " \
        "size in a terminal."  # (a served game's page takes ?fontsize= too: web/app_index.html)
    LEAST_ROWS = 10  # a picture any smaller isn't worth the room

    def __init__(self) -> None:
        super().__init__()
        self.scene: title_scene.Scene | None = None
        self.frames: dict[tuple, list] = {}  # (light, phase) -> the rain's frame in that light
        self.strikes: list[dict] = []  # each strike's frames, by (light, bolt, watcher), and how far off it is
        self.strike: dict | None = None  # the one playing
        self.phase = 0
        self.steps: list[tuple] = []  # what's left of the strike playing
        self.next_strike = 0.0
        self.played = 0
        self.rng = random.Random()

    def compose(self) -> ComposeResult:
        with Vertical(id="title-wrap"):
            yield Center(Static(Text(COMPACT_TITLE), id="splash"))
            yield Center(StormView(id="title-scene"))
            yield Center(Static("A dungeon that listens. Type anything.", id="tagline"))
            with Center():
                with Horizontal(id="menu"):
                    yield Button("Play", id="new", variant="primary")
                    yield Button("Continue", id="continue")
                    yield Button("Settings", id="setup")
                    yield Button("Quit", id="quit", variant="error")
            yield Center(Static("", id="run-info"))
            yield Center(Static("", id="narrator-info"))
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_menu()
        self.fit_scene()
        self.set_interval(self.SERVED_BEAT if hosted() else self.BEAT, self.beat, name="storm")
        sound.music("title_music")

    def on_screen_resume(self) -> None:
        self.refresh_menu()
        sound.music("title_music", fade_in=1.0)

    def on_screen_suspend(self) -> None:
        sound.stop_music(only=("title_music",))  # (the game's own may have started already)

    def on_unmount(self) -> None:
        sound.stop_music(only=("title_music",))

    def on_resize(self) -> None:
        self.fit_scene()

    # --- the storm ---

    def fit_scene(self) -> None:
        """The picture as big as the screen has room for under the name and over the menu, or none at all; its
        first frame now, the rest made ready in the background."""
        stacked = self.app.size.width < len(COMPACT_TITLE.split("\n")[0]) + 2  # (the name in a line doesn't fit)
        self.query_one("#splash", Static).update(Text(STACKED_TITLE if stacked else COMPACT_TITLE))
        width = min(self.app.size.width - 4, 160)
        rows = min(self.app.size.height - (self.STACKED_CHROME if stacked else self.CHROME), width // 3)
        roomy = rows >= self.LEAST_ROWS and self.app.config.art == "sprites"
        scene = title_scene.scene(width, 2 * rows) if roomy else None
        view = self.query_one("#title-scene", StormView)
        view.display = scene is not None
        if scene is self.scene:
            return
        self.scene, self.frames, self.strikes, self.steps, self.strike = scene, {}, [], [], None
        if scene is not None:
            self.frames[(title_scene.DARK, 0)] = storm.lines(scene.grid(title_scene.DARK, 0))
            self.next_strike = time.monotonic() + 1.5
            self.make_ready(scene)
        self.show()

    @work(thread=True, exclusive=True, group="storm")
    def make_ready(self, scene: title_scene.Scene) -> None:
        """Every frame of the storm: the rain's in each light, then STRIKES strikes' own (off the screen's thread,
        a tenth of a second all told)."""
        frames = {}
        for light in title_scene.LIGHTS:
            for phase in range(self.PHASES):
                frames[(light, phase)] = storm.lines(scene.grid(light, self.rain(scene, phase)))
        strikes = []
        for _ in range(self.STRIKES):
            scene.strike(self.rng.randrange(1_000_000))
            strikes.append({"distance": scene.distance, "frames": {
                (light, bolt, watcher): storm.lines(scene.grid(light, 0, bolt, watcher))
                for light, bolt, watcher, _ in self.STRIKE if bolt or watcher}})
        if scene is self.scene:
            self.frames, self.strikes = frames, strikes

    def rain(self, scene: title_scene.Scene, phase: int) -> int:
        """How far the rain's fallen at a phase: the eight phases fall the whole height, so they loop."""
        return round(phase * scene.h / self.PHASES)

    def beat(self) -> None:
        """A beat of the storm: the rain falls a step, or a strike starts when it's due (its frames keep their own
        time: next_step)."""
        if self.scene is None or self.app.screen is not self or self.steps or not self.strikes:
            return
        self.phase = (self.phase + 1) % self.PHASES
        now = time.monotonic()
        if now >= self.next_strike:
            self.strike = self.strikes[self.played % len(self.strikes)]
            self.played += 1
            self.steps = list(self.STRIKE)
            self.set_timer(self.steps[0][3], self.next_step)
            # The thunder: struck close, its crack lands with the flash (played as far ahead as the sound takes to
            # reach the speakers); further off, it rolls in after it, and softer (build_sounds' three thunders).
            distance = self.strike["distance"]
            delay = self.FLASH_AT + self.THUNDER_AFTER[distance] - sound.LEAD
            self.set_timer(max(0.01, delay), lambda: sound.play("thunder", distance))
            self.next_strike = now + self.rng.uniform(4.5, 9.0)
        self.show()

    def next_step(self) -> None:
        """A strike's next frame, after the last one's time."""
        if self.steps:
            self.steps.pop(0)
        if self.steps:
            self.set_timer(self.steps[0][3], self.next_step)
        self.show()

    def show(self) -> None:
        """The frame for now: the strike's, if one's playing, else the rain's; the name flashes with it."""
        if self.scene is None:
            return
        light, bolt, watcher = self.steps[0][:3] if self.steps else (title_scene.DARK, False, False)
        frame = None
        if (bolt or watcher) and self.strike:
            frame = self.strike["frames"].get((light, bolt, watcher))
        frame = frame or self.frames.get((light, self.phase)) or self.frames.get((title_scene.DARK, 0))
        if frame:
            self.query_one("#title-scene", StormView).show(frame)
        self.query_one("#splash", Static).set_class(light == title_scene.FLASH, "lit")

    # --- the menu ---

    def refresh_menu(self) -> None:
        """With a run in progress, Continue comes first, chosen, with the run beneath the menu; Play becomes New
        run."""
        state, problem = read_save()
        menu, info = self.query_one("#menu"), self.query_one("#run-info", Static)
        play, resume = self.query_one("#new", Button), self.query_one("#continue", Button)
        resume.disabled = state is None
        if state:
            menu.move_child(resume, before=play)
        else:
            menu.move_child(resume, after=play)
        info.display = bool(state or problem)
        if state:
            info.update(Text("  ·  ".join(run_summary(state))))
        elif problem:
            info.update(Text(f"Your last run can't be continued: {problem}."))
        first, second = (resume, play) if state else (play, resume)
        first.variant, second.variant = "primary", "default"
        play.label = "New run" if state else "Play"
        first.focus()
        info = Text(f"Narrator: {describe_backend(self.app.config)}")
        info.append(f"\n{self.TEXT_SIZE}", style="#6c6f99")
        self.query_one("#narrator-info", Static).update(info)

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        {"new": self.action_new, "continue": self.action_continue, "setup": self.action_setup,
         "quit": self.app.exit}[event.button.id]()

    def action_new(self) -> None:
        self.app.unfinished_first(self.app.show_campfire)

    def action_continue(self) -> None:
        if load_game() is not None:
            self.app.continue_game()

    def action_setup(self) -> None:
        self.app.push_screen(SetupScreen(self.app.config))


class AbandonScreen(Panel):
    """A new run with one still in progress: continue it, or abandon it, and it ends as a death."""

    size_class = "small"

    def __init__(self, state: GameState) -> None:
        super().__init__()
        self.state = state

    def compose(self) -> ComposeResult:
        state = self.state
        ghost = "" if state.daily else f", and your ghost stays on floor {state.floor}"
        with Vertical(classes="panel-box abandon-box") as box:
            box.border_title = "Your run isn't over"
            yield Static(Text("\n".join(run_summary(state)), style="bold #e8e8f4"), classes="abandon-run")
            yield Static(Text(f"A new run ends this one here, as a death: you keep its souls, it goes in the Hall "
                              f"of Legends{ghost}.", style="#c8c8e0"))
            with Horizontal(classes="abandon-buttons"):
                yield Button("Continue it", id="keep", variant="primary")
                yield Button("Abandon it", id="abandon", variant="error")

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        self.dismiss("continue" if event.button.id == "keep" else "abandon")


class SetupScreen(Screen):
    BINDINGS = [Binding("ctrl+s", "save", "Save"), Binding("escape", "cancel", "Back")]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        config = self.config
        if config.backend == "openai":
            preset = next((k for k, url in DEFAULT_URLS.items() if url == config.url), "openai")
        else:
            preset = config.backend
        # Compact widgets and a scrolling wrapper keep the Save button reachable in short terminals.
        with VerticalScroll(id="setup-wrap"):
            with Vertical(id="setup-box") as box:
                box.border_title = "Settings"
                yield Label("Your name")
                yield Input(config.player_name, id="name", compact=True)
                yield Label("Narrator", classes="local")
                yield Select([("LM Studio (local)", "lmstudio"), ("Ollama (local)", "ollama"),
                              ("Apple Intelligence (on this Mac, via apfel)", "apple"),
                              ("Other OpenAI-compatible server", "openai"), ("Claude API", "anthropic"),
                              ("Offline (no AI)", "offline")], value=preset, allow_blank=False, id="backend",
                             compact=True, classes="local")
                yield Label("Server URL", classes="local")
                yield Input(config.url, id="url", compact=True, classes="local")
                yield Label("Model", classes="local")
                yield Select([], prompt="Auto-detect", id="model", compact=True, classes="local")
                yield Label("API key (optional for local servers)", classes="local")
                yield Input(config.api_key, password=True, id="api_key", compact=True, classes="local")
                yield Label("Art")
                yield Select([("Pixel sprites", "sprites"), ("ASCII art", "ascii")], value=config.art,
                             allow_blank=False, id="art", compact=True)
                yield Label("Game screen")
                yield Select([("Tabs beside the story", "tabs"), ("Grid: map, Here and big buttons", "grid"),
                              ("Classic", "classic")], value=config.layout, allow_blank=False, id="layout",
                             compact=True)
                yield Label("Dice")
                yield Select([("Press Space to roll (dramatic)", "manual"), ("Roll automatically", "auto")],
                             value="auto" if config.auto_roll else "manual", allow_blank=False, id="dice",
                             compact=True)
                yield Label("Boss entrances")
                yield Select([("Big, over the whole screen first", "big"), ("On the stage only", "stage")],
                             value="big" if config.boss_intros else "stage", allow_blank=False, id="intros",
                             compact=True)
                yield Label("Sound (F8 turns it on and off)")
                with Horizontal(id="setup-sound"):
                    yield Select([("On", "on"), ("Off", "off")], value="on" if config.sound else "off",
                                 allow_blank=False, id="sound", compact=True)
                    yield Select([(f"{v}%", v) for v in (25, 50, 70, 100)],
                                 value=min((25, 50, 70, 100), key=lambda v: abs(v - config.volume)),
                                 allow_blank=False, id="volume", compact=True)
                yield Static("", id="setup-status")
                with Horizontal(id="setup-buttons"):
                    yield Button("Save", id="save", variant="primary")
                    yield Button("Detect models", id="detect", classes="local")
                    yield Button("Back", id="back")
        yield Footer()

    def on_mount(self) -> None:
        if hosted():  # the narrator is the server's (not a player's to point elsewhere)
            for widget in self.query(".local"):
                widget.display = False
            return
        self.update_fields(self.query_one("#backend", Select).value, initial=True)

    @on(Select.Changed, "#backend")
    def backend_changed(self, event: Select.Changed) -> None:
        self.update_fields(event.value)

    def update_fields(self, preset: str, initial: bool = False) -> None:
        url = self.query_one("#url", Input)
        url.disabled = preset in ("anthropic", "offline")
        if preset in DEFAULT_URLS and not initial:
            url.value = DEFAULT_URLS[preset]
        model = self.query_one("#model", Select)
        if preset == "anthropic":
            model.set_options([(m, m) for m in CLAUDE_MODELS])
            model.value = self.config.model if self.config.model in CLAUDE_MODELS else DEFAULT_CLAUDE_MODEL
        elif preset == "offline":
            model.set_options([])
        else:
            current = self.config.model if self.config.backend == "openai" else ""
            model.set_options([(current, current)] if current else [])
            if current:
                model.value = current
            self.detect_models()

    @work(exclusive=True)
    async def detect_models(self) -> None:
        status = self.query_one("#setup-status", Static)
        status.update("Looking for models...")
        llm = OpenAICompatLLM(self.query_one("#url", Input).value, api_key=self.query_one("#api_key", Input).value)
        try:
            models = await llm.list_models()
        except LLMError as e:
            apple = self.query_one("#backend", Select).value == "apple"
            status.update(Text(f"Can't reach the server: {e}" + (f"\n{APPLE_HELP}." if apple else "")))
            return
        finally:
            await llm.aclose()
        select = self.query_one("#model", Select)
        previous = select.value
        select.set_options([(m, m) for m in models])
        if previous in models:
            select.value = previous
        status.update(Text(f"Found {len(models)} model(s). Leave it on auto-detect to use the loaded one." if models
                           else "The server is up but has no chat models."))

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "detect":
            self.detect_models()
        elif event.button.id == "back":
            self.action_cancel()
        elif event.button.id == "save":
            self.action_save()

    def action_save(self) -> None:
        preset = self.query_one("#backend", Select).value
        model = self.query_one("#model", Select).value
        narrator = {} if hosted() else {
            "backend": "openai" if preset in ("lmstudio", "ollama", "apple", "openai") else preset,
            "url": self.query_one("#url", Input).value.strip() or DEFAULT_URLS["lmstudio"],
            "model": "" if model is Select.BLANK else str(model),
            "api_key": self.query_one("#api_key", Input).value.strip(),
        }
        config = self.config.model_copy(update={
            "player_name": self.query_one("#name", Input).value.strip() or "Adventurer",
            **narrator,
            "auto_roll": self.query_one("#dice", Select).value == "auto",
            "boss_intros": self.query_one("#intros", Select).value == "big",
            "art": self.query_one("#art", Select).value,
            "layout": self.query_one("#layout", Select).value,
            "sound": self.query_one("#sound", Select).value == "on",
            "volume": self.query_one("#volume", Select).value,
        })
        self.app.save_settings(config)

    def action_cancel(self) -> None:
        if len(self.app.screen_stack) > 2:
            self.app.pop_screen()


class IntroScreen(Screen):
    BINDINGS = [Binding("enter", "begin", "Begin"), Binding("escape", "begin", "Skip")]

    def __init__(self, game) -> None:
        super().__init__()
        self.game = game
        self.text = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="intro-wrap"):
            with Vertical(id="intro-box") as box:
                box.border_title = "A Message From The Void"
                yield Static(Text("The void clears its throat...", style="italic"), id="intro-text")
                yield Clickable("▶ Press Enter, or click here, to begin your descent", action="screen.begin",
                                id="intro-hint")
        yield Footer()

    def on_mount(self) -> None:
        self.speak()

    @work(exclusive=True)
    async def speak(self) -> None:
        widget = self.query_one("#intro-text", Static)

        def on_text(chunk: str) -> None:
            self.text += chunk
            widget.update(Text(self.text))

        final = await intro(self.game.llm, self.game.state.player.name, self.game.theme.name, on_text)
        widget.update(Text(final))

    def action_begin(self) -> None:
        from .tabs import game_screen

        self.app.switch_screen(game_screen(self.game, True, *self.app.size))
