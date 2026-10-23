"""The debug screen (F12, or `ptg --debug`): what the game is made of and what it remembers, at a glance, with
sounds to play and a model check to run.

    Overview   what's loaded, your settings and files, and anything that looks wrong
    Monsters   every monster: its art, numbers, who drew it, where it lives, what your bestiary knows
    Items      every item, the same way
    Art        every sprite, animated in each pose a fight puts it in
    Sounds     every moment's sound (click it, or Enter, to play it) and where it came from
    Story      every story event: reload the files after editing them, or fire one on the next descent
    State      this run's story flags and its whole save, and your profile's marks, secrets and souls
    Models     the model check (ptg.llm.check) against any model, with earlier results to compare
    Log        the latest exchanges with the model (llm.log), guard cuts included

It only looks, except where a button says otherwise.
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

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
from textual.widgets import Button, DataTable, Input, ProgressBar, Select, Static, TabbedContent, TabPane, Tree

from .. import __version__, integrity, sound
from ..config import DEFAULT_CLAUDE_MODEL, DEFAULT_URLS, Config, home, load_game, save_config
from ..content import Content, load_content
from ..game import Game
from ..library import credits, lives, maker_folder
from ..llm import LLMError, check, make_llm
from ..llm.base import Exchange, read_log
from ..llm.openai_compat import OpenAICompatLLM
from ..models import GameState
from ..sprites import DEATH_FRAMES, frame_count, side_by_side, sprite_text
from ..story import StoryError, StoryEvent, load_library, reload_library
from ..text import mid_sentence
from .panels import Panel

POSES = ("idle", "windup", "dizzy", "calm", "lunge", "shake", "death")
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


def poses(key: str, room: int, width: int = 16) -> Text:
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

class PoseSprite(Static):
    """A sprite animating in one pose (see ptg.sprites), or a stand-in text when there's no sprite."""

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self.key, self.pose, self.fallback, self.ticks = "", "idle", "", 0

    def on_mount(self) -> None:
        self.set_interval(0.2, self._tick)

    def show(self, key: str, pose: str = "idle", fallback: str = "") -> None:
        self.key, self.pose, self.fallback, self.ticks = key, pose, fallback, 0
        self._draw()

    def _tick(self) -> None:
        self.ticks += 1
        if self.region.area and frame_count(self.key):  # only while it's on screen
            self._draw()

    def _draw(self) -> None:
        if self.pose == "death":  # dissolve, rest a moment on nothing, then again
            frame = min(self.ticks % (DEATH_FRAMES + 5), DEATH_FRAMES - 1)
        else:
            frame = self.ticks % 24
        art = sprite_text(self.key, frame, pose=self.pose) if self.key else None
        self.update(art if art is not None else Text(self.fallback, style=DIM))
        self.display = art is not None or bool(self.fallback)


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
    item_art = [i for i in items if frame_count(f"item_{i.key}")]
    clips = [clip for found in engine.bank.values() for clip in found]
    sprites = sorted((integrity.data_folder() / "sprites").glob("*.png"))

    problems: list[Text] = []
    if report.tampered:
        problems.append(Text(f"The data files changed since they were signed ({'; '.join(report.lines())}). If that "
                             "was you, sign them: uv run python -m ptg.integrity --sign", style=WARN))
    problems += [Text(f"Sounds: {problem}", style=WARN) for problem in engine.problems]
    if no_sprite:
        problems.append(Text(f"No sprite yet, so ASCII art stands in: {listed(no_sprite)}", style=DIM))
    if config.backend == "offline":
        problems.append(Text("The narrator is offline: the game tells the facts plainly.", style=DIM))

    narrator = [("Backend", config.backend)]
    if config.backend == "openai":
        narrator.append(("Server", config.url))
    narrator += [("Model", config.model or "whatever the server has loaded"), ("Temperature", config.temperature),
                 ("Tone", config.tone), ("API key", "set" if config.api_key else "not set")]
    settings = [("Your name", config.player_name), ("Dice", "roll themselves" if config.auto_roll else "you roll"),
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
        ("Sprites", len(sprites)),
        ("Sounds", f"{len(clips)} files for {len(engine.bank)} moments ({sum(not c.builtin for c in clips)} yours)"),
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
                                 ("Playing", "yes" if engine.enabled else "no")]),
        heading("Your files"), pairs(files),
        heading("Game data"), pairs(data),
        heading("Run"), pairs(run),
    )


