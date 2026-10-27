"""Norfel's hazards (hazards.py): one poison river on the way to the boss, crossed as you choose; one gas vent
somewhere else, over a cache; nothing rolled as you walk in. And Granny's snakeskin, to get ready for them."""

from conftest import put_monster

from ptg import hazards, loot, rules, statuses
from ptg.models import OPPOSITE
from ptg.rules import available_actions, journey, perform
from ptg.world import build_floor, generate


def norfel(content, seed=7):
    state = generate(seed, content=content)
    state.floor = 4
    build_floor(state, content)
    for room in state.rooms:
        if not room.is_boss:
            room.monster = None
    return state


def ids(state, content):
    return [a.id for a in available_actions(state, content)]


def to_the_river(state, content):
    """Walk the way to the boss as far as the river's room, coming in on its near bank."""
    river = next(r for r in state.rooms if r.river)
    path = hazards._path(state.rooms, next(r.id for r in state.rooms if r.is_boss))
    for room_id in path[1:path.index(river.id) + 1]:
        perform(state, content, "go:" + next(d for d, e in state.room.exits.items() if e.to == room_id))
    assert state.room is river and not river.far
    return river


def test_one_river_on_the_way_to_the_boss_and_one_vent_never_next_door(content):
    for seed in range(40):
        state = norfel(content, seed)
        rivers = [r for r in state.rooms if r.river]
        vents = [r for r in state.rooms if r.vent]
        assert len(rivers) == len(vents) == 1
        river, vent = rivers[0], vents[0]
        path = hazards._path(state.rooms, next(r.id for r in state.rooms if r.is_boss))
        assert river.id in (path[1:-2] or path[1:-1]) and river.archetype == "river_crossing"  # (by the boss's door
        # only when there's no other room on the way)
        assert state.rooms[river.exits[river.across].to].id == path[path.index(river.id) + 1]  # (the way on)
        assert vent.archetype == "vent_field" and vent.vent == "live" and vent.id not in (0, path[-1])
        assert vent.id not in {e.to for e in river.exits.values()}
        assert [f for f in vent.features if f.trapped and f.name == hazards.CACHE and (f.loot or f.gold)]
    for number in (1, 2, 3):
        state = generate(3, content=content)
        if number > 1:
            state.floor = number
            build_floor(state, content)
        assert not [r for r in state.rooms if r.river or r.vent]


def test_nothing_rolls_as_you_walk_in(content):
    state = norfel(content)
    state.player.agility = state.player.wits = -50
    to_the_river(state, content)
    vent = next(r for r in state.rooms if r.vent)
    state.room_id = next(e.to for e in vent.exits.values())
    events = perform(state, content, "go:" + next(d for d, e in state.room.exits.items() if e.to == vent.id))
    assert not statuses.has(state, "poison") and not [e for e in events if e.dice]
    assert "A gas vent hisses in the floor" in events[0].text  # (seen as you come in)


def test_the_way_on_is_across_the_river_leap_wade_or_vault(content):
    state = norfel(content)
    river = to_the_river(state, content)
    on = f"go:{river.across}"
    assert on not in ids(state, content) and "across the poison river" in rules.why_not(state, content, on)
    assert {"cross:leap", "cross:wade"} <= set(ids(state, content)) and "cross:vault" not in ids(state, content)
    state.player.inventory.append("ten_foot_pole")
    vault = next(a for a in available_actions(state, content) if a.id == "cross:vault")
    assert vault.label == "Vault the river with your Ten-Foot Pole" and vault.hint == "no roll"
    events = perform(state, content, "cross:vault")
    assert river.far and river.stones and not statuses.has(state, "poison") and not events[0].dice
    assert on in ids(state, content) and not [a for a in ids(state, content) if a.startswith("cross:")]


def test_a_missed_leap_poisons_you_but_youre_across_and_know_the_stones(content):
    state = norfel(content)
    river = to_the_river(state, content)
    state.player.agility = -50
    events = perform(state, content, "cross:leap")
    assert events[0].dice.label == "agility (leap the river)" and events[0].data["rerollable"]
    assert statuses.has(state, "poison") and river.far and river.stones
    statuses.cure(state, "poison")
    perform(state, content, f"go:{OPPOSITE[river.across]}")  # back, and in again: a stroll now
    events = perform(state, content, "go:" + next(d for d, e in state.room.exits.items() if e.to == river.id))
    assert not [e for e in events if e.dice] and f"go:{river.across}" in ids(state, content)


def test_wading_poisons_you_unless_you_wear_the_snakeskin(content):
    for skin, poisoned in ((False, True), (True, False)):
        state = norfel(content)
        river = to_the_river(state, content)
        if skin:
            state.player.armor = loot.SNAKESKIN
        wade = next(a for a in available_actions(state, content) if a.id == "cross:wade")
        assert wade.hint == ("your Shed Snakeskin keeps it off" if skin else "you'll be poisoned")
        perform(state, content, "cross:wade")
        assert statuses.has(state, "poison") == poisoned and river.far


