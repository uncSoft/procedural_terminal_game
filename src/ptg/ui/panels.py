"""Pop-up panels: inventory, character, look, map, bestiary, journal, level-up and help.

Every panel closes on Esc, on the ✕ in its top border, or on a click outside it.
"""

from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.events import Click
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView, Static

from .. import glossary, layout, sound
from ..content import Content, Theme
from ..game import Game
from ..meta import epithet
from ..rules import TRAITS
from ..sprites import sprite_text
from .theme import PERK_COLORS
from .widgets import Clickable, item_note, item_tile, map_text, portrait, room_text

HELP = """\
HOW TO PLAY

Type a number to take one of the choices, or type anything you want to try:

  throw my bread at the rat
  tell the goblin I'm the king's tax collector
  topple the statue onto the troll

The game decides what's possible and rolls the dice; the narrator only describes what happened.

✦ PROPS     Using real things in the room or your pack earns a flair bonus and a Fate token.
⚠ HEAVY     When a monster winds up a heavy blow, Dodge (or stun it) to turn the tables.
✦ FATE      Spend Fate to reroll a failed check. Earn it with flair, perfect dodges and natural 20s.
♥ WEAK      Monsters have weaknesses (fire, holy, shiny, food...). Find them, and the bestiary remembers.
↓ FLOORS    Three floors, each a different dungeon. Find the stairs, then the key, then the boss.
☽ SOULS     Souls carry over when you die. Spend them at the campfire on blessings and gifts.
✧ SECRETS   Some moments are written by hand and hidden in the dungeon: a place, a word, a deed.
            The Book of Secrets at the campfire counts the ones you've found.
◆ WORDS     Coloured names in the story (monsters, items, things in the room): hover for a hint, click for
            the full card and the matching action.

KEYS (or type the word)
  F2  i  inventory      F3  c  character     F4  l  look at the room
  F5  m  map            F6  b  bestiary      F7  j  journal
  F1     this help      F8     sound on/off       Esc  title (your game is saved)    Ctrl+Q  quit
  F12    debug: the library, art, sounds, story, the game's state, and a model check
  Ctrl+L redraw the screen (if letters or art ever come out garbled)

MOUSE   Click a choice, a coloured word, or the dice (once to roll, again to carry on).
        Close any panel with its ✕ or a click outside it.
"""


class CloseButton(Static):
    """The ✕ in a panel's top border."""

    def __init__(self) -> None:
        super().__init__(" ✕ ", id="close")

    def on_click(self, event: Click) -> None:
        event.stop()
        self.screen.action_close()


class Panel(ModalScreen[str | None]):
    BINDINGS = [Binding("escape,q", "close", "Close")]
    title_text = ""
    opening_sound: str | None = "open"

    def on_mount(self) -> None:
        if self.opening_sound:
            sound.play(self.opening_sound)
        self.mount(CloseButton())
        self.screen_layout_refresh_signal.subscribe(self, lambda _: self.place_close())

    def place_close(self) -> None:
        """Sit the ✕ on the box's top border, just in from the corner (it follows the box as it resizes)."""
        boxes = self.query(".panel-box")
        if not boxes or not self.query(CloseButton):
            return
        box = boxes.first().region
        close = self.query_one(CloseButton)
        if box.width and tuple(close.styles.offset.resolve(close.size, self.size)) != (box.right - 5, box.y):
            close.styles.offset = (box.right - 5, box.y)

    def on_click(self, event: Click) -> None:
        if event.widget is self:  # the dimmed screen around the box
            self.action_close()

    def action_close(self) -> None:
        if self.app.screen is self:  # a second click mustn't close whatever is underneath
            sound.play("close")
            self.dismiss(None)


class HelpScreen(Panel):
    BINDINGS = [Binding("escape,f1,enter,q", "close", "Close")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="panel-box") as box:
            box.border_title = "Help"
            yield Static(Text(HELP))


