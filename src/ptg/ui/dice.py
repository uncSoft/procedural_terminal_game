"""The big dice moment, Baldur's Gate 3 style: you press Space, the d20 tumbles and lands, the bonuses add up
one at a time, and the result is stamped. A failed check can be rerolled with a Fate token."""

from __future__ import annotations

import asyncio
import random

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from ..dice import Roll


def d20_face(value: str, style: str) -> Text:
    """A d20 drawn as a triangle face, 5 lines tall."""
    value = value.center(3)
    lines = ["    /\\    ", "   /  \\   ", f"  / {value}\\  ", " /______\\ ", "          "]
    text = Text()
    for line in lines:
        text.append(line + "\n", style=style)
    return text


def faces(values: list[str], styles: list[str]) -> Text:
    """Several dice side by side."""
    rendered = [d20_face(v, s).split("\n") for v, s in zip(values, styles)]
    text = Text()
    for row in range(5):
        for i, die in enumerate(rendered):
            text.append_text(die[row])
            if i < len(rendered) - 1:
                text.append("   ")
        text.append("\n")
    return text


class DiceScreen(ModalScreen[str]):
    """Returns "reroll" or "accept"."""

    BINDINGS = [
        Binding("space,enter", "advance", "Roll / continue", show=True),
        Binding("f", "reroll", "Spend Fate", show=False),
        Binding("escape", "accept", "Accept", show=False),
    ]

    def __init__(self, roll: Roll, summary: str, fate: int, can_reroll: bool, auto: bool = False) -> None:
        super().__init__()
        self.roll = roll
        self.summary = summary
        self.fate = fate
        self.can_reroll = can_reroll
        self.auto = auto
        self.stage = "ready"  # ready -> rolling -> done

    def compose(self) -> ComposeResult:
        with Vertical(id="dice-box") as box:
            box.border_title = f"{self.roll.label.upper()} CHECK"
            yield Static(Text(self.summary, style="italic #c8c8e0"), id="dice-summary")
            yield Static(self._idle_faces(), id="dice-faces")
            target = "IMPOSSIBLE" if self.roll.impossible else f"needs {self.roll.dc}"
            yield Static(Text(target, style="bold #9a9cc0"), id="dice-target")
            yield Static("", id="dice-bonuses")
            yield Static("", id="dice-verdict")
            hint = "two dice: keep the best" if self.roll.advantage > 0 else ""
            yield Static(Text(f"[space] roll the dice   {hint}", style="#ffb000"), id="dice-prompt")

    def _idle_faces(self) -> Text:
        count = len(self.roll.dice)
        return faces(["?"] * count, ["bold #6c8cff"] * count)

    def on_mount(self) -> None:
        if self.auto:
            self.action_advance()

    def action_advance(self) -> None:
        if self.stage == "ready":
            self.stage = "rolling"
            self.animate_roll()
        elif self.stage == "done":
            self.dismiss("accept")

    def action_reroll(self) -> None:
        if self.stage == "done" and self.can_reroll and not self.roll.success:
            self.dismiss("reroll")

    def action_accept(self) -> None:
        if self.stage == "done":
            self.dismiss("accept")

    @work(exclusive=True)
    async def animate_roll(self) -> None:
        roll = self.roll
        dice_widget = self.query_one("#dice-faces", Static)
        count = len(roll.dice)
        # Tumble, slowing down like a real die.
        for i in range(14):
            values = [str(random.randint(1, 20)) for _ in range(count)]
            dice_widget.update(faces(values, ["bold #ffd166"] * count))
            await asyncio.sleep(0.025 + i * 0.012)
        styles = []
        for value in roll.dice:
            kept = value == roll.kept
            if roll.crit and kept:
                styles.append("bold #ffd166")
            elif roll.fumble and kept:
                styles.append("bold #ff4b4b")
            else:
                styles.append("bold #ffffff" if kept else "#4a4a66")
        dice_widget.update(faces([str(v) for v in roll.dice], styles))
        await asyncio.sleep(0.25)

        bonus_widget = self.query_one("#dice-bonuses", Static)
        total = roll.kept
        line = Text(f"d20 {roll.kept}", style="bold")
        bonus_widget.update(line)
        for name, value in roll.bonuses:
            await asyncio.sleep(0.22)
            total += value
            line.append(f"  {'+' if value >= 0 else '-'} {abs(value)} ", style="bold #4cff8a" if value > 0 else "#ff7b7b")
            line.append(name, style="#ff4f9a" if name.startswith("✦") else "#9a9cc0")
            bonus_widget.update(line)
        await asyncio.sleep(0.2)
        line.append("  =  ", style="#6c6f99")
        line.append(str(total), style="bold #ffffff")
        bonus_widget.update(line)
        await asyncio.sleep(0.25)

        verdict = self.query_one("#dice-verdict", Static)
        box = self.query_one("#dice-box")
        if roll.crit:
            verdict.update(Text("★  CRITICAL SUCCESS  ★", style="bold reverse #ffd166"))
            box.add_class("crit")
            await self._shake(box)
        elif roll.fumble:
            verdict.update(Text("✖  CRITICAL FAIL  ✖", style="bold reverse #ff4b4b"))
            box.add_class("fumble")
            await self._shake(box)
        elif roll.success:
            verdict.update(Text("✔  SUCCESS", style="bold #4cff8a"))
            box.add_class("success")
        else:
            verdict.update(Text("✘  FAILURE", style="bold #ff4b4b"))
            box.add_class("failure")

        prompt = Text()
        if not roll.success and self.can_reroll:
            prompt.append(f"[f] spend Fate to reroll ({self.fate} left)", style="bold #ffd166")
            prompt.append("     [enter] accept", style="#9a9cc0")
        else:
            prompt.append("[enter] continue", style="#9a9cc0")
        self.query_one("#dice-prompt", Static).update(prompt)
        self.stage = "done"

    @staticmethod
    async def _shake(widget) -> None:
        for dx in (2, -2, 1, -1, 0):
            widget.styles.offset = (dx, 0)
            await asyncio.sleep(0.04)
