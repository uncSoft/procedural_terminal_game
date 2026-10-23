"""What turns up where. Loot is chosen from the game's own items by role and tier, so a new item (one made in the
Monster & Item Maker, say) drops without any code changes.

Every place that hands out an item asks for a slot: a role and the tiers it allows, or an item by name.

    weapon 1      a tier-1 weapon                       food 0        tier-0 food (Stale Bread)
    armor 3+      armor of tier 3 or more               escape 1+     something to get out of a fight, tier 1 up
    gear 2        a tier-2 weapon or armor              trinket       any trinket (they have no stats to rank)
    potion 2+     a healing potion, tier 2 or more      lucky_charm   that very item

A slot picks a tier first, each tier it allows that has items being as likely as the next, then an item of that
tier: five new tier-3 potions don't make tier 3 five times as likely. A slot with only one item to give gives it
without a roll, so a seed's dungeon only changes where there's something new to choose between.

Where the top tiers land (the "+" slots): the best potion on floor 3, in hidden stashes and in floor-3 chests;
the best weapons and armor in stashes and floor-3 chests; tier 2+ food and escapes on floor 2.

The starting sword, the keys and the Lucky Charm (it has rules of its own) only ever turn up by name.
"""

from __future__ import annotations

import math
import random

from .content import Content, ItemDef

GEAR = ("weapon", "armor")
BY_NAME_ONLY = {"lucky_charm"}

FLOORS = {  # each floor scatters these through its rooms, with its dungeon's own trinket
    1: ["weapon 1", "armor 1", "potion 1", "potion 1", "food 0"],
    2: ["gear 2", "potion 1", "potion 1", "escape 1+", "food 1+"],
    3: ["potion 2+", "potion 1", "potion 1", "gear 2"],
}
DUNGEON_TRINKETS = {"sunken_crypt": "holy_water", "goblin_warren": "bag_of_marbles", "overgrown_ruins": "oil_flask"}
STASH = ["weapon 3+", "armor 3+", "potion 2+", "lucky_charm"]  # each floor's hidden stash holds one of these
CHESTS = {  # a chest holds one of its floor's
    1: ["armor 1", "trinket", "escape 1", "potion 1"],
    2: ["armor 2", "weapon 2", "potion 2", "lucky_charm"],
    3: ["armor 3+", "weapon 3+", "potion 2+", "lucky_charm"],
}
DROP = "potion 1"  # what a slain monster sometimes leaves
FINDS = ["food 0", "food 0", "potion 1", "escape 1", "trinket"]  # what a stunt that pays off can turn up

PLACES = [("floor 1", FLOORS[1]), ("floor 2", FLOORS[2]), ("floor 3", FLOORS[3]), ("hidden stashes", STASH),
          ("floor 1 chests", CHESTS[1]), ("floor 2 chests", CHESTS[2]), ("floor 3 chests", CHESTS[3]),
          ("slain monsters", [DROP]), ("lucky finds", FINDS)]


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
    return int(text), int(text)


def candidates(content: Content, slot: str) -> dict[int, list[str]]:
    """The items a slot can give, by tier, lowest first."""
    if slot in content.items:
        return {content.item(slot).tier: [slot]}
    name, _, tiers = slot.partition(" ")
    roles = GEAR if name == "gear" else (name,)
    low, high = _tiers(tiers)
    found: dict[int, list[str]] = {}
    for item in content.items.values():
        if role(item) in roles and low <= item.tier <= high and item.key not in BY_NAME_ONLY:
            found.setdefault(item.tier, []).append(item.key)
    return dict(sorted(found.items()))


def pick(rng: random.Random, content: Content, slot: str) -> str | None:
    """An item for a slot (a tier, then an item of it), or None if the game has nothing that fits."""
    tiers = list(candidates(content, slot).values())
    if not tiers:
        return None
    keys = tiers[0] if len(tiers) == 1 else rng.choice(tiers)
    return keys[0] if len(keys) == 1 else rng.choice(keys)


def one_of(rng: random.Random, content: Content, slots: list[str]) -> str | None:
    """A chest's or a stash's single item: one of its slots, then an item for that slot."""
    return pick(rng, content, rng.choice(slots))


def where(content: Content, key: str) -> list[str]:
    """Where an item can turn up ("floor 3", "hidden stashes"...), for the debug screen."""
    found = [place for place, slots in PLACES
             if any(key in keys for slot in slots for keys in candidates(content, slot).values())]
    found += [f"{content.themes[theme].name}'s own trinket" for theme, trinket in DUNGEON_TRINKETS.items()
              if trinket == key and theme in content.themes]
    return found
