"""The interpreter (ptg/llm/interpreter.py): typed words, and a model's replies, onto the interaction grid. A table of
every phrase the audit found misread, with what each is now (read with no model, and whether it's sure enough to
skip one), what the important ones do when played offline, replies from a fake model in the v2 schema (verb,
subject, target, amount), what the model is shown, and the suggested trick (drawn from the grid)."""

import asyncio

import pytest

from conftest import FakeLLM, put_monster
from ptg import npcs, testrooms
from ptg.config import Config
from ptg.creative import perform_creative
from ptg.dice import stream
from ptg.game import Game
from ptg.intent import Intent, intent_schema
from ptg.llm import extras
from ptg.llm.interpreter import guessed, interpret, looks, offline_interpret
from ptg.llm.prompts import interpreter_messages, player_status, situation
from ptg.models import Feature
from ptg.rules import available_actions, perform, unlisted
from ptg.scene import RoomView
from ptg.world import generate

FLAVOR = {"kind": "flavor", "action_id": "", "stat": "none", "difficulty": "trivial", "success_effects": [],
          "failure_effects": [], "uses": [], "consumes": [], "summary": "", "verb": "", "subject": "", "target": "",
          "amount": 0}


# --- the rooms the audit typed in -----------------------------------------------------------------------------------

def fight(content, key, items, hurt=False, hp=60):
    state = generate(3)
    put_monster(state, content, key=key, hp=hp)
    state.player.weapon, state.player.inventory, state.player.bombs = "hand_axe", list(items), 2
    state.player.hp -= 10 if hurt else 0
    return state


def ghoul(content, hurt=False):
    return fight(content, "ghoul", ["smoke_bomb", "holy_water", "cheese_wheel", "healing_potion", "pickle"], hurt)


def rat_king(content):
    return fight(content, "rat_king", ["oil_flask", "rubber_chicken", "healing_potion", "bag_of_marbles"])


def hobgoblin(content):
    return fight(content, "hobgoblin", ["healing_potion", "stale_bread", "holy_water"], hurt=True)


def dire_wolf(content):
    return fight(content, "dire_wolf", ["unusual_butter", "bag_of_marbles", "oil_flask"])


def swoogy(content, mood="angry"):
    """Swoogy in his secret room (the strong kit, seed 11): angry (a wrong guess), or waiting for a guess."""
    state = testrooms.build(content, "swoogy", "strong", seed=11)
    state.room_id = testrooms.target(state).id
    monster = state.room.monster
    monster.mood, monster.hostile, monster.secret = mood, mood == "angry", 6
    monster.intent = "heavy" if mood == "angry" else "strike"
    state.player.inventory += ["healing_potion", "rubber_duck", "pickle", "cheese_wheel"]
    return state


def guessing(content):
    return swoogy(content, "guessing")


def lenny(content):
    state = generate(3)
    monster = put_monster(state, content, key=npcs.LENNY)
    monster.hostile, monster.mood = False, "tooth"
    state.player.inventory.append(npcs.BAD_TOOTH)
    return state


def quiet(content, seed=3):
    state = generate(seed)
    state.room.monster = None
    return state


def chest(content, calm=None):
    """A chest, a small key to open it and a War Pick lying here (seed 1, the audit's), maybe a calm creature too."""
    state = quiet(content, 1)
    state.room.fixture, state.room.fixture_used, state.player.keys = "chest", False, 1
    state.room.items = ["war_pick"]
    if calm:
        put_monster(state, content, key=calm).hostile = False
    return state


def chest_and_goblin(content):
    return chest(content, calm="goblin")


def shrine(content, cursed=False):
    state = quiet(content)
    state.room.fixture, state.room.fixture_used = "shrine", False
    state.player.inventory.append(npcs.BAD_TOOTH)
    if cursed:
        state.player.inventory.append("a_ring_probably_importan")
    return state


def cursed_shrine(content):
    return shrine(content, cursed=True)


def carrying(content):
    state = quiet(content)
    state.player.armor = "chain_shirt"
    state.player.inventory += ["war_pick", "moonsilver_vest", "stale_bread"]
    return state


ROOMS = {f.__name__: f for f in (ghoul, rat_king, hobgoblin, dire_wolf, swoogy, guessing, lenny, quiet, chest,
                                  chest_and_goblin, shrine, cursed_shrine, carrying)}
