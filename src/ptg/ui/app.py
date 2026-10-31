"""The Textual app: wires the screens together and owns the profile and narrator connection."""

from __future__ import annotations

from collections.abc import Callable

from textual import events, work
from textual.app import App
from textual.binding import Binding
from textual.errors import NoWidget

from .. import sound
from ..config import Config, hosted, load_game, save_config, touch
from ..content import load_content
from ..game import Game
from ..llm import LLM, LLMError, make_llm
from ..meta import abandon, start_run
from ..profile import Profile
from . import collector
from .debug import DebugScreen
from .game_screen import GameScreen
from .tabs import game_screen
from .hub import EndScreen, HubScreen
from .screens import AbandonScreen, IntroScreen, SetupScreen, TitleScreen, describe_backend
from .theme import CRT
from .widgets import PHONE, TALL, TINY, WIDE


class PTGApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "Procedural Terminal Game"
    BINDINGS = [Binding("f8", "toggle_sound", "Sound"), Binding("f12", "debug", "Debug", show=False),
                Binding("ctrl+l", "redraw", "Redraw", show=False)]
    # How big the terminal is, as a class on every screen (a pop-up's too) to style it by in app.tcss: -phone, -narrow
    # or -wide, and -tiny, -short or -tall (see widgets.PHONE, WIDE, TALL and TINY).
    HORIZONTAL_BREAKPOINTS = [(0, "-phone"), (PHONE, "-narrow"), (WIDE, "-wide")]
    VERTICAL_BREAKPOINTS = [(0, "-tiny"), (TINY, "-short"), (TALL, "-tall")]
    REDRAW_EVERY = 6  # turns between the game's own redraws (see action_redraw)

    def __init__(self, config: Config | None, seed: int | None = None, setup: bool = False,
                 resume: bool = False, daily: bool = False, event: str | None = None, debug: bool = False,
                 test_room: tuple[str, str, int] | None = None) -> None:
        # No command palette by touch: a finger has no Ctrl+P, and the footer's key for it sat under the page's
        # keyboard button (on an iPad).
        self.ENABLE_COMMAND_PALETTE = not touch()
        super().__init__()
        self.needs_setup = config is None or setup
        self.config = config or Config()
        self.seed = seed
        self.resume = resume
        self.daily = daily
        self.event = event  # a story event to fire at the start of the next descent (for testing)
        self.open_debug = debug and not hosted()
        self.test_room = test_room  # (who, kit, floor): straight to a test room (see ptg/testrooms.py)
        self.profile = Profile.open()

    async def on_event(self, event: events.Event) -> None:
        """A mouse press on something that's just been taken away (a choice replaced as a turn ends) is dropped:
        Textual would start a text selection in it and crash on its missing parent (run 44, clicking a choice just
        as a Gelatinous Cube turned up)."""
        if isinstance(event, events.MouseDown) and not event.is_forwarded:
            try:
                widget, _ = self.get_widget_at(event.x, event.y)
            except NoWidget:
                widget = None
            if widget is not None and not widget.is_attached:
                return
        await super().on_event(event)

    def on_mount(self) -> None:
        collector.tune()  # (the garbage collector out of the frames' way: ui/collector.py)
        self.register_theme(CRT)
        self.theme = "crt"
        if sound.in_browser() and self.is_web:  # (ptg serve: the player's browser plays it)
            sound.to_browser(self._driver.write_meta)
        sound.configure(self.config.sound, self.config.volume / 100)
        self.push_screen(TitleScreen())
        if self.needs_setup:
            self.push_screen(SetupScreen(self.config))
        elif self.resume and load_game() is not None:
            self.continue_game()
        elif self.test_room:
            self.start_test_room(*self.test_room)
        elif self.daily:
            self.unfinished_first(lambda: self.start_descent(daily=True))
        if self.open_debug:
            self.push_screen(DebugScreen())

    def save_settings(self, config: Config) -> None:
        self.config = config
        save_config(config)
        sound.configure(config.sound, config.volume / 100)
        self.pop_screen()
        self.notify(f"Narrator: {describe_backend(config)}", title="Settings saved")

    def action_toggle_sound(self, again: str = "F8") -> None:
        """Sound on or off (F8, or the ☰ menu on a short screen: `again` is the one to say turns it back on)."""
        self.config = self.config.model_copy(update={"sound": not self.config.sound})
        save_config(self.config)
        engine = sound.configure(self.config.sound, self.config.volume / 100)
        if self.config.sound and not engine.enabled:
            self.notify("PTG_SOUND=0 is keeping it off.", title="Sound on")
        else:
            self.notify("" if self.config.sound else f"{again} turns it back on.",
                        title="Sound on" if self.config.sound else "Sound off", timeout=3)

    def action_redraw(self) -> None:
        """Wipe the terminal and draw every cell again, as a resize would. Some terminals (ones drawing with the
        GPU, like xterm.js in an editor or app panel) cache each character in each pair of colours, and the pixel
        art fills that cache fast; when it overflows, letters and art come out garbled or tiny. Sending the same
        screen again doesn't help, because they skip cells that haven't changed; wiping it first makes them redraw
        each one from scratch."""
        if self._driver is None or self.is_headless or not self._screen_stack or self._batch_count:
            return  # (mid-batch, nothing would be drawn after the wipe)
        screen = self.screen
        self._begin_update()  # a terminal that can, swaps the whole picture at once: no blank frame
        self._driver.write("\x1b[2J")
        self._display(screen, screen._compositor.render_update(full=True, screen_stack=self._background_screens))
        self._end_update()

    def action_debug(self) -> None:
        if hosted():  # it shows the model log and can point the server's narrator elsewhere
            return
        if not isinstance(self.screen, DebugScreen):  # on the debug screen, F12 closes it
            self.push_screen(DebugScreen())

    async def connect(self, quiet: bool = False) -> LLM | None:
        try:
            llm = make_llm(self.config)
            if llm is not None:
                await llm.prepare()
            return llm
        except LLMError as e:
            if not quiet:
                self.notify(f"{e}\nPlaying offline instead.", title="No narrator", severity="warning", timeout=8)
            return None

    def unfinished_first(self, then: Callable[[], None]) -> None:
        """Before a new run, with one still in progress: continue it, or abandon it (it ends as a death) and go on.
        Without asking, the new run's first save would wipe the old one out: no death, no souls, no ghost."""
        state = load_game()
        if state is None:
            then()
            return

        def answered(choice: str | None) -> None:
            if choice == "continue":
                self.continue_game()
            elif choice == "abandon":
                souls = abandon(self.profile, state)
                ghost = "" if state.daily else f" Your ghost stays on floor {state.floor}."
                self.notify(f"☽ {souls} soul{'' if souls == 1 else 's'} kept.{ghost}",
                            title=f"{state.player.name}'s run is over", timeout=6)
                then()

        self.push_screen(AbandonScreen(state), answered)

    def show_campfire(self) -> None:
        # Always land on: title -> campfire.
        while len(self.screen_stack) > 2:
            self.pop_screen()
        self.push_screen(HubScreen(self.profile))

    @work(exclusive=True, group="start")
    async def start_descent(self, daily: bool = False) -> None:
        llm = await self.connect()
        seed, self.seed = self.seed, None
        state = start_run(self.profile, load_content(), self.config.player_name, seed=seed, daily=daily)
        game = Game(state, self.config, llm, profile=self.profile)
        game.force_event, self.event = self.event, None
        first_time = self.profile.totals()["runs"] == 0
        screen = IntroScreen(game) if first_time else game_screen(game, True, *self.size)
        if isinstance(self.screen, HubScreen):
            self.switch_screen(screen)
        else:
            self.push_screen(screen)

    @work(exclusive=True, group="start")
    async def start_test_room(self, who: str, loadout: str = "random", floor: int = 0, seed: int | None = None) -> None:
        """A run next door to `who` that counts for nothing (see ptg/testrooms.py): your real run's save is safe."""
        from ..testrooms import build

        content = load_content()
        try:
            state = build(content, who, loadout, floor, name=self.config.player_name, seed=seed)
        except (ValueError, KeyError) as error:
            self.notify(str(error).strip("'\""), title="Can't make that test room", severity="error", timeout=8)
            return
        llm = await self.connect()
        stack = self.screen_stack  # from F12, out of a run first (it's saved as it was after its last turn)
        games = [i for i, s in enumerate(stack) if isinstance(s, GameScreen)]
        keep = games[0] if games else next((i for i, s in enumerate(stack) if isinstance(s, DebugScreen)), len(stack))
        for screen in stack[keep:]:
            if isinstance(screen, GameScreen):
                self.run_worker(screen.game.aclose())
        while len(self.screen_stack) > max(1, keep):
            self.pop_screen()
        self.push_screen(game_screen(Game(state, self.config, llm, content, self.profile), True, *self.size))
        self.notify("Nothing here counts: no save, no souls, nothing remembered. Esc twice to leave.",
                    title="A test room", timeout=6)

    @work(exclusive=True, group="start")
    async def continue_game(self) -> None:
        state = load_game()
        if state is None:
            return
        llm = await self.connect()
        self.push_screen(game_screen(Game(state, self.config, llm, profile=self.profile), False, *self.size))

    def end_run(self, screen: GameScreen) -> None:
        self.switch_screen(EndScreen(screen.game.state))
        self.run_worker(screen.game.aclose())

    def leave_game(self, screen: GameScreen) -> None:
        self.pop_screen()
        self.run_worker(screen.game.aclose())
