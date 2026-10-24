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


@pytest.mark.parametrize("words, action_id", [
    ("wield the war pick", "equip:war_pick"), ("equip war pick", "equip:war_pick"),
    ("swap to the pick", "equip:war_pick"),
    ("put on the moonsilver vest", "equip:moonsilver_vest"), ("wear the vest", "equip:moonsilver_vest"),
    ("put the vest on", "equip:moonsilver_vest"),
    ("take off the chain shirt", "unequip:armor"), ("remove my armour", "unequip:armor"),
    ("take the chain shirt off", "unequip:armor"),
    ("drop the stale bread", "drop:stale_bread"), ("leave the bread here", "drop:stale_bread"),
    ("throw away the stale bread", "drop:stale_bread"), ("get rid of the bread", "drop:stale_bread"),
    ("put the bread down", "drop:stale_bread"), ("drop my armor", "drop:chain_shirt"),
    ("drop my weapon", "drop:rusty_sword"),  # (to be told you'd have nothing to fight with)
    ("wield the rusty sword", "equip:rusty_sword"),  # (to be told it's in your hand already)
])
def test_typed_gear_changes_are_real_actions(content, words, action_id):
    """'wield the war pick' was flavor and narrated as done while nothing changed (F26)."""
    intent, confident = offline_interpret(words, carrying(content))
    assert intent.action_id == action_id and confident


@pytest.mark.parametrize("words, action_id", [
    ("wield the snitch", "equip:"), ("swap weapons", "equip:"), ("wear some armor", "equip:"),
    ("take off the hat", "unequip:"), ("drop the lantern", "drop:"), ("sell the axe", "sell:"),
    ("drop to the floor", "flavor"), ("leave the room quietly now", "flavor"), ("switch places with it", "flavor"),
    ("brandish the rusty sword at the darkness", "flavor"),  # (a stunt, for the model)
])
def test_typed_gear_changes_with_nothing_by_that_name(content, words, action_id):
    """'wield the snitch' with no Snitch, or 'drop my armor', was flavor, and narrated as done (F26): the engine says
    you haven't one ("equip:"), unless the words could be about something else. Either way, the model may know."""
    intent, confident = offline_interpret(words, carrying(content))
    assert (intent.action_id or intent.kind) == action_id and not confident


def carrying(content, shop=False):
    """What the interpreter is handed by a player in a Chain Shirt with a War Pick, a Moonsilver Vest and some bread
    in the pack, at full health in a quiet room (or at Granny Gristle's counter)."""
    from ptg import inventory
    from ptg.rules import things_here

    state = shop_with(content) if shop else generate(3)
    state.room.monster = None
    state.player.armor = "chain_shirt"
    state.player.inventory += ["war_pick", "moonsilver_vest", "stale_bread"]
    assert state.player.hp == state.player.max_hp and "healing_potion" in state.player.inventory
    return available_actions(state, content) + things_here(state, content) + inventory.moves(state, content)


def shop_with(content):
    """A run standing at a shop's counter."""
    from ptg import testrooms

    state = testrooms.build(content, "shop", "new", seed=5)
    state.room_id = next(r for r in state.rooms if r.shop).id
    return state


@pytest.mark.parametrize("shop", [False, True])
@pytest.mark.parametrize("words", [
    "drink the healing potion", "use the healing potion", "save the healing potion", "take the healing potion",
    "smell the healing potion", "hug the healing potion", "keep the stale bread", "eat the stale bread",
    "hold the war pick", "show the war pick", "hide the war pick", "take the war pick", "keep the war pick",
])
def test_words_about_a_thing_you_carry_are_not_near_enough_to_drop_or_sell_it(content, words, shop):
    """At full health 'drink the healing potion' was close enough to 'Drop the Healing Potion' to drop it, and at a
    shop 'hold the war pick' sold it, without asking the model (W5 review). They're the model's to read now."""
    intent, confident = offline_interpret(words, carrying(content, shop))
    assert not confident and not intent.action_id.startswith(("drop:", "sell:", "equip:", "unequip:"))


async def test_at_a_shop_holding_a_thing_up_does_not_sell_it(content, profile, fake_llm):
    state = shop_with(content)
    state.player.inventory.append("war_pick")
    gold, pack = state.player.gold, list(state.player.inventory)
    llm = fake_llm(reply={**QUESTION, "kind": "flavor", "summary": "hold the war pick up to the light"})
    game = Game(state, Config(), llm, profile=profile)
    await game.act("hold the war pick", lambda _: None)
    assert llm.json_calls == 1  # (the model was asked)
    assert (game.state.player.gold, game.state.player.inventory) == (gold, pack)


