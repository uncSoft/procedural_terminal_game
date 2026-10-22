"""The Textual interface: title, setup, intro and the game screen."""

from __future__ import annotations

import random
from collections import Counter

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Header, Input, Label, Select, Static

from ..config import DEFAULT_CLAUDE_MODEL, DEFAULT_URLS, Config, load_game, save_config
from ..content import load_content
from ..game import Game
from ..llm import LLM, LLMError, make_llm
from ..llm.narrator import intro
from ..llm.openai_compat import OpenAICompatLLM
from ..models import GameState, LogEntry
from ..rules import Event
from ..world import generate, render_map

CLAUDE_MODELS = [DEFAULT_CLAUDE_MODEL, "claude-sonnet-5-5", "claude-haiku-5-5"]

COMPACT_TITLE = """\
╔═╗┬─┐┌─┐┌─┐┌─┐┌┬┐┬ ┬┬─┐┌─┐┬    ╔╦╗┌─┐┬─┐┌┬┐┬┌┐┌┌─┐┬    ╔═╗┌─┐┌┬┐┌─┐
╠═╝├┬┘│ ││  ├┤  │││ │├┬┘├─┤│     ║ ├┤ ├┬┘│││││││├─┤│    ║ ╦├─┤│││├┤
╩  ┴└─└─┘└─┘└─┘─┴┘└─┘┴└─┴ ┴┴─┘   ╩ └─┘┴└─┴ ┴┴┘└┘┴ ┴┴─┘  ╚═╝┴ ┴┴ ┴└─┘"""

HELP = """\
HOW TO PLAY

Type a number to take one of the listed choices, or type anything you want to try:

  throw my bread at the rat
  tell the goblin I'm the king's tax collector
  pry the gems out of the statue's eyes
  what am I carrying?

The game decides what's possible and rolls the dice. The narrator only describes what actually happened.
Creative ideas use your stats: might (force), agility (speed and aim) and wits (cleverness and talk).

Find the key, open the locked door and defeat the boss. The game saves after every turn.

  F1        this help
  Escape    back to the title screen (your game is saved)
  Ctrl+Q    quit
"""


def bar(value: int, maximum: int, width: int = 14) -> str:
    filled = round(width * max(0, value) / max(1, maximum))
    return "█" * filled + "░" * (width - filled)


def describe_backend(config: Config) -> str:
    if config.backend == "offline":
        return "Offline (no AI narrator)"
    if config.backend == "anthropic":
        return f"Claude: {config.model or DEFAULT_CLAUDE_MODEL}"
    return f"{config.model or 'auto-detected model'} at {config.url}"


# --- title -----------------------------------------------------------------

class TitleScreen(Screen):
    BINDINGS = [Binding("n", "new", "New game"), Binding("c", "continue", "Continue"), Binding("s", "setup", "Settings")]

    def compose(self) -> ComposeResult:
        content = load_content()
        with Vertical(id="title-wrap"):
            roomy = self.app.size.width >= 96 and self.app.size.height >= 48
            splash = content.splash if roomy else COMPACT_TITLE
            yield Center(Static(Text(splash), id="splash"))
            yield Center(Static("A dungeon that listens. Type anything.", id="tagline"))
            with Center():
                with Vertical(id="menu"):
                    yield Button("New game", id="new", variant="primary")
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
        self.app.new_game()

    def action_continue(self) -> None:
        if load_game() is not None:
            self.app.continue_game()

    def action_setup(self) -> None:
        self.app.push_screen(SetupScreen(self.app.config))


# --- setup -----------------------------------------------------------------

class SetupScreen(Screen):
    BINDINGS = [Binding("escape", "cancel", "Back")]

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        config = self.config
        if config.backend == "openai":
            preset = next((k for k, url in DEFAULT_URLS.items() if url == config.url), "openai")
        else:
            preset = config.backend
        with Vertical(id="setup-wrap"):
            with Vertical(id="setup-box") as box:
                box.border_title = "Settings"
                yield Label("Your name")
                yield Input(config.player_name, id="name")
                yield Label("Narrator")
                yield Select([("LM Studio (local)", "lmstudio"), ("Ollama (local)", "ollama"),
                              ("Other OpenAI-compatible server", "openai"), ("Claude API", "anthropic"),
                              ("Offline (no AI)", "offline")], value=preset, allow_blank=False, id="backend")
                yield Label("Server URL")
                yield Input(config.url, id="url")
                yield Label("Model")
                yield Select([], prompt="Auto-detect", id="model")
                yield Label("API key (optional for local servers)")
                yield Input(config.api_key, password=True, id="api_key")
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
            self.save()

    def save(self) -> None:
        preset = self.query_one("#backend", Select).value
        model = self.query_one("#model", Select).value
        config = self.config.model_copy(update={
            "player_name": self.query_one("#name", Input).value.strip() or "Adventurer",
            "backend": "openai" if preset in ("lmstudio", "ollama", "openai") else preset,
            "url": self.query_one("#url", Input).value.strip() or DEFAULT_URLS["lmstudio"],
            "model": "" if model is Select.BLANK else str(model),
            "api_key": self.query_one("#api_key", Input).value.strip(),
        })
        self.app.save_settings(config)

    def action_cancel(self) -> None:
        if len(self.app.screen_stack) > 2:
            self.app.pop_screen()


