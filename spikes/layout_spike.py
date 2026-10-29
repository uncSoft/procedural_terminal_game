"""Spike (not the game): the game screen as a stage, the room's picture, over a story of text only, with a Here
panel of the room's characters and things beside it, shared out to suit whatever screen it's on.

    uv run python spikes/layout_spike.py           then resize the window to watch it reflow
    uv run python spikes/layout_spike.py --touch   as a phone would have it: bigger buttons to tap
    1 Lucky Lenny   2 a fight   3 a shop   4 a room full of things   ctrl+q quit

How the screen is shared out (make_plan), the story first:
    two columns from 88 columns (or a wide, short landscape screen): the stage and the story on the left; Here, the
    floor map and the arrow pad on the right, the side growing from 30 to 56 columns as the screen widens.
    one column below that (phones): the stage, a Here strip, the story, a bar of ways out, the choices.
    The story keeps at least 8 rows (about 40% of the height when there's room); the choices keep the same height
    in each size; the stage is shaped like a room (about 2.4:1) and gets what's left, or hides under 6 rows. Nothing
    shrinks as the screen grows, and each switch waits 2 rows or columns past its line so a drag doesn't flicker.
    Small screens (one column, or under 30 rows) drop the footer, use a 1-row command line and a short status bar.

The choices are a strip of chips under the story, only as many lines as they need (up to three), side by side
where there's room. What you can do with one thing (talk, give, take, attack) is on its tile, numbered after them.

Characters are always in colour: the spike draws them without the grey "calm" tone the game has today.

What's here is drawn as big as it fits, characters before things, one size for each: a card (the 24-px picture,
over its name, how it is and what you can do), a mini card (the 12-px picture), a row (the 12-px picture beside the
words), or a chip (just the words). If even chips don't fit, the last line says how many more, and shows them.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("PTG_HOME", tempfile.mkdtemp())  # (it saves nothing, but never near your real profile)
os.environ.setdefault("PTG_SOUND", "0")

from rich.text import Text  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.containers import Center, Horizontal, Vertical, VerticalScroll  # noqa: E402
from textual.screen import Screen  # noqa: E402
from textual.widgets import Footer, Input, Static  # noqa: E402

from ptg import loot, npcs, sprites, testrooms  # noqa: E402
from ptg.content import load_content  # noqa: E402
from ptg.room_picture import look_of, picture_text  # noqa: E402
from ptg.rules import available_actions  # noqa: E402
from ptg.sprites import DEFAULT_WIDTH, SMALL, frame_count, sprite_text  # noqa: E402
from ptg.ui.theme import CRT  # noqa: E402
from ptg.ui.widgets import ARROWS, ChoiceItem, Clickable, DPad, Hud, bar, blank_art, map_text, monster_pose  # noqa: E402

CSS_PATH = Path(__file__).resolve().parent.parent / "src" / "ptg" / "ui" / "app.tcss"

_posed = sprites.posed
sprites.posed = lambda img, pose, frame=0: img if pose == "calm" else _posed(img, pose, frame)  # (always in colour)


# --- the plan: how the screen is shared out -------------------------------------------------------------------------

TWO_COLUMNS_AT = 88  # columns; below this, one column (unless it's a wide, short landscape screen)
NUDGE = 2  # how far past a line the screen must go before the layout switches back (no flicker while dragging)
STAGE_CAP = 140  # the widest a room picture is drawn, in columns
STAGE_ROWS_CAP = 30
STAGE_SHAPE = 4.8  # columns per row: a room picture is about 2.4:1 in pixels, and a row is two pixels
STORY_MIN = 8  # the story's rows that nothing takes away
STORY_BESIDE_STAGE = {True: 12, False: 10}  # (two columns?) the story's rows when there's a stage too
STAGE_MIN = 6  # a stage shorter than this isn't worth showing
PAD_ROWS = 5  # the arrow pad, with its border


@dataclass(frozen=True)
class Plan:
    columns: int
    rows: int
    two_columns: bool
    compact: bool  # a 1-row command line, no footer, a short status bar, a rule above each box instead of a frame
    touch: bool
    side: int  # the side column's width (two columns), else 0
    stage_rows: int  # 0: no stage
    stage_width: int
    choice_rows: int  # the most lines of choices shown at once (fewer when fewer will do)
    ways_rows: int  # the bar of ways out (one column), else 0
    here_rows: int  # what the Here strip (one column) or panel (two) may use, inside its box
    story_rows: int  # what's left for the story, inside its box (a check: never under STORY_MIN)

    @property
    def edge(self) -> int:
        """Rows a box's frame takes: 1 for a rule above it (compact), 2 for a frame."""
        return 1 if self.compact else 2

    def describe(self) -> str:
        shape = "two columns" if self.two_columns else "one column"
        return (f"{self.columns}x{self.rows} · {shape}{' · compact' if self.compact else ''}"
                f"{' · touch' if self.touch else ''} · stage {self.stage_rows} · story {self.story_rows}+")


