"""The kids' characters and things (ptg/npcs.py, combat's tricks, powers): Lucky Lenny's tooth, Swoogy's guessing game,
King Mouse at the stairs, Baby Joey's thieving, Swamp Bottoms' vines, the Diaper's reek, the Jar o' Light's glow, and
what carried things do to your stats."""

import random

import pytest

from conftest import put_monster
from ptg import combat, npcs, powers
from ptg.models import OPPOSITE, GameState, MonsterState
from ptg.rules import available_actions, perform, room_facts
from ptg.world import build_floor, generate, warden_tier


def ids(state, content):
    return [a.id for a in available_actions(state, content)]


@pytest.fixture
def everyone(monkeypatch):
    """Every character turns up wherever it can."""
    monkeypatch.setattr(npcs, "ODDS", {npcs.LENNY: 1.0, npcs.SWOOGY: 1.0, npcs.KING_MOUSE: 1.0,
                                       "npc": 0.0})


def go_to(state, room):
    state.room_id, room.visited = room.id, True


def with_monster(state, key):
    return next(r for r in state.rooms if r.monster and r.monster.key == key)


# --- Lucky Lenny -------------------------------------------------------------------

def test_lenny_turns_up_calm_with_his_tooth_hidden_nearby(content, everyone):
    seed = next(s for s in range(300) if npcs.lenny_floor(s) == 1)
    state = generate(seed)
    room = with_monster(state, npcs.LENNY)
    assert not room.monster.hostile and room.monster.mood == "tooth" and room.id != 0
    spot, feature = npcs.tooth_spot(state)
    assert feature.hidden and feature.loot == [npcs.BAD_TOOTH]
    go_to(state, room)
    assert "knocked his bad tooth out" in room_facts(state, content)
    assert "lenny" not in ids(state, content)  # nothing to give him yet


def test_lennys_quest_goes_a_step_at_a_time_take_ask_turn_in_and_claim(content, everyone):
    """The good tooth just turned up in your pack: now taking his quest, asking where the tooth flew, turning it in and
    claiming his reward are each a choice of their own."""
    seed = next(s for s in range(300) if npcs.lenny_floor(s) == 1)
    state = generate(seed)
    go_to(state, with_monster(state, npcs.LENNY))
    assert ids(state, content)[0] == "lenny_quest" and "lenny_hint" not in ids(state, content)
    turn = state.turn
    events = perform(state, content, "lenny_quest")
    assert state.quests[npcs.LENNY] == "accepted" and state.turn == turn  # (free)
    assert any(e.kind == "story_effect" and e.text.startswith("New quest") for e in events)
    assert ids(state, content)[0] == "lenny_hint"
    state.player.wits = 50
    events = perform(state, content, "lenny_hint")
    room, feature = npcs.tooth_where(state)
    assert any(e.kind == "tip" for e in events) and npcs.tooth_spot(state) is None  # the room's on your map now
    assert feature.told and feature.hidden  # (the room, not the spot: that's yours to search for)
    state.player.inventory.append(npcs.BAD_TOOTH)
    assert "You're carrying his bad tooth" in room_facts(state, content)
    events = perform(state, content, "lenny")
    assert npcs.BAD_TOOTH not in state.player.inventory and npcs.GOOD_TOOTH not in state.player.inventory
    assert state.room.monster.mood == "owed" and ids(state, content)[0] == "lenny_reward"
    events += perform(state, content, "lenny_reward")
    assert npcs.GOOD_TOOTH in state.player.inventory and state.quests[npcs.LENNY] == "done"
    assert state.room.monster.mood == "happy" and not any(i.startswith("lenny") for i in ids(state, content))
    moves = [(e.data["item"], e.data["how"], e.data["from"], e.data["to"]) for e in events if e.data.get("to")]
    assert moves == [(npcs.BAD_TOOTH, "give", "pack", npcs.LENNY), (npcs.GOOD_TOOTH, "give", npcs.LENNY, "pack")]
    assert powers.has(state, content, "luck")  # +1 to every roll
    assert all(e.data.get("quiet") for e in events if e.kind in ("lenny", "lenny_reward", "take"))  # (no narrator)


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
    assert npcs.DIAPER in state.room.items and monster.mood == "won" and not monster.hostile  # at your feet...
    assert npcs.DIAPER not in state.player.inventory  # ...to take (it's cursed: you're warned first) or leave
    assert npcs.DIAPER in state.rares  # he only had the one
    perform(state, content, f"take:{npcs.DIAPER}")
    perform(state, content, f"take:{npcs.DIAPER}")
    assert npcs.DIAPER in state.player.inventory


