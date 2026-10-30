"""The game screen as a fixed grid, like an old CRPG's: every box sized from the screen alone, never from what's in
it, and lined up with the box beside it, so nothing moves as choices come and go. Only what's inside a box changes.

On a wide screen (BESIDE columns left of the right column):

    across the top    the room's picture, and the map beside it, as tall
    under them        the story (a column easy to read, newest last, the command line at its foot); beside it, at eye
                      height, the decision; and Here, under the map
    at the foot       of the right column, a button for each panel (Pack, Sheet, Map, Journal, Bestiary, Help)

On a narrower one the decision is under the story, its buttons in a row and the compass beside them.

The decision's six big buttons stay in their places, a fight's or the room's, in the same colours where they can:

    in a fight    1 Attack · 2 Dodge · 3 Heal · 4 Throw · 5 Use · 6 Flee
    out of one    1 Search · 2 Rest · 3 Heal · 4 Bomb · 5 Use · 6 Gear

Each in one look at a time, the whole button: as it is, hovered (a tint of its own colour), urgent (Dodge as a heavy
blow comes), open (its options showing), or unavailable (faded, its reason under it). One with a single thing to do
it with does it; one with several shows them under the buttons (a, b, c...: a click or a letter), never a window over
the picture; Bomb always shows its walls, even one, as a bomb's too dear to spend unseen.

Under the buttons, out of a fight, the compass: five cells that never move or change size, a way out lit with where it
goes and what's there, a wall faint; the arrow keys move too, unless you're typing. Under that (in a fight, in its
place) your things as cards, a picture each, what it would do and how it would go ("weak!", "won't work"): all that
Heal, Throw, Use and Gear would use, or only the one button's whose options are showing.

Here is in sections, a heading each: who's here, the things (a picture each), what there is to search, and the
journal's last lines (Lately) in the rows left. Their verbs are on them (Take is one click), numbered on after the
buttons. In a fight Here is the foe's card, big, with all you know of it, where its hits and lunges play.

The Map panel (F5, or its button) is the floor on parchment (see parchment.draw): each room you know drawn in ink, or
in pencil if you've only seen it, its name and what's in it written over it, the passages between; the goal, the
quests, the tips and the key under it. With ASCII art chosen, or no room for the parchment, the chart (see chart).

Chosen by Config.layout "grid" (see tabs.game_screen). It's GameScreen underneath, as the tabs are: the turns, the
dice, the animations, the story and the panels are GameScreen's; this lays the screen out and fills its boxes.
"""

from __future__ import annotations

import textwrap
from collections.abc import Callable
from dataclasses import dataclass

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Click, Enter, Leave
from textual.widget import Widget
from textual.widgets import Footer, Input, Static

from .. import interactions, npcs, sprites
from . import parchment
from ..events import Action
from ..room_picture import look_of
from ..rules import journey, no_way, why_not
from ..sprites import DEFAULT_WIDTH, SMALL, Image
from ..world import map_glyph
from .game_screen import GameScreen
from .here import CHIP, ROW, Tile, measure, things_here
from .panels import Panel, floor_name
from .plan import Plan
from .tabs import TabsScreen, big_map, facts, known_rooms, map_notes, small_map, steps_to
from .theme import MAP_STYLES
from .widgets import (ARROWS, Clickable, ClickableBox, DPad, Hud, Picture, StoryLine, hearts, highlight, item_note,
                      roll_headline)

MIN_COLUMNS, MIN_ROWS = 110, 32  # smaller than this when a run begins, and it's the classic screen
SIDE_SHARE, SIDE_MIN, SIDE_MAX = 0.31, 40, 100  # the right column's width: a share of the screen, within bounds
BESIDE = 110  # columns left of the right column from which the decision sits beside the story (else under it)
ACT_SHARE, ACT_MIN, ACT_MAX = 0.38, 48, 72  # the decision's width beside the story: a share of them, within bounds
STAGE_SHARE = 0.36  # of the rows: the most the room's picture takes
STAGE_SHAPE = 4.8  # columns per row the picture would like (see ui/plan.py); it's drawn the column's width anyway
TALL = 44  # rows from which the big buttons have their icons, the decision under the story (beside it: see share)
BELOW = {True: 4, False: 3}  # rows under the buttons (and the blank one between), the decision under the story
PICKS = 2  # rows at the decision's foot, beside the story, for the choices left (the narrator's idea, a scene's)
PICKS_MOST = 6  # rows they may take from your things over them, when they're more than PICKS take
COMMAND = 1  # the command line's row, at the top of the decision: what you type is a choice too
DECIDE_LEAST = 2 + COMMAND + 7 + 1 + 4 + 1 + 3 + PICKS  # beside the story: its frame, the command line, short buttons,
# a gap, the compass a line a way, a gap, three lines of things, the choices
STORY_LEAST = 8
NAMED_COMPASS = 106  # columns inside the decision from which the compass says where each way goes (under the story)
COMPASS_CELL = (13, 22)  # a named compass cell's columns, least and most: it widens with the screen
BUTTON_LEAST = 20  # columns a big button keeps before the compass widens
CARD = (28, 6)  # a thing's card under the buttons: the least columns (its picture, and words beside it), its rows
LATELY_MOST, LATELY_LEAST = 10, 2  # the journal's last lines at the foot of Here: at most, and the fewest worth it
FIRST_VERB = 7  # Here's verbs are numbered on from the six big buttons
HOVER_WAIT = 0.06  # seconds the mouse rests on a room of the map before it's lit
WORDS, DIM, FAINT, PINK, GOLD, ACCENT = "#c8c8e0", "#6c6f99", "#2a2d4a", "#ff4f9a", "#ffd166", "#ffb000"
WEBBED = "#8b9bb4"  # a lair's way in, sealed with web (only fire gets through)
FOE = "#ff4b4b"  # (Here's colour for a hostile one: see here.FOE)
GROUND = "#0b0c1a"  # the screen's own dark, that a button's tints are mixed into

# The big buttons, in their fixed places: (kind, its word, its colour). Out of a fight the same places keep their
# colours where they can (Heal and Use where they always are; Bomb where Throw is, with its icon). Their hovered
# tints are app.tcss's (GridScreen .big-button.k-...).
FIGHT = [("attack", "Attack", "#ff4b4b"), ("dodge", "Dodge", "#6c8cff"), ("heal", "Heal", "#4cff8a"),
         ("throw", "Throw", "#ff7b39"), ("use", "Use", GOLD), ("flee", "Flee", "#9a9cc0")]
EXPLORE = [("search", "Search", "#5fe3ff"), ("rest", "Rest", "#6c8cff"), ("heal", "Heal", "#4cff8a"),
           ("bomb", "Bomb", "#ff7b39"), ("use", "Use", GOLD), ("gear", "Gear", "#9a9cc0")]
COLOUR = {kind: colour for kind, _, colour in FIGHT + EXPLORE}
WORD = {kind: word for kind, word, _ in FIGHT + EXPLORE}
# Why Search or Rest can't be used now, in a word or two for under the button: (words in rules.why_not's reason, the
# note). Anything else is "not now".
WHY_NOT = [("searched this room", "searched"), ("rested here", "rested"), ("not hurt", "not hurt"),
           ("fight", "in a fight"), ("vent", "gas vent"), ("shop", "her shop")]
CONFIRM = ("bomb",)
VERBS = {"Drink", "Eat", "Throw", "Use", "Distract", "Equip", "Light", "Show", "Give", "Bomb", "Read", "Offer", "Blow",
         "Unlock", "Sell", "Bribe", "Wear", "Apply", "Pour"}  # a label's first word that says what it does  # buttons that always open their row, even for one thing: a bomb's too dear to spend unseen
PANELS = [("inventory", "Pack", "F2"), ("character", "Sheet", "F3"), ("map", "Map", "F5"),
          ("bestiary", "Bestiary", "F6"), ("journal", "Journal", "F7"), ("help", "Help", "F1")]

# The buttons' icons, 8x8 pixels (4 rows of half blocks), in the sprites' palette.
INK = {"W": "#c0cbdc", "g": "#8b9bb4", "Y": "#feae34", "N": "#733e39", "R": "#e43b44", "r": "#f6757a",
       "B": "#124e89", "b": "#0099db", "c": "#2ce8f5", "K": "#3a4466", "k": "#8b9bb4", "S": "#b86f50",
       "s": "#e4a672", "y": "#fee761"}
BOMB = [".....Y..", "....N.Y.", "...N....", "..KKKK..", ".KkKKKK.", ".KKKKKK.", ".KKKKKK.", "..KKKK.."]
ICONS = {
    "attack": ["...Wg...", "...Wg...", "...Wg...", "...Wg...", ".YYYYYY.", "...NN...", "...NN...", "...YY..."],
    "dodge": [".BBBBBB.", "BbbcbbbB", "BbcbbbbB", "BbbbbbbB", ".BbbbbB.", ".BbbbbB.", "..BbbB..", "...BB..."],
    "heal": ["........", ".RR..RR.", "RrRRRRRR", "RRRRRRRR", ".RRRRRR.", "..RRRR..", "...RR...", "........"],
    "throw": BOMB,
    "bomb": BOMB,
    "use": ["..N..N..", "...NN...", "..SSSS..", ".SsSSSS.", "SSSYYSSS", "SSSSSSSS", ".SSSSSS.", "........"],
    "flee": ["........", "....g...", "....gg..", "gggggggg", "gggggggg", "....gg..", "....g...", "........"],
    "search": ["..WWW...", ".W...W..", "W..c..W.", "W.....W.", ".W...W..", "..WWWN..", "......N.", ".......N"],
    "rest": ["...yyy..", "..yy....", ".yy.....", ".yy.....", ".yy.....", "..yy....", "...yyy..", "........"],
    "gear": [".g....g.", "gWg..gWg", "gWWggWWg", "gWWWWWWg", ".gWWWWg.", ".gWggWg.", ".gWWWWg.", "..gggg.."],
}


def tint(colour: str, amount: float) -> str:
    """`colour` mixed into the screen's dark: a button's own shade, for its background when urgent or open."""
    mix = [round(int(GROUND[i:i + 2], 16) * (1 - amount) + int(colour[i:i + 2], 16) * amount) for i in (1, 3, 5)]
    return "#" + "".join(f"{c:02x}" for c in mix)


