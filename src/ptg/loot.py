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

Where the top tiers land (the "+" slots): the best potion on floor 3, in its hidden stash and in floor-3 chests;
the best weapons and armor in floor 3's stash and chests; tier 2+ food and escapes on floor 2. A floor's stash is
its floor's best and no better (a tier-3 blade on floor 1 was too much), and no room holds more than MOST_PER_ROOM
things in its hiding places (world._place_loot).

The starting sword, the keys, bombs, small keys and the Lucky Charm (it has rules of its own) only ever turn up by
name.

Rare things (an item tagged `rare`, or one whose `found` names the only places it turns up) never lie about on a floor,
drop from an everyday monster or turn up from a stunt. They're kept for the places worth seeking out: chests, hidden
stashes, each floor's secret room, and the warden by the stairs (and other elites); an item can also name the monster
that drops it. Each comes at most once a run.

Shops (world._shop) sell what chests keep, and things kept for shops alone (`found = ["shop"]`). Granny Gristle's
counter has a potion no better than the floor, gear of the floor's tier, a bomb or a small key, and a trinket, or now
and then something rare; the rare Granny Kamultruk's has the strong potions, the best gear and two rare things, dearer.
"""

from __future__ import annotations

import math
import random

from .content import FOUND_IN, Content, ItemDef

GEAR = ("weapon", "armor")
BY_NAME_ONLY = {"lucky_charm", "bomb", "small_key"}

FLOORS = {  # each floor spreads these through its rooms (see world._place_loot), with its dungeon's own trinket
    1: ["gear 1", "potion 1", "potion 1", "food 0", "bomb", "small_key"],
    2: ["gear 2", "potion 1", "escape 1+", "food 1+", "bomb", "small_key"],  # loot spread out is found more: a potion less
    3: ["potion 2+", "potion 1", "potion 1", "gear 2", "small_key"],
    4: ["potion 2+", "potion 2+", "potion 1", "gear 3", "small_key", "pure"],  # (Pure: in an egg, a shed skin...)
}
DUNGEON_TRINKETS = {"sunken_crypt": "holy_water", "goblin_warren": "bag_of_marbles", "overgrown_ruins": "oil_flask",
                    "norfel": "holy_water"}  # (Serpentis hates it)
STASH = {  # each floor's hidden stash holds one of its floor's ("rare -1": a rare thing of tier 1 or less)
    1: ["weapon 2", "armor 2", "potion 2", "lucky_charm", "rare -1"],
    2: ["weapon 2", "armor 2", "potion 2", "lucky_charm", "rare -2"],
    3: ["weapon 3+", "armor 3+", "potion 2+", "lucky_charm", "rare"],
    4: ["weapon 3+", "armor 3+", "potion 3+", "lucky_charm", "rare"],
}
MOST_PER_ROOM = 2  # things in a room's hiding places, at most (a quest's own thing aside): more is a treasure trove
ESSENTIAL = ("small_key", "bomb")  # placed first, and always: a chest and a cracked wall wait on them
CHESTS = {  # a chest holds one of its floor's ("rare -1": a rare thing of tier 1 or less)
    1: ["armor 1", "trinket", "escape 1", "potion 1", "rare -1"],
    2: ["armor 2", "weapon 2", "potion 2", "lucky_charm", "rare -2"],
    3: ["armor 3+", "weapon 3+", "potion 2+", "lucky_charm", "rare"],
    4: ["armor 3+", "weapon 3+", "potion 3+", "lucky_charm", "rare"],
}
SECRET = ["rare"]  # what a floor's secret room keeps, any tier: it's hard to find
# What the warden by the stairs drops a third of the time, and an elite now and then: rare things, tier capped by the
# floor (so the best of them come from the elites of the last floor, and secret rooms). A rare thing a floor, about,
# from its secret room: more, and nothing felt rare (docs/plans/combat-and-balance.md §2).
WARDEN = {1: ["rare -1"], 2: ["rare -2"], 3: ["rare"], 4: ["rare"]}
WARDEN_DROP, ELITE_DROP = 0.35, 0.1  # how often
WARDEN_ELSE = ["small_key", "bomb"]  # what a warden leaves when it isn't something rare: it always leaves something
# What a place gives once there's no rare thing left for it: a potion, but a warden carries a small key (so floor 1's,
# with nothing rare that weak to give, always does). Not a strong potion: the run that hoarded ten never needed them.
INSTEAD = {"warden": "small_key"}
INSTEAD_OF_RARE = "potion 1"
DROP = "potion 1"  # what a slain monster sometimes leaves
SHOPKEEPER, SHINY = "granny_gristle", "granny_kamultruk"  # the shiny one: rarer, dearer, better stocked
SHOP_CHANCE, SHINY_CHANCE = 0.25, 0.15  # a floor has a shop; of the shops, how many are Granny Kamultruk's
STATUS_SHOP_CHANCE = 0.5  # a floor with a status of its own (Norfel's poison) has a shop more often
GRISTLE_RARE = 0.2  # how often Granny Gristle has something rare where her trinket would be
STOCK = {"potion": 2, "cure": 2}  # how many of a ware she has: one of anything else
# On the floor above one with poison of its own, a shop always (rules._ask: asked, she brings out the snakeskin).
BEFORE_STATUS_SHOP_CHANCE = 1.0
SNAKESKIN, SNAKESKIN_PRICE = "shed_snakeskin", 80
SHINY_WARES = ["potion 2+", "gear 3+", "rare", "rare"]
FINDS = ["food 0", "food 0", "potion 1", "escape 1", "trinket"]  # what a stunt that pays off can turn up
EVERYDAY = "floor"  # the place of a floor's scattered loot, a monster's drop or a find: no rare things here

PLACES = [*[(f"floor {f}", FLOORS[f], EVERYDAY) for f in FLOORS],
          *[(f"floor {f} stashes", STASH[f], "stash") for f in STASH],
          *[(f"floor {f} chests", CHESTS[f], "chest") for f in CHESTS],
          ("secret rooms", SECRET, "secret"), ("wardens and elites", WARDEN[3], "warden"),
          ("shops", ["potion 1+", "gear 1+", "trinket", "bomb", "small_key"] + SHINY_WARES, "shop"),
          ("slain monsters", [DROP], EVERYDAY), ("lucky finds", FINDS, EVERYDAY)]


def role(item: ItemDef) -> str:
    """The part an item plays in loot: weapon, armor, potion, food, escape, cure (Pure: a slain venomous monster's,
    and floor 4's shops), trinket or key."""
    if item.kind != "consumable":
        return item.kind
    if item.escape:
        return "escape"
    if "food" in item.tags:
        return "food"
    return "potion" if item.heal else "cure" if item.cures else "other"


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
    """Whether an item can turn up in a place: everyday loot anywhere, a rare thing only where it's kept (and a shop
    sells what chests keep, too)."""
    if item.found:
        return place in item.found or (place == "shop" and "chest" in item.found)
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


def owned(state, content: Content) -> list[str]:
    """The gear you have already, worn or carried: no use finding a second of it (run 59's two Iron Helms)."""
    keys = [state.player.weapon, state.player.armor, *state.player.inventory]
    return [k for k in dict.fromkeys(keys) if k in content.items and role(content.item(k)) in GEAR]


def produce(rng: random.Random, content: Content, rares: list[str], slots: list[str], place: str,
            have: list[str] = ()) -> str | None:
    """One of a special place's slots, filled; a rare thing it gives is noted in `rares` so it never comes twice, and
    gear you `have` already isn't given again if anything else fits: if the slot drawn has only what you have, the
    others are tried first (a chest's "weapon 3+" with your Silvered Blade the only one gave a second)."""
    key = None
    if have:
        taken = [*rares, *have]
        key = one_of(rng, content, slots, place, taken) or \
            next((k for slot in slots for k in [pick(rng, content, slot, place, taken)] if k), None)
    key = key or one_of(rng, content, slots, place, rares)
    if key is None and any(s.startswith("rare") for s in slots):  # no rare thing left for here
        key = pick(rng, content, INSTEAD.get(place, INSTEAD_OF_RARE), place, rares)
    if key and rare(content.item(key)):
        rares.append(key)
    return key


def wares(rng: random.Random, content: Content, rares: list[str], keeper: str, floor: int,
          cure_for: str = "") -> list[tuple[str, int, int]]:
    """What a shopkeeper lays out on her counter (rare things noted in `rares`, as anywhere), with their prices and
    how many: potions come in twos (STOCK). On a floor with a status of its own (`cure_for`: floor 4's poison), she
    always has its cure, two of it."""
    if keeper == SHINY:
        slots = SHINY_WARES
    else:
        slots = [f"potion -{floor}", f"gear {min(floor, 3)}", rng.choice(["bomb", "small_key"]),
                 f"rare -{floor}" if rng.random() < GRISTLE_RARE else "trinket"]
    out: list[tuple[str, int, int]] = []
    for slot in slots:
        key = produce(rng, content, rares, [slot], "shop")
        if key and key not in [k for k, _, _ in out]:
            out.append((key, price(content.item(key), floor, keeper == SHINY), STOCK.get(role(content.item(key)), 1)))
    for item in sorted(content.items.values(), key=lambda i: i.key):
        if cure_for and cure_for in item.cures and not item.heal:
            out.append((item.key, price(item, floor, keeper == SHINY), STOCK["cure"]))
    return out


def price(item: ItemDef, floor: int, shiny: bool = False) -> int:
    """What a ware costs: by what it is and how good, a tenth more on each floor down, more for something rare, and
    a quarter more again at Granny Kamultruk's. In fives, rounded up (she's a shopkeeper)."""
    base = {"bomb": 12, "small_key": 15}.get(item.key)
    if base is None:
        base = {"potion": 15 + 20 * (item.tier - 1), "food": 6 + 6 * item.tier, "escape": 20, "cure": 45,
                "weapon": 5 + 20 * item.tier, "armor": 5 + 20 * item.tier}.get(role(item), 20 + 10 * item.tier)
        base *= 1.6 if rare(item) else 1
    cost = base * (1 + 0.1 * (floor - 1)) * (1.25 if shiny else 1)
    return max(5, 5 * math.ceil(cost / 5 - 1e-9))


def where(content: Content, key: str) -> list[str]:
    """Where an item can turn up ("floor 3", "hidden stashes"...), for the debug screen."""
    found = [name for name, slots, place in PLACES
             if any(key in keys for slot in slots for keys in candidates(content, slot, place).values())]
    found += [f"{content.themes[theme].name}'s own trinket" for theme, trinket in DUNGEON_TRINKETS.items()
              if trinket == key and theme in content.themes]
    item = content.item(key)
    found += [f"dropped by {content.monster(place).name}" for place in item.found if place not in FOUND_IN]
    return found
