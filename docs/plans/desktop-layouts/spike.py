"""Spike (not the game): three ways to lay the game screen out on a desktop, built from the game's own pieces (the
room's picture, the portraits, what's here and what you can do with it, the floor, the story), so what you see is what
the game would show. Nothing in it plays: it's a still, to look at.

    uv run python docs/plans/desktop-layouts/spike.py --layout halves --scene lenny
    layouts: halves (A), columns (B), quad (C)        scenes: lenny, fight, explore        ctrl+q quits

What's common to all three, from the review of the current screen:
    - Ways out leave the choices. The pad says where each one goes ("▲ Mess Cave"), and the floor map is big again,
      with the rooms' names on it, so you can see what's in which direction.
    - The pad and the map are a dock with a place of its own: it never moves, whatever's in the room.
    - Here has the room it needs: every card at full size (24 px), and it scrolls if there's more.
    - The choices are one quiet line at the very bottom, under the command line ("+N more" for the rest).
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

os.environ.setdefault("PTG_HOME", tempfile.mkdtemp())
os.environ.setdefault("PTG_SOUND", "0")

from rich.text import Text  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll  # noqa: E402
from textual.widgets import Static  # noqa: E402

from ptg import testrooms  # noqa: E402
from ptg.content import load_content  # noqa: E402
from ptg.glossary import Lexicon, build  # noqa: E402
from ptg.models import DELTA  # noqa: E402
from ptg.room_picture import look_of, picture_text  # noqa: E402
from ptg.rules import available_actions, perform  # noqa: E402
from ptg.ui.here import things_here  # noqa: E402
from ptg.ui.widgets import Hud, Picture, highlight  # noqa: E402
from ptg.world import map_glyph  # noqa: E402

DIM, WORDS, ACCENT = "#6c6f99", "#c8c8e0", "#ffb000"
VERB_COLOURS = {"Attack": "#ff4b4b", "Talk": "#4cff8a"}
ARROWS = {"north": "▲", "south": "▼", "east": "▶", "west": "◀"}


# --- the scene: a real room, walked into ------------------------------------------------------------------------------

def scene(content, name: str):
    """A test room's target walked into, and what the story would say of it."""
    who = {"lenny": "lenny", "fight": "hobgoblin", "explore": "lenny_quest"}[name]
    state = testrooms.build(content, who, "new", seed={"lenny": 4, "fight": 5, "explore": 3}[name])
    target = testrooms.target(state)
    way = next(d for d, e in state.room.exits.items() if e.to == target.id)
    opening = state.room
    events = perform(state, content, f"go:{way}")
    for room in state.rooms:  # (a floor half explored, so the map has something to show)
        if room.distance <= 2 and not room.secret and not room.shop and room.id != state.room_id:
            room.visited = True
    if name == "fight":
        state.room.items = ["healing_potion", "war_pick", "stale_bread"]
    if name == "explore":
        state.room.monster = None
    story = [("floor", f"↓  FLOOR {state.floor} OF {state.floors_total}  ·  {content.themes[state.theme].name.upper()}  ↓"),
             ("words", f"{content.themes[state.theme].blurb} You stand in the {opening.name}."),
             ("player", f"> Go {way}")]
    for event in events:
        if event.kind == "story" and event.data.get("speaker"):
            story.append(("say", f"{event.data['title']}: “{event.text}”"))
        elif event.text:
            story.append(("words", event.text))
    if name == "fight":
        story += [("player", "> Attack the Hobgoblin"),
                  ("roll", "⚄ attack: d20 17 + 2 might + 1 level = 20 vs 13   ✔ HIT   → 5 damage (1d6 3 + might 2)"),
                  ("roll", "⚄ Hobgoblin attacks: d20 15 + 4 attack = 19 vs 11   ✘ HIT YOU   → 6 damage (1d8 6)"),
                  ("words", "You catch the Hobgoblin under its helmet. It snarls and swings back, hard.")]
    return state, story


# --- the pieces -------------------------------------------------------------------------------------------------------

