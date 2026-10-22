import pytest

from ptg.config import Config, load_game, save_game
from ptg.game import Game
from ptg.llm.base import LLMError, ThinkFilter, extract_json
from ptg.llm.interpreter import interpret, offline_interpret
from ptg.llm.openai_compat import normalize_url
from ptg.models import MonsterState
from ptg.rules import available_actions
from ptg.world import generate


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


def actions_for(content, seed=1, monster=None):
    state = generate(seed)
    if monster:
        m = content.monster(monster)
        state.room.monster = MonsterState(key=m.key, name=m.name, hp=m.hp, max_hp=m.hp)
    return state, available_actions(state, content)


def test_offline_interpreter_matches_commands(content):
    state, actions = actions_for(content)
    direction = next(iter(state.room.exits))
    assert offline_interpret(direction[0], actions)[0].action_id == f"go:{direction}"
    assert offline_interpret(f"go {direction}", actions)[0].action_id == f"go:{direction}"
    assert offline_interpret("search for secrets", actions)[0].action_id == "search_room"
    feature = state.room.features[0].name.split()[-1]
    assert offline_interpret(f"search the {feature}", actions)[0].action_id == "search:0"
    assert offline_interpret("what am I carrying?", actions)[0].kind == "question"
    intent, confident = offline_interpret("do a little dance", actions)
    assert intent.kind == "flavor" and not confident

    state, actions = actions_for(content, monster="goblin")
    state.player.hp = 5
    actions = available_actions(state, content)
    assert offline_interpret("attack", actions) == (offline_interpret("hit it", actions)[0], True)
    assert offline_interpret("drink the potion", actions)[0].action_id == "use:healing_potion"
    assert offline_interpret("run away!", actions)[0].action_id == "flee"


async def test_confident_commands_skip_the_model(content, fake_llm):
    state, actions = actions_for(content, monster="goblin")
    llm = fake_llm(reply={"kind": "flavor"})
    intent, error = await interpret(llm, state, content, "attack", actions)
    assert intent.action_id == "attack" and llm.json_calls == 0


async def test_model_creative_intent_passes_through(content, fake_llm):
    state, actions = actions_for(content, monster="goblin")
    reply = {"kind": "creative", "action_id": "", "stat": "agility", "difficulty": "medium",
             "success_effects": ["stun"], "failure_effects": ["hurt_self_small"], "summary": "throw sand"}
    intent, error = await interpret(fake_llm(reply=reply), state, content, "I throw sand in its eyes", actions)
    assert intent.kind == "creative" and intent.success_effects == ["stun"] and error is None


async def test_model_hallucinated_action_falls_back(content, fake_llm):
    state, actions = actions_for(content)
    reply = {"kind": "action", "action_id": "teleport", "stat": "none", "difficulty": "trivial",
             "success_effects": [], "failure_effects": [], "summary": "teleport home"}
    intent, _ = await interpret(fake_llm(reply=reply), state, content, "beam me up", actions)
    assert intent.kind == "flavor"


async def test_model_failure_falls_back_to_keywords(content, fake_llm):
    state, actions = actions_for(content)
    intent, error = await interpret(fake_llm(fail=True), state, content, "please search for secrets now", actions)
    assert intent.action_id == "search_room" or intent.kind == "flavor"
    assert error and "model is down" in error


async def test_game_turn_with_model(content, fake_llm):
    llm = fake_llm(reply={"kind": "question", "action_id": "", "stat": "none", "difficulty": "trivial",
                          "success_effects": [], "failure_effects": [], "summary": "ask"},
                   text="You are fine, mostly.")
    game = Game(generate(1), Config(), llm)
    chunks = []
    await game.opening(chunks.append)
    assert game.state.room.description == "You are fine, mostly."
    result = await game.act("how am I doing?", chunks.append)
    assert result.narration == "You are fine, mostly."
    assert [e.kind for e in game.state.log] == ["narration", "player", "narration"]


async def test_narrator_failure_falls_back_to_facts(content, fake_llm):
    game = Game(generate(1), Config(), fake_llm(fail=True))
    result = await game.act("1", lambda _: None)
    assert result.narration and any("narrator" in e for e in result.errors)


async def test_autosave_round_trip(content):
    game = Game(generate(9), Config(backend="offline"), None)
    await game.opening(lambda _: None)
    await game.act("1", lambda _: None)
    loaded = load_game()
    assert loaded is not None and loaded.model_dump() == game.state.model_dump()
    game.state.status = "dead"
    save_game(game.state)
    assert load_game() is None  # finished games aren't offered to continue