class ItemTile(Static):
    """One thing you carry, in the inventory's grid. Moving to it (or clicking it) shows it in full."""

    can_focus = True

    def __init__(self, index: int, text: Text, equipped: bool) -> None:
        super().__init__(text, classes="item-tile equipped" if equipped else "item-tile")
        self.index = index

    def on_focus(self) -> None:
        self.screen.show_detail(self.index)


class InventoryScreen(Panel):
    """What you carry, as tiles with their art: move to one (or click it) to see it in full, Enter to use it.
    Anything that isn't usable on its own is for creative use: close this and type what you do with it."""

    BINDINGS = [Binding("left", "move(-1)", show=False, priority=True),
                Binding("right", "move(1)", show=False, priority=True),
                Binding("up", "move_rows(-1)", show=False, priority=True),
                Binding("down", "move_rows(1)", show=False, priority=True),
                Binding("enter", "use", "Use", priority=True)]

    def __init__(self, game: Game) -> None:
        super().__init__()
        self.game = game
        self.current = 0
        self.columns = 3
        self.art_width = 24

    def compose(self) -> ComposeResult:
        content, player = self.game.content, self.game.state.player
        usable = {a.id: a for a in self.game.actions if a.id.startswith("use:")}
        items = [(player.weapon, f"in hand · {content.item(player.weapon).damage}", None, True)]
        if player.armor:
            items.append((player.armor, f"worn · +{content.item(player.armor).defense} defense", None, True))
        counts: dict[str, int] = {}
        for key in player.inventory:
            counts[key] = counts.get(key, 0) + 1
        for key, count in counts.items():
            note = (f"×{count} · " if count > 1 else "") + item_note(content, key)
            items.append((key, note, usable.get(f"use:{key}"), False))
        self.items = items
        sprites = self.game.config.art == "sprites"
        width = min(100, self.app.size.width)  # fewer tiles to a row on a narrow terminal, and smaller art
        self.columns = 3 if width >= 100 else 2 if width >= 76 else 1
        self.art_width = 24 if width - 8 - (self.columns * 21 + 1) >= 24 else 12
        with Horizontal(classes="panel-box inventory-box") as box:
            box.border_title = f"Inventory · ¤ {player.gold} gold"
            with VerticalScroll(id="inv-shelf") as shelf:
                shelf.styles.width = self.columns * 21 + 1
                grid = Grid(*[ItemTile(i, item_tile(content, key, note, sprites, room=18), equipped)
                              for i, (key, note, _, equipped) in enumerate(items)], id="inv-grid")
                grid.styles.grid_size_columns = self.columns
                yield grid
            with Vertical(id="inv-side"):
                yield Static("", id="inv-detail")
                yield Clickable("", "screen.use", id="inv-use")
                yield Static(Text("arrows pick · enter uses · esc closes\n\nTo use something creatively, close "
                                  "this and type what you do with it.", style="#6c6f99"), id="inv-hint")

    def on_mount(self) -> None:
        self.query(ItemTile).first().focus()

    def show_detail(self, index: int) -> None:
        self.current = index
        content, player = self.game.content, self.game.state.player
        key, _, action, equipped = self.items[index]
        item = content.item(key)
        text = Text()
        art = sprite_text(f"item_{key}", width=self.art_width) if self.game.config.art == "sprites" else None
        if art is not None:  # drawn in the Monster & Item Maker (docs/maker)
            text.append_text(art)
            text.append("\n")
        text.append(item.name + "\n", style="bold #4cff8a")
        might = f" + {player.might} for your might" if key == player.weapon else ""
        text.append(item_note(content, key) + might + "\n", style="#c8c8e0")
        if equipped:
            text.append("in your hand\n" if item.kind == "weapon" else "you're wearing it\n", style="#ffb000")
        if item.desc:
            text.append("\n" + item.desc + "\n", style="italic #c8c8e0")
        if item.tags:
            text.append("\ntags: " + ", ".join(item.tags) + "\n", style="#5fe3ff")
        ideas = [TAG_IDEAS[t] for t in item.tags if t in TAG_IDEAS]
        if ideas:
            text.append("Ideas: " + "; ".join(ideas[:2]), style="#ff4f9a")
        self.query_one("#inv-detail", Static).update(text)
        if action:
            use = Text(f"▶ {action.label}  (enter)", style="bold #4cff8a")
        else:
            idle = {"key": "It must open something important.", "trinket": "No use on its own: try it creatively.",
                    "consumable": "Throw it in a fight to get away." if item.escape else
                    "You're at full health." if player.hp >= player.max_hp else "Not now."}
            use = Text(idle.get(item.kind, ""), style="#6c6f99")
        self.query_one("#inv-use", Clickable).update(use)

    def action_move(self, step: int) -> None:
        tiles = list(self.query(ItemTile))
        tiles[max(0, min(len(tiles) - 1, self.current + step))].focus()

    def action_move_rows(self, rows: int) -> None:
        self.action_move(rows * self.columns)

    def action_use(self) -> None:
        _, _, action, _ = self.items[self.current]
        if action:
            self.dismiss(action.id)
        else:
            self.notify("Not usable on its own. Try typing what you want to do with it.", timeout=3)


