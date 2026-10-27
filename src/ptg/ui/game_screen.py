"""The main game screen: a stage (the room's picture) over a story of words, Here (who and what is in the room, with
buttons for what you can do with them) beside them or in a strip under the stage, the choices in a strip under the
story, and the command line. How it's shared out for the size is ui/plan.py's; GameScreen.relayout applies it."""

from __future__ import annotations

import asyncio
import time

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, Input, Static

from .. import config, glossary, interactions, inventory, loot, sound, statuses
from ..events import Action, Event
from ..glossary import Lexicon
from ..game import Game
from ..models import LogEntry
from ..outcome import AWFUL, BAD, GOOD, GREAT, overall, tone, verdict
from ..room_picture import look_of, picture_text
from ..sprites import DEATH_FRAMES, splash_sizes
from ..text import cap, mid_sentence, the
from . import effects
from ..llm.interpreter import looks
from .dice import DiceScreen
from .here import CARD, MINI, ROW, Thing, Tile, arrange, things_here
from .panels import (BestiaryScreen, CharacterScreen, FloorScreen, HelpScreen, InfoScreen, InventoryScreen,
                     JournalScreen, LevelUpScreen, LookScreen, MapScreen, MenuScreen, Panel, PickScreen, ShopScreen)
from .plan import Plan, make_plan
from .widgets import (ARROWS, IDLE, ChoiceItem, Clickable, ClickableBox, DiceLine, DPad, Hud, Picture, StoryLine, hearts,
                      highlight, map_text, roll_text, room_text)

# (sprite, steps of (frame, pose, flash)) for the moment you use a fixture. A chest and a shrine end on their used-up
# last frame (emptied; candles out), as the room's picture shows them from then on.
FIXTURE_MOMENTS = {
    "chest": ("chest", [(0, "shake", False), (1, "shake", False)] * 3
              + [(2, "idle", False), (3, "idle", False), (2, "idle", False), (3, "idle", False), (2, "idle", False),
                 (4, "idle", False)]),
    "fountain": ("fountain", [(i % 3, "idle", False) for i in range(9)]),
    "shrine": ("shrine", [(0, "idle", False), (1, "idle", True), (2, "idle", False), (1, "idle", True),
                          (0, "idle", False), (3, "idle", False)]),
    "descend": ("stairs", [(i % 3, "idle", False) for i in range(6)] + [(i, "death", False) for i in range(6)]),
}

SIDE_WORDS = 27  # the columns inside the side column's panels (a panel's frame and padding less its width)
RESIZE_WAIT = 0.12  # seconds a window must hold still before the screen is laid out for its size again
FIRST = ("dodge", "flee", "bomb", "use:", "throw:", "distract:", "go:")  # fight tactics and ways out, before the rest

COMMANDS = {
    "i": "inventory", "inv": "inventory", "inventory": "inventory",
    "c": "character", "char": "character", "character": "character", "stats": "character",
    "l": "look", "look": "look",
    "m": "map", "map": "map",
    "b": "bestiary", "bestiary": "bestiary",
    "j": "journal", "journal": "journal",
    "?": "help", "h": "help", "help": "help",
}
TOASTS = {
    "trait": ("Trait earned", "information"),
    "weakness": ("Bestiary", "information"),
    "fate": ("Fate", "information"),
    "ghost_rest": ("A ghost rests", "information"),
    "reprieve": ("Not yet!", "warning"),
    "key": ("Key", "information"),
}


SPARKS = "✧✦★✦"
LEAVE_WINDOW = 2.0  # seconds for the second Esc that leaves for the title
NARRATION_STEP = 0.12  # seconds between repaints of narration still arriving: re-colouring it every word costs


def secret_banner(frame: int, words: str = "SECRET ROOM", colour: str = "#ffd166") -> Text:
    """The banner across the story for a find worth a fanfare (a secret room, a shop): its stars twinkle in turn,
    then settle."""
    stars = [SPARKS[(frame + i) % len(SPARKS)] for i in range(6)]
    text = Text(justify="center")
    for i, star in enumerate(stars[:3]):
        text.append(f"{star}  ", style="bold #ffffff" if frame and (frame + i) % 3 == 0 else f"bold {colour}")
    text.append(f" {words} ", style=f"bold {effects.INK} on {colour}")
    for i, star in enumerate(stars[3:], 3):
        text.append(f"  {star}", style="bold #ffffff" if frame and (frame + i) % 3 == 0 else f"bold {colour}")
    return text


def pickup_line(events: list[Event], content) -> str | None:
    """A turn of nothing but things picked up, in a line (more than one, side by side): "+ Healing Potion → pack",
    "+ Bomb → bombs". None for any other turn: those are told."""
    moves = [e for e in events if e.kind in ("take", "key")]
    if not moves or len(moves) != len(events) or not all(e.data.get("quiet") and e.data.get("item") for e in moves):
        return None
    where = {"pack": "pack", "counter": "pocket"}
    return "   ".join(f"+ {content.item(e.data['item']).name} → "
                      f"{inventory.PICKUPS.get(e.data['item']) or where.get(e.data['to'], 'pack')}" for e in moves)


def exchange_lines(events: list[Event], content) -> list[str]:
    """What changed hands with a character, a line each: "→ given to Lucky Lenny: Lenny's Bad Tooth", "← a gift from
    Swoogy: Swoogy's Diaper" (an item's event data is inventory.moved's; gold's has {gold, how, from, to})."""
    out = []
    for event in events:
        data = event.data
        if data.get("how") not in ("give", "story", "win"):
            continue
        what = f"{data['gold']} gold" if data.get("gold") else content.item(data["item"]).name if data.get("item") else ""
        if not what:
            continue
        if data.get("to") in content.monsters:
            out.append(f"→ given to {content.monster(data['to']).name}: {what}")
        elif data.get("from") in content.monsters:
            out.append(f"← a gift from {content.monster(data['from']).name}: {what}")
    return out


PURSE = (("gold", "¤", "#ffb000", "gold", "gold"), ("bombs", "●", "#ff7b39", "bomb", "bombs"),
         ("keys", "⚷", "#c0cbdc", "small key", "small keys"))  # (what the HUD counts, its mark, its colour, its names)


def purse(state) -> dict[str, int]:
    """What you'd want told when it goes up: gold, bombs and small keys."""
    return {"gold": state.player.gold, "bombs": state.player.bombs, "keys": state.player.keys}


def purse_chips(before: dict[str, int], after: dict[str, int]) -> Text | None:
    """What a turn added to your purse, as chips in a line: "+6 ¤ gold (21)   +1 ● bomb (2)". None if nothing."""
    text = Text("  ")
    for name, mark, colour, one, many in PURSE:
        gained = after[name] - before[name]
        if gained <= 0:
            continue
        if text.plain.strip():
            text.append("   ")
        text.append(f" +{gained} {mark} {one if gained == 1 else many} ", style=f"bold #10122a on {colour}")
        text.append(f" ({after[name]})", style="#6c6f99")
    return text if text.plain.strip() else None


def shown(widget: Widget) -> str:
    """A piece of the story in a line, for the run's turn log: its words, or what the picture, sprite or cards were
    (a row of them is named for it as it's made: its cards may not be in it yet)."""
    if widget.name:
        return widget.name
    if isinstance(widget, Picture):
        return f"sprite: {widget.key}"
    if widget.has_class("story-card"):
        return "story card: " + str(widget.border_title).removeprefix("✧").strip()
    return str(widget.render()) if isinstance(widget, Static) else type(widget).__name__


