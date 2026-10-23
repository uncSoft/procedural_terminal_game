from conftest import FakeLLM, put_monster
from ptg.events import Event
from ptg.llm.guard import Gate, Rules, check
from ptg.llm.narrator import narrate
from ptg.rules import perform
from ptg.world import generate


def after_a_move(content, seed: int = 5):
    state = generate(seed)
    events = perform(state, content, f"go:{next(iter(state.room.exits))}")
    return state, events, Rules.for_turn(state, content, events)


def test_a_new_room_is_never_familiar(content):
    state, _, rules = after_a_move(content)
    gate = check(f"You step back into the {state.room.name} you just left. Dust hangs in the air.", rules)
    assert gate.text == "Dust hangs in the air." and gate.dropped[0][1] == "calls a new room familiar"
    walked = next(iter(rules.travel))
    for fine in (f"You push {walked} through the narrow corridor.",  # the move itself
                 "The path back leads to the room you just left.",  # going back the way you came
                 "Its lips curl back to reveal a row of teeth."):
        assert check(fine, rules).text == fine


def test_exits_must_be_real_and_complete(content):
    state, _, rules = after_a_move(content)
    missing = next(d for d in ("north", "south", "east", "west") if d not in set(state.room.exits) | rules.travel)
    gate = check(f"A narrow passage leads {missing}. Something drips.", rules)
    assert gate.text == "Something drips." and gate.dropped[0][1] == f"invents a way {missing}"
    assert check(f"A pew sits to the {missing}.", rules).text  # a position in the room, not a way out
    assert check("To the north-east, water pools.", rules).text
    exits = sorted(state.room.exits)
    if len(exits) > 1:  # "you can go" lists that leave some out mislead the player
        assert check(f"You can head {exits[0]} if you wish.", rules).dropped[0][1] == "lists only some of the exits"
    assert check(f"You can head {' or '.join(exits)}.", rules).text


def test_no_echoes_no_meta_no_questions(content):
    _, _, rules = after_a_move(content)
    gate = check("FACTS: you enter. The air is cold. What will you do next? As an AI, I can't see. "
                 "The player shivers. Your options are clear.", rules)
    assert gate.text == "The air is cold."
    assert [why for _, why in gate.dropped] == ["echoes the prompt", "puts choices to the player",
                                               "talks about the game, not in it", "talks about the game, not in it",
                                               "puts choices to the player"]


def test_nothing_is_invented(content):
    state, events, rules = after_a_move(content)
    state.room.monster = None
    rules = Rules.for_turn(state, content, events)
    unseen = next(i.name for i in content.items.values() if i.name.lower() not in rules.known)
    gate = check(f"A goblin lurks in the corner. You spot a {unseen}. You go pale as a ghost.", rules)
    assert gate.text == "You go pale as a ghost."  # a simile isn't a monster
    assert [why for _, why in gate.dropped] == ["invents goblin", f"invents {unseen.lower()}"]
    put_monster(state, content, key="goblin")
    assert check("A goblin lurks in the corner.", Rules.for_turn(state, content, events)).text


def test_streamed_sentences_come_through_as_they_finish(content):
    _, _, rules = after_a_move(content)
    gate = Gate(rules, limit=2)
    assert gate.feed("The door creaks") == []
    assert gate.feed(" open. Inside, ") == ["The door creaks open."]
    assert gate.feed("dark. And then more. ") == ["Inside, dark."]  # the third goes over the limit
    assert gate.finish() == [] and gate.dropped == [("And then more.", "goes on too long")]


async def test_the_narrator_keeps_what_survives_and_falls_back_on_nothing(content):
    state, events, _ = after_a_move(content)
    shown = []
    text, _ = await narrate(FakeLLM(text="Cold air greets you. What will you do?"), state, content, "go", events,
                            "grim", shown.append)
    assert text == "Cold air greets you." and "".join(shown).strip() == text
    text, _ = await narrate(FakeLLM(text="What will you do? Will you run?"), state, content, "wait",
                            [Event("info", "Nothing stirs.")], "grim", shown.append)
    assert text == "Nothing stirs."  # nothing survived: the facts themselves


async def test_the_model_check_scores_a_model(content):
    from ptg.llm.check import run

    question = {"kind": "question", "action_id": "", "stat": "none", "difficulty": "trivial", "success_effects": [],
                "failure_effects": [], "uses": [], "consumes": [], "summary": "ask"}
    report = await run(FakeLLM(reply=question, text="Cold air greets you. What will you do?"), content)
    assert len(report.commands) == 10 and len(report.scenes) == 5
    assert report.right == 1  # it calls everything a question: right once
    assert report.cut == 5 and all(why == "puts choices to the player" for *_, cut, _ in report.scenes
                                   for _, why in cut)
    assert "struggles with typed commands" in report.verdict() and "slips a lot" in report.verdict()
