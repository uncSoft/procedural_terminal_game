"""The big dice moment, Baldur's Gate 3 style: you see what's at stake, you press Space (or click), the d20 tumbles and
lands, the bonuses add up one at a time, and the verdict is stamped in the colour of how it went. A failed check can
be rerolled with a Fate token.

On a big screen (ROOMY) it's a table of its own: the die, and beside it what you need (the target, big, in the die's
pixel letters), the odds ("roll 8 or better · 65%"), your bonuses and what a hit would deal; under them the die's
twenty faces in a row, the ones that would fail in red and the ones that would succeed in green (a 1 always fails, a
20 always succeeds), so the odds are plain before you roll; they flicker as it tumbles, and the face it lands on
lights up. Then the sum, the verdict in big letters, and what came of it. On a smaller screen the same, in a column:
the target a line, the verdict in words; on a tiny one, a smaller die and no row of faces; and on a short, wide one (a
phone on its side, 18 rows) the die on the left and the words beside it (SIDE).

The box keeps one size from the roll to the verdict (the verdict's rows and the Fate button's row are there from the
start, empty till they're wanted), and it fits the screen."""

from __future__ import annotations

import asyncio
import random

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical
from textual.events import Click
from textual.screen import ModalScreen
from textual.widgets import Static

from .. import sound
from ..dice import Roll
from ..dice_art import CRIMSON, GOLD, SIZE, SMALL_SIZE, d20, lettering, lettering_width
from ..outcome import AWFUL, BAD, GOOD, GREAT, NEUTRAL
from ..sprites import side_by_side
from . import effects
from .panels import ornate
from .widgets import TINY, Clickable

VERDICTS = {GREAT: "★  CRITICAL SUCCESS  ★", GOOD: "✔  SUCCESS", NEUTRAL: "•  {word}", BAD: "✘  FAILURE",
            AWFUL: "✖  CRITICAL FAIL  ✖"}
STAMPS = {GREAT: "CRITICAL!", AWFUL: "FUMBLE!", GOOD: "SUCCESS", BAD: "FAILURE", NEUTRAL: "NOTHING SPECIAL"}  # (the
# big letters, when the roll has no word of its own: a hit's HIT, a search's FOUND IT)
ROOMY = (110, 42)  # (columns, rows) from which the dice have a table of their own: the die and what's at stake beside it
BIG_LETTERS = 48  # rows from which the verdict's pixel letters are twice as big, and the die has room round it for a
BURST_ROOM = 4  # critical's burst of light, this many pixels
ROOMY_WIDTH = 112  # the most columns the box takes
SIDE = 80  # columns from which a short screen (a phone on its side) has the die on the left and the rest beside it
SIDE_WIDTH = 96  # the most columns the box takes then
# The die's twenty faces in a row (see faces_strip): each face's colour, by how it would go, and a dark of it under.
FACE_INKS = {"crit": ("#ffd166", "#3a3010"), "good": ("#4cff8a", "#12301e"), "bad": ("#ff4b4b", "#34151d"),
             "fumble": ("#ff2a6d", "#3a0f1e")}
WORDS, DIM, INK = "#e8e8f4", "#6c6f99", "#10122a"


def dice_row(values: list[int | None], turn: int | None = None, bounce: int = 0, glows: list | None = None,
             dims: list[bool] | None = None, size: int = SIZE, pad: int = 0, bursts: list[int] | None = None) -> Text:
    """One or two pixel d20s side by side, `size` pixels across (with `pad` pixels of room round each, for a
    critical's burst of light: `bursts`, each die's). While they tumble (`turn` given) each turns out of step with the
    other; once they land they sit upright."""
    glows = glows or [None] * len(values)
    dims = dims or [False] * len(values)
    bursts = bursts or [0] * len(values)
    turns = [0 if turn is None else (turn + i) % 4 for i in range(len(values))]
    return side_by_side([d20(v, t, bounce, g, d, size, pad, b)
                         for v, t, g, d, b in zip(values, turns, glows, dims, bursts)], gap=2)


