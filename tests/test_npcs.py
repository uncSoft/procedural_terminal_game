"""The kids' characters and things (ptg/npcs.py, combat's tricks, powers): Lucky Lenny's tooth, Swoogy's guessing game,
King Mouse at the stairs, Baby Joey's thieving, Swamp Bottoms' vines, the Diaper's reek, the Jar o' Light's glow, and
what carried things do to your stats."""

import random

import pytest

from conftest import put_monster
from ptg import combat, npcs, powers
from ptg.models import GameState
from ptg.rules import available_actions, perform, room_facts
from ptg.world import build_floor, generate


def ids(state, content):
    return [a.id for a in available_actions(state, content)]


@pytest.fixture
def everyone(monkeypatch):
    """Every character turns up wherever it can."""
    monkeypatch.setattr(npcs, "ODDS", {npcs.LENNY: 1.0, npcs.SWOOGY: 1.0, npcs.KING_MOUSE: 1.0, "npc": 0.0})


def go_to(state, room):
    state.room_id, room.visited = room.id, True


def with_monster(state, key):
    return next(r for r in state.rooms if r.monster and r.monster.key == key)


# --- Lucky Lenny -------------------------------------------------------------------

def test_lenny_turns_up_calm_with_his_tooth_hidden_nearby(content, everyone):
    seed = next(s for s in range(300) if npcs.lenny_plan(s) == (1, 1))
    state = generate(seed)
    room = with_monster(state, npcs.LENNY)
    assert not room.monster.hostile and room.monster.mood == "tooth" and room.id != 0
    spot, feature = npcs.tooth_spot(state)
    assert feature.hidden and feature.loot == [npcs.BAD_TOOTH]
    go_to(state, room)
    assert "knocked his bad tooth out" in room_facts(state, content)
    assert "lenny" not in ids(state, content)  # nothing to give him yet


def test_asking_lenny_points_to_his_tooth_and_giving_it_back_gets_his_good_one(content, everyone):
    seed = next(s for s in range(300) if npcs.lenny_plan(s) == (1, 1))
    state = generate(seed)
    go_to(state, with_monster(state, npcs.LENNY))
    state.player.wits = 50
    events = perform(state, content, "ask")
    assert any(e.kind == "tip" for e in events) and npcs.tooth_spot(state) is None  # it's on your map now
    state.player.inventory.append(npcs.BAD_TOOTH)
    assert "You're carrying his bad tooth" in room_facts(state, content)
    perform(state, content, "lenny")
    assert npcs.GOOD_TOOTH in state.player.inventory and npcs.BAD_TOOTH not in state.player.inventory
    assert state.room.monster.mood == "happy" and "lenny" not in ids(state, content)
    assert powers.has(state, content, "luck")  # +1 to every roll


def test_lennys_tooth_is_never_loot_and_lenny_never_roams(content):
    from ptg import loot

    assert loot.where(content, npcs.BAD_TOOTH) == [] and loot.where(content, npcs.GOOD_TOOTH) == []
    assert not content.monster(npcs.LENNY).roams and not content.monster(npcs.SWOOGY).roams
    assert not content.monster(npcs.KING_MOUSE).roams


# --- Swoogy -------------------------------------------------------------------------

def swoogy(content) -> tuple[GameState, object]:
    state = next(s for s in map(generate, range(50)) if any(r.secret for r in s.rooms))
    room = with_monster(state, npcs.SWOOGY)
    go_to(state, room)
    return state, room.monster


def test_swoogy_waits_in_secret_rooms_cut_down_to_size(content, everyone):
    state, monster = swoogy(content)
    assert state.room.secret and not monster.hostile and monster.mood == "challenge"
    base = content.monster(npcs.SWOOGY)
    assert (monster.hp, base.attack + monster.attack_mod, base.defense + monster.defense_mod) == (40, 5, 13)
    assert "swoogy" in ids(state, content) and "guess the number on his six-sided die" in room_facts(state, content)


