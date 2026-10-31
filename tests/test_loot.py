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
    everyday = {k for slots in (*loot.FLOORS.values(), loot.FINDS, [loot.DROP])
                for slot in slots for tier in loot.candidates(content, slot).values() for k in tier}
    assert not [k for k in everyday if loot.rare(content.item(k))]  # never just lying about
    assert "sword_still_in_the_stone" in str(loot.candidates(content, "rare", "secret"))
    assert "sword_still_in_the_stone" not in str(loot.candidates(content, "rare", "chest"))  # found = ["secret"]
    assert "the_compensator" not in str(loot.candidates(content, "rare -2", "warden"))  # tier 3: not from floor 1
    rares, rng = [], random.Random(3)
    secret_rares = [k for tier in loot.candidates(content, "rare", "secret").values() for k in tier]
    got = [loot.produce(rng, content, rares, loot.SECRET, "secret") for _ in range(len(secret_rares) + 2)]
    assert sorted(got[:len(secret_rares)]) == sorted(secret_rares)  # each once...
    assert all(content.item(k).heal for k in got[len(secret_rares):])  # ...then a good potion instead
    assert "dropped by" not in str(loot.where(content, "snitch")) and "secret rooms" in loot.where(content, "weighted_dice")


def test_roles_come_from_the_data(content):
    roles = {key: loot.role(item) for key, item in content.items.items()}
    assert roles["hand_axe"] == "weapon" and roles["scale_hauberk"] == "armor"
    assert roles["healing_potion"] == roles["superior_healing_potion"] == "potion"
    assert roles["stale_bread"] == roles["cheese_wheel"] == "food" and roles["smoke_bomb"] == "escape"
    assert roles["oil_flask"] == "trinket" and roles["warren_key"] == "key"


def test_helms_turn_up_wherever_armor_does(content):
    """An "armor" slot is anything you wear, body armor or a helm; "helm", only helms; "gear", all three. A helm you
    have on is gear you have already."""
    assert loot.role(content.item("hard_hat")) == "helm" and loot.role(content.item("leather_jerkin")) == "armor"
    worn = loot.candidates(content, "armor 1")[1]
    assert "hard_hat" in worn and "leather_jerkin" in worn
    assert loot.candidates(content, "helm 1") == {1: [k for k in worn if content.item(k).kind == "helm"]}
    assert "hard_hat" in loot.candidates(content, "gear 1")[1]
    rng = random.Random(2)
    assert {"hard_hat", "leather_jerkin"} <= {loot.pick(rng, content, "armor 1") for _ in range(100)}
    state = generate(1)
    state.player.helm = "hard_hat"
    assert "hard_hat" in loot.owned(state, content)


def test_slots_read_tiers_and_keep_some_items_by_name(content):
    assert loot.candidates(content, "gear 2") == {2: ["war_pick", "chain_shirt", "the_butcher_s_cleaver",
                                                      "smouldering_poker", "salted_harpoon", "studded_leather",
                                                      "ratskin_cloak", "horned_helm"]}  # (no Snitch, no Spork: rare)
    assert loot.candidates(content, "potion 2+") == {2: ["greater_healing_potion", "firebird_plume"],
                                                 3: ["superior_healing_potion"]}
    trinkets = [k for keys in loot.candidates(content, "trinket").values() for k in keys]
    assert "lucky_charm" not in trinkets and "oil_flask" in trinkets  # the charm only ever turns up by name
    assert loot.candidates(content, "lucky_charm") == {1: ["lucky_charm"]}
    assert "rusty_sword" not in str(loot.candidates(content, "weapon 1"))


def test_a_slot_with_one_item_gives_it_without_a_roll(content):
    rng = random.Random(5)
    before = rng.getstate()
    assert loot.pick(rng, content, "helm 2") == "horned_helm"
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
    for seed in range(150):  # (ten tier-1 pieces share floor 1's gear, and half the time its dungeon's own has it)
        state = generate(seed, content=content)
        found.update(k for room in state.rooms for f in room.features for k in f.loot)
    assert found["moon_axe"] and found["hand_axe"]  # they share floor 1's tier-1 gear
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
    assert loot.where(content, "superior_healing_potion") == ["floor 3", "floor 4", "floor 5", "floor 3 stashes",
                                                              "floor 4 stashes", "floor 5 stashes", "floor 3 chests",
                                                              "floor 4 chests", "floor 5 chests", "shops"]


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


def test_no_gear_on_a_floor_is_more_than_a_tier_above_its_monsters(content):
    """A floor-1 secret room or Granny Kamultruk's counter could give the Moonsilver Vest or the Sword Still in the
    Stone, tier 3, the best there is but Bloodbath."""
    from ptg.world import tier_for

    for seed in range(80):
        state = generate(seed, content=content)
        for floor in (1, 2):
            if floor > 1:
                state.floor = floor
                build_floor(state, content)
            most = tier_for(floor, state.floors_total) + loot.GEAR_ABOVE
            things = [k for r in state.rooms for k in [*r.items, *(k for f in r.features for k in f.loot)]]
            things += [w.item for r in state.rooms if r.shop for w in r.shop.wares]
            gear = [k for k in things if loot.role(content.item(k)) in loot.GEAR]
            assert all(content.item(k).tier <= most for k in gear), (seed, floor, gear)
    rng = random.Random(3)
    secret = {loot.produce(rng, content, [], loot.SECRET, "secret") for _ in range(400)}
    assert "moonsilver_vest" in secret  # (it's there to be found, deeper)
    secret = {loot.produce(rng, content, [], loot.SECRET, "secret", most=2) for _ in range(400)}
    assert not [k for k in secret if loot.role(content.item(k)) in loot.GEAR and content.item(k).tier > 2]
    shop = {k for _ in range(100) for k, _, _ in loot.wares(rng, content, [], loot.SHINY, 1, most=2)}
    assert not [k for k in shop if loot.role(content.item(k)) in loot.GEAR and content.item(k).tier > 2]


