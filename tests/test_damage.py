"""What a roll did, told on it (Roll.hurt, Roll.told): the story's dice line and the journal show a hit's damage and
where it came from, and anything else it won or cost (the fountain's Fate), since the narration tells the moment, not
the numbers."""

import pytest

from ptg import dice, testrooms
from ptg.rules import perform


def in_room(content, who: str, kit: str = "new", seed: int = 3):
    state = testrooms.build(content, who, kit, seed=seed)
    room = testrooms.target(state)
    state.room_id, room.visited = room.id, True
    return state


@pytest.fixture
def always(monkeypatch):
    """Every d20 comes up `face`."""
    def force(face: int):
        monkeypatch.setattr(dice, "d20", lambda rng: face)
    return force


def hit(events, kind: str):
    return next(e for e in events if e.kind == kind and e.dice)


def test_hurt_tells_the_total_and_its_parts():
    roll = dice.Roll("attack", "player", [20], 20, damage=[("4d6", 14), ("crit 4d6", 4), ("might", 2)])
    assert roll.hurt() == "20 damage (4d6 14 + crit 4d6 4 + might 2)"
    assert dice.Roll("x", "player", [3], 3).hurt() == ""  # (a miss did nothing)


def test_your_blow_says_what_it_did_and_takes_that_off_the_monster(content, always):
    always(20)
    state = in_room(content, "troll", "strong")
    monster = state.room.monster
    before = monster.hp
    roll = hit(perform(state, content, "attack"), "hit").dice
    names = [name for name, _ in roll.damage]
    assert roll.crit and names[:2] == [content.item(state.player.weapon).damage,
                                       f"crit {content.item(state.player.weapon).damage}"]
    assert sum(v for _, v in roll.damage) == before - monster.hp
    assert roll.hits_for.startswith(content.item(state.player.weapon).damage)


def test_a_thrown_grenade_says_it_hits_for_its_own_dice_and_a_crit_doubles_them(content, always):
    always(20)
    state = in_room(content, "troll", "strong")
    state.player.inventory.append("hallowed_hand_grenade")
    monster, before = state.room.monster, state.room.monster.hp
    roll = hit(perform(state, content, "throw:hallowed_hand_grenade"), "hit").dice
    grenade = content.item("hallowed_hand_grenade").damage
    assert roll.hits_for == grenade  # (the d20 is to hit; the damage is the grenade's dice)
    assert [name for name, _ in roll.damage][:2] == [grenade, f"crit {grenade}"]
    assert sum(v for _, v in roll.damage) == before - monster.hp
    assert "damage" in roll.hurt()


def test_the_monsters_blow_says_what_it_did_to_you(content, always):
    for seed in range(40):  # (until it hits: its d20 is forced, but you might dodge or it might guard)
        always(19)
        state = in_room(content, "troll", "new", seed=seed)
        state.room.monster.hostile = True
        hp = state.player.hp
        events = perform(state, content, "attack")
        blows = [e for e in events if e.kind == "monster_hit"]
        if blows:
            roll = blows[0].dice
            assert sum(v for _, v in roll.damage) == hp - state.player.hp >= 1
            assert roll.hurt().startswith(f"{hp - state.player.hp} damage")
            return
    pytest.fail("the troll never hit")


def fountain_room(content, face: int, always):
    from ptg.world import generate
    always(face)
    state = generate(1)
    state.room.fixture, state.room.fixture_used = "fountain", False
    state.room.monster = None
    return state


def test_the_fountain_says_on_its_roll_that_you_gained_fate(content, always):
    state = fountain_room(content, 17, always)
    state.player.fate = 0
    roll = next(e for e in perform(state, content, "fountain") if e.dice).dice
    assert state.player.fate == 1 and roll.told() == f"+1 Fate (1/{state.player.max_fate()})"


def test_a_full_fate_is_not_told_as_a_gain(content, always):
    state = fountain_room(content, 17, always)
    state.player.fate = state.player.max_fate()
    events = perform(state, content, "fountain")
    roll = next(e for e in events if e.dice).dice
    assert roll.told().startswith("Fate already full") and "gain" not in events[0].text
