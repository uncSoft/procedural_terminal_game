"""Title, settings and intro screens."""

from __future__ import annotations

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Label, Select, Static

from ..config import DEFAULT_CLAUDE_MODEL, DEFAULT_URLS, Config, load_game
from ..content import load_content
from ..llm import LLMError
from ..llm.narrator import intro
from ..llm.openai_compat import OpenAICompatLLM
from .widgets import Clickable

CLAUDE_MODELS = [DEFAULT_CLAUDE_MODEL, "claude-sonnet-5-5", "claude-haiku-5-5"]

COMPACT_TITLE = """\
╔═╗┬─┐┌─┐┌─┐┌─┐┌┬┐┬ ┬┬─┐┌─┐┬    ╔╦╗┌─┐┬─┐┌┬┐┬┌┐┌┌─┐┬    ╔═╗┌─┐┌┬┐┌─┐
╠═╝├┬┘│ ││  ├┤  │││ │├┬┘├─┤│     ║ ├┤ ├┬┘│││││││├─┤│    ║ ╦├─┤│││├┤
╩  ┴└─└─┘└─┘└─┘─┴┘└─┘┴└─┴ ┴┴─┘   ╩ └─┘┴└─┴ ┴┴┘└┘┴ ┴┴─┘  ╚═╝┴ ┴┴ ┴└─┘"""


def describe_backend(config: Config) -> str:
    if config.backend == "offline":
        return "Offline (no AI narrator)"
    if config.backend == "anthropic":
        return f"Claude: {config.model or DEFAULT_CLAUDE_MODEL}"
    return f"{config.model or 'auto-detected model'} at {config.url}"


class TitleScreen(Screen):
    BINDINGS = [Binding("n", "new", "Play"), Binding("c", "continue", "Continue"), Binding("s", "setup", "Settings")]

    def compose(self) -> ComposeResult:
        content = load_content()
        with Vertical(id="title-wrap"):
            roomy = self.app.size.width >= 96 and self.app.size.height >= 48
            yield Center(Static(Text(content.splash if roomy else COMPACT_TITLE), id="splash"))
            yield Center(Static("A dungeon that listens. Type anything.", id="tagline"))
            with Center():
                with Vertical(id="menu"):
                    yield Button("Play", id="new", variant="primary")
                    yield Button("Continue", id="continue")
                    yield Button("Settings", id="setup")
                    yield Button("Quit", id="quit", variant="error")
            yield Center(Static("", id="narrator-info"))
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_menu()

    def on_screen_resume(self) -> None:
        self.refresh_menu()

    def refresh_menu(self) -> None:
        self.query_one("#continue", Button).disabled = load_game() is None
        self.query_one("#narrator-info", Static).update(Text(f"Narrator: {describe_backend(self.app.config)}"))

    @on(Button.Pressed)
    def pressed(self, event: Button.Pressed) -> None:
        {"new": self.action_new, "continue": self.action_continue, "setup": self.action_setup,
         "quit": self.app.exit}[event.button.id]()

    def action_new(self) -> None:
        self.app.show_campfire()

    def action_continue(self) -> None:
        if load_game() is not None:
            self.app.continue_game()

    def action_setup(self) -> None:
        self.app.push_screen(SetupScreen(self.app.config))


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
                yield Label("Narrator")
                yield Select([("LM Studio (local)", "lmstudio"), ("Ollama (local)", "ollama"),
                              ("Other OpenAI-compatible server", "openai"), ("Claude API", "anthropic"),
                              ("Offline (no AI)", "offline")], value=preset, allow_blank=False, id="backend",
                             compact=True)
                yield Label("Server URL")
                yield Input(config.url, id="url", compact=True)
                yield Label("Model")
                yield Select([], prompt="Auto-detect", id="model", compact=True)
                yield Label("API key (optional for local servers)")
                yield Input(config.api_key, password=True, id="api_key", compact=True)
                yield Label("Art")
                yield Select([("Pixel sprites", "sprites"), ("ASCII art", "ascii")], value=config.art,
                             allow_blank=False, id="art", compact=True)
                yield Label("Dice")
                yield Select([("Press Space to roll (dramatic)", "manual"), ("Roll automatically", "auto")],
                             value="auto" if config.auto_roll else "manual", allow_blank=False, id="dice",
                             compact=True)
                yield Static("", id="setup-status")
                with Horizontal(id="setup-buttons"):
                    yield Button("Save", id="save", variant="primary")
                    yield Button("Detect models", id="detect")
                    yield Button("Back", id="back")
        yield Footer()

    def on_mount(self) -> None:
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
            status.update(Text(f"Can't reach the server: {e}"))
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
        config = self.config.model_copy(update={
            "player_name": self.query_one("#name", Input).value.strip() or "Adventurer",
            "backend": "openai" if preset in ("lmstudio", "ollama", "openai") else preset,
            "url": self.query_one("#url", Input).value.strip() or DEFAULT_URLS["lmstudio"],
            "model": "" if model is Select.BLANK else str(model),
            "api_key": self.query_one("#api_key", Input).value.strip(),
            "auto_roll": self.query_one("#dice", Select).value == "auto",
            "art": self.query_one("#art", Select).value,
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
        from .game_screen import GameScreen

        self.app.switch_screen(GameScreen(self.game, fresh=True))
