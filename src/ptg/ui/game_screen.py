"""The main game screen: a stage (the room's picture) over a story of words, Here (who and what is in the room, with
buttons for what you can do with them) beside them or in a strip under the stage, the choices in a strip under the
story, and the command line. How it's shared out for the size is ui/plan.py's; GameScreen.relayout applies it."""

from __future__ import annotations

import asyncio
import os
import time

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, Input, Static

from .. import config, encounter, glossary, interactions, inventory, loot, sound, statuses
from ..events import Action, Event
from ..game import Game
from ..glossary import Lexicon
from ..llm.interpreter import looks
from ..models import OPPOSITE, LogEntry, MonsterState
from ..outcome import AWFUL, BAD, GOOD, GREAT, overall, tone, verdict
from ..room_picture import look_of, picture_image, picture_text
from ..rules import no_go, no_way
from ..sprites import CLIP_FPS, DEATH_FRAMES, clips, splash_sizes
from ..text import cap, mid_sentence, the
from . import art_layer, collector, effects
from .boss_intro import BossIntro, fits
from .boss_intro import wanted as big_intro
from .dice import DiceScreen
from .here import CARD, MINI, ROW, Thing, Tile, arrange, things_here
from .panels import (BestiaryScreen, CharacterScreen, FloorScreen, HelpScreen, InfoScreen, InventoryScreen,
                     JournalScreen, LevelUpScreen, LookScreen, MenuScreen, Panel, PickScreen, ShopScreen)
from .plan import Plan, make_plan
from .widgets import (ARROWS, IDLE, LIT, UNLIT, ChoiceItem, Clickable, ClickableBox, DiceLine, DPad, Hud, Picture,
                      StoryLine, hearts, highlight, monster_pose, roll_text, room_text)

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
SETTLE_AFTER = 0.6  # seconds after a new floor's card comes up that the garbage collector sweeps (ui/collector.py)
PRELOAD_AFTER = 3.0  # seconds into a run that its floors' art and its bosses' clips are read, in the background
LOOP_BEATS = round(IDLE * CLIP_FPS)  # a fight's ticks to a sprite's breath, among foes playing clips (loop_step)
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
MUSIC_AFTER_STING = 0.8  # seconds after a fight's sting (its foe landing) that its music comes in
THEIR_BEAT = 0.45  # seconds between your go in a fight and the foes' goes after it (rules.theirs)
SPOILS_HOLD = 6.0  # the most seconds a fight's spoils stay up, unless a key or a click goes on sooner
# What a fight's turn shows on the stage: your blows and the foes', and those that end one.
STAGE_KINDS = {"hit", "miss", "defeat", "pacify", "monster_hit", "monster_miss", "evade", "dodge"}


def paused(seconds: float) -> float:
    """A fight's pause (THEIR_BEAT, SPOILS_HOLD), or none at all with PTG_FIGHT_PAUSES=0 (the tests)."""
    return 0.0 if os.environ.get("PTG_FIGHT_PAUSES") == "0" else seconds


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
    return str(widget.render()) if isinstance(widget, Static) else type(widget).__name__


def boss_here(state, content) -> bool:
    """Whether this floor's dungeon has its boss on it (the last dungeon's, or one holding its own on an earlier floor:
    world.EARLY_BOSSES, unless King Mouse has its stairs): its card says what you're there to do."""
    theme = content.themes[state.theme]
    return state.boss_floor or any(r.monster is not None and r.monster.key == theme.boss for r in state.rooms)


LAYOUTS = ("tabs", "grid", "classic")  # what F9 goes through, in turn (action_switch_layout)
LAYOUT_NAMES = {"tabs": "Tabs: the story beside the room's tabs", "grid": "The grid: big buttons, the map always up",
                "classic": "Classic: the story with Here and the map beside it"}
FIGHT_MUSIC = ("battle_music", "boss_music")
GAME_MUSIC = ("explore_music", "deep_music") + FIGHT_MUSIC


def music_for(state, content) -> str:
    """The music for where you are: a fight's while a monster's after you (a boss's own, if one's in it, whichever of
    it you face), else the floor's, darker on the boss floors."""
    if state.in_combat:
        foes = [m for m in [state.room.monster, *state.room.others] if m.hostile and m.hp > 0]
        boss = any((known := content.monsters.get(m.key)) and known.boss for m in foes)
        return "boss_music" if boss else "battle_music"
    return "deep_music" if state.boss_floor else "explore_music"


