"""Reusable pieces of the game screen: the HUD, room view, monster card, choice list, inline dice, and Picture, the one
way anything with a sprite is drawn."""

from __future__ import annotations

import asyncio
import random
import textwrap
from functools import lru_cache
from typing import NamedTuple
from weakref import WeakKeyDictionary

from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult, ScreenStackError
from textual.containers import Horizontal, Vertical
from textual.dom import NoScreen
from textual.events import Click, Leave, MouseMove
from textual.message import Message
from textual.screen import Screen
from textual.timer import Timer
from textual.types import NoActiveAppError
from textual.widgets import Static

from .. import layout, loot, powers, sound, statuses
from ..content import Content
from ..events import Action, Event
from ..glossary import Lexicon
from ..models import LEVEL_XP, GameState
from ..outcome import tone, verdict
from ..sprites import DEFAULT_WIDTH, GREYS, SMALL, Image, frames, idle_frames, image_text, sprite_text
from ..world import render_map
from . import effects
from .theme import CELL_STYLES, MAP_STYLES


TERM_STYLES = {
    "monster": "bold #ff4b4b", "character": "bold #ffd166", "item": "bold #4cff8a", "feature": "bold #ffb000",
    "fixture": "bold #ff4f9a", "room": "#8fa8ff", "rule": "bold #5fe3ff",
}

# How big the screen is. Every screen, a pop-up's too, gets a class for its width and one for its height (PTGApp's
# breakpoints) to style itself by in app.tcss: -narrow or -wide, and -tiny, -short or -tall. Code that sizes things
# goes by the same lines.
WIDE = 88  # columns from which a screen is -wide: room for two columns side by side
TALL = 34  # rows from which a screen is -tall: room for a blank line between things (below it, boxes drop them)
TINY = 28  # rows below which a screen is -tiny (from there to TALL, -short): the smaller pictures, nothing to spare


def highlight(text: str, lexicon: Lexicon | None, style: str = "") -> Text:
    """Colour the monsters, items, features and rooms in a piece of narration, and make them clickable."""
    out = Text(text, style=style)
    if lexicon is None:
        return out
    for start, end, term in lexicon.find(text):
        # Not a Textual "@click" link: those get repainted in the theme's link colour.
        meta = {"term": term.id, "tip": term.summary}
        out.stylize(Style.parse(TERM_STYLES.get(term.kind, "bold")) + Style(meta=meta), start, end)
    return out


class StoryLine(Static):
    """A line of the story whose highlighted terms explain themselves on hover and open a card on click."""

    def _meta_at(self, x: int, y: int) -> dict:
        return getattr(self.get_style_at(x, y), "meta", None) or {}

    def on_mouse_move(self, event: MouseMove) -> None:
        tip = self._meta_at(event.x, event.y).get("tip")
        if tip != self.tooltip:
            self.tooltip = tip

    def on_click(self, event: Click) -> None:
        term = self._meta_at(event.x, event.y).get("term")
        if term and hasattr(self.screen, "action_lookup"):
            self.screen.action_lookup(term)

    def on_leave(self, event: Leave) -> None:
        self.tooltip = None


def bar(value: int, maximum: int, width: int = 14) -> str:
    filled = round(width * max(0, value) / max(1, maximum))
    return "█" * filled + "░" * (width - filled)


def hearts(hp: int, max_hp: int, tint: str = "") -> Text:
    """Tiny Rogues style: a heart per 5 HP (in a status's colour while it's in your blood: poison's purple)."""
    text = Text()
    for i in range(0, max_hp, 5):
        chunk = hp - i
        if chunk >= 5:
            text.append("♥", style=f"bold {tint or '#ff4b4b'}")
        elif chunk > 0:
            text.append("♥", style="dim " + tint if tint else "#8a2a3a")
        else:
            text.append("♡", style="#4a3040")
    return text


def roll_text(event: Event) -> Text:
    """A finished roll for the story log: the sum, then a coloured badge saying how it went for you, then what a hit
    did ("→ 18 damage (4d6 14 + crit 4d6 4)"): the narration tells the blow, this line the numbers."""
    roll, how = event.dice, tone(event)
    text = Text("  ⚄ ", style=effects.COLORS[how])
    text.append(roll.describe(verdict=False), style="#c8c8e0" if roll.actor == "player" else "#9a9cc0")
    text.append("  ")
    text.append_text(effects.badge(how, verdict(event)))
    if roll.told():
        text.append(f"  → {roll.told()}", style="bold #ffb000" if roll.actor == "player" else "bold #ff7b7b")
    return text