async def test_with_nothing_by_that_name_you_are_told_so(content, profile, fake_llm):
    state = generate(3)
    state.room.monster = None
    state.player.inventory.append("war_pick")
    game = Game(state, Config(backend="offline"), None, profile=profile)
    result = await game.act("wield the snitch", lambda _: None)
    assert result.events[0].kind == "info" and "War Pick" in result.narration
    assert game.state.player.weapon == "rusty_sword"
    flavor = {**QUESTION, "kind": "flavor"}  # the model calling it flavor would have it narrated as done
    game = Game(game.state, Config(), fake_llm(reply=flavor), profile=profile)
    result = await game.act("wield the snitch", lambda _: None)
    assert result.events[0].kind == "info" and game.state.player.weapon == "rusty_sword"


def test_a_gear_change_told_as_a_stunt_is_made(content):
    """A model reading 'put away my sword and wield the war pick' as a trivial stunt had it told as done while the
    weapon stayed the same (F26)."""
    from ptg.intent import Intent
    from ptg.rules import perform_creative

    state = generate(3)
    state.room.monster = None
    state.player.armor = "chain_shirt"
    state.player.inventory += ["war_pick", "stale_bread"]
    for uses in (["war pick", "rusty sword"], []):  # (named or not)
        state.player.weapon, state.player.inventory = "rusty_sword", ["war_pick", "stale_bread"]
        _, events = perform_creative(state, content, Intent(kind="creative", difficulty="trivial", uses=uses,
                                                            summary="put away the rusty sword and wield the war pick"))
        assert events[0].kind == "equip" and state.player.weapon == "war_pick"
        assert "rusty_sword" in state.player.inventory and events[0].data["quiet"]
    for summary, done in (("take off the chain shirt", lambda: state.player.armor is None),
                          ("drop the stale bread", lambda: state.room.items == ["stale_bread"])):
        _, events = perform_creative(state, content, Intent(kind="creative", difficulty="trivial", summary=summary))
        assert events[0].kind in ("unequip", "drop") and done()
    _, events = perform_creative(state, content, Intent(kind="creative", difficulty="trivial",
                                                        summary="wear the bread as a hat"))
    assert events[0].kind == "creative"  # (a stunt, with no gear in it)


@pytest.mark.parametrize("summary", [
    "throw away the stale bread", "toss the stale bread away", "I toss the bread away",
    "toss the bread away into the corner", "dump the stale bread in the corner", "get rid of the stale bread",
    "put the stale bread down on the floor",
])
def test_throwing_a_thing_away_told_as_a_stunt_leaves_it_here(content, summary):
    """A model's trivial 'throw away the stale bread' had it 'used up' and gone ('throw', 'toss' and 'dump' spend what
    you carry), and 'get rid of it' was told as done while it stayed in the pack (W5 review): it's a drop."""
    from ptg.intent import Intent
    from ptg.rules import perform_creative

    state = generate(3)
    state.room.monster = None
    state.player.inventory.append("stale_bread")
    _, events = perform_creative(state, content, Intent(kind="creative", difficulty="trivial", uses=["stale bread"],
                                                        summary=summary))
    assert events[0].kind == "drop" and state.room.items == ["stale_bread"]
    assert "stale_bread" not in state.player.inventory


def test_a_thing_thrown_at_nothing_lands_here_and_at_something_is_used_up(content):
    """Thrown at the wall with nothing at stake, the bread was used up: now it lands here, there to take back (nothing
    changed, so nothing's wasted). Thrown at a monster, it's gone."""
    from ptg.intent import Intent
    from ptg.rules import perform_creative

    state = generate(3)
    state.room.monster = None
    state.player.inventory += ["stale_bread", "war_pick"]
    _, events = perform_creative(state, content, Intent(kind="creative", difficulty="trivial", uses=["stale bread"],
                                                        summary="throw the stale bread at the wall"))
    assert [e.kind for e in events] == ["drop"] and "stale_bread" not in state.player.inventory
    assert state.room.items == ["stale_bread"] and state.turn == 0
    put_monster(state, content, hp=50)
    state.player.inventory.append(state.room.items.pop())
    _, events = perform_creative(state, content, Intent(kind="creative", difficulty="easy", uses=["stale bread"],
                                                        success_effects=["damage_small"],
                                                        summary="throw the stale bread at the goblin"))
    assert events[0].kind in ("hit", "miss") and "stale_bread" not in state.player.inventory + state.room.items
    state.room.monster = None
    _, events = perform_creative(state, content, Intent(kind="creative", difficulty="trivial", uses=["war pick"],
                                                        summary="put the war pick on the table"))
    assert events[0].kind == "creative" and state.player.weapon == "rusty_sword"  # (not wielding it)


