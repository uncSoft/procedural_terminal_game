"""Reusable pieces of the game screen: the HUD, room view, monster card, choice list and inline dice."""

from __future__ import annotations

import asyncio
import random
import textwrap
from functools import lru_cache

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Click, Leave, MouseMove
from textual.message import Message
from textual.widgets import Static

from .. import layout, loot, powers, sound
from ..content import Content
from ..events import Action, Event
from ..glossary import Lexicon
from ..models import LEVEL_XP, GameState
from ..outcome import tone, verdict
from ..sprites import DEFAULT_WIDTH, GREYS, SMALL, Image, frame_count, image_text, sprite_text
from ..world import render_map
from . import effects
from .theme import CELL_STYLES, MAP_STYLES


TERM_STYLES = {
    "monster": "bold #ff4b4b", "item": "bold #4cff8a", "feature": "bold #ffb000",
    "fixture": "bold #ff4f9a", "room": "#8fa8ff", "rule": "bold #5fe3ff",
}


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


def hearts(hp: int, max_hp: int) -> Text:
    """Tiny Rogues style: a heart per 5 HP."""
    text = Text()
    for i in range(0, max_hp, 5):
        chunk = hp - i
        if chunk >= 5:
            text.append("♥", style="bold #ff4b4b")
        elif chunk > 0:
            text.append("♥", style="#8a2a3a")
        else:
            text.append("♡", style="#4a3040")
    return text


def roll_text(event: Event) -> Text:
    """A finished roll for the story log: the sum, then a coloured badge saying how it went for you."""
    roll, how = event.dice, tone(event)
    text = Text("  ⚄ ", style=effects.COLORS[how])
    text.append(roll.describe(verdict=False), style="#c8c8e0" if roll.actor == "player" else "#9a9cc0")
    text.append("  ")
    text.append_text(effects.badge(how, verdict(event)))
    return text


class Hud(Static):
    """The top status bar: hearts, defense, Fate, gold, souls, bombs and small keys, the boss key, XP and floor."""

    def show(self, state: GameState, content: Content) -> None:
        player = state.player
        text = hearts(player.hp, player.max_hp)
        text.append(f" {player.hp}/{player.max_hp}", style="bold")
        text.append("   ⛨ ", style="#6c8cff")
        text.append(str(player.defense(content)))
        text.append("   ")
        for i in range(player.max_fate()):
            text.append("✦" if i < player.fate else "✧", style="bold #ffd166" if i < player.fate else "#5a5030")
        text.append("   ¤ ", style="#ffb000")
        text.append(str(player.gold))
        text.append("   ☽ ", style="#5fe3ff")
        text.append(str(state.souls))
        text.append("   ● ", style="#ff7b39")
        text.append(str(player.bombs))
        text.append("   ⚷ ", style="#c0cbdc")
        text.append(str(player.keys))
        if content.themes[state.theme].key_item in player.inventory:
            text.append("   ♀ key", style="bold #ffb000")
        next_xp = player.next_level_xp()
        text.append(f"   Lv {player.level} ", style="bold #ff4f9a")
        if next_xp:
            prev = LEVEL_XP[player.level - 1]
            text.append(bar(player.xp - prev, next_xp - prev, 8), style="#ff4f9a")
        theme = content.themes[state.theme]
        text.append(f"   Floor {state.floor}/{state.floors_total} · {theme.name}", style="bold #6c8cff")
        text.append(f"   turn {state.turn}", style="#6c6f99")
        if state.daily:
            text.append(f"   DAILY {state.daily}", style="bold #ff4f9a")
        self.update(text)


def room_text(state: GameState, content: Content, legend: bool = True) -> Text:
    rows, items = layout.render(state, content)
    text = Text()
    for row in rows:
        for glyph, style in row:
            text.append(glyph, style=CELL_STYLES.get(style, ""))
        text.append("\n")
    if legend:
        for glyph, style, label in items:
            text.append(f"{glyph}", style=CELL_STYLES.get(style, ""))
            text.append(f" {label}  ", style="#9a9cc0")
    return text


