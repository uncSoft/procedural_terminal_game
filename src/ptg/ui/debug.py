"""The debug screen (F12, or `ptg --debug`): what the game is made of and what it remembers, at a glance, with
sounds to play and a model check to run.

    Overview   what's loaded, your settings and files, and anything that looks wrong
    Monsters   every monster: its art, numbers, who drew it, where it lives, what your bestiary knows
    Items      every item, the same way
    Art        every sprite, animated in each pose a fight puts it in
    Sounds     every sound file, each take of a moment's (click it, or Enter, to play it; music loops till
               Stop) and where it came from
    Story      every story event: reload the files after editing them, or fire one on the next descent
    State      this run's story flags and its whole save, and your profile's marks, secrets and souls
    Models     the model check (ptg.llm.check) against any model, with earlier results to compare
    Log        the latest exchanges with the model (llm.log), guard cuts included
    Test rooms straight to a character, a shop, a boss or any monster, with the kit you pick (ptg/testrooms.py)
    3D         the bosses' clips made in Blender, played as made, and every item's model, turned however you like

It only looks, except where a button says otherwise.
"""

from __future__ import annotations

import bisect
import os
import platform
import random
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import ClassVar

import textual
from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.coordinate import Coordinate
from textual.events import Click
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, ProgressBar, Select, Static, TabbedContent, TabPane, Tree

from .. import __version__, integrity, loot, model3d, powers, sound, testrooms, world
from .boss_intro import wanted as big_intro
from ..config import DEFAULT_CLAUDE_MODEL, DEFAULT_URLS, Config, home, load_game, save_config
from ..content import Content, load_content
from ..game import Game
from ..library import credits, lives, maker_folder, off_palette
from ..llm import LLMError, check, make_llm
from ..llm.base import Exchange, read_log
from ..llm.openai_compat import OpenAICompatLLM
from ..models import GameState, Player
from ..sprites import (CLIP_FPS, DEATH_FRAMES, DEFAULT_WIDTH, SMALL, Clip, clips, count_frames, fill, frame_count,
                       frames, has_small, image_text, side_by_side, sprite_text)
from ..story import StoryError, StoryEvent, load_library, reload_library
from ..text import tell
from .model_view import ModelScreen, ModelView
from .panels import Panel
from .widgets import Picture

POSES = ("idle", "windup", "dizzy", "lunge", "shake", "death")  # (calm is idle: characters keep their colours)
HALF = 0.5  # art in less of its frame than this is flagged in the Art tab (see sprites.fill)
FIXTURES = ("chest", "fountain", "shrine", "stairs")
DIM, HEAD, GOOD, WARN, BAD = "#9a9cc0", "bold #ffb000", "#4cff8a", "#ffd166", "#ff4b4b"
ROLE = "bold #5fe3ff"


# --- small helpers ------------------------------------------------------------------------------------------------

def pairs(rows: list[tuple[str, object]]) -> Table:
    """Names and values, in two columns."""
    table = Table.grid(padding=(0, 2))
    table.add_column(style=DIM, no_wrap=True)
    table.add_column()
    for name, value in rows:
        table.add_row(name, value if isinstance(value, Text) else Text(str(value)))
    return table


def heading(text: str) -> Text:
    return Text(f"\n{text}", style=HEAD)


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' * (n != 1)}"


def listed(values, empty: str = "none") -> str:
    return ", ".join(str(v) for v in values) or empty


def short(path: object) -> str:
    """A path with your home folder written as ~."""
    return str(path).replace(str(Path.home()), "~", 1)


def size(path: Path) -> str:
    if not path.exists():
        return "not there yet"
    if path.is_dir():
        count = sum(1 for p in path.iterdir() if not p.name.startswith("."))
        return plural(count, "file")
    n = path.stat().st_size
    return f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{n / 1e3:.0f} KB" if n >= 1e3 else f"{n} bytes"


def credit_line(credit: dict | None) -> str:
    if not credit:
        return "the game"
    return credit["by"] + (f" ({credit['made']})" if credit.get("made") else "")


