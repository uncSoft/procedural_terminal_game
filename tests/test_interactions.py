"""The interaction grid (ptg/interactions.py, ptg/scene.py): typed refs for everything here, (verb, subject, target)
uses with a row each, creative stunts as the fallback that wastes nothing, and what the UI is to call."""

import random

import pytest

from conftest import FakeLLM, put_monster
from ptg import interactions, inventory, npcs, testrooms
from ptg.combat import defeat
from ptg.config import Config
from ptg.creative import available_props, clamp_intent, gold_said, match_props
from ptg.game import Game
from ptg.intent import Intent
from ptg.interactions import choices, from_intent, is_picker, parse, use_id, verbs
from ptg.llm.interpreter import interpret, offline_interpret
from ptg.models import Feature
from ptg.rules import available_actions, perform, perform_creative, room_facts, unlisted
from ptg.scene import RoomView
from ptg.world import build_floor, generate


def ids(state, content):
    return [a.id for a in available_actions(state, content)]


def stunt(summary: str, **fields) -> Intent:
    base = dict(kind="creative", stat="wits", difficulty="medium", success_effects=["damage_small"], summary=summary)
    return Intent(**{**base, **fields})


def quiet_room(seed=3):
    state = generate(seed)
    state.room.monster = None
    return state


def calm(state, content, key, mood=""):
    monster = put_monster(state, content, key=key)
    monster.hostile, monster.mood = False, mood or ("tooth" if key == npcs.LENNY else "")
    return monster


def clamped(state, content, effects):
    return clamp_intent(state, content, stunt("do something clever", success_effects=effects)).success_effects


def angry_swoogy(content, kit="strong"):
    state = testrooms.build(content, "swoogy", kit, seed=3)
    state.room_id = testrooms.target(state).id
    swoogy = state.room.monster
    swoogy.mood, swoogy.hostile, swoogy.intent = "angry", True, "heavy"
    return state, swoogy


# --- the refs, and the action ids -------------------------------------------------------------------------------------

def test_everything_you_could_act_on_is_a_ref(content):
    """Fixtures, exits, the monster, bombs and small keys were nothing a stunt could name or aim at (F19)."""
    state = quiet_room()
    state.room.fixture = "chest"
    state.player.keys, state.player.gold = 2, 7
    put_monster(state, content, key="goblin")
    state.room.items = ["pickle"]
    view = RoomView(state, content)
    found = {ref.id for ref in view.refs}
    assert {"self", "room", "monster:goblin", "gear:weapon", "item:healing_potion", "bombs", "keys", "gold",
            "floor:pickle", "feature:0", "fixture:chest"} <= found
    assert {f"exit:{d}" for d in state.room.exits} <= found
    assert view.get("keys").count == 2 and view.get("gold").count == 7
    assert view.get("monster:goblin").state["hostile"] and view.match("the goblin's eyes", ("monster",)).key == "goblin"
    assert view.match("the bomb", ("item", "bombs")).id == "bombs"  # (not the Smoke Bomb's, which isn't yours)
    assert any(line.startswith("monster:goblin  Goblin (hostile") for line in view.lines())


def test_an_action_id_says_the_whole_use(content):
    assert use_id("give", "gold", "monster:goblin", 30) == "give:gold*30@monster:goblin"
    use = parse("give:gold*30@monster:goblin")
    assert (use.verb, use.subject, use.target, use.amount) == ("give", "gold", "monster:goblin", 30)
    assert parse("use:healing_potion") is None and parse("attack") is None  # (the engine's own, as they were)
    assert is_picker("give:@monster:lucky_lenny") and is_picker("use:holy_water@")
    assert not is_picker("use:holy_water@monster:ghoul") and not is_picker("smash:@fixture:chest")


# --- F19: the grid has rows for what had none -----------------------------------------------------------------------

def test_prying_the_chest_open_with_an_axe_opens_the_chest(content):
    """'pry the chest open with the hand axe' rolled for a random find and left the chest shut."""
    state = quiet_room()
    state.room.fixture = "chest"
    state.player.inventory.append("hand_axe")
    intent = stunt("pry the chest open with the hand axe", success_effects=["find_item"], uses=["Hand Axe", "chest"])
    assert from_intent(state, content, intent) == "smash:hand_axe@fixture:chest"
    _, events = perform_creative(state, content, intent)
    assert events[0].kind == "chest" and events[0].dice.label == "might (smash it)" and state.room.fixture_used


