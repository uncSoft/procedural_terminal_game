"""Pop-up panels: help, inventory, character, look, map, bestiary, journal, the shop, a new floor's card, the level-up,
and the card of whatever a word in the story is.

Every panel is one box of a size class (see Panel), sized as it opens: what you pick or click in it changes what's
inside, never the box. Each closes on Esc, on the ✕ in its top border, or on a click outside it, and F1-F7 switch to
that panel instead.
"""

from __future__ import annotations

import textwrap

from rich.console import Group
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.events import Click
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Label, ListItem, ListView, Static

from .. import config, glossary, interactions, inventory, layout, model3d, npcs, rules, sheet, sound
from ..content import Content, Theme
from ..game import Game
from ..meta import epithet
from ..models import GameState, Room
from ..room_picture import picture_text
from ..events import Action
from ..rules import TRAITS
from ..text import cap, the
from ..sprites import (DEFAULT_WIDTH, SMALL, SPENT, SPLASH_LEAST, frame_count, splash, splash_sizes,
                       splash_text)
from .theme import PERK_COLORS
from .widgets import (INK_STYLES, TALL, Clickable, Picture, StoryLine, highlight, item_note, item_words, map_text,
                      power_lines, room_text)

PANEL_KEYS = {"f1": "help", "f2": "inventory", "f3": "character", "f4": "look", "f5": "map", "f6": "bestiary",
              "f7": "journal"}  # the panels' keys, on the game screen and in every panel
# Each of those panels' own colour, its frame's and its title's (the map's is its floor's: see grid.ChartScreen).
PANEL_INKS = {"help": "#6c8cff", "inventory": "#ffb000", "character": "#4cff8a", "look": "#5fe3ff",
              "bestiary": "#ff4b4b", "journal": "#733e39"}
INK, FADED_INK, RED_INK = "#3e2731", "#b86f50", "#a22633"  # a parchment page's inks (the journal's, as the map's)
PANEL_ROWS = 40  # the tallest a card's or a wide panel's box gets: on a big screen, a box, not a wall
LOOK_PICTURE = 76  # how wide the Look panel draws the room: the panel, less its border, padding and scrollbar
# An item's tile in the inventory or the shop, (columns, rows) with its frame, by how wide its picture is drawn: full
# size when the screen has the room for a shelf of them (see shelf_width), small when it hasn't.
TILE = {DEFAULT_WIDTH: (26, 17), SMALL: (20, 11)}
DETAIL_WORDS = 16  # rows a detail column keeps under its picture, for what's said and done with it (else it's small)
CARD_WORDS = 6  # the same for a card (it scrolls for the rest)
SHOP_WIDTH = 128  # the widest a shop's box gets: her, two full-size wares across and one in full beside them
KEEPER = {DEFAULT_WIDTH: 28, SMALL: 16}  # the shopkeeper's column, with its padding, by how wide she's drawn
SIDE = 26  # the least a shop's side column needs: a full-size ware, and words beside the shelf
USES = ("use", "throw", "distract", "reveal")  # the actions that do something with a thing you carry
SOFT, DIM, WORDS = "#9a9cc0", "#6c6f99", "#c8c8e0"  # a panel's quieter lines: notes, hints, plain words
FLOOR_WORDS = 64  # how wide a floor card's words run under its picture: lines you can read at a glance
FLOOR_BESIDE = 40  # how wide they run beside it, on a screen with more room across than down


def ornate(title: str) -> str:
    """A panel's name spaced out between ornaments, as the floor's is on its card, and what follows it as it was:
    "✦ I N V E N T O R Y ✦ · ¤ 24 gold"."""
    name, _, rest = title.removeprefix("✦ ").partition(" · ")
    spaced = "  ".join(" ".join(word) for word in name.upper().split())
    return f"✦ {spaced} ✦" + (f" · {rest}" if rest else "")


def panel_rows(height: int) -> int:
    """How tall a card's or a wide panel's box is on a screen `height` rows tall: all of it but a row or two above
    and below (to click to close it), up to PANEL_ROWS."""
    return max(5, min(PANEL_ROWS, height - (4 if height >= TALL else 2)))


def box_frame(height: int) -> tuple[int, int]:
    """(columns, rows) a panel's box takes for its border and its padding: a blank line inside it, top and bottom,
    only on a tall screen (see .panel-box in app.tcss)."""
    return (6, 4) if height >= TALL else (4, 2)


def box_rows(height: int) -> int:
    """The rows inside a card's or a wide panel's box on a screen `height` rows tall."""
    return panel_rows(height) - box_frame(height)[1]


class CloseButton(Static):
    """The ✕ in a panel's top border."""

    def __init__(self) -> None:
        super().__init__(" ✕ ", id="close")

    def on_click(self, event: Click) -> None:
        event.stop()
        self.screen.action_close()


class Panel(ModalScreen[str | None]):
    """A pop-up panel: one box (.panel-box), its title in its top border and a ✕ in the corner. Its size class says
    how big the box is:

        small  as wide as it says (64 unless it says otherwise), and as tall as what's in it: a title card, a
               question, a choice
        card   84 wide (or the screen, if that's narrower), and as tall as the screen allows, up to PANEL_ROWS: one
               thing, or a page of things
        wide   as wide as the panel works out for the screen (a shelf of things, and one of them in full), and as
               tall as a card
        full   the whole screen

    It's sized as it opens, from the screen's size (see fit), and never again while it's open, only if the screen
    itself is resized: what you pick or click in it changes what's inside, and that scrolls inside, so nothing moves
    under the mouse. F1-F7 close it and open that panel instead (its own key just closes it: see action_switch);
    Esc, q, the ✕ or a click outside it close it, unless it's one that waits for an answer (`closable`)."""

    BINDINGS = [Binding("escape,q", "close", "Close"),
                *[Binding(key, f"switch('{name}')", show=False) for key, name in PANEL_KEYS.items()]]
    size_class = "card"
    panel_name = ""  # which of PANEL_KEYS' panels it is, if it's one of them
    opening_sound: str | None = "open"
    closable = True  # whether it can be closed without an answer: a level-up can't (no ✕; its action_close says so)
    peek = False  # opened over a choice still to be made (a level-up): it only shows, and what you'd do waits

    @property
    def box(self) -> Widget:
        """The panel's one box (.panel-box)."""
        return self.query(".panel-box").first()

    def on_mount(self) -> None:
        if self.opening_sound:
            sound.play(self.opening_sound)
        self.box.add_class(self.size_class)
        if self.panel_name in PANEL_KEYS.values():  # one of F1-F7's: its title spaced out, in its own colour
            box = self.box
            box.border_title = ornate(str(box.border_title or ""))
            box.styles.border_title_align = "center"
            if self.panel_name in PANEL_INKS:
                box.styles.border = ("double", PANEL_INKS[self.panel_name])
                box.styles.border_title_color = PANEL_INKS[self.panel_name]
        self.fit()
        if self.closable:
            self.mount(CloseButton())
        self.screen_layout_refresh_signal.subscribe(self, lambda _: self.place_close())

    def on_resize(self) -> None:
        self.fit()

    def fit(self) -> None:
        """Size the box for this screen, by its size class (a small box is as tall as what's in it, a full one is the
        screen): as it opens, and again only when the screen's resized."""
        if self.size_class in ("card", "wide"):
            self.box.styles.height = panel_rows(self.app.size.height)

    def place_close(self) -> None:
        """Sit the ✕ on the box's top border, just in from the corner (where it stays: the box doesn't move, bar a
        resized screen)."""
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

    def lexicon(self) -> glossary.Lexicon | None:
        """The terms worth highlighting in a panel's words, as in the story (a panel about the game has its game)."""
        game = getattr(self, "game", None)
        if game is None:
            return None
        return glossary.Lexicon(glossary.build(game.state, game.content, game.profile.bestiary()))

    def action_lookup(self, term_id: str) -> None:
        """A highlighted word in the panel clicked (StoryLine): its card over the panel. What you do from the card
        (equip the sword) closes the panel too, and goes back to the game as that turn."""
        if self.app.screen is not self or getattr(self, "game", None) is None or self.peek:
            return

        def done(picked) -> None:
            if picked is not None:
                self.dismiss(picked)

        self.app.push_screen(InfoScreen(self.game, term_id), done)

    def action_switch(self, name: str) -> None:
        """F1-F7: that panel instead of this one (this one's own key closes it), opened by what opened this one, if it
        can open it now: not from the title, where there's no game to show, nor mid-turn (bar the help)."""
        if self.app.screen is not self:
            return
        if name == self.panel_name:
            self.action_close()
            return
        opener = self.app.screen_stack[-2]
        if hasattr(opener, "open_panel") and opener.can_open_panel(name):
            self.dismiss(None)
            opener.open_panel(name)


# --- help -------------------------------------------------------------------------------------------------------------

EXAMPLES = ("throw my bread at the rat", "tell the goblin I'm the king's tax collector",
            "topple the statue onto the troll")
RULES = (
    ("✦", "PROPS", "Using real things in the room or your pack earns a flair bonus and a Fate token."),
    ("⚠", "HEAVY", "When a monster winds up a heavy blow, Dodge (or stun it) to turn the tables."),
    ("✦", "FATE", "Spend Fate to reroll a failed check. Earn it with flair, perfect dodges and natural 20s."),
    ("♥", "WEAK", "Monsters have weaknesses (fire, holy, shiny, food...). Find them, and the bestiary remembers."),
    ("↓", "FLOORS", "Three dungeons, then Norfel. Find the stairs; on the third, the key and its boss, who "
                    "guards the way down; at the bottom, Serpentis. Beat her once, and later runs go deeper."),
    ("☽", "SOULS", "Souls carry over when you die. Spend them at the campfire on blessings and gifts."),
    ("●", "BOMBS", "Every floor hides a sealed secret room, in a gap that touches two rooms or more: bomb the wall to "
                   "it (search next to it for a draft). ⚷ Small keys open chests; or pick the lock, or smash it."),
    ("»", "ASK", "A creature that's stopped fighting may know what's hidden on its floor: ask it, or watch it."),
    ("¤", "SHOPS", "Now and then a shop, behind a locked door (a small key, or two bombs). Buy with gold, or haggle: "
                   "wits takes a third off, or puts it up a quarter."),
    ("✧", "SECRETS", "Some moments are written by hand and hidden in the dungeon: a place, a word, a deed. The Book of "
                     "Secrets at the campfire counts the ones you've found."),
    ("◆", "WORDS", "Coloured names in the story (monsters, items, things in the room): hover for a hint, click for "
                   "the full card and the matching action."),
)
KEYS = (("F2 i", "inventory"), ("F3 c", "character"), ("F4 l", "look at the room"), ("F5 m", "map"),
        ("F6 b", "bestiary"), ("F7 j", "journal"), ("F1", "this help"), ("F8", "sound on/off"),
        ("Esc Esc", "the title (saved)"), ("Ctrl+Q", "quit"))
