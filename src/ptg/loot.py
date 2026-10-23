"""What turns up where. Loot is chosen from the game's own items by role and tier, so a new item (one made in the
Monster & Item Maker, say) drops without any code changes.

Every place that hands out an item asks for a slot: a role and the tiers it allows, or an item by name.

    weapon 1      a tier-1 weapon                       food 0        tier-0 food (Stale Bread)
    armor 3+      armor of tier 3 or more               escape 1+     something to get out of a fight, tier 1 up
    gear 2        a tier-2 weapon or armor              trinket       any trinket (they have no stats to rank)
    potion 2+     a healing potion, tier 2 or more      lucky_charm   that very item

    rare -2       a rare thing of tier 2 or less (see below)

A slot picks a tier first, each tier it allows that has items being as likely as the next, then an item of that
tier: five new tier-3 potions don't make tier 3 five times as likely. A slot with only one item to give gives it
without a roll, so a seed's dungeon only changes where there's something new to choose between.

Where the top tiers land (the "+" slots): the best potion on floor 3, in hidden stashes and in floor-3 chests;
the best weapons and armor in stashes and floor-3 chests; tier 2+ food and escapes on floor 2.

The starting sword, the keys, bombs, small keys and the Lucky Charm (it has rules of its own) only ever turn up by
name.

Rare things (an item tagged `rare`, or one whose `found` names the only places it turns up) never lie about on a floor,
drop from an everyday monster or turn up from a stunt. They're kept for the places worth seeking out: chests, hidden
stashes, each floor's secret room, and the warden by the stairs (and other elites); an item can also name the monster
that drops it. Each comes at most once a run.
"""

from __future__ import annotations

import math
import random

from .content import FOUND_IN, Content, ItemDef

GEAR = ("weapon", "armor")
BY_NAME_ONLY = {"lucky_charm", "bomb", "small_key"}

FLOORS = {  # each floor spreads these through its rooms (see world._place_loot), with its dungeon's own trinket
    1: ["weapon 1", "armor 1", "potion 1", "potion 1", "food 0", "bomb", "small_key"],
    2: ["gear 2", "potion 1", "escape 1+", "food 1+", "bomb", "small_key"],  # loot spread out is found more: a potion less
    3: ["potion 2+", "potion 1", "potion 1", "gear 2", "small_key"],
}
DUNGEON_TRINKETS = {"sunken_crypt": "holy_water", "goblin_warren": "bag_of_marbles", "overgrown_ruins": "oil_flask"}
STASH = ["weapon 3+", "armor 3+", "potion 2+", "lucky_charm", "rare"]  # each floor's hidden stash holds one of these
CHESTS = {  # a chest holds one of its floor's ("rare -1": a rare thing of tier 1 or less)
    1: ["armor 1", "trinket", "escape 1", "potion 1", "rare -1"],
    2: ["armor 2", "weapon 2", "potion 2", "lucky_charm", "rare -2"],
    3: ["armor 3+", "weapon 3+", "potion 2+", "lucky_charm", "rare"],
}
SECRET = ["rare"]  # what a floor's secret room keeps, any tier: it's hard to find
# What the warden by the stairs always drops, and an elite sometimes: rare things, tier capped by the floor (so the
# best of them come from the elites of the last floor, and secret rooms).
WARDEN = {1: ["rare -1"], 2: ["rare -2"], 3: ["rare"]}
WARDEN_DROP, ELITE_DROP = 1.0, 0.2  # how often
# What a place gives once there's no rare thing left for it: a strong potion, but a warden carries a small key (so
# floor 1's, with nothing rare that weak to give, always does). A strong potion there won the bot 11% more runs.
INSTEAD = {"warden": "small_key"}
INSTEAD_OF_RARE = "potion 2+"
DROP = "potion 1"  # what a slain monster sometimes leaves
FINDS = ["food 0", "food 0", "potion 1", "escape 1", "trinket"]  # what a stunt that pays off can turn up
EVERYDAY = "floor"  # the place of a floor's scattered loot, a monster's drop or a find: no rare things here

