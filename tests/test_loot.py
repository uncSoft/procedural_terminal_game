"""Loot by role and tier (ptg/loot.py): new items drop without code changes, and the odds stay put."""

import random
from collections import Counter
from dataclasses import replace

from conftest import put_monster
from ptg import loot
from ptg.combat import defeat
from ptg.content import ItemDef
from ptg.rules import gain_item, heal_verb, perform
from ptg.world import build_floor, generate


def with_items(content, *items: ItemDef):
    return replace(content, items={**content.items, **{i.key: i for i in items}})


def test_every_slot_has_something_to_give(content):
    slots = [s for floor in loot.FLOORS.values() for s in floor] + loot.STASH + [loot.DROP] + loot.FINDS
    slots += [s for chest in loot.CHESTS.values() for s in chest]
    empty = [slot for slot in slots if not loot.candidates(content, slot)]
    assert not empty, f"loot asks for things the game doesn't have: {empty}"
    assert all(t in content.items for t in loot.DUNGEON_TRINKETS.values())


def test_roles_come_from_the_data(content):
    roles = {key: loot.role(item) for key, item in content.items.items()}
    assert roles["hand_axe"] == "weapon" and roles["scale_hauberk"] == "armor"
    assert roles["healing_potion"] == roles["superior_healing_potion"] == "potion"
    assert roles["stale_bread"] == roles["cheese_wheel"] == "food" and roles["smoke_bomb"] == "escape"
    assert roles["oil_flask"] == "trinket" and roles["warren_key"] == "key"


def test_slots_read_tiers_and_keep_some_items_by_name(content):
    assert loot.candidates(content, "gear 2") == {2: ["war_pick", "chain_shirt"]}
    assert loot.candidates(content, "potion 2+") == {2: ["greater_healing_potion"], 3: ["superior_healing_potion"]}
    trinkets = [k for keys in loot.candidates(content, "trinket").values() for k in keys]
    assert "lucky_charm" not in trinkets and "oil_flask" in trinkets  # the charm only ever turns up by name
    assert loot.candidates(content, "lucky_charm") == {1: ["lucky_charm"]}
    assert "rusty_sword" not in str(loot.candidates(content, "weapon 1"))


def test_a_slot_with_one_item_gives_it_without_a_roll(content):
    rng = random.Random(5)
    before = rng.getstate()
    assert loot.pick(rng, content, "weapon 1") == "hand_axe"
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
    assert loot.where(content, "superior_healing_potion") == ["floor 3", "hidden stashes", "floor 3 chests"]


def test_food_is_eaten_and_found_things_name_themselves(content):
    assert heal_verb(content.item("cheese_wheel")) == "Eat" and heal_verb(content.item("healing_potion")) == "Drink"
    roast = ItemDef(key="roast_boar", name="Roast Boar", kind="consumable", heal=12, tier=2, tags=["food"])
    assert heal_verb(roast) == "Eat"
    state = generate(3)
    index, feature = next((i, f) for i, f in state.room.visible_features())
    feature.loot = ["smoke_bomb"]
    events = perform(state, content, f"search:{index}")
    assert [(e.kind, e.data.get("item")) for e in events if e.data.get("item")] == [("find", "smoke_bomb"),
                                                                                 ("take", "smoke_bomb")]
    assert gain_item(state, content, "hand_axe")[0].data == {"item": "hand_axe"}


def test_a_slain_monster_drops_what_loot_says(content):
    state = generate(2)
    put_monster(state, content, hp=1)
    rng = random.Random()
    rng.random = lambda: 0.0  # always drop
    events = defeat(state, content, rng, how="slain")
    dropped = next(e for e in events if e.kind == "drop")
    assert dropped.data == {"item": "healing_potion"} and "healing_potion" in state.room.items
    assert dropped.text.endswith("dropped a Healing Potion.")
