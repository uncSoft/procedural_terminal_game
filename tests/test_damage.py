"""What a hit did, told on its roll (Roll.damage, Roll.hurt): the story's dice line and the journal show the damage
and where it came from, since the narration tells the blow, not the numbers."""

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