ROOMS["ghoul_hurt"] = lambda content: ghoul(content, hurt=True)


def given(state, content):
    """What the game hands the interpreter: the numbered choices and everything else that may be said."""
    return available_actions(state, content) + unlisted(state, content)


# --- the table: (room, typed, what it is now, sure enough to skip the model) ---------------------------------------

TABLE = [
    # F12: a Smoke Bomb is no bomb, and a gift is never a bomb thrown
    ("ghoul", "give him my smoke bomb", "give:smoke_bomb@monster:ghoul", False),
    ("ghoul", "use smoke bomb", "use:smoke_bomb", True),
    ("ghoul", "throw smoke bomb", "use:smoke_bomb", True),
    ("ghoul", "throw the smoke bomb", "use:smoke_bomb", True),
    ("ghoul", "use the smoke bomb", "use:smoke_bomb", True),
    ("ghoul", "light the smoke bomb", "use:smoke_bomb", True),
    ("ghoul", "throw smoke bombs", "use:smoke_bomb", True),
    ("ghoul", "throw a bomb", "bomb", True),
    ("ghoul", "bomb it", "bomb", True),
    ("swoogy", "give him my smoke bomb", "give:smoke_bomb@monster:swoogy_the_gooey", False),
    ("swoogy", "give swoogy the smoke bomb", "give:smoke_bomb@monster:swoogy_the_gooey", False),
    ("swoogy", "calm him down with the smoke bomb", "give:smoke_bomb@monster:swoogy_the_gooey", False),
    ("swoogy", "throw the healing potion to swoogy", "give:healing_potion@monster:swoogy_the_gooey", False),
    # F15: what's thrown is what's named, never what the monster's name matches, and a throw is never a drink
    ("ghoul", "throw the cheese at the ghoul", "throw:cheese_wheel@monster:ghoul", True),
    ("ghoul", "throw the potion at the ghoul", "throw:healing_potion@monster:ghoul", True),
    ("ghoul", "throw the pickle at the ghoul", "throw:pickle@monster:ghoul", True),
    ("ghoul", "throw my axe at the ghoul", "throw:hand_axe@monster:ghoul", False),  # (in your hand: refused)
    ("ghoul", "throw the holy water at the ghoul", "throw:holy_water", True),
    ("ghoul_hurt", "throw the cheese at the ghoul", "throw:cheese_wheel@monster:ghoul", True),
    ("ghoul_hurt", "throw the potion at the ghoul", "throw:healing_potion@monster:ghoul", True),
    ("ghoul_hurt", "drink the potion", "use:healing_potion", True),
    ("rat_king", "throw the rubber chicken at the rat king", "throw:rubber_chicken", True),  # (a spare: a choice)
    ("rat_king", "Throw the Rubber Chicken at the Rat King", "throw:rubber_chicken", True),
    ("rat_king", "throw marbles at the rat king's feet", "throw:bag_of_marbles", True),
    ("rat_king", "throw my healing potion at the rat king", "throw:healing_potion@monster:rat_king", True),
    ("rat_king", "throw the oil at the rat king", "throw:oil_flask", True),
    ("hobgoblin", "Throw the Healing Potion at the Hobgoblin", "throw:healing_potion@monster:hobgoblin", True),
    ("hobgoblin", "Throw the stale bread at the hobgoblin", "throw:stale_bread@monster:hobgoblin", True),
    ("hobgoblin", "eat the bread", "use:stale_bread", True),
    ("dire_wolf", "Throw Unusual Butter at the Dire Wolf", "throw:unusual_butter@monster:dire_wolf", True),
    ("dire_wolf", "Throw the Bag of Marbles at the Dire Wolf", "throw:bag_of_marbles", True),
    # F18: the chest by what's done to it; no reading alike for a different thing
    ("chest", "unlock the chest", "chest_key", True),
    ("chest", "smash the chest", "chest_smash", True),
    ("chest", "kick the chest", "chest_smash", True),
    ("chest", "bomb the chest", "chest_bomb", True),
    ("chest", "open the chest", "chest_key", True),
    ("chest", "pick the lock", "chest", True),
    ("chest", "pick the chest's lock", "chest", True),
    ("chest", "use the key on the chest", "chest_key", True),
    ("chest", "open chest with key", "chest_key", True),
    ("chest", "unlock the chest with my key", "chest_key", True),
    ("chest", "pick up the war pick", "take:war_pick", True),
    ("chest_and_goblin", "kick the chest", "chest_smash", True),  # (not the calm goblin)
    ("shrine", "offer the tooth at the shrine", "give:lenny_s_bad_tooth@fixture:shrine", False),
    ("shrine", "offer blood at the shrine", "shrine_blood", True),
    # F42: while Swoogy waits, a number is the guess
    ("guessing", "3", "guess:3", True),
    ("guessing", "i guess three", "guess:3", True),
    ("guessing", "four", "guess:4", True),
    ("guessing", "3!", "guess:3", True),
    ("guessing", "guess 3", "guess:3", True),
    # F43: gifts, said any way
    ("lenny", "give the tooth to lenny", "lenny", False),
    ("lenny", "hand lenny the bad tooth", "lenny", False),
    ("lenny", "return the tooth to lenny", "lenny", False),
    ("lenny", "give him his tooth back", "lenny", False),
    ("lenny", "give lucky lenny his tooth", "lenny", False),
    ("lenny", "talk to lenny", "talk:lucky_lenny", True),
    ("lenny", "give lenny a hug", "flavor", False),  # (his name isn't his tooth's: nothing named is handed over)
    ("lenny", "show lenny a trick", "flavor", False),
    ("swoogy", "give him the rubber duck", "appease:rubber_duck", False),
    ("swoogy", "feed swoogy the pickle", "give:pickle@monster:swoogy_the_gooey", False),
    ("swoogy", "offer swoogy the cheese", "give:cheese_wheel@monster:swoogy_the_gooey", False),
    ("swoogy", "pay swoogy", "appease:gold", False),
    ("swoogy", "give swoogy 20 gold", "give:gold*20@monster:swoogy_the_gooey", False),
    # F83: a look is a look; only searching searches the room
    ("quiet", "look around", "question", True),
    ("quiet", "look", "question", True),
    ("quiet", "check the room", "question", True),
    ("quiet", "examine room", "question", True),
    ("quiet", "look around the room", "question", True),
    ("quiet", "look at the room", "question", True),
    ("quiet", "look for secrets", "search_room", True),
    ("quiet", "search the room", "search_room", True),
    ("quiet", "search for secrets", "search_room", True),
    # F26 and the W5 review: only the thing a move is done to is moved
    ("carrying", "leave with the healing potion", "flavor", False),
    ("carrying", "leave the room with the war pick", "flavor", False),
    ("carrying", "leave the chain shirt on", "flavor", False),
    ("carrying", "wear down the door with the war pick", "flavor", False),
    ("carrying", "remove the cobwebs from my chain shirt", "flavor", False),
    ("carrying", "drop down and eat the bread", "flavor", False),
    ("carrying", "wield the war pick", "equip:war_pick", True),
    ("carrying", "put away my sword and wield the war pick", "equip:war_pick", False),
    # the W5 review: a typed prayer reaches the shrine
    ("cursed_shrine", "pray", "shrine_pray", True),
    ("cursed_shrine", "pray at the shrine", "shrine_pray", True),
    ("cursed_shrine", "lift the curse", "shrine_pray", True),
    ("cursed_shrine", "kneel and pray", "shrine_pray", True),
    ("shrine", "pray at the shrine", "shrine_pray", True),  # (with no curse, told why not)
]