class GameScreen(Screen):
    BINDINGS = [
        Binding("f1", "panel('help')", "Help"),
        Binding("f2", "panel('inventory')", "Inventory"),
        Binding("f3", "panel('character')", "Character"),
        Binding("f4", "panel('look')", "Look"),
        Binding("f5", "panel('map')", "Map"),
        Binding("f6", "panel('bestiary')", "Bestiary"),
        Binding("f7", "panel('journal')", "Journal"),
        Binding("escape", "leave", "Title"),
        Binding("pageup", "story_page(-1)", "Scroll up", show=False),
        Binding("pagedown", "story_page(1)", "Scroll down", show=False),
    ]

    def __init__(self, game: Game, fresh: bool) -> None:
        super().__init__()
        self.game = game
        self.fresh = fresh
        self.busy = False
        self.narration_stop: asyncio.Event | None = None  # set to cut the narrator short (later)
        self.queued = None  # what to do once the turn's done: a move made while the narrator was still talking
        self.turn_marker: Widget | None = None  # where the turn now being shown began (see _mark_turn)
        self.animating = False  # a fight's flashes, lunges or death are playing on its tile
        self.counter_open = False  # the shop's own screen sent the turn now coming: it opens again after it
        self.leave_asked = 0.0  # when Esc last asked "again for the title?" (time.monotonic)
        self.since_redraw = 0  # turns since the whole screen was last drawn afresh (see PTGApp.action_redraw)
        self.plan: Plan | None = None  # how the screen is shared out now (ui/plan.py)
        self.things: list[Thing] = []  # what Here shows, in its order
        self.tile_verbs: list[Action] = []  # the live buttons on those, numbered first
        self.verb_owner: dict[str, str] = {}  # whose each of them is, for the story's line ("Search · prayer rail")
        self.numbered: list[Action] = []  # what typing a number does: Here's buttons, then the strip's choices
        self.choices_shown: tuple | None = None  # what the choices strip shows (see refresh_choices)
        self.here_shown: tuple | None = None  # what Here was built for: rebuilt only when it changes
        self.stage_shown: tuple | None = None  # likewise the stage's picture
        self.stage_frames: list[Text | None] = []  # its two idle frames (the second drawn when it's first wanted)
        self.stage_beat = 0
        self._stage_timer = None
        self.here_page = self.choice_page = 0  # the "more" chips turn these
        self._resize_timer = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="hud-row"):
            yield Hud(id="hud")
            yield Static(id="hud-short")  # a short screen's status bar (see refresh_hud)
            yield Clickable(Text(" ☰ "), "screen.menu()", id="hud-menu")
        with Horizontal(id="main"):
            with Vertical(id="left"):
                with Center(id="stage-box"):  # the room's picture, shaped like a room
                    with ClickableBox(action="screen.stage_card()", id="stage"):
                        yield Static(id="stage-art")
                yield Vertical(id="here-strip", classes="panel")  # Here, when there is one column
                yield VerticalScroll(id="story")
            with Vertical(id="side"):
                yield Vertical(id="here", classes="panel")
                yield Static(id="map", classes="panel")
                yield DPad(id="dpad")
        yield Horizontal(id="ways")  # a narrow screen's way out of the room
        yield Vertical(id="choices")
        yield Input(id="command", placeholder="Type a number, or anything you want to try...  (F1 help)")
        yield Footer()

    def on_mount(self) -> None:
        state = self.game.state
        self.title = self.game.theme.name
        self.sub_title = f"seed {state.seed}"
        for box, title in (("#story", "Story"), ("#choices", "Choices"), ("#here", "Here"), ("#here-strip", "Here"),
                           ("#map", "Map")):
            self.query_one(box).border_title = title
        self.query_one("#story").border_subtitle = self.game.llm.name if self.game.llm else "offline narrator"
        for box in ("#here", "#here-strip", "#stage", "#stage-box", "#map", "#choices", "#ways"):
            self.query_one(box).can_focus = False  # (typed numbers belong to the command line: a click mustn't take them)
        self.relayout()
        if self.fresh:
            self.run_turn(None)
        else:
            lexicon = self.lexicon()
            recent = state.log[-60:]
            floors = [i for i, entry in enumerate(recent) if entry.kind == "floor"]
            for entry in recent[floors[-1] if floors else 0:]:  # this floor's story, as a new floor starts a page
                self.add_entry(entry, lexicon)
            self.pick_up_again()
        self.query_one("#command", Input).focus()

    def on_resize(self) -> None:
        if self._resize_timer is not None:  # (a drag sends a stream of these: lay out once it settles)
            self._resize_timer.stop()
        self._resize_timer = self.set_timer(RESIZE_WAIT, self.relayout)

    # --- the layout ---

    def relayout(self) -> None:
        """Lay the screen out for its size (ui/plan.py's sums), then draw each box again if what it shows has changed."""
        if self._resize_timer is not None:
            self._resize_timer.stop()
            self._resize_timer = None
        if not self.size.width:
            return
        plan = make_plan(self.size.width, self.size.height, config.touch(), self.plan)
        if plan != self.plan:
            self.plan = plan
            self.set_class(not plan.two_columns, "one")
            self.set_class(plan.compact, "compact")
            self.set_class(plan.touch, "touch")
            self.query_one("#side").styles.width = plan.side or 1
            self.query_one("#command", Input).placeholder = (
                "Type, or tap a choice" if plan.compact else
                "Type a number, or anything you want to try...  (F1 help)")
        self.refresh_hud()
        self.refresh_stage()
        self.refresh_here()
        self.refresh_choices()
        self.refresh_ways()

    refresh_panels = relayout  # (what a turn calls when the game has moved on)

    def refresh_hud(self) -> None:
        state, content = self.game.state, self.game.content
        self.query_one("#hud", Hud).show(state, content)
        player = state.player
        short = Text("♥", style="#ff4b4b")
        short.append(f"{player.hp}/{player.max_hp}", style="bold #ff4b4b" if player.hp <= 0.3 * player.max_hp else "bold")
        short.append(f" ⛨{player.defense(content)} ", style="#6c8cff")
        short.append(f"✦{player.fate} ", style="#ffd166")
        short.append(f"¤{player.gold} ", style="#ffb000")
        short.append(f"Lv{player.level} ", style="bold #ff4f9a")
        short.append(f"F{state.floor}/{state.floors_total}", style="bold #6c8cff")
        self.query_one("#hud-short", Static).update(short)

    def refresh_stage(self) -> None:
        """The room's picture over the story (room_picture): redrawn only when its size or what it draws changes."""
        plan, game = self.plan, self.game
        box = self.query_one("#stage-box")
        box.display = plan.stage_rows > 0
        if not box.display:
            return
        state, room = game.state, game.state.room
        monster = room.monster
        shown = (plan.stage_width, plan.stage_rows, plan.compact, state.floor, state.room_id, tuple(room.items),
                 (monster.key, monster.hostile) if monster and monster.hp > 0 else None, room.fixture_used,
                 tuple(f.searched for f in room.features), self._sprites_on())
        if shown != self.stage_shown:
            self.stage_shown = shown
            self.draw_stage(plan.stage_width, 2 * plan.stage_rows)
        stage = self.query_one("#stage")
        stage.border_title = f"✦ {room.name}"
        stage.tooltip = "Click to look around"
        if not plan.compact:
            stage.styles.border = ("round", look_of(state.theme).accent)
            stage.styles.border_title_color = look_of(state.theme).accent
        stage.set_class(bool(monster and monster.hostile and monster.hp > 0), "combat")

    def draw_stage(self, width: int, height: int) -> None:
        """The room's picture on the stage, in the first frame of whoever's here and what lies about; every IDLE
        seconds after, it swaps with the second (stage_step), so they breathe and bob as they do everywhere else."""
        state, content = self.game.state, self.game.content
        art = picture_text(state, content, width, height) if self._sprites_on() else None
        self.stage_frames = [art, None] if art is not None else []
        self.stage_size, self.stage_beat = (width, height), 0
        self.query_one("#stage-art", Static).update(art or room_text(state, content))
        if self._stage_timer is None and art is not None:
            self._stage_timer = self.set_interval(IDLE, self.stage_step, name="stage")

    def stage_step(self) -> None:
        """A beat of the stage's idle animation: the other frame, while this screen's in front and nothing else is
        moving on it (a turn, a blow, a chest opening). Its second frame is drawn the first time it's wanted, off the
        screen's thread (a room takes a tenth of a second or so: a click then shouldn't wait on it), and a room with
        nothing that moves stops asking."""
        frames = self.stage_frames
        if len(frames) != 2 or self.busy or self.animating or self.app.screen is not self:
            return
        if frames[1] is None:
            snapshot = self.game.state.model_copy(deep=True)  # (what it draws can't change under it mid-turn)
            self.run_worker(lambda: self._second_frame(frames, snapshot), thread=True, group="stage", exclusive=True)
            return
        self.stage_beat += 1
        self.query_one("#stage-art", Static).update(frames[self.stage_beat % 2])

    def _second_frame(self, frames: list, state) -> None:
        """The stage's second frame, drawn in a worker thread, then kept, if the stage still shows the same room."""
        second = picture_text(state, self.game.content, *self.stage_size, frame=1)

        def keep() -> None:
            if frames is not self.stage_frames:
                return  # (another room's on the stage by now)
            if second is None or (second.plain, second.spans) == (frames[0].plain, frames[0].spans):
                self.stage_frames = []  # (nothing here moves)
            else:
                frames[1] = second
        self.app.call_from_thread(keep)

    def refresh_here(self) -> None:
        """Who and what is here, as tiles (ui/here.py), in the box the plan gives them: Here beside the story, or a
        strip under the stage. Every live button is numbered, in the order of the tiles, before the choices are."""
        plan, game = self.plan, self.game
        state, content = game.state, game.content
        things = things_here(state, content)
        if state.scene or state.over:  # (a scene's choices are all there is; the buttons wait)
            for thing in things:
                thing.verbs = []
        self.things = things
        numbers: dict[str, int] = {}
        for thing in things:
            for action in thing.verbs:
                if action.id and action.id not in numbers:
                    numbers[action.id] = len(numbers) + 1
        self.tile_verbs = self._ordered(things, numbers)
        self.verb_owner = {a.id: thing.name for thing in things for a in thing.verbs if a.id}  # (whose button it is)
        box = self.query_one("#here" if plan.two_columns else "#here-strip")
        other = self.query_one("#here-strip" if plan.two_columns else "#here")
        width = (plan.side if plan.two_columns else plan.columns) - 4  # less the frame and padding
        rows = max(1, plan.here_rows)
        forms = ((CARD, ROW) if width < 34 else (CARD, MINI, ROW)) if plan.two_columns else (MINI,)
        layout, hidden = arrange(things, width, rows, plan.touch, forms, content, packed=not plan.two_columns)
        if hidden:  # a page of them, and a chip saying how many more (tap it for the next page)
            room_for = rows - (3 if plan.touch else 1)
            first, _ = arrange(things, width, room_for, plan.touch, forms, content, packed=not plan.two_columns)
            per_page = max(1, sum(map(len, first)))
            start = (self.here_page * per_page) % len(things)
            layout, _ = arrange(things[start:] + things[:start], width, room_for, plan.touch, forms, content,
                                packed=not plan.two_columns)
            hidden = len(things) - sum(map(len, layout))
        used = sum(max(h for _, _, (_, h) in line) for line in layout) + ((3 if plan.touch else 1) if hidden else 0)
        shown = (plan, tuple(t.id for t in things), tuple(t.status for t in things),
                 tuple((a.id, a.label) for t in things for a in t.verbs), self.here_page, self._sprites_on())
        if shown != self.here_shown:
            self.here_shown = shown
            for container in (box, other):
                container.remove_children()
            first_person = next((t for t in things if t.character), None)
            rows_out = []
            for line in layout:
                tiles = [Tile(thing, form, size, numbers, content, plan.touch,
                              animate=not plan.touch or thing is first_person and thing.character)
                         for thing, form, size in line]
                rows_out.append(Horizontal(*tiles, classes="here-line"))
            box.mount_all(rows_out)
            if hidden:
                box.mount(Clickable(Text(f" +{hidden} more ▸ ", style="reverse #ffb000"), "screen.more_here()",
                                    classes="more"))
            if not things:
                box.mount(Static(Text("Nothing here.", style="#6c6f99")))
        box.border_title = f"Here · {len(things)}" if things else "Here"
        if plan.two_columns:
            side = self.query_one("#map").content_region.width or SIDE_WORDS
            plain = map_text(state, side)
            map_rows = len(plain.plain.splitlines()) + plan.edge
            self.query_one("#map").display = plan.here_rows - used > map_rows
            self.query_one("#map", Static).update(plain)
            self.query_one("#map").border_title = f"Floor {state.floor}/{state.floors_total}"

    @staticmethod
    def _ordered(things: list[Thing], numbers: dict[str, int]) -> list[Action]:
        """The live buttons, in the order they're numbered."""
        seen: dict[str, Action] = {}
        for thing in things:
            for action in thing.verbs:
                if action.id:
                    seen.setdefault(action.id, action)
        return sorted(seen.values(), key=lambda a: numbers[a.id])

    def _choices(self) -> list[Action]:
        game = self.game
        return [] if game.state.over else game.choices()

    def _strip(self) -> list[Action]:
        """The choices the strip keeps: what isn't a button on a tile. The ways out are the pad's or the ways bar's on a
        narrow screen; fight tactics and the ways out come before the rest."""
        on_tiles = {a.id for a in self.tile_verbs}
        actions = [a for a in self._choices() if a.id not in on_tiles]
        if any(a.id.startswith("use:@") for a in self.tile_verbs):  # (a foe's "Use…" picks the thing: no row for each)
            actions = [a for a in actions if not a.id.startswith(("use:", "throw:", "distract:"))]
        things = [a for a in actions if a.id.startswith(("use:", "throw:", "distract:", "reveal:"))]
        if len(things) > 1 and not self.game.state.scene:  # a row for each thing is a long list: one chip opens them
            state, content = self.game.state, self.game.content
            picker = next((a for a in interactions.verbs(state, content, "self") if interactions.is_picker(a.id)), None)
            if picker is not None:
                actions = [a for a in actions if a not in things] + [Action(picker.id, "Use an item…", picker.hint)]
        if not self.plan.two_columns and not self.game.state.scene:
            actions = [a for a in actions if not a.id.startswith("go:")]
        return sorted(actions, key=lambda a: not a.id.startswith(FIRST) or bool(self.game.state.scene))

    def refresh_choices(self) -> None:
        """The choices as chips side by side, wrapping onto as few lines as they need (up to the plan's), numbered after
        the buttons on the tiles; past that, pages, the last line of each ending in a chip saying how many more (tap it
        for the next page). Rebuilt only when they change: a rebuild swaps the choices out from under the mouse."""
        game, plan = self.game, self.plan
        scene = game.story.scene_title(game.state)
        actions = self._strip()
        suggesting = game.suggestion_pending()
        first = len(self.tile_verbs) + 1
        self.numbered = [*self.tile_verbs, *actions]
        if plan.two_columns:  # the pad lights the ways out, and dimly the locked doors (as the map shows them)
            self.query_one(DPad).show(self._choices(), game.locked_doors())
        shown = (plan, scene, game.state.over, suggesting, self.choice_page, first,
                 [(a.id, a.label, a.hint) for a in actions])
        if shown == self.choices_shown:
            return
        self.choices_shown = shown
        box = self.query_one("#choices", Vertical)
        box.remove_children()
        box.border_title = f"✧ {scene}" if scene else "Choices"
        box.set_class(bool(scene), "scene")
        if game.state.over:
            box.mount(Static(Text("Press Enter to see your fate.", style="#ffb000")))
            return
        width = plan.columns - 2
        chips = [(n, a, len(f"{n}. {a.label}") + (len(a.hint) + 4 if a.hint else 0) + 2 * a.id.startswith("go:") + 3)
                 for n, a in enumerate(actions, first)]
        if suggesting:  # its place is kept until it's thought of
            chips.append((first + len(actions), None, 8))
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
        rest = len(chips) - sum(map(len, page))
        for i, line in enumerate(page):
            row: list[Widget] = [ChoiceItem(n, a) if a else
                                 Static(Text(f"{n}. ✦ …", style="italic #6c6f99"), classes="choice")
                                 for n, a, _ in line]
            if rest and i == len(page) - 1:  # the page's last line ends with how many more
                row.append(Clickable(Text(f" ▼ {rest} more ", style="reverse #ffb000"), "screen.more_choices()",
                                     classes="more"))
            box.mount(Horizontal(*row, classes="choice-line"))

    def refresh_ways(self) -> None:
        """A narrow screen's ways out, directly above the choices: an arrow for each, lit where there is a door."""
        bar = self.query_one("#ways", Horizontal)
        bar.remove_children()
        if self.plan.two_columns:
            return
        choices, locked = self._choices(), self.game.locked_doors()
        ways = {a.id[3:]: a for a in [*locked, *choices] if a.id.startswith("go:")}
        for direction in ("west", "north", "south", "east"):
            way = ways.get(direction)
            label = Text(f"{ARROWS[direction]} {direction[0].upper()}", style="bold #5fe3ff" if way else "#2e3149")
            bar.mount(Clickable(label, f"screen.go('{direction}')" if way else "screen.nothing()", classes="way"))

    def action_nothing(self) -> None:
        """A button that isn't lit."""

    def action_more_here(self) -> None:
        self.here_page += 1
        self.here_shown = None
        self.refresh_here()

    def action_more_choices(self) -> None:
        self.choice_page += 1
        self.refresh_choices()

    def action_stage_card(self) -> None:
        """Clicked the room's picture: look around."""
        self.action_panel("look")

    def action_menu(self) -> None:
        """A short screen's ☰: the panels the footer's F-keys open."""
        if self.busy:
            return

        def done(name: str | None) -> None:
            if name:
                self.action_panel(name)

        self.app.push_screen(MenuScreen(), done)

    # --- what a press does ---

    def press(self, action: Action) -> None:
        """A button or a choice pressed: its action goes through the turn as it is (a picker opens its choices first)."""
        if self.busy:
            self.later(lambda: self.press(action))
            return
        if self.game.state.over or not action.id:
            return
        owner = self.verb_owner.get(action.id) if any(action is a for a in self.tile_verbs) else ""
        if owner:  # a button's words are bare ("Search"): the story says what it was done to
            action = Action(action.id, f"{action.label} · {owner}", action.hint)
        if interactions.is_picker(action.id):
            options = interactions.choices(self.game.state, self.game.content, action.id)

            def done(chosen: Action | None) -> None:
                if chosen is not None:
                    self.run_turn(chosen.label, action=chosen)

            self.app.push_screen(PickScreen(action.label.replace("… ·", " ·").removesuffix("…"), options), done)
        else:
            self.run_turn(action.label, action=action)

    def action_verb(self, action_id: str) -> None:
        """Clicked a button on a tile."""
        action = next((a for a in self.tile_verbs if a.id == action_id), None)
        if action is not None:
            self.press(action)
        self.query_one("#command", Input).focus()

    # --- story helpers ---

    def add_line(self, text: str | Text, classes: str, before=None) -> Static:
        widget = StoryLine(text if isinstance(text, Text) else Text(text), classes=classes)
        story = self.query_one("#story", VerticalScroll)
        story.mount(widget, before=before)
        self._follow()
        return widget

    def _mark_turn(self) -> Widget:
        """A zero-height marker where a turn begins. A new floor's page and the turn log go by it, not by a count of
        the story's children: a sprite moved or removed during the turn shifts every count (and cost a turn its
        command line in the log), but never the marker."""
        marker = Static("", classes="turn-marker")
        self.query_one("#story", VerticalScroll).mount(marker)
        self.turn_marker = marker
        return marker

    def _follow(self) -> None:
        """Keep the story where the turn can be read: at its end while the turn fits the story, and once it's taller
        (a picture, loot and narration under a command), at its start, so the command and the picture's top stay in
        view, however much more is added. Run 44's room pictures were scrolled off before they were seen."""
        story = self.query_one("#story", VerticalScroll)
        marker = self.turn_marker

        def settle() -> None:
            if marker is None or not marker.is_attached:
                story.scroll_end(animate=False)
                return
            top = marker.virtual_region.y
            if story.virtual_size.height - top <= story.scrollable_content_region.height:
                story.scroll_end(animate=False)
            else:
                story.scroll_to(y=top, animate=False)

        story.call_after_refresh(settle)

    def action_story_page(self, direction: int) -> None:
        """PageUp and PageDown read back through the story (the command line keeps the keyboard)."""
        story = self.query_one("#story", VerticalScroll)
        (story.scroll_page_down if direction > 0 else story.scroll_page_up)(animate=False)

    def lexicon(self) -> Lexicon:
        """The terms worth highlighting right now: what's in this room, what you carry, what lives here."""
        game = self.game
        return Lexicon(glossary.build(game.state, game.content, game.profile.bestiary()))

    def add_card(self, title: str, text: str, lexicon: Lexicon | None = None, sprite: str = "",
                 speech: bool = False) -> Widget:
        """A character's words (`speech`) or an authored moment's, in their own. Speech is words only: a bar down the
        left, who is speaking as its first line (so a card scrolled half out of view still says), then what they say;
        their picture is Here's. An authored moment keeps its picture, if it has one (the mirror of the Mirror Trial)."""
        if speech or not (sprite and self._sprites_on()):
            words = Text(f"{title}:\n" if title else "", style="bold #ff4f9a")
            words.append_text(highlight(f"“{text}”" if speech else text, lexicon, "italic #e8e8f4" if speech else ""))
            card = self.add_line(words, "say" if speech else "story-card")
            if not speech:
                card.border_title = f"✧ {title}" if title else "✧"
            return card
        region = self.query_one("#story", VerticalScroll).scrollable_content_region
        art = Picture(sprite, "", (region.width or 40) - 4, max(4, (region.height or 12) - 4),
                      content=self.game.content, sprites=True, classes="card-sprite")
        card = Vertical(art, StoryLine(highlight(text, lexicon)), classes="story-card")
        self.query_one("#story", VerticalScroll).mount(card)
        self._follow()
        card.border_title = f"✧ {title}" if title else "✧"
        return card

    def add_quest(self, text: str, new: bool = False) -> Widget:
        """A quest starting, moving on or done, in a box of its own: "★ NEW QUEST · Lucky Lenny's bad tooth"."""
        done = text.startswith("Quest complete: ")
        words = text.removeprefix("New quest: ").removeprefix("Quest complete: ").rstrip(".")
        label = "NEW QUEST" if new else "QUEST DONE" if done else "QUEST UPDATE"
        return self.add_line(Text(f"★ {label} · {words}"), "quest-banner")

    def _show_story(self, events: list[Event]) -> None:
        """Story cards, their effects and any secret found, after the narration."""
        lexicon = self.lexicon()
        library = self.game.story.library
        for event in events:
            if event.kind == "story" and event.data.get("voice") == "exact":
                self.add_card(event.data.get("title", ""), event.text, lexicon, event.data.get("sprite", ""),
                              speech="speaker" in event.data)
                sound.play("story")
            elif event.kind == "story_effect" and event.text and event.data.get("quest"):
                self.add_quest(event.text, new=event.text.startswith("New quest"))
            elif event.kind == "story_effect" and event.text:
                self.add_line(Text("  ◆ " + event.text, style="bold #ff4f9a"), "mechanic")
            elif event.kind == "story_secret" and not event.data.get("repeat"):
                sound.play("secret")
                found = len(self.game.profile.secrets())
                self.add_line(Text(f"  ✧ {event.text}  ({found}/{len(library.secrets)} in the Book of Secrets)",
                                   style="bold #ffd166"), "system-line")
                self.notify(event.data.get("title", ""), title="✧ Secret found", timeout=6)

    def add_floor_header(self, title: str, name: str, before=None) -> Static:
        """A banner across the story where a new floor begins."""
        text = Text(f"↓   {title.upper()}  ·  {name.upper()}   ↓", style="bold")
        return self.add_line(text, "floor-header", before=before)

    def add_entry(self, entry: LogEntry, lexicon: Lexicon | None = None) -> None:
        if entry.kind == "floor":
            self.add_floor_header(entry.title, entry.text)
            return
        if entry.kind == "card":
            self.add_card(entry.title, entry.text, lexicon, entry.art, speech=bool(entry.speaker))
            return
        if entry.kind == "mechanic":
            self.add_line(Text("  ⚄ " + entry.text, style="#6c6f99"), "mechanic")
            return
        if entry.kind == "player":
            self.add_line("> " + entry.text, "player-line")
            return
        prefix = "  " if entry.kind == "system" else ""
        classes = "system-line" if entry.kind == "system" else "narration"
        self.add_line(highlight(prefix + entry.text, lexicon), classes)

    @work(group="recap")
    async def pick_up_again(self) -> None:
        """Back in a run you left: a line where the story so far stops, and where you are (the stage and Here show the
        room); with a narrator, what's happened so far goes above them."""
        state = self.game.state
        self.busy = True  # (a turn taken while the recap is awaited would be logged twice, and before the seam)
        try:
            marker = self._mark_turn()
            seam = self.add_line(Text(f"↺  CONTINUED  ·  TURN {state.turn}", style="bold"), "continued")
            self.add_line(self._whereabouts(), "system-line")
            self.relayout()
            while state.pending_perks:  # (left mid level-up)
                if not await self._level_up():
                    break  # (put off: the perks wait as the choices)
            self._record_shown(marker)  # (the seam, as it is: the recap comes in above it, and is logged on its own)
            text = await self.game.recap(stand_in=False)
            if text:
                line = StoryLine(highlight("Previously… " + text, self.lexicon(), "italic #ff4f9a"), classes="recap")
                await self.query_one("#story", VerticalScroll).mount(line, after=seam)
                self.game.profile.log(state.run_id, state.turn, [("shown", shown(line))])
        finally:
            self.busy = False
        await self.suggest_later()

    def _whereabouts(self) -> Text:
        """Where you are, in a line: "You're in the Robing Room, on floor 1 of the Sunken Crypt, with 37/44 HP"."""
        state = self.game.state
        player, monster = state.player, state.room.monster
        words = (f"You're in {the(state.room.name)}, on floor {state.floor} of {mid_sentence(self.game.theme.name)}, "
                 f"with {player.hp}/{player.max_hp} HP.")
        if monster and monster.hp > 0:
            words += f" {cap(the(monster.name))} is here."
        return highlight("  " + words, self.lexicon())

    # --- turns ---

    @on(Input.Submitted, "#command")
    def submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if self.busy:
            if text and self.narration_stop is not None and self.queued is None:
                event.input.value = ""
                self.later(lambda: self.take_input(text))
            return
        if self.game.state.over:
            self.app.end_run(self)
            return
        if not text:
            return
        event.input.value = ""
        self.take_input(text)

    def take_input(self, text: str) -> None:
        """What was typed: a panel's word, a look around, a number (the same as pressing it), or a turn."""
        if self.busy or self.game.state.over:
            return
        if text.lower() in COMMANDS:
            self.action_panel(COMMANDS[text.lower()])
            return
        if looks(text) and not self.game.state.scene:  # (just a look around: the panel's, not a turn)
            self.action_panel("look")
            return
        guessing = "guess:1" in {a.id for a in self._choices()}  # (while Swoogy waits, "3" is a guess of 3)
        if text.isdigit() and not guessing and not self.game.state.scene:
            if 1 <= int(text) <= len(self.numbered):  # the same as pressing it: Here's buttons, then the choices
                self.press(self.numbered[int(text) - 1])
                return
        self.run_turn(text)

    @on(ChoiceItem.Chosen)
    def chosen(self, event: ChoiceItem.Chosen) -> None:
        """A click on a choice: that action, wherever it is in the list now (a click on one just replaced must not
        pick whatever took its number), or nothing if it's gone."""
        if self.busy:
            self.later(lambda: self.chosen(event))
            return
        if self.game.state.over:
            return
        action = next((a for a in self._choices() if a.id == event.action_id), None)
        if action is not None:
            if self.game.state.scene or action.id == "suggest":  # (a scene's, and the idea, go by their number)
                self.run_turn(str(next(i for i, a in enumerate(self._choices(), 1) if a.id == action.id)))
            else:
                self.press(action)

    @work(exclusive=True, group="turn")
    async def run_turn(self, text: str | None, action: Action | None = None) -> None:
        """A turn: the opening (None), a numbered choice or typed words, or an `action` from a panel (the shop's).
        Enter waits while it runs (see submitted). The box isn't disabled meanwhile: that moved focus twice a turn,
        and every move had Textual's footer rebuild itself, a fifth of a served game's work."""
        self.busy = True
        self.workers.cancel_group(self, "suggest")  # (the model's needed for this turn now)
        try:
            if text is None:
                await self._opening()
            else:
                await self._turn(text, action)
        finally:
            self.busy = False
            self.query_one("#command", Input).focus()
            queued, self.queued = self.queued, None
            if queued is not None:
                self.call_later(queued)  # (once this turn's worker is done: it's the same group)

    def _record_shown(self, since: Widget | None) -> None:
        """What the story has shown since the turn began (after its marker), top to bottom, in the run's turn log
        ("shown"): the facts are there already, so a played run reads back as it looked, pictures, cards and all."""
        state = self.game.state
        pieces = list(self.query_one("#story", VerticalScroll).children)
        if since is not None and since in pieces:
            pieces = pieces[pieces.index(since) + 1:]
        self.game.profile.log(state.run_id, state.turn,
                              [("shown", shown(w)) for w in pieces if not w.has_class("turn-marker")])

    async def _opening(self) -> None:
        state = self.game.state
        marker = self._mark_turn()
        self.add_floor_header(f"Floor {state.floor} of {state.floors_total}", self.game.theme.name)
        if splash_sizes(self.game.theme.key) and not state.test_room:  # a first floor with art has its card too
            self.app.push_screen(FloorScreen(state.floor, state.floors_total, self.game.theme, state.boss_floor))
        narration, on_text = self._narration_sink()
        result = await self.game.opening(on_text)
        narration.update(highlight(result.narration, self.lexicon()))
        self._follow()
        self._show_story(result.events)
        self._record_shown(marker)
        self.refresh_panels()
        await self.suggest_later()

    async def _turn(self, text: str, action: Action | None = None) -> None:
        game = self.game
        marker = self._mark_turn()
        at_the_counter, self.counter_open = self.counter_open, False  # (whether the shop's own screen sent this)
        choices = game.choices()
        shown = choices[int(text) - 1].label if text.isdigit() and 1 <= int(text) <= len(choices) else text
        shown = action.label if action else shown
        if not (action and action.id.startswith("take:")):  # a click on something lying there needs no echo
            self.add_line(f"> {shown}", "player-line")
        sound.play("select")
        hp_before = game.state.player.hp
        purse_before = purse(game.state)
        monster = game.state.room.monster
        before = (monster.key, monster.name) if monster else None
        room_before = game.state.room_id

        pending = await game.begin(text, action)
        primary = pending.primary
        while primary is not None:
            summary = pending.intent.summary or shown
            choice = await self.app.push_screen_wait(
                DiceScreen(primary.dice, summary, game.fate_left(), game.can_reroll(), auto=game.config.auto_roll,
                           tone=tone(primary), word=verdict(primary)))
            if choice == "reroll" and game.can_reroll():
                sound.play("fate")
                pending = game.reroll()
                primary = pending.primary
                # (counted from before the roll: game.state already holds any token the new roll won, run 44)
                self.add_line(Text(f"  ✦ Fate spent. Rerolling... ({game.fate_left()} left)",
                                   style="bold #ffd166"), "mechanic")
                continue
            break

        narration, on_text = self._narration_sink()
        for event in pending.events:
            if not event.dice:
                continue
            if event is primary:
                effects.flash(self.add_line(roll_text(event), "mechanic", before=narration), tone(event))
            else:
                line = DiceLine("", classes="mechanic")
                await self.query_one("#story").mount(line, before=narration)
                await line.play(event, fast=event.dice.actor == "monster")
        self.query_one("#hud", Hud).show(game.state, game.content)
        for moment in dict.fromkeys(filter(None, map(effects.event_sound, pending.events))):
            sound.play(moment)
        await self._roll_feedback(pending.events, hp_before)
        await self._purse_feedback(purse_before)
        await self._fight_animations(pending.events, before, room_before)
        await self._fixture_moment(pending.events)
        # Then, from the top, all above what's said of it: a new floor's header and a moment's banner. (The room, who
        # and what is in it are the stage's and Here's, drawn again below.)
        if any(e.kind == "descend" for e in pending.events):
            await self._new_page(marker)
            self._new_floor(narration)
        await self._secret_room_moment(pending.events, narration)
        await self._shop_moment(pending.events, narration)
        if any(e.kind == "tip" for e in pending.events):  # look: it's on your map
            effects.pulse(self.query_one("#map"), GREAT, blinks=2)
        self.refresh_panels()

        self.narration_stop = asyncio.Event()
        try:
            result = await game.finish(on_text, self.narration_stop)
        finally:
            self.narration_stop = None
        line = pickup_line(result.events, game.content) if result.narration else None
        if result.narration:
            if line:  # (the card said what it was; this says where it went)
                narration.update(Text(line))
                narration.set_classes("pickup-line")
            else:
                narration.update(highlight(result.narration, self.lexicon()))
            self._follow()
        else:
            await narration.remove()  # an authored moment speaks for itself
        for error in result.errors:
            self.add_line(f"  ({error})", "system-line")
        for exchange in exchange_lines(result.events, game.content):  # (what changed hands, in a line each)
            self.add_line(Text(exchange), "pickup-line")
        for warning in (e for e in result.events if e.kind == "warning"):  # (said as it is, never by the narrator)
            self.add_line(Text("  ⚠ " + warning.text, style="bold #ff7b39"), "system-line")
        for burn in (e for e in result.events if e.kind == "status_tick"):  # (poison's: in its own colour)
            status = statuses.DEFS.get(burn.data.get("status", ""))
            self.add_line(Text("  " + burn.text, style=f"bold {status.colour if status else '#b55088'}"), "system-line")
        chips = purse_chips(purse_before, purse(game.state))
        if chips and not line:  # (gold, bombs and keys found say so, with how many you have now)
            self.add_line(chips, "purse-line")
        self._show_story(result.events)
        self.since_redraw += 1
        if self.since_redraw >= self.app.REDRAW_EVERY:  # keeps a struggling terminal's picture from drifting
            self.since_redraw = 0
            self.call_after_refresh(self.app.action_redraw)
        self._toasts(result.events)
        self.refresh_panels()

        while game.state.pending_perks:
            if not await self._level_up():
                break  # (put off: the perks wait as the choices)
        if game.state.over:
            self.add_line(Text(f"Epitaph: {game.state.epitaph}", style="italic #ff4f9a"), "system-line")
            self._record_shown(marker)
            await asyncio.sleep(1.2)
            self.app.end_run(self)
            return
        self._record_shown(marker)
        shopping = any(e.kind == "shop" for e in result.events) or at_the_counter
        if shopping and game.state.room.shop:  # the counter again, after a purchase, a haggle or a sale there
            arg = action.id.partition(":")[2] if action else ""
            self.open_shop(int(arg) if arg.isdigit() else 0)
        await self.suggest_later()

    def action_shop_counter(self) -> None:
        """Clicked the shopkeeper: her shop, if you're in it."""
        if not self.busy and self.game.state.room.shop and not self.game.state.over:
            self.open_shop()

    def open_shop(self, selected: int = 0) -> None:
        """The shop's own screen: what's on the counter and what it costs. What you do there comes back as a turn."""
        def done(chosen: Action | None) -> None:
            if chosen:
                self.counter_open = True
                self.press(chosen)  # (a purchase or a haggle is a turn; "Sell…" opens its list first)

        self.app.push_screen(ShopScreen(self.game, selected), done)

    async def _level_up(self) -> bool:
        """The perk cards, until you pick one. Whether you did: closing them puts it off, and the perks wait as the
        choices (picked from there, it's an ordinary turn), with the cards back after your next move."""
        game = self.game
        choices = list(game.state.pending_perks)
        sound.play("level_up")
        perk = await self.app.push_screen_wait(LevelUpScreen(game.content, choices, game.state.player.level))
        if perk is None:
            return False
        index = next(i for i, a in enumerate(game.choices(), 1) if a.id == f"perk:{perk}")
        await game.begin(str(index))
        result = await game.finish(lambda _: None)
        self.add_line(Text("★ " + result.narration, style="bold #ffd166"), "system-line")
        self.refresh_panels()
        return True

    def _narration_sink(self):
        narration = self.add_line(Text("…", style="#6c6f99"), "narration")
        buffer: list[str] = []
        lexicon = self.lexicon()
        shown = 0.0

        def on_text(chunk: str) -> None:  # (all of it is shown once it's in: see _turn and _opening)
            nonlocal shown
            buffer.append(chunk)
            if time.monotonic() - shown >= NARRATION_STEP:
                shown = time.monotonic()
                narration.update(highlight("".join(buffer), lexicon))
                self._follow()

        return narration, on_text

    async def _new_page(self, turn_began: Widget) -> None:
        """A new floor, a clean page: the last floor's story leaves the screen (the save, the journal and the turn log
        keep it), and the page opens at its top. What came before the turn's marker goes; the turn's own command stays.
        Everything shown stays in the screen's layout, so a long run would grow heavier turn by turn."""
        story = self.query_one("#story", VerticalScroll)
        pieces = list(story.children)
        await story.remove_children(pieces[:pieces.index(turn_began)] if turn_began in pieces else [])
        story.scroll_home(animate=False)

    def _new_floor(self, narration: Static) -> None:
        """A header in the story, and the floor's card on top until you've read it (the arrival is narrated
        behind it in the meantime)."""
        game = self.game
        state = game.state
        self.add_floor_header(f"Floor {state.floor} of {state.floors_total}", game.theme.name, before=narration)
        self.app.push_screen(FloorScreen(state.floor, state.floors_total, game.theme, state.boss_floor))

    def _toasts(self, events: list[Event]) -> None:
        for event in events:
            if event.kind in TOASTS:
                title, severity = TOASTS[event.kind]
                self.notify(event.text, title=title, severity=severity, timeout=5)

    def _flash_hud(self, kind: str) -> None:
        hud = self.query_one("#hud")
        hud.add_class(kind)
        self.set_timer(0.45, lambda: hud.remove_class(kind))

    @staticmethod
    async def _shake(widget) -> None:
        for dx in (1, -1, 1, 0):
            widget.styles.offset = (dx, 0)
            await asyncio.sleep(0.035)

    # --- feedback ---

    async def _roll_feedback(self, events: list[Event], hp_before: int, gold_before: int | None = None) -> None:
        """How the turn went, at a glance: the story's border lights up in its colour (and blinks and shakes for a
        natural 20 or 1), damage rises off the monster, and your hearts show what you lost or gained."""
        story = self.query_one("#story")
        how = overall(events)
        if how:
            effects.pulse(story, how, blinks=3 if how in (GREAT, AWFUL) else 1)
        hits = [e for e in events if e.kind == "hit" and e.data.get("damage")]
        if hits:
            crit = any(e.dice and e.dice.crit for e in hits)
            dealt = sum(e.data["damage"] for e in hits)
            await self._pop_over_scene(f" -{dealt}{'!' if crit else ''} ",
                                       f"bold {effects.INK} on {effects.COLORS[GREAT] if crit else '#ffffff'}")
        elif any(e.kind == "miss" for e in events):
            await self._pop_over_scene(" MISS ", "bold #c8c8e0 on #23274a")
        player = self.game.state.player
        change = player.hp - hp_before
        if change:  # just under the HP numbers, on the story's top border, sliding right
            hud = self.query_one("#hud").region
            x = hud.x + 1 + len(hearts(player.hp, player.max_hp)) + len(f" {player.hp}/{player.max_hp}") - 2
            style = (f"bold #ffffff on {effects.COLORS[BAD]}" if change < 0
                     else f"bold {effects.INK} on {effects.COLORS[GOOD]}")
            await effects.popup(self, f" {change:+d} ♥ ", style, x, hud.y + 1, dx=4, dy=0)
            self._flash_hud("hurt" if change < 0 else "healed")
            if change > 0:
                sound.play("heal")
            elif not any(e.kind == "monster_hit" for e in events):  # a blow already made its own sound
                sound.play("hurt")
        if gold_before is not None and player.gold > gold_before:
            sound.play("coin")
        if how in (GREAT, AWFUL):
            await self._shake(story)

    async def _purse_feedback(self, before: dict[str, int]) -> None:
        """Gold, bombs or keys gained: their counters light up on the status bar, the gain rises off them, and it
        clinks (gold) or clicks (the rest)."""
        after = purse(self.game.state)
        gained = {name: after[name] - before[name] for name, *_ in PURSE if after[name] > before[name]}
        if not gained:
            return
        hud = self.query_one("#hud", Hud)
        hud.light(set(gained))
        sound.play("coin" if "gold" in gained else "item")
        marks = {name: (mark, colour) for name, mark, colour, *_ in PURSE}
        for name, amount in gained.items():
            if name in hud.at and hud.region.width:
                mark, colour = marks[name]
                x = hud.region.x + 1 + hud.at[name]
                await effects.popup(self, f" +{amount} {mark} ", f"bold #10122a on {colour}", x, hud.region.y + 1,
                                    dx=0, dy=1)

    async def _pop_over_scene(self, text: str, style: str) -> None:
        """A popup rising off the foe's tile (or the stage, with no tile to show it on)."""
        monster = self.game.state.room.monster
        picture = self._tile_picture(monster.key) if monster else None
        region = (picture or self.query_one("#stage-box")).region
        if not region.width:
            return
        x = region.x + max(1, (region.width - len(text)) // 2)
        await effects.popup(self, text, style, x, region.y + min(7, region.height // 2))

    # --- animation ---

    def _sprites_on(self) -> bool:
        return self.game.config.art == "sprites"

    def _tile_picture(self, key: str) -> Picture | None:
        """The picture on Here's tile for `key` (a monster, a fixture), if it has one on show."""
        return next((p for p in self.query(".here-art").results(Picture) if p.key == key and p.display), None)

    async def _fight_animations(self, events: list[Event], before: tuple | None, room_before: int) -> None:
        """Flash white when hit, lunge when attacking, dissolve when it dies (or a ghost finds rest)."""
        game = self.game
        if before is None or game.state.room_id != room_before:
            return
        kinds = {e.kind for e in events}
        gone = game.state.room.monster is None
        picture = self._tile_picture(before[0])
        steps: list[tuple[str, int, bool]] = []
        if "hit" in kinds:
            frame = picture.frame if picture else 0
            steps += [("idle", frame, flash) for flash in (True, False, True, False)]
        if not gone and kinds & {"monster_hit", "monster_miss", "evade", "dodge"}:
            steps += [("lunge", 0, False), ("lunge", 1, False), ("idle", 0, False)]
        if gone:
            steps += [("death", step, False) for step in range(DEATH_FRAMES)]
            sound.play("kill")
        if not self._sprites_on():
            steps = [s for s in steps if s[0] == "idle"]  # ASCII art can still flash
        if steps and picture is not None:
            await self._play_scene(picture, steps)

    async def _play_scene(self, picture: Picture, steps: list[tuple[str, int, bool]]) -> None:
        """A fight's moment on the foe's tile, steps of (pose, frame, flash): its picture plays them, and the lines under
        it hold still."""
        self.animating = True
        try:
            await picture.play([(frame, pose, flash) for pose, frame, flash in steps], delay=0.07)
        finally:
            self.animating = False

    async def _fixture_moment(self, events: list[Event]) -> None:
        """Opening a chest, drinking from a fountain, an offering, going down the stairs: play it out on the fixture's
        tile (the sound plays wherever it is)."""
        kind = next((e.kind for e in events if e.kind in FIXTURE_MOMENTS), None)
        if kind is None:
            return
        key, steps = FIXTURE_MOMENTS[kind]
        sound.play(kind)
        picture = self._tile_picture(key) if self._sprites_on() else None
        if picture is not None:
            await picture.play(steps)  # (the stairs dissolve into the dark)

    async def _secret_room_moment(self, events: list[Event], narration: Static) -> None:
        """The floor's secret room, found: a fanfare after the bang, a banner glittering across the story, the story
        and the map blinking gold, and the room in gold on the map from then on."""
        found = next((e for e in events if e.kind == "secret_room"), None)
        if found is None:
            return
        self.set_timer(0.35, lambda: sound.play("secret_room"))
        story = self.query_one("#story", VerticalScroll)
        banner = self.add_line(secret_banner(0), "secret-banner", before=narration)
        self._follow()
        effects.pulse(story, GREAT, blinks=3)
        effects.pulse(self.query_one("#map"), GREAT, blinks=3)
        room = self.game.state.rooms[found.data["room"]]
        self.notify(f"{room.name}, sealed until now.", title="✧ Secret room found", timeout=6)

        async def glitter() -> None:
            for frame in range(1, len(SPARKS) * 3):
                await asyncio.sleep(0.09)
                banner.update(secret_banner(frame))
            banner.update(secret_banner(0))

        await asyncio.gather(glitter(), self._pop_over_scene(" ✧ SECRET ROOM! ✧ ",
                                                             f"bold {effects.INK} on {effects.COLORS[GREAT]}"))

    async def _shop_moment(self, events: list[Event], narration: Static) -> None:
        """Walking into a shop for the first time: a jingle and a banner, gold and starrier for the rare Granny
        Kamultruk (the shop is on the map from then on, in green)."""
        room = self.game.state.room
        if not room.shop or not any(e.kind == "enter" and e.data.get("first") for e in events):
            return
        shiny = room.shop.keeper == loot.SHINY
        keeper = self.game.content.monster(room.shop.keeper).name
        sound.play("shop_shiny" if shiny else "shop")
        words, colour = (keeper.upper(), "#ffd166") if shiny else ("SHOP", "#4cff8a")
        story = self.query_one("#story", VerticalScroll)
        banner = self.add_line(secret_banner(0, words, colour), "secret-banner" if shiny else "secret-banner shop",
                               before=narration)
        self._follow()
        effects.pulse(story, GREAT if shiny else GOOD, blinks=3 if shiny else 2)
        self.notify(f"{keeper} has her wares out.", title="★ A rare shop!" if shiny else "¤ A shop", timeout=6)
        for frame in range(1, len(SPARKS) * (3 if shiny else 2)):
            await asyncio.sleep(0.09)
            banner.update(secret_banner(frame, words, colour))
        banner.update(secret_banner(0, words, colour))

    async def update_suggestion(self) -> None:
        if not self.game.state.scene:
            await self.game.refresh_suggestion()
        self.refresh_choices()

    async def suggest_later(self) -> None:
        """The suggested trick for the scene now. With a model to ask, it's asked in the background (the next move
        needn't wait for it, and cuts it short: see run_turn); offline, it's there at once."""
        if self.game.llm is None:
            await self.update_suggestion()
        else:
            self.run_worker(self.update_suggestion(), group="suggest", exclusive=True)

    def later(self, call) -> None:
        """A move made mid-turn: while the narrator's still talking, it cuts the narration short (whole sentences
        told so far stand) and is made as soon as the turn's done. Otherwise, mid-turn, it waits for nothing."""
        if self.narration_stop is not None and self.queued is None:
            self.queued = call
            self.narration_stop.set()

    # --- panels ---

    def panel(self, name: str) -> Panel:
        """One of the panels F1-F7 open (see panels.PANEL_KEYS), for this game."""
        screens = {"help": HelpScreen, "inventory": InventoryScreen, "character": CharacterScreen,
                   "look": LookScreen, "map": MapScreen, "bestiary": BestiaryScreen, "journal": JournalScreen}
        return screens[name]() if name == "help" else screens[name](self.game)

    def can_open_panel(self, name: str) -> bool:
        """Whether a panel can open now: not mid-turn, bar the help."""
        return not self.busy or name == "help"

    def _picked(self, picked: Action | str | None) -> None:
        """What a panel or a card sent back: the engine's action for it, as it is (a picker opens its choices), or the id
        of one of the numbered choices."""
        if isinstance(picked, Action):
            self.press(picked)
        elif picked:
            action = next((a for a in self._choices() if a.id == picked), None)
            if action is not None:
                self.press(action)

    def action_panel(self, name: str) -> None:
        """Open a panel (see can_open_panel): what's picked in it comes back as that choice's turn."""
        if not self.can_open_panel(name):
            return

        self.app.push_screen(self.panel(name), self._picked)

    open_panel = action_panel  # (what a panel's F1-F7 open the next one with: see Panel.action_switch)

    def action_lookup(self, term_id: str) -> None:
        """Clicked a highlighted word: show what it is (and offer the matching action, if there is one)."""
        if self.busy:
            return

        self.app.push_screen(InfoScreen(self.game, term_id), self._picked)

    def action_go(self, direction: str) -> None:
        """Clicked an arrow on the pad: go that way, as if you'd picked its choice. A locked door (no choice of its own)
        says it's locked and what would open it, costing nothing."""
        if self.busy:
            self.later(lambda: self.action_go(direction))
            return
        if self.game.state.over:
            return
        index = next((i for i, a in enumerate(self.game.choices(), 1) if a.id == f"go:{direction}"), None)
        locked = next((a for a in self.game.locked_doors() if a.id == f"go:{direction}"), None)
        if index:
            self.run_turn(str(index))
        elif locked:
            self.run_turn(locked.label, locked)

    def action_travel(self, room_id: int) -> None:
        """Clicked a room on the map: quick travel back to it (rules.journey), as a turn of its own."""
        if self.busy:
            self.later(lambda: self.action_travel(room_id))
            return
        state = self.game.state
        if state.over or not 0 <= room_id < len(state.rooms):
            return
        self.run_turn(f"Travel to {state.rooms[room_id].name}",
                      Action(f"travel:{room_id}", f"Travel to {state.rooms[room_id].name}"))

    def action_leave(self) -> None:
        """Esc twice: to the title (the game's saved). Once only asks, so an Esc meant for a panel or the command
        palette never throws you out of a run."""
        if self.busy:
            return
        now = time.monotonic()
        if now - self.leave_asked > LEAVE_WINDOW:
            self.leave_asked = now
            self.notify("Press Esc again for the title screen. (Your game is saved.)", timeout=LEAVE_WINDOW)
            return
        self.app.leave_game(self)

