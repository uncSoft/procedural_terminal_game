"""The main game screen: HUD on top, story on the left, room/monster and map on the right, choices and
command line at the bottom."""

from __future__ import annotations

import asyncio
import time

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, Input, Static

from .. import glossary, loot, sound
from ..events import Action, Event
from ..glossary import Lexicon
from ..game import Game
from ..models import LogEntry
from ..outcome import AWFUL, BAD, GOOD, GREAT, overall, tone, verdict
from ..room_picture import look_of, picture_text
from ..sprites import DEATH_FRAMES, DEFAULT_WIDTH, frame_count
from ..text import the
from . import effects
from .dice import DiceScreen
from .panels import (BestiaryScreen, CharacterScreen, FloorScreen, HelpScreen, InfoScreen, InventoryScreen,
                     JournalScreen, LevelUpScreen, LookScreen, MapScreen, ShopScreen)
from .widgets import (AnimatedSprite, ChoiceItem, Clickable, ClickableBox, DiceLine, DPad, Hud, StoryLine, bar,
                      hearts, highlight, item_note, item_picture, map_text, monster_text, portrait, roll_text,
                      room_text)

# (sprite, steps of (frame, pose, flash)) for the moment you use a fixture
FIXTURE_MOMENTS = {
    "chest": ("chest", [(0, "shake", False), (1, "shake", False)] * 3
              + [(2, "idle", False), (3, "idle", False), (2, "idle", False), (3, "idle", False), (2, "idle", False)]),
    "fountain": ("fountain", [(i % 3, "idle", False) for i in range(9)]),
    "shrine": ("shrine", [(0, "idle", False), (1, "idle", True), (2, "idle", False), (1, "idle", True),
                          (0, "idle", False)]),
    "descend": ("stairs", [(i % 3, "idle", False) for i in range(6)] + [(i, "death", False) for i in range(6)]),
}

# Idle frames for a fixture waiting to be used (a chest stays shut, with the odd glint).
ARRIVAL_LOOPS = {"chest": [0, 0, 0, 1]}
ROOM_CARD = (72, 30)  # the picture of a room you walk into, in pixels: the most the story is given
CHOICE_ROWS = 8  # the choices box never changes height; more choices than this start a second column
# how an item came your way this turn; when an item comes more than one way, the first of these is shown
LOOT_LABELS = {"equip": "equipped", "find": "found", "key": "found", "take": "picked up", "drop": "dropped",
               "buy": "bought", "left": "left here", "floor": "on the floor"}

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
    "ghost_rest": ("A ghost rests", "information"),
    "reprieve": ("Not yet!", "warning"),
    "key": ("Key", "information"),
}


SPARKS = "✧✦★✦"
LEAVE_WINDOW = 2.0  # seconds for the second Esc that leaves for the title
LOOT_CARD = 28  # a loot card's width in the story, with its margins (see .loot-card)


