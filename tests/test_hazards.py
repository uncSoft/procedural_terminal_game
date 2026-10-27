"""Norfel's hazards (hazards.py): poison puddles in its doorways, rivers across its rooms, gas vents in its floors."""

from conftest import put_monster

from ptg import hazards, rules, statuses
from ptg.models import OPPOSITE
from ptg.rules import available_actions, perform
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


def doorway(state, puddle=True, river=False, vent=""):
    """Somewhere to step through: next door to the first room, with what's asked for in its way."""
    direction, exit_ = next((d, e) for d, e in state.room.exits.items() if not e.locked)
    there = state.rooms[exit_.to]
    exit_.puddle = there.exits[OPPOSITE[direction]].puddle = puddle
    there.river, there.vent = river, vent
    return direction, there


def test_only_a_poison_floor_has_them_and_never_where_youd_be_cornered(content):
    for seed in range(20):
        state = generate(seed, content=content)
        for number in (1, 2, 3, 4):
            if number > 1:
                state.floor = number
                build_floor(state, content)
            rooms = state.rooms
            hazardous = [r for r in rooms if r.vent or r.river or any(e.puddle for e in r.exits.values())]
            if number < 4:
                assert not hazardous
                continue
            assert hazardous
            for room in rooms:
                if room.id == 0 or room.is_boss or room.shop or room.secret:
                    assert not room.vent
                assert room.river == (room.archetype == "river_crossing")
                if room.archetype == "vent_field" and not (room.id == 0 or room.shop or room.secret):
                    assert room.vent == "hidden"
                for direction, exit_ in room.exits.items():
                    assert exit_.puddle == rooms[exit_.to].exits[OPPOSITE[direction]].puddle  # (both sides of it)
                    assert not (exit_.puddle and exit_.locked)


def test_a_puddle_is_jumped_or_landed_in(content):
    for agility, poisoned in ((50, False), (-50, True)):
        state = norfel(content)
        state.player.agility = agility
        direction, _ = doorway(state)
        events = perform(state, content, f"go:{direction}")
        jump = next(e for e in events if e.kind == "hazard")
        assert jump.dice.label == "agility (jump the puddle)" and jump.data["rerollable"]
        assert statuses.has(state, "poison") == poisoned
        assert ("land right in it" in jump.text) == poisoned


def test_poisoned_already_nothing_more_can_happen_so_theres_no_roll(content):
    state = norfel(content)
    statuses.inflict(state, "poison")
    direction, there = doorway(state, river=True, vent="hidden")
    events = perform(state, content, f"go:{direction}")
    assert not [e for e in events if e.kind == "hazard"] and there.vent == "seen"  # (you smell it all the same)


def test_pure_in_your_blood_stops_what_would_have_poisoned_you(content):
    state = norfel(content)
    state.player.agility = -50
    statuses.guard(state, "poison", 1)
    direction, _ = doorway(state)
    events = perform(state, content, f"go:{direction}")
    assert not statuses.has(state, "poison") and any(e.kind == "guarded" for e in events)


def test_a_river_is_crossed_coming_in(content):
    state = norfel(content)
    state.player.agility = -50
    direction, _ = doorway(state, puddle=False, river=True)
    events = perform(state, content, f"go:{direction}")
    assert next(e for e in events if e.kind == "hazard").dice.label == "agility (cross the river)"
    assert statuses.has(state, "poison")


def test_a_vent_spotted_or_not_is_seen_after_and_walked_wide_of(content):
    for wits, poisoned in ((50, False), (-50, True)):
        state = norfel(content)
        state.player.wits = wits
        direction, there = doorway(state, puddle=False, vent="hidden")
        events = perform(state, content, f"go:{direction}")
        assert next(e for e in events if e.kind == "hazard").dice.label == "wits (spot the vent)"
        assert there.vent == "seen" and statuses.has(state, "poison") == poisoned
        statuses.cure(state, "poison")
        perform(state, content, f"go:{OPPOSITE[direction]}")
        again = perform(state, content, f"go:{direction}")
        assert not [e for e in again if e.kind == "hazard"]  # (you know where it is now)


def test_no_resting_beside_a_vent_until_its_disarmed(content):
    state = norfel(content)
    state.room.vent, state.player.hp = "seen", 10
    assert "rest" not in ids(state, content) and "disarm it first" in rules.why_not(state, content, "rest")
    disarm = next(a for a in available_actions(state, content) if a.id == "disarm")
    assert disarm.label == "Disarm the gas vent" and disarm.hint == "wits"
    state.player.inventory.append("ten_foot_pole")
    assert next(a for a in available_actions(state, content) if a.id == "disarm").hint == "wits · Ten-Foot Pole +2"
    state.player.wits = -50
    events = perform(state, content, "disarm")
    assert statuses.has(state, "poison") and state.room.vent == "seen"
    state.player.wits, xp = 50, state.player.xp
    statuses.cure(state, "poison")
    events = perform(state, content, "disarm")
    assert "quiet for good" in events[0].text and state.room.vent == "dead"
    assert state.player.xp == xp + hazards.VENT_XP and "rest" in ids(state, content)


def test_a_vent_you_never_saw_finds_you_asleep(content):
    state = norfel(content)
    put_monster(state, content, key="goblin").hostile = False  # (keeping watch: nothing creeps up on you instead)
    state.room.vent, state.player.hp = "hidden", 10
    events = perform(state, content, "rest")
    assert any("doze" in e.text for e in events) and statuses.has(state, "poison") and state.room.vent == "seen"


def test_the_way_through_says_whats_in_it(content):
    state = norfel(content)
    direction, there = doorway(state, river=True)
    there.visited = True
    go = next(a for a in available_actions(state, content) if a.id == f"go:{direction}")
    assert "poison puddle: jump it" in go.hint and "poison river" in go.hint
    state.room.vent = "seen"
    facts = rules.room_facts(state, content)
    assert f"A poison puddle lies across the doorway {direction}" in facts and "A gas vent hisses" in facts


def test_quick_travel_crosses_them_all_on_the_way(content):
    state = norfel(content)
    state.player.agility = 50  # (there and back, safely)
    direction, there = doorway(state)
    perform(state, content, f"go:{direction}")
    perform(state, content, f"go:{OPPOSITE[direction]}")
    state.player.agility = -50
    state.wandered[str(state.floor)] = 99  # (nobody on the way)
    events = perform(state, content, f"travel:{there.id}")
    assert state.room is there and any(e.kind == "hazard" for e in events) and statuses.has(state, "poison")