def test_guess_wrong_and_calm_him_down_or_fight_him(content, everyone):
    state, monster = swoogy(content)
    perform(state, content, "swoogy")
    events = perform(state, content, f"guess:{monster.secret % 6 + 1}")
    assert monster.hostile and monster.mood == "angry" and monster.intent == "heavy"
    assert any(e.kind == "telegraph" for e in events)  # he charges up his flaps: you get a turn first
    state.player.gold = 25
    choices = ids(state, content)
    assert "appease:gold" in choices and "attack" in choices
    assert "give:@monster:swoogy_the_gooey" in choices and "appease:healing_potion" not in choices  # (one to pick)
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
    monkeypatch.setattr(npcs, "ODDS", {npcs.LENNY: 0.0, npcs.SWOOGY: 0.0, npcs.KING_MOUSE: 0.0,
                                       "npc": 0.0})
    keys = {r.monster.key for s in map(generate, range(40)) for r in s.rooms if r.monster}
    assert not keys & {npcs.LENNY, npcs.SWOOGY, npcs.KING_MOUSE}


def test_a_kid_made_npc_turns_up_calm_to_talk_to(content, monkeypatch):
    monkeypatch.setattr(npcs, "ODDS", {npcs.LENNY: 0.0, npcs.SWOOGY: 0.0, npcs.KING_MOUSE: 0.0,
                                       "npc": 1.0})
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


# --- what the audit found (W1) ------------------------------------------------

def angry_swoogy(content):
    state, monster = swoogy(content)
    perform(state, content, "swoogy")
    perform(state, content, f"guess:{monster.secret % 6 + 1}")
    return state, monster


def test_the_glow_doesnt_scare_swoogy_off(content, everyone):
    """Eating the Jar o' Light sent an angry Swoogy running: no diaper, no fight, gone from the floor."""
    state, monster = angry_swoogy(content)
    state.player.inventory.append("jar_o_light")
    events = perform(state, content, "use:jar_o_light")  # (unhurt: it'd be eaten only for a glow he won't mind)
    assert events[0].kind == "info" and "jar_o_light" in state.player.inventory and state.room.monster is monster
    state.player.hp -= 4
    events = perform(state, content, "use:jar_o_light")  # (hurt: eaten for its HP, and he stands there squinting)
    assert state.room.monster is monster and "stands its ground" in next(e.text for e in events if e.kind == "dazzle")


def test_swoogy_never_gets_your_key_or_lennys_tooth(content, everyone, monkeypatch):
    """'Calm Swoogy down with the Greasy Throne-Room Key' was taken, and the boss door stayed locked for good."""
    state, monster = angry_swoogy(content)
    state.player.inventory += ["warren_key", "rubber_duck", npcs.BAD_TOOTH]
    state.rooms[0].monster = MonsterState(key=npcs.LENNY, name="Lucky Lenny", hp=8, max_hp=8, hostile=False,
                                          mood="tooth")  # (still waiting for it)
    offered = {a.id for a in npcs.unlisted(state, content)}
    assert "appease:rubber_duck" in offered and not offered & {"appease:warren_key", f"appease:{npcs.BAD_TOOTH}"}
    assert perform(state, content, "appease:warren_key")[0].text == "You can't do that right now."
    assert "warren_key" in state.player.inventory and monster.mood == "angry"
    monkeypatch.setattr(npcs, "lenny_floor", lambda seed: None)  # (no Lenny on a floor still to come)
    for room in state.rooms:
        if room.monster and room.monster.key == npcs.LENNY:
            room.monster.mood = "happy"  # he's had it back (this one's a spare): it can go
    assert f"appease:{npcs.BAD_TOOTH}" in {a.id for a in npcs.unlisted(state, content)}


def test_a_stunt_never_spends_a_key(content):
    """'Toss the key into the dark' spent the Barnacled Reliquary Key: the run couldn't be won."""
    from ptg.intent import Intent
    from ptg.rules import perform_creative

    state = generate(3)
    state.room.monster = None
    state.player.inventory.append("reliquary_key")
    _, events = perform_creative(state, content, Intent(kind="creative", difficulty="trivial", summary="toss the key",
                                                        consumes=["Barnacled Reliquary Key"]))
    assert "reliquary_key" in state.player.inventory
    assert [e.text for e in events] == ["You'll be needing the Barnacled Reliquary Key: you keep hold of it."]


@pytest.mark.parametrize("consumes", [["Barnacled Reliquary Key"], []])  # (the interpreter says so, or the verb does)
def test_a_key_you_wont_hand_over_buys_you_nothing(content, consumes):
    """Kept back but still offered, the key talked down 10 of 12 orcs, a Fate token and a soul each time."""
    from ptg.intent import Intent
    from ptg.rules import perform_creative

    state = generate(7)
    state.player.inventory += ["reliquary_key", "stale_bread"]
    state.player.fate, state.player.wits = 0, 50  # (a bribe that's made can't fail)
    orc = put_monster(state, content, "orc")
    turn, souls = state.turn, state.souls

    def bribe(name):
        intent = Intent(kind="creative", stat="wits", difficulty="medium", success_effects=["pacify"], uses=[name],
                        consumes=consumes and [name], summary=f"bribe the orc with {name}")
        return perform_creative(state, content, intent)[1]

    events = bribe("the Barnacled Reliquary Key")
    assert [e.kind for e in events] == ["info"] and "reliquary_key" in state.player.inventory
    assert orc.hostile and state.room.monster is orc  # not talked down
    assert (state.turn, state.souls, state.player.fate, state.player.style.get("flair", 0)) == (turn, souls, 0, 0)
    bribe("the Stale Bread")  # (what you'll let go of is a bribe like any other)
    assert not orc.hostile and "stale_bread" not in state.player.inventory and state.player.fate == 1


