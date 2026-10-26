"""The game screen in tabs, the desktop layout, set out like an illustrated story book: the words on the left page
and the pictures on the right.

The left page is the story in its box (whose border lights up in the turn's colour, as it always has), ending about
two thirds of the way down so what just happened is where the eye already is, and right under it the decision:
every choice numbered, one to a line, and the command line (one line: it doesn't wrap). Under that, docked, the
last few things that happened, with the game's notifications at its head for a few seconds (its border lit),
rather than boxes floating over the screen.

The right page is the room's picture in its frame (red in a fight), the arrows beside the ways out in words, and one
pane with tabs, each in its own colour: Here, Map, Pack, Sheet, Journal, Bestiary. They are the panels F2-F7 used to
open over the game: each key brings its tab into the pane, and pressed again (or the ⤢ at the end of the tabs) opens
the panel as it was, in full. A tab stays where you put it; only a fight starting brings Here back. Here is never
bare: what it doesn't need for whoever and whatever is in the room, it fills with the floor map, the quests open and
the last few things that happened.

Everything a turn does (the story, the dice, the animations, the border's flash) is GameScreen's: this only lays the
screen out differently and fills the pane. The footer has every key, and at its end who's narrating.

Chosen by Config.layout ("tabs", the default, or "classic"); a touch screen, or one too small for it when the game
begins, gets the classic one (see game_screen).
"""

from __future__ import annotations

import time

from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Grid, Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Footer, Input, Static

from .. import config, npcs, powers, sheet, statuses
from ..events import Action
from ..room_picture import look_of
from ..world import map_glyph, render_map
from .game_screen import GameScreen
from .here import DEAD_VERB, DIE, PLAIN_VERB, VERB_STYLES, Thing, verb_lines
from .panels import CharacterScreen, item_note
from .plan import Plan
from .widgets import (
    ARROWS,
    MAP_LEGEND,
    MAP_STYLES,
    ChoiceItem,
    Clickable,
    ClickableBox,
    DPad,
    Hud,
    Picture,
    StoryLine,
    highlight,
    legend,
)

TABS = [("here", "Here", "F4"), ("map", "Map", "F5"), ("pack", "Pack", "F2"), ("sheet", "Sheet", "F3"),
        ("journal", "Journal", "F7"), ("bestiary", "Bestiary", "F6")]
PANEL_TAB = {"look": "here", "map": "map", "inventory": "pack", "character": "sheet", "journal": "journal",
             "bestiary": "bestiary"}  # the panel each key used to open, and the tab it opens now
TAB_PANEL = {tab: panel for panel, tab in PANEL_TAB.items()}
TAB_LABEL = {key: label for key, label, _ in TABS}
MOST_CHOICES = 7  # the decision's rows for choices: the most a room usually has (more scroll)
MIN_COLUMNS, MIN_ROWS = 110, 32  # smaller than this when a run begins, and it's the classic screen
SIDE_SHARE, SIDE_MIN, SIDE_MAX = 0.48, 62, 100  # the right page's width
STORY_SHARE = 0.6  # of the rows between the status bar and the footer: the story's
DECIDE_ROWS = 12  # the decision's box: its frame, up to ten choices and the command line (one line: it doesn't wrap)
LATELY_LEAST = 2  # lines: a docked journal shorter than this isn't worth its frame, and the story takes its rows
STAGE_SHARE = 0.38  # of those rows: the most the room's picture takes
STAGE_SHAPE = 4.8  # columns per row (see plan.py)
TAB_COLOURS = {"here": "#ffb000", "map": "", "pack": "#4cff8a", "sheet": "#ff4f9a", "journal": "#6c8cff",
               "bestiary": "#ff7b39"}  # each tab's own (the map's is the floor's: see tab_colour)
NOTE_SECONDS = 8  # how long a notification stays at the head of the docked journal
NOTE_COLOURS = {"information": "#ffd166", "warning": "#ff7b39", "error": "#ff4b4b"}
LATELY = 4  # the journal's last lines in Here, when there's no docked journal and Here has room
JOURNAL_SHOWN = 150

WORDS, DIM, FAINT, ACCENT, PINK, GOLD = "#c8c8e0", "#6c6f99", "#2a2d4a", "#ffb000", "#ff4f9a", "#ffd166"


def game_screen(game, fresh: bool, width: int, height: int) -> GameScreen:
    """The game screen to play `game` on: the tabs, unless the player chose the classic one, plays by touch, or the
    terminal is too small for tabs."""
    if game.config.layout == "tabs" and not config.touch() and width >= MIN_COLUMNS and height >= MIN_ROWS:
        return TabsScreen(game, fresh)
    return GameScreen(game, fresh)


# --- what the pane shows ---------------------------------------------------------------------------------------------

def facts(state, content, thing: Thing) -> Text:
    """Everything about a thing, beside its picture: its name, how it is, its numbers, and its maker's words."""
    text = Text(f"{thing.badge} " if thing.badge else "", style=f"bold {GOLD}")
    text.append(thing.name, style=f"bold {PINK if thing.character else GOLD}")
    if thing.status:
        text.append(f"\n{thing.status}", style=thing.style or DIM)
    numbers, desc = [], ""
    if thing.kind == "monster" and thing.sprite in content.monsters:
        monster = content.monsters[thing.sprite]
        here = state.room.monster
        if here is not None and here.key == monster.key and here.hostile:
            numbers = [f"defense {monster.defense + here.defense_mod}", f"hits +{monster.attack + here.attack_mod}",
                       f"{monster.damage} damage"]
            numbers += [f"weak to {', '.join(monster.weak)}"] if monster.weak else []
        desc = monster.desc
    elif thing.kind == "item" and thing.sprite in content.items:
        item = content.item(thing.sprite)
        numbers = [item_note(content, item.key)] + [powers.POWERS[p] for p in powers.powers_of(state, item)
                                                    if p in powers.POWERS and p in powers.CARRYING]
        desc = item.desc
    for line in dict.fromkeys(n for n in numbers if n):
        text.append(f"\n· {line}", style=WORDS)
    if desc:
        short = desc if len(desc) <= 200 else desc[:198].rsplit(" ", 1)[0] + "…"
        text.append(f"\n\n{short}", style=f"italic {DIM}")
    return text