MORE_KEYS = (("F1-F7", "in any panel too: that panel instead"),
             ("F12", "debug: the library, art, sounds, story, the game's state, and a model check"),
             ("PgUp PgDn", "read back through the story"),
             ("Ctrl+L", "redraw the screen (if letters or art ever come out garbled)"),
             ("n s e w", "go north, south, east or west"))
MOUSE = ("Click a choice, a coloured word, a picture (for its card), or the dice (once to roll, again to carry on).",
         "Click loot in the story (▶ click to take) to pick it up: that's free, it takes no turn.",
         "The arrows beside the choices take you through a door: lit where there is one.",
         "Close any panel with its ✕ or a click outside it.")


def help_text() -> Group:
    """How to play, as tables that wrap to whatever width the panel has: each line of a rule wraps under its words,
    never back under its name (the help was once wrapped by hand, for a wider panel than it had)."""
    heading = "bold #ff4f9a"
    rules = Table.grid(padding=(0, 1))
    rules.add_column(no_wrap=True, style="bold #ffb000")
    rules.add_column(no_wrap=True, style="bold #ffb000", min_width=8)
    rules.add_column(ratio=1, style=WORDS)
    for icon, name, words in RULES:
        rules.add_row(icon, name, words)
    keys = Table.grid(padding=(0, 2))
    for _ in range(2):
        keys.add_column(no_wrap=True, style="bold #ffb000")
        keys.add_column(style=WORDS)
    for i in range(0, len(KEYS), 2):
        keys.add_row(*KEYS[i], *KEYS[i + 1])
    more = Table.grid(padding=(0, 2))
    more.add_column(no_wrap=True, style="bold #ffb000", min_width=7)
    more.add_column(ratio=1, style=WORDS)
    for key, words in MORE_KEYS:
        more.add_row(key, words)
    mouse = Table.grid(padding=(0, 1))
    mouse.add_column(no_wrap=True, style=DIM)
    mouse.add_column(ratio=1, style=WORDS)
    for words in MOUSE:
        mouse.add_row("·", words)
    return Group(
        Text("HOW TO PLAY", style=heading), Text(),
        Text("Type a number to take one of the choices, or type anything you want to try:", style=WORDS), Text(),
        *[Text("  " + line, style="italic #5fe3ff") for line in EXAMPLES], Text(),
        Text("The game decides what's possible and rolls the dice; the narrator only describes what happened.",
             style=WORDS), Text(),
        rules, Text(),
        Text.assemble(("KEYS", heading), ("  (or type the word)", DIM)), keys, more, Text(),
        Text("MOUSE", style=heading), mouse)


class HelpScreen(Panel):
    BINDINGS = [Binding("escape,f1,enter,q", "close", "Close")]
    panel_name = "help"

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="panel-box") as box:
            box.border_title = "Help"
            yield Static(help_text(), id="help-text")


# --- your things, and a shop's ----------------------------------------------------------------------------------------

def shelf_width(columns: int, size: int) -> int:
    """How wide a shelf of item tiles is: `columns` of them with pictures `size` pixels wide, the gaps between them,
    and room for a scrollbar."""
    return columns * (TILE[size][0] + 1) + 1


class ItemTile(Vertical):
    """One thing you carry, or one for sale, in a grid of them: its picture over its name and a note. Moving to it
    (or clicking it) shows it in full beside the grid."""

    can_focus = True

    def __init__(self, index: int, picture: Picture, words: Text, equipped: bool = False) -> None:
        classes = "item-tile" + (" equipped" if equipped else "") + (" full" if picture.art.pixels == DEFAULT_WIDTH
                                                                      else "")
        super().__init__(picture, Static(words, classes="tile-words"), classes=classes)
        self.index = index

    def on_focus(self) -> None:
        self.screen.show_detail(self.index)


def item_tile(index: int, game: Game, key: str, note: str, size: int, equipped: bool = False) -> ItemTile:
    """An item's tile, its picture `size` pixels wide (see TILE)."""
    content = game.content
    picture = Picture(key, "item", size, content=content, sprites=game.config.art == "sprites")
    return ItemTile(index, picture, item_words(content, key, note, TILE[size][0] - 2), equipped)


def detail_rows(height: int) -> int:
    """The most rows a detail column's picture gets on a screen `height` rows tall: full size (12 rows) only with
    DETAIL_WORDS to spare under it, else small."""
    return box_rows(height) - DETAIL_WORDS


