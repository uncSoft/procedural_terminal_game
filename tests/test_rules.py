from collections import Counter

import pytest

from bot import play
from conftest import put_monster
from ptg.creative import available_props, clamp_intent, match_props, spends
from ptg.intent import Intent
from ptg.llm.prompts import player_status
from ptg.models import Feature
from ptg.inventory import gain
from ptg.rules import TRAITS, available_actions, check_traits, perform, perform_creative, room_facts
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


def test_a_tell_written_as_a_sentence_carries_on_from_the_name(content):
    from dataclasses import replace

    from ptg.combat import telegraph
    from ptg.text import mid_sentence

    assert mid_sentence("NPC-style chatter") == "NPC-style chatter"
    orc = replace(content.monster("orc"), tell="Slowly undulates in a circle.")
    content = replace(content, monsters={**content.monsters, "orc": orc})
    state = generate(3)
    put_monster(state, content, key="orc", intent="heavy")
    [event] = telegraph(state, content)
    assert event.text == "The Orc slowly undulates in a circle. A heavy blow is coming!"


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
    gate = next(r for r in state.rooms for e in r.exits.values() if e.locked and not e.key)  # not a shop's door
    direction = next(d for d, e in gate.exits.items() if e.locked and not e.key)
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


def test_what_you_hand_over_is_gone_even_if_the_interpreter_forgets(content):
    """Bribing an orc with stale bread leaves the bread with the orc, though the model only said it was used (if the
    bribe works: if it doesn't, the bread's still yours). What a stunt only shows, it keeps; and a spare weapon thrown
    at it lands at its feet, not used up."""
    state = generate(3)
    orc = put_monster(state, content, key="orc", hp=200)
    state.player.inventory += ["stale_bread", "lucky_charm", "hand_axe"]
    perform_creative(state, content, creative(success_effects=["stun"], uses=["Lucky Rabbit's Foot"],
                                              summary="rub the lucky rabbit's foot and glare at the orc"))
    perform_creative(state, content, creative(success_effects=["damage_small"], uses=["Hand Axe"],
                                              summary="throw the hand axe at the orc"))
    assert "lucky_charm" in state.player.inventory and state.room.items == ["hand_axe"]
    state.player.wits = 50
    perform_creative(state, content, creative(success_effects=["pacify"], uses=["Stale Bread"],
                                              summary="bribe the orc with the stale bread"))
    assert "stale_bread" not in state.player.inventory and not orc.hostile
    assert spends("tossing it") and spends("he threw") and spends("emptied the vial") and spends("dropped bait")
    assert not spends("rub the charm") and not spends("hide behind the table")


def test_what_a_stunt_throws_or_pours_is_gone_though_the_interpreter_lists_nothing(content):
    """The model can leave `uses` and `consumes` empty, or name only what the holy water is poured on. (Splashed on
    the goblin, it's thrown at it: gone, hit or miss. Poured over the altar, a stunt: gone if it works.)"""
    state = generate(3)
    put_monster(state, content, hp=200)
    state.room.features.append(Feature(name="a stone altar"))
    state.player.inventory += ["holy_water", "holy_water"]
    perform_creative(state, content, creative(success_effects=["stun"], summary="brandish the holy water at the goblin"))
    assert state.player.inventory.count("holy_water") == 2  # only shown
    _, events = perform_creative(state, content, creative(success_effects=["damage_small"],
                                                          summary="splash the holy water on the goblin"))
    assert state.player.inventory.count("holy_water") == 1
    assert (events[0].data["item"], events[0].data["how"], events[0].data["to"]) == ("holy_water", "throw", "gone")
    state.player.wits = 50
    _, events = perform_creative(state, content, creative(success_effects=["stun"], uses=["stone altar"],
                                                          summary="pour holy water over the altar"))
    assert "holy_water" not in state.player.inventory
    assert "The Vial of Holy Water is used up." in [e.text for e in events]


def test_choices_say_how_many_you_carry_and_using_one_says_what_is_left(content):
    state = generate(3)
    put_monster(state, content, hp=200)
    state.player.inventory = ["holy_water", "holy_water", "healing_potion"]
    state.player.hp -= 5
    hints = {a.id: a.hint for a in available_actions(state, content)}
    assert hints["throw:holy_water"] == "×2" and hints["use:healing_potion"] == ""
    assert "Carrying: Vial of Holy Water ×2, Healing Potion." in player_status(state, content)  # the model knows too
    events = perform(state, content, "throw:holy_water")
    assert any(e.text.endswith("(1 more in your pack.)") for e in events)
    assert {a.id: a.hint for a in available_actions(state, content)}["throw:holy_water"] == ""
    events = perform(state, content, "throw:holy_water")
    assert not any("more in your pack" in e.text for e in events)  # that was the last


