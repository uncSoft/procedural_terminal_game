"""The main game screen: HUD on top, story on the left, room/monster and map on the right, choices and
command line at the bottom."""

from __future__ import annotations

import asyncio

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Input, Static

from .. import glossary
from ..events import Event
from ..glossary import Lexicon
from ..game import Game
from ..models import LogEntry
from .dice import DiceScreen
from .panels import (BestiaryScreen, CharacterScreen, HelpScreen, InfoScreen, InventoryScreen, JournalScreen,
                     LevelUpScreen, LookScreen, MapScreen)
from .widgets import ChoiceItem, DiceLine, Hud, StoryLine, highlight, map_text, monster_text, roll_text, room_text

COMMANDS = {
    "i": "inventory", "inv": "inventory", "inventory": "inventory",
    "c": "character", "char": "character", "character": "character", "stats": "character",
    "l": "look", "look": "look",
    "m": "map", "map": "map",
    "b": "bestiary", "bestiary": "bestiary",
    "j": "journal", "journal": "journal",
    "?": "help", "h": "help", "help": "help",
}
TOASTS = {
    "trait": ("Trait earned", "information"),
    "weakness": ("Bestiary", "information"),
    "fate": ("Fate", "information"),
    "descend": ("Deeper", "warning"),
    "ghost_rest": ("A ghost rests", "information"),
    "reprieve": ("Not yet!", "warning"),
    "key": ("Key", "information"),
}


