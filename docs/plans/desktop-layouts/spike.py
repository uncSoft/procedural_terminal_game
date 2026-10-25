"""Spike (not the game): the game screen on a desktop, split in half, built from the game's own pieces (the room's
picture, the portraits, what's here and what you can do with it, the floor map, the story), so what you see is what
the game would show. Nothing in it plays: it's a still, to look at (hover the map's rooms and the arrows for names).

    uv run python docs/plans/desktop-layouts/spike.py --layout right --scene lenny
    layouts: right (A1: the choices under Here, beside the map), left (A2: the choices under the story)
    scenes: lenny, fight, explore        ctrl+q quits

From the owner's notes on the first round (three columns, a 2x2 grid, a big map with names in it, the choices in one
quiet line: all set aside):
    - The choices are a box of their own, one to a line and plain to see, but only as wide as half the screen.
    - Ways out leave the choices, and aren't spelled out anywhere: the floor map is the game's own, with its key, and
      the arrow pad under it; hover a room on the map, or an arrow, for where it is.
    - The map and the pad have a place of their own that never moves, whatever's in the room.
    - Here has the room it needs: every card at full size (24 px), scrolling if there's more.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

os.environ.setdefault("PTG_HOME", tempfile.mkdtemp())
os.environ.setdefault("PTG_SOUND", "0")

from rich.style import Style  # noqa: E402
from rich.text import Text  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll  # noqa: E402
from textual.widgets import Static  # noqa: E402

from ptg import testrooms  # noqa: E402
from ptg.content import load_content  # noqa: E402
from ptg.glossary import Lexicon, build  # noqa: E402
from ptg.room_picture import look_of, picture_text  # noqa: E402
from ptg.rules import available_actions, locked_doors, perform  # noqa: E402
from ptg.ui.here import things_here  # noqa: E402
from ptg.ui.widgets import DPad, Hud, Picture, highlight, map_text  # noqa: E402

DIM, WORDS, ACCENT = "#6c6f99", "#c8c8e0", "#ffb000"
VERB_COLOURS = {"Attack": "#ff4b4b", "Talk": "#4cff8a"}


# --- the scene: a real room, walked into ------------------------------------------------------------------------------

def scene(content, name: str):
    """A test room's target walked into (the rooms near the start been to already, so the map has something on it),
    and what the story would say of it."""
    who = {"lenny": "lenny", "fight": "hobgoblin", "explore": "lenny_quest"}[name]
    state = testrooms.build(content, who, "new", seed={"lenny": 4, "fight": 5, "explore": 3}[name])
    target = testrooms.target(state)
    way = next(d for d, e in state.room.exits.items() if e.to == target.id)
    opening = state.room
    events = perform(state, content, f"go:{way}")
    for room in state.rooms:
        if room.distance <= 2 and not room.secret and not room.shop and room.id != state.room_id:
            room.visited = True
    if name == "fight":
        state.room.items = ["healing_potion", "war_pick", "stale_bread"]
    if name == "explore":
        state.room.monster = None
    theme = content.themes[state.theme]
    story = [("floor", f"↓  FLOOR {state.floor} OF {state.floors_total}  ·  {theme.name.upper()}  ↓"),
             ("words", f"{theme.blurb} You stand in the {opening.name}."),
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
    for kind, words_ in story:
        if kind == "floor":
            text.append(words_.center(60) + "\n\n", style="bold #ff4f9a")
        elif kind == "player":
            text.append(words_ + "\n", style=f"bold {ACCENT}")
        elif kind == "roll":
            text.append("  " + words_ + "\n", style="#9a9cc0")
        elif kind == "say":
            text.append("▌ ", style="#ff4f9a")
            text.append_text(highlight(words_, lexicon, "italic #e8e8f4"))
            text.append("\n\n")
        else:
            text.append_text(highlight(words_, lexicon, WORDS))
            text.append("\n\n")
    return text


class MapView(Static):
    """The game's floor map (map_text, its key under it), each room saying where it is when hovered."""

    def __init__(self, state, **kwargs) -> None:
        super().__init__(**kwargs)
        self.state = state

    def on_mount(self) -> None:
        self.update(hover_map(self.state))

    def on_mouse_move(self, event) -> None:
        tip = (getattr(self.get_style_at(event.x, event.y), "meta", None) or {}).get("tip")
        if tip != self.tooltip:
            self.tooltip = tip

    def on_leave(self, event) -> None:
        self.tooltip = None