class CharacterScreen(Panel):
    def __init__(self, game: Game) -> None:
        super().__init__()
        self.game = game

    def compose(self) -> ComposeResult:
        state, content = self.game.state, self.game.content
        player = state.player
        text = Text()
        text.append(f"{player.name} {epithet(state)}\n", style="bold #ffb000")
        text.append(f"Level {player.level} · XP {player.xp} · HP {player.hp}/{player.max_hp} · "
                    f"Defense {player.defense(content)} · Fate {player.fate}/{player.max_fate()}\n")
        text.append(f"Might {player.might}   Agility {player.agility}   Wits {player.wits}\n\n", style="bold")
        text.append("PERKS\n", style="bold #ff4f9a")
        for key in player.perks or []:
            perk = content.perks[key]
            text.append(f"  {perk.name}", style=f"bold {PERK_COLORS.get(perk.color, '')}")
            text.append(f"  {perk.desc}\n", style="#c8c8e0")
        if not player.perks:
            text.append("  none yet: level up to choose one\n", style="#6c6f99")
        text.append("\nTRAITS  (earned by how you play)\n", style="bold #ff4f9a")
        for key, (name, counter, threshold, desc) in TRAITS.items():
            have = key in player.traits
            progress = min(player.style.get(counter, 0), threshold)
            mark = "★" if have else f"{progress}/{threshold}"
            text.append(f"  {mark:>5} {name}", style="bold #4cff8a" if have else "#9a9cc0")
            text.append(f"  {desc}\n", style="#c8c8e0" if have else "#6c6f99")
        if player.blessings:
            text.append("\nBLESSINGS\n", style="bold #ff4f9a")
            for key in player.blessings:
                unlock = content.unlocks[key]
                text.append(f"  {unlock.icon} {unlock.name}  {unlock.desc}\n", style="#c8c8e0")
        text.append(f"\nSouls this descent: {state.souls}", style="#5fe3ff")
        with VerticalScroll(classes="panel-box") as box:
            box.border_title = "Character"
            yield Static(text)


class LookScreen(Panel):
    def __init__(self, game: Game) -> None:
        super().__init__()
        self.game = game

    def compose(self) -> ComposeResult:
        state, content = self.game.state, self.game.content
        room = state.room
        body = room_text(state, content)
        body.append("\n\n")
        body.append(room.description or content.archetypes[room.archetype].blurb, style="#c8c8e0")
        body.append("\n\nExits: ", style="bold")
        exits = []
        for direction, exit_ in room.exits.items():
            dest = state.rooms[exit_.to]
            note = "locked" if exit_.locked else (dest.name if dest.visited else (
                dest.fixture if dest.fixture and not dest.fixture_used else "unexplored"))
            exits.append(f"{direction} ({note})")
        body.append(", ".join(exits))
        with VerticalScroll(classes="panel-box") as box:
            box.border_title = f"{room.name} · floor {state.floor}"
            yield Static(body)


