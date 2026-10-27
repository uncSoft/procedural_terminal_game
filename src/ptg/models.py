"""The game state. Everything here is plain data so a save file is just this model as JSON."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .content import Content

Direction = Literal["north", "south", "east", "west"]
DIRECTIONS: tuple[Direction, ...] = ("north", "south", "east", "west")
OPPOSITE: dict[str, Direction] = {"north": "south", "south": "north", "east": "west", "west": "east"}
DELTA: dict[str, tuple[int, int]] = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}

LEVEL_XP = [0, 20, 55, 110, 200, 320, 480, 700]
FLOORS = 4  # a run: three dungeons, then Norfel (themes.toml)
DUNGEONS = 3  # the run's first floors, a dungeon each: the last of them has its boss, and the way down behind it
MAX_FATE = 3

Intent = Literal["strike", "heavy", "guard"]
Fixture = Literal["", "shrine", "chest", "fountain", "stairs", "shop"]


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
    distracted: bool = False  # something has drawn its eye once this fight (a distract power)
    asked: bool = False  # you've asked it what it knows about this floor (once: see rules._ask)
    met: bool = False  # you've walked in on it, and it's had its say (npcs.react)
    mood: str = ""  # where an NPC's story has got to (see npcs.py): Lenny's "tooth", Swoogy's "challenge"...
    secret: int = 0  # the number on Swoogy's die, while you guess
    stolen_item: str = ""  # what a thief grabbed and means to run off with (a steal trick: see combat.monster_turn)
    stolen_gold: int = 0
    tier: int = 0  # its tier here, if not its maker's: a character cut down to size for its floor (npcs.sized)
    warden: bool = False  # the one guarding the stairs (or standing in for it): it always leaves something
    tricks: list[str] = Field(default_factory=list)  # tricks it has here beyond its maker's (Norfel's venom)
    rewarded: bool = False  # talked down already, and paid for it: killing it now pays nothing more


class Feature(BaseModel):
    name: str
    loot: list[str] = Field(default_factory=list)
    gold: int = 0
    searched: bool = False
    hidden: bool = False
    pos: tuple[int, int] = (0, 0)
    used: str = ""  # what a stunt did with it; once used, it's spent as a prop
    told: str = ""  # who told you something's hidden here (it's on your map)
    trapped: bool = False  # right over a live gas vent (hazards.py): searched before it's disarmed, it gasses you


class Exit(BaseModel):
    to: int
    locked: bool = False
    key: str = ""  # what opens it when locked: the dungeon's own key, or "small_key" for a shop's door
    cracked: bool = False  # a shop door one bomb has had a go at: the next one breaks it


class Ware(BaseModel):
    item: str
    price: int  # each
    haggled: str = ""  # "down" or "up" once you've bartered over it (once a ware)
    count: int = 1  # how many she has of it (potions and Pure come in twos)


class Shop(BaseModel):
    keeper: str  # a monster key, tagged npc: Granny Gristle, or now and then Granny Kamultruk
    wares: list[Ware] = Field(default_factory=list)
    asked: bool = False  # you've asked her what she knows about this floor (once, as any creature: rules._ask)


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
    left: list[str] = Field(default_factory=list)  # those you put down here yourself: no choice offers them back
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
    secret: bool = False  # the floor's hidden room: no doors until a bomb makes one
    draft: str = ""  # the wall you felt a draft through: the secret room is behind it
    told: str = ""  # who told you about this secret room (it's on your map)
    shop: Shop | None = None  # a shopkeeper and her wares, behind a locked door (fixture "shop")
    vent: Literal["", "live", "dead"] = ""  # a gas vent in the floor, under a cache, until it's disarmed (hazards.py)
    river: bool = False  # a poison river across it (hazards.py): the way on, `across`, is on its far bank
    across: str = ""
    far: bool = False  # you're on the river's far bank
    stones: bool = False  # you've crossed it once, and know its stepping stones: no crossing it needs now

    @model_validator(mode="after")
    def _mark_warden(self) -> Room:
        """(A save from before wardens were marked: the stairs' own guard is the one there before anyone rested.)"""
        if self.fixture == "stairs" and self.monster and not self.rested:
            self.monster.warden = True
        return self

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
    bombs: int = 1  # for walls with something behind them, or for monsters
    keys: int = 0  # small keys, for chests
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
    item_stats: dict[str, int] = Field(default_factory=dict)  # what carried things add to your stats now (powers.py)
    hp_given: list[str] = Field(default_factory=list)  # things whose extra max HP (or Fate) came with as much: once a run
    tangled: bool = False  # caught in a monster's vines: no running until it's had its next go (a tangle trick)
    lifted: list[str] = Field(default_factory=list)  # cursed things whose curse a shrine has lifted (inventory.py)
    coating: str = ""  # what your weapon's coated in, as a tag its hits count as: "holy", "fire" (interactions.RECIPES)
    coated: int = 0  # hits the coating has left
    statuses: dict[str, int] = Field(default_factory=dict)  # what's afflicting you, and how strongly (statuses.py)
    guards: dict[str, int] = Field(default_factory=dict)  # charges against a status: the next ones don't take

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
        return MAX_FATE + ("lucky" in self.perks) + ("lucky_charm" in self.inventory) + self.item_stats.get("fate", 0)

    def bump(self, counter: str, amount: int = 1) -> int:
        self.style[counter] = self.style.get(counter, 0) + amount
        return self.style[counter]


class LogEntry(BaseModel):
    kind: Literal["player", "narration", "mechanic", "system", "card", "floor"]
    text: str
    title: str = ""
    art: str = ""  # a story card's sprite
    speaker: str = ""  # a card that's a character's own words: whose (npcs.say), for showing it as their speech


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
    suggestion_id: str = ""  # the use the suggested trick is (interactions.py): what picking it does
    known_weak: dict[str, list[str]] = Field(default_factory=dict)
    ghost: dict | None = None
    test_room: str = ""  # a test room's run (testrooms.py): it counts for nothing, and is never saved
    modded: bool = False  # played on edited game data
    flags: list[str] = Field(default_factory=list)  # story flags for this run
    story_seen: list[str] = Field(default_factory=list)  # story events fired this run
    marks_pending: list[str] = Field(default_factory=list)  # profile marks set this turn, not yet saved
    scene: SceneState | None = None
    mapped_floor: int = 0  # a floor whose whole map you've been handed
    rares: list[str] = Field(default_factory=list)  # rare items this run has turned up: each comes once
    met: list[str] = Field(default_factory=list)  # one-of-a-kind creatures this run has turned up (MonsterDef.once)
    wandered: dict[str, int] = Field(default_factory=dict)  # quick travel's run-ins, by floor (rules.TRAVEL_MEETINGS)
    warned: list[str] = Field(default_factory=list)  # cursed things you've been warned of: taking one now takes it
    quests: dict[str, str] = Field(default_factory=dict)  # each character's stage this run, by its key (npcs.STAGES)
    said: dict[str, int] = Field(default_factory=dict)  # how often each character's said each thing (they take turns)

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

    @property
    def boss_floor(self) -> bool:
        """A floor with a boss behind a locked door: the last dungeon's (floor 3: beaten, its stairs go down), and
        every floor after it (Norfel, the last)."""
        return self.floor >= min(DUNGEONS, self.floors_total)
