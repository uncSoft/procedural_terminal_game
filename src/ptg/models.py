"""The game state. Everything here is plain data so a save file is just this model as JSON."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .content import Content

Direction = Literal["north", "south", "east", "west"]
DIRECTIONS: tuple[Direction, ...] = ("north", "south", "east", "west")
OPPOSITE: dict[str, Direction] = {"north": "south", "south": "north", "east": "west", "west": "east"}
DELTA: dict[str, tuple[int, int]] = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}

LEVEL_XP = [0, 20, 55, 110, 200, 320, 480, 700]
FLOORS = 3
MAX_FATE = 3

Intent = Literal["strike", "heavy", "guard"]
Fixture = Literal["", "shrine", "chest", "fountain", "stairs"]


class MonsterState(BaseModel):
    key: str
    name: str
    hp: int
    max_hp: int
    hostile: bool = True
    stunned: int = 0
    intent: Intent = "strike"
    guarding: bool = False
    elite: str = ""
    attack_mod: int = 0
    defense_mod: int = 0
    damage_mod: int = 0
    reward_mult: float = 1.0
    ghost_id: int | None = None
    ghost_of: str = ""


class Feature(BaseModel):
    name: str
    loot: list[str] = Field(default_factory=list)
    gold: int = 0
    searched: bool = False
    hidden: bool = False
    pos: tuple[int, int] = (0, 0)
    used: str = ""  # what a stunt did with it; once used, it's spent as a prop


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
    history: list[str] = Field(default_factory=list)  # what happened here, for the narrator on later visits
    description: str | None = None
    is_boss: bool = False
    fixture: Fixture = ""
    fixture_used: bool = False
    grid: list[str] = Field(default_factory=list)
    item_spots: list[tuple[int, int]] = Field(default_factory=list)
    monster_pos: tuple[int, int] = (0, 0)
    entered_from: str = ""

    def visible_features(self) -> list[tuple[int, Feature]]:
        return [(i, f) for i, f in enumerate(self.features) if not f.hidden]

    def remember(self, note: str) -> None:
        """Note something that happened here (the last few are kept)."""
        self.history = (self.history + [note])[-4:]


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
    fate: int = 1
    perks: list[str] = Field(default_factory=list)
    traits: list[str] = Field(default_factory=list)
    style: dict[str, int] = Field(default_factory=dict)
    blessings: list[str] = Field(default_factory=list)
    gift: str = ""
    hits_landed: int = 0
    advantage_next: bool = False
    dodging: bool = False
    evaded_rooms: list[str] = Field(default_factory=list)
    second_wind_floor: int = 0
    last_breath_used: bool = False

    @property
    def attack_bonus(self) -> int:
        return self.might + self.level

    def defense(self, content: Content) -> int:
        armor = content.item(self.armor).defense if self.armor else 0
        return 10 + self.agility + armor + (1 if "iron_skin" in self.perks else 0)

    def stat(self, name: str) -> int:
        return {"might": self.might, "agility": self.agility, "wits": self.wits}.get(name, 0)

    def next_level_xp(self) -> int | None:
        return LEVEL_XP[self.level] if self.level < len(LEVEL_XP) else None

    def max_fate(self) -> int:
        return MAX_FATE + ("lucky" in self.perks) + ("lucky_charm" in self.inventory)

    def bump(self, counter: str, amount: int = 1) -> int:
        self.style[counter] = self.style.get(counter, 0) + amount
        return self.style[counter]


class LogEntry(BaseModel):
    kind: Literal["player", "narration", "mechanic", "system", "card", "floor"]
    text: str
    title: str = ""
    art: str = ""  # a story card's sprite


class SceneState(BaseModel):
    """An authored scene in progress: which story event, and which part of it."""

    event: str
    node: str = "start"


class GameState(BaseModel):
    version: int = 3
    seed: int
    theme: str
    themes: list[str] = Field(default_factory=list)
    floor: int = 1
    floors_total: int = FLOORS
    rooms: list[Room]
    room_id: int = 0
    prev_room_id: int | None = None
    player: Player
    turn: int = 0
    reroll: int = 0
    souls: int = 0
    pending_perks: list[str] = Field(default_factory=list)
    perk_debt: int = 0  # extra level-ups still waiting for a perk pick
    journal: list[str] = Field(default_factory=list)
    log: list[LogEntry] = Field(default_factory=list)
    status: Literal["playing", "won", "dead"] = "playing"
    cause: str = ""
    epitaph: str = ""
    daily: str = ""
    run_id: int | None = None
    suggestion: str = ""
    known_weak: dict[str, list[str]] = Field(default_factory=dict)
    ghost: dict | None = None
    modded: bool = False  # played on edited game data
    flags: list[str] = Field(default_factory=list)  # story flags for this run
    story_seen: list[str] = Field(default_factory=list)  # story events fired this run
    marks_pending: list[str] = Field(default_factory=list)  # profile marks set this turn, not yet saved
    scene: SceneState | None = None

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

    @property
    def final_floor(self) -> bool:
        return self.floor >= self.floors_total