@pytest.mark.parametrize("room, typed, wanted, sure", TABLE, ids=[f"{r}: {t}" for r, t, *_ in TABLE])
def test_what_the_audit_typed_is_read_as_what_it_says(content, room, typed, wanted, sure):
    state = ROOMS[room](content)
    intent, confident = offline_interpret(typed, given(state, content), RoomView(state, content))
    assert (intent.action_id or intent.kind, confident) == (wanted, sure)
    llm = FakeLLM(reply=FLAVOR)
    asyncio.run(interpret(llm, state, content, typed, given(state, content)))
    assert llm.json_calls == (0 if sure else 1)  # (a gift, or a character named: the model may know better)


@pytest.mark.parametrize("typed", ["guess 3 or 4", "7", "roll 3 dice", "I guess the goblin did it"])
def test_only_one_number_from_one_to_six_is_a_guess(content, typed):
    assert guessed(typed, given(guessing(content), content)) is None
    assert guessed("3", given(quiet(content), content)) is None  # (nor is anything, when he isn't guessing)


def test_a_look_is_only_a_look():
    assert all(looks(words) for words in ("look", "look around", "I look around carefully", "check the room"))
    assert not any(looks(words) for words in ("look for secrets", "look behind the shelf", "check the chest"))


# --- played offline -------------------------------------------------------------------------------------------------