def test_lenny_yelps_when_you_hit_him(content):
    """'Lucky Lenny had stopped fighting. It hasn't now.': he never was fighting, and he isn't an it. What he yells is
    his own, on his card."""
    state = generate(3)
    state.room.monster = MonsterState(key=npcs.LENNY, name="Lucky Lenny", hp=50, max_hp=50, hostile=False,
                                      mood="tooth")
    state.player.might = -50
    events = perform(state, content, "attack")
    assert events[0].text == "Lucky Lenny yelps and puts up a fight."
    assert events[1].kind == "story" and events[1].text.startswith("WOAH WOAH WOAH WOAH! What was that for?!")


def test_a_distracted_thief_doesnt_run_off_that_turn(content):
    """The Laser Pointer said Joey 'forgets its next attack', then he scampered off with your gold that same turn."""
    state, joey = a_fight(content, "baby_joey")
    joey.stolen_gold = 5
    state.player.inventory.append("laser_pointer")
    events = perform(state, content, "distract:laser_pointer")
    assert state.room.monster is joey and not any(e.kind == "getaway" for e in events)
    assert any(e.kind == "stunned" for e in events)


def test_lenny_doesnt_send_you_looking_for_the_tooth_in_your_hand(content, everyone):
    seed = next(s for s in range(300) if npcs.lenny_floor(s) == 1)
    state = generate(seed)
    go_to(state, with_monster(state, npcs.LENNY))
    state.player.inventory.append(npcs.BAD_TOOTH)
    state.player.wits = 50
    events = perform(state, content, "ask")
    assert npcs.tooth_spot(state) is not None and not any(e.kind == "tip" for e in events)  # (not sent looking)
    assert cards(events) == [(npcs.LENNY, "has_item")] and not any(e.dice for e in events)  # (he wants it, free)
    assert not state.room.monster.asked  # (what else he knows keeps till he has it back)


def test_lenny_names_the_room_his_tooth_flew_into_in_his_own_words(content, everyone):
    seed = next(s for s in range(300) if npcs.lenny_floor(s) == 1)
    state = generate(seed)
    go_to(state, with_monster(state, npcs.LENNY))
    perform(state, content, "lenny_quest")
    state.player.wits = 50
    events = perform(state, content, "lenny_hint")
    room, _ = npcs.tooth_where(state)
    said = next(e for e in events if e.kind == "story")
    assert said.data["moment"] == "point_room" and f"in {room.name}" in said.text.replace("the ", "")


def test_swoogy_has_only_the_one_diaper(content, everyone):
    """Won on floor 1, Swoogy was back in floor 2's secret room with a second one."""
    state, monster = swoogy(content)
    perform(state, content, "swoogy")
    perform(state, content, f"guess:{monster.secret}")
    for floor in (2, 3):
        state.floor = floor
        build_floor(state, content)
        assert not any(r.monster and r.monster.key == npcs.SWOOGY for r in state.rooms)


def test_talked_down_swoogy_keeps_his_diaper_to_play_for(content, everyone):
    """Talked down, he left his diaper at your feet and still offered his game, a second diaper for the right guess;
    now talking him down pays nothing and he keeps it (F16), so there's still the one to play for."""
    import random

    state, monster = swoogy(content)
    xp, souls = state.player.xp, state.souls
    combat.defeat(state, content, random.Random(1), how="pacified")  # (provoked, then talked down)
    assert npcs.DIAPER not in state.room.items and npcs.DIAPER not in state.rares
    assert (state.player.xp, state.souls) == (xp, souls) and not monster.hostile
    offered = ids(state, content)
    assert "attack" in offered and "swoogy" in offered


# --- what they say, Talk, and where their stories have got to (W8) -----------------------------------------------

def next_door(content, who, kit="new", seed=4):
    """A test room (testrooms.py): the state, and the way in to whoever's next door."""
    from ptg import testrooms
    from ptg.models import DELTA

    state = testrooms.build(content, who, kit, seed=seed)
    here, there = state.room, testrooms.target(state)
    return state, next(d for d, (dx, dy) in DELTA.items() if (here.x + dx, here.y + dy) == (there.x, there.y))