def test_prying_a_feature_finds_what_is_in_it(content):
    """Prying the offering bowl turned up a random Smoke Bomb, and left its own bomb for 'Search'."""
    state = quiet_room()
    state.room.features = [Feature(name="an offering bowl", loot=["holy_water"])]
    _, events = perform_creative(state, content, stunt("pry open the offering bowl", success_effects=["find_item"]))
    assert state.room.items == ["holy_water"] and state.room.features[0].searched
    assert [e.kind for e in events] == ["find"]


def test_keys_and_bombs_work_on_chests_and_doors(content):
    state = quiet_room()
    state.room.fixture, state.player.keys = "chest", 1
    assert perform(state, content, "use:small_key@fixture:chest")[0].text.startswith("The small key turns")
    state.room.fixture_used, state.room.items, bombs = False, [], state.player.bombs
    events = perform(state, content, "use:bomb@fixture:chest")  # (a bomb opens it, and breaks what's inside)
    assert events[0].text.startswith("The bomb blows the lid clean off") and state.player.bombs == bombs - 1
    assert events[-1].text.startswith("Inside: ") and not state.room.items and state.room.fixture_used


def test_the_boss_key_opens_its_door_and_nothing_else_does(content):
    state = generate(11)
    state.floor = 3
    build_floor(state, content)
    gate = next(r for r in state.rooms for e in r.exits.values() if e.locked and not e.key)
    direction = next(d for d, e in gate.exits.items() if e.locked and not e.key)
    state.room_id, gate.monster = gate.id, None
    state.player.inventory.append("war_pick")
    turn = state.turn
    for action in (f"use:war_pick@exit:{direction}", f"use:bomb@exit:{direction}", f"smash:@exit:{direction}"):
        [event] = perform(state, content, action)
        assert event.kind == "info" and ("budge" in event.text or "too stout" in event.text)
    assert state.turn == turn and state.player.bombs == 1 and gate.exits[direction].locked
    key = content.themes[state.theme].key_item
    state.player.inventory.append(key)
    perform(state, content, f"use:{key}@exit:{direction}")
    assert state.room.is_boss and key in state.player.inventory


def test_smashing_down_the_locked_door_says_it_holds_and_costs_nothing(content):
    """'smash down the locked door with my war pick' was told as done; the door stayed locked (F17)."""
    state = testrooms.build(content, "shop", "new", seed=5)
    state.player.inventory.append("war_pick")
    door = next(d for d, e in state.room.exits.items() if e.locked)
    intent = stunt("smash down the locked door with my war pick", success_effects=["nothing"], stat="might")
    _, events = perform_creative(state, content, intent)
    assert [e.kind for e in events] == ["info"] and "doesn't budge" in events[0].text
    assert state.room.exits[door].locked and state.turn == 0


def test_holy_water_on_your_weapon_makes_its_hits_holy(content):
    """'pour holy water on my axe' used up the vial and changed nothing (F17): there's a recipe for it now."""
    state = quiet_room()
    state.player.inventory = ["holy_water"]
    _, events = perform_creative(state, content, stunt("pour the holy water on my sword", success_effects=["nothing"]))
    assert events[0].kind == "coat" and "holy_water" not in state.player.inventory
    assert state.player.coating == "holy" and state.player.coated == 3
    ghoul = put_monster(state, content, key="ghoul", hp=200)  # weak to holy
    state.player.might = 50
    events = perform(state, content, "attack")
    assert "holy!" in events[0].text and "holy" in state.known_weak["ghoul"] and state.player.coated == 2
    assert ghoul.hp < 200


def test_two_things_with_no_recipe_come_to_nothing_and_nothing_is_used_up(content):
    state = quiet_room()
    state.player.inventory = ["pickle", "cheese_wheel"]
    [event] = perform(state, content, "use:pickle@item:cheese_wheel")
    assert event.kind == "info" and "You keep both" in event.text
    assert state.player.inventory == ["pickle", "cheese_wheel"]


def test_holy_water_thrown_comes_out_the_same_however_it_is_said(content):
    """Typed, 'throw vial of holy water' was combat.throw (2d4); said to the model it was a stunt's 1d4/2d6 plus a
    pacify, with flair (run 36). Either way now, it's thrown."""
    rolls = []
    for how in ("throw:holy_water", "splash my holy water in its face"):
        state = generate(3)
        put_monster(state, content, key="wight", hp=200)
        state.player.inventory = ["holy_water"]
        fate = state.player.fate
        if ":" in how:
            events = perform(state, content, how)
        else:
            _, events = perform_creative(state, content, stunt(how, success_effects=["damage_medium", "pacify"]))
        rolls.append((events[0].kind, events[0].dice.label, events[0].dice.kept))
        assert "holy_water" not in state.player.inventory and state.room.monster.hostile and state.player.fate == fate
    assert rolls[0] == rolls[1]