def play(state, typed, profile, llm=None):
    game = Game(state, Config(backend="offline") if llm is None else Config(), llm, profile=profile)
    result = asyncio.run(game.act(typed, lambda _: None))
    return game.state, result


def test_a_smoke_bomb_used_is_your_getaway_and_no_bomb_goes_off(content, profile):
    """'use smoke bomb' threw one of the two bombs you needed for walls and doors (F12)."""
    state, result = play(ghoul(content), "use smoke bomb", profile)
    assert state.player.bombs == 2 and "smoke_bomb" not in state.player.inventory and not state.in_combat


def test_a_smoke_bomb_given_to_angry_swoogy_calms_him_and_nobody_is_hit(content, profile):
    """'give him my smoke bomb' bombed Swoogy, who answered with a 20-damage heavy blow (F12)."""
    before = swoogy(content)
    hp, bombs = before.player.hp, before.player.bombs
    state, result = play(before, "give him my smoke bomb", profile)
    assert not state.room.monster.hostile and state.room.monster.mood == "paid"
    assert state.player.bombs == bombs and state.player.hp == hp and "smoke_bomb" not in state.player.inventory


def test_the_cheese_thrown_at_the_ghoul_is_the_cheese(content, profile):
    """'throw the cheese at the ghoul' threw the holy water; hurt, it ate the cheese (F15)."""
    for hurt in (False, True):
        before = ghoul(content, hurt)
        hp = before.player.hp
        state, result = play(before, "throw the cheese at the ghoul", profile)
        assert "cheese_wheel" not in state.player.inventory and "holy_water" in state.player.inventory
        assert state.player.hp <= hp and "Wheel of Cheese" in result.events[0].text


def test_a_healing_potion_thrown_is_thrown_not_drunk(content, profile):
    """A hurt player's 'Throw the Healing Potion at the Hobgoblin' drank it (F15)."""
    before = hobgoblin(content)
    hp = before.player.hp
    state, result = play(before, "Throw the Healing Potion at the Hobgoblin", profile)
    assert "healing_potion" not in state.player.inventory and state.player.hp <= hp
    assert not any(e.kind == "heal" for e in result.events)


def test_unlocking_the_chest_with_a_key_springs_no_needle(content, profile):
    """'unlock the chest' with a key in hand picked the lock, and the needle jabbed (F18)."""
    before = chest(content)
    hp = before.player.hp
    state, _ = play(before, "unlock the chest", profile)
    assert state.room.fixture_used and state.player.keys == 0 and state.player.hp == hp


def test_typing_a_number_while_swoogy_waits_guesses_that_number(content, profile):
    """Typing '3' picked choice #3, which was 'Guess 1' (F42): now it's a guess of 3, wherever the guesses are."""
    game = Game(guessing(content), Config(backend="offline"), None, profile=profile)
    listed = game.choices
    game.choices = lambda: list(reversed(listed()))  # (choice 3 isn't "Guess 3" here)
    pending = asyncio.run(game.begin("3"))
    assert pending.intent.action_id == "guess:3" and pending.shown == "Guess 3"
    assert game.state.room.monster.mood == "angry"  # (his die says 6)
    game = Game(guessing(content), Config(backend="offline"), None, profile=profile)
    assert asyncio.run(game.begin("i guess six")).intent.action_id == "guess:6" and \
        game.state.room.monster.mood == "won"
    game = Game(guessing(content), Config(backend="offline"), None, profile=profile)
    # (a click on a choice sends its number: so the guesses come first, each its own number)
    assert [a.id for a in game.choices()[:6]] == [f"guess:{n}" for n in range(1, 7)]


def test_a_gift_to_angry_swoogy_typed_offline_calms_him_with_no_free_blow(content, profile):
    """Offline, 'give him the rubber duck' was flavor, and Swoogy got a free heavy blow (F43)."""
    before = swoogy(content)
    hp = before.player.hp
    state, _ = play(before, "give him the rubber duck", profile)
    assert not state.room.monster.hostile and "rubber_duck" not in state.player.inventory and state.player.hp == hp