def walk_in(content, who, kit="new", seed=4):
    state, way = next_door(content, who, kit, seed)
    return state, perform(state, content, f"go:{way}")


def cards(events):
    return [(e.data["speaker"], e.data["moment"]) for e in events if e.kind == "story" and e.data.get("speaker")]


def test_lennys_tooth_is_always_on_his_own_floor(content, everyone):
    """In 16% of Lenny's runs his tooth was hidden on the floor above him, where you could never go back for it (F14):
    the owner's call is his floor, always."""
    for seed in range(60):
        floor = npcs.lenny_floor(seed)
        state = generate(seed)
        for at in (1, 2):
            if at == 2:
                state.floor = 2
                build_floor(state, content)
            teeth = [r for r in state.rooms for f in r.features if npcs.BAD_TOOTH in f.loot]
            lenny = [r for r in state.rooms if r.monster and r.monster.key == npcs.LENNY]
            assert (len(teeth), len(lenny)) == ((1, 1) if at == floor else (0, 0)), (seed, at)


def test_meeting_lenny_he_tells_you_himself_in_his_own_words(content):
    """Walking in on Lenny gave only narrator facts, which a model garbled into 'the gold-crowned tooth you're
    holding' (F11): now he says it himself, on a card with his picture, which the narrator never rewords."""
    from ptg.game import narratable

    state, way = next_door(content, "lenny_quest")
    events = perform(state, content, f"go:{way}")
    card = next(e for e in events if e.kind == "story")
    assert card.data == {"voice": "exact", "title": "Lucky Lenny", "sprite": npcs.LENNY, "speaker": npcs.LENNY,
                         "moment": "meet", "met": npcs.LENNY}
    assert "knocked my bad tooth clean out" in card.text and not narratable(card)
    assert state.quests == {npcs.LENNY: "met"} and state.room.monster.met
    facts = room_facts(state, content)
    assert "not a monster to fight" not in facts and "fake gold crown" in facts and "or the one before" not in facts
    assert "somewhere on this floor" in facts
    again = perform(state, content, f"go:{OPPOSITE[way]}") + perform(state, content, f"go:{way}")
    assert cards(again) == []  # (once is enough)


def test_asking_where_his_tooth_flew_is_a_roll_you_can_try_again(content):
    """Asked, Lenny used to say where his tooth was for nothing. Now it's a wits roll (a turn each time) that, made,
    names the room; failed, he can't remember, and you can ask again (F14 was a roll you lost for good)."""
    state, _ = walk_in(content, "lenny_quest")
    perform(state, content, "lenny_quest")
    turn, (room, feature) = state.turn, npcs.tooth_where(state)
    state.player.wits = -50
    events = perform(state, content, "lenny_hint")
    assert any(e.dice for e in events) and not feature.told and state.turn == turn + 1
    assert [c for c in cards(events)] == [(npcs.LENNY, "forgot")] and "lenny_hint" in ids(state, content)
    state.player.wits = 50
    events = perform(state, content, "lenny_hint")
    assert feature.told == "Lucky Lenny" and feature.hidden and "lenny_hint" not in ids(state, content)
    turn = state.turn
    again = perform(state, content, f"talk:{npcs.LENNY}")  # (he says the room again, for nothing)
    assert cards(again) == [(npcs.LENNY, "point_room")] and not any(e.dice for e in again) and state.turn == turn


def test_asking_lenny_what_he_knows_never_gives_away_his_tooth(content):
    state, _ = walk_in(content, "lenny_quest")
    _, feature = npcs.tooth_where(state)
    state.player.wits = 50
    perform(state, content, "ask")  # (his gossip: a roll, once)
    assert state.room.monster.asked and not feature.told and feature.hidden


def test_lenny_with_his_tooth_in_your_pack_and_his_thanks(content):
    state, events = walk_in(content, "lenny")
    assert cards(events) == [(npcs.LENNY, "has_item")] and state.quests[npcs.LENNY] == "met"
    assert ids(state, content)[:3] == ["lenny", f"talk:{npcs.LENNY}", "ask"] and ids(state, content)[-1] == "attack"
    turn = state.turn
    events = perform(state, content, "lenny")
    assert cards(events) == [(npcs.LENNY, "turn_in")] and state.quests[npcs.LENNY] == "turned_in"
    assert state.turn == turn and npcs.status(state, content, npcs.LENNY) == "has a reward for you"
    assert cards(perform(state, content, f"talk:{npcs.LENNY}")) == [(npcs.LENNY, "owed")]
    events = perform(state, content, "lenny_reward")
    assert cards(events) == [(npcs.LENNY, "reward")] and state.quests[npcs.LENNY] == "done"
    assert any(e.kind == "story_effect" and e.text.startswith("Quest complete") for e in events)
    assert cards(perform(state, content, f"talk:{npcs.LENNY}")) == [(npcs.LENNY, "after")]
    refused = perform(state, content, f"give:healing_potion@monster:{npcs.LENNY}")
    assert [e.kind for e in refused] == ["info", "story"] and cards(refused) == [(npcs.LENNY, "keep_it")]
    assert "healing_potion" in state.player.inventory and npcs.status(state, content, npcs.LENNY) == \
        "has his bad tooth back"


