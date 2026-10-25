"""Layout lab (not the game): the game screen on a desktop, built from the game's own pieces (the room's picture, the
portraits, what's here and what you can do with it, the floor map, the story) in rooms of every sort, to try layouts
against. Nothing in it plays: it's a still to look at, flipped through with keys.

    uv run python docs/plans/desktop-layouts/spike.py              then: L layout, N/P room, F focus, D thumbnails
    uv run python docs/plans/desktop-layouts/spike.py --layout hub --room crowded

Rooms (the debug app's own test rooms, filled in to order): sparse (one thing to search, three choices, two rooms
known), lenny (a character with a job for you), crowded (a fight, three things on the floor, a chest), loot (five
things lying about, seven choices, the whole floor known), shop.

Layouts, from the owner's notes on round two (where the eye goes through a turn: read what happened, look at the room,
decide, act):
    hub    the room's picture over the story, on the left; on the right, top to bottom: what's here (pictures and how
           they are, only as tall as it needs), "What do you do?" (every action in one place, grouped by what it's for,
           the command line inside it), and the floor map with its arrows on its edges. The decision sits level with
           the story, and nothing moves from room to room: the decision box is a fixed square, as tall as the most
           choices a room has, and the command line takes the rows the choices don't (one, when there are six).
    band   the room as a band across the top: its picture, and what's here beside it (with their buttons). Under it,
           the story, and beside it the same fixed decision square, with the map under that.
    focus  words on the left, pictures on the right. Left: the room's picture, the story, and the decision square
           under the story. Right: what's here as one frame and a strip, then the map. The frame draws the thing in
           focus at full size (all 24 pixels, never the small version) with everything about it beside it (how it
           is, its numbers, its creator's words, its buttons); the strip under it is everything here as thumbnails
           and nothing else, the one in the frame underlined. Click one (or F) to bring it into the frame. D flips
           the thumbnails between the hand-made small pictures (12 pixels) and "dense": the full 24-pixel art drawn
           2x3 pixels to a cell (sextants), every pixel in a third of the room, two colours to a cell.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

os.environ.setdefault("PTG_HOME", tempfile.mkdtemp())
os.environ.setdefault("PTG_SOUND", "0")

from rich.color import Color as RichColor  # noqa: E402
from rich.style import Style  # noqa: E402
from rich.text import Text  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.containers import Grid, Horizontal, HorizontalScroll, Vertical, VerticalScroll  # noqa: E402
from textual.widgets import Static  # noqa: E402

from ptg import powers, sprites, testrooms  # noqa: E402
from ptg.content import load_content  # noqa: E402
from ptg.events import Action  # noqa: E402
from ptg.glossary import Lexicon, build  # noqa: E402
from ptg.models import Feature  # noqa: E402
from ptg.room_picture import look_of, picture_text  # noqa: E402
from ptg.rules import available_actions, locked_doors, perform  # noqa: E402
from ptg.ui.here import things_here  # noqa: E402
from ptg.ui.widgets import Hud, Picture, highlight, map_text  # noqa: E402

DIM, WORDS, ACCENT, PINK = "#6c6f99", "#c8c8e0", "#ffb000", "#ff4f9a"
VERB_COLOURS = {"Attack": "#ff4b4b", "Talk": "#4cff8a"}
ARROWS = {"north": "▲", "south": "▼", "east": "▶", "west": "◀"}
MOST_CHOICES = 7  # the most choices a room gives you (a loot room): the decision box is this tall, always
LAYOUTS = ["hub", "band", "focus"]
THUMBS = ["small", "dense"]

# What's on offer in a room beyond its own, to fill a room's choices out to the number asked for: real actions, as
# the game words them.
MORE = [Action("search_room", "Search the room for secrets"), Action("rest", "Rest a while", "risky"),
        Action("use:healing_potion", "Drink the Healing Potion"), Action("bomb:north", "Bomb the north wall", "1 bomb"),
        Action("use:stale_bread", "Eat the Stale Bread"), Action("take_all", "Take everything lying here", "no turn"),
        Action("creative", "✦ Rummage through the rubbish heap", "improvise")]
ROOMS = {  # (test room, seed, things on the floor, features, a fixture, choices or None for the room's own, rooms known)
    "sparse": ("lenny_quest", 3, [], 1, "", 3, 1),
    "lenny": ("lenny", 4, [], 2, "", None, 2),
    "crowded": ("hobgoblin", 5, ["healing_potion", "war_pick", "stale_bread"], 1, "chest", None, 2),
    "loot": ("lenny_quest", 3, ["healing_potion", "war_pick", "stale_bread", "torch", "chain_shirt"], 2, "", 7, 9),
    "shop": ("shop", 4, [], 0, "", None, 3),
}


# --- a room, walked into and filled in -------------------------------------------------------------------------------

def room(content, name: str):
    """A test room's target walked into, filled in as ROOMS has it, and what the story would say of it."""
    who, seed, items, features, fixture, _, known = ROOMS[name]
    state = testrooms.build(content, who, "new", seed=seed)
    target = testrooms.target(state)
    way = next(d for d, e in state.room.exits.items() if e.to == target.id)
    opening = state.room
    events = perform(state, content, f"go:{way}")
    for other in state.rooms:
        if other.distance <= known and not other.secret and other.id != state.room_id:
            other.visited = True
    here = state.room
    if name in ("sparse", "loot"):
        here.monster = None
    here.items = list(items)
    shown = [f for f in here.features if not f.hidden][:features]
    while len(shown) < features:
        shown.append(Feature(name=["a heap of rubbish", "a toppled shelf"][len(shown) % 2]))
    here.features = shown
    if fixture:
        here.fixture, here.fixture_used = fixture, False
    theme = content.themes[state.theme]
    story = [("floor", f"↓  FLOOR {state.floor} OF {state.floors_total}  ·  {theme.name.upper()}  ↓"),
             ("words", f"{theme.blurb} You stand in the {opening.name}."), ("player", f"> Go {way}")]
    for event in events:
        if event.kind == "story" and event.data.get("speaker"):
            story.append(("say", f"{event.data['title']}: “{event.text}”"))
        elif event.text:
            story.append(("words", event.text))
    if name == "crowded":
        story += [("player", "> Attack the Hobgoblin"),
                  ("roll", "⚄ attack: d20 17 + 2 might + 1 level = 20 vs 13   ✔ HIT   → 5 damage (1d6 3 + might 2)"),
                  ("roll", "⚄ Hobgoblin attacks: d20 15 + 4 attack = 19 vs 11   ✘ HIT YOU   → 6 damage (1d8 6)"),
                  ("words", "You catch the Hobgoblin under its helmet. It snarls and swings back, hard.")]
    return state, story