def test_a_dungeon_lays_out_its_own_gear_the_best_its_floor_allows(content):
    """JT: the new gear "we have to incorporate into the loot tables". The Crypt's floor gear is the Bucket where it's
    tier 1, the Salted Harpoon where it's tier 2, the Bell-Clapper Maul (a drowned chapel's bell) where it's 3: in
    place of the floor's other gear, never on top of it (more gear made a newcomer's run far easier); once had, a
    piece never comes again."""
    assert all(content.item(k).kind in ("weapon", "armor", "helm") and not loot.rare(content.item(k))
               for gear in loot.DUNGEON_GEAR.values() for k in gear)
    rng = random.Random(1)
    rares = []
    assert loot.dungeon_gear(rng, content, rares, "sunken_crypt", "gear 1") == "bucket_helm"
    assert loot.dungeon_gear(rng, content, rares, "sunken_crypt", "gear 2") == "salted_harpoon"
    assert loot.dungeon_gear(rng, content, rares, "sunken_crypt", "gear 3+", most=4) == "bell_clapper_maul"
    assert loot.dungeon_gear(rng, content, rares, "sunken_crypt", "gear 3") is None and \
        rares == ["bucket_helm", "salted_harpoon", "bell_clapper_maul"]
    assert loot.dungeon_gear(rng, content, [], "goblin_warren", "gear 2") is None  # (its kitchen's tier 1: floor 1's)
    assert loot.dungeon_gear(rng, content, [], "norfel", "gear 3") is None  # (Norfel has its own: the Pure, the skin)
    assert "The Sunken Crypt's own gear" in loot.where(content, "bell_clapper_maul")
    laid = 0
    for seed in range(20):  # on floor 1, in place of its gear
        state = generate(seed, content=content)
        mine = [k for r in state.rooms if not r.secret for f in r.features if not f.hidden for k in f.loot
                if k in loot.DUNGEON_GEAR.get(state.theme, [])]  # (a stash or a secret room may hold better)
        gear = [k for r in state.rooms if not r.secret for f in r.features if not f.hidden for k in f.loot
                if loot.role(content.item(k)) in loot.GEAR]
        assert all(content.item(k).tier == 1 for k in mine) and len(gear) <= 1, (seed, mine, gear)
        laid += bool(mine)
    assert 4 <= laid <= 16  # (half the time: the rest still turns up)


def test_an_elite_leaves_no_gear_but_the_warden_still_can(content):
    """Four of JT's last eight runs had a Snitch off an elite on floor 2 (a Hulking Orc, a Frenzied Dire Wolf...), and
    one an Adamant Stewpot off a Hulking Cinder Imp on floor 4: gear comes from where you look, and the warden."""
    from ptg.combat import _kept

    rng = random.Random(1)
    rng.random = lambda: 0.0  # (always something rare, if there's anything)
    for floor in (2, 3, 4):
        state = generate(1, content=content)
        state.floor = floor
        monster = put_monster(state, content)
        monster.elite = "Hulking"
        kept = [k for _ in range(10) for k in _kept(state, content, rng, monster)]
        assert not [k for k in kept if loot.role(content.item(k)) in loot.GEAR], (floor, kept)
        assert bool(kept) is (floor > 2)  # (nothing rare that isn't gear up there: nothing)
    state = generate(1, content=content)
    state.floor = 2
    monster = put_monster(state, content)
    monster.warden = True
    assert _kept(state, content, rng, monster) == ["snitch"]


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


def everything_placed(state, content) -> list[str]:
    """Every thing this floor has to find: hidden, lying about, on a counter, kept by a monster's keeper."""
    keys = []
    for room in state.rooms:
        keys += room.items + [k for f in room.features for k in f.loot]
        keys += [w.item for w in room.shop.wares] if room.shop else []
    return keys


def test_gear_and_lasting_trinkets_turn_up_once_a_run(content):
    """Run 66 found Gulliver's sword three times (bought on floor 3, then lying on floor 5, then in the Matriarch's
    cocoon) and two Rabbit's Feet: every piece of gear, and every trinket that lasts, is one of a kind now. Things
    used up (a torch, lamp oil, a bomb) still come again."""
    assert loot.single(content.item("gulliver_helper_sword")) and loot.single(content.item("chain_shirt"))
    assert loot.single(content.item("lucky_charm")) and loot.single(content.item("ten_foot_pole"))
    assert not [k for k in ("torch", "oil_flask", "bomb", "small_key", "healing_potion", "glow_stick")
                if loot.single(content.item(k))]
    for seed in range(40):
        state = generate(seed, content=content, floors=5)
        seen = [state.player.weapon]
        for floor in range(1, 6):
            if floor > 1:
                state.floor = floor
                build_floor(state, content)
            seen += [k for k in everything_placed(state, content) if loot.single(content.item(k))]
        twice = [k for k, n in Counter(seen).items() if n > 1]
        assert not twice, (seed, twice)
        assert not [k for k in set(seen) - set(state.rares) if not content.item(k).found]  # (a quest's: its own)


def test_a_slot_with_nothing_left_gives_a_potion(content):
    """Once every tier-3 weapon and armor has turned up, a floor's "gear 3" is a potion, not nothing."""
    rares = [k for k in content.items if loot.single(content.item(k))]
    key = loot.give(random.Random(1), content, rares, "gear 3")
    assert key and loot.role(content.item(key)) == "potion"
    assert loot.give(random.Random(1), content, [], "gear 3") in rares