class Hud(Static):
    """The top status bar: hearts (and what ails you: ☠ Poisoned), defense, Fate, gold, souls, bombs and small keys,
    the boss key, XP and floor. On a screen too narrow for all of it, the least of it goes first (see HUD_DROPS), never
    cut off mid-word."""

    shown: tuple[GameState, Content] | None = None
    lit: frozenset[str] = frozenset()  # counters lit up for a moment: gold, bombs or keys just gained (light)
    at: dict[str, int] = {}  # where each part starts, in cells from the bar's left edge, as last shown

    def light(self, names: set[str], seconds: float = 1.4) -> None:
        """Light up the counters that just went up, for a moment."""
        self.lit = frozenset(names)
        if self.shown:
            self.show(*self.shown)

        def out() -> None:
            if self.lit == frozenset(names):
                self.lit = frozenset()
                if self.shown:
                    self.show(*self.shown)

        self.set_timer(seconds, out)

    def show(self, state: GameState, content: Content) -> None:
        self.shown = (state, content)
        player = state.player
        parts: dict[str, Text] = {}
        ailing = [statuses.DEFS[k] for k in player.statuses if k in statuses.DEFS]
        parts["hp"] = hearts(player.hp, player.max_hp, ailing[0].colour if ailing else "")
        parts["hp"].append(f" {player.hp}/{player.max_hp}", style="bold")
        if ailing:  # (right by your health: it's what it's eating)
            parts["status"] = Text.assemble(*[(f"{d.icon} {d.name}", f"bold {d.colour}") for d in ailing])
        parts["defense"] = Text.assemble(("⛨ ", "#6c8cff"), str(player.defense(content)))
        parts["fate"] = Text.assemble(*[("✦", "bold #ffd166") if i < player.fate else ("✧", "#5a5030")
                                        for i in range(player.max_fate())])
        parts["gold"] = Text.assemble(("¤ ", "#ffb000"), str(player.gold))
        parts["souls"] = Text.assemble(("☽ ", "#5fe3ff"), str(state.souls))
        parts["bombs"] = Text.assemble(("● ", "#ff7b39"), str(player.bombs))
        parts["keys"] = Text.assemble(("⚷ ", "#c0cbdc"), str(player.keys))
        if content.themes[state.theme].key_item in player.inventory:
            parts["boss_key"] = Text("♀ key", style="bold #ffb000")
        parts["level"] = Text(f"Lv {player.level}", style="bold #ff4f9a")
        next_xp = player.next_level_xp()
        if next_xp:
            prev = LEVEL_XP[player.level - 1]
            parts["xp"] = Text(bar(player.xp - prev, next_xp - prev, 8), style="#ff4f9a")
        parts["floor"] = Text(f"Floor {state.floor}/{state.floors_total}", style="bold #6c8cff")
        parts["theme"] = Text(f"· {content.themes[state.theme].name}", style="bold #6c8cff")
        parts["turn"] = Text(f"turn {state.turn}", style="#6c6f99")
        if state.daily:
            parts["daily"] = Text(f"DAILY {state.daily}", style="bold #ff4f9a")
        room = self.content_region.width or self.app.size.width - 2  # (before it's laid out, about that)
        for name in HUD_DROPS:
            if self._width(parts) <= room:
                break
            parts.pop(name, None)
        text, at = Text(), {}
        for name, part in parts.items():
            if text:
                text.append(" " if name in ("xp", "theme") else "   ")
            at[name] = text.cell_len
            if name in self.lit:
                part = Text(part.plain, style="bold #10122a on #ffd166")  # (as wide as ever: nothing shifts)
            text.append_text(part)
        self.at = at
        self.update(text)

    @staticmethod
    def _width(parts: dict[str, Text]) -> int:
        return sum(part.cell_len for part in parts.values()) + sum(
            1 if name in ("xp", "theme") else 3 for name in list(parts)[1:])

    def on_resize(self) -> None:
        if self.shown is not None:
            self.show(*self.shown)


HUD_DROPS = ("turn", "theme", "daily", "souls", "xp", "keys", "bombs", "defense")  # the HUD's least, first to go


def legend(entries: list[tuple[str, str, str]], width: int | None = None, words: str = "#9a9cc0") -> Text:
    """A legend of (glyph, its style, what it is): an entry to a line; or, given a `width`, as many to a line as fit,
    two spaces apart. Either way a glyph is never parted from what it is (a narrow sidebar once split them)."""
    text = Text()
    used = 0
    for glyph, style, label in entries:
        size = cell_len(f"{glyph} {label}")
        if text:
            fits = width is not None and used + 2 + size <= width
            text.append("  " if fits else "\n")
            used = used + 2 if fits else 0
        text.append(glyph, style=style)
        text.append(f" {label}", style=words)
        used += size
    return text