def choices_for(state, content, name: str, taken: set[str]) -> list[Action]:
    """The room's choices bar its ways out (the map has those) and what Here's buttons do, filled out from MORE (or
    cut) to the number ROOMS asks for."""
    own = [a for a in available_actions(state, content) if not a.id.startswith("go:") and a.id not in taken]
    wanted = ROOMS[name][5]
    if wanted is None:
        return own
    ids = {a.id for a in own}
    return (own + [a for a in MORE if a.id not in ids])[:wanted]


# --- the pieces -------------------------------------------------------------------------------------------------------

def story_text(state, content, story) -> Text:
    lexicon = Lexicon(build(state, content))
    text = Text()
    for kind, words_ in story:
        if kind == "floor":
            text.append(words_.center(60) + "\n\n", style=f"bold {PINK}")
        elif kind == "player":
            text.append(words_ + "\n", style=f"bold {ACCENT}")
        elif kind == "roll":
            text.append("  " + words_ + "\n", style="#9a9cc0")
        elif kind == "say":
            text.append("▌ ", style=PINK)
            text.append_text(highlight(words_, lexicon, "italic #e8e8f4"))
            text.append("\n\n")
        else:
            text.append_text(highlight(words_, lexicon, WORDS))
            text.append("\n\n")
    return text