def verb_button(action: Action, numbers: dict[str, int], click: str) -> Clickable:
    """A button, as Here's tiles draw them: its number (as typed), its word, in its verb's colour."""
    number = numbers.get(action.id)
    face = DIE.get(action.id)
    label = f"{number} {face or action.label}" if number else face or action.label
    word = action.label.removesuffix("…").split(" ")[0]
    live = bool(action.id)
    colour = VERB_STYLES.get(word, PLAIN_VERB) if live else DEAD_VERB
    button = Clickable(Text(f" {label} ", style=f"reverse {colour}" if live else DEAD_VERB), click, classes="verb")
    if action.hint:
        button.tooltip = action.hint
    return button


def short_name(name: str, width: int) -> str:
    """A room's name in `width` characters: whole if it fits, else its first words, else cut."""
    name = name.removeprefix("The ")
    if len(name) <= width:
        return name
    words = name.split()
    while len(words) > 1 and len(" ".join(words)) > width:
        words.pop()
    name = " ".join(words)
    return name if len(name) <= width else name[:width - 1] + "…"


def known_rooms(state) -> list:
    """The rooms on your map (as world.render_map has them)."""
    mapped = state.mapped_floor == state.floor
    known = {r.id for r in state.rooms if r.visited or (mapped and (not r.secret or r.exits))}
    for room_id in list(known):
        known.update(e.to for e in state.rooms[room_id].exits.values())
    known.update(r.id for r in state.rooms if r.told or any(f.told for f in r.features))
    return [state.rooms[i] for i in sorted(known)]


STEP_X, STEP_Y, NAME_WIDTH = 14, 4, 12  # a room's place on the big map, and its name's room under its mark