def test_looking_around_spends_no_search_and_no_turn(content, profile):
    """'look around' rolled the room's one search (F83)."""
    state, result = play(quiet(content), "look around", profile)
    assert not state.room.room_searched and state.turn == 0 and not any(e.dice for e in result.events)
    assert "search_room" in {a.id for a in available_actions(state, content)}


def test_a_thing_you_carry_named_in_a_fight_for_nothing_the_grid_knows_costs_no_blow(content, profile):
    """Words about a thing in your pack that come to nothing ("sniff the holy water") were flavor, and the monster
    swung: now they're told what it could do (no turn), when it could do something."""
    before = ghoul(content)
    hp = before.player.hp
    state, result = play(before, "sniff the holy water", profile)
    assert state.turn == 0 and state.player.hp == hp and "holy_water" in state.player.inventory
    assert "Throw the Vial of Holy Water at the Ghoul" in result.narration


def test_tossing_a_small_key_or_the_armor_on_your_back_takes_nothing_from_your_pack(content):
    """Found fuzzing the typed path: 'throw the small key' or 'toss the chain shirt' (worn) took them out of a pack
    they weren't in, and crashed."""
    state = quiet(content)
    state.player.keys, state.player.armor = 1, "chain_shirt"
    for typed in ("throw the small key", "toss the chain shirt", "throw my sword"):
        trial = state.model_copy(deep=True)
        intent, _ = offline_interpret(typed, given(trial, content), RoomView(trial, content))
        if intent.kind == "action":
            perform(trial, content, intent.action_id)
        assert (trial.player.keys, trial.player.armor, trial.player.weapon) == (1, "chain_shirt", "rusty_sword")


def test_gold_waved_at_a_goblin_catches_its_eye(content, profile):
    """A goblin can't resist shiny things, gold too: waving it crashed (there's no gold item to name)."""
    state = fight(content, "goblin", [])
    state.player.gold = 20
    state, result = play(state, "wave the gold at the goblin", profile)
    assert result.events[0].kind == "distract" and "your gold" in result.events[0].text and state.player.gold == 20


# --- a model's reply, in the v2 schema --------------------------------------------------------------------------------

def reply(**fields):
    return {**FLAVOR, "kind": "creative", "stat": "agility", "difficulty": "medium",
            "success_effects": ["damage_small"], **fields}


def test_the_schema_asks_for_a_use(content):
    schema = intent_schema()
    assert {"verb", "subject", "target", "amount"} <= set(schema["required"])
    assert schema["properties"]["amount"]["type"] == "integer"


def test_a_model_s_use_by_scene_ids_is_the_grid_s(content, profile):
    """'lob that stinky wheel at the dead guy': the model's verb, subject and target (SCENE ids) are the grid's
    throw of the cheese, never the holy water."""
    llm = FakeLLM(reply=reply(verb="throw", subject="item:cheese_wheel", target="monster:ghoul", uses=["cheese"]))
    state, result = play(ghoul(content), "lob that stinky wheel at the dead guy", profile, llm)
    assert "cheese_wheel" not in state.player.inventory and "holy_water" in state.player.inventory
    assert "Wheel of Cheese" in result.events[0].text


def test_a_model_s_use_by_name_and_synonym_is_put_in_the_grid_s_terms(content, fake_llm):
    state = swoogy(content)
    llm = fake_llm(reply=reply(verb="feed", subject="Pickle", target="Swoogy"))
    intent, _ = asyncio.run(interpret(llm, state, content, "make the gooey one eat a pickle", given(state, content)))
    assert (intent.verb, intent.subject, intent.target) == ("give", "pickle", "monster:swoogy_the_gooey")
    llm = fake_llm(reply=reply(verb="drink", subject="item:healing_potion"))
    intent, _ = asyncio.run(interpret(llm, state, content, "quaff it down", given(state, content)))
    assert (intent.verb, intent.subject, intent.target) == ("use", "healing_potion", "self")
    llm = fake_llm(reply=reply(verb="teleport", subject="item:pickle", target="room"))
    intent, _ = asyncio.run(interpret(llm, state, content, "teleport the pickle", given(state, content)))
    assert (intent.kind, intent.verb, intent.subject) == ("creative", "", "")  # (no verb the grid knows: a stunt)