def hover_map(state) -> Text:
    """map_text, with each room's three cells ("[@]") carrying its name for a tooltip (render_map's layout)."""
    text = map_text(state, 30)
    mapped = state.mapped_floor == state.floor
    known = {r.id for r in state.rooms if r.visited or (mapped and (not r.secret or r.exits))}
    for room_id in list(known):
        known.update(e.to for e in state.rooms[room_id].exits.values())
    known.update(r.id for r in state.rooms if r.told or any(f.told for f in r.features))
    rooms = [state.rooms[i] for i in known]
    min_x, min_y = min(r.x for r in rooms), min(r.y for r in rooms)
    starts = [0]
    for line in text.plain.split("\n"):
        starts.append(starts[-1] + len(line) + 1)
    for room in rooms:
        cx, cy = (room.x - min_x) * 4 + 1, (room.y - min_y) * 2
        name = room.name if room.visited else "unexplored" + (f": a {room.fixture}" if room.fixture else "")
        at = starts[cy] + cx - 1
        text.stylize(Style(meta={"tip": name + (" (you're here)" if room.id == state.room_id else "")}), at, at + 3)
    return text


def buttons(thing, numbers, width: int) -> Text:
    """A thing's buttons, numbered, each kept whole on a line (a new line rather than split one)."""
    text, used = Text(), 0
    for action in thing.verbs:
        chip = f" {numbers.setdefault(action.id, len(numbers) + 1)} {action.label} "
        if used and used + len(chip) > width:
            text.append("\n")
            used = 0
        text.append(chip, style=f"bold #10122a on {VERB_COLOURS.get(action.label, '#6c8cff')}")
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
    side = Vertical(Static(words(thing), classes="card-words"),
                    Static(buttons(thing, numbers, 30), classes="card-verbs"), classes="card-side")
    return Horizontal(Picture(thing.sprite, thing.kind, 24, content=content, animate=False), side,
                      classes="card character")


def thing_card(content, thing, numbers) -> Vertical:
    """Something in the room: its picture at full size (if it has one) over its name and its buttons."""
    parts = [Picture(thing.sprite, thing.kind, 24, content=content, animate=False)] if thing.art and thing.sprite else []
    parts += [Static(words(thing), classes="card-words"), Static(buttons(thing, numbers, 26), classes="card-verbs")]
    return Vertical(*parts, classes="card thing")


def choices_list(state, content, numbers) -> Text:
    """The choices, bar the ways out (the map and the pad have those): one to a line, numbered after Here's buttons,
    the number and the words bright, a hint dim beside them, a ✦ idea in its own colour."""
    rest = [a for a in available_actions(state, content) if not a.id.startswith("go:") and a.id not in numbers]
    text = Text()
    for i, action in enumerate(rest):
        number = numbers.setdefault(action.id, len(numbers) + 1)
        creative = action.label.startswith("✦")
        text.append(f" {number:>2} ", style=f"bold #10122a on {'#ff4f9a' if creative else ACCENT}")
        text.append(f"  {action.label}", style="italic bold #ff4f9a" if creative else "bold #e8e8f4")
        if action.hint:
            text.append(f"   {action.hint}", style=DIM)
        if i < len(rest) - 1:
            text.append("\n")
    return text


# --- the app: one layout, one scene -----------------------------------------------------------------------------------

CSS = """
Screen { background: #0b0c18; }
#hud { height: 1; }
#main { height: 1fr; }
#left, #right { height: 100%; }
#story { height: 1fr; }
.box { border: round #3d4a8c; border-title-color: #6c8cff; padding: 0 1; }
#stage { border: round $warning; }
#here { height: 1fr; }
#here-cards { grid-gutter: 1 2; height: auto; grid-rows: auto; }
.card { height: auto; width: 100%; }
.card.character { margin-bottom: 1; }
.card-side { height: auto; width: 1fr; padding: 1 0 0 2; }
.card-words, .card-verbs { height: auto; }
.card-verbs { margin-top: 1; }
#choices-box { border: heavy $warning; border-title-color: $warning; border-title-style: bold; padding: 0 1; }
#right #choices-box { width: 1fr; height: 100%; }
#left #choices-box { height: auto; max-height: 12; }
#lower { height: 16; }
#nav { width: 32; height: 100%; }
#lower.strip { height: 11; }
#lower.strip #nav { width: 1fr; }
#lower.strip #map { width: 1fr; height: 100%; }
#lower.strip DPad { width: 24; height: 100%; }
#map { height: 1fr; }
DPad { height: 5; width: 100%; align: center middle; border: round #3d4a8c; }
.dpad-row { height: 1; width: auto; }
.dpad-key, .dpad-gap { width: 5; height: 1; content-align: center middle; }
#command { height: 1; background: #161a33; color: #6c6f99; padding: 0 1; }
"""