def story_text(state, content, story) -> Text:
    lexicon = Lexicon(build(state, content))
    text = Text()
    for kind, words in story:
        if kind == "floor":
            text.append(words.center(60) + "\n\n", style="bold #ff4f9a")
        elif kind == "player":
            text.append(words + "\n", style=f"bold {ACCENT}")
        elif kind == "roll":
            text.append("  " + words + "\n", style="#9a9cc0")
        elif kind == "say":
            text.append("▌ ", style="#ff4f9a")
            text.append_text(highlight(words, lexicon, "italic #e8e8f4"))
            text.append("\n\n")
        else:
            text.append_text(highlight(words, lexicon, WORDS))
            text.append("\n\n")
    return text


def named_map(state, width: int = 60) -> Text:
    """The floor, each room a box with its name in it (unvisited ones as "?"), joined by its doors, the boxes as
    wide as `width` allows (up to 18)."""
    known = {r.id for r in state.rooms if r.visited}
    for room_id in list(known):
        known.update(e.to for e in state.rooms[room_id].exits.values())
    rooms = [state.rooms[i] for i in known]
    min_x, min_y = min(r.x for r in rooms), min(r.y for r in rooms)
    across = max(r.x for r in rooms) - min_x + 1
    cell = max(7, min(18, width // across - 3))
    width = (max(r.x for r in rooms) - min_x + 1) * (cell + 3)
    height = (max(r.y for r in rooms) - min_y) * 2 + 1
    grid = [[(" ", "")] * width for _ in range(height)]

    def put(x, y, words, style):
        for i, ch in enumerate(words):
            if 0 <= x + i < width:
                grid[y][x + i] = (ch, style)

    for room in rooms:
        x, y = (room.x - min_x) * (cell + 3), (room.y - min_y) * 2
        here = room.id == state.room_id
        glyph = map_glyph(state, room)
        name = room.name if room.visited else "?"
        label = (f"@ {name}" if here else name if glyph in "#?" else f"{glyph} {name}")[:cell - 2]
        label = label if len(label) <= cell - 2 else label[:cell - 3] + "…"
        style = "bold reverse #ffd166" if here else ("#ff7b7b" if glyph == "!" else
                                                     WORDS if room.visited else DIM)
        put(x, y, f"[{label.center(cell - 2)}]", style)
        if not room.visited:
            continue
        for direction, exit_ in room.exits.items():
            door = "═══" if exit_.locked else "───"
            if direction == "east":
                put(x + cell, y, door, DIM)
            elif direction == "west":
                put(x - 3, y, door, DIM)
            elif direction == "south":
                put(x + cell // 2, y + 1, "║" if exit_.locked else "│", DIM)
            elif direction == "north" and y:
                put(x + cell // 2, y - 1, "║" if exit_.locked else "│", DIM)
    text = Text()
    for row in grid:
        for ch, style in row:
            text.append(ch, style=style)
        text.append("\n")
    return text


def exits_pad(state) -> Text:
    """The arrow pad, saying where each way goes: the room's name if you've been, else what you can see that way."""
    room = state.room

    def way(direction):
        exit_ = room.exits.get(direction)
        if exit_ is None:
            return Text(f"{ARROWS[direction]} —", style="#3a3c5a")
        there = state.rooms[exit_.to]
        name = there.name if there.visited else ("locked" if exit_.locked else there.fixture or "unexplored")
        return Text(f"{ARROWS[direction]} {name}", style=f"bold {'#5fe3ff' if there.visited else ACCENT}")

    text = Text(justify="center")
    text.append_text(way("north"))
    text.append("\n\n")
    text.append_text(way("west"))
    text.append("    @    ", style="bold #ffd166")
    text.append_text(way("east"))
    text.append("\n\n")
    text.append_text(way("south"))
    return text


def buttons(thing, numbers, width: int) -> Text:
    """A thing's buttons, numbered, each kept whole on a line (a new line rather than split one)."""
    text, used = Text(), 0
    for action in thing.verbs:
        colour = VERB_COLOURS.get(action.label, "#6c8cff")
        chip = f" {numbers.setdefault(action.id, len(numbers) + 1)} {action.label} "
        if used and used + len(chip) > width:
            text.append("\n")
            used = 0
        text.append(chip, style=f"bold #10122a on {colour}")
        text.append(" ")
        used += len(chip) + 1
    return text


def words(thing) -> Text:
    text = Text(thing.title, style=f"bold {'#ff4f9a' if thing.character else '#ffd166'}")
    if thing.status:
        text.append(f"\n{thing.status}", style=thing.style or DIM)
    return text


def character_card(content, thing, numbers) -> Horizontal:
    """Someone in the room: their portrait at full size, and beside it who they are, how they are and what you can
    do with them."""
    side = Vertical(Static(words(thing), classes="card-words"), Static(buttons(thing, numbers, 30),
                                                                         classes="card-verbs"), classes="card-side")
    return Horizontal(Picture(thing.sprite, thing.kind, 24, content=content, animate=False), side,
                      classes="card character")


def thing_card(content, thing, numbers) -> Vertical:
    """Something in the room: its picture at full size (if it has one) over its name and its buttons."""
    parts = [Picture(thing.sprite, thing.kind, 24, content=content, animate=False)] if thing.art and thing.sprite else []
    parts += [Static(words(thing), classes="card-words"), Static(buttons(thing, numbers, 26), classes="card-verbs")]
    return Vertical(*parts, classes="card thing")


def choices_line(state, content, numbers) -> Text:
    """The choices, bar the ways out: one quiet line, numbered after Here's buttons, and how many more."""
    rest = [a for a in available_actions(state, content)
            if not a.id.startswith("go:") and a.id not in numbers]
    text = Text("▸ ", style=DIM)
    for action in rest[:4]:
        text.append(f"{numbers.setdefault(action.id, len(numbers) + 1)} ", style=f"bold {ACCENT}")
        text.append(action.label, style="#9a9cc0")
        text.append("   ")
    if len(rest) > 4:
        text.append(f"+{len(rest) - 4} more", style=f"bold reverse {DIM}")
    return text


# --- the app: one layout, one scene -----------------------------------------------------------------------------------

CSS = """
Screen { background: #0b0c18; }
#hud { height: 1; }
#main { height: 1fr; }
#quad { height: 1fr; grid-gutter: 0; }
#left, #middle, #right { height: 100%; }
#middle { width: 1fr; }
#story { height: 1fr; }
.box { border: round #3d4a8c; border-title-color: #6c8cff; padding: 0 1; }
#stage { border: round $warning; }
#here-cards { grid-gutter: 1 2; height: auto; grid-rows: auto; }
.card { height: auto; width: 100%; }
.card.character { margin-bottom: 1; }
.card-side { height: auto; width: 1fr; padding: 1 0 0 2; }
.card-words, .card-verbs { height: auto; }
.card-verbs { margin-top: 1; }
#quad > #stage { height: 100%; }
#dock { height: 17; }
#dock > Horizontal, #dock > Vertical { height: 100%; }
#dock > Horizontal > #map { width: 1fr; height: 100%; }
#dock > Horizontal > #pad { width: 36; height: 100%; }
#dock > Vertical > #map { height: 1fr; }
#dock > Vertical > #pad { height: 9; }
#pad { content-align: center middle; text-align: center; }
#here { height: 1fr; }
#command { height: 1; background: #161a33; color: #6c6f99; padding: 0 1; }
#choices { height: 1; padding: 0 1; }
"""


class Spike(App):
    CSS = CSS
    BINDINGS = [("ctrl+q", "quit", "Quit")]

    def __init__(self, layout: str, scene_name: str) -> None:
        super().__init__()
        self.layout_name = layout
        self.content = load_content()
        self.state, self.story = scene(self.content, scene_name)

    # the boxes, the same in every layout
    def stage(self) -> Static:
        box = Static(id="stage", classes="box")
        box.border_title = f"✦ {self.state.room.name}"
        return box

    def story_box(self) -> VerticalScroll:
        box = VerticalScroll(Static(story_text(self.state, self.content, self.story)), id="story", classes="box")
        box.border_title = "Story"
        return box

    def here(self, columns: int) -> VerticalScroll:
        self.numbers: dict[str, int] = {}
        things = things_here(self.state, self.content)
        people = [character_card(self.content, t, self.numbers) for t in things if t.character]
        grid = Grid(*[thing_card(self.content, t, self.numbers) for t in things if not t.character], id="here-cards")
        grid.styles.grid_size_columns = columns
        box = VerticalScroll(*people, grid, id="here", classes="box")
        box.border_title = f"Here · {len(things)}"
        return box

    def dock(self, stacked: bool) -> Vertical:
        floor = Static(id="map", classes="box")
        floor.border_title = f"Floor {self.state.floor}/{self.state.floors_total}"
        pad = Static(exits_pad(self.state), id="pad", classes="box")
        pad.border_title = "Ways out"
        inner = Vertical(floor, pad) if stacked else Horizontal(floor, pad)
        return Vertical(inner, id="dock")

    def compose(self) -> ComposeResult:
        hud = Hud(id="hud")
        yield hud
        layout = getattr(self, f"layout_{self.layout_name}")
        yield from layout()
        yield Static(Text("Type a number, or anything you want to try...  (F1 help)"), id="command")
        yield Static(id="choices")

    def layout_halves(self):
        """A: the screen split in half. Left: the room's picture over the story. Right: Here, with the dock pinned
        under it."""
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield self.stage()
                yield self.story_box()
            with Vertical(id="right"):
                yield self.here(3)
                yield self.dock(stacked=False)

    def layout_columns(self):
        """B: three columns. Left, where you can go: the floor and the pad. Middle, what's happening: the room's
        picture over the story. Right, what's here: Here, the full height."""
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield self.dock(stacked=True)
            with Vertical(id="middle"):
                yield self.stage()
                yield self.story_box()
            with Vertical(id="right"):
                yield self.here(2)

    def layout_quad(self):
        """C: a 2x2 grid. Top: the room's picture, and Here beside it. Bottom: the story, and the dock beside it."""
        with Grid(id="quad"):
            yield self.stage()
            yield self.here(3)
            yield self.story_box()
            yield self.dock(stacked=False)

    def on_mount(self) -> None:
        self.query_one(Hud).show(self.state, self.content)
        w, h = self.size
        if self.layout_name == "halves":
            half = w // 2
            self.query_one("#left").styles.width = half
            self.query_one("#right").styles.width = w - half
            self.query_one("#stage").styles.height = round(h * 0.48)
            self.query_one("#here").styles.height = "1fr"
        elif self.layout_name == "columns":
            self.query_one("#left").styles.width = 46
            self.query_one("#right").styles.width = 54
            self.query_one("#stage").styles.height = round(h * 0.45)
            self.query_one("#dock").styles.height = "100%"
        else:
            quad = self.query_one("#quad")
            quad.styles.grid_size_columns, quad.styles.grid_size_rows = 2, 2
            quad.styles.grid_columns = ("3fr", "2fr")
            quad.styles.grid_rows = ("1fr", "1fr")
            self.query_one("#dock").styles.height = "100%"
        self.call_after_refresh(self.draw)

    def draw(self) -> None:
        stage = self.query_one("#stage")
        w, h = stage.content_size
        stage.update(picture_text(self.state, self.content, max(8, w), 2 * max(4, h)) or Text(""))
        floor = self.query_one("#map", Static)
        floor.update(named_map(self.state, floor.content_size.width))
        stage.styles.border = ("round", look_of(self.state.theme).accent)
        self.query_one("#choices", Static).update(choices_line(self.state, self.content, dict(self.numbers)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout", default="halves", choices=["halves", "columns", "quad"])
    parser.add_argument("--scene", default="lenny", choices=["lenny", "fight", "explore"])
    args = parser.parse_args(sys.argv[1:])
    Spike(args.layout, args.scene).run()