def test_a_stunt_cant_hurt_it_and_talk_it_down_at_once(content):
    """A thrown holy water resolved as damage_medium + pacify: hit, then talked down (run 36)."""
    state = generate(3)
    put_monster(state, content, key="hobgoblin", hp=200)
    assert clamped(state, content, ["damage_medium", "pacify"]) == ["damage_medium"]
    assert clamped(state, content, ["pacify", "stun"]) == ["pacify"]


def test_a_fixture_is_a_prop(content):
    """'Throw the chest at the goblin', 'drown the orc in the fountain' rolled with no prop bonus (F19)."""
    state = generate(3)
    state.room.fixture = "fountain"
    put_monster(state, content, key="orc", hp=200)
    _, events = perform_creative(state, content, stunt("drown the orc in the fountain", uses=["fountain"]))
    assert ("✦ fountain", 2) in events[0].dice.bonuses


# --- F17: a stunt that can't change anything isn't made ---------------------------------------------------------------

def test_a_stunt_with_nothing_to_it_costs_nothing_and_says_so(content):
    """'You give the ghoul the wheel of cheese.' (cheese gone, free ghoul attack): no outcome, told as done."""
    state = generate(3)
    put_monster(state, content, key="rat_king", hp=200)
    state.player.inventory.append("cheese_wheel")
    _, events = perform_creative(state, content, stunt("sing the rat king a lullaby", success_effects=["pacify"]))
    [event] = events
    assert event.kind == "creative" and event.text == ("You try to sing the rat king a lullaby, but the Rat King "
                                                       "doesn't understand a word of it.")
    assert state.turn == 0 and state.player.hp == state.player.max_hp  # no turn: it didn't get a free go at you
    _, events = perform_creative(state, content, stunt("hum a tune", difficulty="trivial"))
    assert events[0].text == "You try to hum a tune. Nothing much comes of it." and state.turn == 0


def test_cheese_for_the_ghoul_is_refused_and_kept(content):
    state = generate(3)
    put_monster(state, content, key="ghoul", hp=50)
    state.player.inventory.append("cheese_wheel")
    _, events = perform_creative(state, content, stunt("give the ghoul the wheel of cheese", success_effects=["pacify"],
                                                       consumes=["Wheel of Cheese"]))
    assert [e.text for e in events] == ["The Ghoul sniffs the Wheel of Cheese and ignores it. You keep it."]
    assert "cheese_wheel" in state.player.inventory and state.turn == 0


def test_a_beast_shy_of_noise_is_dazed_not_talked_down(content):
    """The Rubber Chicken (loud) against the Rat King (weak to loud): the pacify was dropped, no roll, a free attack."""
    state = generate(3)
    put_monster(state, content, key="rat_king", hp=200)
    state.player.weapon = "rubber_chicken"
    chicken = match_props(["Rubber Chicken"], available_props(state, content))
    intent = stunt("squeak the rubber chicken at it", success_effects=["pacify"])
    assert clamp_intent(state, content, intent, chicken).success_effects == ["stun"]


# --- F37, F38: only what's used is used up, and only as much gold as is said ----------------------------------------

def test_sand_at_the_rats_eyes_spends_no_pizza_rat(content):
    """'throw sand at the rat's eyes' used up the Pizza Rat (the word 'rat') and counted it against the Giant Rat's
    weakness to food."""
    state = generate(3)
    put_monster(state, content, key="giant_rat", hp=200)
    state.player.inventory.append("pizza_rat")
    state.player.agility = 50
    _, events = perform_creative(state, content, stunt("throw sand at the rat's eyes", stat="agility",
                                                       success_effects=["stun"]))
    assert "pizza_rat" in state.player.inventory and "giant_rat" not in state.known_weak
    assert events[0].data["props"] == []


def test_a_bribe_takes_the_gold_you_offer(content):
    """'offer 10 gold' took 5, 'offer 30 gold' on floor 2 took 10."""
    state = generate(3)
    state.floor = 2
    put_monster(state, content, key="hobgoblin", hp=50)
    state.player.gold, state.player.wits = 100, 50
    _, events = perform_creative(state, content, stunt("offer 30 gold to the hobgoblin", success_effects=["pacify"],
                                                       consumes=["gold coins"]))
    assert state.player.gold == 70 and not state.room.monster.hostile
    assert events[0].data["gold"] == 30 and events[0].data["to"] == "hobgoblin"  # (what changed hands: F31)


