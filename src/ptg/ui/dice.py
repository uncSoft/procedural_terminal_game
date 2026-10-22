"""The big dice moment, Baldur's Gate 3 style: you press Space (or click), the d20 tumbles and lands, the bonuses
add up one at a time, and the result is stamped in the colour of how it went. A failed check can be rerolled with
a Fate token."""

from __future__ import annotations

import asyncio
import random

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.events import Click
from textual.screen import ModalScreen
from textual.widgets import Static

from ..dice import Roll
from ..dice_art import CRIMSON, GOLD, d20
from ..outcome import AWFUL, BAD, GOOD, GREAT, NEUTRAL
from ..sprites import side_by_side
from . import effects
from .widgets import Clickable

VERDICTS = {GREAT: "★  CRITICAL SUCCESS  ★", GOOD: "✔  SUCCESS", NEUTRAL: "•  {word}", BAD: "✘  FAILURE",
            AWFUL: "✖  CRITICAL FAIL  ✖"}


def dice_row(values: list[int | None], turn: int | None = None, bounce: int = 0, glows: list | None = None,
             dims: list[bool] | None = None) -> Text:
    """One or two pixel d20s side by side. While they tumble (`turn` given) each turns out of step with the
    other; once they land they sit upright."""
    glows = glows or [None] * len(values)
    dims = dims or [False] * len(values)
    turns = [0 if turn is None else (turn + i) % 4 for i in range(len(values))]
    return side_by_side([d20(v, t, bounce, g, d) for v, t, g, d in zip(values, turns, glows, dims)], gap=2)


class DiceScreen(ModalScreen[str]):
    """Returns "reroll" or "accept". On a mouse: click anywhere to roll, and again to carry on."""

    BINDINGS = [
        Binding("space,enter", "advance", "Roll / continue", show=True),
        Binding("f", "reroll", "Spend Fate", show=False),
        Binding("escape", "accept", "Accept", show=False),
    ]

    def __init__(self, roll: Roll, summary: str, fate: int, can_reroll: bool, auto: bool = False,
                 tone: str | None = None, word: str = "") -> None:
        super().__init__()
        self.roll = roll
        self.tone = tone or (GREAT if roll.crit else AWFUL if roll.fumble else GOOD if roll.success else BAD)
        self.word = word
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
            with Center():
                yield Clickable("", action="screen.reroll", id="dice-fate")  # shown when a failed roll can be rerolled
            yield Static(Text(f"[space] or click to roll the dice   {hint}", style="#ffb000"), id="dice-prompt")

    def _idle_faces(self) -> Text:
        return dice_row([None] * len(self.roll.dice))

    def on_mount(self) -> None:
        if self.auto:
            self.action_advance()

    def on_click(self, event: Click) -> None:
        self.action_advance()

    def action_advance(self) -> None:
        if self.stage == "ready":
            self.stage = "rolling"
            self.animate_roll()
        elif self.stage == "done":
            self._close("accept")

    def action_reroll(self) -> None:
        if self.stage == "done" and self.can_reroll and not self.roll.success:
            self._close("reroll")

    def action_accept(self) -> None:
        if self.stage == "done":
            self._close("accept")

    def _close(self, result: str) -> None:
        self.stage = "closed"  # so a double click can't dismiss twice
        self.dismiss(result)

    @work(exclusive=True)
    async def animate_roll(self) -> None:
        roll = self.roll
        dice_widget = self.query_one("#dice-faces", Static)
        count = len(roll.dice)
        # Tumble: turn, bounce and flicker through numbers, slowing down like a real die.
        for i in range(14):
            values = [random.randint(1, 20) for _ in range(count)]
            bounce = (2, 0, 1, 0)[i % 4] if i < 10 else 0
            dice_widget.update(dice_row(values, turn=i, bounce=bounce))
            await asyncio.sleep(0.03 + i * 0.012)
        kept_index = roll.dice.index(roll.kept)
        glows = [None] * count
        if roll.crit:
            glows[kept_index] = GOLD
        elif roll.fumble:
            glows[kept_index] = CRIMSON
        dims = [i != kept_index for i in range(count)]  # with advantage, the die you don't keep greys out
        dice_widget.update(dice_row(list(roll.dice), glows=glows, dims=dims))
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

        # The verdict, in the colour of how it went for you; the kept die lights up to match.
        how = self.tone
        verdict = self.query_one("#dice-verdict", Static)
        box = self.query_one("#dice-box")
        big = how in (GREAT, AWFUL)
        verdict.update(Text(VERDICTS[how].format(word=self.word or "NOTHING SPECIAL"),
                            style=f"bold {'reverse ' if big else ''}{effects.COLORS[how]}"))
        box.add_class(f"tone-{how}")
        glows[kept_index] = effects.rgb(how)
        dice_widget.update(dice_row(list(roll.dice), glows=glows, dims=dims))
        effects.flash(verdict, how)
        if big:
            await self._shake(box)

        prompt = Text()
        if not roll.success and self.can_reroll:
            fate = self.query_one("#dice-fate", Clickable)
            fate.update(Text(f" ✦ Spend Fate to reroll ({self.fate} left) ", style="bold #10122a on #ffd166"))
            fate.display = True
            prompt.append("[f] reroll     [enter] or click anywhere to accept", style="#9a9cc0")
        else:
            prompt.append("[enter] or click to continue", style="#9a9cc0")
        self.query_one("#dice-prompt", Static).update(prompt)
        self.stage = "done"

    @staticmethod
    async def _shake(widget) -> None:
        for dx in (2, -2, 1, -1, 0):
            widget.styles.offset = (dx, 0)
            await asyncio.sleep(0.04)
