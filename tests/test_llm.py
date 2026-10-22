import pytest

from conftest import put_monster
from ptg.config import Config, load_game, save_game
from ptg.game import Game
from ptg.llm import extras
from ptg.llm.base import LLMError, ThinkFilter, extract_json
from ptg.llm.interpreter import interpret, offline_interpret
from ptg.llm.openai_compat import normalize_url
from ptg.llm.prompts import narrator_messages
from ptg.models import OPPOSITE
from ptg.rules import available_actions, exit_notes, perform
from ptg.text import the
from ptg.world import generate

QUESTION = {"kind": "question", "action_id": "", "stat": "none", "difficulty": "trivial",
            "success_effects": [], "failure_effects": [], "uses": [], "consumes": [], "summary": "ask"}


def test_think_filter_handles_split_tags():
    f = ThinkFilter()
    out = "".join(f.feed(c) for c in ["Hel", "lo <thi", "nk>secret plans</th", "ink> world"]) + f.flush()
    assert out == "Hello  world"


@pytest.mark.parametrize("raw", [
    '{"a": 1}',
    '```json\n{"a": 1}\n```',
    '<think>hmm {"b": 2}</think>{"a": 1}',
    'Sure! Here you go: {"a": 1} hope that helps',
])
def test_extract_json(raw):
    assert extract_json(raw) == {"a": 1}


def test_extract_json_raises_on_garbage():
    with pytest.raises(LLMError):
        extract_json("no json here")


def test_normalize_url():
    assert normalize_url("localhost:1234") == "http://localhost:1234/v1"
    assert normalize_url("http://localhost:11434/v1/") == "http://localhost:11434/v1"


def test_offline_interpreter_matches_commands(content):
    state = generate(1)
    actions = available_actions(state, content)
    direction = next(iter(state.room.exits))
    assert offline_interpret(direction[0], actions)[0].action_id == f"go:{direction}"
    assert offline_interpret(f"go {direction}", actions)[0].action_id == f"go:{direction}"
    assert offline_interpret("search for secrets", actions)[0].action_id == "search_room"
    feature = state.room.features[0].name.split()[-1]
    assert offline_interpret(f"search the {feature}", actions)[0].action_id == "search:0"
    assert offline_interpret("what am I carrying?", actions)[0].kind == "question"
    intent, confident = offline_interpret("do a little dance", actions)
    assert intent.kind == "flavor" and not confident

    put_monster(state, content)
    state.player.hp = 5
    actions = available_actions(state, content)
    assert offline_interpret("attack", actions) == (offline_interpret("hit it", actions)[0], True)
    assert offline_interpret("duck!", actions)[0].action_id == "dodge"
    assert offline_interpret("drink the potion", actions)[0].action_id == "use:healing_potion"
    assert offline_interpret("run away!", actions)[0].action_id == "flee"


async def test_confident_commands_skip_the_model(content, fake_llm):
    state = generate(1)
    put_monster(state, content)
    llm = fake_llm(reply=QUESTION)
    intent, _ = await interpret(llm, state, content, "attack", available_actions(state, content))
    assert intent.action_id == "attack" and llm.json_calls == 0


async def test_model_creative_intent_passes_through(content, fake_llm):
    state = generate(1)
    put_monster(state, content)
    reply = {**QUESTION, "kind": "creative", "stat": "agility", "difficulty": "medium",
             "success_effects": ["stun"], "failure_effects": ["hurt_self_small"], "uses": ["sand"],
             "summary": "throw sand"}
    intent, error = await interpret(fake_llm(reply=reply), state, content, "I throw sand in its eyes",
                                    available_actions(state, content))
    assert intent.kind == "creative" and intent.success_effects == ["stun"] and error is None


async def test_model_hallucinated_action_falls_back(content, fake_llm):
    state = generate(1)
    reply = {**QUESTION, "kind": "action", "action_id": "teleport", "summary": "teleport home"}
    intent, _ = await interpret(fake_llm(reply=reply), state, content, "beam me up", available_actions(state, content))
    assert intent.kind == "flavor"


async def test_model_failure_falls_back_to_keywords(content, fake_llm):
    state = generate(1)
    intent, error = await interpret(fake_llm(fail=True), state, content, "please search for secrets now",
                                    available_actions(state, content))
    assert intent.action_id == "search_room" or intent.kind == "flavor"
    assert error and "model is down" in error