class MapScreen(Panel):
    def __init__(self, game: Game) -> None:
        super().__init__()
        self.game = game

    def compose(self) -> ComposeResult:
        state, content = self.game.state, self.game.content
        theme = content.themes[state.theme]
        body = map_text(state)
        body.append(f"\n\n{theme.name}: {theme.blurb}", style="#c8c8e0")
        floors = " → ".join(content.themes[t].name + (" (here)" if i + 1 == state.floor else "")
                            for i, t in enumerate(state.themes))
        body.append(f"\n\nThe descent: {floors}\nGoal: {content.themes[state.themes[-1]].goal}", style="#9a9cc0")
        with VerticalScroll(classes="panel-box") as box:
            box.border_title = f"Map · floor {state.floor} of {state.floors_total}"
            yield Static(body)


class BestiaryScreen(Panel):
    def __init__(self, game: Game) -> None:
        super().__init__()
        self.game = game
        self.entries = sorted(game.profile.bestiary().items(), key=lambda kv: kv[1]["first_seen"] or 0)

    def compose(self) -> ComposeResult:
        content = self.game.content
        with Horizontal(classes="panel-box wide") as box:
            box.border_title = f"Bestiary · {len(self.entries)} of {len(content.monsters)} discovered"
            names = [ListItem(Label(content.monster(k).name)) for k, _ in self.entries if k in content.monsters]
            yield ListView(*names, id="beast-list")
            yield VerticalScroll(Static("", id="beast-detail"))

    def on_mount(self) -> None:
        if self.entries:
            self.show(0)
        else:
            self.query_one("#beast-detail", Static).update(Text("Nothing yet. Go meet something.", style="#6c6f99"))

    @on(ListView.Highlighted)
    def highlighted(self, event: ListView.Highlighted) -> None:
        self.show(event.list_view.index or 0)

    def show(self, index: int) -> None:
        content = self.game.content
        key, entry = self.entries[index]
        monster = content.monster(key)
        text = portrait(key, content, self.game.config.art == "sprites")
        text.append("\n\n")
        text.append(f"{monster.name}\n", style="bold #ffb000")
        if monster.desc:
            text.append(monster.desc + "\n", style="#c8c8e0")
        text.append(f"seen {entry['seen']} · slain {entry['killed']} · pacified {entry['pacified']} · "
                    f"killed you {entry['killed_you']}\n", style="#9a9cc0")
        weak = entry["weak"]
        text.append("Weak to: ", style="bold")
        text.append(", ".join(weak) if weak else "???", style="#5fe3ff" if weak else "#6c6f99")
        hidden = len(set(monster.weak) - set(weak))
        if weak and hidden:
            text.append(f"  (+{hidden} undiscovered)", style="#6c6f99")
        text.append("\n\n")
        text.append(entry["lore"] or "No notes yet.", style="italic #c8c8e0")
        self.query_one("#beast-detail", Static).update(text)


class JournalScreen(Panel):
    def __init__(self, game: Game) -> None:
        super().__init__()
        self.game = game

    def compose(self) -> ComposeResult:
        state = self.game.state
        text = Text()
        for line in state.journal[-80:]:
            text.append("· " + line + "\n", style="#c8c8e0")
        with VerticalScroll(classes="panel-box") as box:
            box.border_title = f"Journal · turn {state.turn}"
            yield Static(text or Text("Nothing written yet.", style="#6c6f99"))

    def on_mount(self) -> None:
        self.query_one(VerticalScroll).scroll_end(animate=False)