class Hover(Static):
    """Text whose parts say what they are when hovered (style meta "tip")."""

    def on_mouse_move(self, event) -> None:
        tip = (getattr(self.get_style_at(event.x, event.y), "meta", None) or {}).get("tip")
        if tip != self.tooltip:
            self.tooltip = tip

    def on_leave(self, event) -> None:
        self.tooltip = None


def map_key(state) -> Text:
    """The map's key: the marks on it now, and what each means."""
    from ptg.ui.widgets import MAP_LEGEND, MAP_STYLES, legend
    from ptg.world import render_map

    lines = render_map(state)
    marks = [(glyph, MAP_STYLES.get(glyph[0], DIM), label) for glyph, label in MAP_LEGEND
             if any(glyph[0] in line for line in lines)]
    return legend(marks, 30, words=DIM)


def hover_map(state) -> Text:
    """The floor map without its key, each room's three cells ("[@]") saying where it is when hovered."""
    from ptg.ui.widgets import MAP_STYLES
    from ptg.world import render_map

    text = Text()
    for line in render_map(state):
        for ch in line:
            text.append(ch, style=MAP_STYLES.get(ch, DIM))
        text.append("\n")
    text.rstrip()
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
    for other in rooms:
        cx, cy = (other.x - min_x) * 4 + 1, (other.y - min_y) * 2
        name = other.name if other.visited else "unexplored" + (f": a {other.fixture}" if other.fixture else "")
        at = starts[cy] + cx - 1
        text.stylize(Style(meta={"tip": name + (" (you're here)" if other.id == state.room_id else "")}), at, at + 3)
    return text


def arrow(state, direction: str) -> Hover:
    """One arrow on the map's edge: lit where there's a way, saying where it goes when hovered."""
    exit_ = state.room.exits.get(direction)
    if exit_ is None:
        return Hover(Text(ARROWS[direction], style="#2e3149"), classes=f"arrow {direction}")
    there = state.rooms[exit_.to]
    where = there.name if there.visited else ("locked" if exit_.locked else there.fixture or "unexplored")
    style = "#7a3b4c" if exit_.locked else f"bold {'#5fe3ff' if there.visited else '#ffd166'}"
    return Hover(Text(ARROWS[direction], style=Style.parse(style) + Style(meta={"tip": f"Go {direction}: {where}"})),
                 classes=f"arrow {direction}")


def chips(thing, numbers, width: int) -> Text:
    """A thing's buttons, numbered, each kept whole on a line."""
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


def about(thing) -> Text:
    text = Text(thing.title, style=f"bold {PINK if thing.character else '#ffd166'}")
    if thing.status:
        text.append(f"\n{thing.status}", style=thing.style or DIM)
    return text


def here_cards(content, things, numbers, buttons: bool, columns: int, compact: bool = False) -> list:
    """What's here: someone as a wide card (portrait beside their words, always full size), things in a grid under
    them; things with no picture (what's to search) as a line of chips at the end. With `buttons`, each card has its
    own. `compact` (a crowded room, too much for full size): the things as their hand-made small pictures with their
    words beside them, so all of them show (their full pictures are on the stage, and their cards)."""
    people, pictured, plain = [], [], []
    for thing in things:
        words = Static(about(thing), classes="card-words")
        tail = [Static(chips(thing, numbers, 28), classes="card-verbs")] if buttons and thing.verbs else []
        small = compact and not thing.character
        art = Picture(thing.sprite, thing.kind, 12 if small else 24, content=content, animate=False) \
            if thing.art and thing.sprite else None
        if thing.character and art:
            people.append(Horizontal(art, Vertical(words, *tail, classes="card-side"), classes="card character"))
        elif art and small:
            pictured.append(Horizontal(art, Vertical(words, *tail, classes="card-side small"), classes="card thing"))
        elif art:
            pictured.append(Vertical(art, words, *tail, classes="card thing"))
        else:
            plain.append(thing)
    grid = Grid(*pictured, classes="here-grid")
    grid.styles.grid_size_columns = columns
    out = people + ([grid] if pictured else [])
    if plain:
        line = Text()
        for thing in plain:
            line.append(f" {thing.name} ", style="bold #ffd166 on #24284a")
            if buttons:
                line.append(" ")
                line.append_text(chips(thing, numbers, 99))
            line.append("  ")
        out.append(Static(line, classes="here-plain"))
    return out