class GameScreen(Screen):
    STORY_WIDTH = 9999  # the most columns a story line takes (the grid caps it in app.tcss: a column down the middle)
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
        Binding("f9", "switch_layout", "Layout"),
        *[Binding(key, f"arrow('{way}')", show=False, priority=True)
          for key, way in (("up", "north"), ("down", "south"), ("left", "west"), ("right", "east"))],
    ]

    def __init__(self, game: Game, fresh: bool, switched: bool = False) -> None:
        super().__init__()
        self.game = game
        self.fresh = fresh
        self.switched = switched  # the run carrying on in another layout (action_switch_layout): no recap
        self.switching = False  # leaving for another layout: the music plays on
        self.fights_scored = 0  # fights that have had music: each the next of its tunes (refresh_music)
        self.busy = False
        self.narration_stop: asyncio.Event | None = None  # set to cut the narrator short (later)
        self.queued = None  # what to do once the turn's done: a move made while the narrator was still talking
        self.turn_marker: Widget | None = None  # where the turn now being shown began (see _mark_turn)
        self.follow_from: Widget | None = None  # the turn's first story card, if it has one: kept in view (_follow)
        self.last_rolls: list[Event] = []  # the last turn's rolls, for a layout that calls them out (see grid.py)
        self.animating = False  # a fight's flashes, lunges or death are playing on its tile
        self.counter_open = False  # the shop's own screen sent the turn now coming: it opens again after it
        self.counter = None  # the shop's window while it's up over this screen: what's done there is told there
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
        self.looping = False  # a fight on the stage with clips of its own: played through, a frame a tick (loop_step)
        self.hires: tuple | None = None  # on the web, (its key, the fight made at the art layer's pixels: send_stage)
        self.hires_rooms: dict = {}  # on the web, (the stage's key, its frame) -> the room drawn at those pixels
        self.art_hidden = True  # whether the stage's picture is off the page (or was never sent)
        self.loop_tick = 0
        self._loop_timer = None
        self.fight: encounter.Fight | None = None  # the fight on the stage, while there's one (encounter.py)
        self.fight_key: tuple | None = None  # whose, where, how big: a new one of those, a new Fight
        self.fight_events: list[Event] = []  # what the fight on now has paid so far: its spoils, once it's won
        self.holding: asyncio.Event | None = None  # set to go on from a fight's spoils (see _hold)
        self.ahead: dict[tuple, encounter.Fight] = {}  # the fights behind this room's doors, made ahead
        # (ready_fights): (floor, room, its key, its name, width, height) for each
        self.here_page = self.choice_page = 0  # the "more" chips turn these
        self.map_hover: int | None = None  # the room on the map the mouse is on, that you can get back to: lit
        self.prepared: tuple | None = None  # a room's picture drawn for the stage already (a wipe's): (whose, it)
        self.stage_floor = 0  # the floor the stage's picture is of
        self.stage_still: Text | None = None  # the stage's picture as drawn (its first frame)
        self.frame_shown: tuple | None = None  # the size of what's on the stage (show_frame)
        self.their_sounds: list[str] = []  # the foes' go's sounds, kept for their swing on the stage (_sound_theirs)
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
                yield StoryLine(id="map", classes="panel")  # (its rooms clicked: you go there, as on the grid's)
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
            if self.switched:  # (the same run, laid out another way: carried on from where it was)
                self.relayout()
                self.call_after_refresh(lambda: self.query_one("#story", VerticalScroll).scroll_end(animate=False))
            else:
                self.pick_up_again()
        self.query_one("#command", Input).focus()
        self.refresh_music()
        self.set_timer(PRELOAD_AFTER, lambda: self.run_worker(self._preload, thread=True, group="preload"))

    def _preload(self) -> None:
        """The run's floors' splash art and the clips of the bosses and guardians it may meet, read ahead in the
        background: each was decoded on the game's thread the moment it was first wanted (a floor's card, a boss
        coming in)."""
        state, content = self.game.state, self.game.content
        for theme in dict.fromkeys(state.themes):
            splash_sizes(theme)
        for key, monster in content.monsters.items():
            if monster.boss or "guardian" in monster.tags:
                clips(key)
        collector.freeze()  # (all of it here to stay: out of the collector's sight)

    def on_unmount(self) -> None:
        if not self.switching:
            sound.stop_music(only=GAME_MUSIC)  # (to the title: its own may have started already)

    def refresh_music(self) -> None:
        """The music for where you are now (music_for), if it isn't playing already. A fight's cuts straight in, the
        floor's fading fast under it; once it's over the floor's comes slowly back as the fight's dies away. A run
        that's ended keeps what it had (it stops with the screen). A fight's plays on till the fight's over, whoever
        of it you turn to or falls (run 66: the Fungus's started again with each of its parts). Each fight has the
        next of the fight's tunes, and each floor its own of the floor's (sound.Sound.tune), so they don't get old."""
        state, engine = self.game.state, sound.engine()
        moment, playing = music_for(state, self.game.content), engine.wanted
        if state.over or moment in FIGHT_MUSIC and playing in FIGHT_MUSIC:
            return
        if moment in FIGHT_MUSIC:
            self.fights_scored += 1
            sound.music(moment, fade_in=0.0, fade_out=0.4, variant=self.fights_scored - 1)
        elif moment != playing or engine.variant != engine.tune(moment, state.floor - 1):
            sound.music(moment, fade_in=2.5, fade_out=1.5, variant=state.floor - 1)

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
            self.hide_stage_art()
            return
        state, room = game.state, game.state.room
        monster = room.monster
        shown = (plan.stage_width, plan.stage_rows, plan.compact, state.floor, state.room_id, tuple(room.items),
                 (monster.key, monster.hostile) if monster and monster.hp > 0 else None, room.fixture_used,
                 tuple(f.searched for f in room.features), self._sprites_on(), self.fight_state())
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

    def fight_state(self) -> tuple | None:
        """What the stage shows of a fight (encounter.py), for knowing when to draw it again: the foe's health, its
        next move, how it is, what you know of it, and what makes it more or less dangerous to you."""
        state = self.game.state
        if not state.in_combat:
            return None
        monster, player = state.room.monster, state.player
        return (monster.hp, monster.intent, monster.guarding, monster.stunned, bool(monster.stolen_item or
                monster.stolen_gold), tuple(state.known_weak.get(monster.key, [])), player.level, player.weapon,
                player.armor, player.helm, player.max_hp)

    def fight_view(self, width: int, height: int) -> encounter.Fight | None:
        """The fight on the stage (encounter.Fight), while a monster's after you and the stage has the room for it
        (sprites on): made again only for another foe, room or size, and otherwise brought up to date."""
        state, content = self.game.state, self.game.content
        if not (state.in_combat and self._sprites_on() and encounter.Image is not None and height >= 12):
            self.fight = self.fight_key = None
            return None
        monster = state.room.monster
        known = state.known_weak.get(monster.key, [])
        key = (state.floor, state.room_id, monster.key, monster.name, width, height)
        made = self.ahead.pop(key, None)
        if made is not None and (self.fight is None or self.fight_key != key):  # (made ahead: ready_fights)
            made.update(state, monster, known)
            self.fight, self.fight_key = made, key
        elif self.fight is None or self.fight_key != key:
            same = self.fight is not None and self.fight_key is not None and self.fight_key[:2] + self.fight_key[4:] \
                == key[:2] + key[4:]  # (another foe of the same fight: the room behind it is as it was, not drawn again)
            self.fight = encounter.Fight(state, content, monster, width, height // 2, known,
                                         back=self.fight.back if same else None)
            self.fight_key = key
        else:
            self.fight.update(state, monster, known)
        return self.fight

    def draw_stage(self, width: int, height: int) -> None:
        """The room's picture on the stage, in the first frame of whoever's here and what lies about; every IDLE
        seconds after, it swaps with the second (stage_step), so they breathe and bob as they do everywhere else. In
        a fight, the fight (fight_view): the foe big in the dimmed room, breathing likewise."""
        state, content = self.game.state, self.game.content
        fight = self.fight_view(width, height)
        prepared, self.prepared = self.prepared, None
        if fight is not None:
            art = fight.still(0, monster_pose(state.room.monster))
        elif prepared and prepared[0] == (state.floor, state.room_id, width, height):
            art = prepared[1]  # (drawn for the wipe into it just now)
        else:
            art = picture_text(state, content, width, height) if self._sprites_on() else None
        self.stage_floor = state.floor
        self.stage_frames = [art, None] if art is not None else []
        self.stage_still = art  # (what's on the stage, kept when the room's found to have nothing that moves)
        self.stage_size, self.stage_beat = (width, height), 0
        self.show_frame(art or room_text(state, content))
        if self._stage_timer is None and art is not None:
            self._stage_timer = self.set_interval(IDLE, self.stage_step, name="stage")
        self.looping = fight is not None and fight.loops()
        if self.looping and self._loop_timer is None:
            self._loop_timer = self.set_interval(1 / CLIP_FPS, self.loop_step, name="loop")
        self.send_stage(0)

    def show_frame(self, frame, art: Static | None = None) -> None:
        """A frame on the stage: laid out again only if it isn't the size of what's there (effects.show_frame). The
        stage's moments play in half blocks for now: the art layer's picture steps aside for them."""
        if self.animating:
            self.hide_stage_art()
        self.frame_shown = effects.show_frame(art or self.query_one("#stage-art", Static), frame, self.frame_shown)

    # --- the art layer: on the web, the stage drawn as an image at its own pixels (ui/art_layer.py) ---

    def send_stage(self, frame: int = 0, tick: int | None = None) -> None:
        """On the web, the stage's picture as it stands, as an image: the room, or the fight in it (its banner stays
        words, under the picture; the words over the foes' heads go with it, for the page to draw). What takes long
        to draw at those pixels (a room, a fight's copy) is drawn off the screen's thread and sent once it's ready.
        Not while the stage plays a moment of its own, nor under another screen."""
        if not art_layer.active(self.app) or not self._sprites_on() or not self.plan or not self.plan.stage_rows:
            return
        if self.animating or self.app.screen is not self:
            return
        art, scale, state = self.query_one("#stage-art", Static), art_layer.SCALE, self.game.state
        width, rows = self.plan.stage_width, self.plan.stage_rows
        fight = self.fight
        if fight is not None and state.in_combat:
            art_rows = rows - fight.banner_rows
            key = (state.floor, state.room_id, fight.monster.key, fight.monster.name, width, rows)
            if self.hires is None or self.hires[0] != key:
                self.hires = (key, None)
                snapshot, monster = state.model_copy(deep=True), fight.monster
                self.run_worker(lambda: self._make_hires(key, snapshot, monster, width * scale, art_rows * scale + 2),
                                thread=True, group="hires", exclusive=True)
                return
            hires = self.hires[1]
            if hires is None:
                return
            hires.monster, hires.seen = fight.monster, fight.seen  # (as the stage last showed it: the text fight's)
            hires.others, hires.others_seen = fight.others, fight.others_seen
            image = hires.image(frame, monster_pose(fight.monster), tick)
            image = image.crop((0, 0, image.width, 2 * art_rows * scale))
            art_layer.show(self.app, "stage", art, image, fight.chips, rows=art_rows)
        else:
            key = (self.stage_shown, frame)
            image = self.hires_rooms.get(key)
            if image is None:
                snapshot = state.model_copy(deep=True)
                self.run_worker(lambda: self._make_room(key, snapshot, width * scale, 2 * rows * scale, frame),
                                thread=True, group=f"hires-room-{frame}", exclusive=True)
                return
            art_layer.show(self.app, "stage", art, image)
        self.art_hidden = False

    def _make_hires(self, key: tuple, state, monster: MonsterState, width: int, rows: int) -> None:
        """A copy of the fight at the art layer's pixels, made off the screen's thread (send_stage)."""
        hires = encounter.Fight(state, self.game.content, monster, width, rows, state.known_weak.get(monster.key, []))
        app = self.app

        def keep() -> None:
            if self.hires and self.hires[0] == key:
                self.hires = (key, hires)
                self.send_stage()
        try:
            app.call_from_thread(keep)
        except RuntimeError:  # (the game's gone)
            pass

    def _make_room(self, key: tuple, state, width: int, height: int, frame: int) -> None:
        """The room drawn at the art layer's pixels, off the screen's thread (send_stage)."""
        image = picture_image(state, self.game.content, width, height, frame)
        app = self.app

        def keep() -> None:
            self.hires_rooms[key] = image
            while len(self.hires_rooms) > 8:
                self.hires_rooms.pop(next(iter(self.hires_rooms)))
            if key[0] == self.stage_shown:
                self.send_stage(frame)
        try:
            app.call_from_thread(keep)
        except RuntimeError:
            pass

    def hide_stage_art(self) -> None:
        """The stage's picture off the page (a moment playing in half blocks, the stage gone, a screen over it)."""
        if not self.art_hidden and art_layer.active(self.app):
            art_layer.hide(self.app, "stage")
        self.art_hidden = True

    def on_screen_suspend(self) -> None:
        self.hide_stage_art()  # (the page's picture would sit over whatever's put on top)

    def on_screen_resume(self) -> None:
        self.send_stage()

    def loop_step(self) -> None:
        """A tick of a fight's own clips on the stage: every foe's idle (or its windup, a heavy blow coming) played
        through at its own speed, a sprite among them breathing at its usual pace. It plays on through a turn (the
        dice over it, the beat before the foes' go, the words being written), stopping only while the stage plays a
        moment of its own (a blow, a fall: animating) or can't be seen, and is drawn as the stage last showed the
        fight (its copy), not as the turn's left it, till the stage gets to that."""
        fight, state = self.fight, self.game.state
        if not self.looping or fight is None or self.animating or not self.is_current \
                or self.fight_key is None or self.fight_key[:2] != (state.floor, state.room_id):  # (fled: not here)
            return
        self.loop_tick += 1
        beat = self.loop_tick // LOOP_BEATS % 2
        self.show_frame(fight.still(beat, monster_pose(fight.monster), tick=self.loop_tick))
        self.send_stage(beat, tick=self.loop_tick)

    def stage_step(self) -> None:
        """A beat of the stage's idle animation: the other frame, while this screen's in front and nothing else is
        moving on it (a turn, a blow, a chest opening). Its second frame is drawn the first time it's wanted, off the
        screen's thread (a room takes a tenth of a second or so: a click then shouldn't wait on it), and a room with
        nothing that moves stops asking."""
        frames = self.stage_frames
        if self.looping or len(frames) != 2 or self.busy or self.animating or self.app.screen is not self:
            return  # (a fight with clips of its own plays them: loop_step)
        if frames[1] is None:
            snapshot = self.game.state.model_copy(deep=True)  # (what it draws can't change under it mid-turn)
            self.run_worker(lambda: self._second_frame(frames, snapshot), thread=True, group="stage", exclusive=True)
            return
        self.stage_beat += 1
        self.show_frame(frames[self.stage_beat % 2])
        self.send_stage(self.stage_beat % 2)

    def _second_frame(self, frames: list, state) -> None:
        """The stage's second frame, drawn in a worker thread, then kept, if the stage still shows the same room (or
        fight)."""
        fight = self.fight
        if fight is not None and state.room.monster is not None:
            second = fight.still(1, monster_pose(state.room.monster))
        else:
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
            self.draw_side_map(plan.here_rows - used - plan.edge)

    def draw_side_map(self, rows: int) -> None:
        """The floor in the side column, as big as the rows Here leaves it: the grid's chart (its rooms clicked, you go
        there; the one the mouse is on lit), else the marks with their names, else the marks; and F5 for it in full."""
        from .grid import drawn_map  # (the grid builds on this module)

        state = self.game.state
        box = self.query_one("#map", StoryLine)
        side = box.content_region.width or SIDE_WORDS
        drawn = drawn_map(state, side, max(3, rows - 2), hover=self.map_hover)
        box.display = len(drawn.plain.splitlines()) + 2 <= rows
        box.update(drawn)
        box.border_title = f"Floor {state.floor}/{state.floors_total}"
        box.border_subtitle = "F5 in full"

    def hover_room(self, line: StoryLine, room: int | None) -> None:
        """The mouse has come to a room on the side map you can get back to (or left it): it's lit, or not."""
        if line.id == "map" and room != self.map_hover:
            self.map_hover = room
            self.here_shown = None
            self.refresh_here()

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
        """Clicked the room's picture: look around (or, on a fight's spoils, go on from them); in a fight, the foe you
        face up close, its own animations big (ui/creature.py)."""
        if self.release():
            return
        state = self.game.state
        if state.in_combat and not self.busy:
            self.action_watch(state.room.monster.key, state.room.monster.name)
            return
        self.action_panel("look")

    def action_watch(self, key: str, name: str = "") -> None:
        """A creature up close: its own animations played big (ui/creature.py)."""
        from .creature import CreatureView

        if key in self.game.content.monsters:
            self.app.push_screen(CreatureView(self.game.content, key, name))

    def action_menu(self) -> None:
        """A short screen's ☰: the panels the footer's F-keys open, and sound on or off."""
        if self.busy:
            return

        def done(name: str | None) -> None:
            if name == "sound":
                self.app.action_toggle_sound(again="The ☰ menu")
            elif name == "layout":
                self.action_switch_layout()
            elif name:
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
        on_tile = any(a.id == action.id and a.label == action.label for a in self.tile_verbs)  # (as drawn, or since)
        owner = self.verb_owner.get(action.id) if on_tile else ""
        if owner:  # a button's words are bare ("Search"): the story says what it was done to
            action = Action(action.id, f"{action.label} · {owner}", action.hint)
        if interactions.is_picker(action.id):
            options = interactions.choices(self.game.state, self.game.content, action.id)

            def done(chosen: Action | None) -> None:
                if chosen is not None:
                    self.run_turn(chosen.label, action=self.told(chosen))

            self.app.push_screen(PickScreen(action.label.replace("… ·", " ·").removesuffix("…"), options), done)
        else:
            self.run_turn(action.label, action=action)

    def told(self, picked: Action) -> Action:
        """A picker's option as the story tells it: the whole use ("Throw the Healing Potion at the Lantern Moth"), not
        the thing it's listed by ("Healing Potion"), so nobody's surprised by what a click did."""
        return Action(picked.id, interactions.said(self.game.state, self.game.content, picked), picked.hint)

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
        self.follow_from = None
        return marker

    def _follow(self) -> None:
        """Keep the story where the turn can be read: at its end while the turn fits the story, and once it's taller
        (a picture, loot and narration under a command), at its start, so the command and the picture's top stay in
        view, however much more is added. Run 44's room pictures were scrolled off before they were seen."""
        story = self.query_one("#story", VerticalScroll)
        marker = self.follow_from or self.turn_marker  # (a story card the turn brought: it's what's to be read)

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
        """A character's words (`speech`) or an authored moment's, in their own, each marked by a bar down the left as
        your own words are, never boxed: a box inside the story's frame fought it (and one scrolled half away left
        its bottom edge floating at the top). Speech is words only: who is speaking as its first line (so a card
        scrolled half out of view still says), then what they say; their picture is Here's. An authored moment: its
        name, its picture if it has one (the mirror of the Mirror Trial), then what happens."""
        if speech:
            words = Text(f"{title}:\n" if title else "", style="bold #ff4f9a")
            words.append_text(highlight(f"“{text}”", lexicon, "italic #e8e8f4"))
            return self.add_line(words, "say")
        story = self.query_one("#story", VerticalScroll)
        parts: list[Widget] = [StoryLine(Text(f"✧ {title.upper()}" if title else "✧", style="bold #ff4f9a"))]
        if sprite and self._sprites_on():
            region = story.scrollable_content_region
            parts.append(Picture(sprite, "", min(region.width or 40, self.STORY_WIDTH) - 4,
                                 max(4, (region.height or 12) - 4), content=self.game.content, sprites=True,
                                 classes="card-sprite"))
        parts.append(StoryLine(highlight(text, lexicon)))
        card = Vertical(*parts, classes="story-card", name=f"story card: {title}")  # (the turn log's name for it)
        story.mount(card)
        if self.follow_from is None:  # (the first of a turn's cards kept in view, its title at the top if need be)
            self.follow_from = card
        self._follow()
        return card

    def add_quest(self, text: str, new: bool = False) -> Widget:
        """A quest starting, moving on or done, with a gold bar down its left: "★ NEW QUEST · Lucky Lenny's bad
        tooth"."""
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
        """Where a new floor begins, as a chapter's heading in the middle of the story: "── ↓ FLOOR 2 OF 4 ↓ ──" over
        the floor's name. Words between ornaments, not rules across it: those made a box inside the story's frame."""
        text = Text(f"───  ↓  {title.upper()}  ↓  ───\n", style="#b8336a")
        text.append(name.upper(), style="bold")
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
            seam = self.add_line(Text("┄┄┄  ", style="dim") + Text(f"↺  CONTINUED  ·  TURN {state.turn}", style="bold")
                                 + Text("  ┄┄┄", style="dim"), "continued")
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
            self._settle()  # (a move made during the recap was kept, and then never made: nor was any after it)
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
        if self.busy and self.release() and not text:  # (Enter on a fight's spoils: on we go)
            return
        if self.busy:
            if text and self.later(lambda: self.take_input(text)):
                event.input.value = ""
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
            self._settle()

    @work(exclusive=True, group="turn")
    async def pick_perk(self, then) -> None:
        """The perk cards again, after they were put off (a click outside them does it): a move tried while the perks
        wait as the choices can't be made till one's picked, so it brings them back, and is made once one is."""
        self.busy = True
        picked = False
        try:
            marker = self._mark_turn()
            while self.game.state.pending_perks and await self._level_up():
                picked = True
            self._record_shown(marker)
        finally:
            self._settle()
        if picked and not self.game.state.pending_perks:
            self.call_later(then)

    def ready_fights(self) -> None:
        """A monster after you behind a door of this room: its fight made ahead, off the screen's thread, at the
        stage's size, and a boss's (or a guardian's) big intro's at the screen's too, so walking in starts them at
        once. Each takes a tenth of a second or so, most of it its room's picture (BossIntro.made, fight_view); floor
        5's crowds in the dark half as much again, and run 66 felt every one of them."""
        state, content, plan = self.game.state, self.game.content, self.plan
        if state.in_combat or state.over or plan is None or not self._sprites_on() or encounter.Image is None:
            return
        doors = {way: state.rooms[e.to] for way, e in state.room.exits.items() if 0 <= e.to < len(state.rooms)}
        foes = {way: room for way, room in doors.items() if room.monster and room.monster.hostile
                and room.monster.hp > 0}
        stage = [(plan.stage_width, plan.stage_rows, 2 * plan.stage_rows)] if plan.stage_rows else []
        big = []
        if big_intro(self.game.config):
            width, height = fits(self.app.size)
            if width >= 60 and height >= 20:
                big = [(width, height, height)]

        def sizes(room) -> list[tuple[int, int, int]]:
            known = content.monster(room.monster.key)
            return stage + (big if known.boss or "guardian" in known.tags else [])

        wanted = {(state.floor, room.id, room.monster.key, room.monster.name, width, keyed)
                  for room in foes.values() for width, _, keyed in sizes(room)}
        self.ahead = {key: fight for key, fight in self.ahead.items() if key in wanted}
        todo = [(way, room, size) for way, room in foes.items() for size in sizes(room)
                if (state.floor, room.id, room.monster.key, room.monster.name, size[0], size[2]) not in self.ahead]
        if not todo:
            return
        snapshot = state.model_copy(deep=True)  # (as it stands: nothing it draws can change under it)

        app = self.app

        def make() -> None:
            made = {}
            for way, room, (width, rows, keyed) in todo:
                there = snapshot.model_copy(update={"room_id": room.id})
                there.room.entered_from = OPPOSITE[way]
                monster = there.room.monster
                fight = encounter.Fight(there, content, monster, width, rows, there.known_weak.get(monster.key, []))
                made[(there.floor, room.id, monster.key, monster.name, width, keyed)] = fight

            def keep() -> None:
                if self.game.state.floor == snapshot.floor:
                    self.ahead.update(made)
            try:
                app.call_from_thread(keep)
            except RuntimeError:  # (the game's closed while they were made: nobody's walking in)
                pass

        self.run_worker(make, thread=True, group="ahead", exclusive=True)

    def _settle(self) -> None:
        """A turn done (or a recap, or a perk picked): moves can be made again, and the one made meanwhile is."""
        self.ready_fights()
        self.busy = False
        for command in self.query("#command"):  # (none if the game's closing with the turn still waiting)
            command.focus()
        queued, self.queued = self.queued, None
        if queued is not None:
            self.call_later(queued)  # (once this worker is done: a turn's is the same group)

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
            self.app.push_screen(FloorScreen(state.floor, state.floors_total, self.game.theme, boss_here(state, self.game.content)))
        narration, on_text = self._narration_sink()
        result = await self.game.opening(on_text)
        narration.update(highlight(result.narration, self.lexicon()))
        self._follow()
        self._show_story(result.events)
        self._record_shown(marker)
        self.refresh_panels()
        self.refresh_music()
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
        fighting = game.state.in_combat

        pending = await game.begin(text, action)
        primary = pending.primary
        counter = self.counter  # (at the shop's counter: its rolls and what came of them are told there: told)
        while primary is not None and counter is None:
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

        stepped = game.state.room_id != room_before and not game.state.in_combat and \
            not any(e.kind == "descend" for e in pending.events)
        if stepped:  # a step to the next room: the map, Here and the buttons say so at once, the step sounds (it takes
            self.refresh_around_stage()  # sound.LEAD to be heard: as the wipe gets going), and the stage wipes in
            self.refresh_ways()  # after. Run 66: the wipe, the step, then the map read as a hitch
            sound.play("step")
        narration, on_text = self._narration_sink()
        self.last_rolls = [event for event in pending.events if event.dice]
        if not fighting or game.state.room_id != room_before:
            self.fight_events = []  # (a fight starting now, if one is)
        if fighting or game.state.in_combat:  # (what the fight's paid so far, for its spoils once it's won)
            self.fight_events += [e for e in pending.events if e.kind in ("defeat", "style", "loot", "drop", "level")]
        # A fight's turn: your go, then a beat, then the foes' (rules.theirs), your HP shown between them.
        mine = [e for e in pending.events if not e.data.get("theirs")]
        theirs = [e for e in pending.events if e.data.get("theirs")]
        between = next((e.data["hp_before"] for e in theirs if "hp_before" in e.data), None)
        await self._rolls(mine, primary, narration)
        self.query_one("#hud", Hud).show(game.state, game.content, hp=between)
        for moment in dict.fromkeys(filter(None, map(effects.event_sound, mine))):
            if not (stepped and moment == "step"):  # (played already)
                sound.play(moment)
        await self._roll_feedback(mine, hp_before, hp_after=between)
        await self._purse_feedback(purse_before)
        await self._fight_animations(mine, before, room_before, last=not theirs)
        if theirs and game.state.room_id == room_before:
            await asyncio.sleep(paused(THEIR_BEAT))
            staged = self.fight is not None  # (their blows sound as they swing on the stage, not as their dice land)
            await self._rolls(theirs, primary, narration, quiet=staged)
            self.query_one("#hud", Hud).show(game.state, game.content)
            moments = [effects.roll_sound(e) for e in theirs if e.dice] if staged else []
            self.their_sounds = list(dict.fromkeys([*moments, *filter(None, map(effects.event_sound, theirs))]))
            if not staged:
                self._sound_theirs()
            await self._roll_feedback(theirs, between if between is not None else hp_before)
            facing = game.state.room.monster
            now = (facing.key, facing.name) if facing is not None and any(e.kind == "face" for e in mine) else before
            await self._fight_animations(theirs, now, room_before)
            self._sound_theirs()  # (any the stage didn't get to)
        await self._room_wipe(room_before)
        await self._encounter(fighting, room_before)
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
        self.refresh_music()

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
        for mind in (e for e in result.events if e.kind == "thought"):  # (yours, in your own words: light.thought)
            self.add_line(Text(f"  “{mind.text}” you think.", style="italic #5fe3ff"), "system-line")
        for warning in (e for e in result.events if e.kind == "warning"):  # (said as it is, never by the narrator)
            self.add_line(Text("  ⚠ " + warning.text, style="bold #ff7b39"), "system-line")
        for lamp in (e for e in result.events if e.kind == "light"):  # (your torch lit, filled or out: light.py)
            self.add_line(Text("  ☼ " + lamp.text, style=f"bold {LIT if lamp.data.get('lit') else UNLIT}"),
                          "system-line")
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
        self.refresh_music()

        if game.config.art == "sprites":  # (a thing that's never been yours before: its card, its model turning)
            from .model_view import FoundScreen  # (it builds on the panels)

            for key in game.first_finds(result.events):
                await self.app.push_screen_wait(FoundScreen(game, key))
        for key in game.first_statuses(result.events):  # (the first time one takes hold of you, ever: its card)
            await self.app.push_screen_wait(InfoScreen(game, f"status:{key}"))
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
        if counter is not None and counter.is_attached:  # (the window's still up: it says what came of it)
            await counter.told(pending.events, result.narration)
        elif shopping and game.state.room.shop:  # the counter again, after a purchase, a haggle or a sale there
            arg = action.id.partition(":")[2] if action else ""
            self.open_shop(int(arg) if arg.isdigit() else 0)
        await self.suggest_later()

    async def _rolls(self, events: list[Event], primary: Event | None, narration: Static, quiet: bool = False) -> None:
        """The dice of a turn (or a part of one: rules.theirs) in the story, over what's said of it: the one rolled in
        the dice window lit in its colour, the rest rolling out in their lines (a foe's fast; `quiet`, without what
        came of them sounding: DiceLine.play)."""
        for event in events:
            if not event.dice:
                continue
            if event is primary:
                effects.flash(self.add_line(roll_text(event), "mechanic", before=narration), tone(event))
            else:
                line = DiceLine("", classes="mechanic")
                await self.query_one("#story").mount(line, before=narration)
                await line.play(event, fast=event.dice.actor == "monster", quiet=quiet)

    def _sound_theirs(self) -> None:
        """The sounds of the foes' go (their_sounds), now: as they swing on the stage (_stage_theirs)."""
        moments, self.their_sounds = self.their_sounds, []
        for moment in moments:
            sound.play(moment)

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

        self.app.push_screen(ShopScreen(self.game, selected, opener=self), done)

    def counter_turn(self, action: Action) -> None:
        """Something done at the shop's counter, its window staying up (ShopScreen.act): a turn as any other, its
        roll and what came of it told in the window (ShopScreen.told), not over it."""
        self.press(action)

    async def _level_up(self) -> bool:
        """The level-up window, until you pick a perk (it can't be put off now). Whether you did: a run saved while
        they could be has its perks waiting as the choices, and a move brings this back (see pick_perk)."""
        game = self.game
        choices = list(game.state.pending_perks)
        sound.play("level_up")
        perk = await self.app.push_screen_wait(LevelUpScreen(game, choices))
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
        self.app.push_screen(FloorScreen(state.floor, state.floors_total, game.theme, boss_here(state, self.game.content)))
        self.set_timer(SETTLE_AFTER, collector.settle)  # (the old floor swept away while its card's read)

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

    def story_frame(self) -> Widget:
        """The box whose border frames the story, the one a roll's colour lights up: the story itself here (and in
        the tabs layout); in the grid layout, the box round it, with the command line (GridScreen). Lighting a
        widget with no border of its own gave it one, a frame inside the frame that blinked on and off with each
        roll, shifting the words in and out."""
        return self.query_one("#story")

    async def _roll_feedback(self, events: list[Event], hp_before: int, gold_before: int | None = None,
                             hp_after: int | None = None) -> None:
        """How the turn went, at a glance: the story's border lights up in its colour (and blinks and shakes for a
        natural 20 or 1), damage rises off the monster (big, on the stage, in a fight there: _stage_mine), and your
        hearts show what you lost or gained (by `hp_after`, your go's, before the foes have theirs)."""
        how = overall(events)
        if how:
            effects.pulse(self.story_frame(), how, blinks=3 if how in (GREAT, AWFUL) else 1)
        hits = [e for e in events if e.kind == "hit" and e.data.get("damage")]
        if self.fight is not None:
            pass  # (the stage's own numbers say it)
        elif hits:
            crit = any(e.dice and e.dice.crit for e in hits)
            dealt = sum(e.data["damage"] for e in hits)
            await self._pop_over_scene(f" -{dealt}{'!' if crit else ''} ",
                                       f"bold {effects.INK} on {effects.COLORS[GREAT] if crit else '#ffffff'}")
        elif any(e.kind == "miss" for e in events):
            await self._pop_over_scene(" MISS ", "bold #c8c8e0 on #23274a")
        player = self.game.state.player
        change = (player.hp if hp_after is None else hp_after) - hp_before
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
            await self._shake(self.story_frame())  # (the frame that lit up, and all in it)

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
        """A popup rising off the foe: off the stage in a fight there (fight_view), else off its tile (or the stage,
        with no tile to show it on)."""
        monster = self.game.state.room.monster
        picture = self._tile_picture(monster.key) if monster and self.fight is None else None
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

    async def _fight_animations(self, events: list[Event], before: tuple | None, room_before: int,
                                last: bool = True) -> None:
        """Flash white when hit, lunge when attacking, dissolve when it dies (or a ghost finds rest): on its tile, and
        on the stage too in a fight there (_stage_mine, _stage_theirs). A fight's turn comes in two parts, your go then
        the foes' (rules.theirs): `last` is whether these are the last of the turn's (gone any other way than slain,
        a thief off with what it grabbed, it only shows then)."""
        game = self.game
        if before is None or game.state.room_id != room_before:
            return
        kinds = {e.kind for e in events}
        monster = game.state.room.monster
        theirs = any(e.data.get("theirs") for e in events)
        gone = any(e.kind == "defeat" and e.data.get("monster") == before[0] for e in events) or last and (
            monster is None or (monster.key, monster.name) != before)
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
        moments = [self._play_scene(picture, steps)] if steps and picture is not None else []
        fight = self.fight
        if fight is not None and (gone or kinds & STAGE_KINDS or last and not game.state.in_combat):
            moments.append(self._stage_theirs(fight, events) if theirs else self._stage_mine(fight, events, last))
        if moments:
            self.animating = True
            try:
                await asyncio.gather(*moments)
            finally:
                self.animating = False

    async def _stage_mine(self, fight: encounter.Fight, events: list[Event], last: bool) -> None:
        """Your go on the stage: the foe you hit flashes white and the damage rises off it, big (a miss says so).
        One slain holds a beat and breaks apart where it stood (any of the others a blast finished, likewise). Then:
        the fight won, its spoils (_spoils); the one you faced down, the next of the fight comes at you (_next_foe)."""
        art = self.query_one("#stage-art", Static)
        kinds = {e.kind for e in events}
        if "hit" in kinds:
            for flash in (True, False, True, False):
                self.show_frame(fight.still(0, "idle", flash=flash), art)
                await asyncio.sleep(0.06)
        hits = [e for e in events if e.kind == "hit" and e.data.get("damage")]
        pops = []
        if hits:
            crit = any(e.dice and e.dice.crit for e in hits)
            pops = [(f"-{sum(e.data['damage'] for e in hits)}{'!' if crit else ''}",
                     encounter.GOLD if crit else encounter.WHITE, *fight.over())]
        elif "miss" in kinds:
            pops = [("MISS", encounter.GREY, *fight.over())]
        if pops:
            async for frame, _ in effects.paced(fight.popping(pops)):
                self.show_frame(frame, art)
        await self._fallen(fight, events, last)

    async def _stage_theirs(self, fight: encounter.Fight, events: list[Event]) -> None:
        """The foes' go on the stage, after yours: each that went for you in its own swing (the Goblin King's pan
        coming down) or a lunge, all at once in a crowd; what they took off you rising big over the stage as it
        flushes red. Then any a burn finished breaks apart, as on your go."""
        art = self.query_one("#stage-art", Static)
        kinds = {e.kind for e in events}
        self._sound_theirs()  # (their blows land as they swing)
        striking = frozenset(e.data["foe"] for e in events if "foe" in e.data)
        pose = monster_pose(fight.monster)
        if kinds & {"monster_hit", "monster_miss", "evade", "dodge"}:
            swung = list(fight.swing(striking or None, pose))
            lunge = [(fight.still(0, "lunge"), 0.07), (fight.still(1, "lunge"), 0.07)]
            async for text, _ in effects.paced(swung or lunge):
                self.show_frame(text, art)
        pops, hurt = [], False
        for foe in fight.lineup():  # (each that went for you: what it took off you, in red over it, or its miss)
            blows = [e for e in events if e.data.get("foe") == foe.place]
            dealt = sum(e.data.get("damage", 0) for e in blows if e.kind == "monster_hit")
            if dealt:
                pops.append((f"-{dealt}", "#ff4b4b", *fight.over(foe)))
                hurt = True
            elif any(e.kind in ("monster_miss", "evade", "dodge") for e in blows):
                pops.append(("MISS", encounter.GREY, *fight.over(foe)))
        if pops:
            async for frame, _ in effects.paced(fight.popping(pops, hurt=hurt, pose=pose)):
                self.show_frame(frame, art)
        await self._fallen(fight, events, True)

    async def _fallen(self, fight: encounter.Fight, events: list[Event], last: bool) -> None:
        """After a part of a fight's turn on the stage: those of it slain in it break apart where they stood (the one
        you faced last); then the fight's over (its spoils, or just the room again: _spoils), or the one you face has
        changed (the next comes at you: _next_foe), or it stands as it is now."""
        state = self.game.state
        art = self.query_one("#stage-art", Static)
        fallen = [e for e in events if e.kind == "defeat" and "fallen" in e.data]
        places = {e.data["fallen"] for e in fallen}
        facing = fight.monster
        for other in [m for m in fight.others if m.place in places]:  # (a burn, a blast: one of the others)
            await self._break_apart(fight, other)
        slain = facing.place in places
        if slain:
            await self._break_apart(fight, facing)
        now = state.room.monster
        if last and not state.in_combat:  # (the fight's over: won, or the last of it gone another way)
            await self._spoils(fight)
            return
        if now is None or (now.place, now.name) != (facing.place, facing.name):
            xp = next((e.data.get("xp", 0) for e in fallen if e.data["fallen"] == facing.place), 0)
            spot = fight.over(facing)
            fight = self._next_foe()
            if fight is not None and xp:
                async for frame, _ in effects.paced(fight.popping([(f"+{xp}XP", encounter.GOLD, *spot)])):
                    self.show_frame(frame, art)
            return
        fight.update(state, now, state.known_weak.get(now.key, []))
        self.show_frame(fight.still(0, monster_pose(now)), art)  # (as it stands now)

    async def _break_apart(self, fight: encounter.Fight, who: MonsterState) -> None:
        """A foe slain on the stage: the killing blow holds a beat (white, the one you faced), then it breaks into
        pixels where it stood."""
        art = self.query_one("#stage-art", Static)
        if who is fight.monster:
            self.show_frame(fight.still(0, "idle", flash=True, banner=False), art)
            await asyncio.sleep(0.22)
        sound.play("shatter")
        for frame in fight.shatter(who=who):
            self.show_frame(frame, art)
            await asyncio.sleep(0.055)

    def _next_foe(self) -> encounter.Fight | None:
        """The one you faced is down, and the next of its fight comes at you: the fight on the stage made again for
        it (its own clips, every foe's place along the stage), on the same room (its picture isn't drawn again)."""
        if self.plan is None or not self.plan.stage_rows:
            return None
        fight = self.fight_view(*self.stage_size)
        if fight is not None:
            self.show_frame(fight.still(0, monster_pose(fight.monster)))
            self.looping = fight.loops()
            if self.looping and self._loop_timer is None:
                self._loop_timer = self.set_interval(1 / CLIP_FPS, self.loop_step, name="loop")
        self.stage_shown = None
        return fight

    async def _spoils(self, fight: encounter.Fight) -> None:
        """A fight won on the stage: what it paid comes up over the dimmed room, the whole fight's (every foe beaten
        in it: fight_events): the XP bar filling, the gold and souls, the style it was won in, and each thing dropped
        in its rarity's colour, a sound for each. It stays till a key or a click (or SPOILS_HOLD seconds), then the
        room sweeps back in, and it's over (and at once, for a fight with nothing slain in it)."""
        state, content = self.game.state, self.game.content
        art = self.query_one("#stage-art", Static)
        last = fight.empty()
        beaten = [e.data["monster"] for e in self.fight_events if e.kind == "defeat" and "xp" in e.data]
        name = fight.monster.name if beaten[-1:] == [fight.monster.key] else \
            content.monster(beaten[-1]).name if beaten else ""
        spoils = encounter.Spoils.of(self.fight_events, name)
        self.fight_events = []
        self.refresh_music()  # (the floor's music back under the spoils, not after them)
        self.refresh_hud()
        if spoils is not None:
            player, back = state.player, last
            for i in range(1, 9):
                last = encounter.spoils_text(back, spoils, content, player.level, player.xp, step=0, fill=i / 8)
                self.show_frame(last, art)
                await asyncio.sleep(0.04)
            if spoils.levels:
                sound.play("level_up")
            await asyncio.sleep(0.2)
            self.refresh_around_stage()  # (the foe gone from Here and the map, what it dropped lying there: once its
            # tile's dissolve is done)
            for step in range(1, 2 + len(spoils.drops)):
                last = encounter.spoils_text(back, spoils, content, player.level, player.xp, step=step)
                self.show_frame(last, art)
                if step == 1 and (spoils.all_gold or spoils.styles):
                    sound.play("coin")
                elif step > 1:
                    key = spoils.drops[step - 2]
                    sound.play("rare_drop" if loot.rare(content.item(key)) else "item")
                await asyncio.sleep(0.3)
            await self._hold(lambda hint: encounter.spoils_text(back, spoils, content, player.level, player.xp,
                                                                hint=hint))
            last = encounter.spoils_text(back, spoils, content, player.level, player.xp)
        self.fight = self.fight_key = None
        width, height = self.stage_size
        room = picture_text(state, content, width, height) if self._sprites_on() else None
        if room is not None:
            for frame in encounter.wipe(last, room, side=-1):
                self.show_frame(frame, art)
                await asyncio.sleep(0.035)
        self.stage_shown = None  # (the room, drawn afresh with the rest of the turn)

    async def _hold(self, card) -> None:
        """The spoils held up till you've read them: `card(hint)` with how to go on, until a key (Enter, Esc), a
        click, or a move made (later), or SPOILS_HOLD seconds."""
        seconds = paused(SPOILS_HOLD)
        if not seconds:
            return
        self.show_frame(card("▸ Enter or click to go on"))
        self.holding = asyncio.Event()
        try:
            await asyncio.wait_for(self.holding.wait(), seconds)
        except TimeoutError:
            pass
        finally:
            self.holding = None

    def release(self) -> bool:
        """A key or a click while the spoils are held up: on we go. Whether they were."""
        if self.holding is None:
            return False
        self.holding.set()
        return True

    async def _encounter(self, fighting: bool, room_before: int) -> None:
        """A fight starting (one walked into, an ambush, one you started): the foe comes in onto the dimmed stage, its
        own entrance if it has one (the Goblin King drops in from above) or else sweeping in from the side, a sting
        as it lands (a boss's, deeper, and its name called out on a card: encounter.Fight.entrance), and its banner
        comes up under it, the battle music just after. The status bar, Here, the map and the buttons are brought up to
        date first: the entrance can take a few seconds, and they showed the room before till it was over."""
        state, content = self.game.state, self.game.content
        if not state.in_combat or (fighting and state.room_id == room_before):
            return
        self.refresh_around_stage()
        known = content.monster(state.room.monster.key)
        boss = known.boss or "guardian" in known.tags  # (a guardian is met as a boss is: encounter.Fight.called)
        plan = self.plan
        fight = self.fight_view(plan.stage_width, 2 * plan.stage_rows) if plan and plan.stage_rows else None
        if fight is None:
            sound.play(known.cry or ("boss_encounter" if boss else "encounter"))
            return
        side = -1 if state.room.entered_from == "east" else 1
        art = self.query_one("#stage-art", Static)
        self.query_one("#stage").border_title = f"✦ {state.room.name}  ⚔ a fight!"  # (the room it's coming into)
        self.animating = True
        called = False  # (a boss's entrance big over everything first, then quietly here: ui/boss_intro.py)
        intro = BossIntro.made(state, content, state.room.monster, state.known_weak.get(known.key, []),
                               self.app.size, side, self.ahead) if boss and big_intro(self.game.config) else None
        if intro is not None:
            done = asyncio.Event()
            self.app.push_screen(intro, lambda _: done.set())
            await done.wait()
            self.refresh_music()
            called = True
        try:
            async for frame, _, cue in effects.paced(fight.entrance(side, quiet=called)):
                self.show_frame(frame, art)
                if cue:
                    sound.play(cue)
                if cue and cue == fight.sting:
                    effects.pulse(self.query_one("#stage"), AWFUL if boss else BAD, blinks=2)
                    self.set_timer(MUSIC_AFTER_STING, self.refresh_music)  # (not after the whole entrance)
            await asyncio.sleep(0.15)
        finally:
            self.animating = False

    def _wipe_way(self, room_before: int) -> str | None:
        """The way you walked, if the next room wipes in (_room_wipe): not into a fight (its entrance plays), nor a
        journey of several rooms, nor down the stairs (the floor's card does)."""
        state, plan = self.game.state, self.plan
        if state.room_id == room_before or state.in_combat or not plan or not plan.stage_rows or \
                not self._sprites_on() or self.stage_still is None:
            return None
        return next((w for w, e in state.rooms[room_before].exits.items() if e.to == state.room_id), None) \
            if 0 <= room_before < len(state.rooms) and state.floor == self.stage_floor else None

    async def _room_wipe(self, room_before: int) -> None:
        """Walked through a door: the next room sweeps across the stage from the way you went (from the right going
        east, from the top going north), with a bright seam where they meet (the map and Here have moved on already,
        and your step's sounded: _turn)."""
        state, content, plan = self.game.state, self.game.content, self.plan
        way = self._wipe_way(room_before)
        if way is None:
            return
        width, height = plan.stage_width, 2 * plan.stage_rows
        new = picture_text(state, content, width, height)
        if new is None:
            return
        side, up = {"east": (1, 0), "west": (-1, 0), "north": (0, 1), "south": (0, -1)}[way]
        art = self.query_one("#stage-art", Static)
        self.animating = True
        try:
            for frame in encounter.wipe(self.stage_still, new, side=side or 1, up=up):
                self.show_frame(frame, art)
                await asyncio.sleep(0.03)
        finally:
            self.animating = False
        self.prepared = ((state.floor, state.room_id, width, height), new)  # (drawn: the stage keeps it)

    def refresh_around_stage(self) -> None:
        """Everything but the stage brought up to date (the status bar, Here, the map, the buttons), while the stage
        plays a moment of its own: a fight coming in, its spoils."""
        self.refresh_hud()
        self.refresh_here()
        self.refresh_choices()

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
        banner = self.add_line(secret_banner(0), "secret-banner", before=narration)
        self._follow()
        effects.pulse(self.story_frame(), GREAT, blinks=3)
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
        banner = self.add_line(secret_banner(0, words, colour), "secret-banner" if shiny else "secret-banner shop",
                               before=narration)
        self._follow()
        effects.pulse(self.story_frame(), GREAT if shiny else GOOD, blinks=3 if shiny else 2)
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

    def later(self, call) -> bool:
        """A move made mid-turn (a button, a choice, the map, the compass, words typed): it's made as soon as the
        turn's done, and while the narrator's still talking it cuts the narration short (whole sentences told so far
        stand). The first such move counts; one after it, before the turn's done, doesn't. Moves made during a turn's
        animations (a fight coming in, its spoils: seconds, now) used to be lost, and the map seemed not to take
        clicks. Whether it was kept."""
        self.release()  # (a fight's spoils held up: a move made goes on from them)
        if self.queued is not None:
            return False
        self.queued = call
        if self.narration_stop is not None:
            self.narration_stop.set()
        return True

    # --- panels ---

    def panel(self, name: str) -> Panel:
        """One of the panels F1-F7 open (see panels.PANEL_KEYS), for this game."""
        from .grid import ChartScreen  # (the floor on parchment, in full, in every layout: the grid builds on this)

        screens = {"help": HelpScreen, "inventory": InventoryScreen, "character": CharacterScreen,
                   "look": LookScreen, "map": ChartScreen, "bestiary": BestiaryScreen, "journal": JournalScreen}
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

    def action_arrow(self, direction: str) -> None:
        """An arrow key: go that way, or, while there's something typed, ← and → move the cursor in it (↑ and ↓ still
        go: there's nowhere up or down for a cursor in one line, and words left typed had them do nothing)."""
        command = self.query_one("#command", Input)
        if command.value and direction in ("west", "east"):
            if direction == "west":
                command.action_cursor_left()
            else:
                command.action_cursor_right()
            return
        self.action_go(direction)

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
        elif self.game.state.pending_perks:  # (the cards put off: back they come, and then this way)
            self.pick_perk(lambda: self.action_go(direction))
        else:  # (never nothing at all: that felt like the arrows had stopped working)
            self.notify(no_go(self.game.state, self.game.content, direction), timeout=3)

    def why_not_travel(self, room_id: int) -> None:
        """A room on the map clicked that there's no way to now: mid-turn, it's tried once the turn's done (the map
        may be a moment behind); with the perk cards put off, they come back, and then it's tried; otherwise, why
        not, in a few words (rules.no_way)."""
        if self.busy:
            self.later(lambda: self.action_travel(room_id))
            return
        state = self.game.state
        if state.pending_perks and not state.over:
            self.pick_perk(lambda: self.action_travel(room_id))
        elif 0 <= room_id < len(state.rooms) and not state.over:
            room = state.rooms[room_id]  # (one you haven't been in keeps its name to itself, as on the map)
            self.notify(no_way(state, room_id), title=room.name if room.visited else "Unexplored", timeout=3)

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

    def action_switch_layout(self) -> None:
        """F9 (or the ☰ menu): the next layout (tabs, the grid, classic), and the run carries on in it as it was, its
        story and all; it's kept in Settings for next time. Not mid-turn."""
        from .tabs import game_screen  # (the layouts build on this module)

        if self.busy or self.game.state.over:
            if self.busy:
                self.notify("Once this turn is done.", timeout=2)
            return
        if config.touch():  # (the phone's screen and this one, in turn: ui/phone.py)
            from .phone import swap_touch_layout

            swap_touch_layout(self)
            return
        now = self.game.config.layout
        layout = LAYOUTS[(LAYOUTS.index(now) + 1) % len(LAYOUTS)] if now in LAYOUTS else LAYOUTS[0]
        settings = self.app.config.model_copy(update={"layout": layout})
        config.save_config(settings)
        self.app.config = self.game.config = settings
        screen = game_screen(self.game, False, *self.app.size, switched=True)
        shown = {"TabsScreen": "tabs", "GridScreen": "grid"}.get(type(screen).__name__, "classic")
        self.switching = True
        self.app.switch_screen(screen)
        if shown == layout:
            screen.notify(f"{LAYOUT_NAMES[layout]}. F9 for the next.", title="Layout", timeout=3)
        else:
            screen.notify(f"{LAYOUT_NAMES[layout]} wants a bigger window: classic till then. F9 for the next.",
                          title="Layout", timeout=5)

    def action_leave(self) -> None:
        """Esc twice: to the title (the game's saved). Once only asks, so an Esc meant for a panel or the command
        palette never throws you out of a run."""
        if self.busy:
            self.release()  # (Esc on a fight's spoils: on we go)
            return
        now = time.monotonic()
        if now - self.leave_asked > LEAVE_WINDOW:
            self.leave_asked = now
            self.notify("Press Esc again for the title screen. (Your game is saved.)", timeout=LEAVE_WINDOW)
            return
        self.app.leave_game(self)

