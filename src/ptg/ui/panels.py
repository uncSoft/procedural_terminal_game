"""Pop-up panels: help, inventory, character, look, map, bestiary, journal, the shop, a new floor's card, the level-up,
and the card of whatever a word in the story is.

Every panel is one box of a size class (see Panel), sized as it opens: what you pick or click in it changes what's
inside, never the box. Each closes on Esc, on the ✕ in its top border, or on a click outside it, and F1-F7 switch to
that panel instead.
"""

from __future__ import annotations

from rich.console import Group
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

from .. import glossary, layout, npcs, sound
from ..content import Content, Theme
from ..game import Game
from ..meta import epithet
from ..models import GameState, Room
from ..room_picture import picture_text
from ..events import Action
from ..rules import TRAITS
from ..text import cap, the
from ..sprites import DEFAULT_WIDTH, SMALL, SPENT, frame_count
from .theme import PERK_COLORS
from .widgets import TALL, Clickable, Picture, item_note, item_words, map_text, power_lines, room_text

PANEL_KEYS = {"f1": "help", "f2": "inventory", "f3": "character", "f4": "look", "f5": "map", "f6": "bestiary",
              "f7": "journal"}  # the panels' keys, on the game screen and in every panel
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
    Esc, q, the ✕ or a click outside it close it."""

    BINDINGS = [Binding("escape,q", "close", "Close"),
                *[Binding(key, f"switch('{name}')", show=False) for key, name in PANEL_KEYS.items()]]
    size_class = "card"
    panel_name = ""  # which of PANEL_KEYS' panels it is, if it's one of them
    opening_sound: str | None = "open"
    peek = False  # opened over a choice still to be made (a level-up): it only shows, and what you'd do waits

    @property
    def box(self) -> Widget:
        """The panel's one box (.panel-box)."""
        return self.query(".panel-box").first()

    def on_mount(self) -> None:
        if self.opening_sound:
            sound.play(self.opening_sound)
        self.box.add_class(self.size_class)
        self.fit()
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
    ("↓", "FLOORS", "Three floors, each a different dungeon. Find the stairs, then the key, then the boss."),
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
                Binding("enter", "use", "Use", priority=True)]
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
        content, player = self.game.content, self.game.state.player
        usable = {}  # an item's action right now: drink or eat it, throw it, distract with it, light the room
        for action in self.game.actions:
            verb, _, key = action.id.partition(":")
            if verb in USES and key not in usable:
                usable[key] = action
        items = [(player.weapon, f"in hand · {content.item(player.weapon).damage}", None, True)]
        if player.armor:
            items.append((player.armor, f"worn · +{content.item(player.armor).defense} defense", None, True))
        counts: dict[str, int] = {}
        for key in player.inventory:
            counts[key] = counts.get(key, 0) + 1
        for key, count in counts.items():
            note = (f"×{count} · " if count > 1 else "") + item_note(content, key)
            items.append((key, note, usable.get(key), False))
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
                with VerticalScroll(id="inv-words"):
                    yield Static("", id="inv-detail")
                yield Clickable("", "screen.use", id="inv-use")
                hint = Text("arrows pick · enter uses · esc closes", style=DIM)
                if height >= TALL:
                    hint.append("\n\nTo use something creatively, close this and type what you do with it.")
                yield Static(hint, id="inv-hint")

    def on_mount(self) -> None:
        self.query(ItemTile).first().focus()

    def show_detail(self, index: int) -> None:
        self.current = index
        content, player = self.game.content, self.game.state.player
        key, _, action, equipped = self.items[index]
        item = content.item(key)
        art = self.query_one("#inv-art", Picture)
        art.become(key)
        blank = art.blank and art.display  # nobody has drawn it yet: it's its kind's grey stand-in
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
        if action:
            use = Text(f"▶ {action.label}  (enter)", style="bold #4cff8a")
        else:
            idle = {"key": "It must open something important.", "trinket": "No use on its own: try it creatively.",
                    "consumable": "Throw it in a fight to get away." if item.escape else
                    "You're at full health." if player.hp >= player.max_hp else "Not now."}
            use = Text(idle.get(item.kind, ""), style=DIM)
        self.query_one("#inv-use", Clickable).update(use)

    def action_move(self, step: int) -> None:
        tiles = list(self.query(ItemTile))
        tiles[max(0, min(len(tiles) - 1, self.current + step))].focus()

    def action_move_rows(self, rows: int) -> None:
        self.action_move(rows * self.columns)

    def action_use(self) -> None:
        _, _, action, _ = self.items[self.current]
        if self.peek:
            self.notify("Choose your perk first: then it's yours to use.", timeout=3)
        elif action:
            self.dismiss(action.id)
        else:
            self.notify("Not usable on its own. Try typing what you want to do with it.", timeout=3)


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
                Binding("b", "barter", "Barter")]
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
                yield Static(Text("arrows pick · enter buys · b haggles · esc leaves", style=DIM), id="shop-hint")

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
        text.append(f"\n¤ {ware.price} gold", style="bold #ffd166")
        text.append({"down": "  talked down", "up": "  dearer since you haggled"}.get(ware.haggled, ""), style=SOFT)
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

    def action_barter(self) -> None:
        item, ware = self._ware()
        if item is None:
            return
        if ware.haggled:
            self.notify("She won't haggle over that again.", timeout=3)
            return
        self.dismiss(Action(f"barter:{self.current}", f"Haggle over {the(item.name)}"))


