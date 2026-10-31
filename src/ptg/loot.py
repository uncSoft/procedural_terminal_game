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

So does every piece of gear and every trinket that lasts (single): once it's turned up anywhere, lying about, on a
counter, in a chest, it never turns up again that run, and a slot with none left for it gives a potion instead. Run 66
found Gulliver's sword three times, and two Rabbit's Feet (two of a thing count once).

Shops (world._shop) sell what chests keep, and things kept for shops alone (`found = ["shop"]`). Granny Gristle's
counter has a potion no better than the floor, gear of the floor's tier, a bomb or a small key, and a trinket, or now
and then something rare; the rare Granny Kamultruk's has the strong potions, the best gear and two rare things, dearer.
"""

from __future__ import annotations

import math
import random

from .content import FOUND_IN, Content, ItemDef

GEAR = ("weapon", "armor")
PICKUP_KEYS = ("bomb", "small_key")
BY_NAME_ONLY = {"lucky_charm", *PICKUP_KEYS}

FLOORS = {  # each floor spreads these through its rooms (see world._place_loot), with its dungeon's own trinket
    1: ["gear 1", "potion 1", "potion 1", "food 0", "bomb", "small_key"],
    2: ["gear 2", "potion 1", "escape 1+", "food 1+", "bomb", "small_key"],  # loot spread out is found more: a potion less
    3: ["potion 2+", "potion 1", "potion 1", "gear 2", "small_key"],
    4: ["potion 2+", "potion 2+", "potion 1", "gear 3", "small_key", "pure"],  # (Pure: in an egg, a shed skin...)
    5: ["potion 3+", "potion 2+", "potion 2+", "gear 3", "small_key"],
}
DUNGEON_TRINKETS = {"sunken_crypt": "holy_water", "goblin_warren": "bag_of_marbles", "overgrown_ruins": "oil_flask",
                    "norfel": "holy_water", "underbloom": "oil_flask"}  # (Serpentis hates it; a torch drinks it)
STASH = {  # each floor's hidden stash holds one of its floor's ("rare -1": a rare thing of tier 1 or less)
    1: ["weapon 2", "armor 2", "potion 2", "lucky_charm", "rare -1"],
    2: ["weapon 2", "armor 2", "potion 2", "lucky_charm", "rare -2"],
    3: ["weapon 3+", "armor 3+", "potion 2+", "lucky_charm", "rare"],
    4: ["weapon 3+", "armor 3+", "potion 3+", "lucky_charm", "rare"],
    5: ["weapon 3+", "armor 3+", "potion 3+", "lucky_charm", "rare"],
}
MOST_PER_ROOM = 2  # things in a room's hiding places, at most (a quest's own thing aside): more is a treasure trove
ESSENTIAL = ("small_key", "bomb")  # placed first, and always: a chest and a cracked wall wait on them
CHESTS = {  # a chest holds one of its floor's ("rare -1": a rare thing of tier 1 or less)
    1: ["armor 1", "trinket", "escape 1", "potion 1", "rare -1"],
    2: ["armor 2", "weapon 2", "potion 2", "lucky_charm", "rare -2"],
    3: ["armor 3+", "weapon 3+", "potion 2+", "lucky_charm", "rare"],
    4: ["armor 3+", "weapon 3+", "potion 3+", "lucky_charm", "rare"],
    5: ["armor 3+", "weapon 3+", "potion 3+", "lucky_charm", "rare"],
}
SECRET = ["rare"]  # what a floor's secret room keeps, any tier: it's hard to find
# What the warden by the stairs drops a third of the time, and an elite now and then: rare things, tier capped by the
# floor (so the best of them come from the elites of the last floor, and secret rooms). A rare thing a floor, about,
# from its secret room: more, and nothing felt rare (docs/plans/combat-and-balance.md §2).
WARDEN = {1: ["rare -1"], 2: ["rare -2"], 3: ["rare"], 4: ["rare"], 5: ["rare"]}
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
# On the floor above one with poison of its own, a shop always (rules._ask: asked, she brings out the snakeskin); and
# above a dark one, so you can buy a light before you go down.
BEFORE_STATUS_SHOP_CHANCE = 1.0
LIGHTS = ("torch", "oil_flask")  # on a dark floor and the one above it, she always has these, two of each (light.py)
SNAKESKIN, SNAKESKIN_PRICE = "shed_snakeskin", 80
# What a floor down adds to a ware's price: a quarter (it was a tenth, and gold found grows with the floor, so run 66
# had 866 gold at the end and nothing to spend it on); and a shrine's full heal, a floor down (run 66 paid 10 on
# floor 5).
PRICE_RISE, SHRINE_GOLD = 0.25, 10
SHINY_WARES = ["potion 2+", "gear 3+", "rare", "rare"]
FINDS = ["food 0", "food 0", "potion 1", "escape 1", "trinket"]  # what a stunt that pays off can turn up
EVERYDAY = "floor"  # the place of a floor's scattered loot, a monster's drop or a find: no rare things here
# The best weapon or armor anything on a floor gives, its tier: one above the floor's monsters' (world.tier_for), so a
# floor-1 stash, chest, secret room or Granny Kamultruk can give tier 2 but not the Moonsilver Vest or the Sword Still
# in the Stone (tier 3, the best there is but Bloodbath), which secret rooms and her counter gave from floor 1. And an
# elite (a Hulking Orc, a Frenzied Dire Wolf) leaves no gear at all: gear comes from where you look, and from the
# warden by the stairs, not from the floor's crowd (four of JT's last eight runs had a Snitch off an elite on floor 2,
# one an Adamant Stewpot off a Hulking Cinder Imp). NO_GEAR as the most: none.
GEAR_ABOVE, NO_GEAR = 1, -1

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


SPENT = {"throw", "reveal", "torch"}  # a trinket with one of these powers gets used up: another one's no waste


def single(item: ItemDef) -> bool:
    """One of a kind: a rare thing, a piece of gear, or a trinket that lasts (not one that's thrown, burnt for light or
    used up, nor a bomb or a small key). Each turns up once a run (state.rares)."""
    if rare(item) or item.kind in GEAR:
        return True
    return item.kind == "trinket" and item.key not in PICKUP_KEYS and not SPENT & set(item.powers)


RARITIES = ("Common", "Common", "Uncommon", "Fine", "Epic")  # a thing's rarity by its tier; a rare one's Rare


def rarity(item: ItemDef) -> str:
    """How rare a thing is, in a word: Rare (rare), or its tier's (RARITIES)."""
    return "Rare" if rare(item) else RARITIES[max(0, min(len(RARITIES) - 1, item.tier))]