def test_a_model_s_action_that_is_a_whole_use_is_kept(content, profile):
    """An action id that's a use of the grid, not a numbered choice: Lenny hands the pickle back, at no cost."""
    state = lenny(content)
    state.player.inventory.append("pickle")
    llm = FakeLLM(reply={**FLAVOR, "kind": "action", "action_id": "give:pickle@monster:lucky_lenny"})
    state, result = play(state, "offer lenny my pickle", profile, llm)
    assert "pickle" in state.player.inventory and result.events[0].text.startswith("Lucky Lenny sniffs the Pickle")


def test_a_model_s_action_said_as_a_use_with_no_id_is_that_use(content, profile):
    """kind "action", no action_id, but give, gold, Swoogy, 30: he's paid 30 (more than his price, as said)."""
    before = swoogy(content)
    gold = before.player.gold
    llm = FakeLLM(reply={**FLAVOR, "kind": "action", "verb": "give", "subject": "gold",
                         "target": "monster:swoogy_the_gooey", "amount": 30})
    state, _ = play(before, "here, thirty coins, now calm down", profile, llm)
    assert state.player.gold == gold - 30 and not state.room.monster.hostile


def test_a_gear_change_the_model_calls_a_stunt_is_still_made(content, profile):
    """A model's creative 'swap to the war pick', with a roll, left the weapon as it was while the story told the swap
    (F26): said as a use (equip), it's the move itself, and the narrator's told gear changes only as the facts say."""
    from ptg.llm.prompts import NARRATOR_SYSTEM

    state = quiet(content)
    state.player.inventory.append("war_pick")
    llm = FakeLLM(reply=reply(verb="equip", subject="item:war_pick", stat="might", success_effects=["stun"]))
    state, result = play(state, "trade my rusty blade for that lovely war pick", profile, llm)
    assert state.player.weapon == "war_pick" and "rusty_sword" in state.player.inventory
    assert result.events[0].kind == "equip" and "never narrate a weapon drawn, swapped or put away" in NARRATOR_SYSTEM


def test_a_model_s_use_of_what_you_havent_got_is_told_so_at_no_cost(content, profile):
    before = ghoul(content)
    hp, pack = before.player.hp, list(before.player.inventory)
    llm = FakeLLM(reply=reply(verb="throw", subject="oil_flask", target="monster:ghoul"))
    state, result = play(before, "throw my lamp oil at it", profile, llm)
    assert result.events[0].text == "You have no Flask of Lamp Oil." and state.turn == 0
    assert state.player.inventory == pack and state.player.hp == hp


# --- what the model is shown (F80, F107) ----------------------------------------------------------------------------

def test_the_model_sees_the_scene_by_id_with_bombs_and_keys(content):
    state = ghoul(content)
    state.player.keys = 1
    _, user = interpreter_messages(state, content, "throw it", given(state, content), RoomView(state, content))
    assert "SCENE" in user and "PROPS" not in user
    assert "item:cheese_wheel  Wheel of Cheese (food, throwable, heavy, smelly)" in user
    assert "bombs  bomb (×2)" in user and "keys  small key (×1)" in user and "monster:ghoul  Ghoul (hostile" in user
    assert "Bombs: 2. Small keys: 1." in player_status(state, content)


async def test_what_you_carry_says_your_bombs_and_keys(content, profile):
    state = quiet(content)
    state.player.bombs, state.player.keys = 2, 1
    game = Game(state, Config(backend="offline"), None, profile=profile)
    result = await game.act("what am I carrying?", lambda _: None)
    assert "2 bombs" in result.narration and "1 small key" in result.narration


def test_a_calm_creature_is_never_said_to_be_about_to_attack(content):
    """Calm Lenny read 'not hostile, intelligent, about to attack' (F107)."""
    state = lenny(content)
    line = next(line for line in situation(state, content).splitlines() if line.startswith("Monster:"))
    assert line == "Monster: Lucky Lenny, 8/8 HP, calm, intelligent, watching you"
    state = ghoul(content)
    assert "hostile, animal-minded, about to attack" in situation(state, content)


# --- the suggested trick (F45, F64) -----------------------------------------------------------------------------------