def tiles(shots: list[tuple[str, Text | None]], width: int, room: int, gap: int = 2) -> Text:
    """Pictures side by side, each with a caption under it, in as many rows as `room` columns need."""
    shots = [(name, art) for name, art in shots if art is not None]
    per_row = max(1, (room + gap) // (width + gap))
    out = Text(no_wrap=True, overflow="crop")
    for start in range(0, len(shots), per_row):
        row = shots[start:start + per_row]
        out.append_text(side_by_side([art for _, art in row], gap))
        out.append("\n" + (" " * gap).join(name.center(width)[:width] for name, _ in row) + "\n", style=DIM)
    return out


def poses(key: str, room: int, width: int = SMALL) -> Text:
    """The sprite in every pose a fight can put it in."""
    return tiles([(pose, sprite_text(key, 2 if pose == "death" else 1, width, pose=pose)) for pose in POSES],
                 width, room)


def current_state(app) -> tuple[GameState | None, str]:
    """The game being played under this screen, or else the autosave."""
    for screen in reversed(app.screen_stack):
        if isinstance(getattr(screen, "game", None), Game):
            return screen.game.state, "the run in progress"
    state = load_game()
    return state, ("the autosave (not being played)" if state else "no run in progress")


def reveal(path: Path) -> None:
    """Open a folder in the system's file manager."""
    path.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - a folder the game owns
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --- widgets ------------------------------------------------------------------------------------------------------

class PoseSprite(Picture):
    """A sprite animating in one pose (see ptg.sprites), quickly, on the pictures' clock, or a stand-in text when
    there's no sprite."""

    def __init__(self, **kwargs) -> None:
        super().__init__("", flicker=True, sprites=True, **kwargs)

    def show(self, key: str, pose: str = "idle", fallback: str = "") -> None:
        # Dying, it dissolves, rests a moment on nothing, then goes again; any other pose has frames enough for a glow
        # to pulse and stars to circle.
        loop = [*range(DEATH_FRAMES), *[DEATH_FRAMES - 1] * 5] if pose == "death" else list(range(24))
        self.become(key, pose=pose, loop=loop, ascii=Text(fallback, style=DIM))
        self.display = bool(self.art.sprite or fallback)


class ClickTable(DataTable):
    """A table where one click on a row picks it (a DataTable on its own picks a row on the second click)."""

    def on_click(self, event: Click) -> None:
        row, column = event.style.meta.get("row", -1), event.style.meta.get("column", -1)
        if row >= 0 and Coordinate(row, column) != self.cursor_coordinate:
            self.call_later(self._pick)  # once the table has moved its cursor there

    def _pick(self) -> None:
        if self.row_count:
            key = self.coordinate_to_cell_key(self.cursor_coordinate).row_key
            self.post_message(DataTable.RowSelected(self, self.cursor_row, key))


class DebugTab(Vertical):
    """One tab's contents, filled the first time the tab is shown (and again on r)."""

    loaded = False
    main = "VerticalScroll"  # what gets the keyboard when the tab opens

    def load(self) -> None:
        self.loaded = True

    def focus_main(self) -> None:
        found = self.query(self.main)
        if found:
            found.first().focus()


class TableTab(DebugTab):
    """A table of things, with the highlighted one in detail beside it."""

    columns: tuple[str, ...] = ()
    current = ""
    main = "DataTable"

    def compose(self) -> ComposeResult:
        yield from self.toolbar()
        with Horizontal(classes="debug-split"):
            yield self.make_table()
            with VerticalScroll(classes="debug-detail"):
                yield PoseSprite(classes="debug-sprite")
                yield Static("", classes="debug-info")

    def toolbar(self) -> ComposeResult:
        yield from ()

    def make_table(self) -> DataTable:
        return DataTable(cursor_type="row", zebra_stripes=True)

    def rows(self):
        """(key, cells) for each row."""
        return []

    def detail(self, key: str) -> tuple[str, str, object]:
        """(sprite key, text to show when there's no sprite, what to say about it)."""
        return "", "", ""

    def load(self) -> None:
        super().load()
        table = self.query_one(DataTable)
        row = table.cursor_row
        table.clear(columns=True)
        table.add_columns(*self.columns)
        for key, cells in self.rows():
            table.add_row(*cells, key=key)
        if table.row_count:
            table.move_cursor(row=min(row, table.row_count - 1))
            self.show(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)
        else:
            self.query_one(".debug-info", Static).update(Text("Nothing here yet.", style=DIM))

    def room(self) -> int:
        """How many columns the detail has to draw in."""
        width = self.query_one(".debug-detail").content_size.width
        return width - 1 if width > 10 else 48

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        event.stop()
        if event.row_key.value is not None and event.row_key.value != self.current:
            self.show(event.row_key.value)

    def show(self, key: str) -> None:
        self.current = key
        sprite, fallback, info = self.detail(key)
        self.query_one(PoseSprite).show(sprite, self.pose(), fallback)
        self.query_one(".debug-info", Static).update(info)

    def pose(self) -> str:
        return "idle"


# --- Overview -----------------------------------------------------------------------------------------------------

class OverviewTab(DebugTab):
    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static("", id="overview")

    def load(self) -> None:
        super().load()
        self.query_one("#overview", Static).update(overview(self.app))


def overview(app) -> Group:
    content = load_content()
    library = load_library(content)
    config = app.config
    engine = sound.engine()
    report = integrity.check()
    state, where = current_state(app)
    monsters, items = list(content.monsters.values()), list(content.items.values())
    no_sprite = [m.name for m in monsters if not frame_count(m.key)]
    halved = [i.name for i in items if frame_count(f"item_{i.key}") and not has_small(f"item_{i.key}")]
    item_art = [i for i in items if frame_count(f"item_{i.key}")]
    sound_files = [clip for found in engine.bank.values() for clip in found]
    sprites = sorted((integrity.data_folder() / "sprites").glob("*.png"))
    models = [key for key in model3d.keys() if key in content.items]
    redrawn = [content.item(key).name for key in models if model3d.stale(key)]
    bosses_3d = [m for m in monsters if clips(m.key)]

    problems: list[Text] = []
    if report.tampered:
        problems.append(Text(f"The data files changed since they were signed ({'; '.join(report.lines())}). If that "
                             "was you, sign them: uv run python -m ptg.integrity --sign", style=WARN))
    problems += [Text(f"Sounds: {problem}", style=WARN) for problem in engine.problems]
    if no_sprite:
        problems.append(Text(f"No sprite yet, so ASCII art stands in: {listed(no_sprite)}", style=DIM))
    if halved:
        problems.append(Text(f"Shown small by halving, with no hand-made 12×12 yet (sprites/small): {listed(halved)}",
                             style=WARN))
    if redrawn:
        problems.append(Text(f"Drawn again since their 3D models were made, so they want making again (uv run ptg "
                             f"models; the game makes them as they're wanted till then): {listed(redrawn)}",
                             style=WARN))
    if config.backend == "offline":
        problems.append(Text("The narrator is offline: the game tells the facts plainly.", style=DIM))

    narrator = [("Backend", config.backend)]
    if config.backend == "openai":
        narrator.append(("Server", config.url))
    narrator += [("Model", config.model or "whatever the server has loaded"), ("Temperature", config.temperature),
                 ("Tone", config.tone), ("API key", "set" if config.api_key else "not set")]
    settings = [("Your name", config.player_name), ("Dice", "roll themselves" if config.auto_roll else "you roll"),
                ("Boss entrances", "big, over the whole screen" if big_intro(config) else "on the stage only"),
                ("Art", config.art), ("Sound", f"{'on' if config.sound else 'off'} (F8), volume {config.volume}%")]
    upcoming = [("Seed", app.seed if app.seed is not None else "a new one"),
                ("Story event", app.event or "none (fire one from the Story tab)")]
    kinds = {}
    for item in items:
        kinds[item.kind] = kinds.get(item.kind, 0) + 1
    blessings = sum(u.kind == "blessing" for u in content.unlocks.values())
    counts = [
        ("Dungeons", f"{len(content.themes)}: {listed(t.name for t in content.themes.values())}"),
        ("Room kinds", len(content.archetypes)),
        ("Monsters", f"{len(monsters)} ({len(monsters) - len(no_sprite)} with sprites, "
                     f"{sum(m.boss for m in monsters)} bosses)"),
        ("Items", f"{len(items)} ({listed(f'{n} {kind}' for kind, n in kinds.items())}; {len(item_art)} drawn)"),
        ("Perks", len(content.perks)),
        ("Campfire", f"{blessings} blessings, {len(content.unlocks) - blessings} gifts"),
        ("Story events", f"{len(library.events)} ({plural(sum(e.is_scene for e in library), 'scene')}, "
                         f"{plural(len(library.secrets), 'secret')})"),
        ("Sprites", f"{len(sprites)} ({sum(has_small(p.stem) for p in sprites)} with a hand-made small version)"),
        ("Sounds", f"{len(sound_files)} files for {len(engine.bank)} moments "
                   f"({sum(not c.builtin for c in sound_files)} yours)"),
        ("3D", f"{len(models)} items' models, {len(bosses_3d)} bosses' clips ({listed(m.name for m in bosses_3d)})"),
    ]
    player = getattr(engine.player, "name", None) or "not open yet (it opens for the first sound)"
    folder = home()
    files = [("Folder", short(folder) + ("  (PTG_HOME)" if os.environ.get("PTG_HOME") else "")),
             ("Settings", f"config.json, {size(folder / 'config.json')}"),
             ("Profile", f"profile.db, {size(folder / 'profile.db')}"),
             ("Autosave", f"saves/autosave.json, {size(folder / 'saves' / 'autosave.json')}"),
             ("Model log", f"llm.log, {size(folder / 'llm.log')}"),
             ("Your sounds", f"sounds/, {size(sound.user_folder())}"),
             ("Model checks", f"checks.jsonl, {len(check.history(1000))} so far")]
    maker = maker_folder()
    data = [("Data folder", short(integrity.data_folder())),
            ("Signatures", Text("match", style=GOOD) if not report.tampered else Text(listed(report.lines()),
                                                                                       style=WARN))]
    if maker is not None:
        data.append(("Maker page", f"{short(maker)}, library.json {size(maker / 'library.json')}"))
    run = [("From", where)]
    if state is not None:
        run += [("Where", f"floor {state.floor} of {state.floors_total}, {state.room.name}, turn {state.turn}"),
                ("Player", f"{state.player.name}, level {state.player.level}, "
                           f"HP {state.player.hp}/{state.player.max_hp}")]
    about = (f"ptg {__version__} · Python {platform.python_version()} · Textual {textual.__version__} · "
             f"{platform.system()} · terminal {app.size.width}×{app.size.height}, {app.console.color_system} colour")
    return Group(
        Text(about, style=DIM),
        heading("Worth a look") if problems else Text("\nNothing looks wrong.", style=GOOD),
        *problems,
        heading("Narrator"), pairs(narrator),
        heading("Settings"), pairs(settings),
        heading("Next descent"), pairs(upcoming),
        heading("The game's content"), pairs(counts),
        heading("Sound"), pairs([("Player", player), ("Volume", f"{engine.volume:.0%}"),
                                 ("Playing", "yes" if engine.enabled else "no"),
                                 ("Music", f"{engine.wanted}, take {engine.variant + 1} of "
                                  f"{len(engine.bank.get(engine.wanted, ())) or 1}" if engine.wanted else "none")]),
        heading("Your files"), pairs(files),
        heading("Game data"), pairs(data),
        heading("Run"), pairs(run),
    )


# --- Monsters and items -------------------------------------------------------------------------------------------

class MonstersTab(TableTab):
    columns = ("Monster", "Tier", "HP", "Def", "Atk", "Dmg", "XP", "Floors", "Weak to", "Art", "Drawn by")

    def rows(self):
        self.content = load_content()
        self.credits = credits()["monster"]
        self.known = self.app.profile.bestiary()
        for m in self.content.monsters.values():
            tier = "boss" if m.boss else "ghost" if m.ghost else str(m.tier)
            art = "sprite" if frame_count(m.key) else Text("ascii", style=DIM)
            yield m.key, [Text(m.name, style="bold"), tier, m.hp, m.defense, m.attack, m.damage, m.xp,
                          floors_short(world.met_on(self.content, m.key)) or Text("placed", style=DIM),
                          listed(m.weak, "-"), art, self.credits.get(m.key, {}).get("by", "")]

    def detail(self, key: str):
        m = self.content.monster(key)
        themes = list(self.content.themes.values())
        rank = "boss" if m.boss else "ghost" if m.ghost else f"tier {m.tier}"
        rank += ", guardian" if "guardian" in m.tags and not m.boss else ""
        called = [("Called out", Text(m.epithet, style="italic"))] if m.epithet else []  # (big, as it comes in)
        party = [("Comes with", listed([self.content.monster(k).name for k in m.party], "-"))] if m.party else []
        parts = [Text.assemble((m.name, "bold #ff4b4b"), (f"  {m.key}  ", DIM), (rank, WARN)),
                 pairs([("HP", m.hp), ("Defense", m.defense), ("Attack", m.attack), ("Damage", m.damage),
                        ("XP", m.xp), ("Tags", listed(m.tags, "-")), ("Weak to", listed(m.weak, "-")),
                        ("Thinks", "yes: it can be talked to" if m.intelligent else "no"),
                        ("Heavy blow", tell(m.name, m.tell)), *called, *party,
                        ("Lives in", listed(lives(m.key, m.tags, m.ghost, themes, m.tier, m.dungeons), "-")),
                        ("Turns up on", floors_long(world.met_on(self.content, key))
                         or "nowhere by the rules: only where it's put (a character, a lair, a party)"),
                        ("Drawn by", credit_line(self.credits.get(m.key)))])]
        if m.desc:
            parts.append(Text(f"\n{m.desc}", style="italic"))
        beast = self.known.get(key)
        if beast:
            parts += [heading("Your bestiary"),
                      pairs([("Seen", beast["seen"]), ("Killed", beast["killed"]), ("Pacified", beast["pacified"]),
                             ("Killed you", beast["killed_you"]), ("Weak spots found", listed(beast["weak"]))]
                            + ([("Lore", beast["lore"])] if beast.get("lore") else []))]
        if frame_count(key):
            parts += [heading("In a fight"), poses(key, self.room())]
        return key, m.art, Group(*parts)


class ItemsTab(TableTab):
    columns = ("Item", "Kind", "Tier", "Damage", "Defense", "Heal", "Where", "Art", "Drawn by")

    def rows(self):
        self.content = load_content()
        self.credits = credits()["item"]
        for i in self.content.items.values():
            art = "sprite" if frame_count(f"item_{i.key}") else Text("-", style=DIM)
            yield i.key, [Text(i.name, style="bold"), i.kind, i.tier or "-", i.damage or "-", i.defense or "-",
                          i.heal or "-", where_short(turns_up(self.content, i.key)) or Text("nowhere", style=WARN),
                          art, self.credits.get(i.key, {}).get("by", "")]

    def detail(self, key: str):
        i = self.content.item(key)
        rows = [("Kind", i.kind), ("Tier", i.tier or "-")]
        rows += [(name, value) for name, value in (("Damage", i.damage), ("Defense", i.defense), ("Heals", i.heal))
                 if value]
        if i.escape:
            rows.append(("Escape", "gets you out of a fight"))
        rows.append(("Tags", listed(i.tags, "-")))
        if i.powers:
            rows.append(("Powers", "; ".join(powers.describe(i))))
        rows.append(("Turns up", listed(turns_up(self.content, key), "nowhere: nothing places it")))
        if loot.rare(i):
            rows.append(("Rare", "once a run at most, and only in those places"))
        gifts = [u.name for u in self.content.unlocks.values() if u.item == key]
        if gifts:
            rows.append(("Campfire gift", listed(gifts)))
        rows.append(("Drawn by", credit_line(self.credits.get(key))))
        parts = [Text.assemble((i.name, "bold #4cff8a"), (f"  {i.key}", DIM)), pairs(rows)]
        if i.desc:
            parts.append(Text(f"\n{i.desc}", style="italic"))
        if not frame_count(f"item_{key}"):
            parts.append(Text("\nNo art yet: draw some in the Monster & Item Maker.", style=DIM))
        return f"item_{key}", "", Group(*parts)


# How a monster turns up on a floor (world.met_on), in a mark and in words.
MET_MARKS = {"boss": "★", "stairs": "⚑", "group": "×", "roams": ""}
MET_WORDS = {"roams": "in its rooms", "group": "in groups", "stairs": "by the stairs", "boss": "its boss"}


def floors_short(met: dict[int, set[str]]) -> str:
    """The floors a monster turns up on, a mark for how: "1× 2⚑ 3★" (in groups; by the stairs; the boss)."""
    return " ".join(f"{floor}{''.join(MET_MARKS[how] for how in ('boss', 'stairs', 'group') if how in ways)}"
                    for floor, ways in sorted(met.items()))


def floors_long(met: dict[int, set[str]]) -> str:
    return "; ".join(f"floor {floor}: {', '.join(MET_WORDS[how] for how in MET_WORDS if how in ways)}"
                     for floor, ways in sorted(met.items()))


def where_short(places: list[str]) -> str:
    """Where an item turns up, in a few words: its floors, then anywhere else ("1 2 3 · chests · shops")."""
    floors = sorted({int(word) for place in places if place.startswith("floor ")
                     for word in place.split()[1:2] if word.isdigit()})
    rest = [place.split(" ", 2)[-1] if place.startswith("floor ") else place for place in places]
    others = list(dict.fromkeys(r for r in rest if not r.isdigit() and not r.startswith("floor")))
    return " · ".join(filter(None, [" ".join(map(str, floors)), *others[:3]]))


def turns_up(content: Content, key: str) -> list[str]:
    """Where an item comes from: loot (see loot.py), your starting kit, or a boss door it opens."""
    fresh = Player(name="")
    places = ["you start with it"] if key == fresh.weapon or key in fresh.inventory else []
    places += loot.where(content, key)
    places += [f"the key to {t.name}'s boss" for t in content.themes.values() if t.key_item == key]
    return places


# --- Art ----------------------------------------------------------------------------------------------------------

class ArtTab(TableTab):
    columns = ("Sprite", "Frames", "Size", "Small", "Fills", "Used for")
    chosen_pose = "idle"

    def toolbar(self) -> ComposeResult:
        yield Static("", id="art-poses", classes="debug-toolbar")

    def rows(self):
        content = load_content()
        drawn = credits()
        self.credits = {**drawn["monster"], **{f"item_{k}": v for k, v in drawn["item"].items()}}
        uses: dict[str, list[str]] = {}
        for m in content.monsters.values():
            uses.setdefault(m.key, []).append(f"monster: {m.name}")
        for i in content.items.values():
            uses.setdefault(f"item_{i.key}", []).append(f"item: {i.name}")
        for event in load_library(content):
            if event.sprite:
                uses.setdefault(event.sprite, []).append(f"story: {event.id}")
        for fixture in FIXTURES:
            uses.setdefault(fixture, []).append("in a room")
        for key, screen in (("tombstone", "when you die"), ("crown", "when you win")):
            uses.setdefault(key, []).append(f"the end of a run: {screen}")
        self.uses = uses
        self.paths = {p.stem: p for p in sorted((integrity.data_folder() / "sprites").glob("*.png"))}
        for key, path in self.paths.items():
            count, width, height = sheet(path)
            small = (Text("hand-made", style=GOOD) if has_small(key) else
                     Text("halved", style=WARN) if key.startswith("item_") else "")
            share = fill(key)
            yield key, [Text(key, style="bold"), count, f"{width}×{height}", small,
                        Text(f"{share:.0%}", style=WARN if share < HALF else ""), listed(uses.get(key, []), "")]
        self.set_pose(self.chosen_pose)

    def detail(self, key: str):
        path = self.paths[key]
        count, width, height = sheet(path)
        room = self.room()
        pictures = tiles([(f"frame {n + 1}", sprite_text(key, n, DEFAULT_WIDTH)) for n in range(count)],
                         DEFAULT_WIDTH, room)
        small = tiles([(f"frame {n + 1}", sprite_text(key, n, SMALL)) for n in range(count)], SMALL, room)
        how = ("hand-made" if has_small(key) else
               f"halved automatically: draw one by hand as sprites/small/{key}.png (12×12, same frames)")
        info = pairs([("File", short(path)), ("Frames", f"{count}, {width}×{height} pixels each"),
                      ("Fills", fills_line(key)), ("Colours", colours_line(key)),
                      ("Used for", listed(self.uses.get(key, []), "nothing yet")),
                      ("Drawn by", credit_line(self.credits.get(key)))])
        return key, "", Group(info, heading("Frames"), pictures, heading(f"Small ({SMALL} px): {how}"), small,
                              heading("Poses"), poses(key, room))

    def pose(self) -> str:
        return self.chosen_pose

    def set_pose(self, pose: str) -> None:
        self.chosen_pose = pose
        links = "  ".join(f"[reverse]{p}[/]" if p == pose else f"[@click=screen.pose('{p}')]{p}[/]" for p in POSES)
        self.query_one("#art-poses", Static).update(f"Animate:  {links}")
        if self.current:
            self.query_one(PoseSprite).show(self.current, pose)


def fills_line(key: str) -> Text:
    """How much of its frame the art takes up, with a nudge when it's under half."""
    share = fill(key)
    if share < HALF:
        return Text(f"{share:.0%} of its frame, under half: draw it bigger if it looks small on cards and in rooms",
                    style=WARN)
    return Text(f"{share:.0%} of its frame")


def colours_line(key: str) -> Text:
    """How many colours the art uses, and any from outside the maker's palette (see library.ENDESGA)."""
    found = list(frames(key) or ())
    used = {pixel[:3] for frame in found for pixel in frame.get_flattened_data() if pixel[3] >= 128}
    custom = off_palette(found)
    if not custom:
        return Text(f"{len(used)}, all from the maker's palette")
    return Text(f"{len(used)}, {len(custom)} from outside the maker's palette: {listed(custom)}", style=WARN)


def sheet(path: Path) -> tuple[int, int, int]:
    """(frames, frame width, height) of a sprite strip."""
    try:
        from PIL import Image

        with Image.open(path) as image:
            count = count_frames(image, path.parent.name == "small", path.name)
            return count, image.width // count, image.height
    except (ImportError, OSError, ValueError):
        return frame_count(path.stem), 0, 0


# --- Sounds -------------------------------------------------------------------------------------------------------

class SoundsTab(TableTab):
    """Every sound file, a row each: a moment's takes one under another (the fight's music and its second, hit and
    hit_2...), each played as it is by a click or Enter; music loops on the music's own channel in place of the
    game's (which comes back when the screen closes), and Stop, or s, quiets it all."""

    columns = ("Moment", "File", "Length", "When it plays")
    BINDINGS: ClassVar = [Binding("s", "stop", "Stop", show=False)]

    def toolbar(self) -> ComposeResult:
        with Horizontal(classes="debug-toolbar"):
            yield Button("▶ Play", compact=True, id="sound-play")
            yield Button("■ Stop", compact=True, id="sound-stop")
            yield Button("Reload sounds", compact=True, id="sound-reload")
            yield Button("Open your sounds folder", compact=True, id="sound-folder")
            yield Static("", id="sound-status", classes="debug-status")

    def make_table(self) -> DataTable:
        return ClickTable(cursor_type="row", zebra_stripes=True)

    def status(self, playing: str = "") -> None:
        """The line over the table: what's playing (a preview), else where things stand."""
        config, engine = self.app.config, sound.engine()
        player = getattr(engine.player, "name", None) or "opens on the first sound"
        if playing:
            line = Text.assemble(("▶ ", GOOD), (playing, "bold"), ("  ■ Stop, or s, to quiet it", DIM))
        else:
            line = Text(f"player: {player} · sound {'on' if config.sound else 'off'} (F8) · volume {config.volume}% · "
                        f"yours go in {short(sound.user_folder())} (green ones are yours)", style=DIM)
        self.query_one("#sound-status", Static).update(line)

    def rows(self):
        engine = sound.engine()
        self.status()
        for moment, what in sound.MOMENTS.items():
            clips = engine.bank.get(moment, [])
            if not clips:
                yield f"{moment}#0", [Text(moment, style="bold"), "-", "-", what]
            for n, clip in enumerate(clips):
                length = sound.clip_length(clip)
                name = Text(sound.clip_name(clip), style=GOOD if not clip.builtin else "")
                first = Text(moment, style=f"bold {GOOD}" if not clip.builtin else "bold") if n == 0 \
                    else Text("  ↳", style=DIM)
                yield f"{moment}#{n}", [first, name, f"{length:.2f}s" if length else "-",
                                        what if n == 0 else Text(f"take {n + 1} of {len(clips)}", style=DIM)]

    @staticmethod
    def which(key: str) -> tuple[str, int]:
        """A row's moment and which of its takes."""
        moment, _, n = key.rpartition("#")
        return moment, int(n or 0)

    def detail(self, key: str):
        moment, n = self.which(key)
        engine = sound.engine()
        clips = engine.bank.get(moment, [])
        music = moment.endswith("_music")
        parts = [Text.assemble((moment, "bold"), (f"  {sound.MOMENTS.get(moment, '')}", DIM)),
                 Text("Click it or press Enter to play it" + (" (it loops in place of the game's music, till ■ Stop "
                                                              "or s; the game's comes back when you close this)"
                                                              if music else "") + ".", style=DIM)]
        if len(clips) > 1:
            parts.append(Text(f"Take {n + 1} of {len(clips)}: " + ("each fight has the next, each floor its own"
                                                                   if music else "the game picks one at random"),
                              style=DIM))
        if n < len(clips):
            clip = clips[n]
            try:
                bars = Text(sound.envelope(clip, max(8, self.room() - 2)), style=GOOD)
            except Exception as error:  # a broken file: say so, here of all places
                bars = Text(f"can't read it: {error}", style=BAD)
            length = sound.clip_length(clip)
            parts += [Text(f"\n{sound.clip_name(clip)}", style="bold"), bars,
                      pairs([("Length", f"{length:.2f}s" if length else "?"), ("Volume", f"{clip.volume:.0%}"),
                             ("From", clip.credit), ("Licence", clip.license or "-"), ("File", short(clip.source))])]
        problems = [p for p in engine.problems if moment in p]
        parts += [Text(f"\n{p}", style=WARN) for p in problems]
        if not clips:
            parts.append(Text("\nNo sound for this moment.", style=DIM))
        return "", "", Group(*parts)

    def play(self, key: str) -> None:
        moment, n = self.which(key)
        clips = sound.engine().bank.get(moment, [])
        if not 0 <= n < len(clips):
            return
        clip = clips[n]
        self.status(f"{sound.clip_name(clip)}" + (", looping" if moment.endswith("_music") else ""))
        self.run_worker(lambda: self._play(clip), thread=True, group="sound")

    def _play(self, clip: sound.Clip) -> None:
        problem = sound.preview(clip)
        if problem:
            self.app.call_from_thread(self.app.notify, problem, title="Can't play it", severity="warning")
            self.app.call_from_thread(self.status)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self.play(event.row_key.value)

    @on(Button.Pressed, "#sound-play")
    def play_current(self) -> None:
        if self.current:
            self.play(self.current)

    def action_stop(self) -> None:
        sound.stop_preview()
        self.status()

    @on(Button.Pressed, "#sound-stop")
    def stop_pressed(self) -> None:
        self.action_stop()

    @on(Button.Pressed, "#sound-reload")
    def reload(self) -> None:
        config = self.app.config
        engine = sound.configure(config.sound, config.volume / 100)
        self.load()
        found = sum(not c.builtin for clips in engine.bank.values() for c in clips)
        self.app.notify(f"{found} of yours, {len(engine.problems)} problem(s).", title="Sounds reloaded")

    @on(Button.Pressed, "#sound-folder")
    def folder(self) -> None:
        try:
            reveal(sound.user_folder())
        except OSError as error:
            self.app.notify(str(error), title="Can't open it", severity="warning")


# --- Story --------------------------------------------------------------------------------------------------------

class StoryTab(TableTab):
    columns = ("Event", "Title", "When", "Once per", "Voice", "Kind", "Seen")

    def toolbar(self) -> ComposeResult:
        with Horizontal(classes="debug-toolbar"):
            yield Button("Fire on the next descent", compact=True, id="story-fire")
            yield Button("Reload the story files", compact=True, id="story-reload")
            yield Static("", id="story-next", classes="debug-status")

    def rows(self):
        self.library = load_library(load_content())
        counts = self.app.profile.story_counts()
        state, _ = current_state(self.app)
        this_run = set(state.story_seen) if state else set()
        self.note_next()
        for event in self.library:
            seen = str(counts.get(event.id, 0)) + (" · this run" if event.id in this_run else "")
            title = Text(("✧ " if event.secret else "") + event.title, style="bold #ff4f9a" if event.secret else "")
            yield event.id, [Text(event.id, style="bold"), title, when(event), event.once, event.voice,
                             "scene" if event.is_scene else "moment", seen]

    def detail(self, key: str):
        event = self.library.get(key)
        return (event.sprite, "", story_info(event)) if event else ("", "", "")

    def note_next(self) -> None:
        upcoming = self.app.event
        self.query_one("#story-next", Static).update(
            Text.assemble(("next descent fires: ", DIM), (upcoming, "bold #ff4f9a")) if upcoming
            else Text("next descent fires: nothing", style=DIM))

    @on(Button.Pressed, "#story-fire")
    def fire(self) -> None:
        if not self.current:
            return
        self.app.event = None if self.app.event == self.current else self.current
        self.note_next()
        if self.app.event:
            self.app.notify("It fires right after the opening of your next descent.", title=self.current)

    @on(Button.Pressed, "#story-reload")
    def reload(self) -> None:
        try:
            library = reload_library(load_content())
        except StoryError as error:
            self.query_one(".debug-info", Static).update(Text(str(error), style=BAD))
            self.app.notify("The game keeps the story it had.", title="Problems in the story files",
                            severity="error")
            return
        self.load()
        self.app.notify(f"{len(library.events)} story events. New descents use them; a run already going keeps "
                        "the ones it started with.", title="Story files reloaded")


def when(event: StoryEvent) -> str:
    return " ".join([event.trigger, " | ".join(event.trigger_args)]).strip()


def story_info(event: StoryEvent) -> Group:
    conditions = [("not " if c.negate else "") + c.name + (f" {c.op} {c.value}" if c.op else "")
                  for c in event.conditions]
    parts = [Text.assemble((event.title, "bold #ff4f9a"), (f"  {event.id}", DIM)),
             pairs([("File", event.source), ("When", when(event)), ("Only if", listed(conditions, "always")),
                    ("Once per", event.once), ("Voice", event.voice),
                    ("Secret", f"yes, hint: {event.hint}" if event.secret else "no"), ("Sprite", event.sprite or "-")])]

    def effects(found, indent: str) -> list[Text]:
        return [Text(f"{indent}→ {effect.verb} {' '.join(effect.args)}".rstrip(), style=WARN) for effect in found]

    for node in event.nodes.values():
        parts.append(heading(f"part '{node.id}'"))
        if node.text:
            parts.append(Text(node.text))
        parts += effects(node.effects, "")
        choices = [(f"{n}.", c) for n, c in enumerate(node.options, 1)]
        if node.fallback:
            choices.append(("else", node.fallback))
        for label, choice in choices:
            keywords = f"  [{', '.join(choice.keywords)}]" if choice.keywords else ""
            parts.append(Text.assemble(f"  {label} ", (choice.label, "bold"), (keywords, DIM)))
            if choice.text:
                parts.append(Text(f"     {choice.text}", style="italic"))
            parts += effects(choice.effects, "     ")
    return Group(*parts)


# --- State --------------------------------------------------------------------------------------------------------

class StateTab(DebugTab):
    main = "Tree"

    def compose(self) -> ComposeResult:
        with Horizontal(classes="debug-split"):
            with VerticalScroll(id="state-text"):
                yield Static("", id="state-summary")
            yield Tree("save", id="state-tree")

    def load(self) -> None:
        super().load()
        content = load_content()
        state, where = current_state(self.app)
        self.query_one("#state-summary", Static).update(
            Group(run_summary(state, where, content), profile_summary(self.app.profile, content)))
        tree = self.query_one("#state-tree", Tree)
        tree.clear()
        tree.root.set_label(Text.assemble(("save", "bold"), (f"  {where}", DIM)))
        if state is not None:
            tree.root.data = state.model_dump(mode="json")
            branch(tree.root, tree.root.data)
            tree.root.expand()

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        node = event.node
        if isinstance(node.data, (dict, list)) and not node.children:
            branch(node, node.data)


def branch(node, value: dict | list) -> None:
    """Add a node's children, one level (deeper ones are filled in as they're opened)."""
    for key, item in (value.items() if isinstance(value, dict) else enumerate(value)):
        if isinstance(item, (dict, list)) and item:
            name = item.get("name") if isinstance(item, dict) else None
            count = f"{{{len(item)}}}" if isinstance(item, dict) else f"[{len(item)}]"
            node.add(Text.assemble((str(key), "bold"), f" {count}", (f"  {name}" if name else "", DIM)), data=item)
        else:
            style = GOOD if isinstance(item, str) else WARN if isinstance(item, (int, float)) else DIM
            node.add_leaf(Text.assemble((str(key), "bold"), ": ", (repr(item) if item != [] else "[]", style)))


def run_summary(state: GameState | None, where: str, content: Content) -> Group:
    if state is None:
        return Group(Text("This run", style=HEAD), Text("No run in progress, and no autosave.", style=DIM))
    p, room = state.player, state.room
    dungeons = listed(content.themes[t].name for t in (state.themes or [state.theme]) if t in content.themes)
    here = f"#{room.id} {room.name} ({room.archetype})"
    if room.fixture:
        here += f", {room.fixture}{' (used)' if room.fixture_used else ''}"
    if room.monster:
        here += f", {room.monster.name} {room.monster.hp}/{room.monster.max_hp} HP"
    run = [("From", where), ("Seed", f"{state.seed}" + (f" (daily {state.daily})" if state.daily else "")),
           ("Dungeons", dungeons), ("Floor", f"{state.floor} of {state.floors_total}"), ("Turn", state.turn),
           ("Status", state.status), ("Room", here), ("Souls", state.souls),
           ("Edited data", "yes (modded)" if state.modded else "no")]
    story = [("Flags", listed(state.flags, "none set")), ("Fired this run", listed(state.story_seen)),
             ("Scene", f"{state.scene.event}, part '{state.scene.node}'" if state.scene else "none"),
             ("Marks to save", listed(state.marks_pending))]
    nxt = p.next_level_xp()
    player = [("Name", p.name), ("Level", f"{p.level}, {p.xp} XP" + (f" (next at {nxt})" if nxt else "")),
              ("HP", f"{p.hp}/{p.max_hp}"), ("Might · agility · wits", f"{p.might} · {p.agility} · {p.wits}"),
              ("Gold", p.gold), ("Fate", f"{p.fate}/{p.max_fate()}"),
              ("Weapon", content.item(p.weapon).name if p.weapon in content.items else p.weapon),
              ("Armor", content.item(p.armor).name if p.armor in content.items else p.armor or "none"),
              ("Helm", content.item(p.helm).name if p.helm in content.items else p.helm or "none"),
              ("Pack", listed(content.item(k).name if k in content.items else k for k in p.inventory)),
              ("Perks", listed(p.perks)), ("Traits", listed(p.traits)), ("Blessings", listed(p.blessings)),
              ("Gift", content.unlocks[p.gift].name if p.gift in content.unlocks else p.gift or "none"),
              ("Style", listed(f"{k} {v}" for k, v in sorted(p.style.items())))]
    return Group(Text("This run", style=HEAD), pairs(run), heading("Story variables (this run)"), pairs(story),
                 heading("Player"), pairs(player))


def profile_summary(profile, content: Content) -> Group:
    totals = profile.totals()
    unlocks = [content.unlocks[k].name if k in content.unlocks else k for k in sorted(profile.unlocked())]
    found = profile.secrets()
    secrets = [f"{key} ({datetime.fromtimestamp(when):%Y-%m-%d})" for key, when in sorted(found.items())]
    counts = profile.story_counts()
    beasts = profile.bestiary()
    gift = content.unlocks[profile.gift].name if profile.gift in content.unlocks else profile.gift
    rows = [("Souls", profile.souls), ("Unlocked", listed(unlocks)), ("Next gift", gift or "none"),
            ("Runs", f"{totals['runs']} ({totals['wins']} won), {totals['kills']} kills, "
                     f"deepest floor {totals['deepest']}"),
            ("Bestiary", f"{len(beasts)} kinds met, {sum(b['killed'] for b in beasts.values())} killed")]
    story = [("Marks", listed(sorted(profile.marks()), "none set")),
             ("Events seen", listed(f"{k} ×{n}" for k, n in sorted(counts.items()))),
             ("Secrets found", listed(secrets))]
    remembered = [(key, value if len(value) < 60 else value[:57] + "...") for key, value in profile.meta().items()]
    return Group(heading("Your profile"), pairs(rows), heading("Story variables (kept between runs)"), pairs(story),
                 heading("Remembered values"), pairs(remembered or [("-", "nothing yet")]))


# --- Models -------------------------------------------------------------------------------------------------------

INTRO = """\
The model check asks a model to read ten typed commands and narrate five moments, the same ones every time, and
scores it: does it pick what the player means, and how much of its narration would the guard cut? Then how fast.
It takes a minute or two. Nothing in your game changes; a line about each check is kept, below, to compare models.
"""


class ModelsTab(DebugTab):
    models: dict[str, bool | None] = {}
    worker = None
    main = "#check-run"

    def compose(self) -> ComposeResult:
        config = self.app.config
        backend = config.backend if config.backend != "offline" else "openai"
        with Horizontal(classes="debug-toolbar"):
            yield Select([("OpenAI-compatible", "openai"), ("Anthropic", "anthropic")],
                         value=backend, allow_blank=False, compact=True, id="check-backend")
            yield Input(config.url, placeholder=DEFAULT_URLS["lmstudio"], compact=True, id="check-url")
            yield Select([], prompt="model", compact=True, id="check-model")
            yield Button("↻ Models", compact=True, id="check-list")
        with Horizontal(classes="debug-toolbar"):
            yield Button("Run the check", variant="primary", compact=True, id="check-run")
            yield Button("Stop", compact=True, id="check-stop", disabled=True)
            yield Button("Use for the narrator", compact=True, id="check-use")
            yield Static("", id="check-note", classes="debug-status")
        with Horizontal(classes="debug-toolbar"):
            yield ProgressBar(show_eta=False, id="check-progress")
            yield Static("", id="check-status", classes="debug-status")
        with VerticalScroll(id="check-results"):
            yield Static(Text(INTRO, style=DIM), id="check-lines")
        yield ClickTable(cursor_type="row", zebra_stripes=True, id="check-history")

    def load(self) -> None:
        super().load()
        self.query_one("#check-url", Input).disabled = self.backend() == "anthropic"
        self.fill_history()
        self.list_models()

    def backend(self) -> str:
        return self.query_one("#check-backend", Select).value

    def chosen(self) -> Config:
        """The narrator settings to check: yours, with this tab's backend, server and model."""
        config = self.app.config
        model = self.query_one("#check-model", Select).value
        update = {"backend": self.backend(), "url": self.query_one("#check-url", Input).value.strip()
                  or DEFAULT_URLS["lmstudio"], "model": model if isinstance(model, str) else ""}
        if update["backend"] != config.backend:
            update["api_key"] = ""  # never hand one service's key to another
        return config.model_copy(update=update)

    def note(self, text: str, style: str = DIM) -> None:
        self.query_one("#check-note", Static).update(Text(text, style=style))

    @on(Select.Changed, "#check-backend")
    def backend_changed(self) -> None:
        if self.loaded:
            self.query_one("#check-url", Input).disabled = self.backend() == "anthropic"
            self.list_models()

    @on(Input.Submitted, "#check-url")
    @on(Button.Pressed, "#check-list")
    def relist(self) -> None:
        self.list_models()

    @work(exclusive=True, group="models")
    async def list_models(self) -> None:
        select = self.query_one("#check-model", Select)
        config = self.app.config
        if self.backend() == "anthropic":
            model = config.model if config.backend == "anthropic" and config.model else DEFAULT_CLAUDE_MODEL
            self.models = {model: None}
        else:
            chosen = self.chosen()
            llm = OpenAICompatLLM(chosen.url, api_key=chosen.api_key)
            self.note("Asking the server what it has...")
            try:
                self.models = dict(await llm.catalog())
            except LLMError as error:
                self.models = {}
                self.note(str(error)[:1].upper() + str(error)[1:], BAD)
            finally:
                await llm.aclose()
            if config.backend == "openai" and config.model:
                self.models.setdefault(config.model, None)
        mark = {True: "  · loaded", False: "  · not loaded", None: ""}
        select.set_options([(model + mark[loaded], model) for model, loaded in self.models.items()])
        mine = config.model if config.backend == self.backend() else ""
        pick = mine if mine in self.models else next((m for m, loaded in self.models.items() if loaded), None)
        pick = pick or next(iter(self.models), None)
        if pick:
            select.value = pick
        self.describe()

    @on(Select.Changed, "#check-model")
    def describe(self) -> None:
        model = self.query_one("#check-model", Select).value
        if not isinstance(model, str):
            if self.models == {}:
                return
            self.note("Pick a model to check.")
        elif self.models.get(model) is False:
            self.note("⚠ Not loaded in LM Studio. Checking it makes LM Studio load it, which can unload the model "
                      "you have loaded now.", WARN)
        elif self.models.get(model):
            self.note("Loaded and ready." + ("  (your narrator)" if model == self.app.config.model else ""), GOOD)
        else:
            self.note("Your narrator's model." if model == self.app.config.model else "")

    @on(Button.Pressed, "#check-run")
    def start(self) -> None:
        self.worker = self.run_check(self.chosen())

    @on(Button.Pressed, "#check-stop")
    def stop(self) -> None:
        if self.worker is not None:
            self.worker.cancel()
            self.note("Stopped.", WARN)

    @on(Button.Pressed, "#check-use")
    def use(self) -> None:
        chosen = self.chosen()
        if chosen.backend == "openai" and not chosen.model:
            self.note("Pick a model first.", WARN)
            return
        self.app.config = chosen
        save_config(chosen)
        self.app.notify(f"{chosen.model} narrates from your next descent (a run already going keeps its model).",
                        title="Settings saved")

    @work(exclusive=True, group="check")
    async def run_check(self, config: Config) -> None:
        llm = make_llm(config)
        if llm is None:
            return
        self.running(True)
        self.query_one("#check-lines", Static).update(Text(f"Connecting to {config.model or config.url}...",
                                                           style=DIM))
        try:
            await llm.prepare()
            report = await check.run(llm, load_content(), self.progress)
        except LLMError as error:
            self.note(f"Can't use the model: {error}", BAD)
            return
        finally:
            await llm.aclose()
            self.running(False)
        check.save(report)
        self.show(report.lines())
        self.note(report.verdict().removeprefix("Verdict: "), GOOD)
        self.fill_history()

    def running(self, on: bool) -> None:
        self.query_one("#check-run", Button).disabled = on
        self.query_one("#check-stop", Button).disabled = not on
        if on:
            self.note("")
            self.query_one("#check-progress", ProgressBar).update(total=None, progress=0)
            self.query_one("#check-progress").display = True

    def progress(self, report: check.Report, step: str) -> None:
        self.query_one("#check-progress", ProgressBar).update(total=report.planned, progress=report.done)
        self.query_one("#check-status", Static).update(
            Text(f" {report.done}/{report.planned}  {step}" if step else " done", style=DIM))
        self.show(report.lines()[:-1])  # the verdict waits for the end

    def show(self, lines: list[str]) -> None:
        out = Text()
        for line in lines:
            bare = line.lstrip()
            style = (GOOD if bare.startswith("✔") else BAD if bare.startswith(("✘", "error")) else
                     WARN if bare.startswith("cut") else HEAD if line.startswith(("Typed", "Narration")) else
                     "bold" if line.startswith(("Model", "Verdict")) else "")
            out.append(line + "\n", style=style)
        self.query_one("#check-lines", Static).update(out)
        self.query_one("#check-results").scroll_end(animate=False)

    def fill_history(self) -> None:
        self.earlier = check.history()
        table = self.query_one("#check-history", DataTable)
        table.clear(columns=True)
        table.add_columns("Earlier checks", "Model", "Commands", "Narration", "Speed")
        for n, entry in enumerate(self.earlier):
            table.add_row(entry["when"].replace("T", " ")[:16], entry["model"],
                          f"{entry['right']}/{entry['commands']} right",
                          f"{entry['cut']} of {entry['sentences']} sentences cut", f"{entry['speed']:.1f}s a turn",
                          key=str(n))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        if self.worker is None or self.worker.is_finished:
            self.show(self.earlier[int(event.row_key.value)]["lines"])
            self.query_one("#check-results").scroll_home(animate=False)


# --- Log ----------------------------------------------------------------------------------------------------------

LABELS = {"stream": ("narration", ""), "json": ("json", "#8fa8ff"), "guard": ("guard cut", BAD)}


class LogTab(TableTab):
    columns = ("Time", "Kind", "What", "Reply")

    def toolbar(self) -> ComposeResult:
        with Horizontal(classes="debug-toolbar"):
            yield Select([("Everything", "all"), ("Narration", "stream"), ("JSON (commands, hints)", "json"),
                          ("Guard cuts", "guard")], value="all", allow_blank=False, compact=True, id="log-filter")
            yield Button("Refresh", compact=True, id="log-refresh")
            yield Static("", id="log-where", classes="debug-status")

    def rows(self):
        wanted = self.query_one("#log-filter", Select).value
        found = [e for e in read_log() if wanted == "all" or e.label == wanted]
        self.entries = {str(n): e for n, e in enumerate(found)}
        path = home() / "llm.log"
        self.query_one("#log-where", Static).update(
            Text(f"{short(path)} · {size(path)} · newest first", style=DIM))
        for key, entry in self.entries.items():
            name, style = LABELS.get(entry.label, (entry.label, ""))
            reply = " ".join(entry.response.split())
            yield key, [entry.time, Text(name, style=style), gist(entry)[:70], reply[:50]]

    def detail(self, key: str):
        return "", "", exchange_text(self.entries[key])

    @on(Select.Changed, "#log-filter")
    @on(Button.Pressed, "#log-refresh")
    def refresh_log(self) -> None:
        if self.loaded:
            self.load()


def gist(entry: Exchange) -> str:
    """A line saying what an exchange was about."""
    if entry.label == "guard" and isinstance(entry.request, list):
        return str(entry.request[0]) if entry.request else ""
    if isinstance(entry.request, dict):
        user = next((str(m.get("content", "")) for m in entry.request.get("messages", [])
                     if m.get("role") == "user"), "")
        typed = re.search(r"PLAYER TYPED: (.*)", user)
        return typed.group(1) if typed else (user.strip().splitlines() or [""])[0]
    return " ".join(str(entry.request).split())


def exchange_text(entry: Exchange) -> Text:
    out = Text()
    name, style = LABELS.get(entry.label, (entry.label, ""))
    out.append(f"{entry.time}  ", style=DIM)
    out.append(f"{name}\n\n", style=style or "bold")
    if entry.label == "guard" and isinstance(entry.request, list):
        out.append("CUT\n", style=BAD)
        for line in entry.request:
            out.append(f"  {line}\n")
        out.append("\nKEPT\n", style=GOOD)
        out.append(entry.response or "(nothing: the game told it plainly instead)")
        return out
    if isinstance(entry.request, dict):
        settings = {k: v for k, v in entry.request.items() if k not in ("messages", "response_format", "system")}
        out.append(" · ".join(f"{k} {v}" for k, v in settings.items()) + "\n\n", style=DIM)
        if isinstance(entry.request.get("system"), str):
            out.append("SYSTEM\n", style=ROLE)
            out.append(entry.request["system"] + "\n\n")
        for message in entry.request.get("messages", []):
            out.append(str(message.get("role", "?")).upper() + "\n", style=ROLE)
            out.append(str(message.get("content", "")) + "\n\n")
    else:
        out.append("REQUEST (the log cuts long ones short)\n", style=ROLE)
        out.append(str(entry.request) + "\n\n")
    out.append("REPLY\n", style=GOOD)
    out.append(entry.response)
    return out


# --- Test rooms ---------------------------------------------------------------------------------------------------

TEST_INTRO = (  # one paragraph, no line breaks of its own: it wraps to the tab's width
    "You start next door, so walking in plays out as in a run: Swoogy's wall to bomb (with a bomb), a shop's door (a "
    "small key, two bombs and gold to spend), a boss's locked door (its key), Lucky Lenny (his bad tooth in your "
    "pack). The kit you see is the kit you get: ↻ for another draw. Nothing in a test room counts: it never saves "
    "over your run, banks no souls, and leaves your Hall of Legends, ghosts and bestiary as they were. Esc twice to "
    "leave it. (Also: ptg --test-room list)")


class TestRoomsTab(DebugTab):
    main = "#test-who"
    seed = 0

    def compose(self) -> ComposeResult:
        content = load_content()
        found = testrooms.choices(content)
        with Horizontal(classes="debug-toolbar"):
            yield Select([(words, key) for key, words in found.items()], value="lenny", allow_blank=False,
                         compact=True, id="test-who")
            yield Select([("its own floor", 0)] + [(words, n) for n, words in testrooms.floors(content)], value=0,
                         allow_blank=False, compact=True, id="test-floor")
            yield Select([(words, key) for key, words in testrooms.LOADOUTS.items()] + [("a kit of your own", "own")],
                         value="random", allow_blank=False, compact=True, id="test-kit")
        with Horizontal(classes="debug-toolbar"):
            yield Input(placeholder="weapon=war_pick,armor=chain_shirt,helm=hard_hat,items=holy_water+pickle,level=3",
                        compact=True, disabled=True, id="test-own")
            yield Button("↻ Another", compact=True, id="test-another")
            yield Button("Go", variant="primary", compact=True, id="test-go")
        with VerticalScroll():
            yield Static("", classes="debug-info", id="test-info")

    def load(self) -> None:
        super().load()
        self.seed = random.randrange(1_000_000)
        self.preview()

    def chosen(self) -> tuple[str, str, int]:
        kit = self.query_one("#test-kit", Select).value
        if kit == "own":
            kit = self.query_one("#test-own", Input).value.strip() or "new"
        return self.query_one("#test-who", Select).value, kit, self.query_one("#test-floor", Select).value

    def preview(self) -> None:
        content = load_content()
        who, kit, floor = self.chosen()
        self.query_one("#test-floor", Select).disabled = bool(testrooms.fixed_floor(content, who))
        self.query_one("#test-own", Input).disabled = self.query_one("#test-kit", Select).value != "own"
        info = self.query_one("#test-info", Static)
        try:
            state = testrooms.build(content, who, kit, floor, name=self.app.config.player_name, seed=self.seed)
        except (ValueError, KeyError) as error:
            info.update(Group(Text(""), Text(str(error).strip("'\""), style=BAD), Text("\n" + TEST_INTRO, style=DIM)))
            return
        info.update(Group(Text(""), pairs(testrooms.describe(content, state)), Text("\n" + TEST_INTRO, style=DIM)))

    @on(Select.Changed, "#test-who, #test-floor, #test-kit")
    def changed(self, event: Select.Changed) -> None:
        if self.loaded:
            self.preview()
            if event.select.id == "test-kit" and event.value == "own":
                self.query_one("#test-own", Input).focus()

    @on(Input.Changed, "#test-own")
    def typed(self) -> None:
        if self.loaded:
            self.preview()

    @on(Button.Pressed, "#test-another")
    def another(self) -> None:
        self.seed = random.randrange(1_000_000)
        self.preview()

    @on(Input.Submitted, "#test-own")
    @on(Button.Pressed, "#test-go")
    def go(self) -> None:
        self.app.start_test_room(*self.chosen(), seed=self.seed)


# --- 3D -----------------------------------------------------------------------------------------------------------

FIGHT = (("entrance", 1), ("idle", 2), ("windup", 2), ("attack", 1), ("idle", 2))  # "all": in the order a fight has them
HOLD = 0.6  # seconds a clip played on its own rests on its last frame before it goes again (idle just loops)
TURN = 15  # degrees ← and → turn a model
BY_HAND = "shaped by hand in its sprite's colours, where the sprite can't say the shape"
MADE = {"slab": "a slab: its sprite given depth", "puffed": "a relief of its sprite, thicker toward the middle",
        "turned": "turned on a lathe from its sprite's rows",
        "jar": "a jar: its glass an outline, what's in it floating inside",
        "ring": BY_HAND, "dice": BY_HAND, "cheese": BY_HAND,
        "blender": "in Blender, by its own build script (spikes/goblin3d)"}


def at_size(sized: tuple[Clip, ...], size: int) -> Clip:
    """A clip at a size, or the biggest it comes in under it (else its smallest)."""
    under = [clip for clip in sized if clip.size <= size]
    return under[-1] if under else sized[0]


def clip_names(key: str) -> list[str]:
    """A boss's clips, in the order a fight has them."""
    found = clips(key)
    return [name for name in dict.fromkeys(name for name, _ in FIGHT) if name in found] + sorted(
        name for name in found if name not in dict(FIGHT))


def clip_sizes(key: str) -> list[int]:
    return sorted({clip.size for sized in clips(key).values() for clip in sized})


class ClipView(Widget):
    """A boss's clips (sprites.clips) at the size and speed they were made: one over and over, or all of them in the
    order a fight has them, with which it is and what frame under it."""

    DEFAULT_CSS = """
    ClipView { width: 100%; height: 1fr; content-align: center middle; }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.key, self.clip, self.wanted = "", "all", 0  # (wanted: 0 for the biggest that fits)
        self.reel: list[tuple[str, int, Clip]] = []  # each frame in turn: its clip's name, its number, the clip
        self.ends: list[float] = []  # when each frame is over, in seconds from the start
        self.texts: dict[int, Text] = {}
        self.started = time.monotonic()
        self.shown = -1
        self.picture = Text()

    def on_mount(self) -> None:
        self.set_interval(1 / 24, self.tick)

    def play(self, key: str, clip: str = "all", size: int = 0) -> None:
        """The boss's `clip` ("all": each in turn), at `size` (0: the biggest that fits), from its start."""
        self.key, self.clip, self.wanted = key, clip, size
        self.started, self.reel = time.monotonic(), []
        self.tick()

    def on_resize(self) -> None:
        self.reel = []  # the biggest that fits may be another size now

    @property
    def playing_at(self) -> int:
        """The size it's playing at."""
        return self.reel[0][2].size if self.reel else 0

    def fitting(self) -> int:
        """The biggest size whose every frame fits, with a line under it (the smallest, if none does)."""
        width, height = self.content_size
        found = clips(self.key)
        fit = [size for size in clip_sizes(self.key)
               if size <= 2 * (height - 1) and all(at_size(sized, size).frames[0].width <= width
                                                   for sized in found.values())]
        return fit[-1] if fit else clip_sizes(self.key)[0]

    def build(self) -> None:
        found = clips(self.key)
        size = self.wanted or self.fitting()
        order = [(name, times) for name, times in FIGHT if name in found] if self.clip == "all" else [(self.clip, 1)]
        self.reel, self.ends, self.texts, self.shown, end = [], [], {}, -1, 0.0
        for name, times in order:
            clip = at_size(found[name], size)
            for _ in range(times):
                for n in range(len(clip.frames)):
                    end += 1 / clip.fps
                    self.reel.append((name, n, clip))
                    self.ends.append(end)
        if self.clip not in ("all", "idle"):
            self.ends[-1] += HOLD

    def tick(self) -> None:
        width, height = self.content_size
        if not self.key or not width or not height or not self.is_on_screen:
            return
        if not self.reel:
            self.build()
        index = min(bisect.bisect_right(self.ends, (time.monotonic() - self.started) % self.ends[-1]),
                    len(self.reel) - 1)
        if index == self.shown:
            return
        self.shown = index
        if index not in self.texts:
            name, n, clip = self.reel[index]
            caption = f"{name}  {n + 1}/{len(clip.frames)}" + ("  lands" if name == "entrance" and n == clip.land
                                                              and clip.land else "")
            self.texts[index] = Text.assemble(image_text(clip.frames[n]), "\n",
                                              (caption.center(clip.frames[n].width), DIM), no_wrap=True,
                                              overflow="crop")
        self.picture = self.texts[index]
        self.refresh()

    def render(self) -> Text:
        return self.picture


class ThreeDTab(TableTab):
    """Everything drawn in 3D: the bosses' clips, made in Blender (spikes/goblin3d) and played as made, and every
    item's model, drawn as you watch and turned however you like (ptg.model3d), as the pack's "Turn it over" does."""

    columns = ("Thing", "Is", "Made", "Moves", "Size")
    BINDINGS = [Binding("left", "step(-1)", show=False, priority=True),
                Binding("right", "step(1)", show=False, priority=True),
                Binding("space", "spin", show=False, priority=True)]
    chosen_clip, chosen_size = "all", 0  # what a boss plays, and at what size (0: the biggest that fits)

    def compose(self) -> ComposeResult:
        yield Static("", id="three-d-controls", classes="debug-toolbar")
        with Horizontal(classes="debug-split"):
            yield self.make_table()
            with Vertical(classes="debug-detail"):
                yield ModelView(id="three-d-model")
                yield ClipView(id="three-d-clip")
                with VerticalScroll(id="three-d-about"):
                    yield Static("", classes="debug-info")

    def rows(self):
        self.content = load_content()
        self.things: dict[str, str] = {}
        for m in self.content.monsters.values():
            if clips(m.key):
                self.things[m.key] = "boss"
                sizes = clip_sizes(m.key)
                yield m.key, [Text(m.name, style="bold"), "boss" if m.boss else "guardian" if "guardian" in m.tags
                              else "monster", "Blender clips",
                              plural(len(clips(m.key)), "clip"), f"{sizes[0]}-{sizes[-1]} px"]
        for i in self.content.items.values():
            if model3d.available(i.key):
                self.things[f"item_{i.key}"] = "item"
                model = model3d.load(i.key)
                yield f"item_{i.key}", [Text(i.name, style="bold"), i.kind,
                                        Text(model.made or "?", style=WARN if model3d.stale(i.key) else ""),
                                        "still" if model.frames == 1 else f"{model.frames} frames",
                                        size(Path(str(model3d.path_of(i.key))))]

    @property
    def is_item(self) -> bool:
        return self.things.get(self.current) == "item"

    def show(self, key: str) -> None:
        self.current = key
        model, clip = self.query_one(ModelView), self.query_one(ClipView)
        model.display, clip.display = self.is_item, not self.is_item
        if self.is_item:
            model.show(key.removeprefix("item_"))
            info = self.item_info(key.removeprefix("item_"))
        else:
            if self.chosen_clip not in clip_names(key):
                self.chosen_clip = "all"
            clip.play(key, self.chosen_clip, self.chosen_size)
            info = self.boss_info(key)
        self.query_one(".debug-info", Static).update(info)
        self.controls()

    def item_info(self, key: str) -> Group:
        item, model = self.content.item(key), model3d.load(key)
        faces = sum(len(part.faces) for part in model.parts)
        start = time.perf_counter()
        for turn in range(3):
            model3d.render(model, turn, turn * 40, size=64)
        took = (time.perf_counter() - start) / 3 * 1000
        if not model.sprite:
            drawn = Text("not made from it, so it can be drawn again without it", style=DIM)
        elif model3d.stale(key):
            drawn = Text(f"drawn again since: make it again (uv run ptg models {key}); shown made afresh",
                         style=WARN)
        else:
            drawn = Text("made from it as it's drawn now", style=GOOD)
        rows = [("Made", MADE.get(model.made, model.made or "it doesn't say")), ("Its sprite", drawn),
                ("Parts", f"{plural(len(model.parts), 'part')}, {plural(faces, 'face')}"),
                ("Moves", "no: it's still" if model.frames == 1 else f"{model.frames} frames at {model.fps} a second"),
                ("File", f"models/{key}.json, {size(Path(str(model3d.path_of(key))))}"),
                ("Draws in", f"{took:.1f} ms a frame, 64 pixels across")]
        return Group(Text.assemble((item.name, "bold #4cff8a"), (f"  {key}", DIM)), pairs(rows),
                     Text("\nDrag it round, or ← →; space stops it turning or starts it again; the mouse wheel zooms. "
                          "Enter turns it over in a window, as the pack does.", style=DIM))

    def boss_info(self, key: str) -> Group:
        m, found = self.content.monster(key), clips(key)
        rows = []
        for name in clip_names(key):
            clip = found[name][-1]
            rows.append((name, f"{len(clip.frames)} frames, {len(clip.frames) / clip.fps:.1f} s at {clip.fps:g} a "
                               "second" + (f"; the feet land on frame {clip.land + 1}" if clip.land else "")))
        rows += [("Sizes", listed(f"{n} px" for n in clip_sizes(key))),
                 ("On the stage", f"at {CLIP_FPS} frames a second at most (here, as made)"),
                 ("Made", "in Blender, from its sprite (spikes/goblin3d, and its README)")]
        return Group(Text.assemble((m.name, "bold #ff4b4b"), (f"  {key}  ", DIM), ("boss" if m.boss else "", WARN)),
                     pairs(rows), Text("\n← → or a click picks the clip; space or Enter plays it from the start. "
                                       "Front view only: the bosses are made to be seen from the front.", style=DIM))

    def controls(self) -> None:
        def link(words: str, verb: str, value: object = "", on: bool = False) -> str:
            return f"[reverse]{words}[/]" if on else f"[@click=screen.three_d('{verb}', '{value}')]{words}[/]"

        if self.is_item:
            line = (f"Turn:  {link('◀', 'turn', 'left')}  {link('▶', 'turn', 'right')}  ·  {link('spin', 'spin')}  ·  "
                    f"{link('from the front', 'front')}  ·  {link('in a window', 'open')}")
        else:
            plays = "  ".join(link(name, "clip", name, name == self.chosen_clip)
                              for name in ["all", *clip_names(self.current)])
            sizes = "  ".join(link(words, "size", n, n == self.chosen_size)
                              for words, n in [("fits", 0), *[(str(n), n) for n in clip_sizes(self.current)]])
            line = f"Play:  {plays}      Size:  {sizes}"
        self.query_one("#three-d-controls", Static).update(line)

    def act(self, verb: str, value: str = "") -> None:
        """What a link in the toolbar does."""
        if verb == "turn":
            self.action_step(-1 if value == "left" else 1)
        elif verb == "spin":
            self.action_spin()
        elif verb == "front":
            view = self.query_one(ModelView)
            view.reset()
            view.spinning = False
        elif verb == "open":
            self.open()
        elif verb == "clip":
            self.chosen_clip = value
            self.show(self.current)
        elif verb == "size":
            self.chosen_size = int(value)
            self.show(self.current)

    def action_step(self, step: int) -> None:
        """An item turns; a boss plays its clip before or after."""
        if not self.current:
            return
        if self.is_item:
            view = self.query_one(ModelView)
            view.spinning, view.swing = False, 0.0
            view.yaw -= step * TURN
            return
        names = ["all", *clip_names(self.current)]
        self.chosen_clip = names[(names.index(self.chosen_clip) + step) % len(names)]
        self.show(self.current)

    def action_spin(self) -> None:
        """An item stops turning, or starts again; a boss plays its clip from the start."""
        if self.is_item:
            view = self.query_one(ModelView)
            view.spinning, view.swing = not view.spinning, 0.0
        elif self.current:
            self.query_one(ClipView).play(self.current, self.chosen_clip, self.chosen_size)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        if self.is_item:
            self.open()
        else:
            self.action_spin()

    def open(self) -> None:
        key = self.current.removeprefix("item_")
        self.app.push_screen(ModelScreen(key, self.content.item(key).name))


# --- the screen ---------------------------------------------------------------------------------------------------

TABS = {"overview": ("Overview", OverviewTab), "monsters": ("Monsters", MonstersTab), "items": ("Items", ItemsTab),
        "art": ("Art", ArtTab), "sounds": ("Sounds", SoundsTab), "story": ("Story", StoryTab),
        "state": ("State", StateTab), "models": ("Models", ModelsTab), "log": ("Log", LogTab),
        "test": ("Test rooms", TestRoomsTab), "3d": ("3D", ThreeDTab)}
KEYS = (*"1234567890", "minus")  # each tab's key, in turn


class DebugScreen(Panel):
    BINDINGS = [Binding("escape,f12", "close", "Close"), Binding("r", "reload", "Refresh", show=False),
                *[Binding(n, f"tab('{key}')", show=False) for n, key in zip(KEYS, TABS)]]
    size_class = "full"

    def __init__(self, tab: str = "overview") -> None:
        super().__init__()
        self.first = tab

    def compose(self) -> ComposeResult:
        with Vertical(classes="panel-box debug-box") as box:
            box.border_title = "Debug"
            box.border_subtitle = "1-9, 0, - tabs · r refresh · Esc close"
            with TabbedContent(initial=f"debug-{self.first}", id="debug-tabs"):
                for key, (title, tab) in TABS.items():
                    with TabPane(title, id=f"debug-{key}"):
                        yield tab()

    def on_mount(self) -> None:
        self._fill(self.query_one(f"#debug-{self.first}", TabPane))
        self.call_after_refresh(self._focus_active)

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        self._fill(event.pane)

    def _fill(self, pane: TabPane) -> None:
        tab = pane.query_one(DebugTab)
        if not tab.loaded:
            tab.load()

    def _focus_active(self) -> None:
        # Only ever into the tab on show: focusing a widget in another tab would switch back to it.
        pane = self.query_one(TabbedContent).active_pane
        if pane is not None:
            pane.query_one(DebugTab).focus_main()

    def action_tab(self, key: str) -> None:
        self.query_one(TabbedContent).active = f"debug-{key}"
        self.call_after_refresh(self._focus_active)

    def action_reload(self) -> None:
        self.query_one(TabbedContent).active_pane.query_one(DebugTab).load()

    def action_pose(self, pose: str) -> None:
        self.query_one(ArtTab).set_pose(pose)

    def action_three_d(self, verb: str, value: str = "") -> None:
        self.query_one(ThreeDTab).act(verb, value)

    def on_unmount(self) -> None:
        sound.end_preview()  # (the game's own music back, if the Sounds tab had the music's channel)