def secret_banner(frame: int, words: str = "SECRET ROOM", colour: str = "#ffd166") -> Text:
    """The banner across the story for a find worth a fanfare (a secret room, a shop): its stars twinkle in turn,
    then settle."""
    stars = [SPARKS[(frame + i) % len(SPARKS)] for i in range(6)]
    text = Text(justify="center")
    for i, star in enumerate(stars[:3]):
        text.append(f"{star}  ", style="bold #ffffff" if frame and (frame + i) % 3 == 0 else f"bold {colour}")
    text.append(f" {words} ", style=f"bold {effects.INK} on {colour}")
    for i, star in enumerate(stars[3:], 3):
        text.append(f"  {star}", style="bold #ffffff" if frame and (frame + i) % 3 == 0 else f"bold {colour}")
    return text


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
        self.animating = False  # a one-off scene animation is playing; the idle loop waits
        self.live_sprites: list[AnimatedSprite] = []
        self.fixture_sprites: dict[tuple[int, int], AnimatedSprite] = {}  # (floor, room) -> its fixture's sprite
        self.floor_cards: list[tuple[int, int, str, ClickableBox]] = []  # things lying somewhere, as cards to take
        self.leave_asked = 0.0  # when Esc last asked "again for the title?" (time.monotonic)
        self.since_redraw = 0  # turns since the whole screen was last drawn afresh (see PTGApp.action_redraw)

    def compose(self) -> ComposeResult:
        yield Hud(id="hud")
        with Horizontal(id="main"):
            yield VerticalScroll(id="story")
            with Vertical(id="sidebar"):
                yield Clickable(Text(""), "screen.scene_card", id="scene", classes="panel")
                yield Static(id="map", classes="panel")
        with Horizontal(id="choices"):
            yield Vertical(id="choice-list")
            yield Vertical(id="choice-more")
            yield DPad(id="dpad")
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
        self.set_interval(0.6, self._idle_frame)

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

    def add_card(self, title: str, text: str, lexicon: Lexicon | None = None, sprite: str = "") -> Widget:
        """An authored moment, shown in the writer's own words (with its sprite, if it has one)."""
        if not (sprite and self._sprites_on()):
            card = self.add_line(highlight(text, lexicon), "story-card")
        else:
            art = AnimatedSprite(sprite, interval=0.3, action=self._card_of(sprite), classes="card-sprite")
            card = Vertical(art, StoryLine(highlight(text, lexicon)), classes="story-card")
            story = self.query_one("#story", VerticalScroll)
            story.mount(card)
            story.scroll_end(animate=False)
            self.live_sprites.append(art)
        card.border_title = f"✧ {title}" if title else "✧"
        return card

    def _show_story(self, events: list[Event]) -> None:
        """Story cards, their effects and any secret found, after the narration."""
        lexicon = self.lexicon()
        library = self.game.story.library
        for event in events:
            if event.kind == "story" and event.data.get("voice") == "exact":
                self.add_card(event.data.get("title", ""), event.text, lexicon, event.data.get("sprite", ""))
                sound.play("story")
            elif event.kind == "story_effect" and event.text:
                self.add_line(Text("  ◆ " + event.text, style="bold #ff4f9a"), "mechanic")
            elif event.kind == "story_secret" and not event.data.get("repeat"):
                sound.play("secret")
                found = len(self.game.profile.secrets())
                self.add_line(Text(f"  ✧ {event.text}  ({found}/{len(library.secrets)} in the Book of Secrets)",
                                   style="bold #ffd166"), "system-line")
                self.notify(event.data.get("title", ""), title="✧ Secret found", timeout=6)

    def add_floor_header(self, title: str, name: str, before=None) -> Static:
        """A banner across the story where a new floor begins."""
        text = Text(f"↓   {title.upper()}  ·  {name.upper()}   ↓", style="bold")
        return self.add_line(text, "floor-header", before=before)

    def add_entry(self, entry: LogEntry, lexicon: Lexicon | None = None) -> None:
        if entry.kind == "floor":
            self.add_floor_header(entry.title, entry.text)
            return
        if entry.kind == "card":
            self.add_card(entry.title, entry.text, lexicon, entry.art)
            return
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
    async def run_turn(self, text: str | None, action: Action | None = None) -> None:
        """A turn: the opening (None), a numbered choice or typed words, or an `action` from a panel (the shop's)."""
        self.busy = True
        command = self.query_one("#command", Input)
        command.disabled = True
        try:
            if text is None:
                await self._opening()
            else:
                await self._turn(text, action)
        finally:
            self.busy = False
            command.disabled = False
            command.focus()

    async def _opening(self) -> None:
        state = self.game.state
        self.add_floor_header(f"Floor {state.floor} of {state.floors_total}", self.game.theme.name)
        self._room_card()
        narration, on_text = self._narration_sink()
        result = await self.game.opening(on_text)
        narration.update(highlight(result.narration, self.lexicon()))
        self._show_story(result.events)
        self.refresh_panels()
        await self.update_suggestion()

    async def _turn(self, text: str, action: Action | None = None) -> None:
        game = self.game
        choices = game.choices()
        shown = choices[int(text) - 1].label if text.isdigit() and 1 <= int(text) <= len(choices) else text
        shown = action.label if action else shown
        if not (action and action.id.startswith("take:")):  # a click on something lying there needs no echo
            self.add_line(f"> {shown}", "player-line")
        sound.play("select")
        hp_before, gold_before = game.state.player.hp, game.state.player.gold
        for sprite in self.live_sprites:  # older story sprites stand still
            sprite.freeze()
        self.live_sprites.clear()
        monster = game.state.room.monster
        before = (monster.key, monster.name) if monster else None
        room_before = game.state.room_id
        where = (game.state.floor, room_before)

        pending = await game.begin(text, action)
        primary = pending.primary
        while primary is not None:
            summary = pending.intent.summary or shown
            choice = await self.app.push_screen_wait(
                DiceScreen(primary.dice, summary, game.fate_left(), game.can_reroll(), auto=game.config.auto_roll,
                           tone=tone(primary), word=verdict(primary)))
            if choice == "reroll" and game.can_reroll():
                sound.play("fate")
                pending = game.reroll()
                primary = pending.primary
                self.add_line(Text(f"  ✦ Fate spent. Rerolling... ({game.state.player.fate} left)",
                                   style="bold #ffd166"), "mechanic")
                continue
            break

        narration, on_text = self._narration_sink()
        for event in pending.events:
            if not event.dice:
                continue
            if event is primary:
                effects.flash(self.add_line(roll_text(event), "mechanic", before=narration), tone(event))
            else:
                line = DiceLine("", classes="mechanic")
                await self.query_one("#story").mount(line, before=narration)
                await line.play(event, fast=event.dice.actor == "monster")
        self.query_one("#hud", Hud).show(game.state, game.content)
        for moment in dict.fromkeys(filter(None, map(effects.event_sound, pending.events))):
            sound.play(moment)
        await self._roll_feedback(pending.events, hp_before, gold_before)
        await self._fight_animations(pending.events, before, room_before)
        await self._fixture_moment(pending.events, narration, where)
        picked = pending.intent.kind == "action" and pending.intent.action_id.startswith(("take:", "take_all"))
        await self._loot_moment(pending.events, narration, from_the_floor=picked)
        await self._secret_room_moment(pending.events, narration)
        await self._shop_moment(pending.events, narration)
        if any(e.kind == "tip" for e in pending.events):  # look: it's on your map
            effects.pulse(self.query_one("#map"), GREAT, blinks=2)
        if any(e.kind == "descend" for e in pending.events):
            self._new_floor(narration)
        if any(e.kind in ("enter", "descend") and e.data.get("first") for e in pending.events):
            self._room_card(before=narration)
        self.refresh_panels()

        result = await game.finish(on_text)
        if result.narration:
            narration.update(highlight(result.narration, self.lexicon()))
        else:
            await narration.remove()  # an authored moment speaks for itself
        for error in result.errors:
            self.add_line(f"  ({error})", "system-line")
        self._arrival_sprite(result.events)
        self._show_story(result.events)
        self.since_redraw += 1
        if self.since_redraw >= self.app.REDRAW_EVERY:  # keeps a struggling terminal's picture from drifting
            self.since_redraw = 0
            self.call_after_refresh(self.app.action_redraw)
        self._toasts(result.events)
        self.refresh_panels()

        while game.state.pending_perks:
            await self._level_up()
        if game.state.over:
            self.add_line(Text(f"Epitaph: {game.state.epitaph}", style="italic #ff4f9a"), "system-line")
            await asyncio.sleep(1.2)
            self.app.end_run(self)
            return
        shopping = any(e.kind == "shop" for e in result.events) or (action and action.id.startswith(("buy:", "barter:")))
        if shopping and game.state.room.shop:  # the counter again, after a purchase or a haggle
            self.open_shop(int(action.id.partition(":")[2]) if action else 0)
        await self.update_suggestion()

    def action_shop_counter(self) -> None:
        """Clicked the shopkeeper: her shop, if you're in it."""
        if not self.busy and self.game.state.room.shop and not self.game.state.over:
            self.open_shop()

    def open_shop(self, selected: int = 0) -> None:
        """The shop's own screen: what's on the counter and what it costs. What you do there comes back as a turn."""
        def done(chosen: Action | None) -> None:
            if chosen:
                self.run_turn(chosen.label, action=chosen)

        self.app.push_screen(ShopScreen(self.game, selected), done)

    async def _level_up(self) -> None:
        game = self.game
        choices = list(game.state.pending_perks)
        sound.play("level_up")
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

    def _new_floor(self, narration: Static) -> None:
        """A header in the story, and the floor's card on top until you've read it (the arrival is narrated
        behind it in the meantime)."""
        game = self.game
        state = game.state
        self.add_floor_header(f"Floor {state.floor} of {state.floors_total}", game.theme.name, before=narration)
        self.app.push_screen(FloorScreen(state.floor, state.floors_total, game.theme, state.final_floor))

    def _toasts(self, events: list[Event]) -> None:
        for event in events:
            if event.kind in TOASTS:
                title, severity = TOASTS[event.kind]
                self.notify(event.text, title=title, severity=severity, timeout=5)

    def _flash_hud(self, kind: str) -> None:
        hud = self.query_one("#hud")
        hud.add_class(kind)
        self.set_timer(0.45, lambda: hud.remove_class(kind))

    @staticmethod
    async def _shake(widget) -> None:
        for dx in (1, -1, 1, 0):
            widget.styles.offset = (dx, 0)
            await asyncio.sleep(0.035)

    # --- feedback ---

    async def _roll_feedback(self, events: list[Event], hp_before: int, gold_before: int | None = None) -> None:
        """How the turn went, at a glance: the story's border lights up in its colour (and blinks and shakes for a
        natural 20 or 1), damage rises off the monster, and your hearts show what you lost or gained."""
        story = self.query_one("#story")
        how = overall(events)
        if how:
            effects.pulse(story, how, blinks=3 if how in (GREAT, AWFUL) else 1)
        hits = [e for e in events if e.kind == "hit" and e.data.get("damage")]
        if hits:
            crit = any(e.dice and e.dice.crit for e in hits)
            dealt = sum(e.data["damage"] for e in hits)
            await self._pop_over_scene(f" -{dealt}{'!' if crit else ''} ",
                                       f"bold {effects.INK} on {effects.COLORS[GREAT] if crit else '#ffffff'}")
        elif any(e.kind == "miss" for e in events):
            await self._pop_over_scene(" MISS ", "bold #c8c8e0 on #23274a")
        player = self.game.state.player
        change = player.hp - hp_before
        if change:  # just under the HP numbers, on the story's top border, sliding right
            hud = self.query_one("#hud").region
            x = hud.x + 1 + len(hearts(player.hp, player.max_hp)) + len(f" {player.hp}/{player.max_hp}") - 2
            style = (f"bold #ffffff on {effects.COLORS[BAD]}" if change < 0
                     else f"bold {effects.INK} on {effects.COLORS[GOOD]}")
            await effects.popup(self, f" {change:+d} ♥ ", style, x, hud.y + 1, dx=4, dy=0)
            self._flash_hud("hurt" if change < 0 else "healed")
            if change > 0:
                sound.play("heal")
            elif not any(e.kind == "monster_hit" for e in events):  # a blow already made its own sound
                sound.play("hurt")
        if gold_before is not None and player.gold > gold_before:
            sound.play("coin")
        if how in (GREAT, AWFUL):
            await self._shake(story)

    async def _pop_over_scene(self, text: str, style: str) -> None:
        """A popup rising off the monster's portrait."""
        region = self.query_one("#scene").region
        x = region.x + max(1, (region.width - len(text)) // 2)
        await effects.popup(self, text, style, x, region.y + min(7, region.height // 2))

    # --- animation ---

    def _sprites_on(self) -> bool:
        return self.game.config.art == "sprites"

    async def _fight_animations(self, events: list[Event], before: tuple | None, room_before: int) -> None:
        """Flash white when hit, lunge when attacking, dissolve when it dies (or a ghost finds rest)."""
        game = self.game
        if before is None or game.state.room_id != room_before:
            return
        kinds = {e.kind for e in events}
        gone = game.state.room.monster is None
        steps: list[tuple[str, int, bool]] = []
        if "hit" in kinds:
            steps += [("idle", self.frame, flash) for flash in (True, False, True, False)]
        if not gone and kinds & {"monster_hit", "monster_miss", "evade", "dodge"}:
            steps += [("lunge", 0, False), ("lunge", 1, False), ("idle", 0, False)]
        if gone:
            steps += [("death", step, False) for step in range(DEATH_FRAMES)]
            sound.play("kill")
        if not self._sprites_on():
            steps = [s for s in steps if s[0] == "idle"]  # ASCII art can still flash
        if steps:
            await self._play_scene(*before, steps)

    async def _play_scene(self, key: str, name: str, steps: list[tuple[str, int, bool]]) -> None:
        scene = self.query_one("#scene", Static)
        scene.border_title = name
        scene.add_class("combat")
        self.animating = True
        try:
            for pose, frame, flash in steps:
                scene.update(self._scene_frame(key, pose, frame, flash))
                await asyncio.sleep(0.07)
        finally:
            self.animating = False

    def _scene_frame(self, key: str, pose: str, frame: int, flash: bool) -> Text:
        """The monster card during an animation, keeping its HP bar so the panel doesn't jump."""
        content, monster = self.game.content, self.game.state.room.monster
        art = portrait(key, content, self._sprites_on(), frame, flash, pose=pose)
        hp, max_hp = (monster.hp, monster.max_hp) if monster and monster.key == key else (0, content.monster(key).hp)
        art.append("\n")
        art.append(bar(hp, max_hp, 18), style="#ff4b4b")
        art.append(f" {max(0, hp)}/{max_hp}")
        return art

    async def _fixture_moment(self, events: list[Event], narration: Static, where: tuple[int, int]) -> None:
        """Opening a chest, drinking from a fountain, an offering, going down the stairs: play it out. The sprite
        shown when you walked in moves down to here and plays it, so there's only ever one of each."""
        kind = next((e.kind for e in events if e.kind in FIXTURE_MOMENTS), None)
        if kind is None or not self._sprites_on():
            return
        key, steps = FIXTURE_MOMENTS[kind]
        sound.play(kind)
        story = self.query_one("#story", VerticalScroll)
        sprite = self.fixture_sprites.pop(where, None)
        if sprite is not None and sprite.is_attached and sprite.key == key:
            story.move_child(sprite, before=narration)
        else:
            sprite = AnimatedSprite(key, action=self._card_of(key), classes="story-sprite")
            await story.mount(sprite, before=narration)
        story.scroll_end(animate=False)
        await sprite.play(steps)
        if kind == "descend":
            await sprite.remove()  # it dissolved into the dark

    async def _loot_moment(self, events: list[Event], narration: Static, from_the_floor: bool = False) -> None:
        """What turned up this turn, with its art: what you found, bought or picked up (bombs and keys go straight
        in your pack), and, there for the taking, what a monster dropped, what you left as you took something better,
        and everything lying in a room you walk into. Click one of those to pick it up, no turn spent. Something
        taken `from_the_floor` this turn gets no second card: its card says it's taken."""
        state = self.game.state
        here = (state.floor, state.room_id)
        taken = {e.data["item"] for e in events if from_the_floor and e.kind in ("take", "equip", "key")
                 and e.data.get("item") and self._mark_taken(here, e.data["item"])}
        found: dict[str, str] = {}
        order = list(LOOT_LABELS)
        for event in events:
            key = event.data.get("item")
            if key and key not in taken and event.kind in LOOT_LABELS and event.kind != "drop" and \
                    (key not in found or order.index(event.kind) < order.index(found[key])):
                found[key] = event.kind
        if any(e.kind in ("enter", "descend") for e in events):
            lying = [(key, "floor") for key in state.room.items]
        else:
            lying = [(e.data["item"], "drop") for e in events if e.kind == "drop" and e.data["item"] in state.room.items]
            lying += [(e.data["left"], "left") for e in events if e.data.get("left") in state.room.items]
        if not found and not lying:
            return
        shine: list[AnimatedSprite] = []
        cards = [self._loot_card(key, kind, None, shine) for key, kind in found.items()]
        for key, kind in lying:
            card = self._loot_card(key, kind, here, shine)
            self.floor_cards.append((*here, key, card))
            cards.append(card)
        story = self.query_one("#story", VerticalScroll)
        across = max(1, (story.size.width - 2) // LOOT_CARD)  # as many to a row as fit, the rest below
        for row in range(0, len(cards), across):
            await story.mount(Horizontal(*cards[row:row + across], classes="loot-row"), before=narration)
        story.scroll_end(animate=False)
        self.live_sprites += shine
        await asyncio.gather(*(self._sparkle(picture) for picture in shine))

    def _loot_card(self, key: str, kind: str, lying_at: tuple[int, int] | None, shine: list) -> ClickableBox:
        """An item's card in the story: its full picture, its name and what it does. One `lying_at` a place is
        there for the taking: click it to pick it up."""
        content = self.game.content
        if self._sprites_on() and frame_count(f"item_{key}"):  # the full picture: a small version is for the pack
            picture = AnimatedSprite(f"item_{key}", interval=0.35, classes="loot-art")
            shine.append(picture)
        else:
            picture = Static(item_picture(content, key, self._sprites_on(), width=DEFAULT_WIDTH), classes="loot-art")
        words = Text.assemble((content.item(key).name, "bold #4cff8a"), "\n", (item_note(content, key), "#9a9cc0"))
        if lying_at:
            words.append("\n▶ click to take", style="bold #ffb000")
        action = (f"screen.pick_up('{key}', {lying_at[0]}, {lying_at[1]})" if lying_at
                  else f"screen.lookup('item:{key}')")
        card = ClickableBox(picture, Static(words, classes="loot-text"), action=action, classes=f"loot-card {kind}")
        card.border_title = f"✦ {LOOT_LABELS[kind]}"
        card.tooltip = "Click to pick it up (no turn)" if lying_at else "Click for its card"
        return card

    def _mark_taken(self, here: tuple[int, int], key: str) -> bool:
        """A card of something lying `here`, now picked up: it says so, and clicking it shows the item's card."""
        for floor, room, item, card in self.floor_cards:
            if (floor, room) == here and item == key and not card.has_class("taken"):
                card.add_class("taken")
                card.border_title = "✓ taken"
                card.action, card.tooltip = f"screen.lookup('item:{key}')", "Click for its card"
                content = self.game.content
                card.query_one(".loot-text", Static).update(Text.assemble(
                    (content.item(key).name, "bold #6c6f99"), "\n", (item_note(content, key), "#6c6f99"), "\n",
                    ("✓ in your pack", "#6c6f99")))
                for sprite in card.query(AnimatedSprite):
                    sprite.freeze()
                return True
        return False

    def action_pick_up(self, key: str, floor: int, room_id: int) -> None:
        """Clicked something lying in the story: picked up, no turn spent (only where you are, and not mid-fight)."""
        state, content = self.game.state, self.game.content
        if self.busy or state.over:
            return
        if (floor, room_id) != (state.floor, state.room_id):
            self.notify("That's back on another floor." if floor != state.floor else
                        f"That's back in {the(state.rooms[room_id].name)}.", timeout=3)
            return
        if state.in_combat:
            self.notify("Not in the middle of a fight.", timeout=3)
            return
        if key in state.room.items:
            name = the(content.item(key).name)
            self.run_turn(f"Pick up {name}", action=Action(f"take:{key}", f"Pick up {name}"))

    async def _secret_room_moment(self, events: list[Event], narration: Static) -> None:
        """The floor's secret room, found: a fanfare after the bang, a banner glittering across the story, the story
        and the map blinking gold, and the room in gold on the map from then on."""
        found = next((e for e in events if e.kind == "secret_room"), None)
        if found is None:
            return
        self.set_timer(0.35, lambda: sound.play("secret_room"))
        story = self.query_one("#story", VerticalScroll)
        banner = self.add_line(secret_banner(0), "secret-banner", before=narration)
        story.scroll_end(animate=False)
        effects.pulse(story, GREAT, blinks=3)
        effects.pulse(self.query_one("#map"), GREAT, blinks=3)
        room = self.game.state.rooms[found.data["room"]]
        self.notify(f"{room.name}, sealed until now.", title="✧ Secret room found", timeout=6)

        async def glitter() -> None:
            for frame in range(1, len(SPARKS) * 3):
                await asyncio.sleep(0.09)
                banner.update(secret_banner(frame))
            banner.update(secret_banner(0))

        await asyncio.gather(glitter(), self._pop_over_scene(" ✧ SECRET ROOM! ✧ ",
                                                             f"bold {effects.INK} on {effects.COLORS[GREAT]}"))

    async def _shop_moment(self, events: list[Event], narration: Static) -> None:
        """Walking into a shop for the first time: a jingle and a banner, gold and starrier for the rare Granny
        Kamultruk (the shop is on the map from then on, in green)."""
        room = self.game.state.room
        if not room.shop or not any(e.kind == "enter" and e.data.get("first") for e in events):
            return
        shiny = room.shop.keeper == loot.SHINY
        keeper = self.game.content.monster(room.shop.keeper).name
        sound.play("shop_shiny" if shiny else "shop")
        words, colour = (keeper.upper(), "#ffd166") if shiny else ("SHOP", "#4cff8a")
        story = self.query_one("#story", VerticalScroll)
        banner = self.add_line(secret_banner(0, words, colour), "secret-banner" if shiny else "secret-banner shop",
                               before=narration)
        story.scroll_end(animate=False)
        effects.pulse(story, GREAT if shiny else GOOD, blinks=3 if shiny else 2)
        self.notify(f"{keeper} has her wares out.", title="★ A rare shop!" if shiny else "¤ A shop", timeout=6)
        for frame in range(1, len(SPARKS) * (3 if shiny else 2)):
            await asyncio.sleep(0.09)
            banner.update(secret_banner(frame, words, colour))
        banner.update(secret_banner(0, words, colour))

    @staticmethod
    async def _sparkle(sprite: AnimatedSprite) -> None:
        await sprite.play([(0, "idle", True), (0, "idle", False), (1, "idle", True), (0, "idle", False)], delay=0.08)
        sprite.resume()

    def _room_card(self, before: Widget | None = None) -> None:
        """The room you've just walked into for the first time, as a picture above what the narrator makes of it
        (see room_picture): as wide as the story allows, up to ROOM_CARD."""
        if not self._sprites_on():
            return
        state = self.game.state
        story = self.query_one("#story", VerticalScroll)
        # less the card's border and room for a scrollbar: a line wider than the story would wrap
        space = (story.scrollable_content_region.width or self.app.size.width - 36) - 3
        width = min(ROOM_CARD[0], space)
        if width < 36:
            return
        art = picture_text(state, self.game.content, width, 2 * round(width * ROOM_CARD[1] / ROOM_CARD[0] / 2))
        if art is None:
            return
        card = ClickableBox(Static(art, classes="room-art"), action=f"screen.room_card({state.floor}, {state.room.id})",
                            classes="room-card")
        card.border_title = f"✦ {state.room.name}"
        card.tooltip = "Click to look around"
        card.styles.border = ("round", look_of(state.theme).accent)
        card.styles.border_title_color = look_of(state.theme).accent
        story.mount(Horizontal(card, classes="room-row"), before=before)
        story.scroll_end(animate=False)

    def _arrival_sprite(self, events: list[Event]) -> None:
        """Arriving somewhere with a shrine, chest, fountain or stairs: show it, alive."""
        room = self.game.state.room
        arrived = any(e.kind in ("enter", "descend") and e.data.get("first") for e in events)
        if arrived and room.shop and self._sprites_on():  # the shopkeeper herself: click her to shop
            sprite = AnimatedSprite(room.shop.keeper, interval=0.6, action="screen.shop_counter", classes="story-sprite")
            self.query_one("#story", VerticalScroll).mount(sprite)
            self.live_sprites.append(sprite)
        elif arrived and room.fixture and not room.fixture_used and self._sprites_on():
            sprite = AnimatedSprite(room.fixture, interval=0.3, loop=ARRIVAL_LOOPS.get(room.fixture),
                                    action=self._card_of(room.fixture), classes="story-sprite")
            self.query_one("#story", VerticalScroll).mount(sprite)
            self.live_sprites.append(sprite)
            self.fixture_sprites[(self.game.state.floor, room.id)] = sprite

    def _idle_frame(self) -> None:
        """The monster in the sidebar breathes: its frames take turns while nothing else is playing there. (Not
        called _animate: Textual keeps an animator under that name on every widget, and it hid this.)"""
        monster = self.game.state.room.monster
        if self._sprites_on() and monster and monster.hostile and not self.animating:
            self.frame += 1
            self.refresh_scene()

    async def update_suggestion(self) -> None:
        if not self.game.state.scene:
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
            scene.update(monster_text(state, content, game.config.art == "sprites", self.frame))
            scene.border_title = state.room.monster.name
            scene.add_class("combat")
        else:
            scene.update(room_text(state, content))
            scene.border_title = state.room.name
            scene.remove_class("combat")

    def refresh_choices(self) -> None:
        """The numbered choices, top to bottom in a box that keeps its height (so nothing moves under the mouse
        while a suggestion arrives), spilling into a second column past CHOICE_ROWS; and the pad of ways out."""
        box = self.query_one("#choices", Horizontal)
        first, more = self.query_one("#choice-list", Vertical), self.query_one("#choice-more", Vertical)
        first.remove_children()
        more.remove_children()
        scene = self.game.story.scene_title(self.game.state)
        box.border_title = f"✧ {scene}" if scene else "Choices"
        box.set_class(bool(scene), "scene")
        choices = [] if self.game.state.over else self.game.choices()
        self.query_one(DPad).show(choices)
        if self.game.state.over:
            first.mount(Static(Text("Press Enter to see your fate.", style="#ffb000")))
            more.display = False
            return
        rows: list[Widget] = [ChoiceItem(i, action) for i, action in enumerate(choices, 1)]
        if self.game.suggestion_pending():  # its place is kept until it's thought of
            rows.append(Static(Text(f"{len(rows) + 1}. ✦ …", style="italic #6c6f99"), classes="choice"))
        first.mount(*rows[:CHOICE_ROWS])
        more.mount(*rows[CHOICE_ROWS:])
        more.display = len(rows) > CHOICE_ROWS

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

    def action_go(self, direction: str) -> None:
        """Clicked an arrow on the pad: go that way, as if you'd picked its choice."""
        index = next((i for i, a in enumerate(self.game.choices(), 1) if a.id == f"go:{direction}"), None)
        if index and not self.busy and not self.game.state.over:
            self.run_turn(str(index))

    def action_room_card(self, floor: int, room_id: int) -> None:
        """Clicked a room's picture in the story: look around, if you're still there; otherwise that room's card,
        while it's on this floor."""
        state = self.game.state
        if floor != state.floor:
            return
        if room_id == state.room_id:
            self.action_panel("look")
        else:
            self.action_lookup(f"room:{room_id}")

    def action_scene_card(self) -> None:
        """Clicked the sidebar's top panel: the monster's card in a fight, otherwise a look around the room."""
        monster = self.game.state.room.monster
        if monster and self.query_one("#scene").has_class("combat"):
            self.action_lookup(f"monster:{monster.key}")
        else:
            self.action_panel("look")

    def _card_of(self, sprite: str) -> str | None:
        """The action that shows a story sprite's card: an item's, a monster's or a fixture's."""
        content = self.game.content
        if sprite.startswith("item_") and sprite[5:] in content.items:
            return f"screen.lookup('item:{sprite[5:]}')"
        if sprite in content.monsters:
            return f"screen.lookup('monster:{sprite}')"
        return f"screen.lookup('fixture:{sprite}')" if sprite in glossary.FIXTURES else None

    def action_leave(self) -> None:
        """Esc twice: to the title (the game's saved). Once only asks, so an Esc meant for a panel or the command
        palette never throws you out of a run."""
        if self.busy:
            return
        now = time.monotonic()
        if now - self.leave_asked > LEAVE_WINDOW:
            self.leave_asked = now
            self.notify("Press Esc again for the title screen. (Your game is saved.)", timeout=LEAVE_WINDOW)
            return
        self.app.leave_game(self)