def icon(kind: str, live: bool) -> Text:
    """A button's icon as half-block text; greyed out, one colour, when the button can't be used now."""
    img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    for y, row in enumerate(ICONS[kind]):
        for x, ink in enumerate(row):
            if ink != ".":
                hexcode = INK[ink] if live else "#2e3352"
                img.putpixel((x, y), (*(int(hexcode[i:i + 2], 16) for i in (1, 3, 5)), 255))
    return sprites.image_text(img, snap=True)


def kind_of(action: Action, content, fight: bool) -> str:
    """Which big button an action belongs to, in a fight or out of one, or "" if none does."""
    verb, _, key = action.id.partition(":")
    healing = verb == "use" and key and "@" not in key and "glows" not in action.hint and (
        content.item(key).heal or content.item(key).cures)  # (a light's offered to dazzle, not to heal)
    if healing:
        return "heal"
    if fight:
        if verb in ("attack", "dodge", "flee"):
            return verb
        if verb in ("bomb", "throw") or (verb == "use" and key and "@" not in key and content.item(key).escape):
            return "throw"
        return "use" if verb in ("use", "distract") else ""
    return {"search_room": "search", "rest": "rest", "bomb": "bomb", "equip": "gear", "use": "use",
            "reveal": "use", "distract": "use", "throw": "use"}.get(verb, "")


def wasted(content, action_id: str) -> bool:
    """Whether a use would throw away something that heals, on whatever it's used on: at full HP a potion's only use
    in a fight is to be thrown (for 1d4), and one click shouldn't do that. Typed, it still can be."""
    key, at, _ = action_id.partition(":")[2].partition("@")
    return action_id.startswith("use:") and bool(at) and key in content.items and bool(content.item(key).heal)


def short(action: Action) -> str:
    """An option's words in a row: the thing, not the whole sentence ("Healing Potion", not "Drink the...")."""
    label = action.label
    for verb in ("Drink ", "Eat ", "Throw ", "Use ", "Distract ", "Equip ", "Bomb "):
        if label.startswith(verb):
            label = label[len(verb):]
            break
    thing = label.split(" with ")[-1].split(" at ")[0].split(" on ")[0].split(" (")[0]
    thing = thing.removeprefix("the ").removeprefix("a ").removeprefix("an ")[:28]
    return f"{thing} (distract)" if action.id.startswith("distract:") else thing


def chip(key: str, words: str, colour: str, hint: str = "") -> Text:
    """A choice as a button: its key on a block of colour, its words, and what it'd do, dim, after them."""
    text = Text.assemble((f" {key} ", f"bold #10122a on {colour}"),  # (a line's lead space is dropped)
                         (f" {words}", f"bold {colour if colour == PINK else '#e8e8f4'}"))
    if hint:
        text.append(f"  {hint}", style=DIM)
    return text


def wrapped(chips: list[tuple[Widget, int]], width: int) -> list[Horizontal]:
    """Widgets of these widths, packed into lines no wider than `width`."""
    lines, line, used = [], [], 0
    for widget, w in chips:
        if line and used + w > width:
            lines.append(line)
            line, used = [], 0
        line.append(widget)
        used += w
    if line:
        lines.append(line)
    return [Horizontal(*line, classes="chip-line") for line in lines]


def way_name(state, direction: str) -> tuple[str, str]:
    """Where a way out goes, in a word or two, and its colour: a room you've been to by its name, else what you can
    see through the door."""
    exit_ = state.room.exits[direction]
    there = state.rooms[exit_.to]
    name = "webbed" if exit_.webbed else ("locked" + (": a shop" if there.shop else "")) if exit_.locked else \
        there.name if there.visited else (FIXTURE_WORDS.get(there.fixture, f"a {there.fixture}").removeprefix("the ")
                                          if there.fixture and not there.fixture_used else "unexplored")
    colour = WEBBED if exit_.webbed else "#c05a6c" if exit_.locked else "#5fe3ff" if there.visited else \
        GOLD if there.fixture else DIM
    return name, colour


# --- the chart: the floor, each room a box ---------------------------------------------------------------------------

FIXTURE_WORDS = {"stairs": "the stairs down", "shop": "a shop", "chest": "a chest", "shrine": "a shrine",
                 "fountain": "a fountain"}
# The full chart's boxes, roomiest first, the first that fits whole names: (padding inside a box, columns and rows
# between boxes, lines of notes under a name). The last fits what it can.
ROOMY = [(2, 10, 3, 2), (1, 8, 2, 2), (1, 6, 2, 1)]


def room_label(room, short: bool = False) -> str:
    """A room's words on the chart: its name once you've been in, else what you know of it. `short` (the small map,
    where the box and its mark say the rest): a fixture by its word alone, and nothing for a room you know nothing
    of."""
    if room.visited:
        return room.name
    if room.secret:
        return "secret" if short else "a secret room"
    if room.fixture and not room.fixture_used:
        return room.fixture if short else FIXTURE_WORDS.get(room.fixture, f"a {room.fixture}")
    return "" if short else "unexplored"


def room_notes(state, room) -> list[tuple[str, str]]:
    """What a room on the full chart says under its name, most telling first, each in its colour: what's in it that
    matters (a foe, someone waiting, a tip, what's lying there, a fixture not yet used, a draft), and whether it's been
    searched; nothing for a room you haven't been in."""
    if not room.visited:
        return [("a secret, they say", GOLD)] if room.told else []
    notes = []
    monster = room.monster
    if monster and monster.hp > 0:
        notes.append((monster.name, FOE) if monster.hostile else
                     (monster.name + (" · waiting" if npcs.waiting(state, monster) else ""), PINK))
    if any(f.told and not f.searched for f in room.features):
        notes.append(("something hidden", GOLD))
    if room.items:
        notes.append((f"{len(room.items)} thing{'s' * (len(room.items) != 1)} lying here", ACCENT))
    if room.fixture and not room.fixture_used:
        notes.append((FIXTURE_WORDS.get(room.fixture, room.fixture).removeprefix("a ").removeprefix("the "), PINK))
    if room.draft and not room.secret:
        notes.append((f"a draft, {room.draft}", "#5fe3ff"))
    if room.room_searched:
        notes.append(("searched", DIM))
    return notes


def name_lines(words: str, width: int, most: int) -> list[str]:
    """A name in at most `most` lines `width` wide, split between words, the last cut short (…) if it must be."""
    lines = textwrap.wrap(words, width, max_lines=most, placeholder="…", break_long_words=False) or [""]
    return [line if len(line) <= width else line[:width - 1] + "…" for line in lines]