def price_note(ware) -> str:
    """A ware's price on its tile: talked down (↓), or dearer since you haggled (↑)."""
    return f"¤ {ware.price}" + {"down": " ↓", "up": " ↑"}.get(ware.haggled, "")


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

class CharacterScreen(Panel):
    panel_name = "character"

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
            text.append(f"  {perk.desc}\n", style=WORDS)
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
        text.append(f"\nSouls this descent: {state.souls}", style="#5fe3ff")
        with VerticalScroll(classes="panel-box") as box:
            box.border_title = "Character"
            yield Static(text)


def exits_text(state: GameState, room: Room) -> Text:
    """A room's ways out as they are now: where each leads, if you've been, else what you can see through it (a
    fixture, a shop's locked door), else unexplored."""
    exits = []
    for direction, exit_ in room.exits.items():
        dest = state.rooms[exit_.to]
        seen = dest.fixture if dest.fixture and not dest.fixture_used else "unexplored"
        note = ("locked; a shop beyond" if dest.shop else "locked") if exit_.locked else (
            dest.name if dest.visited else seen)
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


class JournalScreen(Panel):
    panel_name = "journal"

    def __init__(self, game: Game) -> None:
        super().__init__()
        self.game = game

    def compose(self) -> ComposeResult:
        state = self.game.state
        text = Text()
        for line in state.journal[-80:]:
            text.append("· " + line + "\n", style=WORDS)
        with VerticalScroll(classes="panel-box") as box:
            box.border_title = f"Journal · turn {state.turn}"
            yield Static(text or Text("Nothing written yet.", style=DIM))

    def on_mount(self) -> None:
        self.query_one(VerticalScroll).scroll_end(animate=False)


# --- moments: a new floor, a level-up ---------------------------------------------------------------------------------

class FloorScreen(Panel):
    """Arriving on a new floor: its name and what it's like, until you're ready to go on."""

    BINDINGS = [Binding("escape,enter,space,q", "close", "Continue")]
    size_class = "small"
    opening_sound = None  # the stairs already played their part

    def __init__(self, floor: int, total: int, theme: Theme, final: bool) -> None:
        super().__init__()
        self.floor, self.total, self.theme, self.final = floor, total, theme, final

    def compose(self) -> ComposeResult:
        with Vertical(classes="panel-box floor-box") as box:
            box.border_title = f"Floor {self.floor} of {self.total}"
            yield Static(Text("  ".join(" ".join(word) for word in self.theme.name.upper().split()),
                              style="bold #ff4f9a"), classes="floor-name")
            yield Static(Text(self.theme.blurb, style=f"italic {WORDS}"))
            if self.final:
                yield Static(Text(f"Your goal: {self.theme.goal}", style="bold #ffd166"))
            yield Clickable(Text(" ▶ [enter] continue ", style="#ffb000"), action="screen.close",
                            classes="panel-action")

    def on_click(self, event: Click) -> None:
        event.prevent_default()  # instead of Panel's: anywhere closes it, it's a title card
        self.action_close()


class LevelUpScreen(Panel):
    """Tiny Rogues style: pick one of three perk cards (1-3, or click one). Esc, the ✕ or a click outside puts the
    choice off: the perks wait as the game's choices, and the cards come back after your next move. F1-F7 show that
    panel over this one, for a look before you choose."""

    BINDINGS = [Binding("1", "pick(0)", "First"), Binding("2", "pick(1)", "Second"), Binding("3", "pick(2)", "Third")]
    size_class = "small"
    opening_sound = None  # (a level-up has its own)

    def __init__(self, content: Content, choices: list[str], level: int) -> None:
        super().__init__()
        self.content = content
        self.choices = choices
        self.level = level

    def compose(self) -> ComposeResult:
        with Vertical(classes="panel-box levelup-box") as box:
            box.border_title = f"LEVEL UP · level {self.level}"
            yield Static(Text("CHOOSE ONE  ", style="bold #e8e8f4") + Text("(press 1-3, or click a card)", style=DIM))
            for i, key in enumerate(self.choices):
                perk = self.content.perks[key]
                color = PERK_COLORS.get(perk.color, "#e8e8f4")
                text = Text(f"{i + 1}  ", style="bold #ffb000")
                text.append(perk.name + "\n", style=f"bold {color}")
                text.append(f"   {perk.desc}", style=WORDS)
                card = PerkCard(text, i)
                card.styles.border = ("heavy", color)
                yield card

    def action_pick(self, index: int) -> None:
        if index < len(self.choices) and self.app.screen is self:
            sound.play("select")
            self.dismiss(self.choices[index])

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