def room_text(state: GameState, content: Content, legend_width: int | None = None) -> Text:
    """The room's floor plan, and under it the legend of what's in it (see legend: `legend_width` packs it)."""
    rows, items = layout.render(state, content)
    text = Text()
    for row in rows:
        for glyph, style in row:
            text.append(glyph, style=CELL_STYLES.get(style, ""))
        text.append("\n")
    text.append_text(legend([(glyph, CELL_STYLES.get(style, ""), label) for glyph, style, label in items],
                            legend_width))
    return text


# The floor map's legend, in this order: a mark is listed while it's on the map (see world.map_glyph); "#" and "B"
# are rooms you've been in and the boss's.
MAP_LEGEND = (("@", "you"), ("!", "foe"), ("B", "boss"), ("#", "visited"), ("?", "unknown"), (">", "stairs"),
              ("†", "shrine"), ("■", "chest"), ("◊", "fountain"), ("¤", "shop"), ("$", "a tip"),
              ("{✧}", "secret room"), ("=", "locked"), ("☺", "wants you"))


def map_text(state: GameState, legend_width: int | None = None) -> Text:
    """The floor's map, and under it a legend of the marks on it (see legend: `legend_width` packs it)."""
    text = Text()
    lines = render_map(state)
    for line in lines:
        for ch in line:
            text.append(ch, style=MAP_STYLES.get(ch, "#6c6f99"))
        text.append("\n")
    marks = [(glyph, MAP_STYLES.get(glyph[0], "#6c6f99"), label) for glyph, label in MAP_LEGEND
             if any(glyph[0] in line for line in lines)]
    text.append_text(legend(marks, legend_width, words="#6c6f99"))
    return text


def portrait(key: str, content: Content, sprites: bool = True, frame: int = 0, flash: bool = False,
             style: str = "#ff4b4b", pose: str = "idle") -> Text:
    """A monster's pixel sprite (in a pose), or its ASCII art when sprites are off or missing."""
    art = sprite_text(key, frame, flash=flash, pose=pose) if sprites else None
    if art is None:
        art = Text(content.monster(key).art, style="bold #ffffff" if flash else style)
    return art


def monster_pose(monster) -> str:
    """How a monster stands right now: the sprite shows its state at a glance. Calm, it's just itself, in its own
    colours (a character always is: the words under it say it's calm)."""
    if not monster.hostile:
        return "idle"
    if monster.stunned:
        return "dizzy"
    if monster.intent == "heavy":
        return "windup"
    return "idle"


def status_rows(state: GameState, short: bool = False) -> int:
    """How many lines monster_status always takes: its HP and how it is (not when it's `short`), and what it's weak to
    with the Lorekeeper's blessing (otherwise that's in the bestiary, F6)."""
    return (1 if short else 2) + ("lorekeeper" in state.player.blessings)


def monster_how(state: GameState, key: str) -> Text:
    """How a monster is, in a line (empty for a plain fight, or once it's gone): calm, stunned, winding up a heavy
    blow, guarding."""
    monster = state.room.monster
    if monster is None or monster.key != key:
        return Text()
    if not monster.hostile:
        return Text("calm", style="bold #4cff8a")
    if monster.stunned:
        return Text("★ STUNNED", style="bold #ffd166")
    if monster.intent == "heavy":  # (the sidebar's 27 columns, to the letter)
        return Text("⚠ HEAVY ATTACK NEXT · dodge", style="bold #ffb000 reverse")
    if monster.guarding:
        return Text("⛨ guarding (+4 defense)", style="bold #6c8cff")
    return Text()


def monster_status(state: GameState, content: Content, key: str, short: bool = False) -> Text:
    """What's under a monster's portrait in the sidebar: its HP, how it is (see monster_how; left out when it's `short`,
    for a sidebar with no row to spare, which shows that on its frame) and maybe what it's weak to, a line each and
    always status_rows of them, whatever it's doing or once it's gone: a fight's flashes and its death go by with the
    panel holding still. Pass the key of the monster pictured: one no longer here is 0 HP."""
    monster = state.room.monster
    hp, max_hp = (monster.hp, monster.max_hp) if monster and monster.key == key else (0, content.monster(key).hp)
    lines = [Text.assemble((bar(hp, max_hp, 18), "#ff4b4b"), f" {max(0, hp)}/{max_hp}")]
    if not short:
        lines.append(monster_how(state, key))
    if "lorekeeper" in state.player.blessings:
        known = state.known_weak.get(key, [])
        lines.append(Text("weak to: " + ", ".join(known), style="#5fe3ff") if known else Text())
    return Text("\n", no_wrap=True, overflow="ellipsis").join(lines)


