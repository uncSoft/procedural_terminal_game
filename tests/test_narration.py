"""W9: the narrator tells what happened and stops listing what the screen already shows."""

import pytest

from conftest import put_monster
from ptg import combat
from ptg.config import Config
from ptg.events import Event
from ptg.game import Game, narratable
from ptg.llm.guard import Rules, check
from ptg.llm.prompts import narrator_messages, plain
from ptg.rules import available_actions, perform, room_facts
from ptg.scene import RoomView
from ptg.world import generate

LISTINGS = ("In the room", "On the floor", "Exits:", "(north-east)", "(south-west)", "unexplored")


def into_the_skeleton(content):
    """Seed 3: north of the start lies the Bone Gallery, with a hostile Skeleton, and a Vial of Holy Water lying there
    (put there: where a floor's loot lands is world.py's, not this test's)."""
    state = generate(3)
    state.rooms[state.room.exits["north"].to].items = ["holy_water"]
    events = perform(state, content, "go:north")
    assert state.room.monster and state.room.monster.hostile and state.room.items
    return state, events


def test_arrival_tells_the_fight_not_the_room(content):
    state, events = into_the_skeleton(content)
    told = events[0].text
    assert told.startswith("You go north into the Bone Gallery for the first time.")
    assert "The Skeleton is here and hostile. A fight begins." in told
    assert not [listed for listed in LISTINGS if listed in told]
    assert "Vial of Holy Water" not in told and "chest" not in told  # (the stage and Here show them)
    assert "In the room" in room_facts(state, content)  # (the whole room is there for a question about it)


def test_arrival_tells_of_someone_calm_who_is_here(content):
    """Run 59: back in Swoogy's room after calming him, the narrator was told nothing of him and said he'd gone; two
    turns later the player attacked him."""
    from ptg.rules import arrival_facts

    state, _ = into_the_skeleton(content)
    state.room.monster.hostile = False
    told = arrival_facts(state, content)
    assert "The Skeleton is here, not hostile" in told and "A fight begins" not in told
    state.room.monster.hp = 0
    assert "Skeleton" not in arrival_facts(state, content)  # (gone is gone)


async def test_the_opening_and_a_descent_are_short(content, profile):
    game = Game(generate(3), Config(backend="offline"), None, profile=profile)
    opening = await game.opening(lambda _: None)
    assert "floor 1 of 4" not in opening.narration and not [x for x in LISTINGS if x in opening.narration]
    state = game.state
    state.room.monster, state.room.fixture, state.room.fixture_used = None, "stairs", False
    events = perform(state, content, "descend")
    theme = content.themes[state.theme]
    assert events[0].kind == "descend" and f"to floor 2, {theme.name}," in events[0].text
    assert theme.blurb not in events[0].text and "souls" not in events[0].text  # (the floor's header and the HUD)
    assert not [x for x in LISTINGS if x in events[0].text]


def test_a_shop_gives_the_narrator_its_keeper_not_its_prices(content):
    from test_shops import in_the_shop

    state, shop = in_the_shop(content)
    facts = room_facts(state, content)
    assert "Granny Gristle keeps a shop here" in facts and "not a monster" not in facts
    for ware in shop.wares:
        assert content.item(ware.item).name not in facts


async def test_offline_narration_is_not_a_fact_dump(content, profile):
    game = Game(generate(3), Config(backend="offline"), None, profile=profile)
    await game.opening(lambda _: None)
    arrival = await game.act("go north", lambda _: None)
    assert "The Skeleton is here and hostile." in arrival.narration
    assert not [x for x in LISTINGS if x in arrival.narration]
    game.state.room.monster.hp = 1
    kill = await game.act("attack", lambda _: None)
    for numbers in ("XP", "souls", "HP", "damage", "(1 now)", "/10"):
        assert numbers not in kill.narration
    assert "defeated" in kill.narration
    answer = await game.act("what am i carrying?", lambda _: None)
    assert "Player " not in answer.narration and "Fate tokens" not in answer.narration
    assert "Rusty Sword" in answer.narration and "Small keys" not in answer.narration