def test_quick_travel_wont_cross_a_river_you_havent(content):
    state = norfel(content)
    river = to_the_river(state, content)
    beyond = state.rooms[river.exits[river.across].to]
    beyond.visited = True  # (as if you'd come at it some other way)
    back = state.rooms[river.exits[OPPOSITE[river.across]].to]
    state.room_id = back.id
    assert journey(state, beyond.id) is None
    river.stones = True
    assert journey(state, beyond.id)


def test_the_vents_cache_is_yours_disarmed_or_grabbed_with_a_faceful_of_gas(content):
    state = norfel(content)
    vent = next(r for r in state.rooms if r.vent)
    state.room_id, vent.visited = vent.id, True
    index = next(i for i, f in vent.visible_features() if f.trapped)
    search = next(a for a in available_actions(state, content) if a.id == f"search:{index}")
    assert search.hint == "the vent's live: it'll gas you"
    events = perform(state, content, f"search:{index}")
    assert statuses.has(state, "poison") and any(e.kind == "find" for e in events)


def test_no_resting_beside_a_live_vent_until_its_disarmed(content):
    state = norfel(content)
    vent = next(r for r in state.rooms if r.vent)
    state.room_id, state.player.hp = vent.id, 10
    assert "rest" not in ids(state, content) and "disarm it first" in rules.why_not(state, content, "rest")
    state.player.inventory.append("ten_foot_pole")
    assert next(a for a in available_actions(state, content) if a.id == "disarm").hint == "wits · Ten-Foot Pole +2"
    state.player.wits = -50
    perform(state, content, "disarm")
    assert statuses.has(state, "poison") and vent.vent == "live"
    state.player.wits, xp = 50, state.player.xp
    statuses.cure(state, "poison")
    events = perform(state, content, "disarm")
    assert "quiet for good" in events[0].text and vent.vent == "dead"
    assert state.player.xp == xp + hazards.VENT_XP and "rest" in ids(state, content)
    index = next(i for i, f in vent.visible_features() if f.trapped)
    perform(state, content, f"search:{index}")
    assert not statuses.has(state, "poison")  # (disarmed: the cache is safe)


def test_the_snakeskins_card_says_what_it_wards_and_pures_what_it_cures(content):
    from ptg import powers
    from ptg.ui.widgets import item_note

    skin = content.item(loot.SNAKESKIN)
    assert skin.wards == ["poison"] and "while you wear it: poison can't take hold of you" in powers.describe(skin)
    assert item_note(content, loot.SNAKESKIN) == "+2 defense · poison-proof"
    assert item_note(content, "pure") == "cures poison"
    assert powers.describe(content.item("pure")) == ["cures poison", "then the next poisoning won't take hold"]


def test_worn_the_snakeskin_keeps_poison_off_bites_rivers_and_vents(content):
    state = norfel(content)
    state.player.armor = loot.SNAKESKIN
    put_monster(state, content, key="serpentis", intent="heavy")
    state.player.agility, state.player.max_hp = -20, 500  # (every blow lands)
    state.player.hp = 500
    events = rules.monster_turn(state, content, __import__("random").Random(1))
    assert not statuses.has(state, "poison")
    assert any(e.kind == "guarded" and "never gets past your Shed Snakeskin" in e.text for e in events)
    assert hazards.grabbed(state, content)[-1].data.get("ward") and not statuses.has(state, "poison")
    state.player.armor = "scale_hauberk"  # (in your pack, it does nothing)
    state.player.inventory.append(loot.SNAKESKIN)
    hazards.grabbed(state, content)
    assert statuses.has(state, "poison")


def test_asked_on_floor_3_granny_brings_out_the_snakeskin_once(content):
    for seed in range(10):
        state = generate(seed, content=content)
        state.floor = 3
        build_floor(state, content)
        assert any(r.shop for r in state.rooms)  # (always a shop above the poison)
    shop = next(r for r in state.rooms if r.shop)
    state.room_id, before = shop.id, len(shop.shop.wares)
    events = perform(state, content, "ask")
    said = [e for e in events if e.data.get("moment") == "snakeskin"]
    assert said and "snakeskin" in said[0].text.lower() and any("fingers tingle" in e.text for e in events)
    ware = shop.shop.wares[-1]
    assert len(shop.shop.wares) == before + 1 and (ware.item, ware.price) == (loot.SNAKESKIN, loot.SNAKESKIN_PRICE)
    assert loot.SNAKESKIN in state.rares and rules._snakeskin(state, content) == []  # (once a run)
    state.floor = 2
    build_floor(state, content)
    other = next((r for r in state.rooms if r.shop), None)
    if other:
        state.room_id = other.id
        assert not [e for e in perform(state, content, "ask") if e.data.get("moment") == "snakeskin"]