# --- Monsters and items -------------------------------------------------------------------------------------------

class MonstersTab(TableTab):
    columns = ("Monster", "Tier", "HP", "Def", "Atk", "Dmg", "XP", "Weak to", "Art", "Drawn by")

    def rows(self):
        self.content = load_content()
        self.credits = credits()["monster"]
        self.known = self.app.profile.bestiary()
        for m in self.content.monsters.values():
            tier = "boss" if m.boss else "ghost" if m.ghost else str(m.tier)
            art = "sprite" if frame_count(m.key) else Text("ascii", style=DIM)
            yield m.key, [Text(m.name, style="bold"), tier, m.hp, m.defense, m.attack, m.damage, m.xp,
                          listed(m.weak, "-"), art, self.credits.get(m.key, {}).get("by", "")]

    def detail(self, key: str):
        m = self.content.monster(key)
        themes = list(self.content.themes.values())
        rank = "boss" if m.boss else "ghost" if m.ghost else f"tier {m.tier}"
        parts = [Text.assemble((m.name, "bold #ff4b4b"), (f"  {m.key}  ", DIM), (rank, WARN)),
                 pairs([("HP", m.hp), ("Defense", m.defense), ("Attack", m.attack), ("Damage", m.damage),
                        ("XP", m.xp), ("Tags", listed(m.tags, "-")), ("Weak to", listed(m.weak, "-")),
                        ("Thinks", "yes: it can be talked to" if m.intelligent else "no"),
                        ("Heavy blow", f"it {mid_sentence(m.tell)}"),
                        ("Lives in", listed(lives(m.key, m.tags, m.ghost, themes), "-")),
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
    columns = ("Item", "Kind", "Tier", "Damage", "Defense", "Heal", "Art", "Drawn by")

    def rows(self):
        self.content = load_content()
        self.credits = credits()["item"]
        for i in self.content.items.values():
            art = "sprite" if frame_count(f"item_{i.key}") else Text("-", style=DIM)
            yield i.key, [Text(i.name, style="bold"), i.kind, i.tier or "-", i.damage or "-", i.defense or "-",
                          i.heal or "-", art, self.credits.get(i.key, {}).get("by", "")]

    def detail(self, key: str):
        i = self.content.item(key)
        rows = [("Kind", i.kind), ("Tier", i.tier or "-")]
        rows += [(name, value) for name, value in (("Damage", i.damage), ("Defense", i.defense), ("Heals", i.heal))
                 if value]
        if i.escape:
            rows.append(("Escape", "gets you out of a fight"))
        rows.append(("Tags", listed(i.tags, "-")))
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


# --- Art ----------------------------------------------------------------------------------------------------------

class ArtTab(TableTab):
    columns = ("Sprite", "Frames", "Size", "Used for")
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
        self.uses = uses
        self.paths = {p.stem: p for p in sorted((integrity.data_folder() / "sprites").glob("*.png"))}
        for key, path in self.paths.items():
            count, width, height = sheet(path)
            yield key, [Text(key, style="bold"), count, f"{width}×{height}", listed(uses.get(key, []), "")]
        self.set_pose(self.chosen_pose)

    def detail(self, key: str):
        path = self.paths[key]
        count, width, height = sheet(path)
        room = self.room()
        frames = tiles([(f"frame {n + 1}", sprite_text(key, n, 16)) for n in range(count)], 16, room)
        info = pairs([("File", short(path)), ("Frames", f"{count}, {width}×{height} pixels each"),
                      ("Used for", listed(self.uses.get(key, []), "nothing yet")),
                      ("Drawn by", credit_line(self.credits.get(key)))])
        return key, "", Group(info, heading("Frames"), frames, heading("Poses"), poses(key, room))

    def pose(self) -> str:
        return self.chosen_pose

    def set_pose(self, pose: str) -> None:
        self.chosen_pose = pose
        links = "  ".join(f"[reverse]{p}[/]" if p == pose else f"[@click=screen.pose('{p}')]{p}[/]" for p in POSES)
        self.query_one("#art-poses", Static).update(f"Animate:  {links}")
        if self.current:
            self.query_one(PoseSprite).show(self.current, pose)


def sheet(path: Path) -> tuple[int, int, int]:
    """(frames, frame width, height) of a sprite strip."""
    try:
        from PIL import Image

        with Image.open(path) as image:
            count = int(image.info.get("frames") or 0) or max(1, image.width // image.height)
            return count, image.width // count, image.height
    except (ImportError, OSError, ValueError):
        return frame_count(path.stem), 0, 0


# --- Sounds -------------------------------------------------------------------------------------------------------

class SoundsTab(TableTab):
    columns = ("Moment", "When it plays", "Length", "Files")

    def toolbar(self) -> ComposeResult:
        with Horizontal(classes="debug-toolbar"):
            yield Button("▶ Play", compact=True, id="sound-play")
            yield Button("Reload sounds", compact=True, id="sound-reload")
            yield Button("Open your sounds folder", compact=True, id="sound-folder")
            yield Static("", id="sound-status", classes="debug-status")

    def make_table(self) -> DataTable:
        return ClickTable(cursor_type="row", zebra_stripes=True)

    def rows(self):
        self.turns: dict[str, int] = {}
        engine = sound.engine()
        config = self.app.config
        player = getattr(engine.player, "name", None) or "opens on the first sound"
        self.query_one("#sound-status", Static).update(Text(
            f"player: {player} · sound {'on' if config.sound else 'off'} (F8) · volume {config.volume}% · "
            f"yours go in {short(sound.user_folder())} (green ones are yours)", style=DIM))
        for moment, what in sound.MOMENTS.items():
            clips = engine.bank.get(moment, [])
            length = sound.clip_length(clips[0]) if clips else None
            files = (sound.clip_name(clips[0]) + (f" +{len(clips) - 1}" if len(clips) > 1 else "")) if clips else "-"
            mine = any(not clip.builtin for clip in clips)
            yield moment, [Text(moment, style=f"bold {GOOD}" if mine else "bold"), what,
                           f"{length:.2f}s" if length else "-", files]

    def detail(self, moment: str):
        engine = sound.engine()
        parts = [Text.assemble((moment, "bold"), (f"  {sound.MOMENTS.get(moment, '')}", DIM)),
                 Text("Click it or press Enter to play. With several files, each play takes the next.", style=DIM)]
        for clip in engine.bank.get(moment, []):
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
        if not engine.bank.get(moment):
            parts.append(Text("\nNo sound for this moment.", style=DIM))
        return "", "", Group(*parts)

    def play(self, moment: str) -> None:
        clips = sound.engine().bank.get(moment, [])
        if not clips:
            return
        turn = self.turns.get(moment, 0)
        self.turns[moment] = turn + 1
        clip = clips[turn % len(clips)]
        self.run_worker(lambda: self._play(clip), thread=True, group="sound")

    def _play(self, clip: sound.Clip) -> None:
        problem = sound.preview(clip)
        if problem:
            self.app.call_from_thread(self.app.notify, problem, title="Can't play it", severity="warning")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        self.play(event.row_key.value)

    @on(Button.Pressed, "#sound-play")
    def play_current(self) -> None:
        if self.current:
            self.play(self.current)

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


# --- the screen ---------------------------------------------------------------------------------------------------

TABS = {"overview": ("Overview", OverviewTab), "monsters": ("Monsters", MonstersTab), "items": ("Items", ItemsTab),
        "art": ("Art", ArtTab), "sounds": ("Sounds", SoundsTab), "story": ("Story", StoryTab),
        "state": ("State", StateTab), "models": ("Models", ModelsTab), "log": ("Log", LogTab)}


class DebugScreen(Panel):
    BINDINGS = [Binding("escape,f12", "close", "Close"), Binding("r", "reload", "Refresh", show=False),
                *[Binding(str(n), f"tab('{key}')", show=False) for n, key in enumerate(TABS, 1)]]

    def __init__(self, tab: str = "overview") -> None:
        super().__init__()
        self.first = tab

    def compose(self) -> ComposeResult:
        with Vertical(classes="panel-box debug-box") as box:
            box.border_title = "Debug"
            box.border_subtitle = "1-9 tabs · r refresh · Esc close"
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
