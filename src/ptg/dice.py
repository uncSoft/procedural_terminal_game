"""Dice: notation ("2d6+1"), deterministic per-turn random streams, and d20 checks the UI can animate."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

_DICE = re.compile(r"^\s*(\d+)d(\d+)\s*([+-]\s*\d+)?\s*$")


def roll(expr: str, rng: random.Random) -> int:
    match = _DICE.match(expr)
    if not match:
        raise ValueError(f"bad dice expression: {expr!r}")
    count, sides, bonus = int(match.group(1)), int(match.group(2)), match.group(3)
    total = sum(rng.randint(1, sides) for _ in range(count))
    return total + (int(bonus.replace(" ", "")) if bonus else 0)


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

    @property
    def total(self) -> int:
        return self.kept + sum(v for _, v in self.bonuses)

    @property
    def crit(self) -> bool:
        return self.kept == 20 and not self.impossible

    @property
    def fumble(self) -> bool:
        return self.kept == 1

    def describe(self) -> str:
        dice = f"d20 {self.kept}" if len(self.dice) == 1 else f"d20 {'/'.join(map(str, self.dice))}→{self.kept}"
        parts = "".join(f" {'+' if v >= 0 else '-'} {abs(v)} {name}" for name, v in self.bonuses if v)
        target = "impossible" if self.impossible else str(self.dc)
        verdict = "CRIT" if self.crit else ("FUMBLE" if self.fumble else ("success" if self.success else "fail"))
        return f"{self.label}: {dice}{parts} = {self.total} vs {target} - {verdict}"


def check(rng: random.Random, label: str, bonuses: list[tuple[str, int]], dc: int, actor: str = "player",
          advantage: int = 0, impossible: bool = False) -> Roll:
    dice = [d20(rng)] if advantage == 0 else [d20(rng), d20(rng)]
    kept = max(dice) if advantage > 0 else min(dice)
    result = Roll(label, actor, dice, kept, [b for b in bonuses if b[1]], dc, False, advantage, impossible)
    if impossible:
        result.success = False
    else:
        result.success = kept == 20 or (kept != 1 and result.total >= dc)
    return result