class InventoryScreen(Panel):
    """What you carry, as tiles with their art: move to one (or click it) to see it in full, Enter to use it.
    Anything that isn't usable on its own is for creative use: close this and type what you do with it.

    The shelf of tiles scrolls, and so do the words about the one you've picked; what Enter does and the keys stay
    put at the bottom of its column."""

    BINDINGS = [Binding("left", "move(-1)", show=False, priority=True),
                Binding("right", "move(1)", show=False, priority=True),
                Binding("up", "move_rows(-1)", show=False, priority=True),
                Binding("down", "move_rows(1)", show=False, priority=True),
                Binding("enter", "use", "Use", priority=True),
                Binding("t", "turn_over", "Turn it over", show=False, priority=True)]
    size_class = "wide"
    panel_name = "inventory"

    def __init__(self, game: Game) -> None:
        super().__init__()
        self.game = game
        self.current = 0
        self.columns = 3

    def plan(self, count: int) -> tuple[int, int]:
        """How `count` tiles sit on this screen, (their pictures' size, the box's width): full size, three across, if
        the screen's wide enough for that and a picture in full beside them, and tall enough for two rows of them (or
        all there are); else small, three across, or fewer on a narrow screen (and with ASCII art, whose glyph is only
        a lot of space at full size). Sets the columns."""
        width, height = self.app.size
        full = shelf_width(3, DEFAULT_WIDTH) + box_frame(height)[0] + 2  # (the side's padding)
        tall = box_rows(height) >= min(2, -(-count // 3)) * TILE[DEFAULT_WIDTH][1]
        if width >= full + 30 and tall and self.game.config.art == "sprites":
            self.columns = 3
            return DEFAULT_WIDTH, min(width, full + 36)
        width = min(100, width)
        self.columns = 3 if width >= 100 else 2 if width >= 76 else 1
        return SMALL, width

    def compose(self) -> ComposeResult:
        content, state = self.game.content, self.game.state
        player = state.player

        def verbs(ref: str) -> list[Action]:  # what the engine says you can do with it now (a tile's buttons)
            return interactions.verbs(state, content, ref)

        items = [(player.weapon, f"in hand · {content.item(player.weapon).damage}", verbs("gear:weapon"), True)]
        if player.armor:
            items.append((player.armor, f"worn · +{content.item(player.armor).defense} defense",
                          verbs("gear:armor"), True))
        counts: dict[str, int] = {}
        for key in player.inventory:
            counts[key] = counts.get(key, 0) + 1
        for key, count in counts.items():
            note = (f"×{count} · " if count > 1 else "") + item_note(content, key)
            items.append((key, note, verbs(f"item:{key}"), False))
        self.items = items
        size, width = self.plan(len(items))
        height = self.app.size.height
        side = width - box_frame(height)[0] - shelf_width(self.columns, size) - 2  # (less the side's padding)
        with Horizontal(classes="panel-box inventory-box") as box:
            box.border_title = f"Inventory · ¤ {player.gold} gold"
            box.styles.width = width
            with VerticalScroll(id="inv-shelf") as shelf:
                shelf.styles.width = shelf_width(self.columns, size)
                grid = Grid(*[item_tile(i, self.game, key, note, size, equipped)
                              for i, (key, note, _, equipped) in enumerate(items)], id="inv-grid")
                grid.styles.grid_size_columns = self.columns
                yield grid
            with Vertical(id="inv-side"):
                art = Picture("", "item", side, detail_rows(height), content=content,
                              sprites=self.game.config.art == "sprites", id="inv-art")
                art.display = art.sprites  # (an ASCII glyph would only be a lot of space)
                yield art
                if art.sprites:  # (the one picked turns here instead, if it has a model: ui/model_view.py)
                    from .model_view import SHOWN, ModelView, CALM

                    model = ModelView(spin=SHOWN, fps=CALM, id="inv-model")
                    model.styles.height, model.display = min(detail_rows(height), side // 2), False
                    yield model
                with VerticalScroll(id="inv-words"):
                    yield Static("", id="inv-detail")
                yield Vertical(id="inv-use")  # what you can do with it: a button for each (see show_detail)
                hint = Text("arrows pick · enter uses · esc closes", style=DIM)
                if height >= TALL:
                    hint.append("\n\nTo use something creatively, close this and type what you do with it.")
                yield Static(hint, id="inv-hint")

    def on_mount(self) -> None:
        self.query(ItemTile).first().focus()

    def show_detail(self, index: int) -> None:
        self.current = index
        content, player = self.game.content, self.game.state.player
        key, _, buttons, equipped = self.items[index]
        item = content.item(key)
        art = self.query_one("#inv-art", Picture)
        art.become(key)
        blank = art.blank and art.sprites  # nobody has drawn it yet: it's its kind's grey stand-in
        for model in self.query("#inv-model"):  # (its model turning, if it has one: its picture's on its tile)
            turns = model3d.available(key) and not blank
            model.display, art.display = turns, not turns
            if turns:
                model.show(key)
        text = Text()
        text.append(item.name + "\n", style="bold #4cff8a")
        might = f" + {player.might} for your might" if key == player.weapon else ""
        text.append(item_note(content, key) + might + "\n", style=WORDS)
        if equipped:
            text.append("in your hand\n" if item.kind == "weapon" else "you're wearing it\n", style="#ffb000")
        text.append_text(power_lines(content, key))
        if item.desc:
            text.append("\n" + item.desc + "\n", style=f"italic {WORDS}")
        if item.tags:
            text.append("\ntags: " + ", ".join(item.tags) + "\n", style="#5fe3ff")
        ideas = [TAG_IDEAS[t] for t in item.tags if t in TAG_IDEAS]
        if ideas:
            text.append("Ideas: " + "; ".join(ideas[:2]), style="#ff4f9a")
        if blank:
            text.append("\n\nNo picture yet: draw one in the Monster & Item Maker.", style=DIM)
        text.rstrip()
        self.query_one("#inv-detail", Static).update(text)
        self.query_one("#inv-words").scroll_home(animate=False)
        box = self.query_one("#inv-use", Vertical)
        box.remove_children()
        first = self.default(buttons)
        for i, action in enumerate(buttons):  # (Enter does the first that's a use; the rest are a click away)
            label = f"▶ {action.label}" + (f"  [{action.hint}]" if action.hint else "")
            box.mount(Clickable(Text(label + ("  (enter)" if action is first else ""),
                                     style="bold #4cff8a" if action is first else "#9a9cc0"),
                                f"screen.verb({i})", classes="inv-verb"))
        if first is None:
            idle = {"key": "It must open something important.", "trinket": "No use on its own: try it creatively.",
                    "consumable": "Throw it in a fight to get away." if item.escape else
                    "You're at full health." if player.hp >= player.max_hp else "Not now."}
            box.mount(Static(Text(idle.get(item.kind, ""), style=DIM)))
        if art.sprites and model3d.available(key):  # a model of it to turn over (ui/model_view.py)
            box.mount(Clickable(Text("↻ Turn it over  (t)", style="#5fe3ff"), "screen.turn_over", classes="inv-verb"))

    def action_move(self, step: int) -> None:
        tiles = list(self.query(ItemTile))
        tiles[max(0, min(len(tiles) - 1, self.current + step))].focus()

    def action_move_rows(self, rows: int) -> None:
        self.action_move(rows * self.columns)

    def action_turn_over(self) -> None:
        """t: the picked thing's model, in a window to turn it over in, if it has one (ui/model_view.py)."""
        key = self.items[self.current][0]
        if self.app.screen is self and self.game.config.art == "sprites" and model3d.available(key):
            from .model_view import ModelScreen  # (it builds on the panels here)

            sound.play("select")
            self.app.push_screen(ModelScreen(key, self.game.content.item(key).name))

    @staticmethod
    def default(buttons: list[Action]) -> Action | None:
        """What Enter does: the first button that uses the thing (or puts it on), never dropping or selling it."""
        return next((a for a in buttons if a.id.partition(":")[0] in (*USES, "equip") and
                     not interactions.is_picker(a.id)), None)

    def named(self, action: Action) -> Action:
        """A button's words are bare ("Use"): the story says what it was done to ("Use · Pure")."""
        key = self.items[self.current][0]
        return Action(action.id, f"{action.label} · {self.game.content.item(key).name}", action.hint)

    def action_use(self) -> None:
        action = self.default(self.items[self.current][2])
        if self.peek:
            self.notify("Choose your perk first: then it's yours to use.", timeout=3)
        elif action:
            self.dismiss(self.named(action))
        else:
            self.notify("Not usable on its own. Try typing what you want to do with it.", timeout=3)

    def action_verb(self, index: int) -> None:
        """A button on the picked thing: that action, as the engine has it (a picker opens its list)."""
        buttons = self.items[self.current][2]
        if self.peek:
            self.notify("Choose your perk first: then it's yours to use.", timeout=3)
        elif 0 <= index < len(buttons) and self.app.screen is self:
            sound.play("select")
            self.dismiss(self.named(buttons[index]))


class ShopScreen(Panel):
    """A shop: the shopkeeper, her wares on the counter as tiles with their prices, and the one you pick in full, to
    buy (Enter) or haggle over (B). Either comes back to the game as a turn (a haggle rolls the dice), and the shop
    opens again after it. Like the inventory, the counter and the words about a ware scroll; Buy, Haggle and the keys
    stay put."""

    BINDINGS = [Binding("left", "move(-1)", show=False, priority=True),
                Binding("right", "move(1)", show=False, priority=True),
                Binding("up", "move_rows(-1)", show=False, priority=True),
                Binding("down", "move_rows(1)", show=False, priority=True),
                Binding("enter", "buy", "Buy", priority=True),
                Binding("b", "barter", "Barter"),
                Binding("s", "sell", "Sell")]
    size_class = "wide"

    def __init__(self, game: Game, selected: int = 0) -> None:
        super().__init__()
        self.game = game
        self.current = selected
        self.columns = 2

    def plan(self) -> tuple[int, int, int, int]:
        """How the shop sits on this screen, (the box's width, the wares' picture size, the shopkeeper's or 0 when
        there's no room for her, the side's width): she and her wares at full size if there's room for them and a ware
        in full beside them, giving way in this order: the wares small, then her small, then her not at all, then the
        wares one to a row. Sets the columns."""
        width, height = self.app.size
        tall = box_rows(height) >= min(2, -(-len(self.game.state.room.shop.wares) // 2)) * TILE[DEFAULT_WIDTH][1]
        box = min(width, SHOP_WIDTH)
        inside = box - box_frame(height)[0] - 2  # (the side's padding)
        ways = [(DEFAULT_WIDTH, DEFAULT_WIDTH, 2)] if tall and self.game.config.art == "sprites" else []
        ways += [(DEFAULT_WIDTH, SMALL, 2), (SMALL, SMALL, 2), (0, SMALL, 2), (0, SMALL, 1)]
        for keeper, size, columns in ways:
            side = inside - KEEPER.get(keeper, 0) - shelf_width(columns, size)
            if side >= SIDE or columns == 1:
                self.columns = columns
                return box, size, keeper, side

    def compose(self) -> ComposeResult:
        content, state = self.game.content, self.game.state
        shop = state.room.shop
        keeper = content.monster(shop.keeper)
        sprites = self.game.config.art == "sprites"
        width, size, keeper_size, side = self.plan()
        with Horizontal(classes="panel-box shop-box") as box:
            box.border_title = f"{keeper.name}'s Shop · ¤ {state.player.gold} gold"
            box.styles.width = width
            with Vertical(id="shop-keeper") as column:
                column.display = bool(keeper_size)
                column.styles.width = KEEPER.get(keeper_size, 0)
                yield Picture(shop.keeper, "monster", keeper_size or SMALL, content=content, style="#ffd166",
                              sprites=sprites, classes="panel-sprite")
                says = Text(keeper.name, style="bold #ffd166")
                if keeper_size == DEFAULT_WIDTH:  # (a narrow column has room for her name, not all she is)
                    says.append("\n" + keeper.desc, style=f"italic {WORDS}")
                yield Static(says, id="shop-says")
            with VerticalScroll(id="shop-shelf") as shelf:
                shelf.styles.width = shelf_width(self.columns, size)
                if shop.wares:
                    grid = Grid(*[item_tile(i, self.game, w.item, price_note(w), size)
                                  for i, w in enumerate(shop.wares)], id="shop-grid")
                    grid.styles.grid_size_columns = self.columns
                    yield grid
                else:
                    yield Static(Text("Sold out. She's counting your gold.", style=DIM))
            with Vertical(id="shop-side"):
                art = Picture("", "item", side, detail_rows(self.app.size.height), content=content,
                              sprites=sprites, id="shop-art")
                art.display = sprites
                yield art
                with VerticalScroll(id="shop-words"):
                    yield Static("", id="shop-detail")
                    yield Static("", id="shop-about")
                yield Clickable("", "screen.buy", id="shop-buy")
                yield Clickable("", "screen.barter", id="shop-barter")
                yield Clickable(Text("▶ Sell something  (s)", style="bold #ffb000"), "screen.sell", id="shop-sell")
                yield Static(Text("arrows pick · enter buys · b haggles · s sells · esc leaves", style=DIM), id="shop-hint")

    def on_mount(self) -> None:
        tiles = list(self.query(ItemTile))
        if tiles:
            tiles[max(0, min(len(tiles) - 1, self.current))].focus()

    def show_detail(self, index: int) -> None:
        self.current = index
        content, player = self.game.content, self.game.state.player
        ware = self.game.state.room.shop.wares[index]
        item = content.item(ware.item)
        self.query_one("#shop-art", Picture).become(ware.item)
        text = Text()
        text.append(item.name + "\n", style="bold #4cff8a")
        text.append(item_note(content, ware.item) + "\n", style=WORDS)
        text.append(f"\n¤ {ware.price} gold" + (f" each · {ware.count} left" if ware.count > 1 else ""),
                    style="bold #ffd166")
        text.append({"down": "  talked down", "up": "  dearer since you haggled"}.get(ware.haggled, ""), style=SOFT)
        if item.kind in inventory.GEAR:  # against what you have on, and whether it'd only be a spare
            state = self.game.state
            text.append(f"\n\nvs yours: {inventory.versus(state, content, ware.item)}", style=WORDS)
            if not inventory.upgrade(state, content, ware.item):
                text.append("\nYou'd carry it as a spare: it's no better than what you have on.", style="#ffb000")
        self.query_one("#shop-detail", Static).update(text)
        about = power_lines(content, ware.item)
        about.append(item.desc, style=f"italic {WORDS}")
        about.rstrip()
        self.query_one("#shop-about", Static).update(about)
        self.query_one("#shop-words").scroll_home(animate=False)
        short = player.gold < ware.price
        self.query_one("#shop-buy", Clickable).update(
            Text(f"You have {player.gold} gold." if short else f"▶ Buy it for {ware.price} gold  (enter)",
                 style=DIM if short else "bold #4cff8a"))
        self.query_one("#shop-barter", Clickable).update(
            Text("She won't haggle over it again." if ware.haggled else "▶ Haggle  (b) · wits",
                 style=DIM if ware.haggled else "bold #ffb000"))

    def action_move(self, step: int) -> None:
        tiles = list(self.query(ItemTile))
        if tiles:
            tiles[max(0, min(len(tiles) - 1, self.current + step))].focus()

    def action_move_rows(self, rows: int) -> None:
        self.action_move(rows * self.columns)

    def _ware(self):
        wares = self.game.state.room.shop.wares
        return (self.game.content.item(wares[self.current].item), wares[self.current]) if wares else (None, None)

    def action_buy(self) -> None:
        item, ware = self._ware()
        if item is None:
            return
        if self.game.state.player.gold < ware.price:
            self.notify(f"{item.name} is {ware.price} gold, and you have {self.game.state.player.gold}.", timeout=3)
            return
        self.dismiss(Action(f"buy:{self.current}", f"Buy {the(item.name)} for {ware.price} gold"))

    def action_sell(self) -> None:
        """What you'd sell her: the picker of what you carry that she'd buy (at half the price here), or why not."""
        state, content = self.game.state, self.game.content
        keeper = state.room.shop.keeper
        picker = next((a for a in interactions.verbs(state, content, f"keeper:{keeper}")
                       if interactions.is_picker(a.id) and a.id.startswith("sell:")), None)
        if picker is None:
            self.notify("There's nothing you carry that she'd buy.", timeout=3)
        else:
            self.dismiss(picker)

    def action_barter(self) -> None:
        item, ware = self._ware()
        if item is None:
            return
        if ware.haggled:
            self.notify("She won't haggle over that again.", timeout=3)
            return
        self.dismiss(Action(f"barter:{self.current}", f"Haggle over {the(item.name)}"))


def price_note(ware) -> str:
    """A ware's price on its tile: talked down (↓), or dearer since you haggled (↑), and how many she has (×2)."""
    return f"¤ {ware.price}" + {"down": " ↓", "up": " ↑"}.get(ware.haggled, "") + \
        (f" ×{ware.count}" if ware.count > 1 else "")


def whereabouts(game: Game, key: str) -> list[str]:
    """Where an item is, as far as you're concerned: in your hand or on you, in your pack (how many), lying here, or
    for sale here (at what price)."""
    player, room = game.state.player, game.state.room
    places = ["in your hand"] if key == player.weapon else ["you're wearing it"] if key == player.armor else []
    count = player.inventory.count(key)
    if count:
        places.append("in your pack" + (f" ×{count}" if count > 1 else ""))
    if key in room.items:
        places.append("lying here")
    if room.shop:
        places += [f"for sale here: ¤ {ware.price}" for ware in room.shop.wares if ware.item == key]
    return places


def gear_comparison(game: Game, key: str) -> str:
    """A weapon or armor you haven't got on, beside what you have: "your Rusty Sword: 1d6 → 2d6" (a line, or "" for
    anything else)."""
    player, content = game.state.player, game.content
    item = content.item(key)
    if item.kind not in ("weapon", "armor") or key in (player.weapon, player.armor):
        return ""
    worn = content.items.get(player.weapon if item.kind == "weapon" else player.armor)
    if item.kind == "weapon":
        mine, this = (worn.damage if worn else "none"), item.damage
    else:
        mine, this = (f"+{worn.defense}" if worn else "none"), f"+{item.defense} defense"
    return f"your {worn.name if worn else item.kind}: {mine} → {this}\n"


# --- you, the room, the floor, the creatures you've met, what's happened ----------------------------------------------

SHEET_WIDTH = 116  # the widest the character sheet's box gets
STAT_COLOURS = {"Might": "#ff7b7b", "Agility": "#4cff8a", "Wits": "#5fe3ff", "HP": "#ff4b4b", "Defense": "#6c8cff",
                "Fate": "#ffd166"}
LINK = "bold #4cff8a"  # a thing you carry, named on the sheet: click for its card
CURSE = "bold #ff4b4b"


def link(content: Content, key: str, name: str = "", style: str = LINK) -> Text:
    """A thing's name that opens its card when clicked, with what it is on hover (as a highlighted word does)."""
    return Text(name or content.item(key).name,
                style=Style.parse(style) + Style(meta={"term": f"item:{key}", "tip": glossary.item_summary(content, key)}))


def part_text(content: Content, part: sheet.Part, signed: bool = True) -> Text:
    """One piece of a sum: "+2 A Ring, Probably Important" (a link, if it's something you carry), or "base 1"."""
    value = f"{part.value:+d} " if signed and part.name != "base" else f"{part.value} " if part.name != "base" else ""
    if part.name == "base":
        return Text(f"base {part.value}", style=DIM)
    if part.item:
        return Text(value, style=WORDS) + link(content, part.item, part.name)
    return Text(value + part.name, style=WORDS)


class Sheet(Vertical):
    """A character sheet, laid out like a tabletop one: who you are; your stats in boxes, each with what it's made of;
    what you have on and carry and what it does for you (or to you); every kind of roll you make with all that adds
    to it and where that comes from; and your perks, traits and blessings. The sums are sheet.py's. Anything you
    carry is a link to its card (Panel.action_lookup). The Character panel's, and a level-up's under its perk cards:
    `show` draws it again for another state (a perk taken), lighting what's changed since the one it was made for."""

    DEFAULT_CSS = """
    Sheet { height: auto; }
    """

    def __init__(self, game: Game, inner: int, header: bool = True, **kwargs) -> None:
        super().__init__(**kwargs)
        self.game, self.inner, self.header = game, inner, header

    def compose(self) -> ComposeResult:
        state = self.game.state
        if self.header:
            yield Static(self._header(state), classes="sheet-header")
        stats = Grid(*[self._stat_card(line) for line in self._stats(state)], id="sheet-stats")
        stats.styles.grid_size_columns = 6 if self.inner >= 90 else 3 if self.inner >= 48 else 2
        yield stats
        cols = Grid(StoryLine(self._gear(state), classes="sheet-section sheet-gear"),
                    StoryLine(self._rolls(state), classes="sheet-section sheet-rolls"),
                    id="sheet-cols")
        cols.styles.grid_size_columns = 2 if self.inner >= 90 else 1
        yield cols
        yield StoryLine(self._growth(state), classes="sheet-section sheet-growth")

    def show(self, state: GameState, perk: str = "") -> None:
        """The sheet as it would be in `state` (the game's with `perk` taken), what's changed from the game's own lit:
        a stat's box, a roll, the blow, the perk itself."""
        was = self.game.state
        for card, line, old in zip(self.query(".stat-card"), self._stats(state), self._stats(was)):
            self._fill(card, line, old)
        self.query_one(".sheet-gear", StoryLine).update(self._gear(state, was))
        self.query_one(".sheet-rolls", StoryLine).update(self._rolls(state, was))
        self.query_one(".sheet-growth", StoryLine).update(self._growth(state, perk))

    # --- the parts of the sheet ----------------------------------------------------------------------------------

    def _header(self, state: GameState) -> Text:
        player = state.player
        text = Text(player.name, style="bold #ffb000")
        text.append(f"  {epithet(state)}", style="italic #ffd166")
        text.append(f"\nLevel {player.level}", style="bold")
        text.append("   ")
        text.append_text(xp_bar(player))
        text.append(f"   ·   ¤ {player.gold} gold   ·   ☽ {state.souls} souls this descent", style=WORDS)
        return text

    def _stats(self, state: GameState) -> list[sheet.Line]:
        content = self.game.content
        return [*(sheet.stat_line(state, content, stat) for stat in sheet.STATS), sheet.hp_line(state, content),
                sheet.defense_line(state, content), sheet.fate_line(state, content)]

    def _stat_card(self, line: sheet.Line) -> StoryLine:
        """One stat in its box: the number big, what it's made of under it."""
        card = StoryLine(Text(), classes="stat-card")
        card.border_title = line.label.upper()
        self._fill(card, line)
        return card

    def _fill(self, card: StoryLine, line: sheet.Line, was: sheet.Line | None = None) -> None:
        """A stat's box, for `line`; if it's not what it `was`, lit, with an arrow up or down and what it was."""
        colour = STAT_COLOURS.get(line.label, "bold")
        big, parts = stat_big(line), line.parts[1:] if line.label == "HP" else line.parts
        changed = was is not None and stat_big(was) != big
        text = Text(big, style=f"bold {colour}", justify="center")
        if changed:
            up = line.total > was.total or line.parts[0].value > was.parts[0].value
            text.append(" ▲" if up else " ▼", style="bold #4cff8a" if up else "bold #ff4b4b")
            text.append(f"\nwas {stat_big(was)}", style=DIM)
        for part in parts:
            text.append("\n")
            text.append_text(part_text(self.game.content, part))
        card.update(text)
        card.styles.border = ("heavy" if changed else "round", colour)
        card.styles.border_title_color = colour
        card.set_class(changed, "-changed")

    def _gear(self, state: GameState, was: GameState | None = None) -> Group:
        """What you have on and carry that works on you, and what it does: damage, defense, powers, curses. A grid,
        so what's said of a thing wraps under its name, not under its icon."""
        content = self.game.content
        damage = sheet.damage_line(state, content)
        blow = Text("A blow: ", style="bold") + Text(damage.note, style="bold #ffb000")
        for part in damage.parts[1:]:
            blow.append(" + " if part.value >= 0 else " - ", style=DIM)
            blow.append_text(part_text(content, part, signed=False) if part.value else
                             (link(content, part.item, part.name, WORDS) if part.item else Text(part.name, style=WORDS)))
        before = sheet.damage_line(was, content).total if was is not None else damage.total
        if before != damage.total:
            up = damage.total > before
            blow.append(" ▲" if up else " ▼", style="bold #4cff8a" if up else "bold #ff4b4b")
        table = Table.grid(padding=(0, 1), expand=True)
        table.add_column(no_wrap=True)
        table.add_column(ratio=1)
        icons = {"in hand": "⚔", "worn": "⛨"}
        for effect in sheet.carried_effects(state, content):
            words = link(content, effect.item, style=CURSE if effect.cursed else LINK)
            if effect.worn:
                words.append(f" ({effect.worn})", style=DIM)
            if effect.cursed:
                words.append("  CURSED", style="bold reverse #ff4b4b")
            for said in effect.says:
                words.append(f"\n{said}", style=WORDS)
            table.add_row(Text(icons.get(effect.worn, "◆"), style="#ffb000" if effect.worn else "#c084fc"), words)
        return Group(Text("WHAT YOU CARRY", style="bold #ff4f9a"), blow, Text(""), table)

    def _rolls(self, state: GameState, was: GameState | None = None) -> Group:
        """Every kind of roll you make: the d20 plus this, and where each bit comes from (a grid, so the sources
        wrap in their own column). A roll that's changed since `was` is lit."""
        content = self.game.content
        before = {line.label: line.total for line in sheet.roll_lines(was, content)} if was is not None else {}
        table = Table.grid(padding=(0, 1), expand=True)
        table.add_column(no_wrap=True)
        table.add_column(justify="right", no_wrap=True)
        table.add_column(ratio=1)
        for line in sheet.roll_lines(state, content):
            sources = Text()
            for i, part in enumerate(p for p in line.parts if p.value):
                if i:
                    sources.append(" · ", style=DIM)
                sources.append_text(part_text(content, part))
            if line.note:
                sources.append(f"{' · ' if sources.plain else ''}{line.note}", style="italic #ffd166")
            total = Text(f"{line.total:+d}", style="bold #ffb000")
            if line.label in before and before[line.label] != line.total:
                total = Text(f"▲{line.total:+d}" if line.total > before[line.label] else f"▼{line.total:+d}",
                             style="bold reverse #4cff8a" if line.total > before[line.label] else "bold reverse #ff4b4b")
            table.add_row(Text(line.label, style="bold"), total, sources)
        return Group(Text("YOUR ROLLS ", style="bold #ff4f9a") + Text("d20 +", style=DIM), table)

    def _growth(self, state: GameState, new: str = "") -> Text:
        return growth_text(state, self.game.content, new)


def growth_text(state: GameState, content: Content, new: str = "") -> Text:
    """Perks you chose (one about to be, `new`, marked), traits you earned by how you play, and the campfire's
    blessings: the sheet's last part, and the Tabs layout's sheet pane's."""
    player = state.player
    text = Text("PERKS\n", style="bold #ff4f9a")
    for key in player.perks or []:
        perk = content.perks[key]
        text.append(f"  {perk.name}", style=f"bold {PERK_COLORS.get(perk.color, '')}")
        text.append(f"  {perk.desc}", style=WORDS)
        text.append("  ★ new\n" if key == new else "\n", style="bold #ffd166")
    if not player.perks:
        text.append("  none yet: level up to choose one\n", style=DIM)
    text.append("\nTRAITS  (earned by how you play)\n", style="bold #ff4f9a")
    for key, (name, counter, threshold, desc) in TRAITS.items():
        have = key in player.traits
        progress = min(player.style.get(counter, 0), threshold)
        mark = "★" if have else f"{progress}/{threshold}"
        text.append(f"  {mark:>5} {name}", style="bold #4cff8a" if have else SOFT)
        text.append(f"  {desc}\n", style=WORDS if have else DIM)
    if player.blessings:
        text.append("\nBLESSINGS\n", style="bold #ff4f9a")
        for key in player.blessings:
            unlock = content.unlocks[key]
            text.append(f"  {unlock.icon} {unlock.name}  {unlock.desc}\n", style=WORDS)
    return text


def stat_big(line: sheet.Line) -> str:
    """A stat's number as its box shows it big: "+2" (might, agility, wits), "32/40" (HP), "✦✦✧ 2/3" (fate), "11"."""
    if line.label == "HP":
        return f"{line.total}/{line.parts[0].value}"
    if line.label == "Fate":
        most = int(line.note.removeprefix("of "))
        return "✦" * line.total + "✧" * (most - line.total) + f" {line.total}/{most}"
    return f"{line.total:+d}" if line.label.lower() in sheet.STATS else str(line.total)


def xp_bar(player, width: int = 16) -> Text:
    """"XP 30/80 ████░░░░" to the next level, or that there's none."""
    need = player.next_level_xp()
    if not need:
        return Text(f"XP {player.xp} (the most there is)", style=WORDS)
    filled = round(width * min(player.xp, need) / need)
    return (Text(f"XP {player.xp}/{need} ", style=WORDS) + Text("█" * filled, style="#ff4f9a")
            + Text("░" * (width - filled), style="#3a2a44"))


class CharacterScreen(Panel):
    """Your character sheet (Sheet), in a wide panel."""

    panel_name = "character"
    size_class = "wide"

    def __init__(self, game: Game) -> None:
        super().__init__()
        self.game = game

    def compose(self) -> ComposeResult:
        width = min(SHEET_WIDTH, self.app.size.width - 2)
        with VerticalScroll(classes="panel-box sheet-box") as box:
            box.border_title = "Character Sheet"
            box.styles.width = width
            yield Sheet(self.game, width - 6)  # (less the frame, the padding and the scrollbar)


def exits_text(state: GameState, room: Room) -> Text:
    """A room's ways out as they are now: where each leads, if you've been, else what you can see through it (a
    fixture, a shop's locked door), else unexplored."""
    exits = []
    for direction, exit_ in room.exits.items():
        dest = state.rooms[exit_.to]
        seen = dest.fixture if dest.fixture and not dest.fixture_used else "unexplored"
        note = "sealed with web" if exit_.webbed else ("locked; a shop beyond" if dest.shop else "locked") \
            if exit_.locked else (dest.name if dest.visited else seen)
        exits.append(f"{direction} ({note})")
    return Text.assemble(("Exits: ", "bold"), (", ".join(exits) or "none", WORDS))


def room_now(state: GameState, content: Content, room: Room) -> Text:
    """What a room is like now, from the game's state (never what was said walking in, which goes stale: a fight long
    over, a door since opened): what kind of place it is, who's in it and what's lying there (if you've been), and its
    ways out."""
    here = []
    monster = room.monster if room.visited else None
    if monster is not None and monster.hp > 0:
        how, colour = (f"hostile, {monster.hp}/{monster.max_hp} HP", "#ff4b4b") if monster.hostile else ("calm", "#ffd166")
        here.append(Text(f"{cap(the(monster.name))} is here ({how}).", style=colour))
    items = [content.item(key).name for key in room.items] if room.visited else []
    if items:
        here.append(Text("Lying here: " + ", ".join(items) + ".", style="#4cff8a"))
    text = Text(content.archetypes[room.archetype].blurb, style=WORDS)
    for part in ([Text("\n").join(here)] if here else []) + [exits_text(state, room)]:
        text.append("\n\n")
        text.append_text(part)
    return text


class LookScreen(Panel):
    """The room you're in, as it is now: its picture, what kind of place it is, who and what's in it, its ways out
    and its floor plan."""

    panel_name = "look"

    def __init__(self, game: Game) -> None:
        super().__init__()
        self.game = game

    def compose(self) -> ComposeResult:
        state, content = self.game.state, self.game.content
        room = state.room
        picture = self.picture()
        plan = room_text(state, content)
        body = picture or plan  # the floor plan goes last when there's a picture
        body.append("\n\n")
        body.append_text(room_now(state, content, room))
        if picture:
            body.append("\n\n")
            body.append_text(plan)
        with VerticalScroll(classes="panel-box") as box:
            box.border_title = f"{room.name} · floor {state.floor}"
            yield Static(body)

    def picture(self) -> Text | None:
        """The room as you see it (see room_picture), as wide as the panel and as tall as the screen allows."""
        width = min(LOOK_PICTURE, self.app.size.width - 8)  # a wider line would wrap, and a picture can't
        if self.game.config.art != "sprites" or width < 36:
            return None
        rows = max(10, min(20, self.app.size.height - 28))
        return picture_text(self.game.state, self.game.content, width, 2 * rows)


class MapScreen(Panel):
    panel_name = "map"

    def __init__(self, game: Game) -> None:
        super().__init__()
        self.game = game

    def compose(self) -> ComposeResult:
        state, content = self.game.state, self.game.content
        theme = content.themes[state.theme]
        body = map_text(state)
        body.append(f"\n\n{theme.name}: {theme.blurb}", style=WORDS)
        floors = " → ".join(content.themes[t].name + (" (here)" if i + 1 == state.floor else "")
                            for i, t in enumerate(state.themes))
        body.append(f"\n\nThe descent: {floors}\nGoal: {content.themes[state.themes[-1]].goal}", style=SOFT)
        with VerticalScroll(classes="panel-box") as box:
            box.border_title = f"Map · floor {state.floor} of {state.floors_total}"
            yield Static(body)


class BestiaryScreen(Panel):
    """The creatures you've met, a list to move through (arrows or a click), and the one you're on in full beside it:
    its picture, what you know of it, and what it's weak to."""

    size_class = "wide"
    panel_name = "bestiary"

    def __init__(self, game: Game) -> None:
        super().__init__()
        self.game = game
        self.entries = sorted(game.profile.bestiary().items(), key=lambda kv: kv[1]["first_seen"] or 0)

    def compose(self) -> ComposeResult:
        content = self.game.content
        with Horizontal(classes="panel-box bestiary-box") as box:
            box.border_title = f"Bestiary · {len(self.entries)} of {len(content.monsters)} discovered"
            names = [ListItem(Label(content.monster(k).name)) for k, _ in self.entries if k in content.monsters]
            yield ListView(*names, id="beast-list")
            yield VerticalScroll(Picture("", "monster", content=content, sprites=self.game.config.art == "sprites",
                                         id="beast-art", classes="panel-sprite"),
                                 Static("", id="beast-detail"), id="beast-body")

    def on_mount(self) -> None:
        if self.entries:
            self.show(0)
        else:
            self.query_one("#beast-detail", Static).update(Text("Nothing yet. Go meet something.", style=DIM))

    @on(ListView.Highlighted)
    def highlighted(self, event: ListView.Highlighted) -> None:
        self.show(event.list_view.index or 0)

    def show(self, index: int) -> None:
        content = self.game.content
        key, entry = self.entries[index]
        monster = content.monster(key)
        self.query_one("#beast-art", Picture).become(key)  # (its ASCII art, with sprites off or no sprite yet)
        text = Text()
        text.append(f"{monster.name}\n", style="bold #ffb000")
        if monster.desc:
            text.append(monster.desc + "\n", style=WORDS)
        text.append(f"seen {entry['seen']} · slain {entry['killed']} · pacified {entry['pacified']} · "
                    f"killed you {entry['killed_you']}\n", style=SOFT)
        weak = entry["weak"]
        text.append("Weak to: ", style="bold")
        text.append(", ".join(weak) if weak else "???", style="#5fe3ff" if weak else DIM)
        hidden = len(set(monster.weak) - set(weak))
        if weak and hidden:
            text.append(f"  (+{hidden} undiscovered)", style=DIM)
        text.append("\n\n")
        text.append(entry["lore"] or "No notes yet.", style=f"italic {WORDS}")
        self.query_one("#beast-detail", Static).update(text)
        self.query_one("#beast-body").scroll_home(animate=False)


JOURNAL_SHOWN = 250  # the journal's last lines (it scrolls)


class JournalScreen(Panel):
    """What's happened this run, oldest first, scrolled to the end, written in ink on a page of parchment (as the map
    is drawn: see grid.ChartScreen): the quests at the top, then each turn's events, each roll's line fainter with
    its bonuses and what came of it, and everything you gained, gave away, used or lost. A name in it opens its card
    (Panel.action_lookup)."""

    panel_name = "journal"

    def __init__(self, game: Game) -> None:
        super().__init__()
        self.game = game

    def compose(self) -> ComposeResult:
        state = self.game.state
        lexicon = self.lexicon()
        quests = Text()
        for _, line, still in npcs.quest_log(state, self.game.content):  # who wants what of you, the open ones first
            quests.append_text(highlight(("★ " if still else "✓ ") + line, lexicon,
                                         f"bold {RED_INK}" if still else FADED_INK, INK_STYLES))
            quests.append("\n")
        with VerticalScroll(classes="panel-box parchment") as box:
            box.border_title = f"Journal · turn {state.turn}"
            if quests.plain:
                yield StoryLine(quests)
                yield Static(Text("What's happened:", style=f"bold {INK}"))
            for line in state.journal[-JOURNAL_SHOWN:]:  # a roll's line faint, under what happened; names open cards
                roll = line.startswith("⚄ ")
                yield StoryLine(highlight(line if roll else "· " + line, lexicon, FADED_INK if roll else INK,
                                          INK_STYLES), classes="journal-roll" if roll else "journal-line")
            if not state.journal:
                yield Static(Text("Nothing written yet.", style=FADED_INK))

    def on_mount(self) -> None:
        self.query_one(VerticalScroll).scroll_end(animate=False)


# --- moments: a new floor, a level-up ---------------------------------------------------------------------------------

def floor_name(name: str, width: int) -> str:
    """A floor's name for its card: in capitals, letter-spaced if that fits on one line `width` wide."""
    spaced = "  ".join(" ".join(word) for word in name.upper().split())
    return spaced if len(spaced) <= width else name.upper()


def floor_words_rows(theme: Theme, final: bool, width: int) -> int:
    """About how many rows a floor card's words take `width` wide: its name with a blank line round it, its story,
    the goal and the way on, each with a line under it (a short screen drops those, but counting them is safe)."""
    rows = len(textwrap.wrap(floor_name(theme.name, width), width)) + 2
    rows += len(textwrap.wrap(theme.lore or theme.blurb, width)) + 1
    if final:
        rows += len(textwrap.wrap(f"Your goal: {theme.goal}", width)) + 1
    return rows + 2


def floor_card_fit(columns: int, rows: int, theme: Theme, final: bool) -> tuple[int, bool]:
    """How a floor's card sits on a screen this size: (its picture's width, 0 for none; whether its words go beside
    the picture rather than under it). The picture is the widest of its splash art's sizes (sprites.splash_sizes)
    that fits round the words, under it or beside it, whichever lets it be bigger: beside, on a screen with more room
    across than down. On a screen too small for all of them, the smallest is shrunk to fit, down to SPLASH_LEAST."""
    sizes = splash_sizes(theme.key)
    if not sizes:
        return 0, False
    frame_columns, frame_rows = box_frame(rows)
    across = columns - 4 - frame_columns  # (and room round the box, to click outside it)
    down = rows - (4 if rows >= TALL else 2) - frame_rows

    def widest(width: int, height: int) -> int:
        fits = [w for w, h in sizes if w <= width and h // 2 <= height]
        if fits:
            return fits[0]
        smallest, tall = sizes[-1]
        shrunk = min(width, smallest - 1, int(2 * height * smallest / tall))
        while shrunk >= SPLASH_LEAST and round(shrunk * tall / smallest / 2) > height:
            shrunk -= 1
        return shrunk if shrunk >= SPLASH_LEAST else 0

    under = widest(across, down - floor_words_rows(theme, final, min(FLOOR_WORDS, across)))
    beside = (widest(across - FLOOR_BESIDE - 2, down)
              if floor_words_rows(theme, final, FLOOR_BESIDE) <= down else 0)
    return (beside, True) if beside > under else (under, False)


class FloorScreen(Panel):
    """Arriving on a new floor: its splash art if it has some, its name and its story (its lore, or else what it's
    like), until you're ready to go on. The picture's as big as the screen has room for round the words (see
    floor_card_fit), sized as the card opens and again only if the screen is resized."""

    BINDINGS = [Binding("escape,enter,space,q", "close", "Continue")]
    size_class = "small"
    opening_sound = None  # the stairs already played their part

    def __init__(self, floor: int, total: int, theme: Theme, final: bool) -> None:
        super().__init__()
        self.floor, self.total, self.theme, self.final = floor, total, theme, final
        self.shown: tuple | None = None  # (columns, rows, picture's width, beside) as the card was last laid out

    def compose(self) -> ComposeResult:
        with Vertical(classes="panel-box floor-box") as box:
            box.border_title = f"Floor {self.floor} of {self.total}"
            yield Static(id="floor-art")
            with Vertical(classes="floor-words"):
                yield Static(classes="floor-name")
                yield Static(Text(self.theme.lore or self.theme.blurb, style=f"italic {WORDS}"))
                if self.final:
                    yield Static(Text(f"Your goal: {self.theme.goal}", style="bold #ffd166"))
                yield Clickable(Text(" ▶ [enter] continue ", style="#ffb000"), action="screen.close",
                                classes="panel-action")

    def fit(self) -> None:
        super().fit()
        columns, rows = self.app.size
        width, beside = floor_card_fit(columns, rows, self.theme, self.final)
        if self.app.config.art != "sprites":  # (ASCII art chosen in Settings: the words only)
            width, beside = 0, False
        if self.shown == (columns, rows, width, beside):
            return
        self.shown = (columns, rows, width, beside)
        frame = box_frame(rows)[0]
        if not width:  # words only, as wide as a small panel says
            words_width, art_rows = 64 - frame, 0
        else:
            words_width = FLOOR_BESIDE if beside else min(FLOOR_WORDS, columns - 4 - frame)
            art_rows = splash(self.theme.key, width).height // 2
        art = self.query_one("#floor-art", Static)
        art.display = bool(width)
        if width:
            art.update(splash_text(self.theme.key, width))
        # Under the picture, the words' column is the box's width and its lines are centred in it (a box centres what's
        # in it as one block, as wide as the picture); beside it, the column is as wide as the words.
        words = self.query_one(".floor-words")
        words.styles.width = words_width if beside else None
        for line in words.children:
            line.styles.width = words_width if width and not beside else None
        # Beside the picture, the words sit halfway down it (if they're shorter: else the box grows to them).
        short = beside and floor_words_rows(self.theme, self.final, words_width) <= art_rows
        words.styles.height = art_rows if short else None
        self.query_one(".floor-name", Static).update(Text(floor_name(self.theme.name, words_width),
                                                          style="bold #ff4f9a"))
        self.box.set_class(beside, "beside")
        self.box.styles.width = ((width + 2 + words_width if beside else max(width, words_width)) + frame
                                 if width else None)

    def on_click(self, event: Click) -> None:
        event.prevent_default()  # instead of Panel's: anywhere closes it, it's a title card
        self.action_close()


PORTRAIT = "hero_portrait"  # your face (data/sprites, art only): a level-up shows it
PORTRAIT_LOOP = [0, 0, 0, 1, 1, 0, 0, 0, 3, 3, 0, 0, 2]  # IDLE seconds a frame: ahead, a glance left, right, a blink
GAIN_STEP = 0.14  # seconds between a level-up's gains appearing, one row after another


def taken(game: Game, key: str) -> GameState:
    """The game's state as it would be with the perk `key` taken: a copy, for a level-up's preview of it."""
    state = game.state.model_copy(deep=True)
    rules.apply_perk(state, game.content, key)
    return state


def perk_changes(game: Game, state: GameState) -> Text:
    """What a perk would change on your sheet, a line a stat ("▲ HP 32/32 → 40/40"), then the blow, then the rolls
    it raises ("▲ +1 to Throw, Dodge, Flee and Pick a lock"); or that it changes no number but works in play."""
    content, was = game.content, game.state
    text = Text()

    def line(up: bool, words: str) -> None:
        text.append("\n" if text else "")
        text.append("▲ " if up else "▼ ", style="bold #4cff8a" if up else "bold #ff4b4b")
        text.append(words, style=WORDS)

    def lines(s: GameState) -> list[sheet.Line]:
        return [*(sheet.stat_line(s, content, k) for k in sheet.STATS), sheet.hp_line(s, content),
                sheet.defense_line(s, content), sheet.fate_line(s, content)]

    for new, old in zip(lines(state), lines(was)):
        if stat_big(new) != stat_big(old):
            up = new.total > old.total or new.parts[0].value > old.parts[0].value
            line(up, f"{new.label} {stat_big(old)} → {stat_big(new)}")
    blow, blow_was = sheet.damage_line(state, content), sheet.damage_line(was, content)
    if blow.total != blow_was.total:
        line(blow.total > blow_was.total, f"Damage {blow_was.total:+d} → {blow.total:+d} a blow")
    raised: dict[int, list[str]] = {}
    for new, old in zip(sheet.roll_lines(state, content), sheet.roll_lines(was, content)):
        if new.total != old.total:
            raised.setdefault(new.total - old.total, []).append(new.label.replace("Anything", "anything"))
    for change, labels in raised.items():
        named = labels[0] if len(labels) == 1 else f"{', '.join(labels[:-1])} and {labels[-1]}"
        line(change > 0, f"{change:+d} to {named}")
    return text or Text("No number on your sheet: it works in play.", style=f"italic {DIM}")


class LevelUpScreen(Panel):
    """A level-up, with the care the other windows get: your face (PORTRAIT, its eyes glancing about), what the level
    gave you, appearing a row at a time, three perk cards to choose from, and your whole sheet under them. Looking at
    a card (1-3, ← →, or a click) shows what it would change: on the card, and lit on the sheet. Enter, the button
    under them, or the same card again takes it. It can't be put off: there's no ✕, and Esc or a click outside only
    says so. F1-F7 still show a panel over it, for a look before you choose."""

    BINDINGS = [Binding("1", "look(0)", "First"), Binding("2", "look(1)", "Second"), Binding("3", "look(2)", "Third"),
                Binding("left", "step(-1)", show=False), Binding("right", "step(1)", show=False),
                Binding("enter", "take", "Take it")]
    size_class = "wide"
    closable = False
    opening_sound = None  # (a level-up has its own)

    def __init__(self, game: Game, choices: list[str]) -> None:
        super().__init__()
        self.game = game
        self.choices = choices
        self.looking: int | None = None  # the card looked at, which Enter takes
        self.previews = [taken(game, key) for key in choices]
        self.shown = 0  # the gains' rows shown so far (they come in a row at a time)

    def compose(self) -> ComposeResult:
        width = min(SHEET_WIDTH, self.app.size.width - 2)
        inner = width - 6  # less the frame, the padding and the scrollbar
        face = 24 if self.app.size.height >= TALL and inner >= 76 else 12 if inner >= 56 else 0
        with Vertical(classes="panel-box levelup-box") as box:
            box.border_title = f"Level up · level {self.game.state.player.level}"
            box.styles.width = width
            with VerticalScroll(id="levelup-body"):
                with Horizontal(id="levelup-top"):
                    if face:
                        with Vertical(id="levelup-face") as frame:
                            frame.border_title = self.game.state.player.name
                            yield Picture(PORTRAIT, "portrait", face, loop=PORTRAIT_LOOP, content=self.game.content,
                                          ascii=Text("\n" * (face // 4) + " " * (face // 2 - 1) + "@",
                                                     style="bold #ffd166"),
                                          sprites=self.game.config.art == "sprites")
                    yield Static(self._gains(0), id="levelup-gains")
                yield Static(Text("CHOOSE A PERK  ", style="bold #ff4f9a")
                             + Text("1-3, ← → or a click to look at one · Enter, or the same again, to take it",
                                    style=DIM), classes="levelup-rule")
                cards = Grid(*[PerkCard(self._card(i), i, self._colour(i)) for i in range(len(self.choices))],
                             id="levelup-perks")
                cards.styles.grid_size_columns = len(self.choices) if inner >= 84 else 1
                yield cards
                yield Static(Text("YOUR SHEET", style="bold #ff4f9a") + Text("  with the perk you look at, lit",
                                                                             style=DIM), classes="levelup-rule")
                yield Sheet(self.game, inner, header=False)
            with Horizontal(classes="panel-action", id="levelup-take"):
                yield Clickable(self._button(), action="screen.take", id="levelup-button", classes="card-verb")
                yield Static("", id="levelup-hint")

    def on_mount(self) -> None:
        super().on_mount()
        box = self.box
        box.border_title = ornate(str(box.border_title))
        box.styles.border_title_align = "center"
        self.set_interval(GAIN_STEP, self._more_gains, repeat=len(GAIN_ROWS))

    # --- what the level gave you ----------------------------------------------------------------------------------

    def _more_gains(self) -> None:
        self.shown += 1
        self.query_one("#levelup-gains", Static).update(self._gains(self.shown))

    def _gains(self, rows: int) -> Group:
        """Who you are and what the level gave you (GAIN_ROWS): the level, your max HP (and as much healed), your
        attack, and how far it is to the next; the first `rows` of them, the rest left blank till they come in (so
        nothing under them moves)."""
        state, content = self.game.state, self.game.content
        player = state.player
        who = Text(f"★ LEVEL {player.level} ★\n", style="bold #ffd166")
        who.append(player.name, style="bold #ffb000")
        who.append(f" {epithet(state)}", style="italic #ffd166")
        who.append(" has grown harder to kill.", style=WORDS)
        attack = next(line.total for line in sheet.roll_lines(state, content) if line.label == "Attack")
        gains = [("LEVEL", str(player.level - 1), str(player.level), "", "#ffd166"),
                 ("MAX HP", str(player.max_hp - rules.LEVEL_HP), str(player.max_hp),
                  f"+{rules.LEVEL_HP}, and {rules.LEVEL_HP} healed", STAT_COLOURS["HP"]),
                 ("ATTACK", f"{attack - 1:+d}", f"{attack:+d}", "+1 a level, on every swing", "#ffb000")]
        table = Table.grid(padding=(0, 2))
        for justify in ("left", "right", "center", "left", "left"):
            table.add_column(justify=justify, no_wrap=True)
        for n, (label, old, new, note, colour) in enumerate(gains):
            shown = n < rows
            table.add_row(Text(f"▲ {label}" if shown else "", style=f"bold {colour}"), Text(old * shown, style=DIM),
                          Text("→" * shown, style=DIM), Text(new * shown, style=f"bold {colour}"),
                          Text(note * shown, style=SOFT))
        last = Text("")
        if rows >= len(GAIN_ROWS):
            last = (xp_bar(player) + Text(f"  to level {player.level + 1}", style=DIM) if player.next_level_xp()
                    else Text("The most a level goes: there's no more XP to earn.", style=DIM))
        return Group(who, Text(""), table, Text(""), last)

    # --- the cards ------------------------------------------------------------------------------------------------

    def _colour(self, index: int) -> str:
        return PERK_COLORS.get(self.game.content.perks[self.choices[index]].color, "#e8e8f4")

    def _card(self, index: int) -> Text:
        perk = self.game.content.perks[self.choices[index]]
        text = Text(f"{index + 1}  ", style="bold #ffb000")
        text.append(perk.name.upper(), style=f"bold {self._colour(index)}")
        text.append(f"\n{perk.desc}\n\n", style=WORDS)
        text.append_text(perk_changes(self.game, self.previews[index]))
        return text

    def _button(self) -> Text:
        if self.looking is None:
            return Text(" ▶ pick a perk first ", style=DIM)
        name = self.game.content.perks[self.choices[self.looking]].name
        return Text(f" ▶ Take {name}  [enter] ", style="bold #ffb000")

    def action_look(self, index: int) -> None:
        """A card looked at: lit, with what it would change lit on the sheet. The one looked at already is taken."""
        if self.app.screen is not self or not 0 <= index < len(self.choices):
            return
        if index == self.looking:
            self.action_take()
            return
        sound.play("dice_tick")
        self.looking = index
        for card in self.query(PerkCard):
            card.set_class(card.index == index, "-looking")
            card.styles.border = ("heavy" if card.index == index else "round", self._colour(card.index))
            if card.index == index:
                card.scroll_visible()  # (on a small screen, the cards are one under another)
        self.query_one(Sheet).show(self.previews[index], self.choices[index])
        self.query_one("#levelup-button", Clickable).update(self._button())
        self.query_one("#levelup-hint", Static).update("")

    def action_step(self, step: int) -> None:
        """← →: the card beside the one looked at."""
        count = len(self.choices)
        self.action_look((0 if step > 0 else count - 1) if self.looking is None else (self.looking + step) % count)

    def action_take(self) -> None:
        if self.app.screen is not self:
            return
        if self.looking is None:
            self.action_close()
            return
        sound.play("select")
        self.dismiss(self.choices[self.looking])

    def action_close(self) -> None:
        """Esc, or a click outside: a level-up can't wait, so it only says so."""
        if self.app.screen is self:
            self.query_one("#levelup-hint", Static).update(
                Text("  Choose one to go on: a level-up can't wait.", style="bold #ff4f9a"))

    def action_lookup(self, term_id: str) -> None:
        """A thing named on the sheet clicked: its card over this one, to look at only (see Panel.peek)."""
        if self.app.screen is self:
            card = InfoScreen(self.game, term_id)
            card.peek = True
            self.app.push_screen(card)

    def action_switch(self, name: str) -> None:
        if self.app.screen is self:
            self.open_panel(name)

    def can_open_panel(self, name: str) -> bool:
        return True

    def open_panel(self, name: str) -> None:
        """A look at another panel, over this one (see Panel.peek): it's the game's, from the screen under this."""
        stack = self.app.screen_stack
        maker = getattr(stack[stack.index(self) - 1], "panel", None)
        if maker is not None:
            panel = maker(name)
            panel.peek = True
            self.app.push_screen(panel)


GAIN_ROWS = ("level", "max hp", "attack", "xp")  # what a level-up's gains show, a row at a time


class PerkCard(Static):
    """One perk to choose, in its colour: its name, what it does, and what it would change on your sheet."""

    def __init__(self, text: Text, index: int, colour: str) -> None:
        super().__init__(text, classes="perk-card")
        self.index = index
        self.styles.border = ("round", colour)

    def on_click(self, event: Click) -> None:
        event.stop()
        self.screen.action_look(self.index)


# --- what a word in the story is --------------------------------------------------------------------------------------

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
    """What a highlighted word (or a picture you clicked) refers to, titled with its name: its picture, animated, what
    it is, and the matching action one key away, with the other things you can do with it beside it (take a sword
    lying here, or equip it), which stay put under the words while they scroll. A card with a picture is a card's
    size; a few words alone (a rule, a thing in the room) are a small box."""

    BINDINGS = [Binding("escape,q", "close", "Close"), Binding("enter", "act", "Do it")]
    size_class = "small"  # (a card, once there's a picture: see _picture)

    def __init__(self, game: Game, term_id: str) -> None:
        super().__init__()
        self.game = game
        self.term_id = term_id
        self.action_id: str | None = None  # what Enter does: the engine's own action for it (see _offer)
        self.action: Action | None = None
        self.more: list[Action] = []  # the other things the engine says you can do with it, a click each
        self.picture: Widget | None = None  # what it is, drawn above the card's words (a Picture, or a model)

    def compose(self) -> ComposeResult:
        kind, _, ref = self.term_id.partition(":")
        body, title = getattr(self, f"_{kind}", self._unknown)(ref)
        with Vertical(classes="panel-box info-box") as box:
            box.border_title = title
            with VerticalScroll(id="info-body"):
                if self.picture is not None:
                    yield self.picture
                yield Static(body, id="info-text")
            if self.action is not None:
                with Horizontal(classes="panel-action"):
                    yield Clickable(Text(f" ▶ {self.action.label}  [enter] ", style="bold #ffb000"),
                                    action="screen.act", classes="card-verb")
                    for i, action in enumerate(self.more):
                        label = f" ▶ {action.label}" + (f"  [{action.hint}]" if action.hint else "") + " "
                        yield Clickable(Text(label, style="#9a9cc0"), action=f"screen.act_more({i})",
                                        classes="card-verb")

    def fit(self) -> None:
        super().fit()
        if self.size_class == "small":  # as tall as its words, but never past the screen: then they scroll
            rows = box_rows(self.app.size.height) - (2 if self.action_id else 0)
            self.query_one("#info-body").styles.max_height = rows

    def _offer(self, ref_id: str) -> None:
        """What Enter does here: the first thing the engine says you can do with this now (interactions.verbs: what a
        tile in Here would offer), not a picker or one of Swoogy's guesses; the rest are buttons beside it (more).
        Taking something that lies here, or giving a character what they're after, needn't be a numbered choice."""
        if self.action is not None:
            return
        found = [action for action in interactions.verbs(self.game.state, self.game.content, ref_id)
                 if action.id and not interactions.is_picker(action.id) and not action.id.startswith("guess:")]
        if found:
            self.action, self.action_id, self.more = found[0], found[0].id, found[1:]

    def _picture(self, key: str, kind: str, **kwargs) -> Picture:
        """The card's picture: full size if the screen has the room for it and a few lines under it (the card
        scrolls for the rest), else small. A card with a picture is a card's size."""
        self.size_class = "card"
        return Picture(key, kind, LOOK_PICTURE, box_rows(self.app.size.height) - CARD_WORDS, content=self.game.content,
                       sprites=self.game.config.art == "sprites", classes="panel-sprite", **kwargs)

    def _model(self, key: str) -> Widget:
        """A thing's model turning, in its picture's place (ui/model_view.py): as tall as its picture would be, and
        no taller than it is wide."""
        from .model_view import SHOWN, ModelView, CALM

        self.size_class = "card"
        model = ModelView(key, spin=SHOWN, fps=CALM, classes="panel-model")
        model.styles.height = max(8, min(22, box_rows(self.app.size.height) - CARD_WORDS))
        return model

    def _monster(self, key: str) -> tuple[Text, str]:
        game = self.game
        content, state = game.content, game.state
        monster = content.monster(key)
        entry = game.profile.bestiary().get(key, {})
        self.picture = self._picture(key, "monster")  # (its ASCII art, with sprites off or no sprite yet)
        text = Text()
        text.append(glossary.monster_summary(state, content, key, entry) + "\n", style="bold #ffb000")
        if monster.desc:
            text.append(monster.desc + "\n", style=WORDS)
        if entry:
            text.append(f"seen {entry['seen']} · slain {entry['killed']} · pacified {entry['pacified']} · "
                        f"killed you {entry['killed_you']}\n", style=SOFT)
        text.append("\n" + (entry.get("lore") or "No notes on this one yet."), style=f"italic {WORDS}")
        here = state.room.monster
        if here and here.key == key:  # a foe: a blow; someone calm: what they're here for, or else ask them things
            self._offer(f"monster:{key}")
        if state.room.shop and state.room.shop.keeper == key:  # the shopkeeper: her wares
            self._offer(f"keeper:{key}")
        return text, monster.name

    def _item(self, key: str) -> tuple[Text, str]:
        game = self.game
        content = game.content
        item = content.item(key)
        if game.config.art == "sprites":  # (its model turning if it has one; else its picture, or its grey stand-in)
            self.picture = self._model(key) if model3d.available(key) else self._picture(key, "item")
        text = Text()
        text.append(item.name + "\n", style="bold #4cff8a")
        tags = f" · {', '.join(item.tags)}" if item.tags else ""
        text.append(glossary.item_stats(item) + tags + "\n", style=SOFT)
        where = whereabouts(game, key)
        if where:
            text.append(" · ".join(where) + "\n", style="#ffb000")
        wanted = npcs.wanted_by(game.state, content, key)  # ("Lucky Lenny wants it back.")
        if wanted:
            text.append(wanted + "\n", style="bold #ffd166")
        text.append(gear_comparison(game, key), style=WORDS)
        text.append("\n")
        text.append_text(power_lines(content, key))  # (its powers, once)
        text.append(item.desc, style=WORDS)
        ideas = [TAG_IDEAS[t] for t in item.tags if t in TAG_IDEAS]
        if ideas:
            text.append("\n\nIdeas: " + "; ".join(ideas[:3]), style="#ff4f9a")
        player = game.state.player
        self._offer(f"floor:{key}" if key in game.state.room.items else "gear:weapon" if key == player.weapon else
                    "gear:armor" if key == player.armor else f"item:{key}")
        return text, item.name

    def _feature(self, ref: str) -> tuple[Text, str]:
        state, content = self.game.state, self.game.content
        feature = state.room.features[int(ref)]
        tags = content.feature_tags(feature.name)
        text = Text(f"{feature.name} ({layout.where(feature.pos)})\n", style="bold #ffb000")
        text.append(("Searched." if feature.searched else "Not searched yet.") + "\n", style=SOFT)
        if feature.used:
            text.append(f"Already used to {feature.used}.\n", style=SOFT)
        if tags:
            text.append("Properties: " + ", ".join(tags) + "\n", style="#5fe3ff")
            ideas = [TAG_IDEAS[t] for t in tags if t in TAG_IDEAS]
            if ideas:
                text.append("Ideas: " + "; ".join(ideas[:3]), style="#ff4f9a")
        else:
            text.append("Nothing special about it, as far as you can tell.", style=DIM)
        self._offer(f"feature:{ref}")
        return text, cap(feature.name)

    def _fixture(self, ref: str) -> tuple[Text, str]:
        room = self.game.state.room
        if self.game.config.art == "sprites" and frame_count(ref):
            spent = room.fixture == ref and room.fixture_used and ref in SPENT  # (an emptied chest, a snuffed shrine)
            self.picture = self._picture(ref, "", loop=[frame_count(ref) - 1] if spent else None)
        text = Text()
        text.append(ref.title() + "\n\n", style="bold #ff4f9a")
        text.append(glossary.FIXTURES[ref], style=WORDS)
        self._offer(f"fixture:{ref}")
        return text, ref.title()

    def _room(self, ref: str) -> tuple[Text, str]:
        state, content = self.game.state, self.game.content
        room = state.rooms[int(ref)]
        text = Text()
        width = min(LOOK_PICTURE, self.app.size.width - 8)
        if self.game.config.art == "sprites" and room.visited and width >= 36:  # only somewhere you've been
            art = picture_text(state, content, width, 2 * max(10, min(18, self.app.size.height - 26)), room)
            if art is not None:
                self.size_class = "card"  # (a picture: a card's size)
                text.append_text(art)
                text.append("\n\n")
        text.append(room.name + "\n\n", style="bold #8fa8ff")
        text.append_text(room_now(state, content, room))
        return text, room.name

    def _rule(self, ref: str) -> tuple[Text, str]:
        name, summary = glossary.RULES[ref]
        return Text(name + "\n\n", style="bold #5fe3ff") + Text(summary, style=WORDS), name

    def _unknown(self, ref: str) -> tuple[Text, str]:
        return Text("Nothing more is known about that."), "?"

    def action_act(self) -> None:
        if self.peek:
            self.notify("Choose your perk first: then it's yours to use.", timeout=3)
        elif self.app.screen is self:
            sound.play("select")
            self.dismiss(self.action)

    def action_act_more(self, index: int) -> None:
        """One of the buttons beside the main one (equip the sword you'd take)."""
        if self.peek:
            self.notify("Choose your perk first: then it's yours to use.", timeout=3)
        elif self.app.screen is self and 0 <= index < len(self.more):
            sound.play("select")
            self.dismiss(self.more[index])


class PickScreen(Panel):
    """What to give, or use on: a picker's choices (interactions.choices), the ones that would work first, to pick by
    number or a click. One that won't work is shown dimly, and can't be picked. Esc, the ✕ or a click outside it
    picks nothing."""

    BINDINGS = [Binding(str(n), f"pick({n - 1})", show=False) for n in range(1, 10)]
    size_class = "small"

    def __init__(self, title: str, options: list[Action]) -> None:
        super().__init__()
        self.words, self.options = title, options

    def compose(self) -> ComposeResult:
        with Vertical(classes="panel-box pick-box") as box:
            box.border_title = self.words
            if not self.options:
                yield Static(Text("Nothing to pick.", style=DIM))
            for i, action in enumerate(self.options):
                works = action.hint != interactions.NO
                row = Text(f"{i + 1}  ", style="bold #ffb000" if works else DIM)
                row.append(action.label, style=WORDS if works else DIM)
                if action.hint:
                    row.append(f"  [{action.hint}]", style=SOFT if works else DIM)
                yield Clickable(row, f"screen.pick({i})", classes="pick-row")

    def action_pick(self, index: int) -> None:
        if index < len(self.options) and self.options[index].hint != interactions.NO and self.app.screen is self:
            sound.play("select")
            self.dismiss(self.options[index])


class MenuScreen(Panel):
    """A short screen's ☰: the panels the footer's F-keys open, as buttons (three rows tall for a finger), and
    sound on or off, as F8 has it."""

    size_class = "small"
    opening_sound = None
    PANELS = (("Bag", "inventory"), ("Character", "character"), ("Look around", "look"), ("Map", "map"),
              ("Quests", "journal"), ("Bestiary", "bestiary"), ("Help", "help"))

    def compose(self) -> ComposeResult:
        with Vertical(classes="panel-box menu-box") as box:
            box.border_title = "Menu"
            for label, name in (*self.PANELS, (f"Sound: {'on' if self.app.config.sound else 'off'}", "sound")):
                yield Clickable(Text(f" {label} ", style="bold #0b0b14 on #6c8cff" if config.touch() else "#c8c8e0"),
                                f"screen.choose('{name}')", classes="menu-row")

    def action_choose(self, name: str) -> None:
        if self.app.screen is self:
            self.dismiss(name)
