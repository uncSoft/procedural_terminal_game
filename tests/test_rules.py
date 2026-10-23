from collections import Counter

import pytest

from bot import play
from conftest import put_monster
from ptg.creative import available_props, clamp_intent, match_props
from ptg.intent import Intent
from ptg.rules import TRAITS, available_actions, check_traits, gain_item, perform, perform_creative, room_facts
from ptg.world import build_floor, generate


def ids(state, content):
    return [a.id for a in available_actions(state, content)]


def creative(**fields) -> Intent:
    base = dict(kind="creative", stat="wits", difficulty="medium", success_effects=[], failure_effects=[],
                summary="do something clever")
    return Intent(**{**base, **fields})


# --- combat ------------------------------------------------------------------

def test_killing_a_monster_awards_xp_and_souls_once(content):
    state = generate(3)
    put_monster(state, content, hp=1)
    state.player.might = 50  # only a natural 1 misses
    while state.room.monster:
        perform(state, content, "attack")
    assert state.player.xp == content.monster("goblin").xp
    assert state.player.kills == 1 and state.souls == 3


def test_combat_choices(content):
    state = generate(3)
    put_monster(state, content, key="orc")
    actions = ids(state, content)
    assert actions[:2] == ["attack", "dodge"] and "flee" not in actions[:2]
    assert not any(a.startswith("go:") for a in actions)
    assert "use:healing_potion" not in actions  # full HP: nothing to heal


def test_monsters_telegraph_heavy_blows_and_dodging_counters_them(content):
    state = generate(3)
    monster = put_monster(state, content, key="orc", intent="heavy")
    state.player.agility = 50
    fate = state.player.fate
    events = perform(state, content, "dodge")
    kinds = [e.kind for e in events]
    assert "dodge" in kinds and "monster_hit" not in kinds
    assert state.player.advantage_next and state.player.fate == fate + 1
    events = perform(state, content, "attack")
    assert events[0].dice.advantage == 1 and len(events[0].dice.dice) == 2
    assert monster.intent in ("strike", "heavy", "guard")


def test_guarding_monsters_are_harder_to_hit(content):
    state = generate(3)
    monster = put_monster(state, content, key="orc", intent="guard")
    state.player.agility = -50
    perform(state, content, "attack")
    assert monster.guarding
    events = perform(state, content, "attack")
    assert events[0].dice.dc == content.monster("orc").defense + 4


def test_potions_heal_and_are_consumed(content):
    state = generate(3)
    put_monster(state, content)
    state.player.hp = 10
    perform(state, content, "use:healing_potion")
    assert "healing_potion" not in state.player.inventory
    assert state.player.hp > 10 - 12


def test_flee_returns_to_previous_room(content):
    state = generate(3)
    direction = next(iter(state.room.exits))
    perform(state, content, f"go:{direction}")
    start = state.prev_room_id
    put_monster(state, content)
    state.player.agility = 50  # only a natural 1 fails
    fled_from = state.room_id
    while state.room_id == fled_from and state.status == "playing":
        perform(state, content, "flee")
    assert state.room_id == start
    assert state.rooms[state.prev_room_id].monster is not None


def test_death_ends_the_game(content):
    state = generate(3)
    put_monster(state, content, key="orc", hp=999)
    state.player.hp = 1
    state.player.agility = -50  # only the orc's natural 1s miss
    while state.status == "playing":
        perform(state, content, "attack")
    assert state.status == "dead" and state.player.hp == 0 and "Orc" in state.cause
    assert available_actions(state, content) == []


def test_second_wind_saves_you_once_per_floor(content):
    state = generate(3)
    put_monster(state, content, key="orc", hp=999)
    state.player.perks.append("second_wind")
    state.player.hp = 1
    state.player.agility = -50
    while state.player.hp > 0 and state.status == "playing" and state.player.second_wind_floor == 0:
        perform(state, content, "attack")
    assert state.status == "playing" and state.player.hp == 1


# --- moving, floors and fixtures ------------------------------------------------

def test_locked_boss_door_needs_the_key(content):
    state = generate(11)
    state.floor = 3
    build_floor(state, content)
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


def test_descending_builds_the_next_floor(content):
    state = generate(2)
    stairs = next(r for r in state.rooms if r.fixture == "stairs")
    state.room_id = stairs.id
    stairs.monster = None
    events = perform(state, content, "descend")
    assert events[0].kind == "descend"
    assert state.floor == 2 and state.theme == state.themes[1] and state.room_id == 0 and state.souls == 10


def test_unavailable_actions_cost_nothing(content):
    state = generate(1)
    events = perform(state, content, "attack")
    assert events[0].kind == "info" and state.turn == 0