def test_found_before_you_meet_him_his_tooth_says_whose_it_is(content, everyone):
    """Finding the tooth first, nothing said whose it was or that anyone wanted it (F36)."""
    seed = next(s for s in range(300) if npcs.lenny_floor(s) == 1)
    state = generate(seed)
    room, feature = npcs.tooth_where(state)
    go_to(state, room)
    feature.hidden, room.monster = False, None  # (nothing else about)
    perform(state, content, f"search:{room.features.index(feature)}")
    events = perform(state, content, f"take:{npcs.BAD_TOOTH}")
    assert state.quests[npcs.LENNY] == "found_item"
    assert any(e.kind == "story_effect" and "LENNY" in e.text for e in events)
    assert npcs.quest_log(state, content)[0][2] and npcs.wanted_by(state, content, npcs.BAD_TOOTH)
    assert npcs.wanted_by(state, content, "healing_potion") == ""


def test_hit_lenny_fights_back_and_his_tooth_still_calms_him(content):
    """Attacked, the facts still called him 'a friendly fellow, not a monster to fight', and 'Give' was gone (F33)."""
    state, _ = walk_in(content, "lenny")
    state.player.might = -50  # (a miss)
    events = perform(state, content, "attack")
    assert cards(events) == [(npcs.LENNY, "angry")] and state.quests[npcs.LENNY] == "angry"
    facts = room_facts(state, content)
    assert "fighting back" in facts and "friendly" not in facts and "You're carrying his bad tooth" in facts
    assert "lenny" in ids(state, content) and npcs.primary_actions(state, content)[0].id == "lenny"
    events = perform(state, content, "lenny")
    assert events[0].kind == "calm" and not state.in_combat and state.quests[npcs.LENNY] == "turned_in"


def test_hit_swoogy_mid_game_and_hes_cranky_with_his_price_to_pay(content, everyone):
    """Attacked during his challenge or mid-guess, the facts still had him wanting to play, and nothing calmed him
    (F33)."""
    for guessing in (False, True):
        state, monster = swoogy(content)
        if guessing:
            perform(state, content, "swoogy")
        state.player.might, state.player.gold = -50, 50
        events = perform(state, content, "attack")
        assert cards(events) == [(npcs.SWOOGY, "angry")] and monster.mood == "angry" and monster.hostile
        facts = room_facts(state, content)
        assert "furious" in facts and "play a game" not in facts and "waiting for your guess" not in facts
        assert "appease:gold" in ids(state, content)
        assert cards(perform(state, content, "appease:gold")) == [(npcs.SWOOGY, "paid")] and not monster.hostile


def test_swoogys_game_in_his_own_words(content, everyone):
    state, way = next_door(content, "swoogy")
    perform(state, content, f"bomb:{way}")
    met = perform(state, content, f"go:{way}") + perform(state, content, f"go:{OPPOSITE[way]}") + \
        perform(state, content, f"go:{way}")
    assert cards(met) == [(npcs.SWOOGY, "meet")] and state.quests[npcs.SWOOGY] == "challenge"
    monster = state.room.monster
    assert cards(perform(state, content, f"talk:{npcs.SWOOGY}")) == [(npcs.SWOOGY, "talk")]
    assert cards(perform(state, content, "swoogy")) == [(npcs.SWOOGY, "guessing")]
    assert ids(state, content)[:6] == [f"guess:{n}" for n in range(1, 7)]  # (typing 3 guesses 3)
    lost = perform(state, content, f"guess:{monster.secret % 6 + 1}")
    assert cards(lost) == [(npcs.SWOOGY, "lost")] and state.quests[npcs.SWOOGY] == "angry"
    assert [e.kind for e in perform(state, content, f"talk:{npcs.SWOOGY}")] == ["info"]  # (not mid-fight)
    state.player.gold = 50
    perform(state, content, "appease:gold")
    assert cards(perform(state, content, f"talk:{npcs.SWOOGY}")) == [(npcs.SWOOGY, "sulk")]
    state, monster = swoogy(content)
    perform(state, content, "swoogy")
    assert cards(perform(state, content, f"guess:{monster.secret}")) == [(npcs.SWOOGY, "won")]
    assert cards(perform(state, content, f"talk:{npcs.SWOOGY}")) == [(npcs.SWOOGY, "bare")]
    assert state.quests[npcs.SWOOGY] == "won" and npcs.quest_log(state, content)[0][1] == "You won Swoogy's diaper."