def test_gold_offered_to_what_doesnt_care_for_it_stays_yours(content):
    state = generate(3)
    state.floor = 2
    put_monster(state, content, key="bog_lurker", hp=50)
    state.player.gold = 40
    _, events = perform_creative(state, content, stunt("offer 10 gold for the lurker's forgiveness",
                                                       success_effects=["pacify"], consumes=["gold coins"]))
    assert [e.text for e in events] == ["The Bog Lurker doesn't care about gold. You keep it."]
    assert state.player.gold == 40 and state.turn == 0


def test_a_stunt_that_hands_over_gold_hands_over_what_it_says(content):
    state = generate(3)
    state.player.gold = 50
    assert gold_said(state, stunt("toss 12 coins into the dark")) == 12
    assert gold_said(state, stunt("toss a handful of coins")) == 5  # (no amount said: a few)
    assert gold_said(state, stunt("toss ninety gold coins", amount=90)) == 50  # (no more than you have)


def test_a_bribe_hands_the_gift_to_the_monster_and_plays_on_its_weakness(content):
    state = generate(3)
    goblin = put_monster(state, content, key="goblin", hp=50)  # weak to shiny
    state.player.inventory.append("bag_of_marbles")
    state.player.wits, state.player.fate = 50, 0
    events = perform(state, content, "give:bag_of_marbles@monster:goblin")
    assert events[0].dice.advantage == 1 and ("✦ Bag of Marbles", 2) in events[0].dice.bonuses
    given = events[0].data
    assert (given["item"], given["from"], given["to"]) == ("bag_of_marbles", "pack", "goblin")
    assert not goblin.hostile and "shiny" in state.known_weak["goblin"] and state.player.fate == 1


def test_a_bribe_that_doesnt_work_leaves_the_gift_with_you(content):
    state = generate(3)
    orc = put_monster(state, content, key="orc", hp=200)
    state.player.inventory.append("stale_bread")
    state.player.wits = -50
    events = perform(state, content, "give:stale_bread@monster:orc")
    assert events[0].kind == "check" and not events[0].data["success"] and "You keep" in events[0].text
    assert "stale_bread" in state.player.inventory and orc.hostile


# --- F39: a calm creature fights back, and a gift goes to whoever's given it ----------------------------------------

def test_oil_thrown_at_calm_lenny_provokes_him_and_pays_no_flair(content):
    """'It works', the oil used up, Lenny unhurt and calm, and a Fate token for it."""
    state = generate(3)
    lenny = calm(state, content, npcs.LENNY)
    state.player.inventory.append("oil_flask")
    state.player.fate, state.player.agility = 0, 50
    _, events = perform_creative(state, content, stunt("throw the flask of lamp oil at lucky lenny",
                                                       consumes=["Flask of Lamp Oil"]))
    assert [e.kind for e in events[:3]] == ["provoke", "story", "hit"] and lenny.hostile and lenny.hp < 8  # (WOAH!)
    assert state.player.fate == 0 and "oil_flask" not in state.player.inventory


def test_a_stunt_against_a_calm_creature_provokes_it_first(content):
    state = generate(3)
    goblin = calm(state, content, "goblin")
    state.player.wits = 50
    _, events = perform_creative(state, content, stunt("kick dust at the goblin", success_effects=["stun"]))
    assert events[0].kind == "provoke" and goblin.hostile and goblin.stunned


def test_lenny_takes_only_his_tooth(content):
    """'give lucky lenny the wheel of cheese': it worked, the cheese was gone, a Fate token, and Lenny never knew."""
    state = generate(3)
    lenny = calm(state, content, npcs.LENNY)
    state.player.inventory += ["cheese_wheel", npcs.BAD_TOOTH]
    state.player.fate = 0
    _, events = perform_creative(state, content, stunt("give lucky lenny the wheel of cheese",
                                                       success_effects=["pacify"]))
    assert [e.kind for e in events] == ["info", "story"] and "hands it back" in events[0].text
    assert events[1].text.startswith("That's not my tooth!") and events[1].data["speaker"] == npcs.LENNY
    assert "cheese_wheel" in state.player.inventory and state.player.fate == 0
    events = perform(state, content, f"give:{npcs.BAD_TOOTH}@monster:{npcs.LENNY}")  # (turned in: his reward waits)
    assert lenny.mood == "owed" and npcs.GOOD_TOOTH not in state.player.inventory
    events += perform(state, content, "lenny_reward")
    assert lenny.mood == "happy" and npcs.GOOD_TOOTH in state.player.inventory
    moves = [(e.data["item"], e.data["from"], e.data["to"]) for e in events if e.data.get("to")]
    assert moves == [(npcs.BAD_TOOTH, "pack", npcs.LENNY), (npcs.GOOD_TOOTH, npcs.LENNY, "pack")]  # (F31)