def big_map(state, width: int, height: int) -> Text | None:
    """The floor drawn big: each room's mark with its name under it, the passages long, faint dots where a room could
    be (like graph paper). Each room says where it is when hovered, and one you can get back to takes you there when
    clicked (quick travel: rules.journey). None if the floor's too big for the room it has."""
    from ..rules import journey

    rooms = known_rooms(state)
    mapped = state.mapped_floor == state.floor
    min_x, max_x = min(r.x for r in rooms), max(r.x for r in rooms)
    min_y, max_y = min(r.y for r in rooms), max(r.y for r in rooms)
    cols, rows = (max_x - min_x) * STEP_X + NAME_WIDTH + 1, (max_y - min_y) * STEP_Y + 2
    if cols > width or rows > height:
        return None
    grid = [[(" ", Style.parse(DIM)) for _ in range(cols)] for _ in range(rows)]
    for gy in range(0, rows, STEP_Y):
        for gx in range(NAME_WIDTH // 2, cols, STEP_X):
            grid[gy][gx] = ("·", Style.parse(FAINT))
    for room in rooms:
        cx, cy = (room.x - min_x) * STEP_X + NAME_WIDTH // 2, (room.y - min_y) * STEP_Y
        here = room.id == state.room_id
        glyph = map_glyph(state, room)
        name = room.name if room.visited else "unexplored" + (f": a {room.fixture}" if room.fixture else "")
        reachable = not here and journey(state, room.id) is not None
        tip = Style(meta={"tip": name + (" (you're here)" if here else " (click to travel there)" if reachable else ""),
                          **({"@click": f"screen.travel({room.id})"} if reachable else {})})
        left, right = "{}" if room.secret else "[]"
        for dx, ch in ((-1, left), (0, glyph), (1, right)):
            grid[cy][cx + dx] = (ch, Style.parse(f"bold {ACCENT}" if here else MAP_STYLES.get(ch, DIM)) + tip)
        if room.visited:
            label = short_name(room.name, NAME_WIDTH)
            for i, ch in enumerate(label):
                grid[cy + 1][cx - len(label) // 2 + i] = (ch, Style.parse(f"bold {ACCENT}" if here else WORDS) + tip)
        if not (room.visited or mapped):
            continue
        for direction, exit_ in room.exits.items():
            span = {"east": [(cy, x) for x in range(cx + 2, cx + STEP_X - 1)],
                    "west": [(cy, x) for x in range(cx - STEP_X + 2, cx - 1)],
                    "south": [(y, cx) for y in range(cy + 2, cy + STEP_Y)],
                    "north": [(y, cx) for y in range(cy - STEP_Y + 2, cy)]}[direction]
            across = direction in ("east", "west")
            line = ("═" if across else "║") if exit_.locked else ("─" if across else "│")
            style = Style.parse("#7a3b4c" if exit_.locked else "#3d4a8c")
            for y, x in span:
                if 0 <= y < rows and 0 <= x < cols and grid[y][x][0] in " ·":
                    grid[y][x] = (line, style)
    text = Text()
    for row in grid:
        for ch, style in row:
            text.append(ch, style=style)
        text.append("\n")
    text.rstrip()
    return text


def small_map(state) -> Text:
    """The floor map as world.render_map draws it, each room saying where it is when hovered (and taking you there
    when clicked, if you can get back to it: rules.journey)."""
    from ..rules import journey

    text = Text()
    for line in render_map(state):
        for ch in line:
            text.append(ch, style=MAP_STYLES.get(ch, DIM))
        text.append("\n")
    text.rstrip()
    rooms = known_rooms(state)
    min_x, min_y = min(r.x for r in rooms), min(r.y for r in rooms)
    starts = [0]
    for line in text.plain.split("\n"):
        starts.append(starts[-1] + len(line) + 1)
    for room in rooms:
        cx, cy = (room.x - min_x) * 4 + 1, (room.y - min_y) * 2
        name = room.name if room.visited else "unexplored" + (f": a {room.fixture}" if room.fixture else "")
        at = starts[cy] + cx - 1
        here = room.id == state.room_id
        reachable = not here and journey(state, room.id) is not None
        text.stylize(Style(meta={"tip": name + (" (you're here)" if here else " (click to travel there)" if reachable
                                                 else ""),
                                 **({"@click": f"screen.travel({room.id})"} if reachable else {})}), at, at + 3)
    return text


def map_key(state) -> Text:
    """The map's key: the marks on it now, and what each means."""
    lines = render_map(state)
    marks = [(glyph, MAP_STYLES.get(glyph[0], DIM), label) for glyph, label in MAP_LEGEND
             if any(glyph[0] in line for line in lines)]
    return legend(marks, 40, words=DIM)


def steps_to(state, goal: int) -> int | None:
    """How many rooms from here to `goal`, through the doors you know of; None if no way's known."""
    mapped = state.mapped_floor == state.floor
    seen, frontier, steps = {state.room_id}, [state.room_id], 0
    while frontier:
        if goal in frontier:
            return steps
        ahead = []
        for room_id in frontier:
            room = state.rooms[room_id]
            if room.visited or mapped:
                for exit_ in room.exits.values():
                    if exit_.to not in seen:
                        seen.add(exit_.to)
                        ahead.append(exit_.to)
        frontier, steps = ahead, steps + 1
    return None


def map_notes(state, content) -> Table:
    """Under the map: what you're after on this floor and how far it is, whose stories are open, the tips you've had
    (something hidden, a secret room, a draft, the floor's map), and the key."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style=f"bold {DIM}", no_wrap=True)
    table.add_column(ratio=1)
    mapped = state.mapped_floor == state.floor
    goal = next((r for r in state.rooms if (r.is_boss if state.boss_floor else r.fixture == "stairs")), None)
    what = Text("▸ ", style=ACCENT)
    if goal and (goal.visited or mapped):
        steps = steps_to(state, goal.id)
        away = "you're there" if steps == 0 else f"{steps} room{'s' * (steps != 1)} from here" if steps else \
            "no way there known yet"
        what.append(f"{'The boss' if last else 'The stairs down'}: ", style="bold #e8e8f4")
        what.append(goal.name, style="#5fe3ff")
        what.append(f" · {away}", style=DIM)
    else:
        what.append("Find the " + ("boss's lair" if last else "stairs down"), style="bold #e8e8f4")
        what.append("  · not found yet", style=DIM)
    table.add_row("GOAL", what)
    for n, (_, line, still) in enumerate(npcs.quest_log(state, content)):
        table.add_row("QUESTS" if n == 0 else "", Text("★ " if still else "✓ ", style=PINK if still else DIM)
                      + Text(line, style=WORDS if still else DIM))
    tips = []
    for room in state.rooms:
        for feature in room.features:
            if feature.told and not feature.searched:
                tips.append(Text("$ ", style=GOLD) + Text(f"Something hidden in the {feature.name}, in the "
                                                          f"{room.name}", style=WORDS)
                            + Text(f" · {feature.told} said so", style=DIM))
        if room.secret and room.told and not room.visited:
            tips.append(Text("✧ ", style=GOLD) + Text("A secret room on this floor", style=WORDS)
                        + Text(f" · {room.told} said so", style=DIM))
        if room.draft and not room.secret and room.visited:
            tips.append(Text("≈ ", style="#5fe3ff") + Text(f"A draft through the {room.draft} wall of the "
                                                           f"{room.name}", style=WORDS))
    if mapped:
        tips.append(Text("⌘ ", style=ACCENT) + Text("You have this floor's map: every room and door is on it.",
                                                    style=WORDS))
    for n, tip in enumerate(tips or [Text("None yet: ask around, search, listen at walls.", style=DIM)]):
        table.add_row("TIPS" if n == 0 else "", tip)
    table.add_row("KEY", map_key(state))
    return table


def status_lines(state, content) -> Table:
    """Everything the status bar shows in a glyph, said in full: health (what ails you, and what guards you against
    it), defense, Fate, gold, souls, bombs, keys, the boss's key, your level and how far to the next, where you are
    and the turn."""
    player = state.player
    theme = content.themes[state.theme]
    table = Table.grid(padding=(0, 2))
    table.add_column(no_wrap=True)
    table.add_column(style="bold #e8e8f4", no_wrap=True, justify="right")
    table.add_column(style=DIM)

    def row(glyph: str, colour: str, label: str, value: str, note: str = "") -> None:
        table.add_row(Text.assemble((f"{glyph} ", colour), (label, WORDS)), value, note)

    row("♥", "#ff4b4b", "Health", f"{player.hp}/{player.max_hp}", "at 0 the run ends")
    for key in player.statuses:
        status = statuses.DEFS[key]
        row(status.icon, status.colour, status.name, "yes", statuses.effects(status))
    for key, charges in player.guards.items():
        row("✚", "#5fe3ff", f"Guard against {statuses.WORDS.get(key, (key, key))[1].removeprefix('the ')}",
            str(charges), "the next times it would take hold, it doesn't")
    row("⛨", "#6c8cff", "Defense", str(player.defense(content)), "what a blow must roll to hit you")
    row("✦", GOLD, "Fate", f"{player.fate}/{player.max_fate()}", "spend one to roll a die again")
    row("¤", ACCENT, "Gold", str(player.gold), "for shops, and to calm some")
    row("☽", "#5fe3ff", "Souls", str(state.souls), "taken home to the campfire, win or lose")
    row("●", "#ff7b39", "Bombs", str(player.bombs), "throw one, or blow a wall open")
    row("⚷", "#c0cbdc", "Small keys", str(player.keys), "each opens a shop's door")
    key_item = content.items.get(theme.key_item)
    if key_item:
        has = theme.key_item in player.inventory
        row("♀", ACCENT if has else DIM, key_item.name, "yes" if has else "not yet", "opens the boss's door")
    next_xp = player.next_level_xp()
    row("★", PINK, "Level", str(player.level), f"{player.xp} XP" + (f", next at {next_xp}" if next_xp else ", the most"))
    row("↓", "#6c8cff", "Floor", f"{state.floor}/{state.floors_total}", f"{theme.name} · turn {state.turn}")
    return table


def sheet_text(state, content) -> Table:
    """Your numbers, as sheet.py sums them: stats with what they're made of, then what you add to each roll."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style=f"bold {ACCENT}", no_wrap=True)
    table.add_column(style="bold #e8e8f4", no_wrap=True, justify="right")
    table.add_column(style=DIM)
    for line in [*[sheet.stat_line(state, content, stat) for stat in sheet.STATS], sheet.defense_line(state, content),
                 sheet.damage_line(state, content)]:
        parts = [f"{p.value:+d} {p.name}" if p.value else p.name for p in line.parts if p.name != "base"]
        table.add_row(line.label, str(line.total), " · ".join(([line.note] if line.note else []) + parts))
    rolls = Table.grid(padding=(0, 2))
    rolls.add_column(style=WORDS, no_wrap=True)
    rolls.add_column(style="bold #e8e8f4", no_wrap=True, justify="right")
    rolls.add_column(style=DIM)
    for line in sheet.roll_lines(state, content):
        rolls.add_row(line.label, f"{line.total:+d}", line.note)
    return table, rolls


def rule(title: str, width: int, colour: str = PINK) -> Text:
    """A section's heading in the pane: its name, then a faint line to the edge."""
    text = Text(f"{title} ", style=f"bold {colour}")
    text.append("─" * max(0, width - len(title) - 1), style=FAINT)
    return text


# --- the screen -------------------------------------------------------------------------------------------------------

class TabsScreen(GameScreen):
    """The game screen in tabs (see the module's docstring): its layout and its pane; the turns are GameScreen's."""

    # The footer, all of it: F2-F7 by their tabs' names.
    BINDINGS = [
        Binding("f1", "panel('help')", "Help"),
        *[Binding(key, f"panel('{panel}')", TAB_LABEL[tab]) for key, panel, tab in (
            ("f2", "inventory", "pack"), ("f3", "character", "sheet"), ("f4", "look", "here"), ("f5", "map", "map"),
            ("f6", "bestiary", "bestiary"), ("f7", "journal", "journal"))],
        Binding("escape", "leave", "Title"),
        Binding("pageup", "story_page(-1)", "Scroll up", show=False),
        Binding("pagedown", "story_page(1)", "Scroll down", show=False),
    ]

    def __init__(self, game, fresh: bool) -> None:
        super().__init__(game, fresh)
        self.tab = "here"
        self.where_was: tuple | None = None  # the room (and whether a fight was on) the tab was last chosen for
        self.focus = {"here": "", "pack": "", "bestiary": ""}  # the thing in each tab's frame, by its id
        self.pack_items: list[tuple[str, str, list[Action], bool]] = []
        self.pane_shown: tuple | None = None
        self.notes: list[tuple[str, str, str, float]] = []  # notifications in the docked journal: (title, words,
        # severity, until when)
        self.lately_lines = 0

    def compose(self) -> ComposeResult:
        with Horizontal(id="hud-row"):
            yield Hud(id="hud")
            yield Static(id="hud-short")
            yield Clickable(Text(" ☰ "), "screen.menu()", id="hud-menu")
        with Horizontal(id="main"):
            with Vertical(id="left"):  # the words
                yield VerticalScroll(id="story")
                with Vertical(id="decide"):
                    yield VerticalScroll(id="choices")
                    yield Input(id="command", placeholder="Type a number, or anything you want to try…")
                yield StoryLine(id="lately")
            with Vertical(id="side"):  # the pictures
                with Center(id="stage-box"):
                    with ClickableBox(action="screen.stage_card()", id="stage"):
                        yield Static(id="stage-art")
                with Horizontal(id="pane-head"):
                    yield DPad(id="dpad")
                    yield Static(id="ways-words")
                with Horizontal(id="tab-row"):
                    yield Static(id="tab-bar")
                    yield Clickable(Text(" ⤢ "), "screen.expand()", id="tab-expand")
                yield VerticalScroll(id="pane")
        with Vertical(id="shims"):  # (what GameScreen's turns look for, that this layout hasn't)
            yield Vertical(id="here")
            yield Vertical(id="here-strip")
            yield Static(id="map")
            yield Horizontal(id="ways")
        with Horizontal(id="footer-row"):  # the keys, and at the end who's narrating
            yield Footer()
            yield Static(id="footer-narrator")

    def on_mount(self) -> None:
        # (GameScreen's own on_mount runs first by itself, as Textual calls each class's: calling it again here would
        # tell the opening twice)
        self.query_one("#footer-narrator", Static).update(self.game.llm.name if self.game.llm else "offline narrator")
        self.query_one("#tab-expand").tooltip = "Open this in full"
        for box in ("#pane", "#pane-head", "#tab-row", "#decide", "#tab-expand", "#side", "#left"):
            self.query_one(box).can_focus = False

    # --- the layout ---

    def relayout(self) -> None:
        """Share the screen out: the right page a share of the width (within bounds); on the left the story most of
        the height (STORY_SHARE) and the decision the rest; on the right the room's picture as tall as its shape asks
        (to a share), the head, the tabs and the pane the rest."""
        if self._resize_timer is not None:
            self._resize_timer.stop()
            self._resize_timer = None
        width, height = self.size
        if not width:
            return
        side = max(SIDE_MIN, min(SIDE_MAX, round(width * SIDE_SHARE)))
        rows = height - 2  # (less the status bar and the footer)
        stage_width = side - 4
        stage_rows = min(30, round(stage_width / STAGE_SHAPE), round(STAGE_SHARE * rows))
        stage_width = min(stage_width, round(stage_rows * STAGE_SHAPE * 1.3))
        story = round(STORY_SHARE * rows)
        lately = rows - story - DECIDE_ROWS - 2  # (its lines, inside its frame)
        if lately < LATELY_LEAST:
            story, lately = rows - DECIDE_ROWS, 0
        self.lately_lines = lately
        pane = rows - (stage_rows + 2) - 3 - 1 - 2  # (less the picture's frame, the head, the tabs, the pane's frame)
        self.plan = Plan(width, height, True, False, False, side, stage_rows, stage_width, MOST_CHOICES, 0, pane,
                         story - 2)
        self.query_one("#side").styles.width = side
        box = self.query_one("#story")
        box.styles.height = story
        box.border_title, box.border_subtitle = "✦ Story", ""  # (who's narrating is at the footer's end)
        self.query_one("#decide").styles.height = DECIDE_ROWS
        self.refresh_lately()
        self.refresh_hud()
        self.refresh_stage()
        self.refresh_here()
        self.refresh_choices()
        self._place_toasts()

    refresh_panels = relayout

    def refresh_lately(self) -> None:
        """The docked journal under the decision: the last few things that happened, newest last, a roll's line dim.
        Hidden on a screen with no rows for it."""
        box = self.query_one("#lately", StoryLine)
        box.display = self.lately_lines > 0
        if not box.display:
            return
        box.styles.height = self.lately_lines + 2
        box.border_title = "✦ Lately"
        now = time.monotonic()
        self.notes = [note for note in self.notes if note[3] > now]
        box.set_class(bool(self.notes), "noted")
        lexicon = self.lexicon()
        text = Text()
        notes = self.notes[-self.lately_lines:]
        for title, words, severity, _ in reversed(notes):  # (the newest first, over the journal)
            colour = NOTE_COLOURS.get(severity, GOLD)
            text.append(f"{title}: " if title else "", style=f"bold {colour}")
            text.append(words + "\n", style=colour)
        room = self.lately_lines - len(notes)
        for line in self.game.state.journal[-room:] if room > 0 else []:
            roll = line.startswith("⚄ ")
            text.append_text(highlight(line if roll else "· " + line, lexicon, DIM if roll else WORDS))
            text.append("\n")
        text.rstrip()
        box.update(text or Text("Nothing yet.", style=DIM))

    def notify(self, message: str, *, title: str = "", severity: str = "information", timeout: float | None = None,
               markup: bool = True) -> None:
        """A notification from the game (a secret found, a trait earned, "Esc again for the title"): at the head of
        the docked journal for a few seconds, its border lit, rather than a box floating over the screen. With no
        docked journal (a short screen), a toast as ever."""
        if not self.lately_lines:
            return super().notify(message, title=title, severity=severity, timeout=timeout, markup=markup)
        seconds = timeout or NOTE_SECONDS
        self.notes.append((title, str(message), severity, time.monotonic() + seconds))
        self.refresh_lately()
        self.set_timer(seconds + 0.1, self.refresh_lately)

    def _place_toasts(self) -> None:
        """Notifications on the left page, at its foot (over the docked journal): under the choices, never over the
        story's newest lines or the pictures."""
        for rack in self.query("ToastRack"):
            rack.styles.margin = (0, 0, 2, 0)  # (the footer and the box's frame)
            rack.styles.width = self.size.width - (self.plan.side if self.plan else 0) - 3

    def refresh_stage(self) -> None:
        """The room's picture in its frame on the right page, titled with the room's name: the floor's colour, red in a
        fight."""
        plan, game = self.plan, self.game
        state, room = game.state, game.state.room
        monster = room.monster
        fight = bool(monster and monster.hostile and monster.hp > 0)
        self.set_class(fight, "combat")
        shown = (plan.stage_width, plan.stage_rows, state.floor, state.room_id, tuple(room.items),
                 (monster.key, monster.hostile) if monster and monster.hp > 0 else None, room.fixture_used,
                 tuple(f.searched for f in room.features), self._sprites_on())
        if shown != self.stage_shown:
            self.stage_shown = shown
            self.draw_stage(plan.stage_width, 2 * plan.stage_rows)
        stage = self.query_one("#stage")
        stage.tooltip = "Click to look around"
        colour = "#ff4b4b" if fight else look_of(state.theme).accent
        stage.border_title = f"✦ {room.name}" + ("  ⚔ a fight!" if fight else "")
        stage.styles.border = ("round", colour)
        stage.styles.border_title_color = colour
        stage.set_class(fight, "combat")

    def refresh_here(self) -> None:
        """Who and what is here, numbered as before; the ways out in words beside the arrows; and the pane drawn, if
        what it shows has changed. The tab stays as you left it: only a fight starting brings Here in (once, as it
        starts), and a new room puts Here's frame back on its first thing."""
        state = self.game.state
        self.gather_things()
        monster = state.room.monster
        fight = bool(monster and monster.hostile and monster.hp > 0)
        where = (state.floor, state.room_id, fight)
        if where != self.where_was:
            was = self.where_was
            if was is None or (state.floor, state.room_id) != was[:2]:
                self.focus["here"] = ""
            if fight and not (was and was[2] and (state.floor, state.room_id) == was[:2]):
                self.tab = "here"
            self.where_was = where
        self.query_one("#ways-words", Static).update(self.ways_words())
        self.query_one("#tab-bar", Static).update(self.tab_text())
        self.draw_pane()

    def ways_words(self) -> Text:
        """The ways out beside the arrows, two to a line: where each goes, if you've been; else what you can see of it."""
        state = self.game.state
        parts = []
        for direction in ("north", "east", "south", "west"):
            exit_ = state.room.exits.get(direction)
            if exit_ is None:
                continue
            there = state.rooms[exit_.to]
            name = ("locked" + (": a shop" if there.shop else "")) if exit_.locked else there.name if there.visited \
                else (f"a {there.fixture}" if there.fixture and not there.fixture_used else "unexplored")
            colour = "#7a3b4c" if exit_.locked else "#5fe3ff" if there.visited else GOLD if there.fixture else DIM
            parts.append(Text.assemble((f"{ARROWS[direction]} ", f"bold {colour}"),
                                       (short_name(name, 18), WORDS if there.visited else DIM)))
        text = Text()
        for i, part in enumerate(parts):
            if i:
                text.append("\n" if i % 2 == 0 else "   ")
            text.append_text(part)
        return text

    def gather_things(self) -> list[Thing]:
        """What's here (ui/here.py), its buttons numbered first, as GameScreen.refresh_here numbers them."""
        state, content = self.game.state, self.game.content
        from .here import things_here

        things = things_here(state, content)
        if state.scene or state.over:
            for thing in things:
                thing.verbs = []
        self.things = things
        self.numbers: dict[str, int] = {}
        for thing in things:
            for action in thing.verbs:
                if action.id and action.id not in self.numbers:
                    self.numbers[action.id] = len(self.numbers) + 1
        self.tile_verbs = self._ordered(things, self.numbers)
        self.verb_owner = {a.id: thing.name for thing in things for a in thing.verbs if a.id}
        return things

    def tab_colour(self, tab: str) -> str:
        """A tab's own colour: the map's is the floor's, and Here's is red in a fight."""
        monster = self.game.state.room.monster
        if tab == "here" and monster and monster.hostile and monster.hp > 0:
            return "#ff4b4b"
        return TAB_COLOURS[tab] or look_of(self.game.state.theme).accent

    def waiting_here(self) -> bool:
        """Whether Here has something for you while another tab's showing: someone, or something to do (a thing to
        take, a place to search, a chest), so its tab says so."""
        return self.tab != "here" and any(t.character or t.verbs for t in self.things)

    def tab_text(self) -> Text:
        """The tabs, each lit in its own colour when it's the one showing, its key after its name. Here, not showing,
        wears a ● when the room has something for you (waiting_here)."""
        text = Text()
        for key, label, hotkey in TABS:
            on, colour = key == self.tab, self.tab_colour(key)
            click = Style(meta={"@click": f"screen.tab('{key}')"})
            if key == "here" and self.waiting_here():  # (not the one showing: its own look, and a dot)
                text.append(f" {label} ", Style.parse(f"bold {colour} on #3a2a08") + click)
                text.append("● ", Style.parse("bold #ffd166 on #3a2a08") + click)
                text.append(f"{hotkey} ", Style.parse(f"{colour} on #3a2a08") + click)
                text.append(" ")
                continue
            text.append(f" {label} ", Style.parse(f"bold #10122a on {colour}" if on else f"bold {colour} on #171a38")
                        + click)
            text.append(f"{hotkey} ", Style.parse(f"#10122a on {colour}" if on else f"{DIM} on #171a38") + click)
            text.append(" ")
        return text

    def _strip(self) -> list[Action]:
        """The choices, bar the ways out: the arrows and the map have those."""
        return [a for a in super()._strip() if not a.id.startswith("go:") or self.game.state.scene]

    def refresh_choices(self) -> None:
        """The decision: the choices one to a line, numbered after Here's buttons, each with what it costs or risks;
        the arrows lit for the ways out."""
        game = self.game
        scene = game.story.scene_title(game.state)
        actions = self._strip()
        suggesting = game.suggestion_pending()
        first = len(self.tile_verbs) + 1
        self.numbered = [*self.tile_verbs, *actions]
        self.query_one(DPad).show(self._choices(), game.locked_doors())
        decide = self.query_one("#decide")
        decide.border_title = f"✧ {scene}" if scene else "What do you do?"
        decide.set_class(bool(scene), "scene")
        shown = (scene, game.state.over, suggesting, first, [(a.id, a.label, a.hint) for a in actions])
        if shown == self.choices_shown:
            return
        self.choices_shown = shown
        box = self.query_one("#choices", VerticalScroll)
        box.remove_children()
        if game.state.over:
            box.mount(Static(Text("Press Enter to see your fate.", style=ACCENT)))
            return
        rows: list[Widget] = [ChoiceItem(n, a) for n, a in enumerate(actions, first)]
        for row, (n, action) in zip(rows, enumerate(actions, first)):
            row.update(self.choice_text(n, action))
        if suggesting:
            rows.append(Static(Text(f" {first + len(actions):>2}   ✦ …", style=f"italic {DIM}"), classes="choice"))
        if not rows:
            rows.append(Static(Text("Nothing to choose: the buttons above, the arrows, or type what you do.",
                                    style=DIM), classes="choice"))
        box.mount_all(rows)

    @staticmethod
    def choice_text(number: int, action: Action) -> Text:
        """A choice's line: its number on a block of colour, its words, what it costs or risks after them."""
        creative = action.label.startswith("✦") or action.id == "suggest"
        text = Text()
        text.append(f" {number:>2} ", style=f"bold #10122a on {PINK if creative else ACCENT}")
        text.append("  ")
        if action.id.startswith("go:"):
            text.append(ARROWS.get(action.id[3:], "·") + " ", style="bold #5fe3ff")
        text.append(action.label, style=f"italic bold {PINK}" if creative else
                    "bold #ffd166" if action.id.startswith("perk:") else "bold #e8e8f4")
        if action.hint:
            text.append(f"   {action.hint}", style=f"bold {ACCENT}" if "!" in action.hint else DIM)
        return text

    def refresh_ways(self) -> None:
        """(The arrows are always on the right page.)"""

    # --- the tabs ---

    def action_tab(self, name: str) -> None:
        """Bring a tab into the pane; only the pane (and the tabs) change."""
        if name not in TAB_PANEL or self.tab == name:
            return
        self.tab = name
        self.query_one("#tab-bar", Static).update(self.tab_text())
        self.draw_pane()
        self.query_one("#pane").scroll_home(animate=False)

    def action_panel(self, name: str) -> None:
        """What F2-F7 (and typed "map", "i"...) do: bring their tab into the pane; pressed on the tab that's showing, or
        for a panel with no tab (the help), open the panel in full as before."""
        tab = PANEL_TAB.get(name)
        if tab and tab != self.tab:
            self.action_tab(tab)
        else:
            super().action_panel(name)

    def action_expand(self) -> None:
        """The ⤢ at the end of the tabs: this tab's panel, in full."""
        super().action_panel(TAB_PANEL[self.tab])

    def action_focus_thing(self, thing_id: str) -> None:
        """A thumbnail clicked: that thing into the frame."""
        self.focus[self.tab] = thing_id
        self.draw_pane(force=True)

    def action_pack_verb(self, index: int) -> None:
        """A button on the thing you carry in the Pack's frame: that action, as the engine has it."""
        item = next((i for i in self.pack_items if i[0] == self.focus["pack"]), None) or \
            (self.pack_items[0] if self.pack_items else None)
        if item and 0 <= index < len(item[2]):
            self.press(item[2][index])

    def draw_pane(self, force: bool = False) -> None:
        """Fill the pane for its tab, if what it would show has changed (a rebuild swaps it under the mouse)."""
        state = self.game.state
        width = (self.plan.side if self.plan else 70) - 7  # (less the pane's frame, padding and scrollbar)
        key = (self.tab, width, self.plan.here_rows if self.plan else 0, state.turn, state.room_id,
               tuple(self.focus.values()), tuple((t.id, t.status, tuple((a.id, a.label) for a in t.verbs)) for t in self.things),
               state.player.hp, state.player.gold, len(state.player.inventory), self._sprites_on())
        if key == self.pane_shown and not force:
            return
        self.pane_shown = key
        pane = self.query_one("#pane", VerticalScroll)
        colour = self.tab_colour(self.tab)
        pane.styles.border = ("round", colour)
        pane.styles.border_title_color = colour
        pane.border_title, pane.border_subtitle = f"✦ {TAB_LABEL[self.tab]}", ""
        parts = getattr(self, f"pane_{self.tab}")(width, self.plan.here_rows if self.plan else 24)
        with self.app.batch_update():
            pane.remove_children()
            pane.mount_all(parts)

    def frame_and_strip(self, things: list[Thing], focus_id: str, buttons, words=None) -> list[Widget]:
        """A frame with the thing in focus at full size (its picture plays the fight's moments: class here-art) and
        everything about it beside it (`words`, else facts), then all of them as thumbnails in a grid that scrolls
        down, the one in the frame underlined."""
        focus = next((t for t in things if t.id == focus_id), things[0])
        picture = Picture(focus.sprite, focus.kind, 24, pose=focus.pose, content=self.game.content, loop=focus.loop,
                          action=f"screen.lookup('{self.lookup_id(focus)}')", classes="here-art focus-art")
        about = words(focus) if words else facts(self.game.state, self.game.content, focus)
        side = [Static(about, classes="focus-words")]
        lines = buttons(focus)
        if lines:
            side.append(Vertical(*lines, classes="focus-verbs"))
        parts: list[Widget] = [Horizontal(picture, Vertical(*side, classes="focus-side"), classes="focus")]
        if len(things) > 1:
            thumbs = []
            for thing in things:
                thumb = ClickableBox(Picture(thing.sprite, thing.kind, 12, content=self.game.content, loop=thing.loop,
                                             classes="thumb-art"),
                                     Static("▀" * 12, classes="thumb-mark"),
                                     action=f"screen.focus_thing('{thing.id}')",
                                     classes="thumb" + (" picked" if thing is focus else ""))
                thumb.tooltip = thing.name
                thumbs.append(thumb)
            grid = Grid(*thumbs, classes="strip")
            grid.styles.grid_size_columns = max(1, ((self.plan.side if self.plan else 70) - 7) // 13)
            parts.append(grid)
        return parts

    @staticmethod
    def lookup_id(thing: Thing) -> str:
        kind, _, key = thing.id.partition(":")
        return {"floor": f"item:{key}", "ware": f"item:{thing.sprite}", "keeper": f"monster:{key}",
                "pack": f"item:{key}", "beast": f"monster:{key}"}.get(kind, thing.id)

    def pane_here(self, width: int, rows: int) -> list[Widget]:
        """Whoever and whatever is here (the frame, the grid, what's to search), and in the rows that leaves, what's
        worth a glance: the floor map, the quests open, and the last few things that happened, as many as fit."""
        state = self.game.state
        pictured = [t for t in self.things if t.art and t.sprite]
        plain = [t for t in self.things if not (t.art and t.sprite)]
        side = width - 28

        def buttons(thing: Thing) -> list[Widget]:
            return [Horizontal(*[verb_button(a, self.numbers, f"screen.verb('{a.id}')") for a in line],
                               classes="here-verbs") for line in verb_lines(thing, max(16, side))]

        parts = self.frame_and_strip(pictured, self.focus["here"], buttons) if pictured else []
        for thing in plain:
            parts.append(Horizontal(Static(Text(f" {thing.name} ", style=f"bold {GOLD} on #24284a"),
                                           classes="plain-name"),
                                    *[verb_button(a, self.numbers, f"screen.verb('{a.id}')") for a in thing.verbs],
                                    classes="plain-line here-verbs"))
        if not self.things:
            parts.append(Static(Text("Nothing here but the room itself.", style=DIM), classes="pane-text"))
        columns = max(1, width // 13)
        left = rows - (13 if pictured else 1) - (-(-len(pictured) // columns) * 7 if len(pictured) > 1 else 0) \
            - 2 * len(plain)
        quests = [(line, still) for _, line, still in npcs.quest_log(state, self.game.content) if still]
        lately = [line for line in state.journal if not line.startswith("⚄ ")][-LATELY:] \
            if not getattr(self, "lately_lines", 0) else []  # (the docked journal has them)
        need_quests = 3 + len(quests) if quests else 0
        need_lately = 3 + len(lately) if lately else 0
        big = big_map(state, width, left - need_quests - need_lately - 3)
        if big is None:
            big = big_map(state, width, left - 3)
        if big is not None:
            parts += [Static(rule("FLOOR", width, look_of(state.theme).accent), classes="pane-rule"),
                      StoryLine(big, classes="small-map")]
            left -= big.plain.count("\n") + 4
        lexicon = self.lexicon()
        if quests and left >= need_quests:
            text = Text()
            for line, _ in quests:
                text.append_text(highlight("★ " + line, lexicon, f"bold {GOLD}"))
                text.append("\n")
            text.rstrip()
            parts += [Static(rule("QUESTS", width), classes="pane-rule"), StoryLine(text, classes="pane-text")]
            left -= need_quests
        if lately and left >= need_lately:
            text = Text()
            for line in lately:
                text.append_text(highlight("· " + line, lexicon, WORDS))
                text.append("\n")
            text.rstrip()
            parts += [Static(rule("LATELY", width, "#6c8cff"), classes="pane-rule"), StoryLine(text, classes="pane-text")]
        return parts

    def pane_map(self, width: int, rows: int) -> list[Widget]:
        """The floor drawn big (on the pane's frame its name, and at its foot how much of it you've seen), and under it
        the goal, the quests, the tips and the key."""
        state, content = self.game.state, self.game.content
        notes = map_notes(state, content)
        lines = sum(1 + len(cell.plain) // max(1, width - 12) for cell in notes.columns[1]._cells
                    if isinstance(cell, Text))
        room = rows - lines - 2
        drawn = big_map(state, width, room) or small_map(state)
        pane = self.query_one("#pane")
        theme = content.themes[state.theme]
        pane.border_title = f"✦ Map · {theme.name} · floor {state.floor} of {state.floors_total}"
        seen = sum(r.visited for r in state.rooms if not r.secret)
        pane.border_subtitle = f"{seen} of {sum(not r.secret for r in state.rooms)} rooms seen"
        holder = Center(StoryLine(drawn, classes="pane-map"), classes="map-holder")
        holder.styles.height = max(drawn.plain.count("\n") + 1, room)
        return [holder, Static(notes, classes="pane-text")]

    def pane_pack(self, width: int, rows: int) -> list[Widget]:
        state, content = self.game.state, self.game.content
        player = state.player
        from .. import interactions

        def verbs(ref: str) -> list[Action]:
            return interactions.verbs(state, content, ref)

        items = [(player.weapon, f"⚔ in hand · {content.item(player.weapon).damage}", verbs("gear:weapon"), True)]
        if player.armor:
            items.append((player.armor, f"⛨ worn · +{content.item(player.armor).defense} defense",
                          verbs("gear:armor"), True))
        counts: dict[str, int] = {}
        for key in player.inventory:
            counts[key] = counts.get(key, 0) + 1
        for key, count in counts.items():
            items.append((key, (f"×{count} · " if count > 1 else "") + item_note(content, key), verbs(f"item:{key}"),
                          False))
        self.pack_items = [(f"pack:{key}", note, buttons, on) for key, note, buttons, on in items]
        things = [Thing(f"pack:{key}", key, "item", content.item(key).name, note, ACCENT if on else DIM, buttons)
                  for key, note, buttons, on in items]
        if self.focus["pack"] not in {t.id for t in things}:
            self.focus["pack"] = things[0].id

        def buttons(thing: Thing) -> list[Widget]:
            return [Horizontal(*[verb_button(a, {}, f"screen.pack_verb({i})") for i, a in enumerate(thing.verbs)],
                               classes="here-verbs")] if thing.verbs else []

        head = Text.assemble(("¤ ", ACCENT), (f"{player.gold} gold", "bold #e8e8f4"), ("   ● ", "#ff7b39"),
                             (f"{player.bombs} bombs", WORDS), ("   ⚷ ", "#c0cbdc"), (f"{player.keys} small keys", WORDS))
        return [Static(head, classes="pane-text"), Static("", classes="pane-gap"),
                *self.frame_and_strip(things, self.focus["pack"], buttons)]

    def pane_sheet(self, width: int, rows: int) -> list[Widget]:
        state, content = self.game.state, self.game.content
        stats, rolls = sheet_text(state, content)
        return [Static(rule("STATUS", width), classes="pane-text"), Static(status_lines(state, content),
                                                                            classes="pane-text"),
                Static("", classes="pane-gap"), Static(rule("STATS", width), classes="pane-text"),
                Static(stats, classes="pane-text"), Static("", classes="pane-gap"),
                Static(rule("ROLLS · a d20 plus", width), classes="pane-text"), Static(rolls, classes="pane-text"),
                Static("", classes="pane-gap"),
                Static(CharacterScreen._growth(self), classes="pane-text")]  # (it only reads self.game)

    def pane_journal(self, width: int, rows: int) -> list[Widget]:
        state = self.game.state
        lexicon = self.lexicon()
        parts: list[Widget] = []
        quests = npcs.quest_log(state, self.game.content)
        if quests:
            parts.append(Static(rule("QUESTS", width), classes="pane-text"))
            text = Text()
            for _, line, still in quests:
                text.append_text(highlight(("★ " if still else "✓ ") + line, lexicon, f"bold {GOLD}" if still else DIM))
                text.append("\n")
            text.rstrip()
            parts += [StoryLine(text, classes="pane-text"), Static("", classes="pane-gap")]
        parts.append(Static(rule(f"WHAT'S HAPPENED · turn {state.turn}", width), classes="pane-text"))
        text = Text()
        for line in state.journal[-JOURNAL_SHOWN:]:
            roll = line.startswith("⚄ ")
            text.append_text(highlight(line if roll else "· " + line, lexicon, DIM if roll else WORDS))
            text.append("\n")
        text.rstrip()
        parts.append(StoryLine(text or Text("Nothing written yet.", style=DIM), classes="pane-text"))
        self.call_after_refresh(lambda: self.query_one("#pane").scroll_end(animate=False))
        return parts

    def pane_bestiary(self, width: int, rows: int) -> list[Widget]:
        """The creatures you've met, the one here first: the one in focus at full size with what you know of it,
        the rest as thumbnails. A name opens its card; the ⤢ opens the bestiary in full, with each one's lore."""
        content = self.game.content
        entries = dict(sorted(self.game.profile.bestiary().items(), key=lambda kv: kv[1]["first_seen"] or 0))
        here = self.game.state.room.monster
        order = [k for k in entries if k in content.monsters]
        if here is not None and here.key in content.monsters:
            order = [here.key] + [k for k in order if k != here.key]
        head = Static(rule(f"MET · {len(order)} of {len(content.monsters)}", width), classes="pane-text")
        if not order:
            return [head, Static(Text("Nothing yet. Go meet something.", style=DIM), classes="pane-text")]
        things = []
        for key in order:
            entry = entries.get(key, {"seen": 0, "killed": 0, "killed_you": 0, "weak": []})
            status = ("here now · " if here is not None and here.key == key else "") + \
                f"seen {entry['seen']} · slain {entry['killed']}" + \
                (f" · killed you {entry['killed_you']}" if entry["killed_you"] else "") + \
                f"\nweak to: {', '.join(entry['weak']) or '???'}"
            things.append(Thing(f"beast:{key}", key, "monster", content.monster(key).name, status,
                                "#ff4b4b" if here is not None and here.key == key else DIM))
        if self.focus["bestiary"] not in {t.id for t in things}:
            self.focus["bestiary"] = things[0].id

        def words(thing: Thing) -> Text:  # what you know of it: more once you've beaten one
            monster, entry = content.monster(thing.sprite), entries.get(thing.sprite, {})
            text = Text(monster.name, style=f"bold {'#ff4b4b' if here is not None and here.key == monster.key else GOLD}")
            if here is not None and here.key == monster.key:
                text.append("   here now", style="bold #ff4b4b")
            text.append(f"\nseen {entry.get('seen', 0)} · slain {entry.get('killed', 0)} · talked down "
                        f"{entry.get('pacified', 0)}", style=DIM)
            if entry.get("killed_you"):
                text.append(f" · killed you {entry['killed_you']}", style="#ff4b4b")
            weak = entry.get("weak") or []
            text.append("\nweak to: ", style=DIM)
            text.append(", ".join(weak) if weak else "???", style="#5fe3ff" if weak else DIM)
            hidden = len(set(monster.weak) - set(weak))
            if weak and hidden:
                text.append(f"  (+{hidden} to find)", style=DIM)
            if entry.get("killed"):
                text.append(f"\n♥ {monster.hp}  ⛨ {monster.defense}  hits +{monster.attack}  {monster.damage} damage"
                            f"  · tier {monster.tier}", style=WORDS)
            else:
                text.append("\nbeat one to learn its numbers", style=DIM)
            if monster.desc:
                text.append(f"\n\n{monster.desc}", style=f"italic {DIM}")
            if entry.get("lore"):
                text.append(f"\n\n{entry['lore']}", style=f"italic {WORDS}")
            return text

        return [head, *self.frame_and_strip(things, self.focus["bestiary"], lambda thing: [], words)]