class ChoiceItem(Static):
    class Chosen(Message):
        def __init__(self, index: int, action_id: str) -> None:
            self.index = index
            self.action_id = action_id
            super().__init__()

    def __init__(self, index: int, action: Action) -> None:
        text = Text(f"{index}. ", style="bold #ffb000")
        if action.id.startswith("go:"):
            text.append(ARROWS.get(action.id[3:], "·") + " ", style="bold #5fe3ff")
        if action.id == "suggest":
            text.append(action.label, style="italic #ff4f9a")
        elif action.id.startswith("perk:"):
            text.append(action.label, style="bold #ffd166")
        else:
            text.append(action.label)
        if action.hint:
            hint_style = "bold #ffb000" if "!" in action.hint else "#6c6f99"
            text.append(f"  [{action.hint}]", style=hint_style)
        super().__init__(text, classes="choice")
        self.index = index
        self.action_id = action.id
        if len(text.plain) > 56:  # a long one may be cut short in its row: hovering shows all of it
            self.tooltip = text.plain

    def on_click(self) -> None:
        self.post_message(self.Chosen(self.index, self.action_id))


ARROWS = {"north": "▲", "south": "▼", "east": "▶", "west": "◀"}
# A way out on the pad, by its choice's hint: open, a fixture ahead, danger, locked (no key for it: see
# rules.locked_doors), or a door you have the key to.
WAY_STYLES = {"": "bold #5fe3ff", "danger": "bold #ff4b4b", "locked": "#7a3b4c", "a locked shop": "#7a3b4c",
              "boss": "bold #ff4f9a"}
NO_WAY = "#2e3149"


class DPad(Vertical):
    """The ways out of the room as a pad of arrows, lit where there's a door: click one to go that way. Hovering an
    arrow says where it leads, as its choice does."""

    def compose(self) -> ComposeResult:
        for row in (("", "north", ""), ("west", "@", "east"), ("", "south", "")):
            with Horizontal(classes="dpad-row"):
                for cell in row:
                    if cell in ARROWS:
                        yield Clickable(Text(""), f"screen.go('{cell}')", id=f"dpad-{cell}", classes="dpad-key")
                    else:
                        yield Static(Text(cell, style="bold #ffffff"), classes="dpad-gap")

    def show(self, actions: list[Action], locked: list[Action] | None = None) -> None:
        """Light the arrows for the choices' ways out, and dimly for the `locked` doors (as the map shows them)."""
        ways = {a.id[3:]: a for a in [*(locked or []), *actions] if a.id.startswith("go:")}
        for direction, arrow in ARROWS.items():
            key = self.query_one(f"#dpad-{direction}", Clickable)
            way = ways.get(direction)
            style = NO_WAY if way is None else WAY_STYLES.get(way.hint, "bold #ffd166")  # else: a fixture ahead
            key.update(Text(arrow, style=style))
            key.set_class(way is None, "off")
            key.tooltip = None if way is None else way.label + (f"  [{way.hint}]" if way.hint else "")


class ClickableBox(Vertical):
    """A card in the story that runs an action when clicked anywhere on it, such as
    "screen.lookup('item:healing_potion')" to show what's pictured on it."""

    def __init__(self, *children, action: str, **kwargs) -> None:
        super().__init__(*children, **kwargs)
        self.action = action

    async def on_click(self, event: Click) -> None:
        event.stop()
        await self.run_action(self.action)


ITEM_COLORS = {"weapon": "#c8c8e0", "armor": "#8fa8ff", "consumable": "#ff4b4b", "trinket": "#ffb000", "key": "#ffd166"}


def item_note(content: Content, key: str) -> str:
    """What an item does, in a few words: "1d8 damage", "+2 defense", "heals 8", "+1 every roll". A curse comes
    first: "cursed! · +2 dodge & flee"."""
    item = content.item(key)
    if key in powers.PICKED_UP:
        return powers.PICKED_UP[key]
    curse = "cursed! · " if "cursed" in item.powers else ""
    shown = [p for p in item.powers if p != "cursed"]
    if item.kind == "trinket" and shown:
        return curse + powers.SHORT[shown[0]] + (f" ({item.damage})" if shown[0] == "throw" else "")
    return curse + {"weapon": f"{item.damage} damage", "armor": f"+{item.defense} defense", "key": "a key",
                    "consumable": "escape a fight" if item.escape else f"heals {item.heal}",
                    "trinket": "trinket"}[item.kind]