def test_his_tooth_calms_lenny_down_even_after_you_hit_him(content):
    state = generate(3)
    lenny = calm(state, content, npcs.LENNY)
    lenny.hostile = True
    state.player.inventory.append(npcs.BAD_TOOTH)
    events = perform(state, content, f"give:{npcs.BAD_TOOTH}@monster:{npcs.LENNY}")
    assert events[0].kind == "calm" and not lenny.hostile and lenny.mood == "owed"  # (his reward's a choice of its own)
    assert not any(e.kind == "monster_hit" for e in events)


# --- F40: flair only for a stunt that changed something --------------------------------------------------------------

def test_tapping_the_walls_over_and_over_earns_nothing(content):
    """12 'tap the walls with the hand axe' filled Fate and gave 9 souls, each 'nothing hidden here'."""
    state = quiet_room()
    for feature in state.room.features:
        feature.hidden = False
    state.player.wits, state.player.fate = 50, 0
    told = []
    for turn in range(6):
        state.turn = turn
        told += perform_creative(state, content, stunt("tap the walls with the hand axe", difficulty="easy",
                                                       success_effects=["reveal_secret"], uses=["Rusty Sword"]))[1]
    assert state.souls == 0 and not {"flair", "creative_win"} & set(state.player.style)
    assert not any(e.text.startswith("Style points") for e in told)  # (a natural 20's Fate is its own)
    assert not state.room.history  # (nor is "it worked" remembered of it)


def test_a_stunt_that_works_still_earns_its_flair(content):
    state = generate(3)
    put_monster(state, content, key="orc", hp=200)
    state.player.wits, state.player.fate = 50, 0
    state.player.inventory.append("stale_bread")
    _, events = perform_creative(state, content, stunt("smack the orc with the stale bread", uses=["Stale Bread"]))
    assert any(e.kind == "hit" for e in events) and state.player.fate == 1 and state.souls == 1


def test_a_stunt_uses_up_what_it_throws_only_if_it_works(content):
    for wits, kept in ((-50, True), (50, False)):
        state = generate(3)
        put_monster(state, content, key="orc", hp=200)
        state.player.wits = wits
        state.player.inventory.append("bag_of_marbles")
        perform_creative(state, content, stunt("scatter the bag of marbles under the orc's feet",
                                               success_effects=["stun"], uses=["Bag of Marbles"]))
        assert ("bag_of_marbles" in state.player.inventory) is kept


# --- F16: a character talked down is npcs' to say how -----------------------------------------------------------------

def test_talking_angry_swoogy_down_pays_nothing_and_he_keeps_his_diaper(content):
    """A lullaby for an angry Swoogy paid +72 XP, +36 souls and his diaper, and left him 'furious'."""
    state, swoogy = angry_swoogy(content)
    xp, souls, lying = state.player.xp, state.souls, list(state.room.items)
    state.player.wits = 50
    _, events = perform_creative(state, content, stunt("sing Swoogy a lullaby", success_effects=["pacify"],
                                                       difficulty="hard"))
    assert any(e.kind == "pacify" for e in events) and not swoogy.hostile and swoogy.mood == "calmed"
    assert (state.player.xp, state.souls, state.room.items) == (xp, souls, lying)
    assert npcs.DIAPER not in state.rares and "furious" not in room_facts(state, content)


def test_a_character_calmed_by_a_story_keeps_what_it_has(content):
    state, swoogy = angry_swoogy(content)
    swoogy.hostile = False
    events = defeat(state, content, random.Random(1), how="pacified")
    assert events[0].data["how"] == "calmed" and npcs.DIAPER not in state.room.items and state.room.monster is swoogy


# --- F44: what can't be done says why, and costs nothing ------------------------------------------------------------

def test_drinking_at_full_health_in_a_fight_says_why_and_costs_no_turn(content):
    """'drink the potion' at full HP became flavor, and the goblin swung."""
    state = generate(3)
    put_monster(state, content, key="goblin", hp=50)
    intent, _ = offline_interpret("drink the potion", available_actions(state, content) + unlisted(state, content))
    assert intent.action_id == "use:healing_potion"
    events = perform(state, content, intent.action_id)
    assert [e.text for e in events] == ["You're not hurt, so you keep the Healing Potion."] and state.turn == 0


async def test_asking_mid_fight_says_why(content, profile):
    """The model's 'ask' for a hostile Baby Joey wasn't listed, so it became flavor: Joey hit, and nothing else."""
    state = generate(3)
    put_monster(state, content, key="baby_joey", hp=50)
    reply = {"kind": "action", "action_id": "ask", "stat": "none", "difficulty": "trivial", "success_effects": [],
             "failure_effects": [], "uses": [], "consumes": [], "summary": ""}
    game = Game(state, Config(), FakeLLM(reply=reply), profile=profile)
    result = await game.act("ask baby joey what he knows", lambda _: None)
    assert [e.text for e in result.events] == ["Baby Joey is fighting you, not chatting."]
    assert game.state.turn == 0


