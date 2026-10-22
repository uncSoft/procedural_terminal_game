"""The Textual app: wires the screens together and owns the profile and narrator connection."""

from __future__ import annotations

from textual import work
from textual.app import App

from ..config import Config, load_game, save_config
from ..content import load_content
from ..game import Game
from ..llm import LLM, LLMError, make_llm
from ..meta import start_run
from ..profile import Profile
from .game_screen import GameScreen
from .hub import EndScreen, HubScreen
from .screens import IntroScreen, SetupScreen, TitleScreen, describe_backend
from .theme import CRT


class PTGApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "Procedural Terminal Game"

    def __init__(self, config: Config | None, seed: int | None = None, setup: bool = False,
                 resume: bool = False, daily: bool = False) -> None:
        super().__init__()
        self.needs_setup = config is None or setup
        self.config = config or Config()
        self.seed = seed
        self.resume = resume
        self.daily = daily
        self.profile = Profile.open()

    def on_mount(self) -> None:
        self.register_theme(CRT)
        self.theme = "crt"
        self.push_screen(TitleScreen())
        if self.needs_setup:
            self.push_screen(SetupScreen(self.config))
        elif self.resume and load_game() is not None:
            self.continue_game()
        elif self.daily:
            self.start_descent(daily=True)

    def save_settings(self, config: Config) -> None:
        self.config = config
        save_config(config)
        self.pop_screen()
        self.notify(f"Narrator: {describe_backend(config)}", title="Settings saved")

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
        first_time = self.profile.totals()["runs"] == 0
        screen = IntroScreen(game) if first_time else GameScreen(game, fresh=True)
        if isinstance(self.screen, HubScreen):
            self.switch_screen(screen)
        else:
            self.push_screen(screen)

    @work(exclusive=True, group="start")
    async def continue_game(self) -> None:
        state = load_game()
        if state is None:
            return
        llm = await self.connect()
        self.push_screen(GameScreen(Game(state, self.config, llm, profile=self.profile), fresh=False))

    def end_run(self, screen: GameScreen) -> None:
        self.switch_screen(EndScreen(screen.game.state))
        self.run_worker(screen.game.aclose())

    def leave_game(self, screen: GameScreen) -> None:
        self.pop_screen()
        self.run_worker(screen.game.aclose())