def allowed(item: ItemDef, place: str) -> bool:
    """Whether an item can turn up in a place: everyday loot anywhere, a rare thing only where it's kept (and a shop
    sells what chests keep, too)."""
    if item.found:
        return place in item.found or (place == "shop" and "chest" in item.found)
    return place != EVERYDAY if "rare" in item.tags else True


def most_gear(state) -> int:
    """The best weapon or armor (its tier) anything on this floor gives: GEAR_ABOVE its monsters' tier."""
    from .world import tier_for  # (world places loot: it imports this module)

    return tier_for(state.floor, state.floors_total) + GEAR_ABOVE


def candidates(content: Content, slot: str, place: str = EVERYDAY, taken=(), most: float = math.inf
               ) -> dict[int, list[str]]:
    """The items a slot can give in a place, by tier, lowest first, leaving out the one-of-a-kind things this run has
    had (`taken`), and any weapon or armor above the tier `most` (most_gear)."""
    if slot in content.items:
        return {} if slot in taken else {content.item(slot).tier: [slot]}
    name, _, tiers = slot.partition(" ")
    roles = GEAR if name == "gear" else (name,)
    low, high = _tiers(tiers)
    found: dict[int, list[str]] = {}
    for item in content.items.values():
        if item.key in BY_NAME_ONLY or item.key in taken or not allowed(item, place) or \
                role(item) in GEAR and item.tier > most:
            continue
        if (rare(item) if name == "rare" else role(item) in roles) and low <= item.tier <= high:
            found.setdefault(item.tier, []).append(item.key)
    return dict(sorted(found.items()))


def pick(rng: random.Random, content: Content, slot: str, place: str = EVERYDAY, taken=(), most: float = math.inf
         ) -> str | None:
    """An item for a slot (a tier, then an item of it), or None if the game has nothing that fits. Rare things are
    hand-placed already, so each is as likely as the next: a lone tier-0 joke shouldn't be half of every prize."""
    tiers = list(candidates(content, slot, place, taken, most).values())
    if not tiers:
        return None
    if slot.startswith("rare"):
        tiers = [[key for keys in tiers for key in keys]]
    keys = tiers[0] if len(tiers) == 1 else rng.choice(tiers)
    return keys[0] if len(keys) == 1 else rng.choice(keys)


def one_of(rng: random.Random, content: Content, slots: list[str], place: str = EVERYDAY, taken=(),
           most: float = math.inf) -> str | None:
    """A chest's or a stash's single item: one of its slots, then an item for that slot."""
    return pick(rng, content, rng.choice(slots), place, taken, most)


def owned(state, content: Content) -> list[str]:
    """The gear you have already, worn or carried: no use finding a second of it (run 59's two Iron Helms)."""
    keys = [state.player.weapon, state.player.armor, *state.player.inventory]
    return [k for k in dict.fromkeys(keys) if k in content.items and role(content.item(k)) in GEAR]