class PerkCard(Static):
    def __init__(self, text: Text, index: int) -> None:
        super().__init__(text, classes="perk-card")
        self.index = index

    def on_click(self) -> None:
        self.screen.action_pick(self.index)


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
    it is, and the matching action one key away, which stays put under the words while they scroll. A card with a
    picture is a card's size; a few words alone (a rule, a thing in the room) are a small box."""

    BINDINGS = [Binding("escape,q", "close", "Close"), Binding("enter", "act", "Do it")]
    size_class = "small"  # (a card, once there's a picture: see _picture)

    def __init__(self, game: Game, term_id: str) -> None:
        super().__init__()
        self.game = game
        self.term_id = term_id
        self.action_id: str | None = None
        self.picture: Picture | None = None  # what it is, drawn above the card's words

    def compose(self) -> ComposeResult:
        kind, _, ref = self.term_id.partition(":")
        body, title = getattr(self, f"_{kind}", self._unknown)(ref)
        with Vertical(classes="panel-box info-box") as box:
            box.border_title = title
            with VerticalScroll(id="info-body"):
                if self.picture is not None:
                    yield self.picture
                yield Static(body, id="info-text")
            if self.action_id:
                label = next(a.label for a in self.game.choices() if a.id == self.action_id)
                yield Clickable(Text(f" ▶ {label}  [enter] ", style="bold #ffb000"), action="screen.act",
                                classes="panel-action")

    def fit(self) -> None:
        super().fit()
        if self.size_class == "small":  # as tall as its words, but never past the screen: then they scroll
            rows = box_rows(self.app.size.height) - (2 if self.action_id else 0)
            self.query_one("#info-body").styles.max_height = rows

    def _available(self, action_id: str) -> None:
        if any(a.id == action_id for a in self.game.choices()):
            self.action_id = action_id

    def _picture(self, key: str, kind: str, **kwargs) -> Picture:
        """The card's picture: full size if the screen has the room for it and a few lines under it (the card
        scrolls for the rest), else small. A card with a picture is a card's size."""
        self.size_class = "card"
        return Picture(key, kind, LOOK_PICTURE, box_rows(self.app.size.height) - CARD_WORDS, content=self.game.content,
                       sprites=self.game.config.art == "sprites", classes="panel-sprite", **kwargs)

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
        if here and here.key == key and here.hostile:
            self._available("attack")
        elif here and here.key == key:  # someone calm: what they're here for, or else ask them things (not a blow)
            own = npcs.actions(state, content)
            self._available(own[0].id if len(own) == 1 else "ask")
        if state.room.shop and state.room.shop.keeper == key:  # the shopkeeper: her wares
            self._available("shop")
        return text, monster.name

    def _item(self, key: str) -> tuple[Text, str]:
        game = self.game
        content = game.content
        item = content.item(key)
        if game.config.art == "sprites":  # (its grey stand-in if nobody's drawn it yet)
            self.picture = self._picture(key, "item")
        text = Text()
        text.append(item.name + "\n", style="bold #4cff8a")
        tags = f" · {', '.join(item.tags)}" if item.tags else ""
        text.append(glossary.item_stats(item) + tags + "\n", style=SOFT)
        where = whereabouts(game, key)
        if where:
            text.append(" · ".join(where) + "\n", style="#ffb000")
        text.append(gear_comparison(game, key), style=WORDS)
        text.append("\n")
        text.append_text(power_lines(content, key))  # (its powers, once)
        text.append(item.desc, style=WORDS)
        ideas = [TAG_IDEAS[t] for t in item.tags if t in TAG_IDEAS]
        if ideas:
            text.append("\n\nIdeas: " + "; ".join(ideas[:3]), style="#ff4f9a")
        for verb in (*USES, "take"):
            if not self.action_id:
                self._available(f"{verb}:{key}")
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
        self._available(f"search:{ref}")
        return text, cap(feature.name)

    def _fixture(self, ref: str) -> tuple[Text, str]:
        room = self.game.state.room
        if self.game.config.art == "sprites" and frame_count(ref):
            spent = room.fixture == ref and room.fixture_used and ref in SPENT  # (an emptied chest, a snuffed shrine)
            self.picture = self._picture(ref, "", loop=[frame_count(ref) - 1] if spent else None)
        text = Text()
        text.append(ref.title() + "\n\n", style="bold #ff4f9a")
        text.append(glossary.FIXTURES[ref], style=WORDS)
        for action in {"stairs": ["descend"], "shrine": ["shrine_blood", "shrine_gold"],
                       "chest": ["chest_key", "chest", "chest_smash"], "fountain": ["fountain"],
                       "shop": ["shop"]}.get(ref, []):
            if not self.action_id:
                self._available(action)
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
        if self.app.screen is self:
            sound.play("select")
            self.dismiss(self.action_id)
