"""The game state. Everything here is plain data so a save file is just this model as JSON."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .content import Content

Direction = Literal["north", "south", "east", "west"]
DIRECTIONS: tuple[Direction, ...] = ("north", "south", "east", "west")
OPPOSITE: dict[str, Direction] = {"north": "south", "south": "north", "east": "west", "west": "east"}
DELTA: dict[str, tuple[int, int]] = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}

LEVEL_XP = [0, 20, 55, 110, 200, 320]


class MonsterState(BaseModel):
    key: str
    name: str
    hp: int
    max_hp: int
    hostile: bool = True
    stunned: int = 0


class Feature(BaseModel):
    name: str
    loot: list[str] = Field(default_factory=list)
    gold: int = 0
    searched: bool = False
    hidden: bool = False


class Exit(BaseModel):
    to: int
    locked: bool = False


class Room(BaseModel):
    id: int
    x: int
    y: int
    name: str
    archetype: str
    distance: int = 0
    exits: dict[Direction, Exit] = Field(default_factory=dict)
    features: list[Feature] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list)
    monster: MonsterState | None = None
    visited: bool = False
    rested: bool = False
    room_searched: bool = False
    creative_uses: list[str] = Field(default_factory=list)
    description: str | None = None
    is_boss: bool = False

    def visible_features(self) -> list[tuple[int, Feature]]:
        return [(i, f) for i, f in enumerate(self.features) if not f.hidden]


class Player(BaseModel):
    name: str
    hp: int = 30
    max_hp: int = 30
    might: int = 2
    agility: int = 1
    wits: int = 1
    level: int = 1
    xp: int = 0
    gold: int = 0
    weapon: str = "rusty_sword"
    armor: str | None = None
    inventory: list[str] = Field(default_factory=lambda: ["healing_potion"])
    kills: int = 0

    @property
    def attack_bonus(self) -> int:
        return self.might + self.level

    def defense(self, content: Content) -> int:
        armor = content.item(self.armor).defense if self.armor else 0
        return 10 + self.agility + armor

    def stat(self, name: str) -> int:
        return {"might": self.might, "agility": self.agility, "wits": self.wits}.get(name, 0)

    def next_level_xp(self) -> int | None:
        return LEVEL_XP[self.level] if self.level < len(LEVEL_XP) else None


class LogEntry(BaseModel):
    kind: Literal["player", "narration", "mechanic", "system"]
    text: str


class GameState(BaseModel):
    version: int = 2
    seed: int
    theme: str
    rooms: list[Room]
    room_id: int = 0
    prev_room_id: int | None = None
    player: Player
    turn: int = 0
    journal: list[str] = Field(default_factory=list)
    log: list[LogEntry] = Field(default_factory=list)
    status: Literal["playing", "won", "dead"] = "playing"

    @property
    def room(self) -> Room:
        return self.rooms[self.room_id]

    @property
    def in_combat(self) -> bool:
        monster = self.room.monster
        return monster is not None and monster.hostile and monster.hp > 0

    @property
    def over(self) -> bool:
        return self.status != "playing"
