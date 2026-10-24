"""Everything here you could act on, as typed refs: a RoomView. The interaction grid (interactions.py) aims at these,
the Here panel draws them, and the interpreter is to name them, so a "use X on Y" is never a guess at what "the rat"
in a sentence meant.

    self            you
    room            the room itself (what a thing's thrown down in, what a glow stick lights up)
    monster:<key>   whoever's here, monster or character: hostile or not, its mood, HP, where it stands
    keeper:<key>    a shop's keeper, behind her counter (she's no monster: room.shop, not room.monster)
    ware:<i>        a ware on her counter, at its price
    gear:weapon     the weapon in your hand; gear:armor, the armor on your back
    item:<key>      something in your pack (how many)
    bombs, keys     your bombs and small keys (how many); gold, your gold (how much)
    floor:<key>     something lying here (how many; and whether you put it down yourself)
    feature:<i>     a feature you can see (searched? used in a stunt? something told hidden in it?)
    fixture:<kind>  the room's chest, shrine, fountain, stairs or shop counter (used?)
    exit:<dir>      a way out (locked? what opens it? cracked by a bomb?); wall:<dir>, a wall worth a bomb

    view = RoomView(state, content)
    view.get("monster:goblin")      a Ref, or None if it isn't here (any more)
    view.things()                   what's in the room, characters first: what the Here panel shows
    view.carried()                  what's yours: gear, pack, bombs, keys and gold
    view.match(words, kinds)        the ref some words name ("the rat's eyes", "my holy water"), for reading a stunt
    view.lines()                    the refs one to a line, for a model's prompt

A Ref's `key` is what an action id names it by: an item's key ("holy_water"), a monster's, a fixture's kind, a
direction, a feature's index. Its `state` says how it is, for a tile to show: see each kind in RoomView.__init__.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import inventory, layout
from .content import Content
from .models import DIRECTIONS, GameState
from .text import bare

STOPWORDS = {"the", "a", "an", "my", "your", "some", "this", "that", "these", "those", "of", "and", "own", "old",
             "little", "big", "whole", "one"}
PRONOUNS = {"it", "him", "her", "them", "its", "his", "their", "creature", "beast", "monster", "fiend"}
# Other words a thing goes by, beside its name.
ALIASES = {"self": {"me", "myself", "yourself", "self", "wound", "wounds"},
           "room": {"room", "floor", "ground", "corner", "around", "air", "dark", "darkness"},
           "gold": {"gold", "coin", "coins", "money", "purse", "gp"},
           "bombs": {"bomb"}, "keys": {"small", "key"},
           "keeper": {"granny", "shopkeeper", "shopkeep", "merchant", "keeper", "she"},
           "gear:weapon": {"weapon", "blade"}, "gear:armor": {"armor", "armour"},
           "chest": {"chest", "lock", "trunk"}, "shrine": {"shrine", "altar"},
           "fountain": {"fountain", "water", "basin"}, "stairs": {"stairs", "staircase", "steps", "stair"},
           "shop": {"counter", "shop", "wares"}, "exit": {"door", "doorway", "way", "exit", "passage"},
           "wall": {"wall"}}
FIXTURE_NAMES = {"chest": "chest", "shrine": "shrine", "fountain": "fountain", "stairs": "stairs",
                 "shop": "shop counter"}
FIXTURE_TAGS = {"chest": ["heavy", "wood", "metal"], "shrine": ["holy", "heavy"], "fountain": ["water", "liquid"],
                "stairs": ["heavy", "stone"], "shop": ["heavy", "wood"]}
CHARACTERS, THINGS = ("monster", "keeper"), ("ware", "floor", "feature", "fixture", "exit", "wall")
CARRIED = ("gear", "item", "bombs", "keys", "gold")


@dataclass(frozen=True)
class Ref:
    """One thing you could act on (see the module's docstring)."""

    id: str
    kind: str  # self, room, monster, keeper, ware, gear, item, bombs, keys, gold, floor, feature, fixture, exit, wall
    name: str  # as it's called, without an article: "Goblin", "Vial of Holy Water", "stew cauldron", "north door"
    key: str = ""
    count: int = 1
    tags: tuple[str, ...] = ()
    state: dict = field(default_factory=dict, compare=False)
    sprite: str = ""  # its picture: a monster's key, "item_<key>", or a fixture's kind

    def words(self) -> set[str]:
        """What it's called, as the words someone might use for it."""
        aliases = ALIASES.get(self.id, set()) | ALIASES.get(self.kind, set()) | \
            (ALIASES.get(self.key, set()) if self.kind == "fixture" else set())
        if self.kind == "exit":  # "the locked door", "the shop door", "the door to the Ossuary"
            aliases = aliases | {word for word, said in (("locked", self.state["locked"]), ("shop", self.state["shop"]),
                                                         (self.state["dest"], True)) if said and word}
        return words(self.name) | words(" ".join(aliases))


def words(text: str) -> set[str]:
    """The words of a name or a phrase that say which thing: "the Goblin's eyes" -> {goblin, eye}."""
    found = set()
    for word in re.findall(r"[a-z]+(?:'[a-z]+)?", text.lower()):
        word = word.removesuffix("'s").removesuffix("'")
        if word in STOPWORDS or len(word) < 2:
            continue
        found.add(word[:-1] if word.endswith("s") and len(word) > 3 and not word.endswith("ss") else word)
    return found


class RoomView:
    """The room you're in, and what's yours, as refs (see the module's docstring)."""

    def __init__(self, state: GameState, content: Content):
        self.state, self.content = state, content
        room, player = state.room, state.player
        refs: list[Ref] = [Ref("self", "self", "you", state={"hp": player.hp, "max_hp": player.max_hp}),
                           Ref("room", "room", room.name, str(room.id),
                               state={"searched": room.room_searched, "rested": room.rested})]
        monster = room.monster if room.monster and room.monster.hp > 0 else None
        if monster:
            base = content.monster(monster.key)
            refs.append(Ref(f"monster:{monster.key}", "monster", monster.name, monster.key,
                            tags=tuple(base.tags), sprite=monster.key,
                            state={"hostile": monster.hostile, "mood": monster.mood, "hp": monster.hp,
                                   "max_hp": monster.max_hp, "intent": monster.intent, "npc": base.npc,
                                   "boss": base.boss, "intelligent": base.intelligent, "asked": monster.asked,
                                   "distracted": monster.distracted, "pos": layout.where(room.monster_pos)}))
        if room.shop:
            keeper = content.monster(room.shop.keeper)
            refs.append(Ref(f"keeper:{keeper.key}", "keeper", keeper.name, keeper.key, sprite=keeper.key,
                            state={"wares": len(room.shop.wares)}))
            for i, ware in enumerate(room.shop.wares):
                item = content.item(ware.item)
                refs.append(Ref(f"ware:{i}", "ware", item.name, str(i), tags=tuple(item.tags),
                                sprite=f"item_{item.key}",
                                state={"item": item.key, "price": ware.price, "haggled": ware.haggled,
                                       "afford": player.gold >= ware.price}))
        for slot in ("weapon", "armor"):
            key = inventory.worn(state, slot)
            if key:
                item = content.item(key)
                refs.append(Ref(f"gear:{slot}", "gear", item.name, key, tags=tuple(item.tags), sprite=f"item_{key}",
                                state={"slot": slot, "cursed": inventory.sticky(state, content, key)}))
        for key in dict.fromkeys(player.inventory):
            item = content.item(key)
            refs.append(Ref(f"item:{key}", "item", item.name, key, player.inventory.count(key), tuple(item.tags),
                            sprite=f"item_{key}", state={"kind": item.kind,
                                                         "cursed": inventory.sticky(state, content, key)}))
        if player.bombs:
            refs.append(Ref("bombs", "bombs", "bomb", "bomb", player.bombs, ("fire", "loud"), sprite="item_bomb"))
        if player.keys:
            refs.append(Ref("keys", "keys", "small key", "small_key", player.keys, ("metal",), sprite="item_small_key"))
        if player.gold:
            refs.append(Ref("gold", "gold", "gold", "gold", player.gold, ("shiny",)))
        mine = set(room.left)
        for key in dict.fromkeys(room.items):
            item = content.item(key)
            refs.append(Ref(f"floor:{key}", "floor", item.name, key, room.items.count(key), tuple(item.tags),
                            sprite=f"item_{key}", state={"kind": item.kind, "mine": key in mine,
                                                         "cursed": inventory.sticky(state, content, key)}))
        for i, feature in room.visible_features():
            refs.append(Ref(f"feature:{i}", "feature", bare(feature.name), str(i),
                            tags=tuple(content.feature_tags(feature.name)),
                            state={"searched": feature.searched, "used": feature.used, "told": feature.told,
                                   "pos": layout.where(feature.pos)}))
        if room.fixture:
            refs.append(Ref(f"fixture:{room.fixture}", "fixture", FIXTURE_NAMES[room.fixture], room.fixture,
                            tags=tuple(FIXTURE_TAGS[room.fixture]), sprite=room.fixture,
                            state={"used": room.fixture_used}))
        for direction in DIRECTIONS:
            exit_ = room.exits.get(direction)
            if exit_:
                dest = state.rooms[exit_.to]
                refs.append(Ref(f"exit:{direction}", "exit", f"{direction} door", direction, tags=("wood",),
                                state={"locked": exit_.locked, "key": exit_.key, "cracked": exit_.cracked,
                                       "to": exit_.to, "visited": dest.visited, "shop": dest.shop is not None,
                                       "dest": dest.name if dest.visited else ""}))
        from .rules import bombable_walls  # (rules builds on this module's neighbours: imported when it's needed)

        for direction in bombable_walls(state):
            cracked = room.draft == direction  # (a draft through it stays told: the crack is part of the wall now)
            name = f"cracked {direction} wall" if cracked else f"{direction} wall"
            refs.append(Ref(f"wall:{direction}", "wall", name, direction, tags=("stone",), state={"draft": cracked}))
        self.refs = refs
        self._by_id = {ref.id: ref for ref in refs}

    def get(self, ref_id: str) -> Ref | None:
        return self._by_id.get(ref_id)

    def of(self, *kinds: str) -> list[Ref]:
        return [ref for ref in self.refs if ref.kind in kinds]

    @property
    def monster(self) -> Ref | None:
        return next(iter(self.of("monster")), None)

    @property
    def keeper(self) -> Ref | None:
        return next(iter(self.of("keeper")), None)

    def things(self) -> list[Ref]:
        """What's in the room, as the Here panel shows it: whoever's here first, then her wares, what's lying here,
        the features, the fixture and the ways out."""
        return self.of(*CHARACTERS) + self.of(*THINGS)

    def carried(self) -> list[Ref]:
        """What's yours: the gear you have on, your pack, your bombs, small keys and gold."""
        return self.of(*CARRIED)

    def match(self, said: set[str] | str, kinds: tuple[str, ...]) -> Ref | None:
        """The ref of one of `kinds` that some words name best: most of its name said, then fewest of its name's words
        left unsaid ("the bomb" is a bomb, not the Smoke Bomb). "It", "him" and the like are whoever's here. None if
        nothing of the kind is named at all."""
        said = words(said) if isinstance(said, str) else said
        best, score = None, (0, 0)
        for ref in self.of(*kinds):
            named = ref.words()
            hit = len(said & named)
            if ref.kind in CHARACTERS and said & PRONOUNS:
                hit = max(hit, 1)
            if hit and (hit, -len(words(ref.name) - said)) > score:
                best, score = ref, (hit, -len(words(ref.name) - said))
        return best

    def lines(self, tags: bool = False) -> list[str]:
        """The refs one to a line, with how each is: "monster:goblin  Goblin (hostile, 8/8 HP, centre)", "bombs  bomb
        (×2)"; with `tags`, what each thing is made of too ("item:holy_water  Vial of Holy Water (holy, liquid, glass,
        throwable)"), for a model to see what it'd be good for."""
        out = []
        for ref in self.refs:
            notes = []
            s = ref.state
            if ref.kind == "monster":
                notes += ["hostile" if s["hostile"] else "calm", f"{s['hp']}/{s['max_hp']} HP", s["pos"]]
                notes += [f"mood {s['mood']}"] if s["mood"] else []
            elif ref.kind == "ware":
                notes.append(f"{s['price']} gold")
            elif ref.kind == "gold":
                notes.append(str(ref.count))
            elif ref.kind in ("item", "floor") and ref.count > 1 or ref.kind in ("bombs", "keys"):
                notes.append(f"×{ref.count}")
            elif ref.kind == "feature":
                notes += ["searched"] if s["searched"] else []
            elif ref.kind == "fixture" and s["used"]:
                notes.append("used")
            elif ref.kind == "exit" and s["locked"]:
                notes.append("locked, a small key opens it" if s["key"] == "small_key" else "locked")
            if ref.kind in ("item", "floor", "gear") and s.get("cursed"):
                notes.append("cursed")
            if tags and ref.kind in ("item", "floor", "gear", "ware", "feature", "fixture"):
                notes += list(ref.tags)
            out.append(f"{ref.id}  {ref.name}" + (f" ({', '.join(notes)})" if notes else ""))
        return out