def test_a_weakness_is_cheered_only_when_the_attempt_works(content):
    """After a miss, "the prayer rail plays on its weakness to holy!" read as if the miss had worked (run 44)."""
    for difficulty, works in (("absurd", False), ("easy", True)):
        state = generate(3)
        put_monster(state, content, key="troll", hp=200)  # trolls fear fire
        state.player.inventory.append("oil_flask")
        state.player.wits = 50
        _, events = perform_creative(state, content, creative(success_effects=["damage_small"], difficulty=difficulty,
                                                              uses=["Flask of Lamp Oil"],
                                                              summary="set the troll's beard alight with the oil"))
        assert events[0].data["success"] is works and "fire" in state.known_weak["troll"]  # learned either way
        assert ("That's the Troll's weakness: fire!" in [e.text for e in events]) is works


def test_nothing_hidden_is_not_said_of_a_stunt_that_turns_something_up(content):
    state = generate(3)
    state.room.monster = None
    for feature in state.room.features:
        feature.hidden = False
    state.player.wits = 50
    _, events = perform_creative(state, content, creative(success_effects=["reveal_secret", "find_item"],
                                                          difficulty="easy", summary="pry at the loose stones"))
    assert any(e.kind == "find" for e in events)
    assert "There turns out to be nothing hidden here." not in [e.text for e in events]


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
    assert "already used: topple it onto the goblin" in facts
    assert "you tried to topple it onto the goblin, and it worked" in facts


def test_a_failed_stunt_leaves_the_prop_for_another_try(content):
    state = generate(1)
    state.player.wits = -50
    feature = state.room.visible_features()[0][1]
    perform_creative(state, content, creative(success_effects=["find_gold"], uses=[feature.name]))
    assert not feature.used and not state.room.history


def test_gear_goes_in_your_pack_or_on_into_an_empty_slot(content):
    state = generate(1)
    state.player.armor = None
    gain(state, content, "war_pick")
    gain(state, content, "scale_hauberk")
    assert state.player.weapon == "rusty_sword" and "war_pick" in state.player.inventory  # a weapon's always in hand
    assert state.player.armor == "scale_hauberk" and not state.room.items  # nothing tossed on the floor


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


# --- what the audit found (W1) ------------------------------------------------

def calm(state, content, key):
    """A creature here that isn't fighting you (Lucky Lenny, or one you've talked down)."""
    monster = put_monster(state, content, key=key)
    monster.hostile, monster.mood = False, "tooth" if key == "lucky_lenny" else ""
    return monster


def test_killing_what_you_talked_down_pays_nothing_more(content):
    """Run 36 talked the Cursed Wight down (+40 XP, +18 souls), then killed it for +68 XP, +18 souls and 36 gold."""
    import random

    from ptg.combat import defeat, monster_turn

    state = generate(3)
    joey = put_monster(state, content, key="baby_joey")
    joey.stolen_gold, state.player.gold = 15, 0
    joey.hostile = False
    defeat(state, content, random.Random(1), how="pacified")
    assert state.player.gold == 15 and joey.rewarded and not joey.stolen_gold  # his to run off with no more
    xp, souls, items = state.player.xp, state.souls, list(state.room.items)
    assert next(a for a in available_actions(state, content) if a.id == "attack").hint == "it's calm · no reward"
    state.player.might = -50  # a miss: provoked, he gets his go
    events = perform(state, content, "attack")
    assert events[0].text == "Baby Joey had stopped fighting. Not any more."
    assert not any(e.kind == "getaway" for e in events + monster_turn(state, content, random.Random(2)))
    joey.hp, state.player.might = 1, 50
    while state.room.monster:
        events = perform(state, content, "attack")
    assert (state.player.xp, state.souls, state.player.gold, state.room.items) == (xp, souls, 15, items)
    assert "No reward this time" in next(e.text for e in events if e.kind == "defeat") and state.player.kills == 1


def test_only_the_stairs_own_warden_always_leaves_something(content):
    """Resting by the stairs once the warden was dead brought an ambusher that dropped a warden's prize."""
    import random

    from ptg.combat import _kept
    from ptg.models import GameState
    from ptg.world import monster_for

    state = generate(1)
    stairs = next(r for r in state.rooms if r.fixture == "stairs")
    assert stairs.monster.warden and not any(r.monster.warden for r in state.rooms if r.monster and r is not stairs)
    state.room_id = stairs.id
    assert _kept(state, content, random.Random(1), stairs.monster)  # (a small key, on floor 1)
    stairs.monster = monster_for(random.Random(1), content, state.theme, 1)
    assert not stairs.monster.warden and _kept(state, content, random.Random(1), stairs.monster) == []
    old = state.model_dump()  # a save from before wardens were marked
    stairs.monster.warden = False
    for rested in (False, True):
        old["rooms"][stairs.id].update(rested=rested, monster=stairs.monster.model_dump() | {"warden": False})
        assert GameState.model_validate(old).rooms[stairs.id].monster.warden is not rested


