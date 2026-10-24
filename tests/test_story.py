import random

import pytest

from ptg.config import Config, load_game, save_game
from ptg.events import Event
from ptg.game import Game, narratable
from ptg.models import OPPOSITE
from ptg.story import ProfileView, StoryEngine, StoryError, load_files, load_library
from ptg.ui.app import PTGApp
from ptg.ui.game_screen import GameScreen
from ptg.ui.hub import HubScreen
from ptg.ui.widgets import Picture, PictureClock
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
    (story("id: x\nwhen: enter_room\nsprite: gargoyle"), "no sprite called 'gargoyle'"),
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


def test_give_and_take_go_through_the_pack_and_your_gear(content):
    """[give] made no card and tossed your old sword on the floor; [take] missed your gear and counters (F74)."""
    lib = library(content, story("id: gift\nwhen: turn", "A gift. [give war_pick] [give leather_jerkin]"),
                  story("id: thief\nwhen: turn", "A thief! [take leather_jerkin] [take bomb] [take oil_flask]"))
    engine = StoryEngine(lib, content)
    state = generate(1)
    state.room.monster = None
    events = engine.force(state, "gift")
    assert state.player.weapon == "rusty_sword" and "war_pick" in state.player.inventory and not state.room.items
    assert state.player.armor == "leather_jerkin"  # (nothing on: on it goes)
    cards = [e for e in events if e.data.get("item")]
    assert [(e.data["item"], e.data["how"]) for e in cards] == [("war_pick", "story"), ("leather_jerkin", "story")]
    assert not any(narratable(e) for e in cards)  # its card and the event's own words tell it
    bombs = state.player.bombs
    events = engine.force(state, "thief")
    assert state.player.armor is None and state.player.bombs == bombs - 1
    effect = next(e for e in events if e.kind == "story_effect").text
    assert "lost the Leather Jerkin" in effect and "you had no Flask of Lamp Oil to lose" in effect


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


async def test_only_the_first_card_carries_the_sprite(profile):
    g = game(profile)
    g.force_event = "mirror_trial"
    result = await g.opening(lambda _: None)
    assert [e.data.get("sprite") for e in result.events if e.kind == "story"] == ["mirror"]
    await g.begin("I slowly put down my sword")
    result = await g.finish(lambda _: None)
    assert not any(e.data.get("sprite") for e in result.events if e.kind == "story")
    assert [e.art for e in g.state.log if e.kind == "card"] == ["mirror", "", ""]


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
    assert [e.art for e in loaded.log if e.kind == "card"] == ["mirror"]  # the card replays with its art
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
        card = screen.query_one(".story-card")
        assert [picture.key for picture in card.query(Picture)] == ["mirror"]
        assert screen.query_one("#choices").border_title == "✧ The Mirror Trial"
        await pilot.press("2", "enter")  # lower your weapon
        await pilot.pause(0.5)
        assert card.query_one(Picture) in PictureClock.of(app).pictures  # the old card's mirror moves on (in sight)
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


def test_reloading_the_story_keeps_what_works(content, monkeypatch):
    from ptg.story import parser, reload_library

    before = load_library(content)
    assert reload_library(content) is not before  # read again from the files
    good = load_library(content)

    def broken(paths, content):
        raise StoryError("Problems in the story files:\n  story/new.md line 3: no such trigger")

    monkeypatch.setattr(parser, "load_files", broken)
    with pytest.raises(StoryError):
        reload_library(content)
    assert load_library(content) is good


# --- your ghost ------------------------------------------------------------------

GHOST = {"name": "Brannoc", "level": 2, "floor": 1, "items": ["hand_axe"], "gold": 40,
         "epitaph": "Should have dodged.", "cause": "slain by the Troll on floor 1"}
GHOST_SCENE = story("id: own_ghost\ntitle: An Old Face\nwhen: enter_room\nif: monster ghost\nsecret: yes\nhint: Hm.",
                    "{ghost} turns. You remember dying: {ghost_cause}. Your stone said: {ghost_epitaph}\n\n"
                    "* Say {ghost} (say {ghost}, {ghost})\n  -> It remembers. [calm] [secret]\n"
                    "* (anything else)\n  -> It doesn't.")


def beside_your_ghost(content, ghost: dict, seed: int = 4):
    """A run haunted by `ghost`, the player in the room next to it (nothing else about), and the way in."""
    state = generate(seed, ghost=ghost, content=content)
    haunt = next(r for r in state.rooms if r.monster and r.monster.ghost_of)
    direction, exit_ = next((d, e) for d, e in haunt.exits.items() if not e.locked)
    state.room_id = exit_.to
    state.room.monster = None
    return state, haunt, OPPOSITE[direction]