async def test_the_suggested_trick_is_a_grid_use_and_goes_with_what_it_uses(content, profile):
    """After the holy water was thrown, the ✦ still said to throw it, and picking it gave the ghoul a free swing
    (F45). Now it's keyed on what you carry, and picking it does just the use it was thought of as."""
    state = ghoul(content)
    game = Game(state, Config(backend="offline"), None, profile=profile)
    text = await game.refresh_suggestion()
    assert text == "Throw the Vial of Holy Water at the Ghoul" and game.state.suggestion_id == "throw:holy_water"
    await game.act(str(len(game.choices())), lambda _: None)  # (the ✦, last)
    assert "holy_water" not in game.state.player.inventory
    assert game.state.suggestion == "" and await game.refresh_suggestion() != text


async def test_the_suggested_trick_never_spends_a_heal_and_is_none_when_nothing_would_do(content, profile):
    """It suggested throwing healing potions at monsters (F64): what heals you, a getaway, bombs and keys are never
    an idea, and nothing's suggested if nothing would do."""
    state = fight(content, "goblin", ["healing_potion", "superior_healing_potion", "pickle", "stale_bread",
                                       "smoke_bomb"], hurt=True)
    assert extras.ideas(state, content) == []
    game = Game(state, Config(backend="offline"), None, profile=profile)
    assert await game.refresh_suggestion() == "" and game.choices()[-1].id != "suggest"


async def test_a_model_words_the_trick_but_picking_it_does_the_idea(content, profile):
    state = ghoul(content)
    llm = FakeLLM(reply={"idea": 1, "suggestion": "Splash the holy water in the ghoul's face"})
    game = Game(state, Config(), llm, profile=profile)
    assert await game.refresh_suggestion() == "Splash the holy water in the ghoul's face"
    assert game.state.suggestion_id == "throw:holy_water"
    llm.reply = {"idea": 1, "suggestion": "Throw the healing potion at the ghoul"}  # (not what the idea uses)
    game = Game(ghoul(content), Config(), llm, profile=profile)
    assert await game.refresh_suggestion() == "Throw the Vial of Holy Water at the Ghoul"


def test_out_of_a_fight_the_trick_is_only_where_something_is(content):
    """'Pry at the root-wrapped statue' in a room with nothing hidden rolled, hurt, and offered a reroll (F64)."""
    state = quiet(content)
    state.room.features = [Feature(name="a heap of old rubbish", loot=["pickle"]), Feature(name="a stone bench")]
    assert [(a.id, a.label) for a in extras.ideas(state, content)] == [("search:0", "Rummage through the heap of "
                                                                                    "old rubbish")]
    state.room.features[0].searched = True
    assert extras.ideas(state, content) == []
    state.room.features[1].hidden = True
    assert [a.id for a in extras.ideas(state, content)] == ["search_room"]


def test_a_stunt_that_could_turn_up_nothing_offers_no_reroll(content):
    """A failed pry with nothing hidden could be rerolled with Fate, for 'nothing hidden here' (F64)."""
    state = quiet(content)
    for feature in state.room.features:
        feature.hidden = False
    state.player.wits = -30
    pry = Intent(kind="creative", stat="wits", difficulty="medium", success_effects=["reveal_secret"],
                 summary="pry at the walls")
    _, events, _ = perform_creative(state, content, pry, stream(1, "test"))
    assert not events[0].data["rerollable"]
    state.room.features[0].hidden = True
    _, events, _ = perform_creative(state, content, pry, stream(1, "test"))
    assert events[0].data["rerollable"]


async def test_words_that_come_to_nothing_are_told_as_tried_not_done(content, profile):
    """Offline, words that came to nothing were told as done: "You give the tooth to lenny. The dungeon is
    unimpressed." (F43)."""
    game = Game(quiet(content), Config(backend="offline"), None, profile=profile)
    result = await game.act("I do a little dance", lambda _: None)
    assert result.narration == "You try to do a little dance, but nothing comes of it. The dungeon is unimpressed."


def test_a_plain_getaway_is_fleeing_without_asking_the_model(content):
    """'get out of here, run!' was a dodge to a small on-device model: said plainly in a fight, naming nothing in the
    room, a getaway is fled at once. Naming something, it's the model's to read."""
    from ptg.llm.interpreter import offline_interpret
    from ptg.scene import RoomView

    state = generate(1)
    put_monster(state, content, "goblin")
    actions, view = available_actions(state, content), RoomView(state, content)
    for said in ("get out of here, run!", "get away from it", "let's run for it now", "flee"):
        intent, sure = offline_interpret(said, actions, view)
        assert (intent.action_id, sure) == ("flee", True), said
    assert offline_interpret("run past the goblin to the door", actions, view)[1] is False
