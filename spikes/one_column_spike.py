"""Spike: a fixed screen of play, its verbs as big buttons in a fight and out of one, and a map worth opening.

The 2026-10-27 design pass. Round one put the whole turn in one column (the picture, the story, the decision) and a
fight's verbs on six big buttons. Round two fixed the grid: every box sized from the screen, never from what's in
it, lined up with the box beside it; Here with the things' pictures and their verbs on them; buttons out of a fight
too. Round three (this):

    the map         top right, where games keep it, beside the picture: both say where you are. As tall as the
                    picture, so the top row is one band. Each room a box with its name in it and its mark (you, the
                    stairs, a foe...), joined by passages, doors marked where they leave a room; the floor's goal and
                    quests under it. Hover a room; click one you can get back to, to go there.
    the compass     the ways out, beside the six big buttons: moving is what you do most out of a fight, so it's with
                    the other things you do, not across the screen under the map. Each arrow says where it goes; the
                    arrow keys work too.
    Here            the rest of the right column, beside the story and the decision: room for the things' pictures
                    and their verbs, close to the buttons. In a fight, the foe's card, big, with all you know of it.
    the panels      a strip at the foot of the right column: Pack, Sheet, Map, Journal, Bestiary, Help
    the buttons     one look for each state, the whole button: as it is, hovered (a tint of its own colour), urgent
                    (Dodge as a heavy blow comes: lit and framed heavy), open (its row showing under the buttons),
                    unavailable (faded, its reason under it). Sized to the window: icons when there's room, their
                    notes when they're wide enough, the compass's room names when the screen is.
    the full map    (the Map button, or F5) the floor as a chart, the whole screen: its name across the top, every
                    room's whole name, the goal, the quests, the tips and the key under it, all centred

It's GameScreen underneath (the turns, the dice, the story, the panels F1-F7): only the layout, the decision and the
map panel are new. Run it like the game (your own profile and config), or in a test room with a foe next door (walk
in to fight it), which counts for nothing:

    uv run python spikes/one_column_spike.py
    uv run python spikes/one_column_spike.py --fight goblin_stewmancer
    uv run python spikes/one_column_spike.py --fight serpentis --floor 4
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PIL import Image  # noqa: E402
from rich.style import Style  # noqa: E402
from rich.text import Text  # noqa: E402
from textual.app import ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.containers import Horizontal, Vertical, VerticalScroll  # noqa: E402
from textual.widget import Widget  # noqa: E402
from textual.widgets import Footer, Input, Static  # noqa: E402

from ptg import interactions, npcs, sprites  # noqa: E402
from ptg.config import load_config  # noqa: E402
from ptg.events import Action  # noqa: E402
from ptg.room_picture import look_of  # noqa: E402
from ptg.rules import journey, why_not  # noqa: E402
from ptg.sprites import DEFAULT_WIDTH, SMALL  # noqa: E402
from ptg.ui import app as app_module, tabs  # noqa: E402
from ptg.ui.app import PTGApp  # noqa: E402
from ptg.ui.game_screen import GameScreen  # noqa: E402
from ptg.ui.here import CARD, MINI, ROW, Tile, arrange, things_here  # noqa: E402
from ptg.ui.panels import Panel, floor_name  # noqa: E402
from ptg.ui.plan import Plan  # noqa: E402
from ptg.ui.tabs import TabsScreen, big_map, facts, known_rooms, map_notes, small_map, steps_to  # noqa: E402
from ptg.ui.theme import MAP_STYLES  # noqa: E402
from ptg.ui.widgets import ARROWS, Clickable, ClickableBox, DPad, Hud, Picture, StoryLine, hearts  # noqa: E402
from ptg.world import map_glyph  # noqa: E402

SIDE_SHARE, SIDE_MIN, SIDE_MAX = 0.31, 40, 64  # the right column's width: a share of the screen, within bounds
STAGE_SHARE = 0.36  # of the rows: the most the room's picture takes
STAGE_SHAPE = 4.8  # columns per row the picture would like (see ui/plan.py); it's drawn the column's width anyway
TALL = 44  # rows from which the big buttons have their icons (else a row of short ones)
BELOW = {True: 5, False: 4}  # rows under the buttons for an open row and the choices left, tall screen or not
STORY_LEAST = 8
NAMED_COMPASS = 106  # columns inside the decision from which the compass says where each way goes
WORDS, DIM, FAINT, PINK, GOLD, ACCENT = "#c8c8e0", "#6c6f99", "#2a2d4a", "#ff4f9a", "#ffd166", "#ffb000"
GROUND = "#0b0c1a"  # the screen's own dark, that tints are mixed into

# The big buttons, in their fixed places: (kind, its word, its colour). Out of a fight the same places keep their
# colours where they can (Heal and Use where they always are; Bomb where Throw is, with its icon).
FIGHT = [("attack", "Attack", "#ff4b4b"), ("dodge", "Dodge", "#6c8cff"), ("heal", "Heal", "#4cff8a"),
         ("throw", "Throw", "#ff7b39"), ("use", "Use", GOLD), ("flee", "Flee", "#9a9cc0")]
EXPLORE = [("search", "Search", "#5fe3ff"), ("rest", "Rest", "#6c8cff"), ("heal", "Heal", "#4cff8a"),
           ("bomb", "Bomb", "#ff7b39"), ("use", "Use", GOLD), ("gear", "Gear", "#9a9cc0")]
COLOUR = {kind: colour for kind, _, colour in FIGHT + EXPLORE}
WORD = {kind: word for kind, word, _ in FIGHT + EXPLORE}
CONFIRM = ("bomb",)  # buttons that always open their row, even for one thing: a bomb's too dear to spend unseen
PANELS = [("inventory", "Pack", "F2"), ("character", "Sheet", "F3"), ("map", "Map", "F5"),
          ("journal", "Journal", "F7"), ("bestiary", "Bestiary", "F6"), ("help", "Help", "F1")]

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
    """`colour` mixed into the screen's dark: a button's own shade, for its background when hovered, urgent or open."""
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
    name = ("locked" + (": a shop" if there.shop else "")) if exit_.locked else there.name if there.visited \
        else (f"a {there.fixture}" if there.fixture and not there.fixture_used else "unexplored")
    colour = "#c05a6c" if exit_.locked else "#5fe3ff" if there.visited else GOLD if there.fixture else DIM
    return name, colour


# --- the chart: the floor, each room a box ---------------------------------------------------------------------------

FIXTURE_WORDS = {"stairs": "the stairs down", "shop": "a shop", "chest": "a chest", "shrine": "a shrine",
                 "fountain": "a fountain"}


def room_label(room) -> str:
    """A room's words on the chart: its name once you've been in, else what you know of it."""
    if room.visited:
        return room.name
    if room.secret:
        return "a secret room"
    if room.fixture and not room.fixture_used:
        return FIXTURE_WORDS.get(room.fixture, f"a {room.fixture}")
    return "unexplored"


def room_note(state, content, room) -> tuple[str, str]:
    """A room's second line on the full chart, and its colour: what's in it that matters (a foe, someone waiting, a
    tip, what's lying there, a fixture not yet used), or that it's been searched; nothing for a room you haven't
    been in."""
    if not room.visited:
        return ("a secret, they say" if room.told else "", GOLD)
    monster = room.monster
    if monster and monster.hp > 0:
        if monster.hostile:
            return (monster.name, "#ff4b4b")
        return (f"{monster.name}" + (" · waiting" if npcs.waiting(state, monster) else ""), PINK)
    if any(f.told and not f.searched for f in room.features):
        return ("something hidden", GOLD)
    if room.items:
        return (f"{len(room.items)} thing{'s' * (len(room.items) != 1)} lying here", ACCENT)
    if room.fixture and not room.fixture_used:
        return (FIXTURE_WORDS.get(room.fixture, room.fixture).removeprefix("a ").removeprefix("the "), PINK)
    if room.draft and not room.secret:
        return (f"a draft, {room.draft}", "#5fe3ff")
    if room.room_searched:
        return ("searched", DIM)
    return ("", DIM)


def chart(state, content, width: int, height: int, roomy: bool) -> Text | None:
    """The floor as a dungeon chart, at most `width` x `height`: each room a box with its mark and its name in it (as
    much of the name as the width allows), you in amber, the rooms you haven't been in dashed and dim, the secret one
    gold; passages between them where you know of them, a door's joint where one leaves a room, a locked one doubled
    in red. `roomy` (the full map): wider passages, and a second line in each box saying what's in it. Hover a room:
    where it is. Click one you can get back to: you travel there (rules.journey). None if even short names won't
    fit."""
    rooms = known_rooms(state)
    min_x, min_y = min(r.x for r in rooms), min(r.y for r in rooms)
    across, down = max(r.x for r in rooms) - min_x + 1, max(r.y for r in rooms) - min_y + 1
    labels = {r.id: room_label(r) for r in rooms}
    notes = {r.id: room_note(state, content, r) for r in rooms} if roomy else {}
    pad, gap_x, gap_y = (1, 6, 2) if roomy else (0, 2, 1)
    box_h = 4 if roomy else 3
    wanted = max([len(s) for s in labels.values()] + [len(n) - 2 for n, _ in notes.values()])
    name_w = min(wanted, (width - (across - 1) * gap_x) // across - 4 - 2 * pad)
    rows = down * (box_h + gap_y) - gap_y
    if name_w < (10 if roomy else 6) or rows > height:
        return None
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

    places = {}
    for room in rooms:
        left, top = (room.x - min_x) * (box_w + gap_x), (room.y - min_y) * (box_h + gap_y)
        places[room.id] = (left, top)
        here = room.id == state.room_id
        reachable = not here and journey(state, room.id) is not None
        label = labels[room.id]
        tip = Style(meta={"tip": label + (" (you're here)" if here else " (click to travel there)" if reachable else ""),
                          **({"@click": f"screen.travel({room.id})"} if reachable else {})})
        edge = Style.parse(f"bold {ACCENT}" if here else GOLD if room.secret else "#5a6cb8" if room.visited
                           else "#34395e") + tip
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
        name = label if len(label) <= name_w else label[:name_w - 1] + "…"
        write(top + 1, left + 1 + pad, glyph, Style.parse(f"bold {ACCENT}" if here else MAP_STYLES.get(glyph[0], DIM))
              + tip)
        write(top + 1, left + 3 + pad, name, Style.parse("bold #ffffff" if here else WORDS if room.visited
                                                         else f"italic {DIM}") + tip)
        if roomy and notes[room.id][0]:
            note, colour = notes[room.id]
            note = note if len(note) <= name_w + 2 else note[:name_w + 1] + "…"
            write(top + 2, left + 1 + pad, note, Style.parse(f"italic {colour}") + tip)
    for room in rooms:  # the passages, and a door's joint on each box they leave
        if not (room.visited or mapped):
            continue
        left, top = places[room.id]
        bottom, right, mid = top + box_h - 1, left + box_w - 1, left + box_w // 2
        for direction, exit_ in room.exits.items():
            if exit_.to not in places:
                continue
            style = locked if exit_.locked else passage
            if direction in ("east", "west"):
                put(top + 1, right if direction == "east" else left, "├" if direction == "east" else "┤", style)
                span = range(right + 1, right + 1 + gap_x) if direction == "east" else range(left - gap_x, left)
                for x in span:
                    put(top + 1, x, "═" if exit_.locked else "─", style)
            else:
                put(bottom if direction == "south" else top, mid, "┬" if direction == "south" else "┴", style)
                span = range(bottom + 1, bottom + 1 + gap_y) if direction == "south" else range(top - gap_y, top)
                for y in span:
                    put(y, mid, "║" if exit_.locked else "│", style)
    text = Text(no_wrap=True)
    for row in grid:
        for ch, style in row:
            text.append(ch, style=style)
        text.append("\n")
    text.rstrip()
    return text


def drawn_map(state, content, width: int, height: int, roomy: bool = False) -> Text:
    """The floor as big as it fits: the chart (roomy, if asked and there's room), else the marks with names under
    them, else the marks alone."""
    return ((roomy and chart(state, content, width, height, True)) or chart(state, content, width, height, False)
            or big_map(state, width, height) or small_map(state))


class MapPanel(Panel):
    """The floor in full, the whole screen: its name across the top, the chart with every room's whole name, and
    under it the goal, the quests, the tips and the key, all centred. Click a room you can get back to: you go."""

    panel_name = "map"

    def __init__(self, game) -> None:
        super().__init__()
        self.game = game

    def compose(self) -> ComposeResult:
        state, content = self.game.state, self.game.content
        theme = content.themes[state.theme]
        accent = look_of(state.theme).accent
        with Vertical(classes="panel-box map-panel") as box:
            box.border_title = f"✦ Map · floor {state.floor} of {state.floors_total}"
            seen = sum(r.visited for r in state.rooms if not r.secret)
            box.border_subtitle = (f"{seen} of {sum(not r.secret for r in state.rooms)} rooms seen · click a room "
                                   "you've been in to go there · Esc to close")
            box.styles.border = ("double", accent)
            box.styles.border_title_color = accent
            yield Static(Text(floor_name(theme.name, 999), style=f"bold {accent}"), classes="map-name")
            yield Static(Text(theme.goal if state.boss_floor else "Find the stairs down.", style=f"italic {DIM}"),
                         classes="map-goal")
            yield Static(classes="map-rule")
            with Vertical(classes="map-holder"):
                yield StoryLine(id="map-chart")
            yield Static(classes="map-rule")
            with Vertical(classes="notes-holder"):
                yield Static(map_notes(state, content), classes="map-notes")

    def fit(self) -> None:
        """The whole screen less a margin; the chart as big as the rows the notes leave."""
        width, height = self.app.size
        state = self.game.state
        box = self.box
        box.styles.width, box.styles.height = width - 6, height - 2
        inner = width - 6 - 6
        rule = Text("─" * (inner // 2 - 2) + " ✦ " + "─" * (inner // 2 - 2), style=FAINT)
        for line in self.query(".map-rule").results(Static):
            line.update(rule)
        notes = 6 + len(npcs.quest_log(state, self.game.content))
        self.query_one("#map-chart", StoryLine).update(drawn_map(state, self.game.content, inner,
                                                                height - 2 - 4 - 4 - notes, roomy=True))

    def action_travel(self, room_id: int) -> None:
        """A room clicked: back to the game, and there (as GameScreen.action_travel)."""
        name = self.game.state.rooms[room_id].name
        self.dismiss(Action(f"travel:{room_id}", f"Travel to {name}"))


# --- the screen -------------------------------------------------------------------------------------------------------

@dataclass
class Grid:
    """The screen shared out (see OneColumnScreen.relayout): every box's size, from the screen's alone."""
    side: int  # the right column, with its gutter
    left: int  # the left column
    stage: int  # the picture's rows, inside its frame (the map's box is as tall as the picture's)
    story: int  # the story's box, frame and all
    decide: int  # the decision's box, frame and all
    bar: int  # the big buttons' rows
    below: int  # the rows under them
    strip: int  # the panels' buttons, at the foot of the right column
    tall: bool
    named: bool  # whether the compass says where each way goes


class BigButton(Clickable):
    """One of the big buttons, in one of its looks (`look`): "live", "hot" (urgent), "open" (its row is showing) or
    "dead" (it can't be used now). Its number in its frame, its icon and word inside, its note under it."""

    def __init__(self, kind: str, number: int, look: str, note: str, tall: bool, wide: bool) -> None:
        colour = COLOUR[kind]
        live = look != "dead"
        text = Text(justify="center")
        if tall and wide:
            text.append_text(icon(kind, live))
            text.append("\n")
        text.append(WORD[kind], style=f"bold {colour}" if live else "#3a3f66")
        super().__init__(text, f"screen.bar('{kind}')", classes=f"big-button {look} k-{kind}")
        self.styles.border = ("heavy" if look in ("hot", "open") else "round", colour if live else "#23264a")
        self.styles.border_title_color = colour if live else "#3a3f66"
        self.styles.border_subtitle_color = colour if look == "hot" else DIM if live else "#3a3f66"
        if look in ("hot", "open"):
            self.styles.background = tint(colour, 0.2 if look == "hot" else 0.12)
        self.border_title = str(number)
        self.border_subtitle = (note if wide else "") or ""
        self.styles.height = 7 if tall else 3
        self.tooltip = f"{WORD[kind]}: {note}" if note else WORD[kind]


class OneColumnScreen(GameScreen):
    """The fixed screen of play (see the module's docstring)."""

    BINDINGS = [*GameScreen.BINDINGS,
                *[Binding(key, f"arrow('{way}')", show=False, priority=True)
                  for key, way in (("up", "north"), ("down", "south"), ("left", "west"), ("right", "east"))]]

    def __init__(self, game, fresh: bool) -> None:
        super().__init__(game, fresh)
        self.grid: Grid | None = None
        self.tray: tuple[str, str, list[Action], str] | None = None  # the open row: (where, its title, its
        # options, the big button whose it is or ""), where "bar" (under the buttons) or "here" (a thing's, in Here)
        self.slots: dict[int, tuple] = {}  # what typing each number does: ("bar", kind) or ("action", Action)
        self.groups: dict[str, list[Action]] = {}
        self.decide_shown: tuple | None = None
        self.here_drawn: tuple | None = None
        self.map_drawn: tuple | None = None

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
                yield VerticalScroll(id="story")
                with Vertical(id="decide"):
                    with Horizontal(id="top-row"):
                        yield Horizontal(id="bar")
                        yield Vertical(id="compass")
                    yield VerticalScroll(id="below")
                    yield Input(id="command", placeholder="Type a number, or anything you want to try…")
            with Vertical(id="side"):
                with Vertical(id="map"):
                    with Vertical(id="map-holder"):
                        yield StoryLine(id="map-art")
                    yield Static(id="map-notes")
                yield Vertical(id="here", classes="panel")
                yield Vertical(id="strip")
        with Vertical(id="shims"):  # (what GameScreen's turns look for, that this layout hasn't)
            yield Vertical(id="here-strip")
            yield Static(id="choices")
            yield Horizontal(id="ways")
            yield DPad(id="dpad")
        yield Footer()

    # --- the grid ---

    def relayout(self) -> None:
        """Share the screen out, from its size alone: the right column a share of the width; on the left the picture
        (as tall as its shape asks, to a share of the rows), the decision (a fixed height: the buttons and the rows
        under them) and the story the rest; on the right the map as tall as the picture (one band across the top),
        the panels' strip at the foot, and Here the rest."""
        if self._resize_timer is not None:
            self._resize_timer.stop()
            self._resize_timer = None
        width, height = self.size
        if not width:
            return
        rows = height - 2  # (less the status bar and the footer)
        side = max(SIDE_MIN, min(SIDE_MAX, round(width * SIDE_SHARE)))
        left = width - side
        tall = rows >= TALL
        bar, below = (7 if tall else 3), BELOW[tall]
        decide = 2 + bar + below + 1
        stage = max(6, min(round((left - 2) / STAGE_SHAPE), round(STAGE_SHARE * rows)))
        story = rows - (stage + 2) - decide
        if story < STORY_LEAST:
            stage = max(4, stage - (STORY_LEAST - story))
            story = rows - (stage + 2) - decide
        strip = 3 if side >= 54 else 6  # (one row of six, or two of three)
        grid = Grid(side, left, stage, story, decide, bar, below, strip, tall, left - 4 >= NAMED_COMPASS)
        if grid != self.grid:
            self.grid = grid
            self.here_drawn = self.decide_shown = self.map_drawn = None
            self.draw_strip()
        self.plan = Plan(width, height, True, False, False, side, stage, left - 2, below, 0, story + decide, story - 2)
        for box, h in (("#stage-box", stage + 2), ("#story", story), ("#decide", decide), ("#map", stage + 2),
                       ("#here", story + decide - strip), ("#strip", strip), ("#top-row", bar)):
            self.query_one(box).styles.height = h
        self.query_one("#side").styles.width = side
        self.query_one("#story").border_title = "✦ Story"
        self.refresh_hud()
        self.refresh_stage()
        self.refresh_here()
        self.refresh_choices()

    refresh_panels = relayout
    refresh_stage = TabsScreen.refresh_stage  # (its frame red in a fight, titled with the room)

    def refresh_ways(self) -> None:
        """(The ways out are the compass's.)"""

    def panel(self, name: str) -> Panel:
        """The panels F1-F7 open, the map in full this spike's own."""
        return MapPanel(self.game) if name == "map" else super().panel(name)

    # --- the right column ---

    def refresh_here(self) -> None:
        """The map, Here and the compass: each drawn again only if what it shows has changed."""
        self.draw_map()
        self.draw_here()

    def draw_map(self) -> None:
        """The floor as a chart in the map's box (as much of each name as fits), the goal and the quests under it."""
        state, content, grid = self.game.state, self.game.content, self.grid
        shown = (grid, state.floor, state.room_id, tuple((r.id, r.visited, r.fixture_used, map_glyph(state, r))
                                                         for r in state.rooms), state.mapped_floor)
        if shown == self.map_drawn:
            return
        self.map_drawn = shown
        width, rows = grid.side - 5, grid.stage
        quests = [(line, still) for _, line, still in npcs.quest_log(state, content) if still][:2]
        notes = 1 + len(quests)
        self.query_one("#map-art", StoryLine).update(drawn_map(state, content, width, rows - notes))
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
        for line, _ in quests:
            text.append("\n★ ", style=PINK)
            text.append(line, style=WORDS)
        notes_box = self.query_one("#map-notes", Static)
        notes_box.styles.height = notes
        notes_box.update(text)
        box = self.query_one("#map")
        box.border_title = f"Map · floor {state.floor}/{state.floors_total}"
        seen = sum(r.visited for r in state.rooms if not r.secret)
        box.border_subtitle = f"{seen} of {sum(not r.secret for r in state.rooms)} seen · F5 in full"

    def draw_here(self) -> None:
        """Who and what is here as tiles with their pictures, their verbs on them, numbered on from the big buttons
        (in a fight the foe's are the buttons, so its tile has none, and its card is big, with you shown against it).
        A thing's picker, open, is its row instead."""
        state, content, grid = self.game.state, self.game.content, self.grid
        things = things_here(state, content)
        fight = self.fighting()
        if state.scene or state.over:
            for thing in things:
                thing.verbs = []
        if fight:
            for thing in things:
                if thing.kind == "monster" and thing.style == "#ff4b4b":
                    thing.verbs = []
        numbers: dict[str, int] = {}
        for thing in things:
            for action in thing.verbs:
                if action.id and action.id not in numbers:
                    numbers[action.id] = 7 + len(numbers)
        self.things = things
        self.tile_verbs = self._ordered(things, numbers)
        self.verb_owner = {a.id: thing.name for thing in things for a in thing.verbs if a.id}
        player = state.player
        shown = (grid, state.floor, state.room_id, fight, player.hp, player.max_hp, tuple(player.statuses),
                 tuple((t.id, t.status, t.pose, tuple((a.id, a.label) for a in t.verbs)) for t in things),
                 self.here_page, self.tray if self.tray and self.tray[0] == "here" else None, self._sprites_on())
        if shown == self.here_drawn:
            return
        self.here_drawn = shown
        box = self.query_one("#here", Vertical)
        box.remove_children()
        box.border_title = f"Here · {len(things)}" if things else "Here"
        box.set_class(fight, "fight")
        width, rows = grid.side - 5, grid.story + grid.decide - grid.strip - 2
        out: list[Widget] = []
        if fight:  # you against it: your hearts here, beside its picture, not only at the top of the screen
            you = Text("You  ", style="bold #e8e8f4")
            you.append_text(hearts(player.hp, player.max_hp))
            you.append(f" {player.hp}/{player.max_hp}", style="bold")
            out.append(Static(you, classes="here-you"))
            rows -= 1
        foe = next((t for t in things if t.kind == "monster" and t.style == "#ff4b4b"), None) if fight else None
        if foe is not None and not (self.tray and self.tray[0] == "here"):
            # Its card, big: its picture (where the fight's hits, lunges and dissolve play) and beside it all you know
            # of it, weaknesses and all; whatever else is here, a line each under it.
            art = DEFAULT_WIDTH if width >= 50 else SMALL
            picture = Picture(foe.sprite, "monster", art, pose=foe.pose, action=f"screen.lookup('monster:{foe.sprite}')",
                              content=content, classes="here-art duel-art")
            out.append(Horizontal(picture, Static(facts(state, content, foe), classes="duel-words"), classes="duel"))
            rows -= art // 2 + 2
            things = [t for t in things if t is not foe]
        if self.tray and self.tray[0] == "here":
            out += self.tray_lines(width)
        elif not things:
            if foe is None:  # (an empty room says so, and what it's like)
                blurb = content.archetypes[state.room.archetype].blurb
                out.append(Static(Text.assemble(("Nothing here to take or talk to.\n\n", DIM),
                                                (blurb, f"italic {DIM}"))))
        else:
            forms = (ROW,) if foe is not None else (CARD, ROW) if width < 34 else (CARD, MINI, ROW)
            layout, hidden = arrange(things, width, rows, False, forms, content)
            if hidden:  # a page of them, and a chip saying how many more
                first, _ = arrange(things, width, rows - 1, False, forms, content)
                per_page = max(1, sum(map(len, first)))
                start = (self.here_page * per_page) % len(things)
                layout, _ = arrange(things[start:] + things[:start], width, rows - 1, False, forms, content)
                hidden = len(things) - sum(map(len, layout))
            for line in layout:
                tiles = []
                for thing, form, size in line:
                    tile = Tile(thing, form, size, numbers, content, False, animate=True)
                    tile.tooltip = facts(state, content, thing)  # (hover: all about it)
                    tiles.append(tile)
                out.append(Horizontal(*tiles, classes="here-line"))
            if hidden:
                out.append(Clickable(Text(f" +{hidden} more ▸ ", style=f"reverse {ACCENT}"), "screen.more_here()",
                                     classes="more"))
        box.mount_all(out)

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
        """The six big buttons (a fight's, or the room's) and the compass, the open row under them, and the choices
        left as buttons too; in a scene, its choices fill the box instead. Rebuilt only when something in it changes."""
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
        if self.tray and self.tray[3] and not groups.get(self.tray[3]):  # (its button has nothing left: it closes)
            self.tray = None
        suggesting = game.suggestion_pending()
        exits = tuple((d, way_name(state, d), e.locked) for d, e in sorted(state.room.exits.items()))
        shown = (grid, fight, scene, state.over, suggesting, self.tray and self.tray[0] == "bar" and self.tray[1:],
                 {k: [(a.id, a.label, a.hint) for a in v] for k, v in groups.items()},
                 [(a.id, a.label, a.hint) for a in rest], state.room.monster and state.room.monster.intent,
                 tuple(a.id for a in self.tile_verbs), exits)
        decide = self.query_one("#decide")
        decide.border_title = f"✧ {scene}" if scene else "⚔ What do you do?" if fight else "What do you do?"
        decide.set_class(fight, "fight")
        decide.set_class(bool(scene), "scene")
        if shown == self.decide_shown:
            return
        self.decide_shown = shown
        self.groups = groups
        self.slots = {7 + i: ("action", a) for i, a in enumerate(self.tile_verbs)}
        quiet = bool(scene) or state.over
        self.query_one("#top-row").display = not quiet
        below = self.query_one("#below", VerticalScroll)
        below.remove_children()
        below.styles.height = grid.below + (grid.bar if quiet else 0)  # (the box keeps its height: a scene's
        # choices take the buttons' rows too)
        if not quiet:
            self.draw_bar(bar, groups, fight)
            self.draw_compass(fight)
        width = grid.left - 4
        lines: list[Widget] = []
        if state.over:
            lines.append(Static(Text("Press Enter to see your fate.", style=ACCENT)))
        if self.tray and self.tray[0] == "bar":
            lines += self.tray_lines(width)
        first = 1 if scene else 7 + len(self.tile_verbs)
        chips = []
        for number, action in enumerate(rest, first):
            colour = PINK if action.id == "suggest" or action.label.startswith("✦") else ACCENT
            text = chip(str(number), action.label, colour, action.hint)
            chips.append((Clickable(text, f"screen.slot({number})", classes="choice-chip"), text.cell_len + 2))
            self.slots[number] = ("action", action)
        if suggesting:
            text = Text(f" {first + len(rest)}  ✦ …", style=f"italic {DIM}")
            chips.append((Static(text, classes="choice-chip"), text.cell_len + 2))
        lines += wrapped(chips, width)
        below.mount_all(lines)

    def draw_bar(self, bar: list, groups: dict[str, list[Action]], fight: bool) -> None:
        """The six big buttons, each in its look: open if its row's showing, urgent (Dodge, as a heavy blow comes),
        unavailable with why, or as it is; with their icons, and notes, if the window's wide enough for them."""
        grid, state = self.grid, self.game.state
        buttons = self.query_one("#bar", Horizontal)
        buttons.remove_children()
        compass = 3 * (13 if grid.named else 5) + 1
        wide = (grid.left - 4 - compass) // 6 - 1 >= 11
        out = []
        for number, (kind, _, _) in enumerate(bar, 1):
            live, note = self.button_state(kind, groups[kind], fight)
            hot = live and kind == "dodge" and state.room.monster.intent == "heavy"
            opened = bool(self.tray and self.tray[3] == kind)
            look = "dead" if not live else "open" if opened else "hot" if hot else "live"
            out.append(BigButton(kind, number, look, "now!" if hot else "▴ open" if opened else note, grid.tall, wide))
            self.slots[number] = ("bar", kind)
        buttons.mount_all(out)

    def draw_compass(self, fight: bool) -> None:
        """The ways out as a compass beside the buttons: an arrow where there's a door, lit by where it goes (the
        room's name, if you've been, on a wide screen); you in the middle (click: look around). In a fight they're dim:
        the way out is Flee."""
        grid, state = self.grid, self.game.state
        box = self.query_one("#compass", Vertical)
        box.remove_children()
        cell_w = 13 if grid.named else 5
        box.styles.width = 3 * cell_w + 1
        heights = (2, 3, 2) if grid.tall else (1, 1, 1)

        def way(direction: str) -> Widget:
            if direction not in state.room.exits:
                return Static(Text("·" if grid.tall else "", style=FAINT, justify="center"), classes="compass-cell")
            name, colour = way_name(state, direction)
            colour = "#3a3f66" if fight else colour
            arrow = (ARROWS[direction], f"bold {colour}")
            words = name if grid.named else ""
            if len(words) > cell_w - 3:
                words = words[:cell_w - 4] + "…"
            if direction == "east":
                text = Text.assemble((f"{words} " if words else "", colour), arrow, justify="center")
            else:
                gap = "\n" if direction in ("north", "south") and grid.tall else " "
                text = Text.assemble(arrow, (f"{gap}{words}" if words else "", colour), justify="center")
            cell = Clickable(text, f"screen.go('{direction}')", classes="compass-cell way")
            cell.tooltip = f"{direction}: {name}"
            return cell

        middle = Clickable(Text("⚔" if fight else "@", style=f"bold {'#ff4b4b' if fight else ACCENT}",
                                justify="center"), "screen.panel('look')", classes="compass-cell middle")
        middle.tooltip = "Look around (F4)"
        blank = lambda: Static("", classes="compass-cell")  # noqa: E731
        rows = [[blank(), way("north"), blank()], [way("west"), middle, way("east")], [blank(), way("south"), blank()]]
        lines = []
        for cells, h in zip(rows, heights):
            for cell in cells:
                cell.styles.width = cell_w
                cell.styles.height = h
            lines.append(Horizontal(*cells, classes="compass-row"))
        box.mount_all(lines)

    def more_uses(self, fight: bool, groups: dict[str, list[Action]], listed: set[str]) -> list[Action]:
        """What Use offers beyond the game's own choices: in a fight, what the foe's "Use…" would (the things you could
        use on it, bar what Throw has already); out of one, the "Use an item…" picker's things (bar what Heal and Use
        have already). Never what won't work."""
        state, content = self.game.state, self.game.content
        if fight:
            foe = next((t for t in things_here(state, content) if t.kind == "monster" and t.style == "#ff4b4b"), None)
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
                            and a.id.partition(":")[2].split("@")[0] not in taken]
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
                note = group[0].hint or (self.short(group[0]) if kind in ("heal", "throw", "use", "gear") else "")
            return True, note if len(note) <= 12 else note[:11] + "…"
        if kind == "heal":
            healing = any(content.item(k).heal for k in player.inventory)
            return False, "full HP" if healing and player.hp >= player.max_hp else "none"
        if kind == "flee":
            return False, "tangled" if player.tangled else "no way"
        if kind == "bomb":
            return False, "no wall" if player.bombs else "no bombs"
        if kind in ("search", "rest"):
            reason = why_not(state, content, "search_room" if kind == "search" else "rest")
            return False, "done" if kind == "search" and not reason else "not now"
        if kind == "gear":
            return False, "all set"
        return False, "none"

    def tray_lines(self, width: int) -> list[Widget]:
        """The open row: its title, its options a letter each (what each would do after it), and a ✕ to close it."""
        where, title, options, _ = self.tray
        colour = COLOUR.get(title.lower(), GOLD)
        head = Text(f"{title}:", style=f"bold {colour}")
        chips: list[tuple[Widget, int]] = [(Static(head, classes="tray-head"), head.cell_len + 1)]
        for i, action in enumerate(options):
            text = chip(chr(97 + i), self.short(action), colour, action.hint)
            chips.append((Clickable(text, f"screen.pick({i})", classes="choice-chip"), text.cell_len + 2))
        chips.append((Clickable(Text(" ✕ close", style=DIM), "screen.close_tray()", classes="choice-chip"), 9))
        if where == "here":  # (one to a line: Here's narrow)
            return [Horizontal(widget, classes="chip-line") for widget, _ in chips]
        return wrapped(chips, width)

    @staticmethod
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

    # --- what a press does ---

    def action_bar(self, kind: str) -> None:
        """A big button: one thing to do it with, it's done (bar Bomb, which shows which wall first); more, their row
        opens (or closes, if it's open)."""
        if self.busy:
            return
        group = self.groups.get(kind, [])
        if not group:
            self.notify(f"{WORD[kind]}: {self.button_state(kind, group, self.fighting())[1]}", timeout=2)
            return
        if len(group) == 1 and kind not in CONFIRM:
            self.close_tray(redraw=False)
            self.press(group[0])
            return
        self.tray = None if self.tray and self.tray[3] == kind else ("bar", WORD[kind], group, kind)
        self.decide_shown = self.here_drawn = None
        self.refresh_here()
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
        """A choice: a picker opens its row (in Here, under its thing, if it's a thing's; else under the buttons)
        instead of a window; the idea and a scene's choices go by their number in the game's list; anything else is
        a turn, as GameScreen presses it (a tile's button says what it was done to: "Search · pew")."""
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
            self.tray = None if self.tray and self.tray[1] == title else ("here" if owner else "bar", title, options,
                                                                          "")
            self.decide_shown = self.here_drawn = None
            self.refresh_here()
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
        """A choice in the open row."""
        if self.tray and 0 <= index < len(self.tray[2]):
            self.press(self.tray[2][index])
        self.query_one("#command", Input).focus()

    def action_close_tray(self) -> None:
        self.close_tray()

    def close_tray(self, redraw: bool = True) -> None:
        if self.tray is not None:
            self.tray = None
            self.decide_shown = self.here_drawn = None
            if redraw:
                self.refresh_here()
                self.refresh_choices()

    def take_input(self, text: str) -> None:
        """What was typed: a letter for the open row, a number for a button, else as ever."""
        if self.busy or self.game.state.over:
            return super().take_input(text)
        if self.tray and len(text) == 1 and text.isalpha():
            self.action_pick(ord(text.lower()) - 97)
            return
        if text.isdigit() and int(text) in self.slots and not self.game.state.scene:
            self.action_slot(int(text))
            return
        super().take_input(text)

    def action_arrow(self, direction: str) -> None:
        """An arrow key: go that way, or, while there's something typed, move the cursor in it."""
        command = self.query_one("#command", Input)
        if command.value:
            if direction == "west":
                command.action_cursor_left()
            elif direction == "east":
                command.action_cursor_right()
            return
        self.action_go(direction)


HOVER = "\n".join(f"    OneColumnScreen .big-button.live.k-{kind}:hover {{ background: {tint(colour, 0.12)}; }}"
                  for kind, colour in COLOUR.items())


class SpikeApp(PTGApp):
    """The game, its screens laid out by this spike."""

    CSS_PATH = str(Path(app_module.__file__).parent / PTGApp.CSS_PATH)  # (a relative one is read beside this file)
    CSS = """
    OneColumnScreen #play { width: 1fr; }
    OneColumnScreen #stage-box { width: 100%; }
    OneColumnScreen #stage { width: 100%; height: 100%; padding: 0; }
    OneColumnScreen #story { width: 100%; border: double $primary-darken-2; padding: 0 2 0 1; }
    OneColumnScreen #decide { width: 100%; border: round $secondary; border-title-color: $secondary;
        border-title-style: bold; padding: 0 1; }
    OneColumnScreen #decide.fight { border: heavy #ff4b4b; border-title-color: #ff4b4b; }
    OneColumnScreen #decide.scene { border: round $accent; border-title-color: $accent; }
    OneColumnScreen #top-row { width: 100%; }
    OneColumnScreen #bar { width: 1fr; }
    OneColumnScreen .big-button { width: 1fr; margin: 0 1 0 0; content-align: center middle; text-align: center;
        border-title-align: left; border-subtitle-align: center; padding: 0; }
    OneColumnScreen #compass { height: 100%; margin: 0 0 0 1; }
    OneColumnScreen .compass-row { width: 100%; height: auto; }
    OneColumnScreen .compass-cell { content-align: center middle; text-align: center; }
    OneColumnScreen .compass-cell.way { background: #12142a; }
    OneColumnScreen .compass-cell.way:hover { background: #23284e; }
    OneColumnScreen .compass-cell.middle { background: #171a38; }
    OneColumnScreen .compass-cell.middle:hover { background: #23284e; }
    OneColumnScreen #below { width: 100%; padding: 0; margin: 1 0 0 0; scrollbar-size-vertical: 1; }
    OneColumnScreen .chip-line { height: 1; width: 100%; }
    OneColumnScreen .tray-head { width: auto; padding: 0 1 0 0; }
    OneColumnScreen .choice-chip { width: auto; margin: 0 2 0 0; }
    OneColumnScreen .choice-chip:hover { background: #1c2040; }
    OneColumnScreen #command { border: none; height: 1; background: #1c2040; padding: 0 1; }
    OneColumnScreen #command:focus { background: #23284e; }
    OneColumnScreen #side { height: 1fr; padding: 0 0 0 1; }
    OneColumnScreen #map { width: 100%; border: round #6c8cff; border-title-color: #6c8cff; border-title-style: bold;
        border-subtitle-color: #6c6f99; padding: 0 1; }
    OneColumnScreen #map-holder { height: 1fr; align: center middle; }
    OneColumnScreen #map-art { width: auto; height: auto; text-wrap: nowrap; text-overflow: clip; }
    OneColumnScreen #map-notes { width: 100%; }
    OneColumnScreen #here { width: 100%; border: round #ffb000; border-title-color: #ffb000; border-title-style: bold;
        padding: 0 1; overflow: hidden hidden; }
    OneColumnScreen #here.fight { border: heavy #ff4b4b; border-title-color: #ff4b4b; }
    OneColumnScreen .here-you { height: 1; }
    OneColumnScreen .duel { height: auto; margin: 1 0 1 0; }
    OneColumnScreen .duel-art { margin: 0 2 0 0; }
    OneColumnScreen .duel-words { width: 1fr; }
    OneColumnScreen .here-verbs .verb { width: auto; margin-right: 1; }
    OneColumnScreen #strip { width: 100%; }
    OneColumnScreen .panel-row { height: 3; width: 100%; }
    OneColumnScreen .panel-button { width: 1fr; height: 3; border: round #2e3566; border-title-color: #6c6f99;
        border-title-align: right; content-align: center middle; text-align: center; margin: 0; }
    OneColumnScreen .panel-button:hover { border: round #ffb000; border-title-color: #ffb000; background: #1c2040; }
    OneColumnScreen #shims { display: none; }
    MapPanel .map-panel { padding: 1 2; align-horizontal: center; }
    MapPanel .map-name { width: 100%; text-align: center; }
    MapPanel .map-goal { width: 100%; text-align: center; margin: 0 0 1 0; }
    MapPanel .map-rule { width: 100%; text-align: center; }
    MapPanel .map-holder { height: 1fr; width: 100%; align: center middle; }
    MapPanel #map-chart { width: auto; height: auto; text-wrap: nowrap; text-overflow: clip; }
    MapPanel .notes-holder { height: auto; width: 100%; align-horizontal: center; }
    MapPanel .map-notes { width: auto; max-width: 110; }
    """ + HOVER


def spike_screen(game, fresh: bool, width: int, height: int) -> GameScreen:
    return OneColumnScreen(game, fresh)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--fight", help="a test room with this one next door (a monster's key, as ptg --test-room)")
    parser.add_argument("--kit", default="random", help="the test room's loadout (as ptg --loadout)")
    parser.add_argument("--floor", type=int, default=0, help="the test room's floor")
    args = parser.parse_args()
    tabs.game_screen = app_module.game_screen = spike_screen  # (the title, the intro and the app all ask tabs for it)
    SpikeApp(load_config(), seed=args.seed,
             test_room=(args.fight, args.kit, args.floor) if args.fight else None).run()


if __name__ == "__main__":
    main()