def produce(rng: random.Random, content: Content, rares: list[str], slots: list[str], place: str,
            have: list[str] = (), most: float = math.inf) -> str | None:
    """One of a special place's slots, filled (no gear above the tier `most`: most_gear); a one-of-a-kind thing it
    gives is noted in `rares` so it never comes twice, and gear you `have` already isn't given again if anything else
    fits: if the slot drawn has only what you have, the others are tried first (a chest's "weapon 3+" with your
    Silvered Blade the only one gave a second)."""
    key = None
    if have:
        taken = [*rares, *have]
        key = one_of(rng, content, slots, place, taken, most) or \
            next((k for slot in slots for k in [pick(rng, content, slot, place, taken, most)] if k), None)
    key = key or one_of(rng, content, slots, place, rares, most)
    if key is None:  # nothing left for here: every one of it has turned up already
        key = pick(rng, content, INSTEAD.get(place, INSTEAD_OF_RARE), place, rares)
    return noted(content, rares, key)


def give(rng: random.Random, content: Content, rares: list[str], slot: str, place: str = EVERYDAY,
         most: float = math.inf) -> str | None:
    """A slot filled for this run, as `produce` fills a special place's (a floor's scattered loot, a lucky find, the
    gear on the Matriarch's last visitor): a one-of-a-kind thing this run has had already is never given again, and
    one it gives is noted; with none left, a potion."""
    key = pick(rng, content, slot, place, rares, most)
    if key is None and slot.partition(" ")[0] in (*GEAR, "gear", "trinket"):
        key = pick(rng, content, INSTEAD_OF_RARE, place, rares)
    return noted(content, rares, key)


def noted(content: Content, rares: list[str], key: str | None) -> str | None:
    """A key just given, noted in `rares` if it's one of a kind (single), so it's never given again."""
    if key and single(content.item(key)) and key not in rares:
        rares.append(key)
    return key


def wares(rng: random.Random, content: Content, rares: list[str], keeper: str, floor: int,
          cure_for: str = "", lights: bool = False, most: float = math.inf) -> list[tuple[str, int, int]]:
    """What a shopkeeper lays out on her counter (rare things noted in `rares`, as anywhere), with their prices and
    how many: potions come in twos (STOCK). On a floor with a status of its own (`cure_for`: floor 4's poison), she
    always has its cure, two of it; on a dark floor or the one above it (`lights`), torches and lamp oil (LIGHTS). No
    gear above the tier `most` (most_gear)."""
    if keeper == SHINY:
        slots = SHINY_WARES
    else:
        slots = [f"potion -{floor}", f"gear {min(floor, 3)}", rng.choice(["bomb", "small_key"]),
                 f"rare -{floor}" if rng.random() < GRISTLE_RARE else "trinket"]
    out: list[tuple[str, int, int]] = []
    for slot in slots:
        key = produce(rng, content, rares, [slot], "shop", most=most)
        if key and key not in [k for k, _, _ in out]:
            out.append((key, price(content.item(key), floor, keeper == SHINY), STOCK.get(role(content.item(key)), 1)))
    for item in sorted(content.items.values(), key=lambda i: i.key):
        if cure_for and cure_for in item.cures and not item.heal:
            out.append((item.key, price(item, floor, keeper == SHINY), STOCK["cure"]))
    for key in LIGHTS if lights else ():
        if key in content.items:  # (two of each, even if one's on the counter already: it's what she's there for)
            out = [ware for ware in out if ware[0] != key]
            out.append((key, price(content.item(key), floor, keeper == SHINY), 2))
    return out


def price(item: ItemDef, floor: int, shiny: bool = False) -> int:
    """What a ware costs: by what it is and how good, a quarter more on each floor down (PRICE_RISE), more for
    something rare, and a quarter more again at Granny Kamultruk's. In fives, rounded up (she's a shopkeeper)."""
    base = {"bomb": 12, "small_key": 15}.get(item.key)
    if base is None:
        base = {"potion": 15 + 20 * (item.tier - 1), "food": 6 + 6 * item.tier, "escape": 20, "cure": 45,
                "weapon": 5 + 20 * item.tier, "armor": 5 + 20 * item.tier}.get(role(item), 20 + 10 * item.tier)
        base *= 1.6 if rare(item) else 1
    cost = base * (1 + PRICE_RISE * (floor - 1)) * (1.25 if shiny else 1)
    return max(5, 5 * math.ceil(cost / 5 - 1e-9))


def shrine_price(floor: int) -> int:
    """What a shrine asks for a full heal: SHRINE_GOLD a floor down."""
    return SHRINE_GOLD * floor


def where(content: Content, key: str) -> list[str]:
    """Where an item can turn up ("floor 3", "hidden stashes"...), for the debug screen."""
    found = [name for name, slots, place in PLACES
             if any(key in keys for slot in slots for keys in candidates(content, slot, place).values())]
    found += [f"{content.themes[theme].name}'s own trinket" for theme, trinket in DUNGEON_TRINKETS.items()
              if trinket == key and theme in content.themes]
    item = content.item(key)
    found += [f"dropped by {content.monster(place).name}" for place in item.found if place not in FOUND_IN]
    return found
