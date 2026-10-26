"""Statuses (statuses.py), poison first: what it does, what cures it, what guards against it, and how it's shown."""

import dataclasses
import random

import pytest
from conftest import put_monster

from ptg import combat, dice, rules, statuses, testrooms
from ptg.content import ContentError, _read, build_content, load_content
from ptg.llm.prompts import player_status
from ptg.rules import available_actions, perform
from ptg.ui.dice import advantage_hint
from ptg.world import generate


def ids(state, content):
    return [a.id for a in available_actions(state, content)]


def quiet(seed=3):
    state = generate(seed)
    state.room.monster = None
    return state


def venomous(content, key="goblin", trick="deadly_venom"):
    monster = content.monster(key)
    content.monsters[key] = dataclasses.replace(monster, tricks=[*monster.tricks, trick])
    return content


def test_poison_takes_hold_once_and_a_guard_stops_it():
    state = quiet()
    events = statuses.inflict(state, "poison", "The snake's bite")
    assert state.player.statuses == {"poison": 1} and [e.kind for e in events] == ["status", "warning"]
    assert events[0].text == "The snake's bite has poisoned you."
    assert "-2 to your rolls" in events[1].text and "shrine" in events[1].text
    assert statuses.inflict(state, "poison") == []  # (poisoned already: no worse)
    state.player.statuses.clear()
    statuses.guard(state, "poison", 1)
    events = statuses.inflict(state, "poison", "The snake's bite")
    assert events[0].kind == "guarded" and "0 guards left" in events[0].text
    assert not state.player.statuses and "poison" not in state.player.guards


def test_poison_burns_a_step_or_a_fights_turn_at_a_time_but_never_kills():
    state = quiet()
    statuses.inflict(state, "poison")
    state.player.hp = 6
    burns = [statuses.tick(state, when)[0] for when in ("step", "round", "step", "round")]
    assert state.player.hp == 1 and [e.data["damage"] for e in burns] == [2, 2, 1, 0]
    assert "won't finish you" in burns[-1].text and not state.over


def test_each_turn_of_a_fight_burns(content):
    state = quiet()
    put_monster(state, content, key="goblin")
    state.player.max_hp = state.player.hp = 200  # (the goblin's blows aren't what's counted)
    statuses.inflict(state, "poison")
    events = perform(state, content, "dodge")
    assert [e.data["damage"] for e in events if e.kind == "status_tick"] == [2]


def test_walking_burns_and_quick_travel_burns_all_the_way(content):
    state = quiet()
    statuses.inflict(state, "poison")
    hp = state.player.hp
    direction = next(d for d, e in state.room.exits.items() if not e.locked)
    events = perform(state, content, f"go:{direction}")
    burn = f"☠ The poison burns: -2 HP ({hp - 2}/{state.player.max_hp})."
    assert [e.text for e in events if e.kind == "status_tick"] == [burn]
    burns = statuses.summed([e for _ in range(3) for e in statuses.tick(state, "step")])
    assert len(burns) == 1 and burns[0].data["damage"] == 6 and "all the way: -6 HP" in burns[0].text


def test_poisoned_every_roll_of_yours_is_two_worse(content):
    state = quiet()
    statuses.inflict(state, "poison")
    events = perform(state, content, "search_room")
    roll = next(e.dice for e in events if e.dice)
    assert ("poisoned", -2) in roll.bonuses and len(roll.dice) == 1 and not roll.hindered
    assert "- 2 poisoned" in roll.describe()
    assert dice.HINDERED.get() == dice.Hindrance()  # (only for the turn)
    monster_roll = dice.check(random.Random(1), "bite", [], 10, actor="monster")
    assert not monster_roll.bonuses and len(monster_roll.dice) == 1


def test_a_status_could_put_your_rolls_at_a_disadvantage_instead():
    """(Poison was, at first: -2 is kinder. Another status may want it.)"""
    token = dice.HINDERED.set(dice.Hindrance("blinded", disadvantage=True))
    try:
        roll = dice.check(random.Random(2), "attack", [], 10, advantage=1)
        worse = dice.check(random.Random(2), "attack", [], 10)
    finally:
        dice.HINDERED.reset(token)
    assert len(roll.dice) == 1 and roll.hindered == "blinded" and len(worse.dice) == 2
    assert advantage_hint(roll) == "blinded: your advantage is lost"
    worst = dice.Roll("x", "player", [3, 15], 3, [], 10, False, -1, hindered="blinded")
    assert advantage_hint(worst) == "two dice: keep the worst (blinded)"


def test_a_shrine_cures_poison_again_and_again(content):
    state = quiet()
    state.room.fixture = "shrine"
    assert "shrine_pray" not in ids(state, content)  # (nothing to cure, nothing to lift)
    for _ in range(2):
        statuses.inflict(state, "poison")
        pray = next(a for a in available_actions(state, content) if a.id == "shrine_pray")
        assert "cure you (poisoned)" in pray.label and pray.hint == "free"
        events = perform(state, content, "shrine_pray")
        assert not state.player.statuses and any(e.kind == "cured" for e in events)
        assert not state.room.fixture_used  # (a prayer isn't its one use)
    perform(state, content, "shrine_blood")
    statuses.inflict(state, "poison")
    assert "shrine_pray" in ids(state, content)  # (bled on, it still hears a prayer)


