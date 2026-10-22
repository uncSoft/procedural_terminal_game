"""Dice notation ("2d6+1") and deterministic per-turn random streams."""

from __future__ import annotations

import random
import re

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