@pytest.mark.parametrize("fixture,action", [("shrine", "shrine_blood"), ("fountain", "fountain"), ("chest", "chest")])
def test_fixtures_are_one_use(content, fixture, action):
    state = generate(1)
    state.room.fixture = fixture
    state.player.gold = 50
    assert action in ids(state, content)
    perform(state, content, action)
    assert state.room.fixture_used and action not in ids(state, content)


def test_shrine_trades_blood_for_fate(content):
    state = generate(1)
    state.room.fixture = "shrine"
    fate, hp = state.player.fate, state.player.hp
    perform(state, content, "shrine_blood")
    assert state.player.fate == fate + 1 and state.player.hp == hp - 6


# --- progression -------------------------------------------------------------

def test_level_up_offers_three_perks(content):
    state = generate(1)
    put_monster(state, content, key="goblin", hp=1)
    state.player.xp = 19
    state.player.might = 50
    while state.room.monster:
        perform(state, content, "attack")
    assert state.player.level == 2 and len(state.pending_perks) == 3
    choices = available_actions(state, content)
    assert all(a.id.startswith("perk:") for a in choices)
    perform(state, content, choices[0].id)
    assert not state.pending_perks and len(state.player.perks) == 1


def test_two_level_ups_queue_two_perk_picks(content):
    state = generate(1)
    put_monster(state, content, key="orc", hp=1)
    state.player.xp = 19
    state.player.might = 50
    while state.room.monster:
        perform(state, content, "attack")
    assert state.player.level == 3
    perform(state, content, available_actions(state, content)[0].id)
    assert len(state.pending_perks) == 3  # the second pick
    perform(state, content, available_actions(state, content)[0].id)
    assert not state.pending_perks and len(state.player.perks) == 2


def test_traits_come_from_play_style(content):
    state = generate(1)
    state.player.style["pacify"] = 2
    events = check_traits(state)
    assert [e.data["trait"] for e in events] == ["silver_tongue"]
    assert check_traits(state) == []
    assert set(TRAITS) >= {"silver_tongue", "showboat", "trickster"}


# --- creative actions --------------------------------------------------------

def test_clamp_caps_damage_by_difficulty(content):
    state = generate(3)
    put_monster(state, content)
    clamped = clamp_intent(state, content, creative(difficulty="easy", success_effects=["damage_large"]))
    assert clamped.success_effects == ["damage_small"]
    clamped = clamp_intent(state, content, creative(success_effects=["damage_large", "stun", "find_gold"]))
    assert clamped.success_effects == ["damage_medium", "stun"]


def test_clamp_drops_effects_that_cannot_apply(content):
    state = generate(1)
    clamped = clamp_intent(state, content, creative(success_effects=["damage_medium", "stun", "evade", "find_gold"],
                                                    failure_effects=["damage_large", "hurt_self_small"]))
    assert clamped.success_effects == ["find_gold"]
    assert clamped.failure_effects == ["hurt_self_small"]


def test_pacify_rules(content):
    state = generate(3)
    put_monster(state, content, key="giant_rat")
    assert clamp_intent(state, content, creative(success_effects=["pacify"])).success_effects == []
    # ...unless you distract it with something it's weak to
    state.player.inventory.append("cheese_wheel")
    cheese = match_props(["wheel of cheese"], available_props(state, content))
    assert clamp_intent(state, content, creative(success_effects=["pacify"]), cheese).success_effects == ["pacify"]
    put_monster(state, content, key="goblin")
    clamped = clamp_intent(state, content, creative(difficulty="easy", success_effects=["pacify"]))
    assert clamped.success_effects == ["pacify"] and clamped.difficulty == "hard"
    boss = content.monster(content.themes[state.theme].boss)
    put_monster(state, content, key=boss.key)
    assert clamp_intent(state, content, creative(success_effects=["pacify"])).success_effects == ["stun"]


def test_props_must_exist(content):
    state = generate(1)
    props = available_props(state, content)
    assert match_props(["Healing Potion"], props)[0].key == "healing_potion"
    assert match_props(["dragon"], props) == []
    state.player.gold = 10
    assert match_props(["a handful of coins"], available_props(state, content))[0].kind == "gold"


def test_using_a_prop_earns_flair_and_fate(content):
    state = generate(1)
    state.player.wits = 50
    state.player.fate = 0
    feature = state.room.visible_features()[0][1]
    intent, events = perform_creative(state, content, creative(success_effects=["find_gold"], uses=[feature.name]))
    check = events[0]
    assert any(name.startswith("✦") for name, _ in check.dice.bonuses)
    assert state.player.fate == 1 and state.player.style["flair"] == 1