def test_resting_mid_fight_says_why(content):
    state = generate(3)
    put_monster(state, content, key="goblin", hp=50)
    state.player.hp -= 5
    assert perform(state, content, "rest")[0].text == "Not in the middle of a fight." and state.turn == 0
    assert "rest" in {a.id for a in unlisted(state, content)}  # (so "rest" is matched, and told so)


async def test_a_gift_typed_with_no_model_is_given(content, profile):
    """Offline, 'give lenny the healing potion' was flavor, narrated as done ("You give lenny the healing potion")."""
    state = generate(3)
    calm(state, content, npcs.LENNY)
    game = Game(state, Config(backend="offline"), None, profile=profile)
    result = await game.act("give lenny the healing potion", lambda _: None)
    assert result.narration == "Lucky Lenny sniffs the Healing Potion and hands it back."
    assert game.state.log[-1].kind == "card" and game.state.log[-1].text.startswith("That's not my tooth!")
    assert "healing_potion" in game.state.player.inventory


def test_known_actions_that_cant_be_done_say_why(content):
    state = quiet_room()
    state.room.fixture, state.room.fixture_used = "shrine", True
    assert perform(state, content, "shrine_blood")[0].text == "The shrine has given all it will."
    state.room.fixture = "chest"
    assert perform(state, content, "chest_key")[0].text == "The chest is open already."
    wall = next(d for d in ("north", "south", "east", "west") if d not in state.room.exits)
    assert "solid earth" in perform(state, content, f"bomb:{wall}")[0].text
    assert perform(state, content, "rest")[0].text == "You're not hurt: there's nothing to rest off."
    assert state.turn == 0


def test_an_unavailable_action_is_not_taken_for_sure_when_a_model_could_read_it(content):
    state = generate(3)
    put_monster(state, content, key="goblin", hp=50)
    llm = FakeLLM(reply={"kind": "flavor", "action_id": "", "stat": "none", "difficulty": "trivial",
                         "success_effects": [], "failure_effects": [], "uses": [], "consumes": [], "summary": "x"})
    import asyncio

    intent, _ = asyncio.run(interpret(llm, state, content, "drink the potion",
                                      available_actions(state, content) + unlisted(state, content)))
    assert llm.json_calls == 1  # (not confident: the model was asked)


# --- F81: one row to give Swoogy something, not one an item ---------------------------------------------------------

def test_angry_swoogy_offers_one_row_to_give_him_something(content):
    state, swoogy = angry_swoogy(content)
    state.player.inventory += ["pickle", "cheese_wheel", "rubber_duck"]
    offered = ids(state, content)
    assert "appease:gold" in offered and "give:@monster:swoogy_the_gooey" in offered
    assert not any(i.startswith("appease:") and i != "appease:gold" for i in offered)
    events = perform(state, content, "give:@monster:swoogy_the_gooey")  # (a picker only says what there is)
    assert events[0].text.startswith("Give Swoogy The Gooey what? ") and "Pickle" in events[0].text
    assert events[0].data["quiet"] and state.turn == 0
    picked = choices(state, content, "give:@monster:swoogy_the_gooey")
    assert {f"give:{key}@monster:swoogy_the_gooey" for key in ("pickle", "rubber_duck")} <= {a.id for a in picked}
    events = perform(state, content, "give:rubber_duck@monster:swoogy_the_gooey")
    assert swoogy.mood == "paid" and "rubber_duck" not in state.player.inventory
    assert (events[0].data["item"], events[0].data["to"]) == ("rubber_duck", npcs.SWOOGY)


def test_swoogy_takes_more_gold_if_you_say_so_but_not_less(content):
    state, swoogy = angry_swoogy(content)
    state.player.gold = 100
    [refused] = perform(state, content, "give:gold*5@monster:swoogy_the_gooey")
    assert "it'd take 10" in refused.text and swoogy.hostile and state.player.gold == 100
    events = perform(state, content, "give:gold*25@monster:swoogy_the_gooey")
    assert state.player.gold == 75 and swoogy.mood == "paid"
    assert events[0].data == {"gold": 25, "how": "give", "from": "purse", "to": npcs.SWOOGY}  # (F31)


# --- F6: a key never goes, whatever the way ---------------------------------------------------------------------------