def test_resting_beside_someone_or_in_a_shop_brings_no_ambush(content):
    """Resting beside Lucky Lenny replaced him with an ambusher, for good, in 42 rests out of 200."""
    from ptg.models import Shop

    state = generate(1)
    lenny = calm(state, content, "lucky_lenny")
    for turn in range(40):
        state.turn, state.room.rested, state.player.hp = turn, False, 5
        assert next(a for a in available_actions(state, content) if a.id == "rest").hint == "safe here"
        events = perform(state, content, "rest")
        assert state.room.monster is lenny and not any(e.kind == "ambush" for e in events)
    state.room.monster, state.room.shop = None, Shop(keeper="granny_gristle")
    for turn in range(40):
        state.turn, state.room.rested, state.player.hp = turn, False, 5
        assert not any(e.kind == "ambush" for e in perform(state, content, "rest"))
    state.room.shop, ambushed = None, 0
    for turn in range(40):  # anywhere else, it's as risky as ever
        state.turn, state.room.rested, state.room.monster, state.player.hp = turn, False, None, 5
        ambushed += any(e.kind == "ambush" for e in perform(state, content, "rest"))
    assert ambushed


def test_a_hit_always_hurts(content):
    """King Mouse, cut down to 1d12+4-5, hit for 0 damage on a roll of 1."""
    import random

    from ptg import npcs
    from ptg.combat import monster_turn

    state = generate(3)
    state.room.monster = npcs.sized(content, npcs.KING_MOUSE, 2, npcs.KING_MOUSE_SIZE, warden=True)
    state.player.agility, state.player.max_hp = -50, 10_000
    damage = []
    for seed in range(200):
        state.room.monster.intent, state.player.hp = "strike", 10_000
        events = monster_turn(state, content, random.Random(seed))
        damage += [e.data["damage"] for e in events if e.kind == "monster_hit"]
    assert damage and min(damage) >= 1


def test_king_mouse_is_as_hard_to_get_past_as_the_warden_he_stands_in_for(content):
    """Sized at his maker's tier 1, he was easier to dodge and run from, and worth fewer souls, than a warden."""
    import random

    from ptg import npcs
    from ptg.combat import defeat, dodge, flee

    state = generate(3)
    mouse = state.room.monster = npcs.sized(content, npcs.KING_MOUSE, 2, npcs.KING_MOUSE_SIZE, warden=True)
    assert mouse.tier == 3 and content.monster(npcs.KING_MOUSE).tier == 1  # the floor-2 warden's, not his maker's
    assert next(e for e in dodge(state, content, random.Random(1)) if e.dice).dice.dc == 12
    assert next(e for e in flee(state, content, random.Random(1)) if e.dice).dice.dc == 13
    state.room.monster, souls = mouse, state.souls  # (wherever that left you)
    defeat(state, content, random.Random(1))
    assert state.souls - souls == 27  # 3 a tier, three times over


def test_running_out_of_a_tangle_leaves_the_vines_behind(content):
    """Fled from Swamp Bottoms with a smoke bomb, you were still 'tangled in the Goblin's vines' in the next fight."""
    state = generate(3)
    swamp = put_monster(state, content, key="swamp_bottoms")
    state.player.tangled = True
    state.player.inventory.append("smoke_bomb")
    perform(state, content, "use:smoke_bomb")
    assert state.room.monster is not swamp and not state.player.tangled
    goblin = put_monster(state, content, key="goblin")
    assert "flee" in ids(state, content) and "tangled" not in room_facts(state, content)
    goblin.hp, state.player.might, state.player.tangled = 1, 50, True
    while state.room.monster:
        perform(state, content, "attack")
    assert not state.player.tangled  # (no vines once there's no fight)


def test_what_you_get_when_you_are_not_hurt_is_not_called_healing(content):
    """'You eat the Jar o' Light and recover 0 HP', 'The water is cool and clean (+0 HP)'."""
    import random

    from ptg.creative import _apply_effect
    from ptg.rules import _fixture

    state = generate(3)
    put_monster(state, content, key="goblin")
    state.player.inventory = ["jar_o_light"]
    events = perform(state, content, "use:jar_o_light")
    assert events[0].text == "You eat the Jar o' Light." and "0 HP" not in " ".join(e.text for e in events)
    state.room.monster = None
    assert _apply_effect(state, content, random.Random(1), "heal_small", 0) == []
    texts = set()
    for seed in range(60):
        state.player.hp, state.room.fixture, state.room.fixture_used = state.player.max_hp, "fountain", False
        texts |= {e.text for e in _fixture(state, content, random.Random(seed), "fountain")}
    assert "The water is cool and clean." in texts and not any("+0 HP" in t for t in texts)


