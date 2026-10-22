"""Reusable pieces of the game screen: the HUD, room view, monster card, choice list and inline dice."""

from __future__ import annotations

import asyncio
import random

from rich.text import Text
from textual.message import Message
from textual.widgets import Static

from .. import layout
from ..content import Content
from ..dice import Roll
from ..events import Action
from ..models import LEVEL_XP, GameState
from ..world import render_map
from .theme import CELL_STYLES, MAP_STYLES


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


def roll_text(roll: Roll) -> Text:
    """A finished roll as a coloured line for the story log."""
    style = "bold #ffd166" if roll.crit else ("bold #ff4b4b" if roll.fumble else (
        "#4cff8a" if roll.success else "#ff7b7b"))
    if roll.actor == "monster":
        style = "#ff7b7b" if roll.success else "#7a7a99"
    text = Text("  ⚄ ", style="#6c6f99")
    text.append(roll.describe(), style=style)
    if roll.crit:
        text.append("  ★ CRITICAL!", style="bold #ffd166")
    elif roll.fumble:
        text.append("  ✖ FUMBLE", style="bold #ff4b4b")
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


def monster_text(state: GameState, content: Content) -> Text:
    monster = state.room.monster
    monster_def = content.monster(monster.key)
    text = Text(monster_def.art + "\n", style="#ff4b4b" if monster.hostile else "#ffd166")
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


class DiceLine(Static):
    """A d20 that tumbles for a moment in the story log, then shows the result."""

    async def play(self, roll: Roll, fast: bool = False) -> None:
        frames = 4 if fast else 7
        for i in range(frames):
            face = random.randint(1, 20)
            spin = Text("  ⚄ ", style="#6c6f99")
            spin.append(f"{roll.label}: rolling d20 … ", style="#9a9cc0")
            spin.append(f"[{face:>2}]", style="bold #ffd166" if roll.actor == "player" else "bold #ff7b7b")
            self.update(spin)
            await asyncio.sleep(0.03 + i * 0.012)
        self.update(roll_text(roll))