def decision(things, numbers, choices: list[Action], grouped: bool) -> Text:
    """'What do you do?': with `grouped`, every action here, by what it's for (each thing's, then the room's); else
    the room's choices alone (the things' are on their cards). One to a line, numbered on from Here's."""
    text = Text()
    if grouped:
        for thing in things:
            if not thing.verbs:
                continue
            text.append(f"{thing.name}\n", style=f"bold {PINK if thing.character else '#ffd166'}")
            text.append_text(chips(thing, numbers, 50))
            text.append("\n")
        if text.plain:
            text.append("─" * 40 + "\n", style="#2a2d4a")
    for action in choices:
        number = numbers.setdefault(action.id, len(numbers) + 1)
        creative = action.label.startswith("✦")
        text.append(f" {number:>2} ", style=f"bold #10122a on {PINK if creative else ACCENT}")
        text.append(f"  {action.label}", style=f"italic bold {PINK}" if creative else "bold #e8e8f4")
        if action.hint:
            text.append(f"   {action.hint}", style=DIM)
        text.append("\n")
    text.rstrip()
    return text


# --- dense art: 2x3 pixels to a cell ---------------------------------------------------------------------------------

def sextant(bits: int) -> str:
    """The sextant character (U+1FB00 on) lighting the pixels in `bits` (1 top left, 2 top right, 4, 8, 16, 32 down
    the rows); the four that already exist elsewhere are those."""
    if bits in (0, 63, 21, 42):
        return {0: " ", 63: "█", 21: "▌", 42: "▐"}[bits]
    return chr(0x1FB00 + bits - 1 - (bits > 21) - (bits > 42))


def _distance(a, b) -> int:
    if a is None or b is None:
        return 0 if a is b else 10 ** 6
    return sum((x - y) ** 2 for x, y in zip(a, b))


def dense_text(img) -> Text:
    """An RGBA image 2x3 pixels to a cell. A cell has two colours: where its six pixels have more, the pair that
    misses least, each pixel taking the nearer."""
    px, text = img.load(), Text(no_wrap=True)
    for cy in range(0, img.height, 3):
        for cx in range(0, img.width, 2):
            block = []
            for dy in range(3):
                for dx in range(2):
                    x, y = cx + dx, cy + dy
                    r, g, b, a = px[x, y] if x < img.width and y < img.height else (0, 0, 0, 0)
                    block.append((r, g, b) if a >= 128 else None)
            colours = list(dict.fromkeys(block))
            if len(colours) > 2:
                count = {c: block.count(c) for c in colours}
                colours = list(min(((a, b) for i, a in enumerate(colours) for b in colours[i + 1:]),
                                   key=lambda p: sum(min(_distance(c, p[0]), _distance(c, p[1])) * count[c]
                                                     for c in colours)))
            fg, bg = (colours + [None])[:2]
            if fg is None:
                fg, bg = bg, None
            bits = sum(1 << i for i, c in enumerate(block)
                       if fg is not None and c is not None and (bg is None or _distance(c, fg) <= _distance(c, bg)))
            if fg is None:
                text.append(" ")
            else:
                text.append(sextant(bits), Style(color=RichColor.from_rgb(*fg), bgcolor=RichColor.from_rgb(*bg) if bg else None))
        text.append("\n")
    text.rstrip()
    return text