class FloorScreen(Panel):
    """Arriving on a new floor: its name and what it's like, until you're ready to go on."""

    BINDINGS = [Binding("escape,enter,space,q", "close", "Continue")]
    opening_sound = None  # the stairs already played their part

    def __init__(self, floor: int, total: int, theme: Theme, final: bool) -> None:
        super().__init__()
        self.floor, self.total, self.theme, self.final = floor, total, theme, final

    def compose(self) -> ComposeResult:
        with Vertical(classes="panel-box floor-box") as box:
            box.border_title = f"Floor {self.floor} of {self.total}"
            yield Static(Text("  ".join(" ".join(word) for word in self.theme.name.upper().split()),
                              style="bold #ff4f9a"), classes="floor-name")
            yield Static(Text(self.theme.blurb, style="italic #c8c8e0"))
            if self.final:
                yield Static(Text(f"Your goal: {self.theme.goal}", style="bold #ffd166"))
            yield Clickable(Text(" ▶ [enter] continue ", style="#ffb000"), action="screen.close",
                            classes="panel-action")

    def on_click(self, event: Click) -> None:
        event.prevent_default()  # instead of Panel's: anywhere closes it, it's a title card
        self.action_close()


class LevelUpScreen(ModalScreen[str]):
    """Tiny Rogues style: pick one of three perk cards."""

    BINDINGS = [Binding("1", "pick(0)", "First"), Binding("2", "pick(1)", "Second"), Binding("3", "pick(2)", "Third")]

    def __init__(self, content: Content, choices: list[str], level: int) -> None:
        super().__init__()
        self.content = content
        self.choices = choices
        self.level = level

    def compose(self) -> ComposeResult:
        with Vertical(id="levelup-box") as box:
            box.border_title = f"LEVEL UP · level {self.level}"
            yield Static(Text("CHOOSE ONE  ", style="bold #e8e8f4") + Text("(press 1-3, or click a card)",
                                                                           style="#6c6f99"))
            for i, key in enumerate(self.choices):
                perk = self.content.perks[key]
                color = PERK_COLORS.get(perk.color, "#e8e8f4")
                text = Text(f"{i + 1}  ", style="bold #ffb000")
                text.append(perk.name + "\n", style=f"bold {color}")
                text.append(f"   {perk.desc}", style="#c8c8e0")
                card = PerkCard(text, i)
                card.styles.border = ("heavy", color)
                yield card

    def action_pick(self, index: int) -> None:
        if index < len(self.choices) and self.app.screen is self:
            sound.play("select")
            self.dismiss(self.choices[index])


class PerkCard(Static):
    def __init__(self, text: Text, index: int) -> None:
        super().__init__(text, classes="perk-card")
        self.index = index

    def on_click(self) -> None:
        self.screen.action_pick(self.index)



TAG_IDEAS = {
    "heavy": "topple it, shove it or drop it on something",
    "fire": "set something alight (plants and trolls hate fire)",
    "light": "dazzle something that hates the light",
    "holy": "the undead can't stand it",
    "shiny": "bribe or distract something greedy",
    "food": "lure or distract a hungry beast",
    "loud": "make a racket to scare something off",
    "water": "douse, splash or slip",
    "spores": "kick up a choking cloud",
    "rope": "trip, tie up or swing",
    "paper": "hide behind it, burn it, read it",
    "glass": "smash it",
    "slippery": "scatter it under someone's feet",
    "smelly": "gag something with it",
    "plant": "tangle or snare",
    "sticky": "glue something in place",
}