async def test_your_ghost_scene_names_it_and_calm_lays_it_to_rest_mid_fight(content, profile):
    profile.add_ghost(1, **GHOST)
    ghost = profile.pick_ghost(random.Random(0), chance=1.0)
    state, haunt, way_in = beside_your_ghost(content, ghost)
    g = Game(state, Config(backend="offline"), None, profile=profile, library=library(content, GHOST_SCENE))
    entered = await g.act(f"go {way_in}", lambda _: None)
    card = next(e for e in entered.events if e.kind == "story")
    assert card.text.startswith("Brannoc turns. You remember dying: slain by the Troll on floor 1.")
    assert "Should have dodged." in card.text and g.state.in_combat and g.state.scene  # the fight waits
    assert g.choices()[0].label == "Say Brannoc"

    result = await g.act("Brannoc!", lambda _: None)
    assert g.state.room.monster is None and not g.state.scene
    rest = next(e for e in result.events if e.kind == "ghost_rest")
    assert rest.data["told_by"] == "exact" and not narratable(rest)  # the card says it; the narrator doesn't
    assert any(e.kind == "story_effect" and "finally rests" in e.text for e in result.events)
    assert profile.pick_ghost(random.Random(0), chance=1.0) is None  # laid to rest for good
    assert "own_ghost" in profile.secrets()


def test_a_ghost_story_waits_for_a_run_with_a_ghost(content):
    lib = library(content, story("id: name_it\nwhen: say hello", "Hello, {ghost}."))
    engine = StoryEngine(lib, content)
    state = generate(1)
    assert not engine.wants_say(state, "hello")  # no ghost this run
    state.ghost = dict(GHOST)
    assert engine.on_say(state, "hello")[-1].text == "Hello, Brannoc."
    forced = engine.force(generate(1), "name_it")  # testing it with --event, ghost or not
    assert forced[-1].text == "Hello, (your ghost's name)."


def test_say_its_name(content):
    lib = library(content, story("id: its_name\nwhen: say {ghost}\nif: monster ghost", "It stops. [calm]"))
    engine = StoryEngine(lib, content)
    state, haunt, way_in = beside_your_ghost(content, dict(GHOST, id=1))
    state.room_id = haunt.id
    assert state.in_combat and not engine.wants_say(state, "hello there")
    assert engine.wants_say(state, "Brannoc, it's me")
    events = engine.on_say(state, "Brannoc, it's me")
    assert state.room.monster is None and any(e.kind == "ghost_rest" for e in events)


def test_a_scene_about_another_monster_still_waits_for_the_fight_to_end(content):
    lib = library(content, story("id: goblin_talk\nwhen: enter_room\nif: monster goblin",
                                 "Hi.\n\n* Wave (wave)\n  -> It waves."))
    engine = StoryEngine(lib, content)
    state, haunt, way_in = beside_your_ghost(content, dict(GHOST, id=1))
    state.room_id = haunt.id
    assert engine.after_turn(state, [Event("enter", "", data={"first": True})]) == [] and not state.scene


@pytest.mark.parametrize("text,message", [
    (story("id: x\nwhen: enter_room", "Hello, {ghots}."), "unknown placeholder {ghots}"),
    (story("id: x\nwhen: enter_room", "Hello, {Ghost}."), "unknown placeholder {Ghost}"),
    (story("id: x\ntitle: {ghost}'s Rest\nwhen: enter_room"), "the title and hint can't use placeholders"),
])
def test_placeholder_mistakes_are_caught(content, text, message):
    with pytest.raises(StoryError) as error:
        library(content, text)
    assert message in str(error.value)


# --- the characters' stories (W8) ---------------------------------------------------------------------------------

def test_a_story_reads_and_moves_a_characters_story(content):
    """A story card could hand Lenny his tooth, but nothing told npcs.py: he stayed 'tooth', and the narrator kept
    sending you looking for it (F34). Now 'npc' reads a character's stage and [npc] moves it, and him with it."""
    from ptg import npcs, testrooms
    from ptg.rules import available_actions, room_facts

    lib = library(content, story("id: tooth_back\nwhen: turn\nif: npc lucky_lenny met; has lenny_s_bad_tooth",
                                 "He grins. [take lenny_s_bad_tooth] [give lenny_s_good_tooth] [npc lucky_lenny done]"),
                  story("id: never_met\nwhen: turn\nif: not npc lucky_lenny", "Who's Lenny?"))
    engine = StoryEngine(lib, content)
    state = testrooms.build(content, "lenny", "new", seed=4)
    assert engine._eligible(state, lib.get("never_met"), {}) is False  # (found his tooth: the story knows of him)
    state.quests.clear()
    assert engine._eligible(state, lib.get("never_met"), {})
    state.room_id = testrooms.target(state).id
    lenny = state.room.monster
    assert not engine._eligible(state, lib.get("tooth_back"), {})
    state.quests[npcs.LENNY] = "met"  # (as walking in on him does)
    assert [e.text for e in engine.after_turn(state, []) if e.kind == "story"] == ["He grins."]
    assert state.quests[npcs.LENNY] == "done" and lenny.mood == "happy" and npcs.GOOD_TOOTH in state.player.inventory
    assert "has his bad tooth back" in room_facts(state, content)
    assert "lenny" not in [a.id for a in available_actions(state, content)]