async def test_typing_a_gear_change_makes_it(content, profile, fake_llm):
    state = generate(3)
    state.room.monster = None
    state.player.inventory.append("war_pick")
    game = Game(state, Config(backend="offline"), None, profile=profile)
    await game.act("wield the war pick", lambda _: None)
    assert game.state.player.weapon == "war_pick" and "rusty_sword" in game.state.player.inventory
    reply = {**QUESTION, "kind": "action", "action_id": "drop:rusty_sword"}  # the model sees the moves too
    game = Game(game.state, Config(), fake_llm(reply=reply), profile=profile)
    await game.act("I've no more need of that old blade", lambda _: None)
    assert "rusty_sword" in game.state.room.items and "rusty_sword" not in game.state.player.inventory


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


async def test_each_reroll_says_how_much_fate_it_left_counted_from_before_the_roll(content, profile, monkeypatch):
    """Run 44: two rerolls both said '(3 left)', since a perfect dodge on the second had won a token back, and only the
    last reroll reached the narrator."""
    from ptg import combat

    def lucky(state, roll):  # every reroll wins a token back, as a perfect dodge would
        if state.reroll:
            state.player.fate += 1
            return []
        return combat.fortune(state, roll)

    state = generate(1)
    state.player.wits, state.player.fate = -30, 3
    state.room.features[0].hidden = True
    game = Game(state, Config(backend="offline"), None, profile=profile)
    monkeypatch.setattr("ptg.rules.fortune", lucky)
    await game.begin("search the room for secrets")
    while game.can_reroll() and game._rerolls < 2:
        pending = game.reroll()
    assert game._rerolls == 2
    assert [e.text for e in pending.events if e.kind == "fate_spent"] == [
        "You spend a Fate token to reroll (2 left).", "You spend a Fate token to reroll (1 left)."]


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
    state.player.inventory.append("oil_flask")
    game = Game(state, Config(backend="offline"), None, profile=profile)
    text = await game.refresh_suggestion()
    assert text and game.choices()[-1].id == "suggest"
    assert "troll" in text.lower()
    state.player.inventory.remove("oil_flask")  # with nothing that would do anything (a potion's for you), none
    game = Game(state, Config(backend="offline"), None, profile=profile)
    assert await game.refresh_suggestion() == "" and game.choices()[-1].id != "suggest"


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


async def test_lm_studio_says_which_models_are_loaded():
    import httpx

    from ptg.llm.openai_compat import OpenAICompatLLM

    def lm_studio(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v0/models":
            return httpx.Response(200, json={"data": [{"id": "big", "type": "llm", "state": "loaded"},
                                                      {"id": "small", "type": "llm", "state": "not-loaded"},
                                                      {"id": "nomic-embed", "type": "embeddings", "state": "loaded"}]})
        return httpx.Response(200, json={"data": [{"id": "small"}, {"id": "big"}, {"id": "nomic-embed"}]})

    llm = OpenAICompatLLM("http://localhost:1234")
    llm.client = httpx.AsyncClient(transport=httpx.MockTransport(lm_studio))
    assert await llm.catalog() == [("big", True), ("small", False)]
    assert await llm.list_models() == ["big", "small"]
    await llm.prepare()
    assert llm.model == "big"  # never a model that would have to be loaded

    def ollama(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v0/models":
            return httpx.Response(404)
        return httpx.Response(200, json={"data": [{"id": "llama3.2:3b"}]})

    llm.client = httpx.AsyncClient(transport=httpx.MockTransport(ollama))
    assert await llm.catalog() == [("llama3.2:3b", None)]  # it doesn't say


def test_the_log_reads_back_newest_first(tmp_path):
    from ptg.llm.base import log_exchange, read_log

    log_exchange("json", {"model": "m", "messages": [{"role": "user", "content": "hi"}]}, '{"a": 1}')
    log_exchange("guard", ["meta: As an AI, I can't."], "The torch gutters.")
    with (tmp_path / "llm.log").open("a", encoding="utf-8") as f:  # a request the log cut short
        f.write('--- 12:00:00 stream\n>>> {\n "model": "m", "messa\n<<< The door creaks.\n\n')
    stream, guard, json_ = read_log()
    assert (stream.label, stream.request, stream.response) == ("stream", '{\n "model": "m", "messa', "The door creaks.")
    assert guard.request == ["meta: As an AI, I can't."] and guard.response == "The torch gutters."
    assert json_.request["messages"][0]["content"] == "hi" and json_.response == '{"a": 1}'
    assert len(read_log(limit=2)) == 2
    assert read_log(path=tmp_path / "missing.log") == []