def test_plain_leaves_out_the_numbers_the_screen_shows():
    said = {
        "You hit the Skeleton with your Rusty Sword for 5 damage (5/10 HP left).":
            "You hit the Skeleton with your Rusty Sword (hurt).",
        "The Orc takes 4 damage (0/12 HP left).": "The Orc takes a hit (down).",
        "The Skeleton is defeated. +12 XP, +3 souls.": "The Skeleton is defeated.",
        "You take the Small Key (1 now).": "You take the Small Key.",
        "You put on the Leather Jerkin (+2 defense).": "You put on the Leather Jerkin.",
        "You take the War Pick in hand (1d6 → 1d10).": "You take the War Pick in hand.",
        "You take the Axe (1d8+1 & goblin-bane) and put it in your pack.": "You take the Axe and put it in your pack.",
        "You go down the stairs. +10 souls.": "You go down the stairs.",
        "The water is bitter and burns going down (-3 HP).": "The water is bitter and burns going down.",
        "You hurt yourself for 3 damage (27/30 HP).": "You hurt yourself.",
    }
    for fact, words in said.items():
        assert plain(fact) == words, fact
    assert plain("You hit the Orc for 5 damage (5/12 HP left).", health=False) == "You hit the Orc."


def test_the_narrator_is_not_handed_numbers_in_what_happened_before(content):
    state = generate(3)
    state.journal += ["You hit the Orc for 10 damage (20/30 HP left). +50 XP, +9 souls.", "You reached level 2."]
    _, user = narrator_messages(state, content, "look", [Event("search", "You find nothing.")], "grim")
    recently = user.split("RECENTLY")[1].split("THIS TURN")[0]
    assert "damage" not in recently and "20/30" not in recently and "XP" not in recently and "souls" not in recently


def test_the_screen_says_fate_levels_and_traits_not_the_narrator(content):
    for kind in ("fate_spent", "level", "trait"):
        assert not narratable(Event(kind, "Whatever."))
    assert narratable(Event("hit", "You hit the Orc.")) and narratable(Event("defeat", "The Orc is defeated."))


def test_the_narrator_is_told_not_to_list_the_room(content):
    state, events = into_the_skeleton(content)
    system, user = narrator_messages(state, content, "go north", events, "grim")
    assert "Don't list them" in system and "mention every" not in system
    assert "Notes:" in user and "FACTS:" in user and not [x for x in LISTINGS if x in user]


def drops_in(state, content, monkeypatch, key):
    monkeypatch.setattr(combat, "_drops", lambda *args: [key])
    put_monster(state, content, hp=1)
    return [e for e in combat.defeat(state, content, __import__("random").Random(1), how="slain") if e.kind == "drop"]


def test_a_drop_says_it_lies_there_unless_it_is_yours_at_once(content, monkeypatch):
    potion = drops_in(generate(2), content, monkeypatch, "healing_potion")[0]
    assert "lies on the floor (not picked up)" in potion.text
    key = drops_in(generate(2), content, monkeypatch, "small_key")[0]
    assert key.text.endswith("dropped a Small Key.")  # (collect takes it next)


def guard_for(content, lying=(), packed=(), events=()):
    state = generate(3)
    state.room.monster = None
    state.room.items = list(lying)
    state.player.inventory = list(packed)
    return state, Rules.for_turn(state, content, list(events))


def test_the_guard_cuts_taking_what_still_lies_on_the_floor(content):
    _, rules = guard_for(content, lying=["healing_potion"])
    for taken in ("You pocket the Healing Potion.", "You scoop up the potion and move on.",
                  "You grab the dropped healing potion."):
        assert check(taken, rules).dropped[0][1] == "takes healing potion, which still lies there"
    assert check("The Healing Potion glints on the floor.", rules).text  # (lying there, as the facts say)
    _, rules = guard_for(content, packed=["healing_potion"])  # (in the pack, so it's yours to take out)
    assert check("You take out the Healing Potion.", rules).text


def test_the_guard_cuts_putting_on_what_is_still_in_the_pack(content):
    _, rules = guard_for(content, packed=["leather_jerkin"])
    assert check("You quickly strap on the Leather Jerkin.", rules).dropped[0][1] == \
        "puts on leather jerkin, which is still in the pack"
    assert check("The Leather Jerkin sits heavy in your pack.", rules).text


def test_the_guard_keeps_the_sentence_that_ends_the_fight(content):
    state = generate(3)
    put_monster(state, content, key="goblin")
    events = [Event("defeat", "The Goblin is defeated.")]
    sentence = "The blast catches the rat king off guard, flinging him down for good."
    assert check(sentence, Rules.for_turn(state, content, [])).dropped[0][1] == "invents rat king"
    assert check(sentence, Rules.for_turn(state, content, events)).text == sentence
    still = "The rat king grins at you."  # (not about how it ended: still another monster's name)
    assert check(still, Rules.for_turn(state, content, events)).dropped[0][1] == "invents rat king"