def test_shopkeepers_greet_you_thank_you_and_talk(content):
    """Granny's counter showed her bestiary entry where a greeting would go, and a shop had no Talk or Ask (F11,
    F35)."""
    state, events = walk_in(content, "shop")
    keeper = state.room.shop.keeper
    assert cards(events) == [(keeper, "greet")]
    assert ids(state, content)[:3] == ["shop", f"talk:{keeper}", "ask"]
    assert cards(perform(state, content, f"talk:{keeper}")) == [(keeper, "talk")]
    assert cards(perform(state, content, "buy:0")) == [(keeper, "thanks")]
    door = next(iter(state.room.exits))
    back = perform(state, content, f"go:{door}") and perform(state, content, f"go:{OPPOSITE[door]}")
    assert cards(back) == [(keeper, "again")]
    state.player.wits = 50
    asked = perform(state, content, "ask")  # (she knows her floor too: a wits roll, once)
    assert asked and state.room.shop.asked and "ask" not in ids(state, content)


async def test_a_purchase_and_its_thanks_need_no_narrator(content, profile, fake_llm):
    from ptg.config import Config
    from ptg.game import Game

    from ptg.events import Action

    state, _ = walk_in(content, "shop")
    game = Game(state, Config(), fake_llm(text="The narrator says something."), profile=profile)
    result = await game.act("buy", lambda _: None, action=Action("buy:0", "Buy it"))
    assert result.narration.startswith("You buy ") and "narrator" not in result.narration
    assert game.state.log[-1].kind == "card" and game.state.log[-1].title == content.monster(
        state.room.shop.keeper).name and game.state.log[-1].speaker == state.room.shop.keeper  # (hers, on a Continue)
    assert game.state.journal[-1].startswith(f"{game.state.log[-1].title}: ")  # (who said it)


def test_king_mouse_has_his_say(content):
    """King Mouse got no intro, and his 'squeeeeeeeEEAKKK!!!' was only ever a heavy-blow tell (F11)."""
    state, events = walk_in(content, "king_mouse", "strong")
    assert cards(events) == [(npcs.KING_MOUSE, "meet")]
    assert "squeeeeeeeEEAKKK!!!" in next(e for e in events if e.kind == "story").text
    assert "guards the stairs" in room_facts(state, content)
    mouse = state.room.monster
    mouse.hp, state.player.might = 1, 50
    events = []
    while state.room.monster:
        events = perform(state, content, "attack")
    assert cards(events) == [(npcs.KING_MOUSE, "beaten")] and state.quests[npcs.KING_MOUSE] == "beaten"


def test_a_maker_npc_with_no_lines_of_its_own_gets_the_npc_ones(content):
    """A kid's next NPC turned up with only Ask and Attack (F35)."""
    import dataclasses

    from ptg.content import MonsterDef

    squeaks = MonsterDef(key="sir_squeaks", name="Sir Squeaks", hp=8, defense=12, attack=3, damage="1d6", xp=10,
                         tier=1, tags=["npc"], intelligent=True)
    made = dataclasses.replace(content, monsters={**content.monsters, "sir_squeaks": squeaks})
    state = generate(3)
    state.room.monster = MonsterState(key="sir_squeaks", name="Sir Squeaks", hp=8, max_hp=8, hostile=False)
    assert npcs.speaks(made, "sir_squeaks") and not npcs.speaks(made, "goblin")
    said = npcs.say(state, made, "sir_squeaks", "meet")
    assert said[0].text == "Oh! Hello there. I'm Sir Squeaks. I'm not here to fight, honest!"
    talk = npcs.talk_action(state, made)
    assert talk.id == "talk:sir_squeaks" and npcs.talk(state, made, "sir_squeaks")[0].data["moment"] == "talk"


async def test_talking_is_free_and_typed_too(content, profile):
    """Offline, 'talk to lenny' and 'talk to granny' were 'The dungeon is unimpressed', and in a fight an 'ask' handed
    the monster a free swing (F35)."""
    from ptg.config import Config
    from ptg.game import Game

    state, _ = walk_in(content, "lenny_quest")
    game = Game(state, Config(backend="offline"), None, content, profile)
    for words in ("talk to lenny", "ask lenny what his favourite food is", "hello there"):
        turn = game.state.turn
        result = await game.act(words, lambda _: None)
        assert result.narration == "" or "points a shaky finger" in result.narration, words
        assert any(e.data.get("speaker") == npcs.LENNY for e in result.events) and game.state.turn == turn, words
    state, monster = angry_swoogy(content)
    hp = state.player.hp
    game = Game(state, Config(backend="offline"), None, content, profile)
    result = await game.act("talk to swoogy", lambda _: None)
    assert [e.text for e in result.events] == ["Swoogy The Gooey is fighting you, not chatting."]
    assert state.player.hp == hp and monster.hostile