PLACES = [("floor 1", FLOORS[1], EVERYDAY), ("floor 2", FLOORS[2], EVERYDAY), ("floor 3", FLOORS[3], EVERYDAY),
          ("hidden stashes", STASH, "stash"), ("floor 1 chests", CHESTS[1], "chest"),
          ("floor 2 chests", CHESTS[2], "chest"), ("floor 3 chests", CHESTS[3], "chest"),
          ("secret rooms", SECRET, "secret"), ("wardens and elites", WARDEN[3], "warden"),
          ("slain monsters", [DROP], EVERYDAY), ("lucky finds", FINDS, EVERYDAY)]


def role(item: ItemDef) -> str:
    """The part an item plays in loot: weapon, armor, potion, food, escape, trinket or key."""
    if item.kind != "consumable":
        return item.kind
    if item.escape:
        return "escape"
    if "food" in item.tags:
        return "food"
    return "potion" if item.heal else "other"


def _tiers(text: str) -> tuple[int, float]:
    if not text:
        return 0, math.inf
    if text.endswith("+"):
        return int(text[:-1]), math.inf
    if text.startswith("-"):
        return 0, int(text[1:])
    return int(text), int(text)


def rare(item: ItemDef) -> bool:
    return bool(item.found) or "rare" in item.tags


def allowed(item: ItemDef, place: str) -> bool:
    """Whether an item can turn up in a place: everyday loot anywhere, a rare thing only where it's kept."""
    if item.found:
        return place in item.found
    return place != EVERYDAY if "rare" in item.tags else True


def candidates(content: Content, slot: str, place: str = EVERYDAY, taken=()) -> dict[int, list[str]]:
    """The items a slot can give in a place, by tier, lowest first, leaving out rare things this run has had."""
    if slot in content.items:
        return {content.item(slot).tier: [slot]}
    name, _, tiers = slot.partition(" ")
    roles = GEAR if name == "gear" else (name,)
    low, high = _tiers(tiers)
    found: dict[int, list[str]] = {}
    for item in content.items.values():
        if item.key in BY_NAME_ONLY or item.key in taken or not allowed(item, place):
            continue
        if (rare(item) if name == "rare" else role(item) in roles) and low <= item.tier <= high:
            found.setdefault(item.tier, []).append(item.key)
    return dict(sorted(found.items()))


def pick(rng: random.Random, content: Content, slot: str, place: str = EVERYDAY, taken=()) -> str | None:
    """An item for a slot (a tier, then an item of it), or None if the game has nothing that fits. Rare things are
    hand-placed already, so each is as likely as the next: a lone tier-0 joke shouldn't be half of every prize."""
    tiers = list(candidates(content, slot, place, taken).values())
    if not tiers:
        return None
    if slot.startswith("rare"):
        tiers = [[key for keys in tiers for key in keys]]
    keys = tiers[0] if len(tiers) == 1 else rng.choice(tiers)
    return keys[0] if len(keys) == 1 else rng.choice(keys)


def one_of(rng: random.Random, content: Content, slots: list[str], place: str = EVERYDAY, taken=()) -> str | None:
    """A chest's or a stash's single item: one of its slots, then an item for that slot."""
    return pick(rng, content, rng.choice(slots), place, taken)


def produce(rng: random.Random, content: Content, rares: list[str], slots: list[str], place: str) -> str | None:
    """One of a special place's slots, filled; a rare thing it gives is noted in `rares` so it never comes twice."""
    key = one_of(rng, content, slots, place, rares)
    if key is None and any(s.startswith("rare") for s in slots):  # no rare thing left for here
        key = pick(rng, content, INSTEAD.get(place, INSTEAD_OF_RARE), place, rares)
    if key and rare(content.item(key)):
        rares.append(key)
    return key


def where(content: Content, key: str) -> list[str]:
    """Where an item can turn up ("floor 3", "hidden stashes"...), for the debug screen."""
    found = [name for name, slots, place in PLACES
             if any(key in keys for slot in slots for keys in candidates(content, slot, place).values())]
    found += [f"{content.themes[theme].name}'s own trinket" for theme, trinket in DUNGEON_TRINKETS.items()
              if trinket == key and theme in content.themes]
    item = content.item(key)
    found += [f"dropped by {content.monster(place).name}" for place in item.found if place not in FOUND_IN]
    return found