class InfoScreen(Panel):
    """What a highlighted word refers to, with the matching action one key away."""

    BINDINGS = [Binding("escape,q", "close", "Close"), Binding("enter", "act", "Do it")]

    def __init__(self, game: Game, term_id: str) -> None:
        super().__init__()
        self.game = game
        self.term_id = term_id
        self.action_id: str | None = None

    def compose(self) -> ComposeResult:
        kind, _, ref = self.term_id.partition(":")
        body, title = getattr(self, f"_{kind}", self._unknown)(ref)
        with VerticalScroll(classes="panel-box") as box:
            box.border_title = title
            yield Static(body)
            if self.action_id:
                label = next(a.label for a in self.game.choices() if a.id == self.action_id)
                yield Clickable(Text(f" ▶ {label}  [enter] ", style="bold #ffb000"), action="screen.act",
                                classes="panel-action")

    def _available(self, action_id: str) -> None:
        if any(a.id == action_id for a in self.game.choices()):
            self.action_id = action_id

    def _monster(self, key: str) -> tuple[Text, str]:
        game = self.game
        content, state = game.content, game.state
        monster = content.monster(key)
        entry = game.profile.bestiary().get(key, {})
        text = portrait(key, content, game.config.art == "sprites")
        text.append("\n\n")
        text.append(glossary.monster_summary(state, content, key, entry) + "\n", style="bold #ffb000")
        if monster.desc:
            text.append(monster.desc + "\n", style="#c8c8e0")
        if entry:
            text.append(f"seen {entry['seen']} · slain {entry['killed']} · pacified {entry['pacified']} · "
                        f"killed you {entry['killed_you']}\n", style="#9a9cc0")
        text.append("\n" + (entry.get("lore") or "No notes on this one yet."), style="italic #c8c8e0")
        here = state.room.monster
        if here and here.key == key:
            self._available("attack")
        return text, monster.name

    def _item(self, key: str) -> tuple[Text, str]:
        item = self.game.content.item(key)
        text = Text()
        art = sprite_text(f"item_{key}") if self.game.config.art == "sprites" else None
        if art is not None:  # drawn in the Monster & Item Maker (docs/maker)
            text.append_text(art)
            text.append("\n\n")
        text.append(item.name + "\n", style="bold #4cff8a")
        text.append(glossary.item_summary(self.game.content, key) + "\n\n", style="#9a9cc0")
        text.append(item.desc, style="#c8c8e0")
        ideas = [TAG_IDEAS[t] for t in item.tags if t in TAG_IDEAS]
        if ideas:
            text.append("\n\nIdeas: " + "; ".join(ideas[:3]), style="#ff4f9a")
        self._available(f"use:{key}")
        if not self.action_id:
            self._available(f"take:{key}")
        return text, "Item"

    def _feature(self, ref: str) -> tuple[Text, str]:
        state, content = self.game.state, self.game.content
        feature = state.room.features[int(ref)]
        tags = content.feature_tags(feature.name)
        text = Text(f"{feature.name} ({layout.where(feature.pos)})\n", style="bold #ffb000")
        text.append(("Searched." if feature.searched else "Not searched yet.") + "\n", style="#9a9cc0")
        if feature.used:
            text.append(f"Already used to {feature.used}.\n", style="#9a9cc0")
        if tags:
            text.append("Properties: " + ", ".join(tags) + "\n", style="#5fe3ff")
            ideas = [TAG_IDEAS[t] for t in tags if t in TAG_IDEAS]
            if ideas:
                text.append("Ideas: " + "; ".join(ideas[:3]), style="#ff4f9a")
        else:
            text.append("Nothing special about it, as far as you can tell.", style="#6c6f99")
        self._available(f"search:{ref}")
        return text, "In the room"

    def _fixture(self, ref: str) -> tuple[Text, str]:
        text = Text(ref.title() + "\n\n", style="bold #ff4f9a")
        text.append(glossary.FIXTURES[ref], style="#c8c8e0")
        for action in {"stairs": ["descend"], "shrine": ["shrine_blood", "shrine_gold"], "chest": ["chest"],
                       "fountain": ["fountain"]}.get(ref, []):
            if not self.action_id:
                self._available(action)
        return text, "Fixture"

    def _room(self, ref: str) -> tuple[Text, str]:
        state, content = self.game.state, self.game.content
        room = state.rooms[int(ref)]
        text = Text(room.name + "\n\n", style="bold #8fa8ff")
        text.append(room.description or content.archetypes[room.archetype].blurb, style="#c8c8e0")
        text.append("\n\nExits: " + ", ".join(room.exits), style="#9a9cc0")
        return text, "Room"

    def _rule(self, ref: str) -> tuple[Text, str]:
        name, summary = glossary.RULES[ref]
        return Text(name + "\n\n", style="bold #5fe3ff") + Text(summary, style="#c8c8e0"), "How it works"

    def _unknown(self, ref: str) -> tuple[Text, str]:
        return Text("Nothing more is known about that."), "?"

    def action_act(self) -> None:
        if self.app.screen is self:
            sound.play("select")
            self.dismiss(self.action_id)