class Spike(App):
    CSS = CSS
    BINDINGS = [("ctrl+q", "quit", "Quit")]

    def __init__(self, layout: str, scene_name: str) -> None:
        super().__init__()
        self.layout_name = layout
        self.content = load_content()
        self.state, self.story = scene(self.content, scene_name)
        self.numbers: dict[str, int] = {}

    # the boxes, the same in either layout
    def stage(self) -> Static:
        box = Static(id="stage", classes="box")
        box.border_title = f"✦ {self.state.room.name}"
        return box

    def story_box(self) -> VerticalScroll:
        box = VerticalScroll(Static(story_text(self.state, self.content, self.story)), id="story", classes="box")
        box.border_title = "Story"
        return box

    def here(self) -> VerticalScroll:
        things = things_here(self.state, self.content)
        people = [character_card(self.content, t, self.numbers) for t in things if t.character]
        grid = Grid(*[thing_card(self.content, t, self.numbers) for t in things if not t.character], id="here-cards")
        grid.styles.grid_size_columns = 3
        box = VerticalScroll(*people, grid, id="here", classes="box")
        box.border_title = f"Here · {len(things)}"
        return box

    def choices(self) -> VerticalScroll:
        box = VerticalScroll(Static(id="choice-list"), id="choices-box")
        box.border_title = "What do you do?"
        return box

    def nav(self, side_by_side: bool = False) -> Vertical | Horizontal:
        """The floor map and the arrow pad, in a place of their own that never moves: the pad under the map, or
        beside it."""
        floor = MapView(self.state, id="map", classes="box")
        floor.border_title = f"Floor {self.state.floor}/{self.state.floors_total}"
        return (Horizontal if side_by_side else Vertical)(floor, DPad(id="dpad"), id="nav")

    def compose(self) -> ComposeResult:
        yield Hud(id="hud")
        yield from getattr(self, f"layout_{self.layout_name}")()
        yield Static(Text("Type a number, or anything you want to try...  (F1 help)"), id="command")

    def layout_right(self):
        """A1: the screen in halves. Left: the room's picture over the story. Right: Here, and under it the choices,
        with the map and the pad beside them."""
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield self.stage()
                yield self.story_box()
            with Vertical(id="right"):
                yield self.here()
                with Horizontal(id="lower"):
                    yield self.choices()
                    yield self.nav()

    def layout_left(self):
        """A2: the screen in halves. Left: the room's picture, the story, and the choices under it. Right: Here, and
        under it the map and the pad side by side."""
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield self.stage()
                yield self.story_box()
                yield self.choices()
            with Vertical(id="right"):
                yield self.here()
                with Horizontal(id="lower", classes="strip"):
                    yield self.nav(side_by_side=True)

    def on_mount(self) -> None:
        self.query_one(Hud).show(self.state, self.content)
        w, h = self.size
        self.query_one("#left").styles.width = w // 2
        self.query_one("#right").styles.width = w - w // 2
        self.query_one("#stage").styles.height = round(h * (0.45 if self.layout_name == "right" else 0.4))
        self.query_one(DPad).show(available_actions(self.state, self.content), locked_doors(self.state, self.content))
        self.call_after_refresh(self.draw)

    def draw(self) -> None:
        stage = self.query_one("#stage")
        w, h = stage.content_size
        stage.update(picture_text(self.state, self.content, max(8, w), 2 * max(4, h)) or Text(""))
        stage.styles.border = ("round", look_of(self.state.theme).accent)
        self.query_one("#choice-list", Static).update(choices_list(self.state, self.content, self.numbers))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout", default="right", choices=["right", "left"])
    parser.add_argument("--scene", default="lenny", choices=["lenny", "fight", "explore"])
    args = parser.parse_args(sys.argv[1:])
    Spike(args.layout, args.scene).run()