def test_the_guard_lets_idioms_with_a_monsters_name_pass(content):
    _, rules = guard_for(content)
    for idiom in ("The last lantern gives up the ghost.", "It is quiet enough to wake any ghost.",
                  "The engine gave up the ghost at last."):
        assert check(idiom, rules).text == idiom
    assert check("A ghost drifts out of the wall.", rules).dropped[0][1] == "invents ghost"


async def test_a_rooms_description_is_its_blurb_not_the_arrival(content, profile):
    game = Game(generate(3), Config(backend="offline"), None, profile=profile)
    await game.opening(lambda _: None)
    await game.act("go north", lambda _: None)
    room = game.state.room
    assert room.description == content.archetypes[room.archetype].blurb and "hostile" not in room.description
    start = game.state.rooms[game.state.prev_room_id]
    assert start.description == content.archetypes[start.archetype].blurb


def test_no_blurb_puts_a_boss_where_the_facts_may_not():
    from ptg.content import load_content

    content = load_content()
    for archetype in content.archetypes.values():
        for boss in (m for m in content.monsters.values() if m.boss):
            assert boss.name.lower().removeprefix("the ") not in archetype.blurb.lower(), (archetype.key, boss.key)
    assert "at prayer" not in content.archetypes["abbots_sanctum"].blurb  # (someone, somewhere)


def test_a_draft_stays_a_cracked_wall(content):
    from ptg.rules import bombable_walls

    state = next(s for s in map(generate, range(1, 40)) if bombable_walls(s))
    walls = bombable_walls(state)
    state.room.draft = walls[0]
    view = RoomView(state, content)
    cracked = view.get(f"wall:{walls[0]}")
    assert cracked.name == f"cracked {walls[0]} wall" and cracked.state["draft"]
    for other in walls[1:]:
        assert view.get(f"wall:{other}").name == f"{other} wall"


class SlowLLM:
    """A model that takes its time: a sentence every `pause` seconds, and it counts what it was asked."""

    name = "slow"

    def __init__(self, sentences=("The room is cold.", "Water drips somewhere.", "You feel watched."), pause=0.2):
        self.sentences, self.pause, self.streams, self.json_calls = list(sentences), pause, 0, 0

    async def prepare(self):
        pass

    async def complete_json(self, system, user, schema, max_tokens=500):
        self.json_calls += 1
        return {}

    async def stream_text(self, system, user, max_tokens=600):
        import asyncio

        self.streams += 1
        for sentence in self.sentences:
            await asyncio.sleep(self.pause)
            for word in sentence.split(" "):
                yield word + " "

    async def aclose(self):
        pass


async def test_the_narrator_cut_short_keeps_its_whole_sentences(content):
    """A move made while the narrator talks cuts it short: what it's said whole stands, nothing half said."""
    import asyncio

    from ptg.llm.narrator import narrate

    state = generate(1)
    events = perform(state, content, next(a.id for a in available_actions(state, content) if a.id.startswith("go:")))
    stop, shown = asyncio.Event(), []
    llm = SlowLLM(("The room is cold and very quiet.", "Water drips somewhere far away.", "You feel watched."),
                  pause=0.3)

    async def cut():
        await asyncio.sleep(0.45)  # (the first sentence told, the second on its way)
        stop.set()

    asyncio.ensure_future(cut())
    text, error = await narrate(llm, state, content, "go", events, "", shown.append, stop=stop)
    assert error is None and text.startswith("The room is cold") and "Water" not in text


async def test_going_back_through_the_floor_waits_on_no_narrator(content):
    """With a model narrating, a move back into a room you've been in, with nothing waiting there, is told in the
    engine's line: no stream to wait for. A new room is the narrator's."""
    state = generate(5, content=content)
    for room in state.rooms:
        room.monster = None
    llm = SlowLLM(pause=0.0)
    game = Game(state, Config(backend="openai"), llm, content)
    way = next(a.id for a in available_actions(state, content) if a.id.startswith("go:"))
    back = {"go:north": "go:south", "go:south": "go:north", "go:east": "go:west", "go:west": "go:east"}[way]
    numbered = lambda action_id: str(next(i for i, a in enumerate(game.choices(), 1) if a.id == action_id))  # noqa: E731
    await game.act(numbered(way), lambda _: None)
    assert llm.streams == 1  # (somewhere new)
    result = await game.act(numbered(back), lambda _: None)
    assert llm.streams == 1 and "where you've been before" in result.narration