def chart(state, width: int, height: int, roomy: bool, hover: int | None = None) -> Text | None:
    """The floor as a dungeon chart, at most `width` x `height`: each room a box with its mark and its name in it, you
    in amber, the rooms you haven't been in dashed and dim, the secret one gold; passages between them where you know
    of them, a door's joint where one leaves a room, a locked one doubled in red. A name too long for its box takes a
    second line if there are rows for it, else it's cut short. `roomy` (the full map): boxes and passages as big as
    the room allows (ROOMY), and a line or two in each box saying what's in it. Hover a room: where it is. Click one
    you can get back to: you travel there (rules.journey); `hover`, the one the mouse is on, is framed in gold, so
    it's plain that it's a click away. None if even short names won't fit."""
    rooms = known_rooms(state)
    min_x, min_y = min(r.x for r in rooms), min(r.y for r in rooms)
    across, down = max(r.x for r in rooms) - min_x + 1, max(r.y for r in rooms) - min_y + 1
    labels = {r.id: room_label(r, short=not roomy) for r in rooms}
    notes = {r.id: room_notes(state, r) for r in rooms} if roomy else {}

    least = 10 if roomy else 6
    wanted = max([least] + [len(s) for s in labels.values()] + [len(n) - 2 for ns in notes.values() for n, _ in ns[:2]])

    def shape(pad: int, gap_x: int, gap_y: int, lines: int) -> tuple[int, int, int]:
        """(the names' width, the boxes' height, the chart's rows) with these spaces, and lines in a box."""
        name_w = min(wanted, (width - (across - 1) * gap_x) // across - 4 - 2 * pad)
        return name_w, 2 + lines, down * (2 + lines + gap_y) - gap_y

    # The full chart: its roomiest boxes that fit whole names, else the smallest. The small map: a name a line, or
    # two where one won't do and there are rows to spare.
    options = [(pad, gx, gy, 1 + n) for pad, gx, gy, n in ROOMY] if roomy else [(0, 2, 1, 1), (0, 2, 1, 2)]
    fits = [o for o in options if shape(*o)[2] <= height and shape(*o)[0] >= least]
    if not fits:
        return None
    pad, gap_x, gap_y, lines = next((o for o in fits if shape(*o)[0] >= wanted), fits[-1])
    name_w, box_h, rows = shape(pad, gap_x, gap_y, lines)
    box_w = name_w + 4 + 2 * pad
    cols = across * box_w + (across - 1) * gap_x
    grid: list[list[tuple[str, Style | None]]] = [[(" ", None)] * cols for _ in range(rows)]
    mapped = state.mapped_floor == state.floor
    passage, locked = Style.parse("#3d4a8c"), Style.parse("bold #c05a6c")

    def put(y: int, x: int, ch: str, style: Style) -> None:
        if 0 <= y < rows and 0 <= x < cols:
            grid[y][x] = (ch, style)

    def write(y: int, x: int, words: str, style: Style) -> None:
        for i, ch in enumerate(words):
            put(y, x + i, ch, style)

    places, tips = {}, {}
    for room in rooms:
        left, top = (room.x - min_x) * (box_w + gap_x), (room.y - min_y) * (box_h + gap_y)
        places[room.id] = (left, top)
        here = room.id == state.room_id
        reachable = not here and journey(state, room.id) is not None
        label = labels[room.id]
        tip = Style(meta={"tip": room_label(room) + (" (you're here)" if here else " (click to travel there)"
                                                     if reachable else ""),
                          "room": room.id, **({"travel": room.id} if reachable else {})})
        tips[room.id] = tip
        lit = reachable and room.id == hover
        edge = Style.parse(f"bold {ACCENT}" if here else "bold #ffd166" if lit else GOLD if room.secret else "#5a6cb8"
                           if room.visited else "#34395e") + tip
        bottom, right = top + box_h - 1, left + box_w - 1
        across_ch, down_ch = ("─", "│") if room.visited or here else ("┄", "┆")
        for x in range(left + 1, right):
            put(top, x, across_ch, edge)
            put(bottom, x, across_ch, edge)
        for y in range(top + 1, bottom):
            put(y, left, down_ch, edge)
            put(y, right, down_ch, edge)
        for (y, x), ch in {(top, left): "╭", (top, right): "╮", (bottom, left): "╰", (bottom, right): "╯"}.items():
            put(y, x, ch, edge)
        for y in range(top + 1, bottom):  # (the box's inside, hoverable and clickable too)
            write(y, left + 1, " " * (box_w - 2), tip)
        glyph = map_glyph(state, room)
        write(top + 1, left + 1 + pad, glyph, Style.parse(f"bold {ACCENT}" if here else MAP_STYLES.get(glyph[0], DIM))
              + tip)
        name_style = Style.parse("bold #ffffff" if here or lit else WORDS if room.visited else f"italic {DIM}") + tip
        names = name_lines(label, name_w, 1 if roomy else lines)
        for i, line in enumerate(names):
            write(top + 1 + i, left + 3 + pad, line, name_style)
        for i, (note, colour) in enumerate(notes.get(room.id, [])[:lines - 1]):
            note = note if len(note) <= name_w + 2 else note[:name_w + 1] + "…"
            write(top + 2 + i, left + 1 + pad, note, Style.parse(f"italic {colour}") + tip)
    # The passages, and a door's joint on each box they leave: a door is drawn from both its rooms, and only one side
    # of it says it's locked, so the open sides first and the locked ones over them.
    doors = sorted(((room, direction, exit_) for room in rooms if room.visited or mapped
                    for direction, exit_ in room.exits.items() if exit_.to in places), key=lambda door: door[2].shut)
    for room, direction, exit_ in doors:
        left, top = places[room.id]
        bottom, right, mid = top + box_h - 1, left + box_w - 1, left + box_w // 2
        style = Style.parse(WEBBED) if exit_.webbed else locked if exit_.locked else passage
        joint = style + tips[room.id]  # (a door in a room's wall is still that room's, to hover and click)
        if direction in ("east", "west"):
            put(top + 1, right if direction == "east" else left, "├" if direction == "east" else "┤", joint)
            span = range(right + 1, right + 1 + gap_x) if direction == "east" else range(left - gap_x, left)
            for x in span:
                put(top + 1, x, "┄" if exit_.webbed else "═" if exit_.locked else "─", style)
        else:
            put(bottom if direction == "south" else top, mid, "┬" if direction == "south" else "┴", joint)
            span = range(bottom + 1, bottom + 1 + gap_y) if direction == "south" else range(top - gap_y, top)
            for y in span:
                put(y, mid, "┆" if exit_.webbed else "║" if exit_.locked else "│", style)
    text = Text(no_wrap=True)
    for row in grid:
        for ch, style in row:
            text.append(ch, style=style)
        text.append("\n")
    text.rstrip()
    return text


def drawn_map(state, width: int, height: int, roomy: bool = False, hover: int | None = None) -> Text:
    """The floor as big as it fits: the chart (roomy, if asked and there's room), else the marks with names under
    them, else the marks alone."""
    return ((roomy and chart(state, width, height, True, hover)) or chart(state, width, height, False, hover)
            or big_map(state, width, height) or small_map(state))


class ChartScreen(Panel):
    """The Map panel, the floor in full: the whole screen, the floor drawn on parchment (parchment.draw), each room you
    know with its name and what's in it, and under it the goal, the quests, the tips and the key, all centred. With
    ASCII art chosen, or no room for the parchment, the chart instead, the floor's name over it. A room you can get
    back to, clicked: you travel there."""

    panel_name = "map"

    def __init__(self, game) -> None:
        super().__init__()
        self.game = game
        self.hover: int | None = None  # the room the mouse is on, that you can get back to: lit
        self.drawn: tuple | None = None  # what the map was last drawn for: the screen's size, the room lit
        self.drawings: dict[tuple, tuple[Text, bool]] = {}  # each drawing so far, and whether it's the parchment:
        # nothing on the floor moves while the map's up
        self._hover_timer = None

    def compose(self) -> ComposeResult:
        state, content = self.game.state, self.game.content
        theme = content.themes[state.theme]
        accent = look_of(state.theme).accent
        with Vertical(classes="panel-box chart-box") as box:
            box.border_title = f"✦ Map · floor {state.floor} of {state.floors_total}"
            seen = sum(r.visited for r in state.rooms if not r.secret)
            box.border_subtitle = (f"{seen} of {sum(not r.secret for r in state.rooms)} rooms seen · click a room "
                                   "you've been in to go there · Esc to close")
            box.styles.border = ("double", accent)
            box.styles.border_title_color = accent
            with Vertical(classes="chart-head"):
                yield Static(Text(floor_name(theme.name, 999), style=f"bold {accent}"), classes="chart-name")
                yield Static(Text(theme.goal if state.boss_floor else "Find the stairs down.", style=f"italic {DIM}"),
                             classes="chart-goal")
                yield Static(classes="chart-rule")
            with Vertical(classes="chart-holder"):
                yield StoryLine(id="chart")
            yield Static(classes="chart-rule")
            with Vertical(classes="chart-notes-holder"):
                yield Static(map_notes(state, content), classes="chart-notes")

    def fit(self) -> None:
        """The whole screen less a margin; the parchment (or the chart) as big as the rows the notes leave."""
        width, height = self.app.size
        state, content = self.game.state, self.game.content
        box = self.box
        box.styles.width, box.styles.height = width - 6, height - 2
        inner = width - 6 - 6
        rule = Text("─" * (inner // 2 - 2) + " ✦ " + "─" * (inner // 2 - 2), style=FAINT)
        for line in self.query(".chart-rule").results(Static):
            line.update(rule)
        self.draw()

    def draw(self) -> None:
        """The parchment (or the chart) as big as the rows the notes leave, the room the mouse is on lit. Drawn only
        when that's changed (opening sizes it twice), and each drawing kept while the map is up: sweeping the mouse
        over the rooms drew the whole map again for each, and the screen stopped answering for a while."""
        width, height = self.app.size
        key = (width, height, self.hover)
        if key == self.drawn:
            return
        self.drawn = key
        if key not in self.drawings:
            self.drawings[key] = self._drawing(width, height)
        drawn, on_paper = self.drawings[key]
        self.query_one(".chart-head").display = not on_paper  # (the parchment has the floor's name on it)
        self.query_one("#chart", StoryLine).update(drawn)

    def _drawing(self, width: int, height: int) -> tuple[Text, bool]:
        state, content = self.game.state, self.game.content
        inner = width - 6 - 6
        notes = 6 + len(npcs.quest_log(state, content))
        drawn = None
        if self.game.config.art == "sprites":
            drawn = parchment.draw(state, inner, height - 2 - 2 - 2 - notes, content.themes[state.theme].name,
                                   {r.id: room_label(r) for r in state.rooms},
                                   {r.id: room_notes(state, r) for r in state.rooms}, self.hover)
        if drawn is not None:
            return drawn, True
        return drawn_map(state, inner, height - 2 - 4 - 4 - notes, roomy=True, hover=self.hover), False

    def hover_room(self, line: StoryLine, room: int | None) -> None:
        """The mouse has come to a room you can get back to (or left it): it's lit, or not, once the mouse has
        settled for a moment (a sweep across the map lights only where it stops)."""
        if room == self.hover:
            return
        self.hover = room
        if self._hover_timer is not None:
            self._hover_timer.stop()
        self._hover_timer = self.set_timer(HOVER_WAIT, self.draw)

    def why_not_travel(self, room_id: int) -> None:
        """A room clicked that there's no way to now: why not (rules.no_way)."""
        state = self.game.state
        room = state.rooms[room_id]  # (one you haven't been in keeps its name to itself, as on the map)
        self.notify(no_way(state, room_id), title=room.name if room.visited else "Unexplored", timeout=3)

    def action_travel(self, room_id: int) -> None:
        """A room clicked: back to the game, and there (as GameScreen.action_travel)."""
        name = self.game.state.rooms[room_id].name
        self.dismiss(Action(f"travel:{room_id}", f"Travel to {name}"))


# --- the screen -------------------------------------------------------------------------------------------------------

@dataclass
class Grid:
    """The screen shared out (see GridScreen.relayout): every box's size, from the screen's alone."""
    side: int  # the right column, with its gutter
    left: int  # the columns left of it: the picture across them, the story and the decision under it
    beside: bool  # the decision beside the story (a wide screen), else under it
    story_w: int  # the story's box: beside the decision, the columns the decision leaves; else all of them
    stage: int  # the picture's rows, inside its frame (the map's box is as tall as the picture's)
    story: int  # the story's box, frame and all
    decide: int  # the decision's box, frame and all
    bar: int  # a big button's rows (7 with its icon, 3 without)
    ways: int  # the compass's rows: beside the story, under the buttons, a heading and three rows of ways, two lines
    # each with a blank row between them (9), or without (7), or a line each (4); under it, beside the buttons, as
    # tall as they are
    cell: int  # a compass cell's columns
    strip: int  # the panels' buttons, at the foot of the right column
    tall: bool  # the big buttons have their icons

    @property
    def band(self) -> int:
        """The rows under the picture (and the map)."""
        return self.story if self.beside else self.story + self.decide

    @property
    def named(self) -> bool:
        """Whether the compass's cells have the room to say where each way goes."""
        return self.beside or self.cell >= COMPASS_CELL[0]


def share(width: int, height: int) -> Grid:
    """The screen shared out, from its size alone: the right column a share of the width; the room's picture across
    the rest, as tall as its shape asks (to a share of the rows), the map beside it as tall; under them the story, the
    decision and Here. On a wide screen the decision is beside the story, a share of their columns, as tall as it: its
    buttons with their icons if it's tall enough for them and the compass under them; the compass's ways two lines
    tall if there are still rows for the things under it. On a narrower one the decision is under the story, a fixed
    height (the buttons, a blank row, the rows under them), and the compass beside the buttons, its cells widening
    with it once the buttons have their least."""
    rows = height - 2  # (less the status bar and the footer)
    side = max(SIDE_MIN, min(SIDE_MAX, round(width * SIDE_SHARE)))
    left = width - side
    strip = 3 if side >= 54 else 6  # (one row of six, or two of three)
    stage = max(6, min(round((left - 2) / STAGE_SHAPE), round(STAGE_SHARE * rows)))
    if left >= BESIDE:
        act = max(ACT_MIN, min(ACT_MAX, round(left * ACT_SHARE)))
        stage = max(4, min(stage, rows - 2 - DECIDE_LEAST))
        band = rows - (stage + 2)
        tall = band >= 2 + COMMAND + 15 + 1 + 4 + 1 + 3 + PICKS  # (two rows of buttons with icons, the least under)
        bar = 7 if tall else 3
        under = band - 2 - COMMAND - (2 * bar + 1) - 1 - PICKS  # (less its frame, the command line, the buttons, a
        # gap and the choices)
        cards = 1 + 1 + CARD[1]  # (a row of your things: its heading, a gap, the cards)
        ways = 9 if under >= 9 + 1 + cards else 7 if under >= 7 + 1 + cards else 4
        return Grid(side, left, True, left - act, stage, band, band, bar, ways, (act - 4 - 2) // 3, strip, tall)
    tall = rows >= TALL
    bar = 7 if tall else 3
    decide = 2 + COMMAND + bar + 1 + BELOW[tall]
    story = rows - (stage + 2) - decide  # (the command line's row the decision's now, not the story's box's)
    if story < STORY_LEAST:
        stage = max(4, stage - (STORY_LEAST - story))
        story = rows - (stage + 2) - decide
    named = left - 4 >= NAMED_COMPASS
    least, most = COMPASS_CELL
    cell = max(least, min(most, (left - 4 - 1 - 6 * BUTTON_LEAST) // 3)) if named else 5
    return Grid(side, left, False, left, stage, story, decide, bar, bar, cell, strip, tall)


class BigButton(Vertical):
    """One of the big buttons. Built once for its place (its number in its frame, as tall as the screen allows) and
    then shown in one look or another, in place, as the turns go by (see show): no rebuilding it, which would leave a
    frame with no button in it. A shade (urgent, open, hovered) fills its face, inside the frame: on the frame itself
    it would show half a cell outside the line."""

    def __init__(self, kind: str, number: int, tall: bool, pictured: bool) -> None:
        self.face = Static(classes="face")
        super().__init__(self.face, classes=f"big-button k-{kind}")
        self.kind, self.number, self.pictured = kind, number, pictured
        self.look: str | None = None
        self.shown: tuple | None = None
        self.border_title = str(number)
        self.styles.height = 7 if tall else 3

    def show(self, look: str, note: str, wide: bool) -> None:
        """Its look: "live", "hot" (urgent), "open" (its options are showing) or "dead" (it can't be used now); its
        icon (if it's pictured) and word inside, its note under it (if it's `wide` enough)."""
        if (look, note, wide) == self.shown:
            return
        colour, live = COLOUR[self.kind], look != "dead"
        if self.look is None or (self.look != "dead") != live:  # (the face changes only as it comes alive or dies)
            text = Text(justify="center")
            if self.pictured:
                text.append_text(icon(self.kind, live))
                text.append("\n")
            text.append(WORD[self.kind], style=f"bold {colour}" if live else "#3a3f66")
            self.face.update(text)
        self.shown, self.look = (look, note, wide), look
        for name in ("live", "hot", "open", "dead"):
            self.set_class(name == look, name)
        self.styles.border = ("heavy" if look in ("hot", "open") else "round", colour if live else "#23264a")
        self.styles.border_title_color = colour if live else "#3a3f66"
        self.styles.border_subtitle_color = colour if look == "hot" else DIM if live else "#3a3f66"
        if look in ("hot", "open"):
            self.face.styles.background = tint(colour, 0.2 if look == "hot" else 0.12)
        else:  # (app.tcss's hover shade, then, not one set here)
            self.face.styles.clear_rule("background")
        self.border_subtitle = note if wide else ""
        self.tooltip = self.face.tooltip = f"{WORD[self.kind]}: {note}" if note else WORD[self.kind]
        if not live:
            self.remove_class("-hover")

    async def on_click(self, event: Click) -> None:
        event.stop()
        await self.run_action(f"screen.bar('{self.kind}')")

    def on_enter(self, event: Enter) -> None:
        """(Hovered, frame or face: a tint of its own colour, app.tcss's GridScreen .big-button.-hover.)"""
        self.set_class(self.look != "dead", "-hover")

    def on_leave(self, event: Leave) -> None:
        self.set_class(self.look != "dead" and self.is_mouse_over, "-hover")


class CompassCell(Static):
    """One of the compass's five cells (or a blank corner), built once for its place and shown in place (see show):
    a way out, lit, a click away; a wall, faint; you in the middle."""

    def __init__(self) -> None:
        super().__init__(classes="compass-cell")
        self.action = ""
        self.shown: tuple | None = None

    def show(self, text: Text, kind: str, action: str = "", tip: str = "") -> None:
        if (text, kind, action, tip) == self.shown:
            return
        self.shown = (text, kind, action, tip)
        self.update(text)
        for name in ("way", "wall", "middle"):
            self.set_class(name == kind, name)
        self.action, self.tooltip = action, tip or None

    async def on_click(self, event: Click) -> None:
        event.stop()
        if self.action:
            await self.run_action(self.action)


def item_key(action: Action, content) -> str:
    """The thing an option would use, if it's a thing you carry ("" for a wall to bomb, say): use:healing_potion's
    potion, throw:holy_water's water, a fight's bomb, give:bread@lucky_lenny's bread."""
    verb, _, rest = action.id.partition(":")
    key = rest.split("@")[0]
    if key in content.items:
        return key
    return "bomb" if verb == "bomb" and not rest and "bomb" in content.items else ""


def rule(words: str, width: int, colour: str = DIM) -> Text:
    """A heading across a box: its words, then a line to the edge."""
    text = Text(words.upper(), style=f"bold {colour}")
    text.append(" " + "─" * max(0, width - len(words) - 1), style="#30345a")
    return text


class ItemCard(Horizontal):
    """A thing as a card under the buttons: its picture (or an arrow, for a wall to bomb), and beside it, if there's
    something to do with it now (`action`), its letter, what it does and to what, and how it would go ("weak!", "won't
    work"): clicked, it's done. If there isn't, it's dim, with what it is and why not ("full HP")."""

    def __init__(self, index: int, action: Action | None, kind: str, key: str, content, sprites: bool, count: int,
                 why: str = "", weak: list[str] | None = None, width: int = 0) -> None:
        colour = COLOUR.get(kind, GOLD)
        if action is not None:
            verb = action.label.split(" ")[0]
            verb = verb if verb in VERBS else WORD.get(kind, "Use")  # (a picker's option is only the thing: "5 gold")
            words = Text.assemble((f" {chr(97 + index)} ", f"bold #10122a on {colour}"),
                                  (f" {verb.upper()}", f"bold {colour}"))
            words.append("\n" + short(action), style="bold #e8e8f4")
            hint = action.hint or (item_note(content, key) if key else "")
            if weak:
                words.append(f"\n✔ weak to {' and '.join(weak)}!", style="bold #4cff8a")
            if hint:
                good = any(word in hint for word in ("weak", "heals", "full heal", "get away", "shows", "loses"))
                bad = any(word in hint for word in ("won't", "NO", "breaks"))
                words.append("\n" + hint, style="#4cff8a" if good else FOE if bad else WORDS)
        else:
            words = Text(content.item(key).name, style=f"bold {DIM}")
            words.append("\n" + item_note(content, key), style=DIM)
            words.append("\n" + why, style="#4a4e7a")
        if count > 1:
            words.append(f"\n×{count} in your pack", style=DIM)
        if key:
            picture: Widget = Picture(key, "item", SMALL, content=content, sprites=sprites, animate=False,
                                      classes="card-art")  # (still: a card's a button, not a show)
        else:
            arrow = ARROWS.get(action.id.partition(":")[2], "✦") if action else "✦"
            picture = Static(Text(f"\n\n{arrow}", style=f"bold {colour}", justify="center"), classes="card-art")
        super().__init__(picture, Static(words, classes="card-words"),
                         classes=f"item-card k-{kind}" + ("" if action else " idle"))
        if width:
            self.styles.width = width
        self.index, self.action = index, action
        self.tooltip = (action.label + (f" ({action.hint})" if action.hint else "")) if action else \
            f"{content.item(key).name}: {why}"

    async def on_click(self, event: Click) -> None:
        event.stop()
        if self.action is not None:
            await self.run_action(f"screen.pick({self.index})")

    def on_enter(self, event: Enter) -> None:
        self.set_class(self.action is not None, "-hover")

    def on_leave(self, event: Leave) -> None:
        self.set_class(self.action is not None and self.is_mouse_over, "-hover")


class GridScreen(GameScreen):
    """The game screen as a fixed grid (see the module's docstring): its layout, its boxes and its decision; the turns
    are GameScreen's."""

    STORY_WIDTH = 100  # (as app.tcss's GridScreen #story > *)
    def story_frame(self) -> Widget:
        """The box round the story and the command line: its border is the story's frame here (the story itself has
        none), so it's the one a roll's colour lights up."""
        return self.query_one("#story-box")

    def __init__(self, game, fresh: bool, switched: bool = False) -> None:
        super().__init__(game, fresh, switched)
        self.grid: Grid | None = None
        self.tray: tuple[str, list[Action], str] | None = None  # the options showing under the buttons, if a button
        # or a thing's picker (Give…) opened them: (their title, the options, the big button whose they are, or "")
        self.offered: list[Action] = []  # what's under the buttons now, a letter each: the open tray's, or your things
        self.item_page = 0  # which page of them, when they're more than fit
        self.slots: dict[int, tuple] = {}  # what typing each number does: ("bar", kind) or ("action", Action)
        self.groups: dict[str, list[Action]] = {}  # the big buttons' actions, by kind
        self.here_drawn: tuple | None = None
        self.map_drawn: tuple | None = None
        self.map_hover: int | None = None  # the room on the map the mouse is on, that you can get back to: lit
        # What each part of the screen shows, as it was last drawn: each is drawn again only when that changes, and
        # what can be shown in place is (the buttons, the compass's cells, Lately), never torn down and built again.
        self.buttons: dict[str, BigButton] = {}
        self.cells: dict[str, CompassCell] = {}
        self.bar_built: tuple | None = None
        self.compass_built: tuple | None = None
        self.below_drawn: tuple | None = None
        self.picks_drawn: tuple | None = None
        self.lately_drawn: tuple | None = None
        self.here_used = 0  # the rows Here's things take, the rest Lately's
        self.here_you: Static | None = None  # in a fight, your hearts over the foe's card, and how the last turn went
        self.here_last: Static | None = None  # under it: both shown in place
        self.duel: tuple[Picture, Static] | None = None  # the foe's card: its picture, and all you know of it

    def compose(self) -> ComposeResult:
        with Horizontal(id="hud-row"):
            yield Hud(id="hud")
            yield Static(id="hud-short")
            yield Clickable(Text(" ☰ "), "screen.menu()", id="hud-menu")
        with Horizontal(id="main"):
            with Vertical(id="play"):
                with Vertical(id="stage-box"):
                    with ClickableBox(action="screen.stage_card()", id="stage"):
                        yield Static(id="stage-art")
                with Horizontal(id="band"):
                    with Vertical(id="story-box"):
                        yield VerticalScroll(id="story")
                    with Vertical(id="decide"):  # (what you type first: it's a choice too, any you like)
                        yield Input(id="command", placeholder="✎ Type anything you want to try, or a number…")
                        with Horizontal(id="top-row"):  # (the buttons, and the compass under them or beside them)
                            yield Vertical(id="bar")
                            yield Vertical(id="compass")
                        yield VerticalScroll(id="below")  # your things, or the options a button's opened
                        yield VerticalScroll(id="picks")  # the choices left: the narrator's idea, a scene's
            with Vertical(id="side"):
                with Vertical(id="map"):
                    with Vertical(id="map-holder"):
                        yield StoryLine(id="map-art")
                    yield Static(id="map-notes")
                with Vertical(id="here", classes="panel"):
                    yield Vertical(id="here-things")
                    with Vertical(id="here-lately"):
                        yield Static(id="lately-head", classes="here-head")
                        yield StoryLine(id="lately", classes="lately")
                yield Vertical(id="strip")
        with Vertical(id="shims"):  # (what GameScreen's turns look for, that this layout hasn't)
            yield Vertical(id="here-strip")
            yield Static(id="choices")
            yield Horizontal(id="ways")
            yield DPad(id="dpad")
        yield Footer()

    # --- the grid ---

    def relayout(self) -> None:
        """Share the screen out (see share) and, if that's changed (the screen was resized), size every box to it:
        the right column's boxes as tall as the left's beside them, so their edges meet. Then fill them, each drawn
        again only if what it shows has changed: sizing the boxes on every turn would lay out, and paint, the whole
        screen again each time."""
        if self._resize_timer is not None:
            self._resize_timer.stop()
            self._resize_timer = None
        width, height = self.size
        if not width:
            return
        grid = share(width, height)
        if grid != self.grid:
            self.grid = grid
            self.here_drawn = self.map_drawn = self.lately_drawn = None
            self.bar_built = self.compass_built = self.below_drawn = self.picks_drawn = None
            self.place(grid)
            self.draw_strip()
        self.refresh_hud()
        self.refresh_stage()
        self.refresh_here()
        self.refresh_choices()

    def place(self, grid: Grid) -> None:
        """Every box sized to the screen as it's shared out."""
        width, height = self.size
        self.plan = Plan(width, height, True, False, False, grid.side, grid.stage, grid.left - 2, BELOW[grid.tall], 0,
                         grid.band - grid.strip - 2, grid.story - 2)
        band, story, decide = self.query_one("#band"), self.query_one("#story-box"), self.query_one("#decide")
        band.styles.layout = "horizontal" if grid.beside else "vertical"
        band.styles.height = grid.band
        story.styles.width = grid.story_w if grid.beside else "100%"
        story.styles.height = "100%" if grid.beside else grid.story
        decide.styles.width = "1fr" if grid.beside else "100%"
        decide.styles.height = "100%" if grid.beside else grid.decide
        decide.set_class(grid.beside, "beside")
        self.query_one("#top-row").styles.layout = "vertical" if grid.beside else "horizontal"
        for box, h in (("#stage-box", grid.stage + 2), ("#map", grid.stage + 2), ("#here", grid.band - grid.strip),
                       ("#strip", grid.strip)):
            self.query_one(box).styles.height = h
        self.query_one("#side").styles.width = grid.side
        story.border_title = "✦ Story"
        story.border_subtitle = self.game.llm.name if self.game.llm else "offline narrator"

    def swap(self, box: Widget, widgets: list[Widget]) -> None:
        """What's in a box, swapped for these in one go: the screen isn't painted between taking the old out and
        putting the new in, so there's never a frame with the box empty (it showed as text flashing off and on)."""
        async def go() -> None:
            async with box.batch():
                await box.remove_children()
                await box.mount_all(widgets)

        self.call_later(go)

    refresh_panels = relayout
    refresh_stage = TabsScreen.refresh_stage  # (its frame red in a fight, titled with the room)

    def refresh_ways(self) -> None:
        """(The ways out are the compass's.)"""

    # --- the right column ---

    def refresh_here(self) -> None:
        """The map and Here: each drawn again only if what it shows has changed."""
        self.draw_map()
        self.draw_here()

    def draw_map(self) -> None:
        """The floor as a chart in the map's box (as much of each name as fits), the goal and the quests under it."""
        state, content, grid = self.game.state, self.game.content, self.grid
        quests = [line for _, line, still in npcs.quest_log(state, content) if still][:2]
        doors = tuple(tuple((way, e.to, e.locked, e.webbed) for way, e in r.exits.items()) for r in state.rooms)
        shown = (grid, state.floor, state.room_id, doors, tuple((r.id, r.visited, r.fixture_used, map_glyph(state, r),
                                                                 r.told, journey(state, r.id) is not None)
                                                                for r in state.rooms),
                 state.mapped_floor, tuple(quests), self.map_hover)  # (where you can travel to: a fight's end, a
        # perk picked, a scene over make the rooms clickable again; a wall blown open, a door broken in, a secret
        # room told of: what's on it now)
        if shown == self.map_drawn:
            return
        self.map_drawn = shown
        width, rows = grid.side - 5, grid.stage
        notes = 1 + len(quests)
        self.query_one("#map-art", StoryLine).update(drawn_map(state, width, rows - notes, hover=self.map_hover))
        goal = next((r for r in state.rooms if (r.is_boss if state.boss_floor else r.fixture == "stairs")), None)
        text = Text("GOAL ", style=f"bold {DIM}")
        if goal and (goal.visited or state.mapped_floor == state.floor):
            steps = steps_to(state, goal.id)
            away = "you're there" if steps == 0 else f"{steps} room{'s' * (steps != 1)} away" if steps else "no way known"
            text.append(f"{'The boss' if state.boss_floor else 'The stairs'}: ", style="bold #e8e8f4")
            text.append(goal.name, style="#5fe3ff")
            text.append(f" · {away}", style=DIM)
        else:
            text.append("Find the " + ("boss's lair" if state.boss_floor else "stairs down"), style="bold #e8e8f4")
        lines = [text]
        for line in quests:
            lines.append(Text.assemble(("★ ", PINK), (line, WORDS)))
        for line in lines:  # (a line each, cut short if it must be: a second would be lost under the frame)
            line.truncate(width, overflow="ellipsis")
        text = Text("\n").join(lines)
        notes_box = self.query_one("#map-notes", Static)
        notes_box.styles.height = notes
        notes_box.update(text)
        box = self.query_one("#map")
        box.border_title = f"Map · floor {state.floor}/{state.floors_total}"
        seen = sum(r.visited for r in state.rooms if not r.secret)
        box.border_subtitle = f"{seen} of {sum(not r.secret for r in state.rooms)} seen · F5 in full"

    def hover_room(self, line: StoryLine, room: int | None) -> None:
        """The mouse has come to a room on the map you can get back to (or left it): it's lit, or not."""
        if line.id == "map-art" and room != self.map_hover:
            self.map_hover = room
            self.draw_map()

    def draw_here(self) -> None:
        """Who and what is here, in sections, a heading each: who's here, the things (a picture each, its words and
        its verbs beside it), what there is to search (a line each); then the journal's last lines (Lately) in the
        rows they leave. Their verbs are numbered on from the big buttons. A section too tall for its rows draws its
        things smaller (a line each), the things before the people; more than fit, a page of them and a chip saying
        how many more. In a fight the foe's verbs are the buttons, so its card has none, and it's big, with you shown
        against it and how the last turn went under it; whoever else is here, a line each. The things are drawn again
        only when they change; Lately, in place, as the journal grows."""
        state, content, grid = self.game.state, self.game.content, self.grid
        things = things_here(state, content)
        fight = self.fighting()
        for thing in things:  # (a spent chest is a line, not a picture as big as the loot it gave)
            if thing.id.startswith("fixture:") and thing.status == "spent":
                thing.art, thing.name = False, f"{thing.name} · spent"
        if state.scene or state.over:
            for thing in things:
                thing.verbs = []
        foe = next((t for t in things if t.kind == "monster" and t.style == FOE), None) if fight else None
        if foe is not None:
            foe.verbs = []
        others = [t for t in things if t is not foe]
        sections = [("Who's here", [t for t in others if t.character]),
                    ("Things", [t for t in others if not t.character and t.art]),
                    ("To search", [t for t in others if not t.character and not t.art])]
        if foe is not None:
            sections = [("Also here", others)]
        numbers: dict[str, int] = {}
        for _, group in sections:
            for thing in group:
                for action in thing.verbs:
                    if action.id and action.id not in numbers:
                        numbers[action.id] = FIRST_VERB + len(numbers)
        ordered = [t for _, group in sections for t in group]
        self.things = things
        self.tile_verbs = self._ordered(ordered, numbers)
        self.verb_owner = {a.id: thing.name for thing in things for a in thing.verbs if a.id}
        player = state.player
        box = self.query_one("#here", Vertical)
        box.border_title = f"Here · {state.room.name}"
        box.set_class(fight, "fight")
        width, rows = grid.side - 5, grid.band - grid.strip - 2
        shown = (grid, state.floor, state.room_id, fight,  # (the foe's own state is shown in place: see below)
                 tuple((t.id, *(() if t is foe else (t.status, t.pose)), tuple((a.id, a.label) for a in t.verbs))
                       for t in things),
                 self.here_page, self._sprites_on())
        if shown != self.here_drawn:
            self.here_drawn = shown
            out, self.here_used = self.here_things(foe, sections, numbers, width, rows)
            self.swap(self.query_one("#here-things"), out)
        last = 0
        if foe is not None and self.here_you is not None:  # (your hearts, the foe's own state and the last turn, shown
            # in place: its card stays put through the fight, hits and lunges and all)
            self.duel[0].set_pose(foe.pose)
            self.duel[1].update(facts(state, content, foe))
            you = Text("You  ", style="bold #e8e8f4")
            you.append_text(hearts(player.hp, player.max_hp))
            you.append(f" {player.hp}/{player.max_hp}", style="bold")
            self.here_you.update(you)
            rolls = self.last_rolls[-3:]
            words = Text("\n").join([rule("Last turn", width, FOE)] + [roll_headline(e) for e in rolls])
            self.here_last.display = bool(rolls)
            self.here_last.styles.height = 1 + len(rolls)
            self.here_last.update(words)
            last = (2 + len(rolls)) if rolls else 0
        self.draw_lately(width, min(LATELY_MOST, rows - self.here_used - last - 1))

    def here_things(self, foe, sections: list, numbers: dict[str, int], width: int,
                    rows: int) -> tuple[list[Widget], int]:
        """Here's things as widgets (see draw_here), and the rows they take."""
        state, content = self.game.state, self.game.content
        out: list[Widget] = []
        self.here_you = self.here_last = None
        if foe is not None:  # you against it: your hearts here, beside its picture, not only at the top of the screen
            self.here_you = Static(classes="here-you")
            out.append(self.here_you)
            # Its card, big: its picture (where the fight's hits, lunges and dissolve play) and beside it all you know
            # of it, weaknesses and all; under it, how the last turn went, a line a roll (both shown by draw_here).
            art = DEFAULT_WIDTH if width >= 50 else SMALL
            picture = Picture(foe.sprite, "monster", art, pose=foe.pose, action=f"screen.lookup('monster:{foe.sprite}')",
                              content=content, classes="here-art duel-art")
            self.duel = (picture, Static(facts(state, content, foe), classes="duel-words"))
            out.append(Horizontal(*self.duel, classes="duel"))
            self.here_last = Static(classes="here-last")
            out.append(self.here_last)
            rows -= 1 + art // 2 + 2
        forms = {"Who's here": ROW, "Things": ROW, "To search": CHIP, "Also here": CHIP}

        def tall(name: str, group: list) -> int:
            return 1 + sum(measure(t, forms[name] if t.art else CHIP, width, False, content)[1] for t in group)

        def total() -> int:
            return sum(tall(name, group) for name, group in sections if group)

        for name in ("Things", "Who's here"):  # (too tall: the things a line each, then the people)
            if total() > rows:
                forms[name] = CHIP
        hidden = 0
        if total() > rows:  # (still too tall: a page of them, and a chip saying how many more)
            everyone = [t for _, group in sections for t in group]
            start = (self.here_page * max(1, len(everyone) // 2)) % max(1, len(everyone))
            kept = everyone[start:] + everyone[:start]
            while kept and sum(tall(name, [t for t in kept if t in group]) for name, group in sections
                               if any(t in group for t in kept)) > rows - 1:
                kept.pop()
            hidden = len(everyone) - len(kept)
            sections = [(name, [t for t in group if t in kept]) for name, group in sections]
        used = 0
        for name, group in sections:
            if not group:
                continue
            out.append(Static(rule(name, width), classes="here-head"))
            for thing in group:
                form = forms[name] if thing.art else CHIP
                size = measure(thing, form, width, False, content)
                tile = Tile(thing, form, (width if form == ROW else size[0], size[1]), numbers, content, False,
                            animate=True)
                tile.tooltip = facts(state, content, thing)  # (hover: all about it)
                out.append(Horizontal(tile, classes="here-line"))
            used += tall(name, group)
        if hidden:
            out.append(Clickable(Text(f" +{hidden} more ▸ ", style=f"reverse {ACCENT}"), "screen.more_here()",
                                 classes="more"))
            used += 1
        if not any(group for _, group in sections) and foe is None:
            out.append(Static(Text("Nothing here to take or talk to.", style=DIM), classes="here-empty"))
            used += 2
        taken = (self.grid.band - self.grid.strip - 2) - rows + used  # (the foe's card and the last turn, too)
        return out, taken

    def draw_lately(self, width: int, rows: int) -> None:
        """The journal's last lines at the foot of Here (what you did, and what came of it: not the dice), newest
        last, as many as fit in `rows` wrapped `width` wide; hidden if fewer than LATELY_LEAST rows would show. Shown
        in place, so nothing above it is drawn again as the journal grows."""
        journal = self.game.state.journal
        shown = (width, rows, tuple(journal[-LATELY_MOST:]))
        if shown == self.lately_drawn:
            return
        self.lately_drawn = shown
        box, line = self.query_one("#here-lately"), self.query_one("#lately", StoryLine)
        lines, used = [], 0
        for entry in reversed(journal) if rows >= LATELY_LEAST else []:
            if entry.startswith("⚄ "):
                continue
            tall = len(textwrap.wrap("· " + entry, width)) or 1
            if used + tall > rows:
                break
            lines.insert(0, entry)
            used += tall
        box.display = bool(lines)
        if not lines:
            return
        lexicon = self.lexicon()
        text = Text()
        for i, entry in enumerate(lines):
            text.append("· ", style=FAINT)
            text.append_text(highlight(entry, lexicon, WORDS if i == len(lines) - 1 else DIM))
            text.append("\n")
        text.rstrip()
        self.query_one("#lately-head", Static).update(rule("Lately", width))
        line.styles.height = used
        line.update(text)

    def draw_strip(self) -> None:
        """The panels' buttons at the foot of the right column: a row of six, or two of three on a narrow screen, each
        its key in its frame."""
        strip = self.query_one("#strip", Vertical)
        strip.remove_children()
        per_row = 6 if self.grid.strip == 3 else 3
        rows = []
        for start in range(0, len(PANELS), per_row):
            buttons = []
            for name, word, key in PANELS[start:start + per_row]:
                button = Clickable(Text(word, style="bold #c8c8e0"), f"screen.panel('{name}')", classes="panel-button")
                button.border_title = key
                buttons.append(button)
            rows.append(Horizontal(*buttons, classes="panel-row"))
        strip.mount_all(rows)

    # --- the decision ---

    def fighting(self) -> bool:
        state = self.game.state
        return state.in_combat and not state.scene and not state.over

    def refresh_choices(self) -> None:
        """The six big buttons (a fight's, or the room's), the compass, your things or the options a button's opened,
        and the choices left; in a scene, its choices fill the box instead. Each part drawn again only when what it
        shows changes, the buttons and the compass's cells in place: a part torn down and built again flashes off and
        on, and swaps what's under the mouse."""
        game, grid = self.game, self.grid
        state, content = game.state, game.content
        if grid is None:
            return
        scene = game.story.scene_title(state)
        fight = self.fighting()
        bar = FIGHT if fight else EXPLORE
        choices = self._choices()
        on_tiles = {a.id for a in self.tile_verbs}
        groups: dict[str, list[Action]] = {kind: [] for kind, _, _ in bar}
        rest: list[Action] = []
        for action in choices:
            kind = "" if scene else kind_of(action, content, fight)
            if kind in groups:
                groups[kind].append(action)
            elif action.id not in on_tiles and (scene or not action.id.startswith("go:")):
                rest.append(action)
        if not scene:
            groups["use"] += self.more_uses(fight, groups, {a.id for a in choices})
        if self.tray and self.tray[2] and not groups.get(self.tray[2]):  # (its button has nothing left: it closes)
            self.tray = None
        decide = self.query_one("#decide")
        decide.border_title = f"✧ {scene}" if scene else "⚔ What do you do?" if fight else "What do you do?"
        decide.set_class(fight, "fight")
        decide.set_class(bool(scene), "scene")
        self.groups = groups
        self.slots = {FIRST_VERB + i: ("action", a) for i, a in enumerate(self.tile_verbs)}
        quiet = bool(scene) or state.over
        self.query_one("#top-row").display = not quiet
        if not quiet:
            self.draw_bar(bar, groups, fight)
        compass = self.query_one("#compass")
        compass.display = not quiet and (not grid.beside or not (fight or self.tray))
        if compass.display:
            self.draw_compass(fight)
        first = 1 if scene else FIRST_VERB + len(self.tile_verbs)
        for number, action in enumerate(rest, first):
            self.slots[number] = ("action", action)
        width = (self.size.width - grid.side - grid.story_w - 4) if grid.beside else grid.left - 4
        suggesting = game.suggestion_pending()
        chips_shown = (tuple((a.id, a.label, a.hint) for a in rest), first, suggesting)

        def chips() -> list[Widget]:
            out = []
            for number, action in enumerate(rest, first):
                colour = PINK if action.id == "suggest" or action.label.startswith("✦") else ACCENT
                text = chip(str(number), action.label, colour, action.hint)
                if text.cell_len + 2 > width:  # (one longer than the box: cut short, never cut off)
                    text.truncate(max(8, width - 2), overflow="ellipsis")
                button = Clickable(text, f"screen.slot({number})", classes="choice-chip")
                button.tooltip = action.label
                out.append((button, text.cell_len + 2))
            if suggesting:
                text = Text(f" {first + len(rest)}  ✦ …", style=f"italic {DIM}")
                out.append((Static(text, classes="choice-chip"), text.cell_len + 2))
            return wrapped(out, width)

        below = self.query_one("#below", VerticalScroll)
        picks = self.query_one("#picks", VerticalScroll)
        picks.display = grid.beside and not quiet
        if grid.beside:
            below.styles.height = "1fr"
        else:  # (the box keeps its height: a scene's choices take the buttons' rows too)
            below.styles.height = BELOW[grid.tall] + (grid.bar if quiet else 0)
        if state.over:
            self.offered = []
            shown, build = ("over",), lambda: [Static(Text("Press Enter to see your fate.", style=ACCENT))]
        elif scene:  # (its choices big, a wide button each, filling the box)
            self.offered = []
            shown = ("scene", chips_shown)

            # (a framed button each where they all fit, else a line each: the second was cut in half at 120x40)
            room = below.styles.height.value if not grid.beside and below.styles.height else grid.decide - 2
            framed = 4 * len(rest) <= room

            def build() -> list[Widget]:
                return [Clickable(Text.assemble((f" {n} ", f"bold #10122a on {ACCENT}"), ("  " + a.label, "bold")),
                                  f"screen.slot({n})", classes="scene-choice" if framed else "scene-choice tight")
                        for n, a in enumerate(rest, first)]
        elif grid.beside:
            shown, build = self.things_under(width, fight, groups)
        else:
            self.offered = self.tray[1] if self.tray else []
            shown = ("under", self.tray and (self.tray[0], tuple(a.id for a in self.tray[1])), chips_shown)

            def build() -> list[Widget]:
                return (self.tray_lines(width) if self.tray else []) + chips()
        if shown != self.below_drawn:
            self.below_drawn = shown
            self.swap(below, build())
        if grid.beside and not quiet and chips_shown != self.picks_drawn:
            self.picks_drawn = chips_shown
            lines = chips()  # (more than PICKS lines of them: they take rows from your things, and scroll past that)
            picks.styles.height = max(PICKS, min(PICKS_MOST, len(lines)))
            self.swap(picks, lines)

    def things_under(self, width: int, fight: bool, groups: dict[str, list[Action]]) -> tuple[tuple, Callable]:
        """Under the buttons (beside the story): the options a button (or a thing's picker) has opened, or else your
        things, all that Heal, Throw (in a fight), Use and Gear would use, a card each with its picture, what it would
        do and how it would go, a letter each, then what you carry that has no use now, dim, and why; a line each if
        there's room for only one card; a page of them if they're more than fit. What it would show, and how to build
        it (so it's built only if that's changed)."""
        state, content, grid = self.game.state, self.game.content, self.grid
        player = state.player
        if self.tray:
            title, options, kind = self.tray
        else:
            title, kind, options = "Your things", "", []
            for group in ("heal", "throw", "use", "gear") if fight else ("heal", "use", "gear"):
                options += [a for a in groups.get(group, []) if a.id not in {o.id for o in options}]
        self.offered = options
        kinds = {a.id: (kind or next((k for k, group in groups.items() if a in group), "use")) for a in options}
        # Then (your things, not an open button's) what you carry that there's nothing to do with now, dim, and why.
        used = {item_key(a, content) for a in options}
        idle = [] if self.tray else [key for key in dict.fromkeys(player.inventory) if key not in used]
        compass = 0 if fight or self.tray else grid.ways + 1
        rows = grid.decide - 2 - COMMAND - (2 * grid.bar + 1) - compass - 1 - PICKS - 1  # (less the heading)
        per_row = 2 if width >= 2 * CARD[0] + 1 else 1
        entries: list[Action | str] = [*options, *idle]  # (an option, or a thing with nothing to do with it now)
        cards = rows // (CARD[1] + 1) * per_row if rows >= CARD[1] else 0
        if cards < min(2, len(entries)):  # (room for one card only, and more to show: a line each)
            cards = 0
        fits = cards or rows
        page = entries
        if len(entries) > fits:
            per_page = max(1, fits - (0 if cards else 1))
            start = (self.item_page * per_page) % len(entries)
            page = (entries[start:] + entries[:start])[:per_page]
        foe = state.room.monster if fight else None
        weak_to = content.monster(foe.key).weak if foe else []
        counts = player.inventory
        reasons = {key: self.why_idle(key, fight) for key in idle}
        shown = ("things", title, kind, bool(self.tray), cards, per_row, width, len(entries) - len(page),
                 tuple((e, counts.count(e), reasons[e]) if isinstance(e, str) else
                       (e.id, e.label, e.hint, kinds[e.id], counts.count(item_key(e, content))) for e in page),
                 tuple(weak_to))

        def build() -> list[Widget]:
            controls: list[Widget] = []
            if len(entries) > len(page):
                more = Text(f" +{len(entries) - len(page)} more ▸ ", style=f"reverse {ACCENT}")
                controls.append(Clickable(more, "screen.more_things()", classes="items-more"))
            if self.tray:
                controls.append(Clickable(Text(" ✕ close", style=DIM), "screen.close_tray()", classes="items-close"))
            taken = sum(len(str(c.render())) + 1 for c in controls)
            head = Horizontal(Static(rule(title + (" · pick one" if self.tray else ""), width - taken,
                                          COLOUR.get(kind, GOLD) if self.tray else DIM), classes="items-title"),
                              *controls, classes="items-head")
            out: list[Widget] = [head]
            if not entries:
                words = "Nothing to use on it: try something of your own." if fight else "Your pack is empty."
                out.append(Static(Text(words, style=DIM), classes="items-none"))
                return out
            sprites = self._sprites_on()
            card_w = (width - 1) // 2 if per_row == 2 else 0
            if cards:
                row: list[Widget] = []
                for entry in page:
                    if isinstance(entry, str):
                        card = ItemCard(0, None, "", entry, content, sprites, counts.count(entry), reasons[entry],
                                        width=card_w)
                    else:
                        key = item_key(entry, content)
                        weak = [t for t in content.item(key).tags if t in weak_to] if key and kinds[entry.id] in (
                            "throw", "use") else []
                        card = ItemCard(options.index(entry), entry, kinds[entry.id], key, content, sprites,
                                        counts.count(key) if key else 0, weak=weak, width=card_w)
                    row.append(card)
                    if len(row) == per_row:
                        out.append(Horizontal(*row, classes="card-row"))
                        row = []
                if row:
                    out.append(Horizontal(*row, classes="card-row"))
                return out
            for entry in page:
                if isinstance(entry, str):
                    text = Text.assemble(("     " + content.item(entry).name, f"bold {DIM}"),
                                         (f"  {reasons[entry]}", "#4a4e7a"))
                    out.append(Horizontal(Static(text, classes="choice-chip"), classes="chip-line"))
                    continue
                index = options.index(entry)
                colour = COLOUR.get(kinds[entry.id], GOLD)
                key = item_key(entry, content)
                verb = entry.label.split(" ")[0]
                verb = verb if verb in VERBS else WORD.get(kinds[entry.id], "Use")
                text = chip(chr(97 + index), f"{verb} {short(entry)}", colour,
                            entry.hint or (item_note(content, key) if key else ""))
                out.append(Horizontal(Clickable(text, f"screen.pick({index})", classes="choice-chip"),
                                      classes="chip-line"))
            return out

        return shown, build

    def why_idle(self, key: str, fight: bool) -> str:
        """Why there's nothing to do with a thing you carry, now, in a word or two."""
        state, content = self.game.state, self.game.content
        item, player = content.item(key), state.player
        if item.kind == "consumable":
            if item.heal and player.hp >= player.max_hp:
                return "full HP"
            if item.escape and not fight:
                return "for a fight"
            return "nothing ails you" if item.cures else "not now"
        if item.kind == "key":
            return "it opens something"
        if item.kind in ("weapon", "armor"):
            return "not as good" if item.kind == "armor" or item.damage else "spare"
        return "use it on something"

    def action_more_things(self) -> None:
        self.item_page += 1
        self.refresh_choices()

    def draw_bar(self, bar: list, groups: dict[str, list[Action]], fight: bool) -> None:
        """The six big buttons, each in its look: open if its options are showing, urgent (Dodge, as a heavy blow
        comes; Heal, when you're low), unavailable with why, or as it is; with their icons, and notes, if there's room
        for them. Beside the story, two rows of three; under it, a row of six. Built afresh only for another set (a
        fight's, the room's) or another size; otherwise each shows its look in place."""
        grid, state = self.grid, self.game.state
        box = self.query_one("#bar", Vertical)
        if grid.beside:
            inside = (self.size.width - grid.side - grid.story_w - 4 - 2) // 3 - 2  # (inside a button's frame)
            rows = [bar[:3], bar[3:]]
        else:
            compass = 3 * grid.cell + 2 + 1  # (and its margin)
            inside = (grid.left - 4 - compass) // 6 - 1 - 2
            rows = [bar]
        wide = inside >= 9
        pictured = grid.tall and wide and self._sprites_on() and Image is not None  # (ASCII art chosen: words only)
        built = (grid, tuple(kind for kind, _, _ in bar), pictured)
        if built != self.bar_built:
            self.bar_built = built
            numbers = {kind: number for number, (kind, _, _) in enumerate(bar, 1)}
            self.buttons = {kind: BigButton(kind, numbers[kind], grid.tall, pictured) for kind, _, _ in bar}
            lines = []
            for r, row in enumerate(rows):
                line = Horizontal(*[self.buttons[kind] for kind, _, _ in row], classes="bar-row")
                line.styles.height = grid.bar
                line.styles.margin = (1 if r else 0, 0, 0, 0)
                lines.append(line)
            box.styles.height = len(rows) * grid.bar + len(rows) - 1
            self.swap(box, lines)
        for number, (kind, _, _) in enumerate(bar, 1):
            live, note = self.button_state(kind, groups[kind], fight)
            low = kind == "heal" and state.player.hp * 3 <= state.player.max_hp  # (a third of your HP, or less)
            hot = live and (kind == "dodge" and fight and state.room.monster.intent == "heavy" or low)
            opened = bool(self.tray and self.tray[2] == kind)
            look = "dead" if not live else "open" if opened else "hot" if hot else "live"
            note = ("low HP!" if low else "now!") if hot and not opened else "▾ open" if opened else note
            note = note if len(note) <= inside - 2 else note[:inside - 3] + "…"  # (as much as its frame has room for)
            self.buttons[kind].show(look, note, wide)
            self.slots[number] = ("bar", kind)

    def draw_compass(self, fight: bool) -> None:
        """The ways out as a compass, five cells that never move or change size, whatever the room: north, west, you,
        east and south. A way out says where it goes and, on a second line if there's room, what's there (a foe in
        red, a chest, that it's been searched); one through a locked door says so; a wall is faint. You in the middle
        (click: look around). In a fight they're dim: the way out is Flee. Beside the story, under the buttons with a
        heading; under it, beside them. The cells are built once for the screen's size, then shown in place."""
        grid, state = self.grid, self.game.state
        box = self.query_one("#compass", Vertical)
        cw = grid.cell
        lines_per = 2 if grid.beside and grid.ways >= 7 else 1
        if self.compass_built != grid:
            self.compass_built = grid
            gaps = (0, 0, 0)
            if grid.beside:
                box.styles.height, box.styles.width = grid.ways, "100%"
                heights = (lines_per,) * 3
                gaps = (0, 1, 1) if grid.ways >= 9 else gaps
            else:
                box.styles.height, box.styles.width = grid.bar, 3 * cw + 2
                heights = (2, 3, 2) if grid.tall else (1, 1, 1)
            self.cells = {name: CompassCell() for name in ("north", "west", "middle", "east", "south")}
            layout = [[None, "north", None], ["west", "middle", "east"], [None, "south", None]]
            lines: list[Widget] = []
            if grid.beside:
                lines.append(Static(rule("Ways", self.size.width - grid.side - grid.story_w - 4), classes="ways-head"))
            for names, h, gap in zip(layout, heights, gaps):
                cells = [self.cells[name] if name else Static("", classes="compass-cell blank") for name in names]
                for i, cell in enumerate(cells):
                    cell.styles.width, cell.styles.height = cw, h
                    cell.styles.margin = (0, 1 if i < 2 else 0, 0, 0)
                line = Horizontal(*cells, classes="compass-row")
                line.styles.margin = (gap, 0, 0, 0)
                lines.append(line)
            self.swap(box, lines)

        def cut(words: str, room: int) -> str:
            return words if len(words) <= room else words[:room - 1] + "…"

        for direction in ("north", "west", "east", "south"):
            arrow = ARROWS[direction]
            if direction not in state.room.exits:
                words = ("wall ▶" if direction == "east" else f"{arrow} wall") if grid.named else "·"
                self.cells[direction].show(Text(words, style=FAINT, justify="center"), "wall")
                continue
            exit_ = state.room.exits[direction]
            there = state.rooms[exit_.to]
            name, colour = way_name(state, direction)
            note, note_colour = "", DIM
            if exit_.webbed:
                note = "only fire gets through"
            elif exit_.locked:
                name, note = "locked", name.partition(": ")[2] or "a key, or bombs"
            elif there.visited:
                note, note_colour = (room_notes(state, there) or [("", DIM)])[0]
            elif name != "unexplored":
                note = "unexplored"
            if fight:
                colour = note_colour = "#3a3f66"
            tip = f"{direction}: {name}" + (f" ({note})" if note else "")
            if not grid.named:  # (no room for where it goes: the arrow, lit)
                name = ""
            first = cut((f"{name} {arrow}" if direction == "east" else f"{arrow} {name}").strip(), cw - 1)
            text = Text(first, style=f"bold {colour}", justify="center")
            if lines_per > 1:
                text.append("\n" + cut(note, cw - 1), style=note_colour)
            self.cells[direction].show(text, "way", f"screen.go('{direction}')", tip)
        middle = Text(("✕ fight" if fight else "@ you") if cw >= 9 else "✕" if fight else "@",
                      style=f"bold {FOE if fight else ACCENT}", justify="center")
        if lines_per > 1:
            middle.append("\nflee: 6" if fight else "\nlook · F4", style=DIM)
        self.cells["middle"].show(middle, "middle", "screen.panel('look')", "Look around (F4)")

    def more_uses(self, fight: bool, groups: dict[str, list[Action]], listed: set[str]) -> list[Action]:
        """What Use offers beyond the game's own choices: in a fight, what the foe's "Use…" would (the things you could
        use on it, bar what Throw has already); out of one, the "Use an item…" picker's things (bar what Heal and Use
        have already). Never what won't work."""
        state, content = self.game.state, self.game.content
        if fight:
            foe = next((t for t in things_here(state, content) if t.kind == "monster" and t.style == FOE), None)
            pickers = [v.id for v in (foe.verbs if foe else []) if v.id.startswith("use:")]
            have = groups["throw"]
        else:
            pickers = [a.id for a in interactions.verbs(state, content, "self") if a.id.startswith("use:")]
            have = groups["heal"] + groups["use"]
        taken = {a.id.partition(":")[2].split("@")[0] or a.id for a in have}  # (the things: "bomb" is its own)
        options = []
        for picker in pickers:
            if interactions.is_picker(picker):
                options += [a for a in interactions.choices(state, content, picker)
                            if a.hint not in ("NO", "won't work") and a.id not in listed
                            and a.id.partition(":")[2].split("@")[0] not in taken
                            and not (fight and wasted(content, a.id))]
        return options

    def button_state(self, kind: str, group: list[Action], fight: bool) -> tuple[bool, str]:
        """Whether a big button can be used now, and its note: how many things it has, the one it'd use, what's
        urgent, or why not."""
        state, content = self.game.state, self.game.content
        player = state.player
        if group:
            if len(group) > 1:
                note = f"{len(group)} ▾"
            else:  # (the one thing it'd use, or what's urgent)
                note = group[0].hint or (short(group[0]) if kind in ("heal", "throw", "use", "gear") else "")
            return True, note
        if kind == "heal":
            healing = any(content.item(k).heal for k in player.inventory)
            return False, "full HP" if healing and player.hp >= player.max_hp else "none"
        if kind == "flee":
            return False, "tangled" if player.tangled else "no way"
        if kind == "bomb":
            return False, "no wall" if player.bombs else "no bombs"
        if kind in ("search", "rest"):
            reason = why_not(state, content, "search_room" if kind == "search" else "rest")
            return False, next((note for words, note in WHY_NOT if words in reason), "not now")
        if kind == "gear":
            return False, "all set"
        return False, "none"

    def tray_lines(self, width: int) -> list[Widget]:
        """The open options, under the story (no room for cards): its title, its options a letter each (what each
        would do after it), and a ✕ to close it."""
        title, options, kind = self.tray
        colour = COLOUR.get(kind, GOLD)
        head = Text(f"{title}:", style=f"bold {colour}")
        chips: list[tuple[Widget, int]] = [(Static(head, classes="tray-head"), head.cell_len + 1)]
        for i, action in enumerate(options):
            text = chip(chr(97 + i), short(action), colour, action.hint)
            chips.append((Clickable(text, f"screen.pick({i})", classes="choice-chip"), text.cell_len + 2))
        chips.append((Clickable(Text(" ✕ close", style=DIM), "screen.close_tray()", classes="choice-chip"), 9))
        return wrapped(chips, width)

    # --- what a press does ---

    def action_bar(self, kind: str) -> None:
        """A big button: one thing to do it with, it's done (bar Bomb, which shows which wall first); more, their
        options show (or hide again, if they're showing). Mid-turn, once the turn's done (GameScreen.later)."""
        if self.busy:
            self.later(lambda: self.action_bar(kind))
            return
        group = self.groups.get(kind, [])
        if not group:
            self.notify(f"{WORD[kind]}: {self.button_state(kind, group, self.fighting())[1]}", timeout=2)
            return
        if len(group) == 1 and kind not in CONFIRM:
            self.close_tray(redraw=False)
            self.press(group[0])
            return
        self.tray = None if self.tray and self.tray[2] == kind else (WORD[kind], group, kind)
        self.item_page = 0
        self.refresh_choices()

    def action_slot(self, number: int) -> None:
        """A choice's button, or a number typed."""
        what, value = self.slots.get(number, ("", None))
        if what == "bar":
            self.action_bar(value)
        elif what == "action":
            self.press(value)
        self.query_one("#command", Input).focus()

    def press(self, action: Action) -> None:
        """A choice: a picker (Give…) shows its options under the buttons, as a button's do, instead of a window; the
        idea and a scene's choices go by their number in the game's list; anything else is a turn, as GameScreen
        presses it (a tile's button says what it was done to: "Search · pew")."""
        if self.busy:
            self.later(lambda: self.press(action))
            return
        state = self.game.state
        if state.over or not action.id:
            return
        if interactions.is_picker(action.id):
            options = interactions.choices(state, self.game.content, action.id)
            owner = self.verb_owner.get(action.id)
            title = action.label.removesuffix("…") + (f" · {owner}" if owner else "")
            self.tray = None if self.tray and self.tray[0] == title else (title, options, "")
            self.item_page = 0
            self.refresh_choices()
            return
        self.close_tray(redraw=False)
        if state.scene or action.id == "suggest":
            index = next((i for i, a in enumerate(self._choices(), 1) if a.id == action.id), None)
            if index:
                self.run_turn(str(index))
            return
        super().press(action)

    def action_pick(self, index: int) -> None:
        """One of the options under the buttons (yours, or the open ones), by its letter: a picker's, told as the whole
        use it is (told)."""
        if 0 <= index < len(self.offered):
            option = self.offered[index]
            picked = (self.tray and not self.tray[2]) or "@" in option.id
            self.press(self.told(option) if picked else option)
        self.query_one("#command", Input).focus()

    def action_close_tray(self) -> None:
        self.close_tray()

    def close_tray(self, redraw: bool = True) -> None:
        if self.tray is not None:
            self.tray = None
            self.item_page = 0
            if redraw:
                self.refresh_choices()

    def take_input(self, text: str) -> None:
        """What was typed: a letter for one of the options under the buttons, a number for a button, else as ever."""
        if self.busy or self.game.state.over:
            return super().take_input(text)
        if self.offered and len(text) == 1 and text.isalpha():
            self.action_pick(ord(text.lower()) - 97)
            return
        if text.isdigit() and int(text) in self.slots and not self.game.state.scene:
            self.action_slot(int(text))
            return
        super().take_input(text)