@pytest.mark.parametrize("action", [f"{verb}:warren_key@monster:swoogy_the_gooey" for verb in ("give", "throw", "use")])
def test_the_boss_key_is_never_handed_over_or_thrown(content, action):
    state, swoogy = angry_swoogy(content)
    state.player.inventory.append("warren_key")
    [event] = perform(state, content, action)
    assert event.kind == "info" and "needing" in event.text and "warren_key" in state.player.inventory
    assert swoogy.hostile and state.turn == 0


async def test_typing_that_swoogy_gets_the_key_keeps_it(content, profile):
    """Offline, 'calm swoogy down with the Greasy Throne-Room Key' was taken, and the run couldn't be won."""
    state, swoogy = angry_swoogy(content)
    key = content.themes[state.theme].key_item
    state.player.inventory.append(key)
    game = Game(state, Config(backend="offline"), None, profile=profile)
    result = await game.act(f"calm swoogy down with the {content.item(key).name}", lambda _: None)
    assert [e.kind for e in result.events] == ["info"] and "needing" in result.events[0].text
    assert key in game.state.player.inventory and swoogy.hostile


def test_a_bribe_with_the_key_is_refused(content):
    state = generate(3)
    put_monster(state, content, key="goblin", hp=50)
    state.player.inventory.append("reliquary_key")
    _, events = perform_creative(state, content, stunt("bribe the goblin with the key", success_effects=["pacify"]))
    assert [e.kind for e in events] == ["info"] and "reliquary_key" in state.player.inventory


# --- what the W1 and W5 reviews left (carried over) -------------------------------------------------------------------

def test_a_stunt_that_only_mentions_the_key_still_happens(content):
    """'throw the healing potion at the goblin while holding the key' was refused outright ('You'll be needing...')."""
    state = generate(3)
    put_monster(state, content, key="goblin", hp=50)
    state.player.inventory.append("reliquary_key")
    _, events = perform_creative(state, content, stunt("throw the healing potion at the goblin while holding the key",
                                                       consumes=["Healing Potion"], uses=["Barnacled Reliquary Key"]))
    assert events[0].kind in ("hit", "miss") and "healing_potion" not in state.player.inventory
    assert "reliquary_key" in state.player.inventory
    _, events = perform_creative(state, content, stunt("jingle the key to lure the goblin into the pit",
                                                       success_effects=["stun"], uses=["Barnacled Reliquary Key"]))
    assert events[0].kind == "check" and "reliquary_key" in state.player.inventory


@pytest.mark.parametrize("summary", [
    "leave the room with the war pick over your shoulder", "wear a grin and twirl the war pick",
    "remove the cobwebs from the chain shirt", "swap insults with the goblin", "leave the chain shirt on",
    "wear down the door with the war pick", "put the war pick on the table", "leave with the healing potion",
])
def test_words_that_only_mention_your_gear_dont_move_it(content, summary):
    """A trivial stunt with a move word anywhere and a thing you carry named dropped, wore or took off the thing."""
    state = quiet_room()
    state.player.armor = "chain_shirt"
    state.player.inventory += ["war_pick"]
    assert from_intent(state, content, Intent(kind="creative", difficulty="trivial", summary=summary)) is None
    perform_creative(state, content, Intent(kind="creative", difficulty="trivial", summary=summary))
    assert (state.player.weapon, state.player.armor, state.room.items) == ("rusty_sword", "chain_shirt", [])
    assert "war_pick" in state.player.inventory and "healing_potion" in state.player.inventory


@pytest.mark.parametrize("summary, action", [
    ("put away the rusty sword and wield the war pick", "equip:war_pick"),
    ("take the chain shirt off", "unequip:armor"), ("I toss the bread away into the corner", "drop:stale_bread"),
    ("get rid of the stale bread", "drop:stale_bread"), ("put the stale bread down on the floor", "drop:stale_bread"),
])
def test_a_move_said_plainly_is_that_move(content, summary, action):
    state = quiet_room()
    state.player.armor = "chain_shirt"
    state.player.inventory += ["war_pick", "stale_bread"]
    assert from_intent(state, content, Intent(kind="creative", difficulty="trivial", summary=summary)) == action


def test_praying_lifts_a_curse_at_a_shrine_youve_already_used(content):
    """A shrine you'd bled on offered no prayer, and a prayer used the shrine up."""
    state = quiet_room()
    state.room.fixture = "shrine"
    perform(state, content, "shrine_blood")
    assert state.room.fixture_used and "shrine_pray" not in ids(state, content)
    state.player.inventory.append("a_ring_probably_importan")
    assert "shrine_pray" in ids(state, content)
    events = perform(state, content, "shrine_pray")
    assert "the curse lifts" in events[0].text and not inventory.sticky(state, content, "a_ring_probably_importan")
    state.room.fixture_used = False
    state.player.inventory.append(npcs.DIAPER)
    perform(state, content, "shrine_pray")
    assert not state.room.fixture_used and "shrine_blood" in ids(state, content)  # (a prayer isn't its one use)