def advantage_hint(roll) -> str:
    """What the two dice mean, said by the prompt: keep the best, keep the worst (and why, if a status did it: poison),
    or an advantage a status took away."""
    why = f" ({roll.hindered})" if roll.hindered else ""
    if roll.advantage > 0:
        return "two dice: keep the best"
    if roll.advantage < 0:
        return f"two dice: keep the worst{why}"
    return f"{roll.hindered}: your advantage is lost" if roll.hindered else ""


def face_kind(roll: Roll, face: int) -> str:
    """How the die showing `face` would go: "crit" (a 20), "fumble" (a 1), "good" or "bad"."""
    if roll.impossible:
        return "bad"
    return "crit" if face == 20 else "fumble" if face == 1 else "good" if face >= roll.needed else "bad"


def faces_strip(roll: Roll, cell: int, lit: tuple[int, ...] = (), landed: tuple[int, ...] = ()) -> Text:
    """The die's twenty faces in a row, `cell` columns each, in the colour of how each would go: red would fail,
    green would succeed, a 20 gold, a 1 crimson. `lit`, faces lit up (the tumbling die's); `landed`, where the dice
    came to rest, the one kept first: its face lit, a ▲ under it (a dim △ under the other of two)."""
    faces, marks = Text(no_wrap=True), Text(no_wrap=True)
    kept = landed[0] if landed else None
    for face in range(1, 21):
        ink, dark = FACE_INKS[face_kind(roll, face)]
        on = face in lit or face == kept
        faces.append(f"{face:^{cell}}", style=f"bold {INK} on {ink}" if on else f"{ink} on {dark}")
        mark = "▲" if face == kept else "△" if face in landed[1:] else " "
        marks.append(f"{mark:^{cell}}", style=f"bold {ink}" if face == kept else DIM)
        if face < 20:
            faces.append(" ")
            marks.append(" ")
    faces.append("\n")
    faces.append_text(marks)
    return faces