def test_talking_a_calm_character_down_is_just_talking(content):
    """A creative 'pacify' at a calm character rolled for nothing (F35): it's talking to them."""
    from ptg.intent import Intent
    from ptg.rules import perform_creative

    state, _ = walk_in(content, "lenny")
    _, events = perform_creative(state, content, Intent(kind="creative", stat="wits", difficulty="medium",
                                                        success_effects=["pacify"], summary="cheer lenny up"))
    assert cards(events) == [(npcs.LENNY, "has_item")] and not any(e.dice for e in events)


def test_a_calm_characters_card_offers_what_it_wants_first(content):
    """Clicking Lenny's name offered Attack, and Enter ended the quest (F13): primary_actions, for the card's Enter."""
    state, _ = walk_in(content, "lenny")
    assert [a.id for a in npcs.primary_actions(state, content)] == ["lenny", f"talk:{npcs.LENNY}", "ask", "attack"]
    state, _ = walk_in(content, "shop")
    assert [a.id for a in npcs.primary_actions(state, content)][:2] == ["shop", f"talk:{state.room.shop.keeper}"]


def test_swoogy_is_as_tough_as_his_maker_made_him_on_floor_one(content):
    """Sized for floor 1, Swoogy (his maker's tier 4) dropped to the warden's tier 2: dodge 13->11, flee 14->12, souls
    36->18 (carried from the W1 review). Characters are only ever raised to the floor's warden, never lowered."""
    from ptg.combat import defeat, dodge, flee

    state = generate(3)
    state.room.monster = npcs.sized(content, npcs.SWOOGY, 1, npcs.SWOOGY_SIZE, hostile=True, mood="angry")
    assert state.room.monster.tier == 4
    assert next(e for e in dodge(state, content, random.Random(1)) if e.dice).dice.dc == 13
    assert next(e for e in flee(state, content, random.Random(1)) if e.dice).dice.dc == 14
    state.room.monster = npcs.sized(content, npcs.SWOOGY, 1, npcs.SWOOGY_SIZE, hostile=True, mood="angry")
    souls = state.souls
    defeat(state, content, random.Random(1))
    assert state.souls - souls == 36  # 3 a tier, three times over
    assert npcs.sized(content, npcs.KING_MOUSE, 2, npcs.KING_MOUSE_SIZE).tier == warden_tier(2)  # (raised to it)


def test_the_map_marks_lenny_while_he_waits(content):
    from ptg.world import map_glyph

    state, way = next_door(content, "lenny")
    room = state.rooms[state.room.exits[way].to]
    perform(state, content, f"go:{way}")
    perform(state, content, f"go:{OPPOSITE[way]}")
    assert map_glyph(state, room) == "☺"
    perform(state, content, f"go:{way}")
    perform(state, content, "lenny")
    perform(state, content, f"go:{OPPOSITE[way]}")
    assert map_glyph(state, room) == "☺"  # (turned in: he still has your reward waiting)
    perform(state, content, f"go:{way}")
    perform(state, content, "lenny_reward")
    perform(state, content, f"go:{OPPOSITE[way]}")
    assert map_glyph(state, room) != "☺"


def test_the_glossary_colours_characters_as_friends(content):
    """Lenny, Swoogy and the Grannies were highlighted in foe red (F77)."""
    from ptg.glossary import Lexicon, build

    state, _ = walk_in(content, "lenny")
    terms = {t.id: t for t in build(state, content, {"granny_gristle": {}, "goblin": {}}).values()}  # (met, so named)
    assert terms[f"monster:{npcs.LENNY}"].kind == "character" and terms["monster:granny_gristle"].kind == "character"
    assert terms["monster:goblin"].kind == "monster"
    assert "wants his bad tooth back" in terms[f"monster:{npcs.LENNY}"].summary
    state.room.monster.hostile = True
    assert Lexicon(build(state, content)).find("Lucky Lenny")[0][2].kind == "monster"  # (fighting you: a foe)


def test_every_character_has_its_lines(content):
    """What the code has each character say, the data has a line for."""
    needs = {npcs.LENNY: ["meet", "accept", "wondering", "point_room", "forgot", "has_item", "lying", "missing",
                          "turn_in", "owed", "reward", "after", "refuse_gift", "keep_it", "angry", "calmed", "beaten"],
             npcs.SWOOGY: ["meet", "again", "talk", "guessing", "won", "lost", "angry", "paid", "calmed", "sulk",
                           "bare", "refuse_gift", "keep_it", "beaten"],
             npcs.KING_MOUSE: ["meet", "angry", "calmed", "talk", "beaten"],
             "granny_gristle": ["greet", "again", "talk", "thanks", "buys", "haggle_won", "haggle_lost"],
             "granny_kamultruk": ["greet", "again", "talk", "thanks", "buys", "haggle_won", "haggle_lost"],
             "npc": ["meet", "talk", "refuse_gift", "angry", "calmed", "beaten"]}
    for who, moments in needs.items():
        assert not [m for m in moments if not content.dialogue[who].get(m)], who
    for who in ("baby_joey", "swamp_bottoms"):
        assert content.dialogue[who]["meet"] and npcs.speaks(content, who)


