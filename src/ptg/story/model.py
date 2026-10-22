"""The shape of an authored story event, independent of the file format it was written in.

The parser turns story files into these; the engine only ever sees these. If the writing format changes,
only the parser has to.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TRIGGERS = ("enter_room", "say", "roll", "defeat", "pacify", "run_start", "turn")
VOICES = ("exact", "narrated", "silent")
ONCE = ("run", "profile", "always")


class StoryError(ValueError):
    """A problem in a story file. The message names the file and line."""


@dataclass
class Effect:
    verb: str
    args: list[str]
    line: int = 0


@dataclass
class Condition:
    name: str
    negate: bool = False
    op: str = ""
    value: str = ""
    line: int = 0


@dataclass
class Choice:
    label: str
    keywords: list[str]
    text: str = ""
    effects: list[Effect] = field(default_factory=list)
    fallback: bool = False
    line: int = 0


@dataclass
class Node:
    id: str
    text: str = ""
    effects: list[Effect] = field(default_factory=list)
    choices: list[Choice] = field(default_factory=list)
    line: int = 0

    @property
    def options(self) -> list[Choice]:
        """The choices shown as numbered options (everything but the catch-all)."""
        return [c for c in self.choices if not c.fallback]

    @property
    def fallback(self) -> Choice | None:
        return next((c for c in self.choices if c.fallback), None)


@dataclass
class StoryEvent:
    id: str
    title: str
    trigger: str
    trigger_args: list[str]
    conditions: list[Condition]
    once: str
    voice: str
    secret: bool
    hint: str
    nodes: dict[str, Node]
    source: str
    sprite: str = ""

    @property
    def start(self) -> Node:
        return self.nodes["start"]

    @property
    def is_scene(self) -> bool:
        return any(node.choices for node in self.nodes.values())
