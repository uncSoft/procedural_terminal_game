"""What a played run turned up (run 42, seed 54540): loot in piles, a narrator fed numbers and smells to repeat, a
suggester throwing marbles at everything, an epitaph that buried a winner, and a ghost that didn't know its own player.
"""

import random
from collections import Counter

from conftest import put_monster
from ptg.combat import defeat
from ptg.intent import Intent
from ptg.events import Event
from ptg.llm import extras
from ptg.llm.guard import Rules, check
from ptg.llm.prompts import narrator_messages, plain, situation, suggestion_situation
from ptg.models import MonsterState
from ptg.inventory import gain
from ptg.rules import perform, perform_creative, room_facts
from ptg.world import build_floor, generate


def every_floor(seeds, content):
    for seed in seeds:
        state = generate(seed)
        for floor in (1, 2, 3):
            if floor > 1:
                state.floor = floor
                build_floor(state, content)
            yield state


def test_loot_is_spread_out_not_piled_up(content):
    """One thing to a hiding place, and rarely more than two in a room (seed 54540 hid three in one cage)."""
    per_room = Counter()
    for state in every_floor(range(60), content):
        for room in state.rooms:
            assert all(len(f.loot) <= 1 for f in room.features), (state.seed, state.floor, room.name)
            per_room[len(room.items) + sum(len(f.loot) for f in room.features)] += 1
    assert sum(n for things, n in per_room.items() if things >= 4) <= sum(per_room.values()) // 100


def test_a_warden_talked_down_still_leaves_its_prize(content):
    state = generate(5)
    stairs = next(r for r in state.rooms if r.fixture == "stairs")
    state.room_id = stairs.id
    events = defeat(state, content, random.Random(1), how="pacified")
    left = [e for e in events if e.kind == "drop"]
    assert len(left) == 1 and left[0].data["item"] in state.room.items and "at your feet" in left[0].text


def test_an_attempt_is_only_attempted_once(content):
    state = generate(3)
    put_monster(state, content, hp=50)
    intent = Intent(kind="creative", stat="wits", difficulty="easy", success_effects=["stun"],
                    summary="attempt to talk down the goblin by claiming friendship")
    _, events = perform_creative(state, content, intent)
    assert events[0].text.startswith("You attempt to talk down the goblin")


def test_gear_changing_hands_is_not_a_rooms_memory(content):
    """'Earlier here: you left your old Rusty Sword here.' stayed after you'd picked it back up (F69)."""
    state = generate(3)
    state.room.monster = None
    gain(state, content, "war_pick")
    perform(state, content, "equip:war_pick")
    perform(state, content, "drop:rusty_sword")
    perform(state, content, "take:rusty_sword")
    assert not state.room.history and "rusty_sword" in state.player.inventory


def test_the_narrator_gets_health_in_words_and_the_setting_once(content):
    assert plain("The Goblin hits you for 3 damage (32/35 HP left).") == "The Goblin hits you for 3 damage (still strong)."
    assert plain("You hit the Troll for 9 damage (2/30 HP left).") == "You hit the Troll for 9 damage (barely standing)."
    assert plain("The Goblin is defeated. +10 XP, +3 souls.") == "The Goblin is defeated."
    assert plain("You gain a Fate token (2/3).") == "You gain a Fate token."
    state = generate(3)
    blurb = content.themes[state.theme].blurb
    _, first = narrator_messages(state, content, "", [], "fun", opening=True)
    _, later = narrator_messages(state, content, "look around", [Event("search", "You find nothing.")], "fun")
    assert blurb in first and blurb not in later  # said every turn, it was repeated every turn


def test_suggestions_must_name_something_here_and_not_throw_things_about(content):
    state = generate(3)
    state.room.monster = None
    state.player.inventory.append("bag_of_marbles")
    feature = state.room.visible_features()[0][1]
    noun = feature.name.split()[-1]
    assert extras.sensible(f"Pry at the {noun}", state, content)
    assert not extras.sensible(f"Scatter marbles under the {noun}", state, content)  # outside a fight
    assert not extras.sensible("Pry up the loose stones by the altar", state, content) or "altar" in feature.name
    assert "Bag of Marbles" not in suggestion_situation(state, content)
    put_monster(state, content, key="goblin", hp=20)
    assert extras.sensible("Throw the Bag of Marbles at the goblin", state, content)  # in a fight, fine


async def test_a_winner_gets_a_statue_line_not_a_tombstone(content):
    state = generate(3)
    state.status, state.cause = "won", "conquered The Overgrown Ruins"
    seen = []

    class Model:
        name = "fake"

        async def stream_text(self, system, user, max_tokens=200):
            seen.append((system, user))
            yield "Statue line."

    assert await extras.epitaph(Model(), state) == "Statue line."
    system, user = seen[0]
    assert "Hall of Legends" in system and "never \"he\" or \"she\"" in system and "they won and lived" in user


def test_your_ghost_knows_its_player(content):
    """Told "it's me, I died here", the narrator called it a lie: now it, and the interpreter, know it's true."""
    state = generate(3)
    state.ghost = {"name": "Adventurer", "cause": "slain by the Cursed Orc on floor 1", "epitaph": "HP pools are lies."}
    state.room.monster = MonsterState(key="ghost", name="Ghost of Adventurer", hp=10, max_hp=10, ghost_of="Adventurer")
    for told in (room_facts(state, content), situation(state, content)):
        assert "your own ghost" in told and "is true" in told
    rest = next(e for e in defeat(state, content, random.Random(1), how="pacified") if e.kind == "ghost_rest")
    assert "your own earlier life" in rest.text


def test_the_guard_remembers_who_died_here(content):
    state = generate(3)
    put_monster(state, content, key="rat_king", hp=1)
    defeat(state, content, random.Random(1))
    rules = Rules.for_turn(state, content, [Event("search_room", "You search every corner but find nothing hidden.")])
    sentence = "The Lookout holds no more secrets than the Rat King's discarded bones."
    assert check(sentence, rules).text == sentence


def test_someones_things_take_no_article():
    from ptg.text import a, the

    assert the("Brannoc's remains") == "Brannoc's remains" == a("Brannoc's remains")
    assert the("mourner's lantern") == "the mourner's lantern" and a("Healing Potion") == "a Healing Potion"
    assert the("Saint's Alcove") == "the Saint's Alcove"  # a place's title