def test_weakness_gives_advantage_and_is_learned(content):
    state = generate(3)
    put_monster(state, content, key="troll", hp=200)
    state.player.inventory.append("oil_flask")
    intent, events = perform_creative(state, content, creative(success_effects=["damage_small"],
                                                               consumes=["Flask of Lamp Oil"]))
    assert events[0].dice.advantage == 1
    assert "fire" in state.known_weak["troll"]
    assert "oil_flask" not in state.player.inventory
    assert any(e.kind == "weakness" for e in events)


def test_hiding_behind_a_prop_is_not_exploiting_it(content):
    state = generate(3)
    put_monster(state, content, key="troll", intent="heavy")
    state.player.inventory.append("oil_flask")
    intent, events = perform_creative(state, content, creative(success_effects=["evade"], uses=["Flask of Lamp Oil"]))
    assert events[0].dice.advantage == 0 and "troll" not in state.known_weak


def test_absurd_attempts_always_fail(content):
    state = generate(3)
    put_monster(state, content)
    state.player.wits = 99
    for _ in range(10):
        _, events = perform_creative(state, content, creative(difficulty="absurd", success_effects=["damage_large"]))
        assert events[0].kind == "check" and events[0].data["success"] is False
        state.player.hp = state.player.max_hp


def test_stun_buys_a_free_turn(content):
    state = generate(3)
    put_monster(state, content, key="orc")
    state.player.wits = 50
    _, events = perform_creative(state, content, creative(success_effects=["stun"]))
    assert [e.kind for e in events][:3] == ["check", "stun", "stunned"]
    hp = state.player.hp
    state.player.might = -50  # miss, so the orc survives
    events = perform(state, content, "attack")
    assert any(e.kind == "stunned" for e in events) and state.player.hp == hp


def test_self_harm_never_kills(content):
    state = generate(1)
    state.player.hp = 1
    state.player.wits = -50
    perform_creative(state, content, creative(success_effects=["find_gold"], failure_effects=["hurt_self_medium"]))
    assert state.player.hp == 1 and state.status == "playing"


# --- whole games -------------------------------------------------------------

def test_bot_games_finish_without_errors(content):
    results = Counter()
    for seed in range(100):
        state = play(generate(seed), content)
        results[state.status] += 1
    assert results["playing"] == 0
    # Balance guard: an action-only bot that never improvises should win some and lose some.
    assert 0.2 <= results["won"] / 100 <= 0.75, results


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_bot_games_are_deterministic(seed, content):
    assert play(generate(seed), content).model_dump() == play(generate(seed), content).model_dump()


def test_a_prop_is_spent_once_its_stunt_works(content):
    state = generate(1)
    state.player.wits = 50
    put_monster(state, content, key="goblin", hp=200)
    feature = state.room.visible_features()[0][1]
    stunt = creative(success_effects=["damage_small"], uses=[feature.name], summary="topple it onto the goblin")
    perform_creative(state, content, stunt)
    assert feature.used == "topple it onto the goblin"
    assert feature.name not in [p.name for p in available_props(state, content)]  # no farming the same prop
    facts = room_facts(state, content)
    assert "already used: topple it onto the goblin" in facts and "topple it onto the goblin (it worked)" in facts


def test_a_failed_stunt_leaves_the_prop_for_another_try(content):
    state = generate(1)
    state.player.wits = -50
    feature = state.room.visible_features()[0][1]
    perform_creative(state, content, creative(success_effects=["find_gold"], uses=[feature.name]))
    assert not feature.used and not state.room.history


def test_swapped_gear_stays_where_you_left_it(content):
    state = generate(1)
    old_weapon, old_armor = state.player.weapon, state.player.armor
    gain_item(state, content, "war_pick")
    gain_item(state, content, "scale_hauberk")
    assert state.player.weapon == "war_pick" and old_weapon in state.room.items
    assert state.player.armor == "scale_hauberk" and (old_armor is None or old_armor in state.room.items)


def test_rooms_remember_what_happened_in_them(content):
    state = generate(2)
    start = state.room
    put_monster(state, content, key="goblin", hp=1)
    state.player.might = 50
    while start.monster is not None:
        perform(state, content, "attack")
    direction = next(iter(start.exits))
    perform(state, content, f"go:{direction}")
    state.room.monster = None  # nothing in the way back
    back = next(d for d, e in state.room.exits.items() if e.to == start.id)
    events = perform(state, content, f"go:{back}")
    assert start.history == ["you killed the Goblin"] and "Earlier here: you killed the Goblin." in events[0].text