def test_npc_angry_and_calmed_set_how_they_stand(content):
    from ptg import npcs

    lib = library(content, story("id: cross\nwhen: turn", "Swoogy sees red. [npc swoogy_the_gooey angry]"),
                  story("id: soothe\nwhen: turn", "He calms. [npc swoogy_the_gooey calmed]"))
    engine = StoryEngine(lib, content)
    state = generate(3)
    state.room.monster = npcs.sized(content, npcs.SWOOGY, 1, npcs.SWOOGY_SIZE, hostile=False, mood="challenge")
    engine.force(state, "cross")
    assert state.in_combat and state.room.monster.mood == "angry" and state.room.monster.intent == "heavy"
    engine.force(state, "soothe")
    assert not state.in_combat and state.room.monster.mood == "calmed" and npcs.stage(state, npcs.SWOOGY) == "calmed"


def test_meet_and_gain_triggers(content):
    """There was no trigger for meeting a character, nor for finding a thing (F34)."""
    from ptg import testrooms
    from ptg.models import DELTA
    from ptg.rules import perform

    lib = library(content, story("id: hello_lenny\nwhen: meet lucky_lenny", "A sad little man waves."),
                  story("id: anyone\nwhen: meet", "Someone's here."),
                  story("id: mouse\nwhen: meet king_mouse", "Squeak."),
                  story("id: toothy\nwhen: gain lenny_s_bad_tooth", "Ew."))
    engine = StoryEngine(lib, content)
    state = testrooms.build(content, "lenny_quest", "new", seed=4)
    here, there = state.room, testrooms.target(state)
    way = next(d for d, (dx, dy) in DELTA.items() if (here.x + dx, here.y + dy) == (there.x, there.y))
    fired = engine.after_turn(state, perform(state, content, f"go:{way}"))
    assert [e.text for e in fired if e.kind == "story"] == ["A sad little man waves.", "Someone's here."]
    state.room.items.append("lenny_s_bad_tooth")
    state.room.features = [f for f in state.room.features if "lenny_s_bad_tooth" not in f.loot]
    fired = engine.after_turn(state, perform(state, content, "take:lenny_s_bad_tooth"))
    assert [e.text for e in fired if e.kind == "story"] == ["Ew."]


@pytest.mark.parametrize("text,message", [
    (story("id: x\nwhen: turn\nif: npc lenny done"), "'lenny' isn't a monster key"),
    (story("id: x\nwhen: turn\nif: npc lucky_lenny happy"), "lucky_lenny's stages are unknown, found_item, met"),
    (story("id: x\nwhen: turn", "Hi. [npc swoogy_the_gooey]"), "[npc] takes 2 argument(s)"),
    (story("id: x\nwhen: turn", "Hi. [npc swoogy_the_gooey sulking]"), "swoogy_the_gooey's stages are"),
    (story("id: x\nwhen: meet lucky_lennie"), "unknown monster 'lucky_lennie' for 'when: meet'"),
    (story("id: x\nwhen: gain a_golden_toaster"), "unknown item 'a_golden_toaster' for 'when: gain'"),
    (story("id: x\nwhen: meet lucky_lenny swoogy_the_gooey"), "'meet' takes one monster's key at most"),
])
def test_character_story_mistakes_are_caught(content, text, message):
    with pytest.raises(StoryError) as error:
        library(content, text)
    assert message in str(error.value)


async def test_the_documented_whose_tooth_card_fires(content, profile):
    """docs/writing-events.md's example: found before you've met him, his tooth has its card."""
    from ptg import npcs

    lib = library(content, story("id: whose_tooth\ntitle: Whose Tooth?\nwhen: gain lenny_s_bad_tooth\n"
                                 "if: npc lucky_lenny found_item", "Scratched into the tooth: PROPERTY OF LENNY."))
    g = game(profile, lib, seed=3)
    g.state.room.monster = None
    g.state.room.items.append(npcs.BAD_TOOTH)
    await g.begin("take the bad tooth")
    result = await g.finish(lambda _: None)
    assert [e.text for e in result.events if e.kind == "story"] == ["Scratched into the tooth: PROPERTY OF LENNY."]
    assert result.narration == "You take Lenny's Bad Tooth."  # (quiet: no narrator, the cards say the rest)