def test_guess_swoogys_number_and_his_diaper_is_yours(content, everyone):
    state, monster = swoogy(content)
    perform(state, content, "swoogy")
    assert monster.mood == "guessing" and 1 <= monster.secret <= 6
    assert [i for i in ids(state, content) if i.startswith("guess:")] == [f"guess:{n}" for n in range(1, 7)]
    perform(state, content, f"guess:{monster.secret}")
    assert npcs.DIAPER in state.player.inventory and monster.mood == "won" and not monster.hostile
    assert npcs.DIAPER in state.rares  # he only had the one


def test_guess_wrong_and_calm_him_down_or_fight_him(content, everyone):
    state, monster = swoogy(content)
    perform(state, content, "swoogy")
    events = perform(state, content, f"guess:{monster.secret % 6 + 1}")
    assert monster.hostile and monster.mood == "angry" and monster.intent == "heavy"
    assert any(e.kind == "telegraph" for e in events)  # he charges up his flaps: you get a turn first
    state.player.gold = 25
    choices = ids(state, content)
    assert "appease:gold" in choices and "appease:healing_potion" in choices and "attack" in choices
    perform(state, content, "appease:gold")
    assert state.player.gold == 15 and not monster.hostile and monster.mood == "paid"
    assert npcs.DIAPER not in state.player.inventory and not any(i.startswith(("swoogy", "guess")) for i in ids(state, content))


def test_anything_you_carry_calms_him_if_you_say_so(content, everyone):
    state, monster = swoogy(content)
    perform(state, content, "swoogy")
    perform(state, content, f"guess:{monster.secret % 6 + 1}")
    state.player.inventory.append("rubber_duck")
    assert "appease:rubber_duck" not in ids(state, content)  # not a numbered choice...
    perform(state, content, "appease:rubber_duck")  # ...but typed, fine
    assert monster.mood == "paid" and "rubber_duck" not in state.player.inventory


def test_beat_him_and_the_diaper_is_yours_anyway(content, everyone):
    state, monster = swoogy(content)
    perform(state, content, "swoogy")
    perform(state, content, f"guess:{monster.secret % 6 + 1}")
    monster.hp, state.player.might = 1, 50
    perform(state, content, "attack")
    assert state.room.monster is None and npcs.DIAPER in state.room.items and state.status == "playing"


# --- King Mouse ---------------------------------------------------------------------

def test_king_mouse_guards_the_stairs_now_and_then_cut_down_to_size(content, everyone):
    state = generate(5)
    assert next(r for r in state.rooms if r.fixture == "stairs").monster.key != npcs.KING_MOUSE  # not on floor 1
    state.floor = 2
    build_floor(state, content)
    stairs = next(r for r in state.rooms if r.fixture == "stairs")
    mouse = stairs.monster
    base = content.monster(npcs.KING_MOUSE)
    assert mouse.key == npcs.KING_MOUSE and mouse.hostile
    assert (mouse.hp, base.attack + mouse.attack_mod, base.defense + mouse.defense_mod) == (30, 4, 12)
    go_to(state, stairs)
    mouse.hp, state.player.might = 1, 50
    perform(state, content, "attack")
    assert state.status == "playing" and "king_mouses_vest" in state.room.items  # no win: just his vest


def test_nobody_turns_up_when_the_odds_are_nil(content, monkeypatch):
    monkeypatch.setattr(npcs, "ODDS", {npcs.LENNY: 0.0, npcs.SWOOGY: 0.0, npcs.KING_MOUSE: 0.0, "npc": 0.0})
    keys = {r.monster.key for s in map(generate, range(40)) for r in s.rooms if r.monster}
    assert not keys & {npcs.LENNY, npcs.SWOOGY, npcs.KING_MOUSE}


def test_a_kid_made_npc_turns_up_calm_to_talk_to(content, monkeypatch):
    monkeypatch.setattr(npcs, "ODDS", {npcs.LENNY: 0.0, npcs.SWOOGY: 0.0, npcs.KING_MOUSE: 0.0, "npc": 1.0})
    monkeypatch.setattr(npcs, "PLACED", set())  # as if Lenny and Swoogy were anyone's
    state = generate(3)
    room = next(r for r in state.rooms if r.monster and content.monster(r.monster.key).npc)
    go_to(state, room)
    assert not room.monster.hostile and "might talk" in room_facts(state, content)
    assert "ask" in ids(state, content)


