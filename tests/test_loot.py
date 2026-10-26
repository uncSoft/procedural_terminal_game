"""Loot by role and tier (ptg/loot.py): new items drop without code changes, and the odds stay put."""

import random
from collections import Counter
from dataclasses import replace

from conftest import put_monster
from ptg import loot, npcs
from ptg.combat import defeat
from ptg.content import ItemDef
from ptg.rules import heal_verb, perform
from ptg.world import build_floor, generate


def with_items(content, *items: ItemDef):
    return replace(content, items={**content.items, **{i.key: i for i in items}})


def test_every_slot_has_something_to_give(content):
    places = loot.PLACES + [(f"floor {f} wardens", slots, "warden") for f, slots in loot.WARDEN.items()]
    empty = [(name, slot) for name, slots, place in places for slot in slots  # (a rare slot falls back on a potion)
             if not loot.candidates(content, slot, place) and not slot.startswith("rare")]
    assert not empty, f"loot asks for things the game doesn't have: {empty}"
    assert all(t in content.items for t in loot.DUNGEON_TRINKETS.values())


def test_rare_things_turn_up_only_where_theyre_kept_and_only_once(content):
    everyday = {k for slots in (loot.FLOORS[1], loot.FLOORS[2], loot.FLOORS[3], loot.FINDS, [loot.DROP])
                for slot in slots for tier in loot.candidates(content, slot).values() for k in tier}
    assert not [k for k in everyday if loot.rare(content.item(k))]  # never just lying about
    assert "sword_still_in_the_stone" in str(loot.candidates(content, "rare", "secret"))
    assert "sword_still_in_the_stone" not in str(loot.candidates(content, "rare", "chest"))  # found = ["secret"]
    assert "the_compensator" not in str(loot.candidates(content, "rare -2", "warden"))  # tier 3: not from floor 1
    rares, rng = [], random.Random(3)
    got = [loot.produce(rng, content, rares, loot.SECRET, "secret") for _ in range(12)]
    secret_rares = [k for tier in loot.candidates(content, "rare", "secret").values() for k in tier]
    assert sorted(got[:len(secret_rares)]) == sorted(secret_rares)  # each once...
    assert all(content.item(k).heal for k in got[len(secret_rares):])  # ...then a good potion instead
    assert "dropped by" not in str(loot.where(content, "snitch")) and "secret rooms" in loot.where(content, "weighted_dice")


def test_roles_come_from_the_data(content):
    roles = {key: loot.role(item) for key, item in content.items.items()}
    assert roles["hand_axe"] == "weapon" and roles["scale_hauberk"] == "armor"
    assert roles["healing_potion"] == roles["superior_healing_potion"] == "potion"
    assert roles["stale_bread"] == roles["cheese_wheel"] == "food" and roles["smoke_bomb"] == "escape"
    assert roles["oil_flask"] == "trinket" and roles["warren_key"] == "key"


def test_slots_read_tiers_and_keep_some_items_by_name(content):
    assert loot.candidates(content, "gear 2") == {2: ["war_pick", "chain_shirt"]}  # the Snitch is rare: not here
    assert loot.candidates(content, "potion 2+") == {2: ["greater_healing_potion"], 3: ["superior_healing_potion"]}
    trinkets = [k for keys in loot.candidates(content, "trinket").values() for k in keys]
    assert "lucky_charm" not in trinkets and "oil_flask" in trinkets  # the charm only ever turns up by name
    assert loot.candidates(content, "lucky_charm") == {1: ["lucky_charm"]}
    assert "rusty_sword" not in str(loot.candidates(content, "weapon 1"))


def test_a_slot_with_one_item_gives_it_without_a_roll(content):
    rng = random.Random(5)
    before = rng.getstate()
    assert loot.pick(rng, content, "weapon 2") == "war_pick"
    assert rng.getstate() == before  # so a seed's dungeon only changes where there's something new to choose


def test_a_tier_is_picked_before_an_item(content):
    """Five new tier-3 potions don't make tier 3 five times as likely."""
    new = [ItemDef(key=f"elixir_{n}", name=f"Elixir {n}", kind="consumable", heal=24, tier=3) for n in range(5)]
    content = with_items(content, *new)
    rng = random.Random(1)
    tiers = Counter(content.item(loot.pick(rng, content, "potion 2+")).tier for _ in range(4000))
    assert abs(tiers[3] / 4000 - 0.5) < 0.03


