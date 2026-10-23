"""Asking a creature that's stopped fighting what it knows (ptg/rules.py): the floor's secret room or its hidden stash
goes on your map, and one that talks can tell you what a monster down here can't stand."""

from conftest import put_monster
from ptg.events import Action
from ptg.llm.interpreter import offline_interpret
from ptg.rules import available_actions, perform, room_facts
from ptg.ui.widgets import map_text
from ptg.world import generate, render_map


def calm_here(content, key="goblin", seed=11):
    """A floor with nothing hostile on it but the warden, and a calm creature in the room you're in."""
    state = generate(seed)
    for room in state.rooms:
        if room.fixture != "stairs":
            room.monster = None
    monster = put_monster(state, content, key=key, hp=10)
    monster.hostile = False
    state.player.wits = 50  # it'll tell (anything but a natural 1)
    return state, monster


def secret_room(state):
    return next(r for r in state.rooms if r.secret)


def stash(state):
    return next((room, f) for room in state.rooms for f in room.features if f.hidden and (f.loot or f.gold))


def ask(state, content):
    events = perform(state, content, "ask")
    roll = next((e.dice for e in events if e.dice and e.dice.actor == "player"), None)
    return events, roll


def test_a_calm_creature_can_be_asked_once(content):
    state, monster = calm_here(content)
    ask_action = next(a for a in available_actions(state, content) if a.id == "ask")
    assert ask_action.label == "Ask the Goblin what it knows" and ask_action.hint == "wits"
    perform(state, content, "ask")
    assert monster.asked and "ask" not in {a.id for a in available_actions(state, content)}
    monster.hostile, monster.asked = True, False
    assert "ask" not in {a.id for a in available_actions(state, content)}  # not in the middle of a fight


def test_one_that_cant_talk_is_watched_instead(content):
    state, _ = calm_here(content, key="giant_rat")
    assert next(a for a in available_actions(state, content) if a.id == "ask").label == "Watch the Giant Rat for a while"


def test_it_puts_the_secret_room_on_your_map(content):
    state, _ = calm_here(content)
    room, feature = stash(state)
    feature.told = "someone else"  # so it's the room it tells you about
    secret = secret_room(state)
    assert "{" not in "".join(render_map(state))
    events, roll = ask(state, content)
    tip = next(e for e in events if e.kind == "tip")
    assert roll.success and tip.dice is roll and secret.told == "Goblin"
    assert "hidden room" in tip.text and "on your map" in tip.text
    assert "{✧}" in "".join(render_map(state)) and "secret room" in map_text(state).plain

    beside = next(r for r in state.rooms if not r.secret and abs(r.x - secret.x) + abs(r.y - secret.y) == 1)
    state.room_id, beside.monster = beside.id, None
    bomb = next(a for a in available_actions(state, content) if a.id.startswith("bomb:"))
    assert bomb.hint.startswith("a tip!")
    assert "the Goblin told you about" in room_facts(state, content)


def test_it_tells_where_something_is_hidden_and_its_there_when_you_go(content):
    state, _ = calm_here(content)
    secret_room(state).told = "someone else"  # so it's the stash it tells you about
    room, feature = stash(state)
    item = feature.loot[0]
    events, roll = ask(state, content)
    tip = next(e for e in events if e.kind == "tip")
    assert roll.success and content.item(item).name.lower() in tip.text.lower()
    assert not feature.hidden and feature.told == "Goblin" and "$" in "".join(render_map(state))

    state.room_id, room.monster = room.id, None
    index = room.features.index(feature)
    search = next(a for a in available_actions(state, content) if a.id == f"search:{index}")
    assert search.hint == "a tip!"
    found = perform(state, content, f"search:{index}")
    assert any(e.kind == "find" and e.data.get("item") == item for e in found)
    assert "$" not in "".join(render_map(state))


def test_with_nothing_hidden_left_a_talker_knows_a_weak_spot(content):
    state, _ = calm_here(content)
    secret_room(state).told = "someone else"
    stash(state)[1].told = "someone else"
    warden = next(r for r in state.rooms if r.fixture == "stairs").monster
    events, _ = ask(state, content)
    learned = next(e for e in events if e.kind == "weakness")
    assert learned.data["monster"] == warden.key and learned.data["tag"] in state.known_weak[warden.key]
    assert "by the stairs" in next(e for e in events if e.kind == "tip").text


def test_with_nothing_to_tell_theres_nothing_to_roll(content):
    state, _ = calm_here(content, key="giant_rat")  # a rat can't tell you about monsters
    secret_room(state).told = "someone else"
    stash(state)[1].told = "someone else"
    events, roll = ask(state, content)
    assert roll is None and events[0].kind == "ask" and "anywhere new" in events[0].text


def test_a_failed_ask_tells_nothing_but_fate_can_try_again(content):
    state, _ = calm_here(content)
    state.player.wits = -50
    events, roll = ask(state, content)
    assert not roll.success and events[0].data["rerollable"]
    assert not secret_room(state).told and not stash(state)[1].told


def test_asking_in_your_own_words():
    actions = [Action("ask", "Ask the Goblin Stewmancer what it knows", "wits"), Action("go:north", "Go north")]
    for words in ("ask him where the secret room is", "ask about secrets", "ask the stewmancer", "ask what it knows"):
        assert offline_interpret(words, actions)[0].action_id == "ask", words
    assert offline_interpret("ask him his favorite dish to cook", actions)[0].kind == "flavor"  # small talk
    beast = [Action("ask", "Watch the Giant Rat for a while", "wits")]
    assert offline_interpret("watch the rat", beast)[0].action_id == "ask"
    assert offline_interpret("follow the corridor north", beast)[0].action_id != "ask"