# --- tricks, the reek and the glow --------------------------------------------------

def a_fight(content, key, hp=50):
    state = generate(3)
    state.room.monster = None
    state.player.agility = -30  # (it can't miss)
    return state, put_monster(state, content, key=key, hp=hp)


def test_baby_joey_grabs_your_food_and_runs_off_with_it(content):
    state, joey = a_fight(content, "baby_joey")
    state.player.inventory = ["pickle"]
    events = combat.monster_turn(state, content, random.Random(1))
    assert joey.stolen_item == "pickle" and not state.player.inventory and any(e.kind == "steal" for e in events)
    events = combat.monster_turn(state, content, random.Random(2))
    assert state.room.monster is None and any(e.kind == "getaway" for e in events)


def test_stop_joey_and_he_drops_it_and_no_food_means_gold(content):
    state, joey = a_fight(content, "baby_joey")
    state.player.inventory, state.player.gold = [], 40
    combat.monster_turn(state, content, random.Random(1))
    assert joey.stolen_gold and state.player.gold == 40 - joey.stolen_gold
    joey.hp, state.player.might, state.player.agility = 1, 50, 50
    perform(state, content, "attack")
    assert state.room.monster is None and state.player.gold >= 40  # his own gold on top


def test_swamp_bottoms_vines_stop_you_running_until_his_next_go(content):
    state, swamp = a_fight(content, "swamp_bottoms")
    combat.monster_turn(state, content, random.Random(1))
    assert state.player.tangled and "flee" not in ids(state, content)
    assert "tangled" in room_facts(state, content)
    state.player.agility = 50  # (now it can't hit)
    combat.monster_turn(state, content, random.Random(1))
    assert not state.player.tangled and "flee" in ids(state, content)


def test_the_diaper_keeps_them_at_arms_length(content):
    hits = []
    for diaper in (False, True):
        state, goblin = a_fight(content, "goblin")
        state.player.max_hp = state.player.hp = 500
        if diaper:
            state.player.inventory.append(npcs.DIAPER)
        event = next(e for e in combat.monster_turn(state, content, random.Random(9)) if e.kind == "monster_hit")
        hits.append(event.data["damage"])
    assert hits[1] == max(1, hits[0] - 2)


def test_the_jar_o_light_sends_a_monster_running_but_not_a_boss(content):
    state, goblin = a_fight(content, "goblin")
    state.player.inventory = ["jar_o_light"]
    assert "use:jar_o_light" in ids(state, content)  # at full health too: it's the glow you want
    events = perform(state, content, "use:jar_o_light")
    assert state.room.monster is None and any(e.kind == "dazzle" for e in events)
    state, boss = a_fight(content, "drowned_abbot")
    state.player.inventory = ["jar_o_light"]
    perform(state, content, "use:jar_o_light")
    assert state.room.monster is boss


# --- what carrying things does to your stats ----------------------------------------

def test_carried_things_change_your_stats_and_letting_go_changes_them_back(content):
    state = generate(3)
    state.room.monster = None
    player = state.player
    might, wits, most, hp = player.might, player.wits, player.max_hp, player.hp
    state.room.items = [npcs.BAD_TOOTH, "unusual_butter"]
    perform(state, content, "take_all")
    assert (player.might, player.wits) == (might + 2, wits)  # +1 might, -1 wits; +1 all
    assert (player.max_hp, player.hp) == (most + 5, hp + 5)
    restored = GameState.model_validate_json(state.model_dump_json())
    assert restored.player.item_stats == player.item_stats  # a save keeps track
    player.inventory.remove("unusual_butter")
    powers.settle_stats(state, content)
    assert (player.might, player.wits, player.max_hp) == (might + 1, wits - 1, most)
    assert player.hp == most  # no more than the new most
