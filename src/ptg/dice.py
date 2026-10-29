"""Dice: notation ("2d6+1"), deterministic per-turn random streams, and d20 checks the UI can animate."""

from __future__ import annotations

import random
import re
from contextvars import ContextVar
from dataclasses import dataclass, field

_DICE = re.compile(r"^\s*(\d+)d(\d+)\s*([+-]\s*\d+)?\s*$")


def roll(expr: str, rng: random.Random) -> int:
    match = _DICE.match(expr)
    if not match:
        raise ValueError(f"bad dice expression: {expr!r}")
    count, sides, bonus = int(match.group(1)), int(match.group(2)), match.group(3)
    total = sum(rng.randint(1, sides) for _ in range(count))
    return total + (int(bonus.replace(" ", "")) if bonus else 0)


def average(expr: str) -> float:
    """What a roll comes to on average: "2d6+2" is 9."""
    match = _DICE.match(expr)
    if not match:
        raise ValueError(f"bad dice expression: {expr!r}")
    count, sides, bonus = int(match.group(1)), int(match.group(2)), match.group(3)
    return count * (sides + 1) / 2 + (int(bonus.replace(" ", "")) if bonus else 0)


def span(expr: str) -> tuple[int, int]:
    """The least and the most a roll can come to: "2d6+2" is (4, 14)."""
    match = _DICE.match(expr)
    if not match:
        raise ValueError(f"bad dice expression: {expr!r}")
    count, sides, bonus = int(match.group(1)), int(match.group(2)), match.group(3)
    flat = int(bonus.replace(" ", "")) if bonus else 0
    return count + flat, count * sides + flat


def d20(rng: random.Random) -> int:
    return rng.randint(1, 20)


def stream(seed: int, *labels: object) -> random.Random:
    """A random stream fully determined by the seed and labels, so saves replay identically."""
    return random.Random(":".join(str(part) for part in (seed, *labels)))


@dataclass
class Roll:
    """One d20 check, with everything the UI needs to animate it."""

    label: str
    actor: str  # "player" or "monster"
    dice: list[int]
    kept: int
    bonuses: list[tuple[str, int]] = field(default_factory=list)
    dc: int = 10
    success: bool = False
    advantage: int = 0  # 1 = roll two keep high, -1 = roll two keep low
    impossible: bool = False
    hits_for: str = ""  # a roll to hit: the damage it does if it hits ("4d6"), told before you roll
    damage: list[tuple[str, int]] = field(default_factory=list)  # what the hit did, part by part (see hurt)
    effects: list[str] = field(default_factory=list)  # what else came of it: "+1 Fate (2/3)", "+6 HP" (see told)
    hindered: str = ""  # why it was at a disadvantage, if a status put it there (a penalty is one of its bonuses)

    @property
    def total(self) -> int:
        return self.kept + sum(v for _, v in self.bonuses)

    @property
    def needed(self) -> int:
        """The least the die has to show to succeed, from 2 (a 1 always fails) to 20 (a 20 always succeeds); 21 if
        nothing will do (an impossible check)."""
        if self.impossible:
            return 21
        return max(2, min(20, self.dc - sum(v for _, v in self.bonuses)))

    @property
    def chance(self) -> float:
        """How likely it was to succeed, before it was rolled: on one die, or the better (or worse) of two."""
        one = max(0, 21 - self.needed) / 20
        return 1 - (1 - one) ** 2 if self.advantage > 0 else one * one if self.advantage < 0 else one

    @property
    def crit(self) -> bool:
        return self.kept == 20 and not self.impossible

    @property
    def fumble(self) -> bool:
        return self.kept == 1

    def hurt(self) -> str:
        """The damage a hit did and where it came from: "18 damage (4d6 14 + crit 4d6 4)", or "" if it did none."""
        if not self.damage:
            return ""
        total = sum(v for _, v in self.damage)
        first, *rest = self.damage
        parts = f"{first[0]} {first[1]}" + "".join(f" {'+' if v >= 0 else '-'} {name} {abs(v)}" for name, v in rest)
        return f"{total} damage ({parts})"

    def told(self) -> str:
        """What came of the roll, for after its verdict: the damage, then anything it won or cost you."""
        return " · ".join(filter(None, [self.hurt(), *self.effects]))

    def describe(self, verdict: bool = True) -> str:
        dice = f"d20 {self.kept}" if len(self.dice) == 1 else f"d20 {'/'.join(map(str, self.dice))}→{self.kept}"
        parts = "".join(f" {'+' if v >= 0 else '-'} {abs(v)} {name}" for name, v in self.bonuses if v)
        target = "impossible" if self.impossible else str(self.dc)
        label = f"{self.label}, {self.hindered}" if self.hindered else self.label
        sum_ = f"{label}: {dice}{parts} = {self.total} vs {target}"
        if not verdict:
            return sum_
        return f"{sum_} - " + ("CRIT" if self.crit else "FUMBLE" if self.fumble else
                               "success" if self.success else "fail")


@dataclass(frozen=True)
class Hindrance:
    """What a status does to the player's rolls (statuses.hindrance): why ("poisoned"), a penalty off each, or a
    disadvantage; and the dark's (light.hindrance), a disadvantage of its own (`why_worse`: "in the dark")."""
    why: str = ""
    penalty: int = 0
    disadvantage: bool = False
    why_worse: str = ""  # why the disadvantage, when it isn't `why`'s


# What a status does to the player's rolls this turn: set by the turn (rules.perform), so every roll of the player's
# takes it in without each one asking.
HINDERED: ContextVar[Hindrance] = ContextVar("hindered", default=Hindrance())  # noqa: B039 (frozen: never changes)


def check(rng: random.Random, label: str, bonuses: list[tuple[str, int]], dc: int, actor: str = "player",
          advantage: int = 0, impossible: bool = False) -> Roll:
    hindrance = HINDERED.get() if actor == "player" else Hindrance()
    if hindrance.penalty:  # (said as a bonus of its own: "- 2 poisoned")
        bonuses = [*bonuses, (hindrance.why, -hindrance.penalty)]
    if hindrance.disadvantage:
        advantage -= 1  # (an advantage and a disadvantage cancel out: one die)
    dice = [d20(rng)] if advantage == 0 else [d20(rng), d20(rng)]
    kept = max(dice) if advantage > 0 else min(dice)
    result = Roll(label, actor, dice, kept, [b for b in bonuses if b[1]], dc, False, advantage, impossible,
                  hindered=(hindrance.why_worse or hindrance.why) if hindrance.disadvantage else "")
    if impossible:
        result.success = False
    else:
        result.success = kept == 20 or (kept != 1 and result.total >= dc)
    return result