def test_fate_goes_with_the_rabbits_foot(content):
    """Spending the Lucky Rabbit's Foot left Fate at 4/3 for the rest of the run."""
    state = generate(3)
    state.room.monster = None
    state.player.inventory.append("lucky_charm")
    state.player.fate, state.player.wits = 4, 50
    perform_creative(state, content, creative(success_effects=["find_gold"], consumes=["Lucky Rabbit's Foot"],
                                              summary="toss the rabbit's foot over your shoulder"))
    assert "lucky_charm" not in state.player.inventory and state.player.fate == state.player.max_fate() == 3


def test_no_dead_end_choices_at_locked_doors_or_a_shrine_with_nothing_to_heal(content):
    from ptg.rules import locked_doors

    state = generate(11)
    state.floor = 3
    build_floor(state, content)
    gate = next(r for r in state.rooms for e in r.exits.values() if e.locked and not e.key)
    direction = next(d for d, e in gate.exits.items() if e.locked and not e.key)
    state.room_id, gate.monster = gate.id, None
    assert f"go:{direction}" not in ids(state, content)  # nothing to do there yet...
    assert f"go:{direction}" in [a.id for a in locked_doors(state, content)]
    turn = state.turn
    assert perform(state, content, f"go:{direction}")[0].kind == "locked" and state.turn == turn  # ...but it says so
    state.pending_perks = ["tough"]  # (not while a level-up waits to be picked)
    assert locked_doors(state, content) == []
    state.pending_perks = []
    state.room.fixture, state.room.fixture_used, state.player.gold = "shrine", False, 50
    assert "shrine_gold" not in ids(state, content)  # at full health, it would only take your gold
    state.player.hp -= 5
    assert "shrine_gold" in ids(state, content)


def test_someones_things_take_no_article_title_case_or_not(content):
    """'You take the Swoogy's Diaper.', 'You go north into the Granny Gristle's Shop', 'a King Mouses Vest'."""
    from ptg.text import a, the

    for name in ("Swoogy's Diaper", "Lenny's Bad Tooth", "Mama's Shillelagh", "Granny Gristle's Shop",
                 "King Mouse's Vest", "Brannoc's remains", "Sir Bob's remains"):
        assert the(name) == a(name) == name
    for name in ("Lucky Rabbit's Foot", "Saint's Alcove", "Hidden Saint's Alcove"):
        assert the(name) == f"the {name}" and a(name) == f"a {name}"
    assert content.item("king_mouses_vest").name == "King Mouse's Vest"
    state = generate(1)
    assert gain(state, content, "swoogy_s_diaper")[0].text == "You take Swoogy's Diaper."


def test_the_narrator_hears_about_a_character_by_name_and_of_a_stunt_as_something_you_did(content):
    """'About the Lucky Lenny', and 'Earlier here: offer the ghost the stale bread (it worked)'."""
    from ptg.llm.prompts import narrator_messages

    state = generate(1)
    calm(state, content, "lucky_lenny")
    from ptg.llm.prompts import situation

    _, user = narrator_messages(state, content, "hello", [], "classic")
    assert "About Lucky Lenny:" in user and "About the Lucky Lenny" not in user
    assert "About Lucky Lenny:" in situation(state, content)
    state.room.monster, state.player.wits = None, 50
    perform_creative(state, content, creative(success_effects=["find_gold"], summary="pry at the loose stones"))
    assert state.room.history[-1] == "you tried to pry at the loose stones, and it worked"


def test_a_ghosts_remains_hold_no_second_rare_and_nothing_this_run_must_earn(content):
    """Remains brought back the Sword Still in the Stone a run had already, and Lenny's tooth in a run without him."""
    ghost = {"id": 7, "name": "Old Me", "level": 2, "floor": 1, "gold": 10, "epitaph": "", "cause": "",
             "items": ["lenny_s_bad_tooth", "swoogy_s_diaper", "reliquary_key", "sword_still_in_the_stone",
                       "moonsilver_vest", "healing_potion", "healing_potion"]}
    for seed in range(30):
        state = generate(seed, ghost=ghost)
        remains = next(f for r in state.rooms for f in r.features if f.name == "Old Me's remains")
        assert not {"lenny_s_bad_tooth", "swoogy_s_diaper", "reliquary_key"} & set(remains.loot)
        rares = [k for k in remains.loot if k in ("sword_still_in_the_stone", "moonsilver_vest")]
        assert rares and all(state.rares.count(k) == 1 for k in rares)  # this run's one of each
        placed = [k for r in state.rooms for k in r.items + [i for f in r.features for i in f.loot]]
        assert all(placed.count(k) == 1 for k in rares)