def make_plan(columns: int, rows: int, touch: bool = False, previous: Plan | None = None) -> Plan:
    """Share the screen out: the story's rows first, then the choices, the ways out and the least of the Here strip,
    then the stage, shaped like a room, from what's left. The story gets what nothing else uses."""
    line = TWO_COLUMNS_AT + (0 if previous is None else -NUDGE if previous.two_columns else NUDGE)
    two = columns >= line or (columns >= 70 and columns >= 2.5 * rows)
    compact = not two or rows < 30
    edge = 1 if compact else 2
    avail = rows - 1 - (1 if compact else 3) - (0 if compact else 1)  # less the status bar, command line, footer
    if two:
        side = max(30, min(56, columns - STAGE_CAP - 4))
        left = columns - side
        choice_rows = 3 if rows >= 34 else 2
        ways, strip = 0, 0
    else:
        side, left = 0, columns
        choice_rows = 3 if rows >= 40 else 2
        ways = 3 if touch else 1
        strip = 1 + edge  # at least a line of chips
    main = avail - (choice_rows + 1) - ways  # (the choices have a rule above them, not a frame)
    width = min(STAGE_CAP, left - 2)
    wanted = min(STAGE_ROWS_CAP, round(width / STAGE_SHAPE))
    rest = main - strip - (STORY_MIN + edge)
    story_extra = max(0, round(0.4 * main) - STORY_MIN) if two else 0  # the story's fair share, when there's room
    least = STORY_BESIDE_STAGE[two] - STORY_MIN  # (a stage that would leave the story less than this, isn't shown)
    stage = min(wanted, rest - edge - max(story_extra, least))
    if stage < STAGE_MIN:
        stage = min(wanted, rest - edge - least)  # the story at its least, before the stage goes
    if stage < STAGE_MIN + (NUDGE if previous is not None and not previous.stage_rows else 0):
        stage = 0
    if stage and stage < wanted:
        width = min(width, round(stage * STAGE_SHAPE))  # a narrower picture, rather than bars beside it
    rest -= stage + edge if stage else 0
    if two:
        here, story = main - PAD_ROWS - edge, STORY_MIN + rest
    else:  # the strip may grow, up to 40% of the screen; the story has the rest
        here = min(strip - edge + rest, max(1, round(0.4 * main) - edge))
        story = STORY_MIN + rest - (here - (strip - edge))
    return Plan(columns, rows, two, compact, touch, side, stage, width if stage else 0, choice_rows, ways, here,
                story)


# --- what's here ---------------------------------------------------------------------------------------------------

@dataclass
class Thing:
    """Something the Here panel shows: a character or an item, how it is, and what you can do with it."""
    id: str
    sprite: str
    name: str
    status: str
    status_style: str
    verbs: list[tuple[str, str]]  # (label, what it sends to the engine)
    character: bool = False
    pose: str = "idle"
    fallback: str = "trinket"  # the grey stand-in's kind, when there's no art
    badge: str = ""  # ★ for someone with a job for you
    compact: str = ""  # the status in a few characters, for a chip


VERB_STYLES = {"Attack": "#ff4b4b", "Talk": "#4cff8a", "Give…": "#4cff8a", "Play": "#4cff8a", "Take": "#ffb000",
               "Equip": "#ffb000", "Buy": "#ffb000"}  # by what they do; the rest are blue
MOODS = {(npcs.LENNY, "tooth"): "wants his bad tooth back", (npcs.LENNY, "happy"): "grinning a gap-toothed grin",
         (npcs.SWOOGY, "challenge"): "wants to play a game", (npcs.SWOOGY, "angry"): "FURIOUS"}