def facts(state, content, thing) -> Text:
    """Everything about a thing, for beside its picture in the frame: its name, how it is, its numbers, and its
    creator's words."""
    text = about(thing)
    numbers, desc = [], ""
    if thing.kind == "monster" and thing.sprite in content.monsters:
        monster = content.monsters[thing.sprite]
        if state.room.monster and state.room.monster.hostile:
            numbers = [f"defense {monster.defense}", f"hits +{monster.attack}", f"{monster.damage} damage"]
            numbers += [f"weak to {', '.join(monster.weak)}"] if monster.weak else []
        desc = monster.desc
    elif thing.kind == "item":
        item = content.item(thing.sprite)
        numbers = ([f"{item.damage} damage"] if item.kind == "weapon" and item.damage else []) + \
                  ([f"+{item.defense} defense"] if item.defense else []) + \
                  [powers.POWERS[p] for p in powers.powers_of(state, item) if p in powers.POWERS] + \
                  ([powers.stat_words(item.stats)] if item.stats else [])
        desc = item.desc
    for line in numbers:
        text.append(f"\n· {line}", style=WORDS)
    if desc:
        text.append(f"\n\n{desc if len(desc) <= 180 else desc[:178].rsplit(' ', 1)[0] + '…'}", style=f"italic {DIM}")
    return text


class Thumb(Vertical):
    """A thing in the strip: its picture small, underlined when it's the one in the frame; clicked, it's brought in."""

    def __init__(self, index: int, *children, **kwargs) -> None:
        super().__init__(*children, **kwargs)
        self.index = index

    def on_click(self) -> None:
        self.app.call_later(self.app.pick, self.index)


# --- the app ----------------------------------------------------------------------------------------------------------

CSS = """
Screen { background: #0b0c18; }
* { scrollbar-size-vertical: 1; scrollbar-size-horizontal: 1; scrollbar-background: #12142a;
    scrollbar-background-hover: #12142a; scrollbar-background-active: #12142a; scrollbar-color: #3d4a8c;
    scrollbar-color-hover: #6c8cff; scrollbar-color-active: #ffb000; scrollbar-corner-color: #12142a; }
#story > Static { width: 100%; }
#hud { height: 1; }
#main { height: 1fr; }
.box { border: round #3d4a8c; border-title-color: #6c8cff; padding: 0 1; }
#stage { border: round $warning; }
#story { height: 1fr; }
.card { height: auto; width: 100%; }
.card.character { margin-bottom: 1; }
.card-side { height: auto; width: 1fr; padding: 1 0 0 2; }
.card-side.small { padding: 0 0 0 1; }
.card-words, .card-verbs, .here-plain { height: auto; }
.card-verbs { margin-top: 1; }
.here-grid { grid-gutter: 1 2; height: auto; grid-rows: auto; }
.here-plain { margin-top: 1; }
#decide { border: heavy $warning; border-title-color: $warning; border-title-style: bold; padding: 0 1;
          background: #12142a; }
#choices { height: auto; }
#command { height: 1fr; min-height: 1; background: #1c2040; color: #9a9cc0; padding: 0 1; }
#nav { height: auto; width: auto; }
#nav-grid { grid-size: 3 3; grid-columns: 2 auto 2; grid-rows: 1 auto 1; height: auto; width: auto; }
#nav-map { width: auto; }
#nav-key { width: auto; max-width: 32; height: auto; }
#band > #stage { height: 100%; }
#dock { height: 1fr; margin-top: 0; }
#dock > #nav { height: 100%; }
#pack { width: 1fr; height: 100%; }
#pack-grid { grid-size: 3; grid-gutter: 0 1; grid-rows: auto; height: auto; }
.pack-tile { height: auto; }
.pack-name { height: auto; }
.arrow { content-align: center middle; width: 100%; height: 1; }
#nav-map { height: auto; }
#focus { height: auto; }
.focus-art { margin-right: 2; }
.focus-side { height: auto; width: 1fr; }
#strip { height: auto; margin-top: 1; }
.thumb { width: 12; height: auto; margin-right: 1; }
.thumb:hover { background: #1c2040; }
.thumb-art { height: auto; width: 12; }
.thumb-mark { height: 1; width: 12; color: #12142a; }
.thumb.picked > .thumb-mark { color: $warning; }
#text-side > #decide { margin-top: 1; }
#picture-side > #nav { height: 1fr; width: 100%; }
"""