def map_text(state: GameState) -> Text:
    text = Text()
    lines = render_map(state)
    for line in lines:
        for ch in line:
            text.append(ch, style=MAP_STYLES.get(ch, "#6c6f99"))
        text.append("\n")
    text.append("@ you ! foe ? unknown\n> stairs † shrine ■ chest ◊ fountain = locked", style="#6c6f99")
    found = [(glyph, label, style) for mark, glyph, label, style in
             (("{", "{✧}", "secret room", "$"), ("$", "$", "a tip", "$"), ("¤", "¤", "shop", "¤"))
             if any(mark in line for line in lines)]
    for i, (glyph, label, style) in enumerate(found):
        text.append("\n" if i == 0 else "  ")
        text.append(glyph, style=MAP_STYLES[style])
        text.append(f" {label}", style="#6c6f99")
    return text


def portrait(key: str, content: Content, sprites: bool = True, frame: int = 0, flash: bool = False,
             style: str = "#ff4b4b", pose: str = "idle") -> Text:
    """A monster's pixel sprite (in a pose), or its ASCII art when sprites are off or missing."""
    art = sprite_text(key, frame, flash=flash, pose=pose) if sprites else None
    if art is None:
        art = Text(content.monster(key).art, style="bold #ffffff" if flash else style)
    return art


def monster_pose(monster) -> str:
    """How a monster stands right now: the sprite shows its state at a glance."""
    if not monster.hostile:
        return "calm"
    if monster.stunned:
        return "dizzy"
    if monster.intent == "heavy":
        return "windup"
    return "idle"


def monster_text(state: GameState, content: Content, sprites: bool = True, frame: int = 0,
                 flash: bool = False) -> Text:
    monster = state.room.monster
    text = portrait(monster.key, content, sprites, frame, flash, "#ff4b4b" if monster.hostile else "#ffd166",
                    pose=monster_pose(monster))
    text.append("\n")
    text.append(bar(monster.hp, monster.max_hp, 18), style="#ff4b4b")
    text.append(f" {max(0, monster.hp)}/{monster.max_hp}\n")
    if not monster.hostile:
        text.append("calm\n", style="bold #4cff8a")
    elif monster.stunned:
        text.append("★ STUNNED\n", style="bold #ffd166")
    elif monster.intent == "heavy":
        text.append("⚠ HEAVY ATTACK NEXT · dodge!\n", style="bold #ffb000 reverse")
    elif monster.guarding:
        text.append("⛨ guarding (+4 defense)\n", style="bold #6c8cff")
    known = state.known_weak.get(monster.key, [])
    if known and "lorekeeper" in state.player.blessings:  # otherwise look it up in the bestiary (F6)
        text.append("weak to: " + ", ".join(known), style="#5fe3ff")
    return text


class ChoiceItem(Static):
    class Chosen(Message):
        def __init__(self, index: int) -> None:
            self.index = index
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
        if len(text.plain) > 56:  # a long one may be cut short in its row: hovering shows all of it
            self.tooltip = text.plain

    def on_click(self) -> None:
        self.post_message(self.Chosen(self.index))


ARROWS = {"north": "▲", "south": "▼", "east": "▶", "west": "◀"}
# A way out on the pad, by its choice's hint: open, a fixture ahead, danger, locked, or a door you have the key to.
WAY_STYLES = {"": "bold #5fe3ff", "danger": "bold #ff4b4b", "locked": "#7a3b4c", "boss": "bold #ff4f9a"}
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

    def show(self, actions: list[Action]) -> None:
        ways = {a.id[3:]: a for a in actions if a.id.startswith("go:")}
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


