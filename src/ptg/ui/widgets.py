"""Reusable pieces of the game screen: the HUD, room view, monster card, choice list and inline dice."""

from __future__ import annotations

import asyncio
import random

from rich.style import Style
from rich.text import Text
from textual.events import Click, Leave, MouseMove
from textual.message import Message
from textual.widgets import Static

from .. import layout
from ..content import Content
from ..events import Action, Event
from ..glossary import Lexicon
from ..models import LEVEL_XP, GameState
from ..outcome import tone, verdict
from ..sprites import frame_count, sprite_text
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
    """The top status bar: hearts, defense, Fate, gold, souls, keys, XP and floor."""

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
    for line in render_map(state):
        for ch in line:
            text.append(ch, style=MAP_STYLES.get(ch, "#6c6f99"))
        text.append("\n")
    text.append("@ you ! foe ? unknown\n> stairs † shrine ■ chest ◊ fountain = locked", style="#6c6f99")
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

    def on_click(self) -> None:
        self.post_message(self.Chosen(self.index))


class AnimatedSprite(Static):
    """A sprite that animates where it stands: in the story, or on a story card. `loop` picks which frames its
    idle animation cycles through (all of them by default)."""

    def __init__(self, key: str, interval: float = 0.25, loop: list[int] | None = None, **kwargs) -> None:
        self.key = key
        self.interval = interval
        self.loop = loop or list(range(max(1, frame_count(key))))
        self.index = 0
        self._timer = None
        super().__init__(sprite_text(key, self.loop[0]) or Text(""), **kwargs)

    def on_mount(self) -> None:
        if len(self.loop) > 1:
            self._timer = self.set_interval(self.interval, self._tick)

    def _tick(self) -> None:
        self.index = (self.index + 1) % len(self.loop)
        self.update(sprite_text(self.key, self.loop[self.index]) or Text(""))

    def freeze(self, frame: int | None = None) -> None:
        """Stop animating (older story sprites stand still so the newest one draws the eye)."""
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        if frame is not None:
            self.update(sprite_text(self.key, frame) or Text(""))

    async def play(self, steps: list[tuple[int, str, bool]], delay: float = 0.09) -> None:
        """Play a one-off sequence of (frame, pose, flash) steps, then stop on the last one."""
        self.freeze()
        for frame, pose, flash in steps:
            self.update(sprite_text(self.key, frame, flash=flash, pose=pose) or Text(""))
            await asyncio.sleep(delay)


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