class Lab(App):
    CSS = CSS
    BINDINGS = [("l", "layout", "Next layout"), ("n", "room(1)", "Next room"), ("p", "room(-1)", "Previous room"),
                ("f", "pick_next", "Next in focus"), ("d", "thumbs", "Thumbnails small/dense"),
                ("ctrl+q", "quit", "Quit")]

    def __init__(self, layout: str = "hub", room_name: str = "crowded", thumbs: str = "small") -> None:
        super().__init__()
        self.layout_name, self.room_name, self.thumbs, self.in_focus = layout, room_name, thumbs, 0
        self.content = load_content()

    def compose(self) -> ComposeResult:
        yield Hud(id="hud")
        yield Vertical(id="main")

    async def on_mount(self) -> None:
        await self.show()

    async def action_layout(self) -> None:
        self.layout_name = LAYOUTS[(LAYOUTS.index(self.layout_name) + 1) % len(LAYOUTS)]
        await self.show()

    async def action_room(self, step: int) -> None:
        names = list(ROOMS)
        self.room_name = names[(names.index(self.room_name) + step) % len(names)]
        self.in_focus = 0
        await self.show()

    async def action_pick_next(self) -> None:
        await self.pick((self.in_focus + 1) % max(1, len(self.pictured())))

    async def action_thumbs(self) -> None:
        self.thumbs = THUMBS[(THUMBS.index(self.thumbs) + 1) % len(THUMBS)]
        await self.show()

    async def pick(self, index: int) -> None:
        """Bring the strip's `index`th thing into the frame."""
        if self.layout_name != "focus":
            return
        self.in_focus = index
        frame = self.query_one("#focus")
        await frame.remove_children()
        await frame.mount(*self.focus_parts())
        for thumb in self.query(Thumb):
            thumb.set_class(thumb.index == index, "picked")
            if thumb.index == index:
                thumb.scroll_visible()

    async def show(self) -> None:
        """Build the screen afresh for this layout and room."""
        self.state, self.story = room(self.content, self.room_name)
        self.query_one(Hud).show(self.state, self.content)
        self.title = f"{self.layout_name} · {self.room_name}" + (f" · {self.thumbs}" * (self.layout_name == "focus"))
        main = self.query_one("#main")
        await main.remove_children()
        await main.mount(*getattr(self, f"layout_{self.layout_name}")())
        self.call_after_refresh(self.draw)

    # the pieces each layout places
    def stage(self) -> Static:
        box = Static(id="stage", classes="box")
        box.border_title = f"✦ {self.state.room.name}"
        return box

    def story_box(self) -> VerticalScroll:
        box = VerticalScroll(Static(story_text(self.state, self.content, self.story)), id="story", classes="box")
        box.border_title = "Story"
        return box

    def here(self, buttons: bool, columns: int, rows: int = 0) -> VerticalScroll:
        """What's here; given the `rows` it has, compact if its things wouldn't all fit at full size."""
        self.numbers: dict[str, int] = {}
        self.things = things_here(self.state, self.content)
        pictured = [t for t in self.things if t.art and t.sprite and not t.character]
        people = sum(1 for t in self.things if t.character)
        need = 13 * people + -(-len(pictured) // columns) * 17 + (2 if len(pictured) < len(self.things) - people else 0)
        compact = bool(rows) and need > rows
        box = VerticalScroll(*here_cards(self.content, self.things, self.numbers, buttons, columns, compact),
                             id="here", classes="box")
        box.border_title = f"Here · {len(self.things)}"
        return box

    def decide(self, grouped: bool) -> Vertical:
        """The decision square: the actions, and the command line under them taking the rows they leave."""
        taken = {a.id for t in self.things for a in t.verbs}
        self.choices = choices_for(self.state, self.content, self.room_name, taken)
        listed = decision(self.things, self.numbers, self.choices, grouped)
        box = Vertical(Static(listed, id="choices"), Static(Text("› type a number, or anything you want to try…"),
                                                            id="command"), id="decide")
        box.border_title = "What do you do?"
        return box

    def nav(self) -> Vertical:
        """The floor map with its arrows on its edges (one box), its key under it; hover a room or an arrow."""
        grid = Grid(Static(""), arrow(self.state, "north"), Static(""),
                    arrow(self.state, "west"), Hover(hover_map(self.state), id="nav-map"), arrow(self.state, "east"),
                    Static(""), arrow(self.state, "south"), Static(""), id="nav-grid")
        box = Vertical(grid, Static(map_key(self.state), id="nav-key"), id="nav", classes="box")
        box.border_title = f"Floor {self.state.floor}/{self.state.floors_total}"
        return box

    def pack(self) -> VerticalScroll:
        """What you carry, as the hand-made small pictures (the 12-px ones are drawn for this), each with how many;
        what you have on, marked."""
        player, counts = self.state.player, {}
        for key in [player.weapon, *([player.armor] if player.armor else []), *self.state.player.inventory]:
            counts[key] = counts.get(key, 0) + 1
        tiles = []
        for key, count in counts.items():
            on = key in (player.weapon, player.armor)
            label = Text(("⚔ " if key == player.weapon else "⛨ " if on else "") + self.content.item(key).name,
                         style=f"bold {'#ffd166' if on else WORDS}")
            if count > 1:
                label.append(f" ×{count}", style=DIM)
            tiles.append(Vertical(Picture(key, "item", 12, content=self.content, animate=False),
                                  Static(label, classes="pack-name"), classes="pack-tile"))
        grid = Grid(*tiles, id="pack-grid")
        box = VerticalScroll(grid, id="pack", classes="box")
        box.border_title = f"Pack · ¤ {player.gold}"
        return box

    def layout_hub(self):
        """The picture over the story; beside them, what's here, the decision square and the map."""
        here, decide, nav = self.here(buttons=False, columns=3), None, None
        decide, nav = self.decide(grouped=True), self.nav()
        left = Vertical(self.stage(), self.story_box(), id="left")
        right = Vertical(here, decide, nav, id="right")
        return [Horizontal(left, right, id="row")]

    def pictured(self) -> list:
        """What's here with a picture: the strip's things, someone first."""
        things = [t for t in self.things if t.art and t.sprite]
        return sorted(things, key=lambda t: not t.character)

    def thumb(self, thing) -> Static:
        if self.thumbs == "dense":
            name = f"item_{thing.sprite}" if thing.kind == "item" else thing.sprite
            found = sprites.frames(name)
            if found:
                return Static(dense_text(found[0]), classes="thumb-art")
        return Picture(thing.sprite, thing.kind, 12, content=self.content, animate=False, classes="thumb-art")

    def focus_parts(self) -> list:
        """The frame: the thing in focus at full size, its words and its buttons beside it."""
        things = self.pictured()
        if not things:
            return [Static(Text("Nothing here to look at.", style=DIM), classes="focus-side")]
        thing = things[min(self.in_focus, len(things) - 1)]
        side = [Static(facts(self.state, self.content, thing), classes="card-words")]
        if thing.verbs:
            room = self.size.width - round(self.size.width * 0.54) - 4 - 26  # (the right side, bar the picture)
            side.append(Static(chips(thing, self.numbers, max(16, room)), classes="card-verbs"))
        return [Picture(thing.sprite, thing.kind, 24, content=self.content, pose=thing.pose, loop=thing.loop,
                        classes="focus-art"), Vertical(*side, classes="focus-side")]

    def here_focus(self) -> Vertical:
        """What's here: the frame over the strip, then what has no picture (what's to search) as chips."""
        self.numbers = {}
        self.things = things_here(self.state, self.content)
        for thing in self.pictured():  # (number every button, the frame's and the strip's, the same way each time)
            for action in thing.verbs:
                self.numbers.setdefault(action.id, len(self.numbers) + 1)
        frame = Horizontal(*self.focus_parts(), id="focus")
        thumbs = [Thumb(i, self.thumb(t), Static("▀" * 12, classes="thumb-mark"),
                        classes="thumb" + (" picked" if i == self.in_focus else ""))
                  for i, t in enumerate(self.pictured())]
        for thumb, thing in zip(thumbs, self.pictured()):
            thumb.tooltip = thing.name
        parts = [frame, HorizontalScroll(*thumbs, id="strip")] if len(thumbs) > 1 else [frame]
        plain = [t for t in self.things if not (t.art and t.sprite)]
        if plain:
            line, used, width = Text(), 0, self.size.width - round(self.size.width * 0.54) - 4
            for thing in plain:
                group = Text(f" {thing.name} ", style="bold #ffd166 on #24284a") + Text(" ")
                group.append_text(chips(thing, self.numbers, 99))
                if used and used + group.cell_len > width:  # (a thing and its buttons kept on one line)
                    line.append("\n")
                    used = 0
                line.append_text(group + Text("  "))
                used += group.cell_len + 2
            parts.append(Static(line, classes="here-plain"))
        box = Vertical(*parts, id="here", classes="box")
        box.border_title = f"Here · {len(self.things)}"
        return box

    def layout_focus(self):
        """Words on the left (the room's picture, the story, the decision square under it); pictures on the right
        (the frame and its strip, the map)."""
        here = self.here_focus()
        decide, nav = self.decide(grouped=False), self.nav()
        left = Vertical(self.stage(), self.story_box(), decide, id="text-side")
        right = Vertical(here, nav, id="picture-side")
        return [Horizontal(left, right, id="row")]

    def layout_band(self):
        """The room across the top (its picture, what's here beside it: a narrow column for a room with little in it,
        the picture wider); under it the story, and beside that the decision square over the map."""
        few = len(things_here(self.state, self.content)) <= 2
        here = self.here(buttons=True, columns=1 if few else 2, rows=round(self.size.height * 0.44) - 2)
        here.set_class(few, "few")
        decide, nav = self.decide(grouped=False), self.nav()
        top = Horizontal(self.stage(), here, id="band")
        bottom = Horizontal(self.story_box(), Vertical(decide, Horizontal(nav, self.pack(), id="dock"), id="right"),
                            id="lower")
        return [top, bottom]

    def draw(self) -> None:
        w, h = self.size
        decide_rows = MOST_CHOICES + 1 + (sum(2 for t in self.things if t.verbs) + 1  # (+1: the command line)
                                          if self.layout_name == "hub" else 0)
        decide = self.query_one("#decide")
        decide.styles.height = decide_rows + 2
        if self.layout_name == "focus":
            self.query_one("#text-side").styles.width = round(w * 0.54)
            self.query_one("#picture-side").styles.width = w - round(w * 0.54)
            self.query_one("#stage").styles.height = round(h * 0.40)
            self.query_one("#here").styles.height = "auto"
        elif self.layout_name == "hub":
            self.query_one("#left").styles.width = round(w * 0.56)
            self.query_one("#right").styles.width = w - round(w * 0.56)
            self.query_one("#stage").styles.height = round(h * 0.44)
            here = self.query_one("#here")
            here.styles.height = "auto"
            here.styles.max_height = h - decide_rows - 2 - 14
            self.query_one("#right").styles.align_vertical = "bottom" if self.layout_name == "hub" else "top"
        else:
            self.query_one("#band").styles.height = round(h * 0.44)
            here = self.query_one("#here")
            self.query_one("#stage").styles.width = "1fr"
            here.styles.width = 34 if here.has_class("few") else w - round(w * 0.56)
            self.query_one("#lower").styles.height = "1fr"
            self.query_one("#story").styles.width = round(w * 0.56)
            self.query_one("#right").styles.width = "1fr"
        self.set_timer(0.2, self.paint)  # (once the sizes above are laid out)

    def paint(self) -> None:
        self.query_one("#story").scroll_end(animate=False)
        stage = self.query_one("#stage")
        w, h = stage.content_size
        stage.update(picture_text(self.state, self.content, max(8, w), 2 * max(4, h)) or Text(""))
        stage.styles.border = ("round", look_of(self.state.theme).accent)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--layout", default="hub", choices=LAYOUTS)
    parser.add_argument("--room", default="crowded", choices=list(ROOMS))
    parser.add_argument("--thumbs", default="small", choices=THUMBS)
    args = parser.parse_args(sys.argv[1:])
    Lab(args.layout, args.room, args.thumbs).run()
