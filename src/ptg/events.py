"""Events are the facts a turn produces; actions are what the player can choose."""

from __future__ import annotations

from dataclasses import dataclass, field

from .dice import Roll


@dataclass
class Event:
    kind: str
    text: str
    dice: Roll | None = None
    data: dict = field(default_factory=dict)

    @property
    def roll(self) -> str:
        return self.dice.describe() if self.dice else ""


@dataclass
class Action:
    id: str
    label: str
    hint: str = ""  # short tag shown beside the choice, e.g. "shrine" or "heavy attack!"