def test_a_new_item_drops_where_its_kind_and_tier_do(content):
    axe = ItemDef(key="moon_axe", name="Moon Axe", kind="weapon", damage="1d8", tier=1, tags=["sharp"])
    content = with_items(content, axe)
    found = Counter()
    for seed in range(60):
        state = generate(seed, content=content)
        found.update(k for room in state.rooms for f in room.features for k in f.loot)
    assert found["moon_axe"] and found["hand_axe"]  # they share floor 1's tier-1 weapon
    assert "floor 1" in loot.where(content, "moon_axe")


def test_the_best_potion_is_on_floor_three_or_hidden(content):
    places = Counter()
    for seed in range(40):
        state = generate(seed)
        for floor in (1, 2, 3):
            if floor > 1:
                state.floor = floor
                build_floor(state, content)
            for room in state.rooms:
                for feature in room.features:
                    if "superior_healing_potion" in feature.loot:
                        places["stash" if feature.hidden else f"floor {floor}"] += 1
                if "superior_healing_potion" in room.items:
                    places[f"floor {floor}"] += 1
    assert places["floor 3"] and places["stash"]
    assert not places["floor 1"] and not places["floor 2"]
    assert loot.where(content, "superior_healing_potion") == ["floor 3", "floor 3 stashes", "floor 3 chests", "shops"]


def test_food_is_eaten_and_found_things_name_themselves(content):
    assert heal_verb(content.item("cheese_wheel")) == "Eat" and heal_verb(content.item("healing_potion")) == "Drink"
    roast = ItemDef(key="roast_boar", name="Roast Boar", kind="consumable", heal=12, tier=2, tags=["food"])
    assert heal_verb(roast) == "Eat"
    state = generate(3)
    index, feature = next((i, f) for i, f in state.room.visible_features())
    feature.loot = ["smoke_bomb"]
    events = perform(state, content, f"search:{index}")
    assert [(e.kind, e.data.get("item")) for e in events if e.data.get("item")] == [("find", "smoke_bomb")]
    assert "smoke_bomb" in state.room.items and "smoke_bomb" not in state.player.inventory  # to take, or leave


def test_a_slain_monster_drops_what_loot_says(content):
    state = generate(2)
    put_monster(state, content, hp=1)
    rng = random.Random()
    rng.random = lambda: 0.0  # always drop
    events = defeat(state, content, rng, how="slain")
    dropped = next(e for e in events if e.kind == "drop")
    assert dropped.data["item"] == "healing_potion" and "healing_potion" in state.room.items
    assert (dropped.data["how"], dropped.data["to"]) == ("drop", "room")
    assert dropped.text.endswith("dropped a Healing Potion; it lies on the floor (not picked up).")  # (yet to be taken)


def test_no_room_is_a_treasure_trove_and_a_stash_is_its_floors_best_and_no_better(content):
    """Lucky Lenny's room had his tooth, a Silvered Blade, a Smoke Bomb and a flask of oil hidden in it: a tier-3 blade
    on floor 1 or 2, and four things to one room."""
    from ptg.world import build_floor, generate

    for seed in range(60):
        state = generate(seed, content=content)
        for floor in (1, 2, 3):
            if floor > 1:
                state.floor = floor
                build_floor(state, content)
            for room in state.rooms:
                if room.secret:
                    continue
                kept = [k for f in room.features for k in f.loot if k not in (npcs.BAD_TOOTH, state_key(content, state))]
                ghost = any(f.name.endswith("'s remains") for f in room.features)
                assert len(kept) <= loot.MOST_PER_ROOM + (2 if ghost else 0), (seed, floor, room.name, kept)
                if floor < 3:
                    assert not [k for f in room.features if f.hidden for k in f.loot if content.item(k).tier >= 3], \
                        (seed, floor, room.name)


def state_key(content, state):
    return content.themes[state.theme].key_item


def test_a_chest_doesnt_hand_you_gear_you_already_have(content):
    """Run 59 found a second Iron Helm while wearing one: gear you have isn't given again if anything else fits."""
    state = generate(1)
    state.player.armor = "iron_helm" if "iron_helm" in content.items else state.player.armor
    have = loot.owned(state, content)
    assert state.player.weapon in have
    given = {loot.produce(random.Random(seed), content, [], [f"gear {state.floor}"], "chest", have)
             for seed in range(200)}
    assert given and None not in given and not given & set(have)