class AnimatedSprite(Static):
    """A sprite that animates where it stands: in the story, or on a story card. `loop` picks which frames its
    idle animation cycles through (all of them by default); `action`, if given, runs when it's clicked (such as
    "screen.lookup('fixture:chest')", for its card)."""

    def __init__(self, key: str, interval: float = 0.25, loop: list[int] | None = None, width: int = DEFAULT_WIDTH,
                 action: str | None = None, **kwargs) -> None:
        self.key = key
        self.interval = interval
        self.width = width
        self.loop = loop or list(range(max(1, frame_count(key))))
        self.index = 0
        self._timer = None
        self.action = action
        super().__init__(sprite_text(key, self.loop[0], width) or Text(""), **kwargs)

    def on_mount(self) -> None:
        self.resume()

    async def on_click(self, event: Click) -> None:
        if self.action:
            event.stop()
            await self.run_action(self.action)

    def resume(self) -> None:
        """Animate again (after a play())."""
        if self._timer is None and len(self.loop) > 1:
            self._timer = self.set_interval(self.interval, self._tick)

    def become(self, key: str) -> None:
        """Show another sprite instead (a panel's picture as you page through), animating all its frames."""
        self.freeze()
        self.key, self.index = key, 0
        self.loop = list(range(max(1, frame_count(key))))
        self.update(sprite_text(key, self.loop[0], self.width) or Text(""))
        if self.is_mounted:
            self.resume()

    def _tick(self) -> None:
        self.index = (self.index + 1) % len(self.loop)
        self.update(sprite_text(self.key, self.loop[self.index], self.width) or Text(""))

    def freeze(self, frame: int | None = None) -> None:
        """Stop animating (older story sprites stand still so the newest one draws the eye)."""
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        if frame is not None:
            self.update(sprite_text(self.key, frame, self.width) or Text(""))

    async def play(self, steps: list[tuple[int, str, bool]], delay: float = 0.09) -> None:
        """Play a one-off sequence of (frame, pose, flash) steps, then stop on the last one."""
        self.freeze()
        for frame, pose, flash in steps:
            self.update(sprite_text(self.key, frame, self.width, flash=flash, pose=pose) or Text(""))
            await asyncio.sleep(delay)


ITEM_COLORS = {"weapon": "#c8c8e0", "armor": "#8fa8ff", "consumable": "#ff4b4b", "trinket": "#ffb000", "key": "#ffd166"}


def item_note(content: Content, key: str) -> str:
    """What an item does, in a few words: "1d8 damage", "+2 defense", "heals 8", "+1 every roll"."""
    item = content.item(key)
    if key in powers.PICKED_UP:
        return powers.PICKED_UP[key]
    if item.kind == "trinket" and item.powers:
        return powers.SHORT[item.powers[0]] + (f" ({item.damage})" if item.powers[0] == "throw" else "")
    return {"weapon": f"{item.damage} damage", "armor": f"+{item.defense} defense", "key": "a key",
            "consumable": "escape a fight" if item.escape else f"heals {item.heal}", "trinket": "trinket"}[item.kind]


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


def item_picture(content: Content, key: str, sprites: bool, width: int = SMALL) -> Text:
    """An item's art (its hand-made small version, at the small size); with no art, a grey stand-in for its kind;
    in ASCII mode, its glyph, as tall as the art would be."""
    item = content.item(key)
    art = (sprite_text(f"item_{key}", width=width) or blank_art(loot.role(item), width)) if sprites else None
    if art is not None:
        return art.copy()
    rows = width // 2  # two pixels to a row, and item art is square
    glyph = layout.ITEM_GLYPHS.get(item.kind, "*")
    return Text("\n" * (rows // 2) + glyph + "\n" * (rows - rows // 2 - 1), style=f"bold {ITEM_COLORS[item.kind]}")


def item_tile(content: Content, key: str, note: str, sprites: bool, room: int = 16) -> Text:
    """An item at a glance: its picture, its name (on up to two lines) and a short note (centre it with CSS)."""
    name = textwrap.wrap(content.item(key).name, room)
    if len(name) > 2:
        name = [name[0], textwrap.shorten(" ".join(name[1:]), room, placeholder="…")]
    out = Text()
    out.append_text(item_picture(content, key, sprites))  # its colour stays its own, not the name's
    out.append("\n" + "\n".join(name + [""] * (2 - len(name))), style="bold")
    out.append("\n" + (note if len(note) <= room else note[:room - 1] + "…"), style="#9a9cc0")
    return out


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