def power_lines(content: Content, key: str) -> Text:
    """What an item's powers do, a line each, for its card."""
    text = Text()
    for line in powers.describe(content.item(key)):
        text.append(f"◆ {line}\n", style="bold #ffd166")
    return text


# "No picture yet": a plain grey icon for each kind of item (see loot.role), for items nobody has drawn.
BLANKS = {
    "weapon": [
        "...........c",
        "..........cb",
        ".........cb.",
        "........cb..",
        ".......cb...",
        "..b...cb....",
        "...b.cb.....",
        "....bb......",
        "...a.b......",
        "..a...b.....",
        ".a..........",
        "............",
    ],
    "armor": [
        "............",
        "...bb..bb...",
        "..bcbbbbcb..",
        ".bccccccccb.",
        ".bbccccccbb.",
        "..bccccccb..",
        "..bccccccb..",
        "..bccccccb..",
        "..bccccccb..",
        "..bbbbbbbb..",
        "............",
        "............",
    ],
    "potion": [
        "............",
        ".....aa.....",
        ".....bb.....",
        "....bccb....",
        ".....cc.....",
        "....bccb....",
        "...bccccb...",
        "..bccccccb..",
        "..bccccccb..",
        "..bbccccbb..",
        "...bbbbbb...",
        "............",
    ],
    "food": [
        "............",
        "............",
        "............",
        "....bbbb....",
        "..bbccccbb..",
        ".bccccccccb.",
        ".bcbccbccbb.",
        ".bccccccccb.",
        ".abbbbbbbba.",
        "..aaaaaaaa..",
        "............",
        "............",
    ],
    "escape": [
        "..........c.",
        ".........c..",
        "........b...",
        "......bb....",
        "....bbbbb...",
        "...bccbbbb..",
        "...bcbbbbb..",
        "...bbbbbbb..",
        "...abbbbba..",
        "....aaaaa...",
        "............",
        "............",
    ],
    "trinket": [
        "............",
        "...bbbbbb...",
        "..b......b..",
        "..b......b..",
        "...b....b...",
        "....b..b....",
        ".....bb.....",
        "....bccb....",
        "....bccb....",
        ".....bb.....",
        "............",
        "............",
    ],
    "key": [
        "............",
        "............",
        "............",
        "..bbb.......",
        ".bc..b......",
        ".b...bbbbbbb",
        ".b...b..b.b.",
        "..bbb...b.b.",
        "............",
        "............",
        "............",
        "............",
    ],
}
SHADES = {"a": GREYS[1], "b": GREYS[2], "c": GREYS[3]}


@lru_cache(maxsize=32)
def blank_art(role: str, width: int = SMALL) -> Text | None:
    """The grey stand-in for an item with no art, `width` pixels wide (whole multiples of 12 stay crisp)."""
    if Image is None:
        return None
    img = Image.new("RGBA", (12, 12), (0, 0, 0, 0))
    for y, row in enumerate(BLANKS.get(role, BLANKS["trinket"])):
        for x, ch in enumerate(row):
            if ch != ".":
                img.putpixel((x, y), (*SHADES[ch], 255))
    if width != 12:
        img = img.resize((width, width), Image.NEAREST)
    return image_text(img)


def item_words(content: Content, key: str, note: str, room: int = 16) -> Text:
    """What goes under an item's picture on its tile: its name, on up to two lines, and a short note (centre it with
    CSS)."""
    name = textwrap.wrap(content.item(key).name, room)
    if len(name) > 2:
        name = [name[0], textwrap.shorten(" ".join(name[1:]), room, placeholder="…")]
    out = Text()
    out.append("\n".join(name + [""] * (2 - len(name))), style="bold")
    out.append("\n" + (note if len(note) <= room else note[:room - 1] + "…"), style="#9a9cc0")
    return out


# --- pictures ------------------------------------------------------------------------------------------------------

IDLE = 0.6  # seconds a frame of an idle animation lasts, wherever it's shown: a monster breathing, an item bobbing, a
# shrine's candles flickering (see PictureClock)
FLICKER = 0.15  # seconds a frame lasts for the few things that move fast, the campfire's flames and the crown's glint,
# and the beat of the one clock every picture animates by
IDLE_BEATS = round(IDLE / FLICKER)


class Art(NamedTuple):
    """What a Picture draws (see art_for): a sprite, or else a still stand-in, and how big it is in cells."""

    sprite: str  # the sprite's key, or "" for a stand-in
    pixels: int  # how wide the sprite (or the grey stand-in) is drawn: DEFAULT_WIDTH, or SMALL when that won't fit
    still: Text | None  # with no sprite to draw: an item's grey stand-in, or the ASCII art
    columns: int
    rows: int
    blank: bool = False  # the grey stand-in for an item nobody has drawn yet