class GameScreen(Screen):
    BINDINGS = [
        Binding("f1", "panel('help')", "Help"),
        Binding("f2", "panel('inventory')", "Inventory"),
        Binding("f3", "panel('character')", "Character"),
        Binding("f4", "panel('look')", "Look"),
        Binding("f5", "panel('map')", "Map"),
        Binding("f6", "panel('bestiary')", "Bestiary"),
        Binding("f7", "panel('journal')", "Journal"),
        Binding("escape", "leave", "Title"),
    ]

    def __init__(self, game: Game, fresh: bool) -> None:
        super().__init__()
        self.game = game
        self.fresh = fresh
        self.busy = False
        self.frame = 0  # idle animation frame for the monster sprite
        self.flashing = False

    def compose(self) -> ComposeResult:
        yield Hud(id="hud")
        with Horizontal(id="main"):
            yield VerticalScroll(id="story")
            with Vertical(id="sidebar"):
                yield Static(id="scene", classes="panel")
                yield Static(id="map", classes="panel")
        yield Vertical(id="choices")
        yield Input(id="command", placeholder="Type a number, or anything you want to try...  (F1 help)")
        yield Footer()

    def on_mount(self) -> None:
        state = self.game.state
        self.title = self.game.theme.name
        self.sub_title = f"seed {state.seed}"
        self.query_one("#story").border_title = "Story"
        self.query_one("#map").border_title = "Map"
        self.query_one("#choices").border_title = "Choices"
        self.query_one("#story").border_subtitle = self.game.llm.name if self.game.llm else "offline narrator"
        if self.fresh:
            self.run_turn(None)
        else:
            lexicon = self.lexicon()
            for entry in state.log[-60:]:
                self.add_entry(entry, lexicon)
            self.refresh_panels()
            self.previously()
        self.query_one("#command", Input).focus()
        self.set_interval(0.6, self._animate)

    def on_resize(self) -> None:
        self.query_one("#map").display = self.size.height >= 38

    # --- story helpers ---

    def add_line(self, text: str | Text, classes: str, before=None) -> Static:
        widget = StoryLine(text if isinstance(text, Text) else Text(text), classes=classes)
        story = self.query_one("#story", VerticalScroll)
        story.mount(widget, before=before)
        story.scroll_end(animate=False)
        return widget

    def lexicon(self) -> Lexicon:
        """The terms worth highlighting right now: what's in this room, what you carry, what lives here."""
        game = self.game
        return Lexicon(glossary.build(game.state, game.content, game.profile.bestiary()))

    def add_entry(self, entry: LogEntry, lexicon: Lexicon | None = None) -> None:
        if entry.kind == "mechanic":
            self.add_line(Text("  ⚄ " + entry.text, style="#6c6f99"), "mechanic")
            return
        if entry.kind == "player":
            self.add_line("> " + entry.text, "player-line")
            return
        prefix = "  " if entry.kind == "system" else ""
        classes = "system-line" if entry.kind == "system" else "narration"
        self.add_line(highlight(prefix + entry.text, lexicon), classes)

    @work(group="recap")
    async def previously(self) -> None:
        text = await self.game.recap()
        if text:
            self.add_line(highlight("Previously… " + text, self.lexicon(), "italic #ff4f9a"), "recap")
        await self.update_suggestion()

    # --- turns ---

    @on(Input.Submitted, "#command")
    def submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if self.busy:
            return
        if self.game.state.over:
            self.app.end_run(self)
            return
        if not text:
            return
        event.input.value = ""
        if text.lower() in COMMANDS:
            self.action_panel(COMMANDS[text.lower()])
            return
        self.run_turn(text)

    @on(ChoiceItem.Chosen)
    def chosen(self, event: ChoiceItem.Chosen) -> None:
        if not self.busy and not self.game.state.over:
            self.run_turn(str(event.index))

    @work(exclusive=True, group="turn")
    async def run_turn(self, text: str | None) -> None:
        self.busy = True
        command = self.query_one("#command", Input)
        command.disabled = True
        try:
            if text is None:
                await self._opening()
            else:
                await self._turn(text)
        finally:
            self.busy = False
            command.disabled = False
            command.focus()

    async def _opening(self) -> None:
        narration, on_text = self._narration_sink()
        result = await self.game.opening(on_text)
        narration.update(highlight(result.narration, self.lexicon()))
        self.refresh_panels()
        await self.update_suggestion()

    async def _turn(self, text: str) -> None:
        game = self.game
        choices = game.choices()
        shown = choices[int(text) - 1].label if text.isdigit() and 1 <= int(text) <= len(choices) else text
        self.add_line(f"> {shown}", "player-line")
        hp_before = game.state.player.hp

        pending = await game.begin(text)
        primary = pending.primary
        while primary is not None:
            summary = pending.intent.summary or shown
            choice = await self.app.push_screen_wait(
                DiceScreen(primary.dice, summary, game.fate_left(), game.can_reroll(), auto=game.config.auto_roll))
            if choice == "reroll" and game.can_reroll():
                pending = game.reroll()
                primary = pending.primary
                self.add_line(Text(f"  ✦ Fate spent. Rerolling... ({game.state.player.fate} left)",
                                   style="bold #ffd166"), "mechanic")
                continue
            break

        narration, on_text = self._narration_sink()
        crit = False
        for event in pending.events:
            if not event.dice:
                continue
            crit = crit or event.dice.crit
            if event is primary:
                self.add_line(roll_text(event.dice), "mechanic", before=narration)
            else:
                line = DiceLine("", classes="mechanic")
                await self.query_one("#story").mount(line, before=narration)
                await line.play(event.dice, fast=event.dice.actor == "monster")
        if any(e.kind == "hit" for e in pending.events) and game.state.room.monster:
            await self._hit_flash()
        self.refresh_panels()

        result = await game.finish(on_text)
        narration.update(highlight(result.narration, self.lexicon()))
        for error in result.errors:
            self.add_line(f"  ({error})", "system-line")
        self._toasts(result.events)
        if crit:
            await self._shake(self.query_one("#story"))
        if game.state.player.hp < hp_before:
            self._flash_hud()
        self.refresh_panels()

        while game.state.pending_perks:
            await self._level_up()
        if game.state.over:
            self.add_line(Text(f"Epitaph: {game.state.epitaph}", style="italic #ff4f9a"), "system-line")
            await asyncio.sleep(1.2)
            self.app.end_run(self)
            return
        await self.update_suggestion()

    async def _level_up(self) -> None:
        game = self.game
        choices = list(game.state.pending_perks)
        perk = await self.app.push_screen_wait(LevelUpScreen(game.content, choices, game.state.player.level))
        index = next(i for i, a in enumerate(game.choices(), 1) if a.id == f"perk:{perk}")
        await game.begin(str(index))
        result = await game.finish(lambda _: None)
        self.add_line(Text("★ " + result.narration, style="bold #ffd166"), "system-line")
        self.refresh_panels()

    def _narration_sink(self):
        narration = self.add_line(Text("…", style="#6c6f99"), "narration")
        story = self.query_one("#story", VerticalScroll)
        buffer: list[str] = []
        lexicon = self.lexicon()

        def on_text(chunk: str) -> None:
            buffer.append(chunk)
            narration.update(highlight("".join(buffer), lexicon))
            story.scroll_end(animate=False)

        return narration, on_text

    def _toasts(self, events: list[Event]) -> None:
        for event in events:
            if event.kind in TOASTS:
                title, severity = TOASTS[event.kind]
                self.notify(event.text, title=title, severity=severity, timeout=5)

    def _flash_hud(self) -> None:
        hud = self.query_one("#hud")
        hud.add_class("hurt")
        self.set_timer(0.4, lambda: hud.remove_class("hurt"))

    @staticmethod
    async def _shake(widget) -> None:
        for dx in (1, -1, 1, 0):
            widget.styles.offset = (dx, 0)
            await asyncio.sleep(0.035)

    async def _hit_flash(self) -> None:
        """The monster sprite blinks white when it takes damage."""
        for flash in (True, False, True, False):
            self.flashing = flash
            self.refresh_scene()
            await asyncio.sleep(0.07)

    def _animate(self) -> None:
        if self.game.config.art == "sprites" and self.game.state.room.monster and not self.flashing:
            self.frame += 1
            self.refresh_scene()

    async def update_suggestion(self) -> None:
        await self.game.refresh_suggestion()
        self.refresh_choices()

    # --- panels ---

    def refresh_panels(self) -> None:
        game = self.game
        state, content = game.state, game.content
        self.query_one("#hud", Hud).show(state, content)
        self.refresh_scene()
        self.query_one("#map", Static).update(map_text(state))
        self.query_one("#map").border_title = f"Floor {state.floor}/{state.floors_total}"
        self.refresh_choices()

    def refresh_scene(self) -> None:
        """The sidebar's top panel: the monster's portrait during a fight, otherwise the room's floor plan."""
        game = self.game
        state, content = game.state, game.content
        scene = self.query_one("#scene", Static)
        if state.room.monster and (state.in_combat or state.room.monster.hostile):
            scene.update(monster_text(state, content, game.config.art == "sprites", self.frame, self.flashing))
            scene.border_title = state.room.monster.name
            scene.add_class("combat")
        else:
            scene.update(room_text(state, content))
            scene.border_title = state.room.name
            scene.remove_class("combat")

    def refresh_choices(self) -> None:
        box = self.query_one("#choices", Vertical)
        box.remove_children()
        if self.game.state.over:
            box.mount(Static(Text("Press Enter to see your fate.", style="#ffb000")))
            return
        box.mount(*[ChoiceItem(i, action) for i, action in enumerate(self.game.choices(), 1)])

    def action_panel(self, name: str) -> None:
        if self.busy and name != "help":
            return
        screens = {"help": HelpScreen, "inventory": InventoryScreen, "character": CharacterScreen,
                   "look": LookScreen, "map": MapScreen, "bestiary": BestiaryScreen, "journal": JournalScreen}
        screen = screens[name]() if name == "help" else screens[name](self.game)

        def done(action_id: str | None) -> None:
            if action_id:
                index = next((i for i, a in enumerate(self.game.choices(), 1) if a.id == action_id), None)
                if index:
                    self.run_turn(str(index))

        self.app.push_screen(screen, done)

    def action_lookup(self, term_id: str) -> None:
        """Clicked a highlighted word: show what it is (and offer the matching action, if there is one)."""
        if self.busy:
            return

        def done(action_id: str | None) -> None:
            if action_id:
                index = next((i for i, a in enumerate(self.game.choices(), 1) if a.id == action_id), None)
                if index:
                    self.run_turn(str(index))

        self.app.push_screen(InfoScreen(self.game, term_id), done)

    def action_leave(self) -> None:
        if not self.busy:
            self.app.leave_game(self)

