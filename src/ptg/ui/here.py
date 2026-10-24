"""Here: who and what is in the room, as tiles with a button for each thing you can do with them.

Each thing is a `Thing` (things_here makes them from the room's RoomView; the buttons are the engine's own actions,
interactions.verbs), drawn as a card (a 24-pixel picture, its name, how it is, its buttons), a mini card or a row (the
12-pixel picture, over or beside the words), or a chip (words only). `arrange` picks the forms for the space there is:
the characters in the biggest form that fits them all, then the things in the biggest form that still fits, and when
even chips overflow, as many lines as fit and a count of the rest. `Tile` draws one, with a Picture for its art, so it
is drawn the same way here as everywhere else.

A character's how-it-is is always shown, in every form (a foe's health, and a big blow coming): a tile that can't show
it is a form too small for it.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from .. import inventory, npcs
from ..content import Content
from ..events import Action
from ..models import GameState
from ..scene import RoomView
from ..sprites import DEFAULT_WIDTH, SMALL
from .widgets import Clickable, Picture, art_for, bar, monster_pose

ARRIVAL_LOOPS = {"chest": [0, 0, 0, 1]}  # a fixture's idle animation: the frames it shows in turn (the chest glints)

CARD, MINI, ROW, CHIP = "card", "mini", "row", "chip"
ART = {CARD: DEFAULT_WIDTH, MINI: SMALL, ROW: SMALL}  # the pixels wide of the picture in each form
CARD_WIDTH, MINI_WIDTH = 26, 17  # the least columns a card or mini card is drawn in
# What a button does, by its colour: foes red, kind words green, taking amber, the rest blue.
VERB_STYLES = {"Attack": "#ff4b4b", "Talk": "#4cff8a", "Give": "#4cff8a", "Play": "#4cff8a", "Take": "#ffb000",
               "Equip": "#ffb000", "Buy": "#ffb000"}
PLAIN_VERB = "#6c8cff"
DIE = {f"guess:{n}": face for n, face in enumerate("⚀⚁⚂⚃⚄⚅", 1)}  # Swoogy's guesses are the faces of his die
DEAD_VERB = "#6c6f99"  # a button that can't be pressed ("need 12¤")
FRIEND, FOE, COIN, DIM = "#4cff8a", "#ff4b4b", "#ffb000", "#9a9cc0"


@dataclass
class Thing:
    """Something Here shows: a character or a thing, how it is, and what you can do with it."""

    id: str  # its ref's (monster:goblin, floor:war_pick, ware:2, fixture:chest)
    sprite: str  # what its Picture draws
    kind: str  # the Picture's kind: "monster", "item", or "" for a fixture
    name: str
    status: str
    style: str  # the status' colour
    verbs: list[Action] = field(default_factory=list)  # (an id of "" is a button that can't be pressed)
    character: bool = False
    pose: str = "idle"
    badge: str = ""  # ★ for someone with a job for you
    compact: str = ""  # the status in a few characters, for a chip
    loop: list[int] | None = None
    art: bool = True  # whether it has a picture at all (a feature to search hasn't)

    @property
    def title(self) -> str:
        return f"{self.badge} {self.name}".strip()


def item_short(content: Content, key: str) -> str:
    """What an item is, in a few words."""
    item = content.item(key)
    if item.heal:
        return f"heals {item.heal}"
    return {"trinket": "a trinket", "consumable": "use it once", "key": "a key"}.get(item.kind, item.kind)


def compare(state: GameState, content: Content, key: str) -> tuple[str, str]:
    """A weapon or armor against the one you have on: better, like it or worse (or you've none)."""
    item = content.item(key)
    now = inventory.worn(state, item.kind)
    if not now:
        return "▲ you have none", FRIEND
    mine = content.item(now)
    if now == key:
        return f"the same as your {mine.name}", DIM
    ours, theirs = inventory.rating(state, content, key), inventory.rating(state, content, now)
    if ours > theirs:
        return f"▲ better than your {mine.name}", FRIEND
    if ours == theirs:
        return f"= like your {mine.name}", DIM
    return f"▼ worse than your {mine.name}", DEAD_VERB


def foe_status(monster, width: int = 8) -> tuple[str, str]:
    """A foe's how-it-is, in full and in a few characters: a big blow coming (or stunned, or guarding), then its health."""
    hp = f"{max(0, monster.hp)}/{monster.max_hp}"
    warning = "⚠ big hit next! " if monster.intent == "heavy" else "★ stunned " if monster.stunned else \
        "⛨ guarding " if monster.guarding else ""
    short = "⚠" if monster.intent == "heavy" else "★" if monster.stunned else "⛨" if monster.guarding else ""
    left = min(max(0, monster.hp), monster.max_hp)
    return f"{warning}{bar(left, monster.max_hp, width)} {hp}", f"{bar(left, monster.max_hp, 4)} {hp} {short}".strip()


def things_here(state: GameState, content: Content) -> list[Thing]:
    """What's in the room, as tiles, in the order they're shown (and numbered): whoever's here first (a foe first of
    all), then a shop's keeper and her wares, what's lying here, then the fixture, the features to search and a wall
    a draft came through."""
    from ..interactions import verbs

    view = RoomView(state, content)
    player, found = state.player, []
    for ref in view.things():
        buttons = verbs(state, content, ref.id) if ref.kind != "exit" else []
        if ref.kind == "monster":
            monster = state.room.monster
            if monster.hostile:
                status, short = foe_status(monster)
                found.append(Thing(ref.id, monster.key, "monster", monster.name, status, FOE, buttons, True,
                                   monster_pose(monster), compact=short))
            else:
                mood = npcs.status(state, content, monster.key) or "calm"
                found.append(Thing(ref.id, monster.key, "monster", monster.name, mood, FRIEND, buttons, True,
                                   badge="★" if npcs.waiting(state, monster) else "", compact=mood))
        elif ref.kind == "keeper":
            greeting = npcs.line(state, content, ref.key, "greet") or npcs.status(state, content, ref.key)
            first = re.match(r".+?[.!?](?=\s|$)|.+", greeting)  # (her first sentence: a tile's room is short)
            greeting = first.group(0) if first else greeting
            found.append(Thing(ref.id, ref.key, "monster", ref.name, greeting, FRIEND, buttons, True, compact="shopkeeper"))
        elif ref.kind == "ware":
            item, price = content.item(ref.state["item"]), ref.state["price"]
            if ref.state["afford"]:
                status, style = f"{price}¤ · {item_short(content, item.key)}", COIN
            else:
                status, style = f"need {price}¤", DEAD_VERB
                buttons = [Action("", f"need {price}¤")]
            found.append(Thing(ref.id, item.key, "item", item.name, status, style, buttons, compact=f"{price}¤"))
        elif ref.kind == "floor":
            item = content.item(ref.key)
            status, style = (compare(state, content, ref.key) if item.kind in inventory.GEAR
                             else (item_short(content, ref.key), DIM))
            if ref.state["cursed"]:
                status, style = "cursed! sticks to you", FOE
            if ref.count > 1:
                status = f"×{ref.count} · {status}"
            found.append(Thing(ref.id, ref.key, "item", item.name, status, style, buttons,
                               compact=status.split(" than")[0]))
        elif ref.kind == "fixture":
            used = ref.state["used"]
            found.append(Thing(ref.id, ref.key, "", ref.name, "spent" if used else "", DEAD_VERB if used else DIM,
                               buttons, loop=None if used else ARRIVAL_LOOPS.get(ref.key)))
        elif ref.kind == "feature" and not ref.state["searched"] and buttons:
            found.append(Thing(ref.id, "", "", ref.name, "", DIM, buttons, art=False))
        elif ref.kind == "wall" and ref.state["draft"] and buttons:
            found.append(Thing(ref.id, "", "", ref.name, "a draft comes through", DIM, buttons, art=False))
    return found


# --- the forms ------------------------------------------------------------------------------------------------------

def button_width(action: Action, touch: bool = False) -> int:
    """The columns a button takes: " 1 Take " and a space after it; with touch, a framed block at least 8 wide with 2
    between."""
    n = len(f"{9} {action.label}")  # (every live one gets a number: at most two digits)
    return max(n + 2, 8) + 2 if touch else n + 3


def verbs_width(thing: Thing, touch: bool = False) -> int:
    """The columns all its buttons take on a line."""
    return sum(button_width(a, touch) for a in thing.verbs)


def verb_lines(thing: Thing, width: int, touch: bool = False) -> list[list[Action]]:
    """Its buttons packed into lines `width` columns wide: one is never split, and the rest wrap."""
    out, line, used = [], [], 0
    for action in thing.verbs:
        w = button_width(action, touch)
        if line and used + w > width:
            out.append(line)
            line, used = [], 0
        line.append(action)
        used += w
    return out + ([line] if line else [])


def lines(text: str, width: int, most: int) -> int:
    return max(1, min(most, len(textwrap.wrap(text, max(4, width)) or [""])))


def art_rows(thing: Thing, form: str, content: Content | None = None) -> int:
    """How tall its picture is in a form, in rows."""
    return art_for(thing.sprite, thing.kind, content, ART[form]).rows if thing.art and thing.sprite else 0


def measure(thing: Thing, form: str, width: int, touch: bool, content: Content | None = None,
            packed: bool = False) -> tuple[int, int]:
    """A tile's (columns, rows) in a box `width` columns wide: its picture, its name (up to two lines), how it is (up
    to three for a character) and its buttons (wrapping onto a second line rather than being cut)."""
    verb_row, verbs = (3 if touch else 1), verbs_width(thing, touch)
    widest = max((button_width(a, touch) for a in thing.verbs), default=0)
    if form in (CARD, MINI):
        w = max(CARD_WIDTH if form == CARD else MINI_WIDTH, widest + 2)
        if w > width:
            return w, 999
        inner = w - 2
        rows = art_rows(thing, form, content) + lines(thing.title, inner, 2) + \
            lines(thing.status, inner, 3 if thing.character else 1)
        return w, rows + verb_row * len(verb_lines(thing, inner, touch)) + 1
    if form == ROW:
        words = width - SMALL - 1
        text = lines(thing.title, words, 2) + lines(thing.status, words, 3 if thing.character else 1)
        return width, max(art_rows(thing, form, content), text) + verb_row * len(verb_lines(thing, width, touch)) + 1
    name = len(thing.title) + 1 + (len(thing.compact) + 1 if thing.character else 0)
    if packed and name + verbs <= width:  # chips side by side, in the phone's strip
        return name + verbs, verb_row
    return (width, verb_row) if name + verbs <= width else (min(width, max(name, verbs)), 1 + verb_row)


def arrange(things: list[Thing], width: int, rows: int, touch: bool, forms: tuple[str, ...],
            content: Content | None = None, packed: bool = False):
    """Lines of (thing, form, size) filling `rows`: the characters in the biggest form that fits them all with
    everything else at least a chip, then the things in the biggest form that still fits. A thing with no picture is
    a chip. If even chips overflow, as many lines as fit. Returns (lines, how many things didn't fit)."""
    people = [t for t in things if t.character]
    stuff = [t for t in things if not t.character]

    def laid(group: list[Thing], form: str):
        out, line, used = [], [], 0
        for thing in group:
            use = form if thing.art else CHIP
            w, h = measure(thing, use, width, touch, content, packed)
            if line and used + w > width:
                out.append(line)
                line, used = [], 0
            line.append((thing, use, (w, h)))
            used += w + (1 if packed else 0)
        return out + ([line] if line else [])

    def height(layout) -> int:
        return sum(max(h for _, _, (_, h) in line) for line in layout)

    choose = [f for f in forms if f != CHIP] + [CHIP]
    who = next((f for f in choose if height(laid(people, f)) + height(laid(stuff, CHIP)) <= rows), CHIP)
    what = next((f for f in choose if height(laid(people, who)) + height(laid(stuff, f)) <= rows), CHIP)
    layout = laid(people, who) + laid(stuff, what)
    if height(layout) <= rows:
        return layout, 0
    shown, used = [], 0
    for line in layout:
        h = max(h for _, _, (_, h) in line)
        if used + h > rows:
            break
        shown.append(line)
        used += h
    return shown, len(things) - sum(len(line) for line in shown)


# --- a tile ---------------------------------------------------------------------------------------------------------

class Tile(Vertical):
    """One thing in Here, in one of the forms (see measure). Its buttons are numbered as typed (`numbers`: action id to
    number), and run their action by `screen.verb(id)`."""

    def __init__(self, thing: Thing, form: str, size: tuple[int, int], numbers: dict[str, int], content: Content,
                 touch: bool = False, animate: bool = True) -> None:
        super().__init__(classes=f"here-tile here-{form}" + (" character" if thing.character else ""))
        self.thing, self.form, self.tile_size, self.numbers = thing, form, size, numbers
        self.content, self.touch, self.animate = content, touch, animate
        self.styles.width, self.styles.height = size
        self.can_focus = False

    def compose(self) -> ComposeResult:
        thing = self.thing
        name = Text(thing.badge + " " if thing.badge else "", style="bold #ffd166")
        name.append(thing.name, style="bold #ff4f9a" if thing.character else "bold")
        if self.form == CHIP:
            if thing.character and thing.compact:
                name.append(f" {thing.compact}", style=thing.style)
            stacked = self.tile_size[1] > (3 if self.touch else 1)  # (too long for a line)
            with (Vertical if stacked else Horizontal)(classes="here-body"):
                yield Static(name, classes="here-name")
                yield self.buttons()
            return
        words = [Static(name, classes="here-name"), Static(Text(thing.status, style=thing.style), classes="here-status")]
        if self.form == ROW:
            with Horizontal(classes="here-body"):
                yield self.picture()
                with Vertical(classes="here-words"):
                    yield from words
        else:
            yield self.picture()
            yield from words
        yield self.buttons()

    def picture(self) -> Picture:
        thing = self.thing
        pose = "idle" if self.form != CARD and thing.pose == "windup" else thing.pose  # (a glow swamps a small picture)
        return Picture(thing.sprite, thing.kind, ART[self.form], pose=pose, animate=self.animate and thing.character,
                       action=f"screen.lookup('{self.lookup_id()}')", content=self.content, loop=thing.loop,
                       classes="here-art")

    def lookup_id(self) -> str:
        """The glossary term a click on its picture opens: its card."""
        kind, _, key = self.thing.id.partition(":")
        return {"floor": f"item:{key}", "ware": f"item:{self.thing.sprite}", "keeper": f"monster:{key}"}.get(
            kind, self.thing.id)

    def buttons(self) -> Vertical:
        """Its buttons, in the lines they wrap into (see verb_lines)."""
        width = self.tile_size[0] - (0 if self.form == CHIP else 2)
        rows = []
        for line in verb_lines(self.thing, width, self.touch) or [[]]:
            rows.append(Horizontal(*[self.button(action) for action in line], classes="here-verbs"))
        return Vertical(*rows, classes="here-verb-rows")

    def button(self, action: Action) -> Clickable:
        number = self.numbers.get(action.id)
        face = DIE.get(action.id)
        label = f"{number} {face or action.label}" if number else face or action.label
        word = action.label.removesuffix("…").split(" ")[0]
        live = bool(action.id)
        colour = VERB_STYLES.get(word, PLAIN_VERB) if live else DEAD_VERB
        click = f"screen.verb('{action.id}')"
        if self.touch:  # a solid block three rows tall, easy to hit with a thumb
            button = Clickable(Text(label, style="bold #0b0b14" if live else DEAD_VERB), click, classes="verb")
            if live:
                button.styles.background = colour
        else:
            button = Clickable(Text(f" {label} ", style=f"reverse {colour}" if live else DEAD_VERB), click,
                               classes="verb")
        if action.hint:
            button.tooltip = action.hint
        return button