def things_here(state, content) -> list[Thing]:
    """Characters first (a foe first of all), then the shop's keeper and her wares, then what's lying here."""
    room, player, found = state.room, state.player, []
    monster = room.monster
    if monster:
        if monster.hostile:
            heavy = monster.intent == "heavy"
            hp = f"{max(0, monster.hp)}/{monster.max_hp}"
            status = ("⚠ big hit next! " if heavy else "") + f"{bar(monster.hp, monster.max_hp, 8)} {hp}"
            chip = f"{bar(monster.hp, monster.max_hp, 4)} {hp}{' ⚠' if heavy else ''}"
            found.append(Thing(monster.key, monster.key, monster.name, status, "#ff4b4b",
                               [("Attack", "attack"), ("Use…", f"use_on:{monster.key}")], character=True,
                               pose=monster_pose(monster), compact=chip))
        else:
            mood = MOODS.get((monster.key, monster.mood), "friendly")
            quest = monster.key == npcs.LENNY and monster.mood == "tooth"
            verbs = [("Talk", "ask")] + ([("Give…", "lenny")] if quest else [])
            found.append(Thing(monster.key, monster.key, monster.name, mood, "#4cff8a", verbs, character=True,
                               badge="★" if quest else "", compact=mood))
    if room.shop:
        keeper = content.monster(room.shop.keeper)
        found.append(Thing(keeper.key, keeper.key, keeper.name, "come in, dearie", "#4cff8a",
                           [("Browse", "shop"), ("Sell…", "sell")], character=True, compact="shopkeeper"))
        for i, ware in enumerate(room.shop.wares):
            item = content.item(ware.item)
            afford = player.gold >= ware.price
            found.append(Thing(f"ware:{i}", f"item_{ware.item}", item.name, f"{ware.price}¤ · {item_short(item)}",
                               "#ffb000" if afford else "#6c6f99", [("Buy", f"buy:{i}")] if afford else
                               [(f"need {ware.price}¤", "")], fallback=loot.role(item), compact=f"{ware.price}¤"))
    for key in room.items:
        item = content.item(key)
        verbs = [("Take", f"take:{key}")]
        status, style = item_short(item), "#9a9cc0"
        if item.kind in ("weapon", "armor"):
            worn = getattr(player, item.kind)
            status, style = compare(content, item, worn)
            if status.startswith("▲"):
                verbs.append(("Equip", f"equip:{key}"))
        if "cursed" in item.tags:
            status, style = "cursed! sticks to you", "#ff4b4b"
        found.append(Thing(key, f"item_{key}", item.name, status, style, verbs, fallback=loot.role(item),
                           compact=status.split(" than")[0]))
    return found


def item_short(item) -> str:
    if item.heal:
        return f"heals {item.heal}"
    return {"trinket": "a trinket", "consumable": "use it once"}.get(item.kind, item.kind)


def compare(content, item, worn: str | None) -> tuple[str, str]:
    """A weapon or armor against what you have on: better, the same or worse."""
    if not worn:
        return "▲ you have none", "#4cff8a"
    mine = content.item(worn)
    score = (lambda i: i.defense) if item.kind == "armor" else (lambda i: i.tier)
    if score(item) > score(mine):
        return f"▲ better than your {mine.name}", "#4cff8a"
    if score(item) == score(mine):
        return f"= like your {mine.name}", "#9a9cc0"
    return f"▼ worse than your {mine.name}", "#6c6f99"


# --- tiles -----------------------------------------------------------------------------------------------------------

CARD, MINI, ROW, CHIP = "card", "mini", "row", "chip"
ART = {CARD: DEFAULT_WIDTH, MINI: SMALL, ROW: SMALL}


def verbs_width(thing: Thing, touch: bool = False) -> int:
    """" Label " and a space after each; with touch, framed buttons at least 8 wide with 2 between."""
    if touch:
        return sum(max(len(label) + 2, 8) + 4 for label, _ in thing.verbs)
    return sum(len(label) + 3 for label, _ in thing.verbs)


def lines(text: str, width: int, most: int) -> int:
    return max(1, min(most, len(textwrap.wrap(text, max(4, width)) or [""])))