def odds_colour(chance: float) -> str:
    return "#4cff8a" if chance >= 0.65 else "#ffd166" if chance >= 0.35 else "#ff4b4b"


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
        self.die = SIZE  # how big the dice are drawn (smaller on a tiny screen: see compose)
        self.roomy = False  # a table of its own (see ROOMY)
        self.side = False  # the die on the left and the rest beside it (a short, wide screen: see SIDE)
        self.cell = 0  # the columns each face takes in the row of faces (0: no row)
        self.scale = 1  # how big the verdict's pixel letters are
        self.pad = 0  # the pixels of room round the die, for a critical's burst of light

    def compose(self) -> ComposeResult:
        width, height = self.app.size
        roll = self.roll
        self.die = SIZE if height >= TINY else SMALL_SIZE
        self.roomy = width >= ROOMY[0] and height >= ROOMY[1]
        self.scale = 2 if self.roomy and height >= BIG_LETTERS else 1
        self.pad = BURST_ROOM if self.scale == 2 else 0
        inner = (min(width - 8, ROOMY_WIDTH) if self.roomy else min(width, 76)) - 6  # (less its frame and padding)
        self.cell = 0 if height < TINY else min(4, (inner + 1) // 20 - 1)
        self.cell = self.cell if self.cell >= 2 else 0
        self.side = not self.roomy and height < TINY and width >= SIDE  # (a phone on its side: 18 rows don't hold it)
        with Vertical(id="dice-box", classes="roomy" if self.roomy else "side" if self.side else "") as box:
            box.border_title = ornate(f"{roll.label} check")
            if self.roomy:
                box.styles.width = min(width - 8, ROOMY_WIDTH)
            elif self.side:
                box.styles.width = min(width - 4, SIDE_WIDTH)
            yield Static(Text(self.summary, style="italic #c8c8e0"), id="dice-summary")
            if self.side:  # the die on the left, and what's at stake and what came of it beside it
                with Horizontal(id="dice-main"):
                    yield Static(self._idle_faces(), id="dice-faces")
                    with Vertical(id="dice-words"):
                        yield from self._words()
                return
            if self.roomy:
                with Horizontal(id="dice-main"):
                    yield Static(self._idle_faces(), id="dice-faces")
                    yield Static(self.stakes(), id="dice-stakes")
            else:
                yield Static(self._idle_faces(), id="dice-faces")
            yield from self._words()

    def _words(self) -> ComposeResult:
        """Everything but the die: the target in a line (beside the die on a big screen, it's its stakes), the faces in
        a row, the bonuses, the verdict, what a hit deals, the Fate button's row and how to go on."""
        roll = self.roll
        if not self.roomy:
            yield Static(self.target_line(), id="dice-target")
        if self.cell:
            yield Static(faces_strip(roll, self.cell), id="dice-strip")
        yield Static("", id="dice-bonuses")
        verdict = Static("", id="dice-verdict")
        if self.roomy:  # (its rows kept from the start, so the box doesn't grow when it's stamped)
            verdict.styles.height = (5 * self.scale + 2) // 2
        yield verdict
        if roll.hits_for or roll.effects:  # (its row kept from the start, so the box doesn't grow)
            yield Static(" ", id="dice-damage")
        with Center():  # (its row is kept for it: it shows when a failed roll can be rerolled)
            yield Clickable(Text(" "), action="screen.reroll", id="dice-fate")
        hint = advantage_hint(roll)
        yield Static(Text(f"[space] or click to roll the dice   {hint}".rstrip(), style="#ffb000"), id="dice-prompt")

    def target_line(self) -> Text:
        """What you need, in a line (a smaller screen's): the target, the odds, what a hit deals."""
        roll = self.roll
        if roll.impossible:
            return Text("IMPOSSIBLE", style="bold #ff4b4b")
        text = Text(f"needs {roll.dc}" + (" to hit" if roll.hits_for else ""), style="bold #9a9cc0")
        text.append(f"  ·  roll {roll.needed}+ (", style=DIM)
        text.append(f"{round(roll.chance * 100)}%", style=f"bold {odds_colour(roll.chance)}")
        text.append(")", style=DIM)
        if roll.hits_for:
            text.append(f"  ·  a hit deals {roll.hits_for}", style="bold #9a9cc0")
        return text

    def stakes(self) -> Text:
        """What's at stake, beside the die (a big screen's): what you need, big; the odds; your bonuses; what a hit
        deals; what two dice mean."""
        roll = self.roll
        text = Text("NEED", style=f"bold {DIM}")
        text.append("\n")
        if roll.impossible:
            text.append_text(lettering("NO", effects.rgb(BAD), 2, (35, 38, 74)))
            text.append("\n")
            text.append("it can't be done", style="bold #ff4b4b")
        else:
            text.append_text(lettering(str(roll.dc), (232, 232, 244), 2, (35, 38, 74)))
            text.append("\n")
            text.append("to hit · its defense" if roll.hits_for else "to succeed", style="bold #9a9cc0")
            text.append("\n\n")
            text.append(f"roll {roll.needed} or better" if roll.needed < 20 else "only a 20 will do",
                        style="#c8c8e0")
            text.append("  ·  ", style=DIM)
            text.append(f"{round(roll.chance * 100)}% chance", style=f"bold {odds_colour(roll.chance)}")
        if roll.bonuses:
            text.append("\n")
            for i, (name, value) in enumerate(roll.bonuses):
                colour = "#ff4f9a" if name.startswith("✦") else "#4cff8a" if value > 0 else "#ff7b7b"
                text.append(("  " if i else "") + f"{'+' if value >= 0 else '-'}{abs(value)} {name.lstrip('✦ ')}",
                            style=f"bold {colour}")
        if roll.hits_for and not roll.impossible:
            text.append(f"\na hit deals {roll.hits_for}", style="bold #ffb000")
        hint = advantage_hint(roll)
        if hint:
            text.append(f"\n{hint}", style="#6c8cff")
        return text

    def _idle_faces(self) -> Text:
        return dice_row([None] * len(self.roll.dice), size=self.die, pad=self.pad)

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

    def _strip(self, lit: tuple[int, ...] = (), landed: tuple[int, ...] = ()) -> None:
        if self.cell:
            self.query_one("#dice-strip", Static).update(faces_strip(self.roll, self.cell, lit, landed))

    @work(exclusive=True)
    async def animate_roll(self) -> None:
        roll = self.roll
        dice_widget = self.query_one("#dice-faces", Static)
        count = len(roll.dice)
        sound.play("dice_roll")
        # Tumble: turn, bounce and flicker through numbers, slowing down like a real die; the row of faces flickers
        # with it.
        for i in range(14):
            values = [random.randint(1, 20) for _ in range(count)]
            bounce = (2, 0, 1, 0)[i % 4] if i < 10 else 0
            dice_widget.update(dice_row(values, turn=i, bounce=bounce, size=self.die, pad=self.pad))
            self._strip(lit=tuple(values))
            await asyncio.sleep(0.03 + i * 0.012)
        kept_index = roll.dice.index(roll.kept)
        glows = [None] * count
        if roll.crit:
            glows[kept_index] = GOLD
        elif roll.fumble:
            glows[kept_index] = CRIMSON
        dims = [i != kept_index for i in range(count)]  # with advantage, the die you don't keep greys out
        dice_widget.update(dice_row(list(roll.dice), glows=glows, dims=dims, size=self.die, pad=self.pad))
        others = tuple(v for i, v in enumerate(roll.dice) if i != kept_index)
        self._strip(landed=(roll.kept, *others))
        sound.play("dice_land")
        await asyncio.sleep(0.25)

        bonus_widget = self.query_one("#dice-bonuses", Static)
        total = roll.kept
        line = Text(f"d20 {roll.kept}", style="bold")
        bonus_widget.update(line)
        for name, value in roll.bonuses:
            await asyncio.sleep(0.22)
            sound.play("dice_tick")
            total += value
            line.append(f"  {'+' if value >= 0 else '-'} {abs(value)} ", style="bold #4cff8a" if value > 0 else "#ff7b7b")
            line.append(name, style="#ff4f9a" if name.startswith("✦") else "#9a9cc0")
            bonus_widget.update(line)
        await asyncio.sleep(0.2)
        line.append("  =  ", style=DIM)
        line.append(str(total), style="bold #ffffff")
        if not roll.impossible:
            line.append(f"   vs {roll.dc}", style=f"bold {DIM}")
        bonus_widget.update(line)
        await asyncio.sleep(0.25)

        # The verdict, in the colour of how it went for you, stamped big on a big screen; the kept die lights up to
        # match.
        how = self.tone
        verdict = self.query_one("#dice-verdict", Static)
        box = self.query_one("#dice-box")
        big = how in (GREAT, AWFUL)
        if self.roomy:
            word = self.word if self.word and how not in (GREAT, AWFUL) else STAMPS[how]
            inner = box.content_region.width
            scale = self.scale if lettering_width(word, self.scale) <= inner else 1
            verdict.update(lettering(word, effects.rgb(how), scale, (16, 18, 42)))
        else:
            verdict.update(Text(VERDICTS[how].format(word=self.word or "NOTHING SPECIAL"),
                                style=f"bold {'reverse ' if big else ''}{effects.COLORS[how]}"))
        box.add_class(f"tone-{how}")
        glows[kept_index] = effects.rgb(how)
        dice_widget.update(dice_row(list(roll.dice), glows=glows, dims=dims, size=self.die, pad=self.pad))
        effects.flash(verdict, how)
        if how == GREAT and self.pad:  # (a critical: a burst of light round the die, spreading and glinting)
            for frame in (1, 2, 3, 2, 3):
                bursts = [frame if i == kept_index else 0 for i in range(count)]
                dice_widget.update(dice_row(list(roll.dice), glows=glows, dims=dims, size=self.die, pad=self.pad,
                                            bursts=bursts))
                await asyncio.sleep(0.07)
        if roll.told():
            self.query_one("#dice-damage", Static).update(
                Text(f"→ {roll.told()}", style="bold #ffb000" if roll.actor == "player" else "bold #ff7b7b"))
        sound.play(how)
        if big:
            await self._shake(box)

        prompt = Text()
        if not roll.success and self.can_reroll:
            fate = self.query_one("#dice-fate", Clickable)
            fate.update(Text(f" ✦ Spend Fate to reroll ({self.fate} left) ", style="bold #10122a on #ffd166"))
            fate.add_class("-shown")  # (into the row kept for it: the box doesn't grow)
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
