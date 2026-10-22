import pytest

from ptg.config import Config, load_game, save_game
from ptg.events import Event
from ptg.game import Game
from ptg.story import ProfileView, StoryEngine, StoryError, load_files, load_library
from ptg.ui.app import PTGApp
from ptg.ui.game_screen import GameScreen
from ptg.ui.hub import HubScreen
from ptg.world import generate

def library(content, *texts):
    return load_files([(f"test{i}.md", text) for i, text in enumerate(texts)], content)


def story(header: str, body: str = "Something happens.") -> str:
    return f"---\n{header.strip()}\n---\n{body.strip()}\n"


def game(profile, lib=None, llm=None, seed=1):
    return Game(generate(seed), Config(backend="offline"), llm, profile=profile, library=lib)


# --- files ---------------------------------------------------------------------

def test_shipped_story_files_load(content):
    lib = load_library(content)
    assert {"mirror_trial", "old_word"} <= set(lib.events)
    assert all(e.secret and e.hint for e in lib.secrets)
    mirror = lib.get("mirror_trial")
    assert mirror.is_scene and set(mirror.nodes) == {"start", "bow"}


@pytest.mark.parametrize("text,message", [
    (story("id: x\nwhen: enter_room", "Boom. [explode]"), "unknown effect [explode]"),
    (story("id: x\nwhen: sneeze"), "unknown trigger 'sneeze'"),
    (story("id: x\nwhen: enter_room\nif: floor ~ 2"), "can't read the condition"),
    (story("id: x\nwhen: enter_room", "Hi.\n\n* Go (go)\n  -> Gone. [goto nowhere]"), "goto nowhere"),
    (story("id: x\nwhen: enter_room", "You find it. [give golden_toaster]"), "give golden_toaster"),
    (story("id: x\nwhen: enter_room\nmood: grim"), "unknown header line"),
])
def test_mistakes_name_the_file_and_line(content, text, message):
    with pytest.raises(StoryError) as error:
        library(content, text)
    assert message in str(error.value) and "test0.md" in str(error.value)


def test_duplicate_ids_are_rejected(content):
    with pytest.raises(StoryError, match="two story files use the id 'x'"):
        library(content, story("id: x\nwhen: turn"), story("id: x\nwhen: turn"))


# --- conditions and triggers -------------------------------------------------------

def test_conditions(content):
    lib = library(content, story("id: deep\nwhen: turn\nif: floor >= 2; not in_combat; has oil_flask; not flag done"))
    engine = StoryEngine(lib, content)
    state = generate(1)
    event = lib.get("deep")
    assert not engine._eligible(state, event, {})
    state.floor = 2
    state.player.inventory.append("oil_flask")
    assert engine._eligible(state, event, {})
    state.flags.append("done")
    assert not engine._eligible(state, event, {})


def test_chance_is_seeded(content):
    lib = library(content, story("id: maybe\nwhen: turn\nif: chance 50%\nonce: always"))
    engine = StoryEngine(lib, content)
    event = lib.get("maybe")
    results = []
    for turn in range(40):
        state = generate(1)
        state.turn = turn
        results.append(engine._eligible(state, event, {}))
        assert results[-1] == engine._eligible(state, event, {})  # same state, same answer
    assert 5 < sum(results) < 35


def test_enter_room_fires_once_per_run_and_sets_flags(content, profile):
    lib = library(content, story("id: welcome\nwhen: enter_room\nif: first_visit", "A draft. [flag felt_draft]"))
    engine = StoryEngine(lib, content)
    state = generate(1)
    enter = [Event("enter", "", data={"first": True})]
    events = engine.after_turn(state, enter)
    assert [e.kind for e in events][:2] == ["story_seen", "story"] and "felt_draft" in state.flags
    assert [e for e in engine.after_turn(state, enter) if e.kind == "story"] == []  # once per run


def test_defeat_and_roll_triggers(content):
    lib = library(content,
                  story("id: rat_slayer\nwhen: defeat\nif: monster giant_rat", "Squeak no more. [souls 5]"),
                  story("id: lucky\nwhen: roll nat20", "The dice approve."))
    engine = StoryEngine(lib, content)
    state = generate(1)
    events = engine.after_turn(state, [Event("defeat", "", data={"monster": "goblin"})])
    assert not any(e.kind == "story" for e in events)
    events = engine.after_turn(state, [Event("defeat", "", data={"monster": "giant_rat"})])
    assert any(e.text == "Squeak no more." for e in events) and state.souls == 5
    from ptg.dice import Roll
    crit = Roll("attack", "player", [20], 20, [], 10, True)
    assert any(e.text == "The dice approve." for e in engine.after_turn(state, [Event("hit", "", dice=crit)]))


def test_spawn_starts_a_fight_and_ends_the_scene(content):
    lib = library(content, story("id: ambush\nwhen: turn", "Rustling.\n\n* Look (look)\n  -> A goblin! [spawn goblin]"))
    engine = StoryEngine(lib, content)
    state = generate(1)
    engine.force(state, "ambush")
    assert state.scene is not None
    engine.choose(state, 0)
    assert state.scene is None and state.in_combat and state.room.monster.key == "goblin"


# --- through the Game: magic words, scenes, persistence ----------------------------------

