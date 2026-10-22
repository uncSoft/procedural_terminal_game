from collections import Counter

import pytest

from bot import play
from ptg.intent import Intent
from ptg.models import MonsterState
from ptg.rules import available_actions, clamp_intent, perform, perform_creative
from ptg.world import generate


def with_monster(content, key="goblin", hp=None, seed=3):
    state = generate(seed)
    monster = content.monster(key)
    state.room.monster = MonsterState(key=key, name=monster.name, hp=hp or monster.hp, max_hp=monster.hp)
    return state


def ids(state, content):
    return [a.id for a in available_actions(state, content)]


def test_killing_a_monster_awards_xp_once(content):
    state = with_monster(content, hp=1)
    state.player.might = 50  # only a natural 1 misses
    while state.room.monster:
        perform(state, content, "attack")
    assert state.player.xp == content.monster("goblin").xp
    assert state.player.kills == 1
    assert not state.in_combat


def test_combat_choices_and_monster_strikes_back(content):
    state = with_monster(content, key="orc")
    assert ids(state, content)[0] == "attack"
    assert not any(a.startswith("go:") for a in ids(state, content))
    hp_before, turns = state.player.hp, 0
    while state.player.hp == hp_before and turns < 50:
        perform(state, content, "attack")
        turns += 1
    assert state.player.hp < hp_before


def test_potions_heal_are_consumed_and_not_wasted(content):
    state = with_monster(content)
    assert "use:healing_potion" not in ids(state, content)  # full HP: nothing to heal
    state.player.hp = 10
    perform(state, content, "use:healing_potion")
    assert state.player.hp >= 18 - 10  # healed 8, minus whatever the goblin did back
    assert "healing_potion" not in state.player.inventory


def test_flee_returns_to_previous_room(content):
    state = generate(3)
    direction = next(iter(state.room.exits))
    perform(state, content, f"go:{direction}")
    start = state.prev_room_id
    monster = content.monster("goblin")
    state.room.monster = MonsterState(key="goblin", name=monster.name, hp=monster.hp, max_hp=monster.hp)
    state.player.agility = 50  # only a natural 1 fails
    fled_from = state.room_id
    while state.room_id == fled_from and state.status == "playing":
        perform(state, content, "flee")
    assert state.room_id == start
    assert state.rooms[state.prev_room_id].monster is not None


def test_locked_door_needs_the_key(content):
    state = generate(11)
    theme = content.themes[state.theme]
    gate = next(r for r in state.rooms for e in r.exits.values() if e.locked)
    direction = next(d for d, e in gate.exits.items() if e.locked)
    state.room_id = gate.id
    gate.monster = None
    turn = state.turn
    events = perform(state, content, f"go:{direction}")
    assert events[0].kind == "locked" and state.turn == turn and state.room_id == gate.id
    state.player.inventory.append(theme.key_item)
    perform(state, content, f"go:{direction}")
    assert state.room.is_boss and state.in_combat


def test_unknown_or_unavailable_actions_cost_nothing(content):
    state = generate(1)
    events = perform(state, content, "attack")
    assert events[0].kind == "info" and state.turn == 0


def test_death_ends_the_game(content):
    state = with_monster(content, key="orc", hp=999)
    state.player.hp = 1
    state.player.agility = -50  # only the orc's natural 1s miss
    while state.status == "playing":
        perform(state, content, "attack")
    assert state.status == "dead" and state.player.hp == 0
    assert available_actions(state, content) == []


# --- creative actions --------------------------------------------------------

def creative(**fields) -> Intent:
    base = dict(kind="creative", stat="wits", difficulty="medium", success_effects=[], failure_effects=[],
                summary="do something clever")
    return Intent(**{**base, **fields})


def test_clamp_caps_damage_by_difficulty(content):
    state = with_monster(content)
    clamped = clamp_intent(state, content, creative(difficulty="easy", success_effects=["damage_large"]))
    assert clamped.success_effects == ["damage_small"]
    clamped = clamp_intent(state, content, creative(difficulty="medium", success_effects=["damage_large", "stun", "find_gold"]))
    assert clamped.success_effects == ["damage_medium", "stun"]


def test_clamp_drops_effects_that_cannot_apply(content):
    state = generate(1)  # no monster in the start room
    clamped = clamp_intent(state, content, creative(success_effects=["damage_medium", "stun", "pacify", "find_gold"],
                                                    failure_effects=["damage_large", "hurt_self_small"]))
    assert clamped.success_effects == ["find_gold"]
    assert clamped.failure_effects == ["hurt_self_small"]


def test_pacify_rules(content):
    rat = with_monster(content, key="giant_rat")
    assert clamp_intent(rat, content, creative(success_effects=["pacify"])).success_effects == []
    goblin = with_monster(content, key="goblin")
    clamped = clamp_intent(goblin, content, creative(difficulty="easy", success_effects=["pacify"]))
    assert clamped.success_effects == ["pacify"] and clamped.difficulty == "hard"
    state = generate(1)
    boss = content.monster(content.themes[state.theme].boss)
    state.room.monster = MonsterState(key=boss.key, name=boss.name, hp=boss.hp, max_hp=boss.hp)
    assert clamp_intent(state, content, creative(success_effects=["pacify"])).success_effects == ["stun"]


def test_once_per_room_effects(content):
    state = generate(1)
    state.player.wits = 50
    intent, _ = perform_creative(state, content, creative(success_effects=["find_gold"]))
    gold = state.player.gold
    assert gold > 0
    intent, events = perform_creative(state, content, creative(success_effects=["find_gold"]))
    assert state.player.gold == gold


def test_absurd_attempts_always_fail(content):
    state = with_monster(content)
    state.player.wits = 99
    for _ in range(10):
        _, events = perform_creative(state, content, creative(difficulty="absurd", success_effects=["damage_large"]))
        assert events[0].kind == "check" and events[0].data["success"] is False
        state.player.hp = state.player.max_hp


def test_stun_buys_a_free_turn(content):
    state = with_monster(content, key="orc")
    state.player.wits = 50
    _, events = perform_creative(state, content, creative(success_effects=["stun"]))
    assert [e.kind for e in events] == ["check", "stun", "stunned"]
    hp = state.player.hp
    state.player.might = -50  # miss, so the orc survives
    events = perform(state, content, "attack")
    assert events[-1].kind == "stunned" and state.player.hp == hp


def test_self_harm_never_kills(content):
    state = generate(1)
    state.player.hp = 1
    state.player.wits = -50
    perform_creative(state, content, creative(success_effects=["find_gold"], failure_effects=["hurt_self_medium"]))
    assert state.player.hp == 1 and state.status == "playing"


# --- whole games -------------------------------------------------------------

def test_bot_games_finish_without_errors(content):
    results = Counter()
    for seed in range(120):
        state = play(generate(seed), content)
        results[state.status] += 1
    assert results["playing"] == 0
    # Balance guard: an action-only bot that never flees or improvises should still win sometimes.
    assert 0.3 <= results["won"] / 120 <= 0.85, results


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_bot_games_are_deterministic(seed, content):
    assert play(generate(seed), content).model_dump() == play(generate(seed), content).model_dump()