def test_a_save_keeps_where_their_stories_are(content):
    state, _ = walk_in(content, "lenny_quest")
    perform(state, content, f"talk:{npcs.LENNY}")
    restored = GameState.model_validate_json(state.model_dump_json())
    assert restored.quests == {npcs.LENNY: "met"} and restored.said == state.said and restored.room.monster.met


async def test_the_game_screen_shows_what_they_say_as_story_cards():
    """Meeting Lenny on screen was a room picture and narration, nothing else (F11): his words are a card, with his
    picture, and so is what he says when you talk to him (no turn)."""
    from ptg import testrooms
    from ptg.config import Config
    from ptg.models import DELTA
    from ptg.ui.app import PTGApp
    from ptg.ui.game_screen import GameScreen
    from ptg.ui.widgets import Picture

    app = PTGApp(Config(backend="offline", layout="classic", player_name="Tester"), test_room=("lenny_quest", "new", 0, 4))
    async with app.run_test(size=(150, 46)) as pilot:
        for _ in range(50):
            await pilot.pause(0.1)
            if isinstance(app.screen, GameScreen) and not app.screen.busy:
                break
        screen = app.screen
        state = screen.game.state
        here, there = state.room, testrooms.target(state)
        way = next(d for d, (dx, dy) in DELTA.items() if (here.x + dx, here.y + dy) == (there.x, there.y))
        await pilot.press(way[0], "enter")
        for _ in range(50):
            await pilot.pause(0.1)
            if not screen.busy:
                break
        [card] = screen.query(".say")  # his words, with who is speaking first, and no picture (it's Here's)
        assert str(card.render()).startswith("Lucky Lenny:") and not card.query(Picture)
        turn = screen.game.state.turn
        talk = next(i for i, a in enumerate(screen.game.choices(), 1) if a.id.startswith("talk:"))
        await pilot.press(*str(talk), "enter")  # Talk to Lucky Lenny
        for _ in range(50):
            await pilot.pause(0.1)
            if not screen.busy:
                break
        assert len(screen.query(".say")) == 2 and screen.game.state.turn == turn
        assert screen.game.state.log[-1].kind == "card"  # (his words, and nothing told over them)


def test_the_kids_monsters_bark_too(content):
    """Baby Joey's and Swamp Bottoms' catchphrases were only heavy-blow tells: now they've a first-meeting bark, and
    Joey crows over what he grabs."""
    state, events = walk_in(content, "baby_joey")
    assert cards(events) == [("baby_joey", "meet")] and state.in_combat
    state.player.inventory, state.player.agility, state.player.might = ["pickle"], -50, -50
    state.room.monster.intent = "strike"
    events = perform(state, content, "attack")
    assert ("baby_joey", "steal") in cards(events) and state.room.monster.stolen_item == "pickle"
    state, events = walk_in(content, "swamp_bottoms")
    assert cards(events) == [("swamp_bottoms", "meet")]
    assert "Somethings Comin'" in next(e for e in events if e.kind == "story").text


def test_meeting_swoogy_again_on_a_later_floor_is_a_rematch(content, everyone):
    """Met (and left cranky, or paid off) on one floor, Swoogy turns up in a later secret room wanting a rematch: it's
    not his first meeting this run, so a story's "when: meet" doesn't fire again."""
    state, way = next_door(content, "swoogy")
    perform(state, content, f"bomb:{way}")
    first = perform(state, content, f"go:{way}")
    assert [e.data.get("met") for e in first if e.kind == "story"] == [npcs.SWOOGY]
    state.player.gold = 50
    perform(state, content, "swoogy")
    perform(state, content, f"guess:{state.room.monster.secret % 6 + 1}")
    perform(state, content, "appease:gold")
    later = npcs.sized(content, npcs.SWOOGY, 2, npcs.SWOOGY_SIZE, hostile=False, mood="challenge")
    state.room.monster = later  # (as if a floor further down)
    events = perform(state, content, f"go:{OPPOSITE[way]}") + perform(state, content, f"go:{way}")
    assert cards(events) == [(npcs.SWOOGY, "again")] and not any(e.data.get("met") for e in events)
    assert state.quests[npcs.SWOOGY] == "challenge"


def test_lennys_tooth_is_never_in_his_own_room(content, everyone):
    """His tooth turned up in the room he was standing in, the quest over before it began."""
    seen = 0
    for seed in range(80):
        floor = npcs.lenny_floor(seed)
        if floor != 1:
            continue
        state = generate(seed)
        lenny = next((r for r in state.rooms if r.monster and r.monster.key == npcs.LENNY), None)
        where = npcs.tooth_where(state)
        if lenny and where:
            seen += 1
            assert where[0].id != lenny.id, seed
    assert seen >= 10