async def test_magic_word_is_a_secret_once_per_profile(profile):
    first = game(profile)
    fate = first.state.player.fate
    pending = await first.begin("I whisper XYZZY!")
    assert pending.intent.action_id == "story:say"
    result = await first.finish(lambda _: None)
    assert result.narration == ""  # the card says it all; no narrator call
    assert any(e.kind == "story" and e.data["voice"] == "exact" for e in result.events)
    assert first.state.player.fate == fate + 1 and first.state.turn == 0
    assert "old_word" in profile.secrets()
    assert [e.kind for e in first.state.log][-4:] == ["player", "card", "mechanic", "system"]  # ✧ secret found

    second = game(profile, seed=2)
    assert not second.story.wants_say(second.state, "xyzzy")  # once per profile: now it's just a word


async def test_mirror_trial_scene(profile):
    g = game(profile)
    g.force_event = "mirror_trial"
    result = await g.opening(lambda _: None)
    assert any(e.kind == "story" for e in result.events)
    assert [a.label for a in g.choices()] == ["Attack your reflection", "Lower your weapon"]

    await g.begin("I slowly put down my sword")  # the author's keyword "put down"
    await g.finish(lambda _: None)
    assert g.state.scene.node == "bow"
    assert [a.label for a in g.choices()] == ["Step through", "Leave it be"]

    g.state.player.hp = 5
    await g.begin("1")
    result = await g.finish(lambda _: None)
    assert g.state.scene is None and g.state.player.hp == g.state.player.max_hp
    assert "mirror_trial" in profile.secrets() and "mirror_unbroken" in profile.marks()
    assert any(e.kind == "story_effect" and "Fate" in e.text for e in result.events)


async def test_scene_catch_all(profile):
    g = game(profile)
    g.force_event = "mirror_trial"
    await g.opening(lambda _: None)
    hp = g.state.player.hp
    await g.begin("I sing it a lullaby")
    await g.finish(lambda _: None)
    assert g.state.scene is None and g.state.player.hp == hp - 2
    assert "mirror_trial" not in profile.secrets()


async def test_the_model_maps_free_text_onto_a_choice(profile, fake_llm):
    llm = fake_llm(reply={"choice": 2, "question": False})
    g = game(profile, llm=llm)
    g.force_event = "mirror_trial"
    await g.opening(lambda _: None)
    await g.begin("I salute my reflection and let my sword arm fall")  # none of the author's keywords
    await g.finish(lambda _: None)
    assert llm.json_calls == 1 and g.state.scene.node == "bow"


async def test_questions_keep_the_scene_open(profile, fake_llm):
    g = game(profile, llm=fake_llm(reply={"choice": 0, "question": True}, text="It is very old, and very patient."))
    g.force_event = "mirror_trial"
    await g.opening(lambda _: None)
    await g.begin("what is this mirror?")
    result = await g.finish(lambda _: None)
    assert result.narration.startswith("It is very old") and g.state.scene is not None


async def test_marks_survive_into_the_next_run(content, profile):
    lib = library(content,
                  story("id: plant\nwhen: say remember me\nonce: always", "Noted. [mark remembered]"),
                  story("id: harvest\nwhen: run_start\nif: mark remembered", "Someone remembers you."))
    first = game(profile, lib)
    await first.begin("remember me")
    await first.finish(lambda _: None)
    second = game(profile, lib, seed=2)
    result = await second.opening(lambda _: None)
    assert any(e.text == "Someone remembers you." for e in result.events)


async def test_a_scene_survives_save_and_load(profile):
    g = game(profile)
    g.force_event = "mirror_trial"
    await g.opening(lambda _: None)
    save_game(g.state)
    loaded = load_game()
    assert loaded.scene.event == "mirror_trial"
    again = Game(loaded, Config(backend="offline"), None, profile=profile)
    assert [a.label for a in again.choices()] == ["Attack your reflection", "Lower your weapon"]


def test_profile_view_counts_deaths(profile):
    profile.start_run(1, "A", [])
    run = profile.start_run(2, "B", [])
    profile.finish_run(run, status="dead")
    view = ProfileView.from_profile(profile)
    assert view.deaths == 1 and view.wins == 0


# --- UI ------------------------------------------------------------------------

async def test_scene_in_the_ui_and_the_book_of_secrets():
    app = PTGApp(Config(backend="offline", player_name="T"), seed=1, event="mirror_trial")
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause()
        app.show_campfire()
        await pilot.pause(0.3)
        app.profile.add_souls(0)
        app.start_descent()
        await pilot.pause(0.6)
        if not isinstance(app.screen, GameScreen):
            await pilot.press("enter")
            await pilot.pause(0.6)
        screen = app.screen
        while screen.busy:
            await pilot.pause(0.1)
        assert screen.query(".story-card")
        assert screen.query_one("#choices").border_title == "✧ The Mirror Trial"
        await pilot.press("2", "enter")  # lower your weapon
        await pilot.pause(0.5)
        await pilot.press("2", "enter")  # leave it be
        await pilot.pause(0.5)
        assert screen.game.state.scene is None and "mirror_trial" in app.profile.secrets()
        assert screen.query_one("#choices").border_title == "Choices"
        await pilot.press("escape")
        await pilot.pause(0.3)
        app.show_campfire()
        await pilot.pause(0.5)
        assert isinstance(app.screen, HubScreen)
        book = app.screen.query_one("#secrets-list").render()
        total = len(load_library(app.screen.content).secrets)
        assert f"1/{total} found" in str(book) and "The Mirror Trial" in str(book)