def test_pure_cures_poison_and_guards_against_the_next_one(content):
    state = quiet()
    state.player.inventory.append("pure")
    assert "use:pure" not in ids(state, content)
    statuses.inflict(state, "poison")
    drink = next(a for a in available_actions(state, content) if a.id == "use:pure")
    assert drink.label == "Drink the Pure" and drink.hint == "cures poison"
    events = perform(state, content, "use:pure")
    assert not state.player.statuses and state.player.guards == {"poison": 1} and "pure" not in state.player.inventory
    assert [e.kind for e in events][:3] == ["use", "cured", "guarded"]
    assert statuses.inflict(state, "poison")[0].kind == "guarded"
    assert statuses.inflict(state, "poison")[0].kind == "status"


def test_pure_drunk_ahead_of_time_guards_but_doesnt_pile_up(content):
    state = quiet()
    state.player.inventory += ["pure", "pure"]
    events = perform(state, content, "use:pure")  # (said, not listed: no poison to cure yet)
    assert state.player.guards == {"poison": 1} and events[0].kind == "use"
    events = perform(state, content, "use:pure")
    assert state.player.inventory.count("pure") == 1 and "still guards you" in events[0].text


def test_pure_in_a_fight_takes_a_turn(content):
    state = quiet()
    state.player.inventory.append("pure")
    put_monster(state, content, key="goblin")
    statuses.inflict(state, "poison")
    assert "use:pure" in ids(state, content)
    perform(state, content, "use:pure")
    assert not state.player.statuses and state.turn == 1


def test_a_venomous_bite_poisons_you_and_its_owner_may_carry_pure():
    content = venomous(load_content())
    state = quiet()
    put_monster(state, content, key="goblin")
    state.player.armor, state.player.agility = None, -20  # (every bite lands)
    events = []
    for _ in range(20):
        if state.player.statuses or state.over:
            break
        events += combat.monster_turn(state, content, random.Random(len(events)))
    assert state.player.statuses == {"poison": 1}
    assert any(e.kind == "status" and e.text == "The Goblin's bite has poisoned you." for e in events)
    drops = [combat._drops(state, content, random.Random(seed), state.room.monster) for seed in range(200)]
    assert 30 < sum("pure" in d for d in drops) < 70  # (a quarter of the time)


def test_serpentis_is_venomous(content):
    assert "venom" in content.monster("serpentis").tricks


def test_resting_poisoned_does_half_the_good(content):
    healed = {}
    for sick in (False, True):
        state = quiet()
        state.player.hp = 5
        if sick:
            statuses.inflict(state, "poison")
        events = perform(state, content, "rest")
        healed[sick] = state.player.hp - 5
        assert ("barely sleep" in events[0].text) == sick
    assert healed[True] == healed[False] // 2


def test_the_narrator_is_told_youre_poisoned(content):
    state = quiet()
    assert "Poisoned" not in player_status(state, content)
    statuses.inflict(state, "poison")
    assert "Poisoned: Venom in your blood" in player_status(state, content)


def test_the_poison_test_room_starts_you_poisoned_with_a_pure_and_a_shrine(content):
    state = testrooms.build(content, "poison", "new", seed=1)
    assert state.player.statuses == {"poison": 1} and "pure" in state.player.inventory
    assert testrooms.target(state).fixture == "shrine"
    assert testrooms.describe(content, state)[0][1].startswith("A shrine")


def test_what_cures_and_guards_must_be_statuses_the_game_knows():
    def read(name: str) -> str:
        text = _read(name)
        return text.replace('cures = ["poison"]\nguards = {poison = 1}', 'cures = ["hiccups"]\nguards = {poison = -1}')
    with pytest.raises(ContentError) as error:
        build_content(read)
    assert "statuses the game knows: poison" in str(error.value) and "like {poison = 2}" in str(error.value)


def test_the_bot_cures_itself():
    from bot import choose

    content = load_content()
    state = quiet()
    statuses.inflict(state, "poison")
    state.player.inventory.append("pure")
    assert choose(state, content) == "use:pure"
    state.player.inventory.remove("pure")
    state.room.fixture = "shrine"
    assert choose(state, content) == "shrine_pray"


def test_poison_says_what_it_does(content):
    said = statuses.effects(statuses.DEFS["poison"])
    assert said == ("-2 to your rolls · -2 HP a step and a fight's turn, never the last · cure: pray at a shrine, "
                    "or drink Pure")
    state = quiet()
    state.player.inventory.append("pure")
    statuses.guard(state, "poison", 1)
    assert "still guards you" in rules.why_not(state, content, "use:pure")


# --- shown: the status bar, the sheet, the story ----------------------------------------------------------------------

async def test_poison_shows_by_your_health_on_the_sheet_and_in_the_story():
    from test_tabs import plain
    from test_ui import settle, take_choice

    from ptg.config import Config
    from ptg.ui.app import PTGApp
    from ptg.ui.tabs import status_lines

    app = PTGApp(Config(backend="offline", player_name="T"), test_room=("poison", "new", 0))
    async with app.run_test(size=(152, 43)) as pilot:
        await pilot.pause(0.5)
        await settle(app, pilot)
        screen = app.screen
        state = screen.game.state
        hud = str(screen.query_one("#hud").render())
        assert "☠ Poisoned" in hud and hud.index("☠") < hud.index("⛨")  # (by your health)
        sheet = plain(status_lines(state, screen.game.content), 160)
        assert "☠ Poisoned" in sheet and "cure: pray at a shrine" in sheet
        direction = next(d for d, e in state.room.exits.items() if not e.locked and not state.rooms[e.to].monster)
        await take_choice(app, pilot, screen, f"go:{direction}")
        said = " ".join(str(w.render()) for w in screen.query("#story .system-line"))
        assert "☠ The poison burns: -2 HP" in said
        await take_choice(app, pilot, screen, "use:pure")
        assert not state.player.statuses and "☠" not in str(screen.query_one("#hud").render())
        assert "Guard against poison" in plain(status_lines(state, screen.game.content), 160)