async def test_two_phase_turn_and_narration(content, fake_llm, profile):
    game = Game(generate(1), Config(), fake_llm(reply=QUESTION, text="You are fine, mostly."), profile=profile)
    chunks = []
    await game.opening(chunks.append)
    assert game.state.room.description == "You are fine, mostly."
    pending = await game.begin("how am I doing?")
    assert pending.intent.kind == "question" and pending.primary is None
    result = await game.finish(chunks.append)
    assert result.narration == "You are fine, mostly."
    assert [e.kind for e in game.state.log] == ["floor", "narration", "player", "narration"]


async def test_fate_reroll_rewinds_and_spends_a_token(content, profile):
    state = generate(1)
    state.player.wits = -30  # guaranteed failure unless a natural 20
    state.player.fate = 2
    hidden = [f for f in state.room.features if f.hidden]
    if not hidden:
        state.room.features[0].hidden = True
    game = Game(state, Config(backend="offline"), None, profile=profile)
    pending = await game.begin("search the room for secrets")
    assert pending.primary is not None and game.can_reroll()
    first = pending.primary.dice.dice
    turn = game.state.turn
    pending = game.reroll()
    assert game.state.player.fate == 1 and game.state.turn == turn
    assert pending.events[0].kind == "fate_spent"
    second = pending.primary.dice.dice
    assert (first, second) != (None, None)
    await game.finish(lambda _: None)
    assert game.state.player.fate == 1 and game.state.reroll == 0


async def test_narrator_failure_falls_back_to_facts(content, fake_llm, profile):
    game = Game(generate(1), Config(), fake_llm(fail=True), profile=profile)
    result = await game.act("1", lambda _: None)
    assert result.narration and any("narrator" in e for e in result.errors)


async def test_autosave_round_trip(content, profile):
    game = Game(generate(9), Config(backend="offline"), None, profile=profile)
    await game.opening(lambda _: None)
    await game.act("1", lambda _: None)
    loaded = load_game()
    assert loaded is not None and loaded.model_dump() == game.state.model_dump()
    game.state.status = "dead"
    save_game(game.state)
    assert load_game() is None  # finished games aren't offered to continue


async def test_suggestion_appears_as_a_choice(content, profile):
    state = generate(1)
    put_monster(state, content, key="troll")
    game = Game(state, Config(backend="offline"), None, profile=profile)
    text = await game.refresh_suggestion()
    assert text and game.choices()[-1].id == "suggest"
    assert "troll" in text.lower()


async def test_offline_extras_have_fallbacks(content):
    state = generate(1)
    state.status, state.cause = "dead", "slain by Giant Rat on floor 1"
    assert "Here lies" in await extras.epitaph(None, state)
    assert await extras.void_line(None, None, "Chubrock")
    assert await extras.lore(None, content, "goblin") == ""


def test_the_narrator_knows_where_the_player_was_and_is(content):
    """Walking into a new room must not read as going back to one you know (the model used to mix them up)."""
    state = generate(5)
    start = state.room
    direction = next(iter(start.exits))
    events = perform(state, content, f"go:{direction}")
    _, user = narrator_messages(state, content, "go", events, "grim")
    new = the(state.room.name)
    assert f"THIS TURN: the player has just left {the(start.name)} and is now in {new}, a room they have never" in user
    assert f"({the(start.name)}, where you came from)" in user
    assert "How you described it" not in user

    start.description = "Old words about the first room."
    events = perform(state, content, f"go:{OPPOSITE[direction]}")
    _, user = narrator_messages(state, content, "go back", events, "grim")
    assert "a room they have been in before" in user and "Old words about the first room." in user

    _, user = narrator_messages(state, content, "look around", [], "grim")
    assert f"THIS TURN: the player is in {the(start.name)}." in user and "Exits: " in user
    assert "Old words" not in user  # the old description only comes back on re-entry


def test_exits_say_what_lies_beyond(content):
    state = generate(2)
    stairs = next(r for r in state.rooms if r.fixture == "stairs")
    near = next(r for r in state.rooms if any(e.to == stairs.id for e in r.exits.values()))
    state.room_id = near.id
    assert "(unexplored; the stairs down beyond)" in exit_notes(state)


async def test_moves_are_journaled_as_one_line(content, profile):
    game = Game(generate(5), Config(backend="offline"), None, profile=profile)
    await game.opening(lambda _: None)
    go = next(i for i, a in enumerate(game.choices(), 1) if a.id.startswith("go:"))
    await game.begin(str(go))
    await game.finish(lambda _: None)
    assert game.state.journal[-1].startswith("You went ") and "Exits" not in game.state.journal[-1]