# --- for the UI: each thing's verbs, and pickers ----------------------------------------------------------------------

def test_each_thing_here_has_its_verbs(content):
    state = testrooms.build(content, "lenny", "strong", seed=3)
    state.room_id = testrooms.target(state).id
    state.room.items = ["war_pick"]
    state.player.hp -= 5
    assert [a.label for a in verbs(state, content, f"monster:{npcs.LENNY}")] == ["Turn in his tooth", "Talk", "Ask",
                                                                                 "Attack"]
    assert verbs(state, content, f"monster:{npcs.LENNY}")[1].id == f"talk:{npcs.LENNY}"  # (his own words, no turn)
    tooth = verbs(state, content, f"item:{npcs.BAD_TOOTH}")[0]  # (F13: the tooth's card offers what it's for)
    assert (tooth.id, tooth.label) == (f"give:{npcs.BAD_TOOTH}@monster:{npcs.LENNY}", "Give it to Lucky Lenny")
    assert [a.id for a in verbs(state, content, "floor:war_pick")] == ["take:war_pick", "equip:war_pick"]
    assert [a.label for a in verbs(state, content, "self")] == ["Use…"]
    potion = verbs(state, content, "item:superior_healing_potion")
    assert potion[0].id == "use:superior_healing_potion" and potion[0].label == "Drink"
    holy = {a.label: a.id for a in verbs(state, content, "item:holy_water")}
    assert holy["Use on…"] == "use:holy_water@" and is_picker(holy["Use on…"])
    targets = {a.id: a.label for a in choices(state, content, "use:holy_water@")}
    assert targets["use:holy_water@gear:weapon"] == "Pour the Vial of Holy Water on your Silvered Blade"
    assert verbs(state, content, "monster:goblin") == []  # (not here)


def test_a_chest_offers_every_way_open(content):
    state = quiet_room()
    state.room.fixture, state.player.keys = "chest", 1
    assert [a.label for a in verbs(state, content, "fixture:chest")] == ["Unlock", "Pick the lock", "Smash it open",
                                                                         "Bomb it"]
    state.player.keys = state.player.bombs = 0
    assert [a.label for a in verbs(state, content, "fixture:chest")] == ["Pick the lock", "Smash it open"]


def test_a_fight_offers_attack_and_a_picker_of_what_to_use(content):
    state = generate(3)
    put_monster(state, content, key="goblin", hp=50)
    state.player.inventory += ["holy_water", "laser_pointer"]
    labels = [a.label for a in verbs(state, content, "monster:goblin")]
    assert labels == ["Attack", "Use…"]
    options = {a.id for a in choices(state, content, "use:@monster:goblin")}
    assert {"use:holy_water@monster:goblin", "use:laser_pointer@monster:goblin", "use:bomb@monster:goblin"} <= options


def test_every_option_a_picker_offers_does_what_it_says(content):
    """What a picker says would work, does: none of its ids is turned down."""
    state, _ = angry_swoogy(content)
    for option in choices(state, content, "give:@monster:swoogy_the_gooey"):
        if option.hint != interactions.NO:
            trial = state.model_copy(deep=True)
            assert perform(trial, content, option.id)[0].kind != "info", option.id


def test_the_interpreter_hears_of_gifts_a_character_would_take(content):
    """Hit, Lenny's tooth was no longer a choice, though saying you give it him still worked (and calmed him): now it's
    a choice in the fight too (F14), and either way it calms him."""
    state = generate(3)
    calm(state, content, npcs.LENNY).hostile = True
    state.player.inventory.append(npcs.BAD_TOOTH)
    offered = next(a for a in available_actions(state, content) if a.id == "lenny")
    assert offered.label == "Turn in: give Lucky Lenny his bad tooth" and offered.hint == "he'd stop fighting"
    intent, _ = offline_interpret("give lucky lenny his bad tooth", available_actions(state, content)
                                  + unlisted(state, content))
    assert perform(state, content, intent.action_id)[0].kind == "calm"
    state = generate(3)
    swoogy = calm(state, content, npcs.SWOOGY, mood="angry")
    swoogy.hostile = True
    state.player.inventory.append("rubber_duck")
    said = {a.id: a.label for a in interactions.unlisted(state, content)}
    assert said[f"give:rubber_duck@monster:{npcs.SWOOGY}"] == "Calm Swoogy down with the Rubber Duck"