def art_for(key: str, kind: str = "", content: Content | None = None, max_w: int = DEFAULT_WIDTH,
            max_h: int | None = None, sprites: bool = True, ascii: Text | str | None = None,
            style: str = "#ff4b4b") -> Art:
    """What to draw for `key` in a space `max_w` columns wide and `max_h` rows tall (None: as tall as it likes).
    `kind` says what the key is: "item" (an item's key, whose sprite is item_<key>), "monster", or anything else
    ("fixture") for a sprite's own key: a fixture, the campfire, a story's sprite (given as "", one that's an item's or
    a monster's falls back as theirs do).

    Its sprite at full size (24 pixels wide) whenever that fits, else small (12): the hand-made small version, or the
    big one halved block by block. An item nobody has drawn gets the grey stand-in for its kind, at the same sizes.
    With sprites off (or no sprite and no stand-in), the ASCII art: `ascii` if it's given (a plain one in `style`),
    else a monster's own (in `style`), or an item's glyph in the middle of a space as tall as its picture would be."""
    if not key:  # nothing to show (yet)
        return Art("", DEFAULT_WIDTH, Text(), 0, 1)
    if not kind and content is not None:
        if key.startswith("item_") and key[5:] in content.items:
            kind, key = "item", key[5:]
        elif key in content.monsters:
            kind = "monster"
    name = f"item_{key}" if kind == "item" else key
    item = content.items.get(key) if kind == "item" and content is not None else None
    monster = content.monsters.get(key) if kind == "monster" and content is not None else None
    found = frames(name) if sprites else None
    if found:
        pixels = _fitting(found[0].height, max_w, max_h)
        img = found[0] if pixels == DEFAULT_WIDTH else frames(name, SMALL)[0]
        return Art(name, pixels, None, img.width, (img.height + 1) // 2)
    pixels = _fitting(DEFAULT_WIDTH, max_w, max_h)  # (item art is square)
    blank = blank_art(loot.role(item) if item else "trinket", pixels) if sprites and kind == "item" else None
    if blank is not None:
        return Art("", pixels, blank.copy(), pixels, pixels // 2, blank=True)
    if ascii is not None:
        still = ascii.copy() if isinstance(ascii, Text) else Text(ascii, style=style)
    elif monster is not None:
        still = Text(monster.art, style=style)
    elif kind == "item":
        rows = pixels // 2
        colour = ITEM_COLORS.get(item.kind, "") if item else ""
        glyph = layout.ITEM_GLYPHS.get(item.kind, "*") if item else "*"
        still = Text("\n" * (rows // 2) + glyph + "\n" * (rows - rows // 2 - 1), style=f"bold {colour}".strip())
    else:
        still = Text()
    lines = still.plain.split("\n")
    return Art("", pixels, still, max(map(cell_len, lines)), len(lines))


def _fitting(height: int, max_w: int, max_h: int | None) -> int:
    """How wide to draw a sprite `height` pixels tall at full size: full size if it fits the space, else small."""
    fits = max_w >= DEFAULT_WIDTH and (max_h is None or (height + 1) // 2 <= max_h)
    return DEFAULT_WIDTH if fits else SMALL


class PictureClock:
    """The one clock every Picture animates by, one to an app. While any picture has frames to show it beats, counting
    FLICKER seconds a beat, and each picture takes its next frame on its own beats (an idle one every IDLE seconds),
    only while it's in sight: on the screen in front, not scrolled away or hidden. So every idle animation keeps the
    same time, and the screen changes once a beat, not once a picture. It ticks only as often as it needs to: every
    IDLE seconds, unless a flame or a glint wants FLICKER."""

    clocks: WeakKeyDictionary[App, PictureClock] = WeakKeyDictionary()

    def __init__(self, app: App) -> None:
        self.app = app
        self.beat = 0
        self.pictures: set[Picture] = set()  # the ones animating
        self.timer: Timer | None = None
        self.interval = IDLE  # how often it ticks (a tick is IDLE_BEATS beats when nothing flickers)

    @classmethod
    def of(cls, app: App) -> PictureClock:
        if app not in cls.clocks:
            cls.clocks[app] = cls(app)
        return cls.clocks[app]

    def join(self, picture: Picture) -> None:
        self.pictures.add(picture)
        self._pace()

    def leave(self, picture: Picture) -> None:
        self.pictures.discard(picture)
        self._pace()

    def _pace(self) -> None:
        """Tick as often as the quickest picture needs, and not at all with nothing to move."""
        interval = FLICKER if any(picture.flicker for picture in self.pictures) else IDLE
        if self.timer is not None and (interval != self.interval or not self.pictures):
            self.timer.stop()
            self.timer = None
        if self.timer is None and self.pictures:
            self.interval = interval
            self.timer = self.app.set_interval(interval, self.tick, name="pictures")

    def tick(self) -> None:
        self.beat = self.beat + 1 if self.interval == FLICKER else (self.beat // IDLE_BEATS + 1) * IDLE_BEATS
        try:
            front = self.app.screen
        except ScreenStackError:
            return
        for picture in list(self.pictures):
            picture.step(self.beat, front)


class Picture(Static):
    """An item, a character or a fixture, drawn the same way wherever it's shown (see art_for for what it draws, and
    at what size). It's a picture on its own, never part of a run of text that wraps: a column too narrow for it
    crops it rather than shredding it. It keeps the height it was given, whatever it shows (a pose, a flash, a frame
    of a fight or a dissolve), so nothing around it moves; `cells` says how big it is.

    It animates on the app's one clock (PictureClock), only while it's in sight: `loop` is the frames its idle
    animation shows in turn (by default sprites.idle_frames), IDLE seconds each, or FLICKER for a flame or a glint.
    `pose` is how it stands (see sprites.posed); `play` runs a one-off sequence of frames at its own pace (a blow, a
    chest opening); `freeze` and `resume` stop and start the idle animation; `become` shows something else in its
    place and `fit` gives it another space to fit. `action`, if given, runs when it's clicked, such as
    "screen.lookup('item:healing_potion')" for its card. `sprites` is whether to draw sprites at all (by default, the
    player's choice in Settings)."""

    DEFAULT_CSS = """
    Picture {
        width: auto;
        max-width: 100%;
        text-wrap: nowrap;
        text-overflow: clip;
    }
    """

    def __init__(self, key: str, kind: str = "", max_w: int = DEFAULT_WIDTH, max_h: int | None = None,
                 pose: str = "idle", animate: bool = True, action: str | None = None, *,
                 content: Content | None = None, loop: list[int] | None = None, flicker: bool = False,
                 ascii: Text | str | None = None, style: str = "#ff4b4b", sprites: bool | None = None,
                 **kwargs) -> None:
        super().__init__(**kwargs)
        self.key, self.kind = key, kind
        self.data = content  # the game's Content: what an item or monster with no sprite falls back to
        self.max_w, self.max_h = max_w, max_h
        self.pose, self.action, self.flicker = pose, action, flicker
        self.animate = animate  # whether it's to animate at all
        self.animating = animate  # whether it is now (on the clock while there's more than one frame to show)
        self.chosen_loop, self.ascii, self.style = loop, ascii, style
        self.sprites = self._sprites_on() if sprites is None else sprites
        self.text = Text()
        self.placed = False  # mounted (is_mounted only comes true once on_mount is done)
        self._resolve()

    def _sprites_on(self) -> bool:
        """Sprites, unless the player has chosen ASCII art in Settings (or there's no game to ask: a test)."""
        try:
            config = getattr(self.app, "config", None)
        except NoActiveAppError:
            return True
        return getattr(config, "art", "sprites") == "sprites"

    def _resolve(self) -> None:
        """Work out what to draw, at what size (see art_for), from its first frame."""
        self.art = art_for(self.key, self.kind, self.data, self.max_w, self.max_h, self.sprites, self.ascii,
                           self.style)
        self.loop = list(self.chosen_loop or (idle_frames(self.art.sprite) if self.art.sprite else [0]))
        self.index = 0
        self.styles.height = self.art.rows
        self.update(self.frame_text(self.frame, self.pose))

    @property
    def frame(self) -> int:
        """The frame of its idle animation it's showing."""
        return self.loop[self.index % len(self.loop)]

    @property
    def cells(self) -> tuple[int, int]:
        """How big it is: (columns, rows)."""
        return self.art.columns, self.art.rows

    @property
    def blank(self) -> bool:
        """Whether it's the grey stand-in for an item nobody has drawn yet."""
        return self.art.blank

    def frame_text(self, frame: int, pose: str = "idle", flash: bool = False) -> Text:
        """One frame of it, in a pose (white all over for a flash), as text."""
        art = self.art
        if art.sprite:
            return sprite_text(art.sprite, frame, art.pixels, flash=flash, pose=pose) or Text()
        if flash and not art.blank:  # ASCII art can still flash when it's hit
            return Text(art.still.plain, style="bold #ffffff")
        return art.still.copy()

    # --- shown as a Static would show it, but drawn when it's rendered: it can be made before the app runs ---

    def render(self) -> Text:
        return self.text

    @property
    def content(self) -> Text:
        """The frame it's showing."""
        return self.text

    def update(self, content: Text | str = "", *, layout: bool = True) -> None:
        self.text = content if isinstance(content, Text) else Text(content)
        self.refresh(layout=layout)

    # --- animation ---

    def on_mount(self) -> None:
        self.placed = True
        self._clock()

    def on_unmount(self) -> None:
        self.placed = False
        PictureClock.of(self.app).leave(self)

    async def on_click(self, event: Click) -> None:
        if self.action:
            event.stop()
            await self.run_action(self.action)

    def _clock(self) -> None:
        """On the clock while it's animating and has more than one frame to show; off it otherwise."""
        if not self.placed:
            return  # (on_mount sees to it)
        clock = PictureClock.of(self.app)
        if self.animating and self.art.sprite and len(self.loop) > 1:
            clock.join(self)
        else:
            clock.leave(self)

    def step(self, beat: int, front: Screen) -> None:
        """A beat of the clock: its next idle frame, if this is one of its beats and it's in sight on `front`, the
        screen in front."""
        if beat % (1 if self.flicker else IDLE_BEATS):
            return
        try:
            in_sight = self.screen is front and front.can_view_partial(self)
        except NoScreen:
            in_sight = False
        if in_sight:
            self.index = (self.index + 1) % len(self.loop)
            self.update(self.frame_text(self.frame, self.pose), layout=False)

    def freeze(self, frame: int | None = None) -> None:
        """Stop animating: on the frame it's showing, or on `frame` (a chest emptied, a card taken)."""
        self.animating = False
        self._clock()
        if frame is not None:
            self.update(self.frame_text(frame, self.pose), layout=False)

    def resume(self) -> None:
        """Animate again (after play or freeze)."""
        self.animating = True
        self._clock()

    def set_pose(self, pose: str) -> None:
        """Stand another way from now on (a monster winding up a heavy blow, or stunned)."""
        if pose != self.pose:
            self.pose = pose
            self.update(self.frame_text(self.frame, pose), layout=False)

    async def play(self, steps: list[tuple[int, str, bool]], delay: float = 0.09) -> None:
        """Play a one-off sequence of (frame, pose, flash) steps at its own pace, `delay` seconds each, then stay on the
        last (resume() to go back to the idle animation)."""
        self.freeze()
        for frame, pose, flash in steps:
            self.update(self.frame_text(frame, pose, flash), layout=False)
            await asyncio.sleep(delay)

    def become(self, key: str, kind: str | None = None, pose: str = "idle", loop: list[int] | None = None,
               style: str | None = None, ascii: Text | str | None = None) -> None:
        """Show something else in its place (a panel's picture as you page through, the next monster in the sidebar),
        from its first frame, animating if it animates at all; `kind` and `style` stay as they were unless given. Its
        height is the new picture's."""
        self.key, self.pose, self.chosen_loop, self.ascii = key, pose, loop, ascii
        self.kind = self.kind if kind is None else kind
        self.style = self.style if style is None else style
        self.animating = self.animate
        self._resolve()
        self._clock()

    def fit(self, max_w: int, max_h: int | None = None) -> None:
        """Fit another space (the screen's been resized): full size or small, whichever fits it now."""
        if (max_w, max_h) == (self.max_w, self.max_h):
            return
        self.max_w, self.max_h = max_w, max_h
        size = art_for(self.key, self.kind, self.data, max_w, max_h, self.sprites, self.ascii, self.style).pixels
        if size != self.art.pixels:
            self._resolve()


class Clickable(Static):
    """Text that runs an action when clicked, such as "screen.reroll": a button for players on a mouse."""

    def __init__(self, text: Text | str, action: str, **kwargs) -> None:
        super().__init__(text, **kwargs)
        self.action = action

    async def on_click(self, event: Click) -> None:
        event.stop()
        await self.run_action(self.action)


class DiceLine(Static):
    """A d20 that tumbles for a moment in the story log, then shows the result."""

    async def play(self, event: Event, fast: bool = False) -> None:
        roll = event.dice
        sound.play("dice_small")
        frames = 4 if fast else 7
        for i in range(frames):
            face = random.randint(1, 20)
            spin = Text("  ⚄ ", style="#6c6f99")
            spin.append(f"{roll.label}: rolling d20 … ", style="#9a9cc0")
            spin.append(f"[{face:>2}]", style="bold #ffd166" if roll.actor == "player" else "bold #ff7b7b")
            self.update(spin)
            await asyncio.sleep(0.03 + i * 0.012)
        self.update(roll_text(event))
        effects.flash(self, tone(event))
        sound.play(effects.roll_sound(event))