# --- intro -----------------------------------------------------------------

class IntroScreen(Screen):
    BINDINGS = [Binding("enter", "begin", "Begin"), Binding("escape", "begin", "Skip")]

    def __init__(self, game: Game) -> None:
        super().__init__()
        self.game = game
        self.text = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="intro-wrap"):
            with Vertical(id="intro-box") as box:
                box.border_title = "A Message From The Void"
                yield Static(Text("The void clears its throat...", style="italic"), id="intro-text")
                yield Static("Press Enter to begin your adventure", id="intro-hint")
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
        self.app.switch_screen(GameScreen(self.game, fresh=True))


# --- help ------------------------------------------------------------------

class HelpScreen(ModalScreen):
    BINDINGS = [Binding("escape,f1,enter,q", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-box") as box:
            box.border_title = "Help"
            yield Static(Text(HELP))


# --- the game --------------------------------------------------------------

class GameScreen(Screen):
    BINDINGS = [Binding("f1", "help", "Help"), Binding("escape", "leave", "Title screen")]

    def __init__(self, game: Game, fresh: bool) -> None:
        super().__init__()
        self.game = game
        self.fresh = fresh
        self.busy = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            yield VerticalScroll(id="story")
            with Vertical(id="sidebar"):
                yield Static(id="player", classes="panel")
                yield Static(id="monster", classes="panel")
                yield Static(id="map", classes="panel")
        yield Static(id="choices")
        yield Input(id="command", placeholder="Type a number, or anything you want to try...")
        yield Footer()

    def on_mount(self) -> None:
        state = self.game.state
        self.title = self.game.theme.name
        self.sub_title = f"seed {state.seed}  ·  {self.game.llm.name if self.game.llm else 'offline'}"
        self.query_one("#story").border_title = "Story"
        self.query_one("#player").border_title = state.player.name
        self.query_one("#map").border_title = "Map"
        self.query_one("#choices").border_title = "Choices"
        if self.fresh:
            self.run_turn(None)
        else:
            for entry in state.log[-60:]:
                self.add_entry(entry)
            self.add_line("(Game loaded.)", "system-line")
            self.refresh_panels()
        self.query_one("#command", Input).focus()

    # story helpers

    def add_line(self, text: str, classes: str, before: Static | None = None) -> Static:
        widget = Static(Text(text), classes=classes)
        story = self.query_one("#story", VerticalScroll)
        story.mount(widget, before=before)
        story.scroll_end(animate=False)
        return widget

    def add_entry(self, entry: LogEntry) -> None:
        prefix = {"player": "> ", "mechanic": "  ⚄ ", "system": "  "}.get(entry.kind, "")
        classes = {"player": "player-line", "mechanic": "mechanic", "system": "system-line"}.get(entry.kind, "narration")
        self.add_line(prefix + entry.text, classes)

    # turns

    @on(Input.Submitted, "#command")
    def submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if self.busy:
            return
        if self.game.state.over:
            self.action_leave()
            return
        if not text:
            return
        event.input.value = ""
        self.run_turn(text)

    @work(exclusive=True)
    async def run_turn(self, text: str | None) -> None:
        self.busy = True
        command = self.query_one("#command", Input)
        command.disabled = True
        if text is not None:
            actions = self.game.actions
            shown = actions[int(text) - 1].label if text.isdigit() and 1 <= int(text) <= len(actions) else text
            self.add_line(f"> {shown}", "player-line")
        narration = self.add_line("...", "narration")
        story = self.query_one("#story", VerticalScroll)
        buffer: list[str] = []

        def on_text(chunk: str) -> None:
            buffer.append(chunk)
            narration.update(Text("".join(buffer)))
            story.scroll_end(animate=False)

        def on_resolved(events: list[Event]) -> None:
            for event in events:
                if event.roll:
                    self.add_line(f"  ⚄ {event.roll}", "mechanic", before=narration)
            self.refresh_panels()

        if text is None:
            result = await self.game.opening(on_text)
        else:
            result = await self.game.act(text, on_text, on_resolved)
        narration.update(Text(result.narration))
        for error in result.errors:
            self.add_line(f"  ({error})", "system-line")
        self.refresh_panels()
        if self.game.state.over:
            self.show_ending()
        self.busy = False
        command.disabled = False
        command.focus()

    def show_ending(self) -> None:
        state = self.game.state
        player = state.player
        headline = "VICTORY!" if state.status == "won" else "YOU DIED"
        self.add_line(f"{headline}\nLevel {player.level} · {player.kills} monsters defeated · {player.gold} gold · "
                      f"{state.turn} turns · seed {state.seed}", "banner")
        command = self.query_one("#command", Input)
        command.placeholder = "Press Enter to return to the title screen"

    # side panels

    def refresh_panels(self) -> None:
        content = self.game.content
        state: GameState = self.game.state
        player = state.player

        weapon = content.item(player.weapon)
        armor = content.item(player.armor) if player.armor else None
        pack = Counter(content.item(k).name for k in player.inventory)
        next_xp = player.next_level_xp()
        info = Text()
        info.append(f"Level {player.level}", style="bold")
        info.append(f"   XP {player.xp}" + (f"/{next_xp}" if next_xp else "") + "\n")
        hp_style = "green" if player.hp > player.max_hp / 2 else ("yellow" if player.hp > player.max_hp / 4 else "red")
        info.append("HP ")
        info.append(bar(player.hp, player.max_hp), style=hp_style)
        info.append(f" {player.hp}/{player.max_hp}\n")
        info.append(f"Might {player.might}  Agility {player.agility}  Wits {player.wits}\n", style="dim")
        info.append(f"Weapon  {weapon.name} ({weapon.damage}+{player.might})\n")
        info.append(f"Armor   {armor.name + f' (+{armor.defense})' if armor else 'none'}\n")
        info.append(f"Gold    {player.gold}\n")
        info.append("Pack    " + (", ".join(f"{n} ×{c}" if c > 1 else n for n, c in pack.items()) or "empty"))
        self.query_one("#player", Static).update(info)

        room = state.room
        monster_panel = self.query_one("#monster", Static)
        if room.monster:
            monster = room.monster
            art = Text(content.monster(monster.key).art + "\n", style="red" if monster.hostile else "yellow")
            art.append(bar(monster.hp, monster.max_hp, 16), style="red")
            art.append(f" {max(0, monster.hp)}/{monster.max_hp}")
            if monster.stunned:
                art.append("  stunned", style="bold yellow")
            if not monster.hostile:
                art.append("  calm", style="bold green")
            monster_panel.update(art)
            monster_panel.border_title = monster.name
        else:
            monster_panel.update(Text(content.archetypes[room.archetype].blurb, style="dim italic"))
            monster_panel.border_title = room.name

        map_text = Text("\n".join(render_map(state)) + "\n\n")
        map_text.append("@ you  ! foe  ? unknown  = locked", style="dim")
        self.query_one("#map", Static).update(map_text)

        choices = Text()
        for i, action in enumerate(self.game.actions, 1):
            choices.append(f"{i}. ", style="bold")
            choices.append(action.label + "\n")
        self.query_one("#choices", Static).update(choices if choices.plain else Text("—", style="dim"))

    def action_help(self) -> None:
        self.app.push_screen(HelpScreen())

    def action_leave(self) -> None:
        self.app.leave_game(self)


# --- app -------------------------------------------------------------------

class PTGApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "Procedural Terminal Game"

    def __init__(self, config: Config | None, seed: int | None = None, setup: bool = False,
                 resume: bool = False) -> None:
        super().__init__()
        self.needs_setup = config is None or setup
        self.config = config or Config()
        self.seed = seed
        self.resume = resume

    def on_mount(self) -> None:
        self.push_screen(TitleScreen())
        if self.needs_setup:
            self.push_screen(SetupScreen(self.config))
        elif self.resume and load_game() is not None:
            self.continue_game()

    def save_settings(self, config: Config) -> None:
        self.config = config
        save_config(config)
        self.pop_screen()
        self.notify(f"Narrator: {describe_backend(config)}", title="Settings saved")

    async def connect(self) -> LLM | None:
        try:
            llm = make_llm(self.config)
            if llm is not None:
                await llm.prepare()
            return llm
        except LLMError as e:
            self.notify(f"{e}\nPlaying offline instead.", title="No narrator", severity="warning", timeout=8)
            return None

    @work(exclusive=True, group="start")
    async def new_game(self) -> None:
        llm = await self.connect()
        seed = self.seed if self.seed is not None else random.randrange(1_000_000)
        self.seed = None
        game = Game(generate(seed, self.config.player_name), self.config, llm)
        self.push_screen(IntroScreen(game))

    @work(exclusive=True, group="start")
    async def continue_game(self) -> None:
        state = load_game()
        if state is None:
            return
        llm = await self.connect()
        self.push_screen(GameScreen(Game(state, self.config, llm), fresh=False))

    def leave_game(self, screen: GameScreen) -> None:
        self.pop_screen()
        self.run_worker(screen.game.aclose())