def measure(thing: Thing, form: str, width: int, touch: bool, packed: bool = False) -> tuple[int, int]:
    """A tile's (columns, rows) in a box `width` columns wide: its picture, its name (up to two lines), how it is (up
    to three for a character), and its verbs (wrapping to a second line rather than being cut)."""
    verb_row, verbs = (3 if touch else 1), verbs_width(thing, touch)
    if form in (CARD, MINI):
        w = max(26 if form == CARD else 17, verbs + 2)
        if w > width:
            return w, 999
        inner = w - 2
        rows = ART[form] // 2 + lines(thing.badge + thing.name, inner, 2) + \
            lines(thing.status, inner, 3 if thing.character else 1)
        return w, rows + verb_row * (1 if verbs <= inner else 2) + 1
    if form == ROW:
        words = width - SMALL - 1
        text = lines(thing.badge + thing.name, words, 2) + lines(thing.status, words, 3 if thing.character else 1)
        return width, max(SMALL // 2, text) + verb_row * (1 if verbs <= width else 2) + 1
    name = len(thing.badge + " " + thing.name) + 1 + (len(thing.compact) + 1 if thing.character else 0)
    if packed and name + verbs <= width:  # chips side by side in the phone's strip
        return name + verbs, verb_row
    return (width, verb_row) if name + verbs <= width else (min(width, max(name, verbs)), 1 + verb_row)


def arrange(things: list[Thing], width: int, rows: int, touch: bool, forms: tuple[str, ...], packed: bool = False):
    """Lines of (thing, form, size) filling `rows`: characters in the biggest form that fits them all with every
    thing at least a chip, then the things in the biggest form that still fits. If even chips overflow, as many
    lines as fit. Returns (lines, how many things didn't fit)."""
    people = [t for t in things if t.character]
    stuff = [t for t in things if not t.character]

    def laid(group: list[Thing], form: str) -> list[list[tuple[Thing, str, tuple[int, int]]]]:
        out, line, used = [], [], 0
        for thing in group:
            w, h = measure(thing, form, width, touch, packed)
            if line and used + w > width:
                out.append(line)
                line, used = [], 0
            line.append((thing, form, (w, h)))
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


class Tile(Vertical):
    """One thing in Here: a card, a mini card, a row or a chip (see measure)."""

    def __init__(self, thing: Thing, form: str, size: tuple[int, int]) -> None:
        super().__init__(classes=f"tile tile-{form}" + (" character" if thing.character else ""))
        self.thing, self.form, self.frame, self.tile_size = thing, form, 0, size
        self.styles.width, self.styles.height = size
        self.can_focus = False

    def compose(self) -> ComposeResult:
        thing = self.thing
        name = Text(thing.badge + " " if thing.badge else "", style="bold #ffd166")
        name.append(thing.name, style="bold #ff4f9a" if thing.character else "bold")
        if self.form == CHIP:
            if thing.character and thing.compact:
                name.append(f" {thing.compact}", style=thing.status_style)
            stacked = self.tile_size[1] > (3 if self.screen.has_class("touch") else 1)  # (too long for a line)
            with (Vertical if stacked else Horizontal)(classes="tile-body"):
                yield Static(name, classes="tile-name")
                yield self._verbs()
            return
        words = [Static(name, classes="tile-name"),
                 Static(Text(thing.status, style=thing.status_style), classes="tile-status")]
        if self.form == ROW:
            with Horizontal(classes="tile-body"):
                yield Static(self._art(), classes="tile-art")
                with Vertical(classes="tile-words"):
                    yield from words
        else:
            yield Static(self._art(), classes="tile-art")
            yield from words
        yield self._verbs()

    def _verbs(self) -> Horizontal:
        touch = self.screen.has_class("touch")
        buttons = []
        for label, sends in self.thing.verbs:
            colour = VERB_STYLES.get(label.split(" ", 1)[-1], "#6c8cff") if sends else ""
            if touch:  # a solid block three rows tall, easy to hit with a thumb
                button = Clickable(Text(label, style="bold #0b0b14" if sends else "#6c6f99"), f"screen.send('{sends}')",
                                   classes="verb")
                if colour:
                    button.styles.background = colour
            else:
                button = Clickable(Text(f" {label} ", style=f"reverse {colour}" if sends else "#6c6f99"),
                                   f"screen.send('{sends}')", classes="verb")
            buttons.append(button)
        return Horizontal(*buttons, classes="tile-verbs")

    def _art(self) -> Text:
        pose = "idle" if self.form != CARD and self.thing.pose == "windup" else self.thing.pose  # (a glow swamps
        art = sprite_text(self.thing.sprite, self.frame, ART[self.form], pose=pose)  # a small picture)
        return art if art is not None else (blank_art(self.thing.fallback, ART[self.form]) or Text("?"))

    def tick(self) -> None:
        art = self.query(".tile-art")
        if art and frame_count(self.thing.sprite) > 1:  # (nothing to draw on until it's been composed)
            self.frame = (self.frame + 1) % frame_count(self.thing.sprite)
            art.first(Static).update(self._art())


# --- the story's scenes (the spike's, not the game's) -----------------------------------------------------------------

def scene_story(key: str, state) -> list[tuple[str, ...]]:
    room = state.room.name
    return {
        "1": [("player-line", "> go north"),
              ("narration", f"You duck under a low arch into the {room}. Someone small and lumpy is sitting on an "
                            "upturned bucket, prodding a gap in his teeth and sighing."),
              ("say", "Lucky Lenny", "Oi! You haven't seen a tooth about, have you? A bad one. Big, brown, smells of "
                                     "onions. A goblin knocked it clean out with a frying pan. Find it and I'll "
                                     "make it worth your while!"),
              ("quest", "★ NEW QUEST · Lenny's bad tooth")],
        "2": [("player-line", "> attack"),
              ("narration", "Your blade bites into the muck. Swamp Bottoms gurgles, rears back and starts winding up "
                            "something big."),
              ("mechanic", "⚄ Attack: 14 + 3 = 17 vs 13 · hit for 6"),
              ("narration", "Vines slither across the floor toward your ankles.")],
        "3": [("player-line", "> go north"),
              ("narration", f"The door of {room} groans open. Lanterns, jars and a rubber chicken hang from every "
                            "beam."),
              ("say", "Granny Gristle", "Come in, come in, mind the chicken. Everything's for sale, dearie. Even "
                                        "the chicken. Especially the chicken.")],
        "4": [("player-line", "> search the room"),
              ("narration", f"You turn the {room} upside down. Most of it is junk. Some of it isn't."),
              ("mechanic", "⚄ Search: 12 + 1 = 13 vs 10 · found 6 things")],
    }[key]


SCENES = {"1": ("lenny", "random", 3), "2": ("swamp_bottoms", "random", 5), "3": ("shop", "strong", 4),
          "4": ("goblin", "new", 4)}
ON_TILES = ("attack", "ask", "lenny", "swoogy", "shop", "take:", "guess:", "appease:")  # what Here's verbs do instead
FIRST = ("dodge", "flee", "bomb", "use:", "throw:", "distract:", "go:")  # fight tactics and ways out, before the rest


# --- the screen ------------------------------------------------------------------------------------------------------

CSS = """
#hud-row { height: 1; }
#hud { width: 1fr; }
#hud-short { width: 1fr; display: none; height: 1; background: $surface; padding: 0 1; }
#menu { width: 3; background: $surface; color: $secondary; text-style: bold; display: none; }
#left { width: 1fr; }
#stage-box { height: auto; }
#stage { width: auto; height: auto; border: round $primary-darken-2; border-title-color: $secondary; }
#story { min-height: 3; }
#side { height: 1fr; }
#here, #here-strip { height: auto; border: double $primary-darken-2; border-title-color: $secondary; padding: 0 1; }
#here-strip { display: none; }
#side #map { height: auto; }
#side #dpad { margin: 0 0 0 6; }
#ways { display: none; height: 1; padding: 0 1; }
.way { width: 9; margin-right: 2; text-align: center; }
#choices { height: auto; border: none; border-top: heavy $secondary-darken-2; border-title-color: $secondary;
           padding: 0 1; }
.choice-line { height: auto; width: 100%; }
#choices .choice { width: auto; margin-right: 3; }
.more { color: $secondary; text-style: bold; width: auto; }
.tile-line { height: auto; width: 100%; }
.tile { padding: 0 1 1 1; }
.tile-chip { padding: 0; }
.tile-body { height: auto; width: 100%; }
.tile-art { width: auto; height: auto; }
.tile-words { width: 1fr; height: auto; padding-left: 1; }
.tile-name, .tile-status { width: 100%; height: auto; }
.tile-chip .tile-name { width: auto; margin-right: 1; }
.tile-verbs { height: auto; width: 100%; layout: horizontal; }
.tile-chip .tile-verbs { width: 1fr; }
.verb { width: auto; margin-right: 1; height: 1; }
.verb:hover { text-style: bold; }
.say { border-left: thick $accent; padding: 0 1; margin-top: 1; height: auto; }
.quest { border: round $secondary; color: $secondary; text-style: bold; padding: 0 1; height: auto; width: auto; }
#story Static { height: auto; }

SpikeScreen.one #main { layout: vertical; }
SpikeScreen.one #side { display: none; }
SpikeScreen.one #here-strip { display: block; }
SpikeScreen.one #ways { display: block; }
SpikeScreen.compact #hud { display: none; }
SpikeScreen.compact #hud-short, SpikeScreen.compact #menu { display: block; }
SpikeScreen.compact Footer { display: none; }
SpikeScreen.compact #command { height: 1; border: none; padding: 0 1; }
SpikeScreen.compact #story, SpikeScreen.compact #here, SpikeScreen.compact #here-strip,
SpikeScreen.compact #stage, SpikeScreen.compact #map {
    border: none; border-top: heavy $primary-darken-2; }
SpikeScreen.touch .verb { height: 3; min-width: 8; padding: 0 1; margin-right: 2; content-align: center middle; }
SpikeScreen.touch #ways { height: 3; }
SpikeScreen.touch .way { height: 3; background: $panel; content-align: center middle; }
"""


class SpikeScreen(Screen):
    BINDINGS = [Binding("1", "scene('1')", "Lenny", priority=True), Binding("2", "scene('2')", "Fight", priority=True),
                Binding("3", "scene('3')", "Shop", priority=True), Binding("4", "scene('4')", "Things", priority=True),
                Binding("ctrl+q", "app.quit", "Quit")]  # (the spike's command line does nothing: 1-4 are scenes)

    def __init__(self, touch: bool = False) -> None:
        super().__init__()
        self.content = load_content()
        self.touch = touch
        self.state = None
        self.plan: Plan | None = None
        self.scene_key = "1"
        self.here_page = 0
        self.here_shown: tuple | None = None  # what Here was built for: rebuilt only when it changes
        self.stage_shown: tuple | None = None
        self.choice_page = 0
        self.verbs_numbered = 0
        self.tiles: list[Tile] = []
        self._resize_timer = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="hud-row"):
            yield Hud(id="hud")
            yield Static(id="hud-short")
            yield Clickable(Text(" ☰ "), "screen.send('menu: bag, map, quests, help')", id="menu")
        with Horizontal(id="main"):
            with Vertical(id="left"):
                with Center(id="stage-box"):
                    yield Static(id="stage")
                yield Vertical(id="here-strip")
                yield VerticalScroll(id="story")
            with Vertical(id="side"):
                yield Vertical(id="here")
                yield Static(id="map", classes="panel")
                yield DPad(id="dpad")
        yield Horizontal(id="ways")
        yield Vertical(id="choices")
        yield Input(id="command", placeholder="Type a number, or anything you want to try...  (F1 help)")
        yield Footer()

    def on_mount(self) -> None:
        for box, title in (("#story", "Story"), ("#choices", "Choices"), ("#here", "Here"), ("#here-strip", "Here")):
            self.query_one(box).border_title = title
        for box in ("#here", "#here-strip", "#stage", "#story"):
            self.query_one(box).can_focus = False
        self.query_one("#command").can_focus = False  # (in the spike, typed keys are for switching scenes)
        self.set_interval(0.6, self._tick)
        self.action_scene("1")

    def on_resize(self) -> None:
        if self._resize_timer is not None:  # (a drag sends a stream of these: lay out once it settles)
            self._resize_timer.stop()
        self._resize_timer = self.set_timer(0.12, self.relayout)

    def action_scene(self, key: str) -> None:
        self.scene_key, self.here_page, self.choice_page = key, 0, 0
        who, kit, seed = SCENES[key]
        state = testrooms.build(self.content, who, kit, seed=seed)
        room = testrooms.target(state)
        state.room_id, room.visited = room.id, True
        if key == "1":
            room.items = ["hand_axe", "healing_potion"]
        if key == "2":
            room.monster.intent = "heavy"
            room.monster.hp = room.monster.max_hp - 6
        if key == "4":
            room.monster = None
            room.items = ["war_pick", "chain_shirt", "pickle", "holy_water", "rubber_duck", "swoogy_s_diaper"]
        self.state = state
        self.here_shown = self.stage_shown = None
        self._story()
        self.relayout()

    def relayout(self) -> None:
        self._resize_timer = None
        if self.state is None or not self.size.width:
            return
        plan = make_plan(self.size.width, self.size.height, self.touch, self.plan)
        self.plan = plan
        self.set_class(not plan.two_columns, "one")
        self.set_class(plan.compact, "compact")
        self.set_class(plan.touch, "touch")
        self.query_one("#side").styles.width = plan.side or 1
        self.sub_title = plan.describe()
        self._hud()
        self._stage()
        self._here()
        self._choices()
        self._ways()

    # --- pieces ---

    def _hud(self) -> None:
        state, content = self.state, self.content
        self.query_one("#hud", Hud).show(state, content)
        p = state.player
        short = Text("♥", style="#ff4b4b")
        short.append(f"{p.hp}/{p.max_hp}", style="bold #ff4b4b" if p.hp <= 0.3 * p.max_hp else "bold")
        short.append(f" ⛨{p.defense(content)} ", style="#6c8cff")
        short.append(f"✦{p.fate} ", style="#ffd166")
        short.append(f"¤{p.gold} ", style="#ffb000")
        short.append(f"Lv{p.level} ", style="bold #ff4f9a")
        short.append(f"F{state.floor}/{state.floors_total}", style="bold #6c8cff")
        self.query_one("#hud-short", Static).update(short)

    def _stage(self) -> None:
        plan, box = self.plan, self.query_one("#stage-box")
        box.display = plan.stage_rows > 0
        shown = (plan.stage_width, plan.stage_rows, plan.compact, self.scene_key)
        if not box.display or shown == self.stage_shown:
            return
        self.stage_shown = shown
        stage = self.query_one("#stage", Static)
        stage.update(picture_text(self.state, self.content, plan.stage_width, 2 * plan.stage_rows) or Text(""))
        stage.border_title = f"✦ {self.state.room.name}"
        if not plan.compact:
            stage.styles.border = ("round", look_of(self.state.theme).accent)

    def _here(self) -> None:
        plan = self.plan
        things = things_here(self.state, self.content)
        n = 0
        for thing in things:  # every verb gets a number, so typing it does the same as clicking it
            numbered = []
            for label, sends in thing.verbs:
                if sends:
                    n += 1
                    label = f"{n} {label}"
                numbered.append((label, sends))
            thing.verbs = numbered
        self.verbs_numbered = n
        box = self.query_one("#here" if plan.two_columns else "#here-strip")
        other = self.query_one("#here-strip" if plan.two_columns else "#here")
        width = (plan.side if plan.two_columns else plan.columns) - 4  # less the frame and padding
        rows = max(1, plan.here_rows)
        forms = ((CARD, ROW) if width < 34 else (CARD, MINI, ROW)) if plan.two_columns else (MINI,)
        packed = not plan.two_columns
        layout, hidden = arrange(things, width, rows, plan.touch, forms, packed)
        if hidden:  # a page of them, and a line saying how many more (tap it for the next page)
            room_for = rows - (3 if plan.touch else 1)
            first, _ = arrange(things, width, room_for, plan.touch, forms, packed)
            per_page = max(1, sum(map(len, first)))
            start = (self.here_page * per_page) % len(things)
            layout, _ = arrange(things[start:] + things[:start], width, room_for, plan.touch, forms, packed)
            hidden = len(things) - sum(map(len, layout))
        used = sum(max(h for _, _, (_, h) in line) for line in layout) + ((3 if plan.touch else 1) if hidden else 0)
        shown = (plan, tuple(t.id for t in things), tuple(t.status for t in things), self.here_page)
        if shown != self.here_shown:
            self.here_shown = shown
            for container in (box, other):
                container.remove_children()
            self.tiles, rows_out = [], []
            for line in layout:
                row = [Tile(thing, form, size) for thing, form, size in line]
                self.tiles += row
                rows_out.append(Horizontal(*row, classes="tile-line"))
            box.mount_all(rows_out)
            if hidden:
                box.mount(Clickable(Text(f" +{hidden} more ▸ ", style="reverse #ffb000"), "screen.more_here()",
                                    classes="more"))
            if not things:
                box.mount(Static(Text("Nothing here.", style="#6c6f99")))
        box.border_title = f"Here · {len(things)}" if things else "Here"
        box.styles.height = "auto"
        if plan.two_columns:
            map_rows = len(map_text(self.state).plain.splitlines()) + plan.edge
            spare = plan.here_rows - used
            self.query_one("#map").display = spare > map_rows
            self.query_one("#map", Static).update(map_text(self.state))
            self.query_one("#map").border_title = f"Floor {self.state.floor}/{self.state.floors_total}"
            self.query_one("#dpad", DPad).show(available_actions(self.state, self.content))

    def more_here(self) -> None:
        self.here_page += 1
        self.here_shown = None
        self._here()

    def _actions(self):
        actions = [a for a in available_actions(self.state, self.content) if not a.id.startswith(ON_TILES)]
        if not self.plan.two_columns:
            actions = [a for a in actions if not a.id.startswith("go:")]  # the ways bar has them
        return sorted(actions, key=lambda a: not a.id.startswith(FIRST))

    def _choices(self) -> None:
        """The choices as chips side by side, wrapping onto as few lines as they need (up to the plan's), numbered
        after the verbs on the tiles; past that, pages, the last line of each ending in a chip saying how many more
        (tap it for the next page)."""
        plan, box = self.plan, self.query_one("#choices", Vertical)
        actions = self._actions()
        width = plan.columns - 2
        chips = [(n, a, len(f"{n}. {a.label}") + (len(a.hint) + 4 if a.hint else 0) + 2 * a.id.startswith("go:") + 3)
                 for n, a in enumerate(actions, self.verbs_numbered + 1)]
        pages, i = [], 0
        while i < len(chips):
            page, line, used = [], [], 0
            while i < len(chips):
                last = len(page) == plan.choice_rows - 1
                limit = width - (14 if last and len(chips) > i + 1 else 0)  # (room for the "more" chip)
                if line and used + chips[i][2] > limit:
                    page.append(line)
                    line, used = [], 0
                    if len(page) == plan.choice_rows:
                        break
                    continue
                line.append(chips[i])
                used += chips[i][2]
                i += 1
            if line:
                page.append(line)
            pages.append(page)
        page = pages[self.choice_page % len(pages)] if pages else []
        box.remove_children()
        rest = len(actions) - sum(map(len, page))
        for i, line in enumerate(page):
            chips = [ChoiceItem(n, a) for n, a, _ in line]
            if rest and i == len(page) - 1:  # the page's last line ends with how many more (tap for the next page)
                chips.append(Clickable(Text(f" ▼ {rest} more ", style="reverse #ffb000"), "screen.more_choices()",
                                       classes="more"))
            box.mount(Horizontal(*chips, classes="choice-line"))
        box.border_title = "Choices"

    def more_choices(self) -> None:
        self.choice_page += 1
        self._choices()

    def _ways(self) -> None:
        bar_ = self.query_one("#ways", Horizontal)
        bar_.remove_children()
        if self.plan.two_columns:
            return
        ways = {a.id[3:]: a for a in available_actions(self.state, self.content) if a.id.startswith("go:")}
        for direction in ("west", "north", "south", "east"):
            way = ways.get(direction)
            label = Text(f"{ARROWS[direction]} {direction[0].upper()}", style="bold #5fe3ff" if way else "#2e3149")
            bar_.mount(Clickable(label, f"screen.send('go:{direction}')" if way else "screen.send('')",
                                 classes="way"))

    def _story(self) -> None:
        story = self.query_one("#story", VerticalScroll)
        story.remove_children()
        first = None
        for line in scene_story(self.scene_key, self.state):
            if line[0] == "say":
                text = Text(f"{line[1]}:\n", style="bold #ff4f9a")
                text.append(f"“{line[2]}”", style="italic #e8e8f4")
                widget = Static(text, classes="say")
            else:
                widget = Static(Text(line[1]), classes=line[0])
            story.mount(widget)
            first = first or widget
        self.call_after_refresh(lambda: story.scroll_to_widget(first, top=True, animate=False))

    def _tick(self) -> None:
        for tile in self.tiles:
            if tile.thing.character and tile.is_attached:
                tile.tick()

    def action_send(self, sends: str) -> None:
        if sends:
            self.notify(f"→ the engine gets: {sends}", title="Interaction", timeout=3)

    send = action_send


class Spike(App):
    CSS_PATH = str(CSS_PATH)
    CSS = CSS
    TITLE = "Layout spike"

    def __init__(self, touch: bool = False) -> None:
        super().__init__()
        self.touch = touch

    def on_mount(self) -> None:
        self.register_theme(CRT)
        self.theme = "crt"
        self.push_screen(SpikeScreen(self.touch))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="The Stage + Here layout spike.")
    parser.add_argument("--touch", action="store_true", help="bigger buttons to tap, as on a phone")
    Spike(parser.parse_args().touch).run()
    sys.exit(0)
