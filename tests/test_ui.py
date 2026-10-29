import asyncio

import pytest
from textual import events
from textual.geometry import Offset, Region
from textual.widgets import Static

from ptg import model3d, sound
from ptg.config import Config, load_game, save_game, save_path
from ptg.content import load_content
from ptg.dice import Roll
from ptg.events import Event
from ptg.sprites import DEATH_FRAMES, DEFAULT_WIDTH, SMALL, frame_count, sprite_text
from ptg.ui.app import PTGApp
from ptg.ui.dice import DiceScreen
from ptg.ui.game_screen import GameScreen, shown
from ptg.ui.hub import CROWN_GLINT, EndScreen, HubScreen
from ptg.ui.model_view import FoundScreen, ModelView
from ptg.ui.effects import Popup
from ptg.ui.panels import (BestiaryScreen, CharacterScreen, FloorScreen, HelpScreen, InfoScreen, InventoryScreen,
                           JournalScreen, LevelUpScreen, LookScreen, MapScreen, ShopScreen, floor_card_fit)
from ptg.meta import start_run
from ptg.ui.screens import AbandonScreen, IntroScreen, SetupScreen, TitleScreen
from ptg.ui.widgets import ChoiceItem, Picture, PictureClock, StoryLine, roll_text


async def settle(app, pilot, limit: float = 10.0) -> None:
    """Wait for the current turn to finish, rolling any dice, picking any perks and reading any floor's card along the
    way."""
    for _ in range(int(limit / 0.1)):
        await pilot.pause(0.1)
        if isinstance(app.screen, FloorScreen):
            await pilot.press("enter")
        elif isinstance(app.screen, DiceScreen):
            await pilot.press("space")
            await pilot.pause(1.5)
            await pilot.press("enter")
        elif isinstance(app.screen, LevelUpScreen):
            await pilot.press("1")
        elif isinstance(app.screen, GameScreen) and not app.screen.busy:
            return


async def test_campfire_descent_panels_and_continue():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="Tester"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, TitleScreen)
        await pilot.press("n")
        await pilot.pause(0.5)
        assert isinstance(app.screen, HubScreen)
        await pilot.press("d")
        await pilot.pause(0.5)
        assert isinstance(app.screen, IntroScreen)  # first descent ever
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, GameScreen)
        for command in ["1", "search the room for secrets", "sing a sea shanty", "2"]:
            await pilot.press(*command, "enter")
            await settle(app, pilot)
        assert len(app.screen.query_one("#story").query(Static)) > 6
        turns = app.screen.game.state.turn
        assert turns > 0
        for key, panel in [("f2", InventoryScreen), ("f3", CharacterScreen), ("f4", LookScreen),
                           ("f6", BestiaryScreen)]:
            await pilot.press(key)
            await pilot.pause(0.2)
            assert isinstance(app.screen, panel)
            await pilot.press("escape")
            await pilot.pause(0.1)
        await pilot.press("i", "enter")  # typed IF-style command opens the inventory
        await pilot.pause(0.2)
        assert isinstance(app.screen, InventoryScreen)
        await pilot.press("escape")  # the inventory closes
        await pilot.press("escape")  # "Press Esc again for the title screen": an Esc too many doesn't end a run
        await pilot.pause(0.3)
        assert isinstance(app.screen, GameScreen)
        await pilot.press("escape")
        await pilot.pause(0.3)
        assert isinstance(app.screen, TitleScreen)
        await pilot.press("c")
        await settle(app, pilot)
        assert isinstance(app.screen, GameScreen) and app.screen.game.state.turn == turns


async def test_a_run_in_progress_comes_first_and_picks_up_where_it_was():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"))
    state = start_run(app.profile, load_content(), "T", seed=5)
    state.room.monster, state.room.items = None, ["healing_potion"]
    save_game(state)
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause(0.3)
        title = app.screen
        assert [w.id for w in title.query_one("#menu").children][:2] == ["continue", "new"]
        assert title.query_one("#run-info").display
        assert app.focused.id == "continue" and str(title.query_one("#new").label) == "New run"
        assert "Floor 1/4" in str(title.query_one("#run-info").render())
        await pilot.press("n")  # a new run, not without asking
        await pilot.pause(0.3)
        assert isinstance(app.screen, AbandonScreen)
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert app.screen is title and load_game() is not None
        await pilot.press("n")
        await pilot.pause(0.3)
        await pilot.press("enter")  # "Continue it" is the one already chosen
        await settle(app, pilot)
        await pilot.pause(0.5)
        screen = app.screen
        story = screen.query_one("#story")
        classes = [c for w in story.children for c in w.classes]
        assert "continued" in classes and "recap" not in classes  # offline: no repeat
        assert not story.query(Picture) and not story.query(".loot-card")  # (the room is the stage's, its things Here's)
        assert any(t.id == "floor:healing_potion" and "take:healing_potion" in {a.id for a in t.verbs}
                   for t in screen.things)  # (anything lying there is a tile to take)
        assert str(story.children[-1].render()).strip().startswith("You're in the ")


async def test_abandoning_a_run_from_the_title_ends_it_as_a_death():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"))
    state = start_run(app.profile, load_content(), "T", seed=5)
    state.souls = 9
    save_game(state)
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("n")
        await pilot.pause(0.3)
        await pilot.click("#abandon")
        await pilot.pause(0.5)
        assert isinstance(app.screen, HubScreen) and app.profile.souls >= 9 and load_game() is None
        assert app.profile.runs(limit=1)[0]["cause"] == "abandoned on floor 1"
        await pilot.press("escape")  # the title: nothing to continue now
        await pilot.pause(0.3)
        assert app.screen.query_one("#continue").disabled and app.focused.id == "new"
        assert str(app.screen.query_one("#new").label) == "Play"


async def test_a_daily_from_the_command_line_asks_about_a_run_in_progress():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), daily=True)
    save_game(start_run(app.profile, load_content(), "T", seed=5))
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause(0.3)
        assert isinstance(app.screen, AbandonScreen)


async def test_a_run_that_cant_be_continued_says_why():
    save_path().write_text('{"version": 1, "status": "playing"}')
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"))
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause(0.3)
        info = app.screen.query_one("#run-info")
        assert info.display and "an older version of the game saved it" in str(info.render())
        assert app.screen.query_one("#continue").disabled and app.focused.id == "new"


async def test_a_press_on_a_choice_just_replaced_is_dropped(monkeypatch):
    """Run 44 crashed here: a click on a choice in the instant it was replaced, which Textual took for the start of a
    text selection in a widget no longer on the screen."""
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        gone = screen.query(ChoiceItem).first()
        x, y = gone.region.x + 1, gone.region.y
        await gone.remove()
        # the screen's map of what's where, a moment behind: the old choice is still there
        monkeypatch.setattr(screen, "get_widget_and_offset_at", lambda *_: (gone, Offset(1, 0)))
        monkeypatch.setattr(screen, "get_widget_at", lambda *_: (gone, Region(x - 1, y, 20, 1)))
        await app.on_event(events.MouseDown(None, x, y, 0, 0, 1, False, False, False, screen_x=x, screen_y=y))
        assert app.screen is screen


async def test_a_click_on_a_choice_is_that_choice_wherever_it_is_now():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        first = screen.query(ChoiceItem).first()
        screen.refresh_choices()
        assert screen.query(ChoiceItem).first() is first  # nothing changed, so nothing was swapped out
        turn = screen.game.state.turn
        screen.post_message(ChoiceItem.Chosen(1, "go:nowhere"))  # a choice that's gone: nothing happens
        await pilot.pause(0.3)
        assert screen.game.state.turn == turn
        assert [a.id for a in screen.game.choices()].index("search_room") > 0
        screen.post_message(ChoiceItem.Chosen(1, "search_room"))  # its number was 1 in an older list
        await settle(app, pilot)
        assert screen.game.state.room.room_searched


def told_since(story, start: int) -> list[str]:
    """What the story has shown since its `start`th piece, by kind."""
    kinds = ("player-line", "floor-header", "secret-banner", "room-row", "story-sprite", "loot-row", "narration")
    return [next((k for k in kinds if k in widget.classes), type(widget).__name__)
            for widget in list(story.children)[start:] if not widget.has_class("turn-marker")]


async def take_choice(app, pilot, screen, action_id: str) -> None:
    ids = [a.id for a in screen.game.choices()]
    screen.run_turn(str(ids.index(action_id) + 1))
    for _ in range(60):
        await pilot.pause(0.2)
        if isinstance(app.screen, FloorScreen):
            await pilot.press("enter")
        elif isinstance(app.screen, GameScreen) and not app.screen.busy:
            break


async def test_a_room_is_the_stage_and_what_lies_in_it_is_heres(monkeypatch):
    """Run 44 had a potion's card come above the room's picture and its chest after what was said of it. The room is
    the stage's now, who and what is in it Here's, and the story is words, command first; on the stairs, the new
    floor's potion is a tile too, under the floor's header."""
    from ptg import rules
    from ptg.world import generate

    seed = next(s for s in range(500) if any(not e.locked and generate(s).rooms[e.to].fixture == "chest"
                                             for e in generate(s).room.exits.values()))
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T", auto_roll=True), seed=seed)
    async with app.run_test(size=(130, 46)) as pilot:
        screen = await into_a_run(app, pilot)
        state, story = screen.game.state, screen.query_one("#story")
        direction, way = next((d, e) for d, e in state.room.exits.items()
                              if not e.locked and state.rooms[e.to].fixture == "chest")
        state.rooms[way.to].monster, state.rooms[way.to].items = None, ["healing_potion"]
        start = len(story.children)
        await take_choice(app, pilot, screen, f"go:{direction}")
        assert told_since(story, start) == ["player-line", "narration"]  # (words only)
        assert {"fixture:chest", "floor:healing_potion"} <= {t.id for t in screen.things}
        assert str(screen.query_one("#stage").border_title) == f"✦ {state.room.name}"
        logged = [text for (text,) in app.profile.db.execute(
            "select text from turns where run_id = ? and turn = ? and kind = 'shown'", (state.run_id, state.turn))]
        assert logged[0] == f"> Go {direction}" and len(logged) == 2  # the turn log keeps it as it looked

        build = rules.build_floor

        def with_a_potion(state, content):
            build(state, content)
            state.room.monster, state.room.items = None, ["healing_potion"]

        monkeypatch.setattr(rules, "build_floor", with_a_potion)
        for room in state.rooms:
            room.monster = None
        state.room_id = next(r.id for r in state.rooms if r.fixture == "stairs")
        await take_choice(app, pilot, screen, "descend")
        assert told_since(story, 0)[:2] == ["player-line", "floor-header"]  # a new floor, a new page
        assert told_since(story, 0)[-1] == "narration"
        assert any(t.id == "floor:healing_potion" for t in screen.things)

async def test_a_hosted_game_keeps_its_narrator_and_debug_screen_to_itself(monkeypatch):
    """Served to several players (ptg serve), Settings can't point the server's narrator elsewhere, and the debug
    screen, which shows the model log, stays shut. Sound plays in the player's browser, so F8 and Settings' sound
    row are there as ever."""
    from textual.widgets import Input

    from ptg.ui.debug import DebugScreen

    monkeypatch.setenv("PTG_HOSTED", "1")
    app = PTGApp(Config(backend="anthropic", layout="classic", model="claude-haiku-5-5", player_name="Ava"), debug=True)
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("f12")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, DebugScreen) and app.check_action("toggle_sound", ())
        await pilot.press("s")
        await pilot.pause(0.3)
        assert isinstance(app.screen, SetupScreen) and not any(w.display for w in app.screen.query(".local"))
        assert app.screen.query_one("#setup-sound").display
        app.screen.query_one("#name", Input).value = "Ava Rose"
        app.screen.action_save()
        await pilot.pause(0.2)
        assert (app.config.player_name, app.config.backend, app.config.model) == ("Ava Rose", "anthropic",
                                                                                  "claude-haiku-5-5")


async def test_death_goes_to_the_tombstone_then_the_campfire():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="Doomed"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause()
        app.show_campfire()
        await pilot.pause(0.3)
        app.profile.set("intro_seen", 1)
        app.start_descent()
        await pilot.pause(0.5)
        if isinstance(app.screen, IntroScreen):
            await pilot.press("enter")
        await settle(app, pilot)
        game = app.screen.game
        from conftest import put_monster

        put_monster(game.state, game.content, key="orc", hp=999)
        game.state.player.hp = 1
        game.state.player.agility = -50
        app.screen.refresh_panels()
        for _ in range(10):
            if not isinstance(app.screen, GameScreen):
                break
            await pilot.press("a", "t", "t", "a", "c", "k", "enter")
            await settle(app, pilot)
        await pilot.pause(1.5)
        assert isinstance(app.screen, EndScreen)
        assert app.profile.runs()[0]["status"] == "dead"
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert isinstance(app.screen, HubScreen)


async def test_a_test_room_from_the_command_line_counts_for_nothing():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="Tester"), test_room=("swoogy", "strong", 0))
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause(0.5)
        await settle(app, pilot)
        assert isinstance(app.screen, GameScreen) and app.screen.game.state.test_room == "swoogy"
        assert not app.screen.game.autosave and app.screen.game.state.player.weapon == "silvered_blade"
        await pilot.press("escape", "escape")
        await pilot.pause(0.3)
        assert isinstance(app.screen, TitleScreen) and not save_path().exists()


async def test_a_test_room_from_f12_mid_run_leaves_that_run_as_it_was():
    from test_debug import plain
    from textual.widgets import Select

    from ptg.ui.debug import DebugScreen, TestRoomsTab

    app = PTGApp(Config(backend="offline", layout="classic", player_name="Tester"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        await into_a_run(app, pilot)
        await pilot.press("f12")
        await pilot.pause(0.3)
        await pilot.press("0")
        await pilot.pause(0.3)
        tab = app.screen.query_one(TestRoomsTab)
        assert isinstance(app.screen, DebugScreen) and "Lucky Lenny" in plain(tab.query_one("#test-info").content)
        tab.query_one("#test-who", Select).value = "shiny_shop"
        tab.query_one("#test-kit", Select).value = "new"
        await pilot.pause(0.2)
        assert "Granny Kamultruk's shop" in plain(tab.query_one("#test-info").content)
        await pilot.click("#test-go")
        await pilot.pause(0.5)
        await settle(app, pilot)
        games = [s for s in app.screen_stack if isinstance(s, GameScreen)]
        assert len(games) == 1 and games[0] is app.screen and app.screen.game.state.test_room == "shiny_shop"
        assert load_game().test_room == "" and load_game().seed == 1  # the real run, saved as it was


async def test_first_run_opens_settings():
    app = PTGApp(None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, SetupScreen)


async def into_a_run(app, pilot) -> GameScreen:
    await pilot.pause()
    app.show_campfire()
    await pilot.pause(0.3)
    app.profile.set("intro_seen", 1)
    app.start_descent()
    await pilot.pause(0.5)
    if isinstance(app.screen, IntroScreen):
        await pilot.press("enter")
    await settle(app, pilot)
    return app.screen


async def test_fights_flash_lunge_and_dissolve():
    """A fight plays on the foe's tile in Here (a test room puts a foe in the first room, so it's there to see)."""
    from conftest import put_monster

    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        game = screen.game
        played = []
        play = screen._play_scene

        async def spy(picture, steps):
            played.append([pose for pose, _, _ in steps])
            await play(picture, steps)
        screen._play_scene = spy

        put_monster(game.state, game.content, key="hobgoblin")
        screen.refresh_panels()
        await pilot.pause(0.3)
        assert screen._tile_picture("hobgoblin") is not None  # (the foe's tile has its picture)
        here = game.state.room_id
        await screen._fight_animations([Event("hit", ""), Event("monster_hit", "")], ("hobgoblin", "Hobgoblin"), here)
        # the next blow kills it: its tile is still up for the dissolve (it goes when Here is drawn again)
        game.state.room.monster = None
        await screen._fight_animations([Event("hit", "")], ("hobgoblin", "Hobgoblin"), here)
        assert played == [["idle"] * 4 + ["lunge", "lunge", "idle"], ["idle"] * 4 + ["death"] * DEATH_FRAMES]
        assert not screen.animating

        played.clear()
        await screen._fight_animations([Event("hit", "")], ("hobgoblin", "Hobgoblin"), here + 1)  # fled
        game.config.art = "ascii"
        await screen._fight_animations([Event("hit", "")], ("hobgoblin", "Hobgoblin"), here)
        assert played == [["idle"] * 4]  # ASCII art still flashes, but doesn't dissolve

async def test_fixtures_come_alive():
    """A fixture is a tile Here: its picture glints while there is something to do with it, plays the moment you use
    it, and rests (a chest open and emptied, a shrine snuffed) after."""
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        game = screen.game
        clock = PictureClock.of(app)

        # The chest waits, shut (it only glints).
        game.state.room.monster = None
        game.state.room.fixture, game.state.room.fixture_used = "chest", False
        screen.refresh_panels()
        await pilot.pause(0.3)
        chest = screen._tile_picture("chest")
        assert chest is not None and chest.key == "chest" and set(chest.loop) == {0, 1}
        assert not screen.query_one("#story").query(Picture)  # (not in the story)

        # Opening it plays on its own tile, then it rests open and emptied, as the room's picture shows it.
        await screen._fixture_moment([Event("chest", "")])
        assert chest not in clock.pictures
        assert chest.content == sprite_text("chest", frame_count("chest") - 1)

        # No tile to play it on (it isn't here), or ASCII art: nothing, and no new picture.
        before = len(screen.query(Picture))
        await screen._fixture_moment([Event("descend", "")])
        game.config.art = "ascii"
        await screen._fixture_moment([Event("shrine", "")])
        assert len(screen.query(Picture)) == before

        # A shrine waiting to be used flickers, its snuffed-out frame left for after the offering.
        game.config.art = "sprites"
        game.state.room.fixture, game.state.room.fixture_used = "shrine", False
        screen.refresh_panels()
        await pilot.pause(0.3)
        shrine = screen._tile_picture("shrine")
        assert shrine.key == "shrine" and shrine.loop == [0, 1, 2] and frame_count("shrine") == 4
        await screen._fixture_moment([Event("shrine", "")])
        assert shrine.content == sprite_text("shrine", 3)

def close_on_border(screen) -> bool:
    box, close = screen.query_one(".panel-box").region, screen.query_one("#close").region
    return (close.y, close.right) == (box.y, box.right - 2)


async def test_panels_close_with_the_mouse():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        screen.game.state.player.inventory += ["oil_flask", "stale_bread", "holy_water"]
        for key, panel in [("f1", HelpScreen), ("f2", InventoryScreen), ("f3", CharacterScreen), ("f4", LookScreen),
                           ("f5", MapScreen), ("f6", BestiaryScreen), ("f7", JournalScreen)]:
            await pilot.press(key)
            await pilot.pause(0.3)
            assert isinstance(app.screen, panel) and close_on_border(app.screen), key
            await pilot.click("#close")
            await pilot.pause(0.2)
            assert isinstance(app.screen, GameScreen), f"{key}: the ✕ closes it"
            await pilot.press(key)
            await pilot.pause(0.3)
            await pilot.click(offset=(1, 1))
            await pilot.pause(0.2)
            assert isinstance(app.screen, GameScreen), f"{key}: a click outside closes it"
        await pilot.press("f2")
        await pilot.pause(0.3)
        box = app.screen.query_one(".panel-box").region
        await pilot.press("down", "down", "down")  # each item's notes once resized the box, and the ✕ followed it
        await pilot.pause(0.3)
        assert close_on_border(app.screen) and app.screen.query_one(".panel-box").region == box
        panel = app.screen
        panel.action_close()
        panel.action_close()  # a double click
        await pilot.pause(0.2)
        assert isinstance(app.screen, GameScreen)  # closed the panel, not the game under it


async def test_dice_roll_and_reroll_with_the_mouse():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        await into_a_run(app, pilot)
        results = []
        failed = Roll("might", "player", [4], 4, [("Might", 1)], dc=14, success=False)
        app.push_screen(DiceScreen(failed, "Lift the portcullis", 1, True), results.append)
        await pilot.pause(0.2)
        await pilot.click("#dice-box")  # click to roll
        assert app.screen.stage == "rolling"
        await pilot.pause(3.2)
        assert app.screen.stage == "done" and app.screen.query_one("#dice-box").has_class("tone-bad")
        await pilot.click("#dice-fate")
        await pilot.pause(0.2)
        assert results == ["reroll"]

        made = Roll("might", "player", [15], 15, [("Might", 1)], dc=14, success=True)
        app.push_screen(DiceScreen(made, "Lift the portcullis", 1, True), results.append)
        await pilot.pause(0.2)
        await pilot.click(offset=(1, 1))  # anywhere rolls...
        await pilot.pause(3.2)
        fate = app.screen.query_one("#dice-fate")
        assert app.screen.query_one("#dice-box").has_class("tone-good") and not fate.has_class("-shown")
        assert fate.styles.visibility == "hidden"
        await pilot.click(offset=(1, 1))  # ...and carries on
        await pilot.pause(0.2)
        assert results == ["reroll", "accept"]


@pytest.mark.parametrize("size,die,height,roomy", [
    ((240, 70), "SIZE", "-tall", True), ((160, 45), "SIZE", "-tall", True), ((130, 44), "SIZE", "-tall", True),
    ((100, 30), "SIZE", "-short", False), ((80, 24), "SMALL_SIZE", "-tiny", False)])
async def test_the_dice_box_fits_the_screen_and_keeps_its_size(size, die, height, roomy):
    """At 100x30 the box grew from 30 rows to 32 when the Fate button showed, its bottom off the screen (at 80x24 it
    was cut from the start). Now its row is kept for the button from the first, a short screen drops the blank lines
    and a tiny one has a smaller die: the whole box shows, the same size from the roll to the verdict. A big screen's
    too, the verdict stamped big in rows kept for it."""
    from ptg import dice_art

    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        failed = Roll("might", "player", [4], 4, [("Might", 1)], dc=14, success=False)
        app.push_screen(DiceScreen(failed, "Lift the portcullis with all your might", 1, True))
        await pilot.pause(0.3)
        box = app.screen.query_one("#dice-box")
        before = box.region
        assert app.screen.die == getattr(dice_art, die) and app.screen.has_class(height)  # (the app's size classes
        # reach it)
        assert app.screen.roomy == roomy and bool(app.screen.query("#dice-stakes")) == roomy
        await pilot.press("space")
        await rolled(app, pilot)
        assert app.screen.query_one("#dice-fate").has_class("-shown")
        assert box.region == before and box.region.y >= 0 and box.region.bottom <= size[1]
        prompt = app.screen.query_one("#dice-prompt").region
        assert before.y < prompt.y < before.bottom - 1  # the prompt, inside the frame


async def rolled(app, pilot) -> None:
    """Wait for the dice to land and the verdict to be told."""
    for _ in range(80):  # (the dice tumble for about three seconds: longer, on a busy machine)
        await pilot.pause(0.1)
        if app.screen.stage == "done":
            return
    raise AssertionError("the dice never landed")


async def test_a_big_screen_sets_the_dice_a_table_of_their_own():
    """Beside the die, what you need (big), your odds, your bonuses and what a hit deals; under it the twenty faces
    by how each would go. It lands on 14: the face is marked, the sum told, HIT stamped big; a critical bursts with
    light."""
    from ptg.dice_art import SPARK, lettering
    from ptg.outcome import GOOD, GREAT
    from ptg.ui.dice import BURST_ROOM
    from ptg.ui.effects import rgb

    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(240, 70)) as pilot:
        await pilot.pause()
        hit = Roll("attack", "player", [14], 14, [("might", 2), ("level", 1)], dc=11, success=True,
                   hits_for="1d6 + 2", damage=[("1d6", 5), ("might", 2)])
        app.push_screen(DiceScreen(hit, "Attack the goblin", 1, True, tone=GOOD, word="HIT"))
        await pilot.pause(0.3)
        dice = app.screen
        assert (dice.scale, dice.pad) == (2, BURST_ROOM)
        stakes = dice.query_one("#dice-stakes").content.plain
        for told in ("NEED", "to hit · its defense", "roll 8 or better", "65% chance", "+2 might", "+1 level",
                     "a hit deals 1d6 + 2"):
            assert told in stakes, told
        assert dice.query_one("#dice-strip").content.plain.split("\n")[0].split() == [str(n) for n in range(1, 21)]
        await pilot.press("space")
        await rolled(app, pilot)
        assert "▲" in dice.query_one("#dice-strip").content.plain.split("\n")[1]
        assert dice.query_one("#dice-bonuses").content.plain == "d20 14  + 2 might  + 1 level  =  17   vs 11"
        verdict = dice.query_one("#dice-verdict")
        assert verdict.content.plain == lettering("HIT", rgb(GOOD), 2, (16, 18, 42)).plain
        assert verdict.region.height == 6
        assert dice.query_one("#dice-damage").content.plain == "→ 7 damage (1d6 5 + might 2)"
        die = dice.query_one("#dice-faces").content
        assert SPARK not in {tuple(span.style.color.triplet) for span in die.spans if span.style.color}
        await pilot.press("enter")

        crit = Roll("attack", "player", [20], 20, [("might", 2)], dc=11, success=True, hits_for="1d6 + 2",
                    damage=[("1d6", 6), ("crit 1d6", 4), ("might", 2)])
        app.push_screen(DiceScreen(crit, "Attack the goblin", 1, True, tone=GREAT, word="CRITICAL!"))
        await pilot.pause(0.3)
        dice = app.screen
        await pilot.press("space")
        await rolled(app, pilot)
        assert dice.query_one("#dice-verdict").content.plain == lettering("CRITICAL!", rgb(GREAT), 2,
                                                                           (16, 18, 42)).plain
        die = dice.query_one("#dice-faces").content
        assert SPARK in {tuple(span.style.color.triplet) for span in die.spans if span.style.color}  # (its burst)


async def test_a_smaller_screen_tells_the_target_and_odds_in_a_line():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        hit = Roll("attack", "player", [14], 14, [("might", 2), ("level", 1)], dc=11, success=True,
                   hits_for="1d6 + 2")
        app.push_screen(DiceScreen(hit, "Attack the goblin", 1, True))
        await pilot.pause(0.3)
        assert app.screen.query_one("#dice-target").content.plain == ("needs 11 to hit  ·  roll 8+ (65%)  ·  "
                                                                      "a hit deals 1d6 + 2")
        assert app.screen.query("#dice-strip") and not app.screen.query("#dice-stakes")


async def test_each_reroll_line_counts_the_fate_left_from_before_the_roll(monkeypatch):
    """Run 44: the second reroll's perfect dodge won a token back, and the story said '(3 left)' twice. Each line
    counts from before the roll, as the dice screen does."""
    from ptg import combat

    def lucky(state, roll):  # every reroll wins a token back, as a perfect dodge would
        if state.reroll:
            state.player.fate += 1
            return []
        return combat.fortune(state, roll)

    monkeypatch.setattr("ptg.rules.fortune", lucky)
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        state.player.wits, state.player.fate = -30, 3  # a search that fails (but for a natural 20), and Fate 3/3
        state.room.features[0].hidden = True
        story = screen.query_one("#story")
        start = len(story.children)
        screen.run_turn("search the room for secrets")
        rerolls, fate_shown, seen = 0, [], set()
        for _ in range(300):
            await pilot.pause(0.1)
            dice = app.screen
            if isinstance(dice, DiceScreen) and id(dice) not in seen:
                seen.add(id(dice))
                fate_shown.append(dice.fate)
                await pilot.press("space")
                while dice.stage != "done":
                    await pilot.pause(0.1)
                if dice.can_reroll and not dice.roll.success and rerolls < 2:
                    rerolls += 1
                    await pilot.press("f")
                else:
                    await pilot.press("enter")
            elif isinstance(dice, GameScreen) and not dice.busy and seen:
                break
        assert rerolls == 2 and fate_shown == [3, 2, 1]
        lines = [shown(w).strip() for w in list(story.children)[start:] if "Fate spent" in shown(w)]
        assert lines == ["✦ Fate spent. Rerolling... (2 left)", "✦ Fate spent. Rerolling... (1 left)"]


async def test_rolls_light_up_the_story():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        game = screen.game
        from conftest import put_monster

        put_monster(game.state, game.content, key="orc", hp=30)
        hit = Event("hit", "", dice=Roll("attack", "player", [15], 15, dc=12, success=True), data={"damage": 6})
        hurt = Event("monster_hit", "", dice=Roll("Orc attacks", "monster", [16], 16, dc=11, success=True),
                     data={"damage": 4})
        assert "✔ HIT" in roll_text(hit).plain and "✘ HIT YOU" in roll_text(hurt).plain
        game.state.player.hp -= 4
        await screen._roll_feedback([hit, hurt], game.state.player.hp + 4)
        story = screen.query_one("#story")
        assert story.has_class("tone-neutral")  # you hit it and it hit you: mixed
        assert len(screen.query(Popup)) == 2 and screen.query_one("#hud").has_class("hurt")
        await pilot.pause(1.4)
        assert not screen.query(Popup) and not story.has_class("tone-neutral")


def test_a_floor_card_draws_its_picture_as_big_as_the_screen_has_room_for(content):
    """The widest of its splash art's sizes that fits round its words, under the picture or beside it, whichever
    lets it be bigger; words only on a screen too small for both, or for a floor with no art."""
    import dataclasses
    norfel = content.themes["norfel"]
    assert floor_card_fit(240, 70, norfel, True) == (160, False)  # a big screen: all of it, the words under
    assert floor_card_fit(200, 55, norfel, True) == (128, True)  # a wide, short one: the words beside
    assert floor_card_fit(80, 24, norfel, True) == (0, False)  # 80x24: words only, as ever
    assert floor_card_fit(240, 70, dataclasses.replace(norfel, key="no_such_floor"), True) == (0, False)
    widths = [floor_card_fit(columns, columns // 3, norfel, True)[0] for columns in range(80, 260, 10)]
    assert widths == sorted(widths)  # (a bigger screen never gets a smaller picture)


async def test_norfels_card_shows_its_splash_art_and_fits_the_screen(content):
    for size, drawn in (((240, 70), 160), ((200, 55), 128), ((80, 24), 0)):
        app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await app.push_screen(FloorScreen(4, 4, content.themes["norfel"], True))
            await pilot.pause(0.2)
            card = app.screen
            art = card.query_one("#floor-art", Static)
            assert art.display == bool(drawn) and (not drawn or art.region.width == drawn), size
            box = card.box.region
            assert box.right <= size[0] and box.bottom <= size[1], size
            assert box.contains_region(card.query_one(".panel-action").region), size  # (nothing cut off)
            words = " ".join(str(w.render()) for w in card.query(".floor-words > Static"))
            assert "Serpentis was already old" in words and "Your goal" in words
            await pilot.press("enter")
            assert not isinstance(app.screen, FloorScreen)


async def test_a_run_opens_on_its_first_floors_card(monkeypatch):
    """A run's first floor has its card too (the descents always had theirs): its art and its lore, or its words
    only with ASCII art chosen in Settings; and a floor with no art has none, as before any had art."""
    for art, drawn in (("sprites", True), ("ascii", True), ("sprites", False)):
        if not drawn:
            monkeypatch.setattr("ptg.ui.game_screen.splash_sizes", lambda key: ())
        app = PTGApp(Config(backend="offline", layout="classic", player_name="T", art=art), seed=1)
        async with app.run_test(size=(130, 44)) as pilot:
            await pilot.pause()
            app.show_campfire()
            await pilot.pause(0.3)
            app.profile.set("intro_seen", 1)
            app.start_descent()
            for _ in range(50):
                await pilot.pause(0.1)
                if isinstance(app.screen, IntroScreen):
                    await pilot.press("enter")
                elif isinstance(app.screen, FloorScreen) or isinstance(app.screen, GameScreen) and not app.screen.busy:
                    break
            if not drawn:
                assert isinstance(app.screen, GameScreen)
                continue
            card = app.screen
            assert isinstance(card, FloorScreen) and card.floor == 1 and card.theme.floor == 0  # (a dungeon)
            words = " ".join(str(w.render()) for w in card.query(".floor-words > Static"))
            assert card.theme.lore[:40] in words and "Your goal" not in words  # (its boss is on the third)
            assert card.query_one("#floor-art").display == (art == "sprites")
            await pilot.press("enter")
            await settle(app, pilot)
            assert isinstance(app.screen, GameScreen)


async def test_a_new_floor_waits_for_you():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        game = screen.game
        assert len(screen.query(".floor-header")) == 1  # floor 1's banner
        stairs = next(r for r in game.state.rooms if r.fixture == "stairs")
        game.state.room_id, stairs.monster, stairs.visited = stairs.id, None, True
        screen.refresh_panels()
        await pilot.press(*"descend", "enter")
        for _ in range(80):
            await pilot.pause(0.1)
            if not screen.busy:
                break
        assert isinstance(app.screen, FloorScreen)  # no timeout: it stays until you're done reading
        await pilot.click(offset=(60, 20))
        await pilot.pause(0.2)
        assert isinstance(app.screen, GameScreen) and game.state.floor == 2
        assert len(screen.query(".floor-header")) == 1  # a new page: floor 1's story is in the save, not on screen
        assert [e.kind for e in game.state.log].count("floor") == 2
        first = next(w for w in screen.query_one("#story").children if not w.has_class("turn-marker"))
        assert str(first.render()) == "> descend"  # this turn, at the top
        assert not screen.query_one("#story").query(Picture)  # (words only)
        assert str(screen.query_one("#stage").border_title) == f"✦ {game.state.room.name}"  # the new floor's first room


async def test_the_mouse_can_begin_and_end_a_run():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause()
        app.show_campfire()
        await pilot.pause(0.3)
        app.start_descent()
        await pilot.pause(0.5)
        assert isinstance(app.screen, IntroScreen)
        await pilot.click("#intro-hint")
        await settle(app, pilot)
        assert isinstance(app.screen, GameScreen)
        app.screen.game.state.status = "dead"
        app.end_run(app.screen)
        await pilot.pause(0.5)
        assert isinstance(app.screen, EndScreen)
        await pilot.click(app.screen.query(".end-hint Clickable").first())
        await pilot.pause(0.3)
        assert isinstance(app.screen, HubScreen)


async def test_the_end_of_a_run_is_drawn_in_pixels():
    """A pixel tombstone with your name carved in it, or a glinting crown; the ASCII ones for ASCII art."""
    from ptg.world import generate

    for art in ("sprites", "ascii"):
        app = PTGApp(Config(backend="offline", layout="classic", player_name="T", art=art), seed=1)
        async with app.run_test(size=(110, 44)) as pilot:
            await pilot.pause()
            state = generate(1, "Pip the Brave", load_content())
            state.status, state.floor, state.test_room = "dead", 2, "x"
            app.push_screen(EndScreen(state))
            await pilot.pause(0.3)
            stone = app.screen.query_one(".end-art", Static)
            lines = stone.content.plain.split("\n")
            assert "Pip the Brave" in stone.content.plain and "floor 2" in stone.content.plain
            assert ("▀" in stone.content.plain) == (art == "sprites") and "R.I.P." in lines[2]
            app.pop_screen()
            state.status = "won"
            app.push_screen(EndScreen(state))
            await pilot.pause(0.3)
            crown = app.screen.query_one(".end-art", Picture)
            if art == "sprites":
                assert crown.art.sprite == "crown" and crown in PictureClock.of(app).pictures  # it glints
                assert crown.flicker and crown.loop == CROWN_GLINT
            else:
                assert "_/\\_/\\_/\\_" in crown.content.plain and not crown.art.sprite


LONG_EPITAPH = ("Here lies Sir Reginald Pumpernickel the Brief, who tried to pet a gelatinous cube and was very, very "
                "surprised by how sticky it turned out to be.")


async def test_the_end_of_a_run_fits_the_screen():
    """On an 80x24 terminal the whole box shows, down to its hint: the blank lines between the parts go first, then
    the pixel picture shrinks to half size (ASCII art, which has one size, goes); on a big screen it all comes back."""
    from ptg.world import generate

    # (art, outcome, a long epitaph and traits) -> the picture's rows at 80x24 (0: none), then on a big screen
    expected = {("sprites", "dead", False): (10, 10), ("sprites", "dead", True): (5, 10),
                ("sprites", "won", False): (8, 8), ("sprites", "won", True): (4, 8),
                ("ascii", "dead", False): (8, 8), ("ascii", "dead", True): (0, 8),
                ("ascii", "won", False): (3, 3), ("ascii", "won", True): (3, 3)}
    for (art, status, long), (small, big) in expected.items():
        app = PTGApp(Config(backend="offline", layout="classic", player_name="T", art=art), seed=1)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            state = generate(1, "Sir Reginald Pumpernickel", load_content())
            state.status, state.floor, state.test_room = status, 2, "x"
            state.epitaph = LONG_EPITAPH if long else "Short and sweet."
            state.player.traits = ["iron_gut", "lucky"] if long else []
            app.push_screen(EndScreen(state))
            for size, rows, tight in (((80, 24), small, True), ((110, 44), big, False)):
                await pilot.resize_terminal(*size)
                await pilot.pause(0.3)
                screen = app.screen
                box, picture, hint = (screen.query_one(q) for q in ("#end-box", ".end-art", ".end-hint"))
                case = (art, status, long, size)
                assert hint.region.height == 1 and box.region.bottom < size[1], case  # all of it, above the footer
                assert hint.region.bottom < box.region.bottom, case
                assert box.has_class("-tight") == tight, case
                assert (picture.content.plain.count("\n") + 1 if picture.display else 0) == rows, case
                if art == "sprites" and status == "dead":  # the name's carved on the stone while it's full size
                    assert ("Sir Reginald P" in picture.content.plain) == (rows == 10), case


async def test_the_moments_make_sounds(monkeypatch):
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        from conftest import Recorder, put_monster

        monkeypatch.delenv("PTG_SOUND", raising=False)
        speakers = Recorder()
        monkeypatch.setattr(sound, "_sound", sound.Sound(True, 1.0, player=speakers))
        put_monster(screen.game.state, screen.game.content, key="orc", hp=200)
        screen.refresh_panels()
        await pilot.press(*"attack", "enter")
        await settle(app, pilot)
        heard = speakers.moments
        assert heard[:2] == ["select", "dice_small"] and {"hit", "crit_hit", "miss", "awful"} & set(heard)
        await pilot.press("f2")
        await pilot.pause(0.3)
        await pilot.click("#close")
        await pilot.pause(0.2)
        assert speakers.moments[-2:] == ["open", "close"]


async def test_a_run_has_its_floors_music_and_its_fights(monkeypatch):
    """The floor's music while you explore (darker on the boss floors), a fight's once a monster's after you (a
    boss's own), and the floor's again when it's over."""
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        from conftest import Recorder, put_monster

        assert sound.engine().wanted == "explore_music"  # (asked for as the run began, sound off or not)
        monkeypatch.delenv("PTG_SOUND", raising=False)
        speakers = Recorder()
        monkeypatch.setattr(sound, "_sound", sound.Sound(True, 1.0, player=speakers))
        state, content = screen.game.state, screen.game.content
        put_monster(state, content, key="orc", hp=200)
        await pilot.press(*"attack", "enter")
        await settle(app, pilot)
        assert speakers.looping == "battle_music"
        state.room.monster.hp = 0
        screen.refresh_music()
        assert speakers.looping == "explore_music"
        put_monster(state, content, key="goblin_king")
        screen.refresh_music()
        assert speakers.looping == "boss_music"
        state.room.monster = None
        state.floor = 3  # (the last dungeon's: its boss is down here)
        screen.refresh_music()
        assert speakers.looping == "deep_music"


async def test_items_drawn_in_the_maker_show_their_art(monkeypatch):
    """The same picture wherever it's shown, and animated: the pack's tile, Here, the shop. Its card and the pack's
    detail turn its model, made from that picture (ui/model_view.py); a thing with no model has its picture there
    too."""
    from ptg.ui.panels import ItemTile

    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        key = screen.game.state.player.inventory[0]
        screen.action_lookup(f"item:{key}")
        await pilot.pause(0.3)
        assert app.screen.query_one(ModelView).model is model3d.load(key) and not app.screen.query(Picture)
        await pilot.press("escape")
        modelled = model3d.available
        monkeypatch.setattr(model3d, "available", lambda k: k != key and modelled(k))  # (one with no model yet)
        screen.action_lookup(f"item:{key}")
        await pilot.pause(0.3)
        card = app.screen.query_one(Picture)
        assert card.art.sprite == f"item_{key}" and card in PictureClock.of(app).pictures
        await pilot.press("escape")
        monkeypatch.setattr(model3d, "available", modelled)
        await pilot.press("f2")
        await pilot.pause(0.3)
        inventory = app.screen
        tile = next(t for t in inventory.query(ItemTile) if inventory.items[t.index][0] == key)
        tile.focus()
        await pilot.pause(0.2)
        assert tile.query_one(Picture).art.sprite == f"item_{key}"  # (its picture on its tile, its model beside)
        turning = inventory.query_one("#inv-model", ModelView)
        assert turning.display and turning.model is model3d.load(key) and not inventory.query_one("#inv-art").display
        assert all(p in PictureClock.of(app).pictures for p in inventory.query(Picture) if p.display)


async def test_the_first_time_a_thing_is_yours_its_card_holds_it_up_turning(found_cards):
    """A thing that's never been yours before, taken: its card pops up over the story, its model turning, with what it
    is and where it went; Enter carries on. The second time it's yours, it doesn't (ui/model_view.py FoundScreen)."""
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=4)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        state.room.items = ["superior_healing_potion", "ten_foot_pole"]
        screen.refresh_panels()  # (Here's tiles, with them)
        await pilot.pause(0.2)
        screen.action_verb("take:superior_healing_potion")
        for _ in range(40):
            await pilot.pause(0.1)
            if isinstance(app.screen, FoundScreen):
                break
        card = app.screen
        assert isinstance(card, FoundScreen) and card.key == "superior_healing_potion" and screen.busy
        assert card.query_one(ModelView).model is model3d.load("superior_healing_potion")
        words = str(card.query_one("#found-text").render())
        assert "restores 24 HP" in words and "in your pack" in words and "NEW" in str(card.query_one(
            "#found-banner").render())
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, GameScreen) and "superior_healing_potion" in state.player.inventory
        state.room.items = ["superior_healing_potion"]  # (another, a thing you've had: no card)
        screen.refresh_panels()
        await pilot.pause(0.2)
        screen.action_verb("take:superior_healing_potion")
        await settle(app, pilot)
        assert isinstance(app.screen, GameScreen) and state.player.inventory.count("superior_healing_potion") == 2


async def test_the_inventory_is_tiles_and_enter_uses_the_one_picked(monkeypatch):
    from ptg.ui import widgets
    from ptg.ui.panels import ItemTile

    drawn = widgets.frames  # pretend nobody has drawn the oil yet
    monkeypatch.setattr(widgets, "frames", lambda key, *args: None if key == "item_oil_flask" else drawn(key, *args))
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        player = screen.game.state.player
        player.inventory = ["healing_potion", "healing_potion", "oil_flask"]
        player.hp = 10
        await pilot.press("f2")
        await pilot.pause(0.3)
        inventory = app.screen
        assert isinstance(inventory, InventoryScreen)
        assert len(inventory.query(ItemTile)) == 3  # the sword in hand, both potions on one tile, the oil
        detail = lambda: str(inventory.query_one("#inv-detail").render())  # noqa: E731
        assert "No picture yet" not in detail()  # the sword is drawn
        await pilot.press("right", "right")
        await pilot.pause(0.1)
        assert "No picture yet" in detail()  # the oil isn't
        await pilot.press("left")
        await pilot.pause(0.1)
        assert inventory.items[inventory.current][0] == "healing_potion"
        assert "Drink" in " ".join(str(b.render()) for b in inventory.query(".inv-verb"))
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, GameScreen)
        assert player.inventory.count("healing_potion") == 1 and player.hp > 10


async def test_found_loot_is_a_tile_to_take_or_leave():
    """What a search turns up lies there: a tile Here, with its art, to take, or leave. Taking it empties its place."""
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=4)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        index, feature = next((i, f) for i, f in state.room.visible_features() if not f.searched)
        feature.loot = ["superior_healing_potion"]
        number = next(n for n, a in enumerate(screen.game.choices(), 1) if a.id == f"search:{index}")
        screen.run_turn(str(number))
        await settle(app, pilot)
        tile = next(t for t in screen.things if t.id == "floor:superior_healing_potion")
        assert [a.id for a in tile.verbs][0] == "take:superior_healing_potion"  # there for the taking, or leaving
        assert "superior_healing_potion" in state.room.items and not screen.query_one("#story").query(Picture)
        picture = next(p for p in screen.query(".here-art").results(Picture) if p.key == "superior_healing_potion")
        assert picture.art.sprite == "item_superior_healing_potion"
        await pilot.click(picture)  # its card, with its model turning and what it does
        await pilot.pause(0.3)
        assert isinstance(app.screen, InfoScreen)
        assert app.screen.query_one(ModelView).model.name == model3d.load("superior_healing_potion").name
        assert "Superior Healing Potion" in str(app.screen.query_one("#info-text").render())
        await pilot.press("escape")
        await pilot.pause(0.2)
        screen.action_verb("take:superior_healing_potion")
        await settle(app, pilot)
        assert "superior_healing_potion" in state.player.inventory
        assert not any(t.id == "floor:superior_healing_potion" for t in screen.things)  # (Here is drawn again)

async def test_the_stage_always_shows_the_room_you_are_in():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        stage = screen.query_one("#stage")
        assert str(stage.border_title) == f"✦ {state.room.name}" and "▀" in str(screen.query_one("#stage-art").render())
        for room in state.rooms:
            room.monster = None
        go = next(n for n, a in enumerate(screen.game.choices(), 1)
                  if a.id.startswith("go:") and not state.room.exits[a.id[3:]].locked)
        came_from = state.room.name
        screen.run_turn(str(go))
        await settle(app, pilot)
        assert str(stage.border_title) == f"✦ {state.room.name}" != f"✦ {came_from}"
        back = next(n for n, a in enumerate(screen.game.choices(), 1)
                    if a.id.startswith("go:") and state.rooms[state.room.exits[a.id[3:]].to].name == came_from)
        screen.run_turn(str(back))
        await settle(app, pilot)
        assert str(stage.border_title) == f"✦ {came_from}"  # been here before: it's still the room you're in

async def test_the_pad_lights_the_ways_out_and_takes_you_there():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=57)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        for room in state.rooms:
            room.monster = None
        ways = {a.id[3:] for a in screen.game.choices() if a.id.startswith("go:")}
        for direction in ("north", "south", "east", "west"):
            assert screen.query_one(f"#dpad-{direction}").has_class("off") == (direction not in ways)
        go = next(c for c in screen.query(ChoiceItem) if "Go " in str(c.render()))
        assert str(go.render()).split(". ")[1][0] in "▲▼▶◀"  # the way's arrow by its choice
        way = sorted(ways)[0]
        target = state.room.exits[way].to
        await pilot.click(f"#dpad-{way}")
        await settle(app, pilot)
        assert state.room_id == target
        here = state.room_id
        off = next(d for d in ("north", "south", "east", "west") if screen.query_one(f"#dpad-{d}").has_class("off"))
        await pilot.click(f"#dpad-{off}")  # no door that way: nothing happens
        await settle(app, pilot)
        assert state.room_id == here

        # A shop door and no key: no choice of its own, but still a (dim) door on the pad, as on the map; clicking it
        # says it's locked and costs no turn.
        way = next(a.id[3:] for a in screen.game.choices() if a.id.startswith("go:"))
        state.room.exits[way].locked, state.room.exits[way].key = True, "small_key"
        state.player.keys = state.player.bombs = 0
        screen.refresh_choices()
        await pilot.pause(0.2)
        assert f"go:{way}" not in {a.id for a in screen.game.choices()}
        arrow = screen.query_one(f"#dpad-{way}")
        assert not arrow.has_class("off") and "locked" in arrow.tooltip
        story, turn = screen.query_one("#story"), state.turn
        start = len(story.children)
        await pilot.click(f"#dpad-{way}")
        await settle(app, pilot)
        assert state.room_id == here and state.turn == turn
        assert any("is locked" in shown(w) for w in list(story.children)[start:])


async def test_the_choices_strip_pages_when_there_are_more_than_its_lines():
    """A strip of chips as tall as it needs, up to its plan's lines; past that, a chip says how many more, and taps
    to the next page. The numbers carry on from the buttons on the tiles."""
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=57)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        state.player.inventory += ["healing_potion", "stale_bread", "smoke_bomb"]
        state.player.hp = 10
        screen.refresh_panels()
        await pilot.pause(0.2)
        lines = screen.query("#choices .choice-line")
        assert len(lines) <= screen.plan.choice_rows
        shown = [c.index for c in screen.query(ChoiceItem)]
        assert shown == sorted(shown) and shown[0] == len(screen.tile_verbs) + 1
        more = screen.query("#choices .more")
        if more:  # (more than fit: tap it for the next page)
            await pilot.click(more.first())
            await pilot.pause(0.3)
            assert [c.index for c in screen.query(ChoiceItem)][0] > shown[0]

async def test_pictures_open_their_cards():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=57)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        await pilot.click("#stage")  # the room you're in: look around
        await pilot.pause(0.3)
        assert isinstance(app.screen, LookScreen)
        await pilot.press("escape")
        await pilot.pause(0.2)
        screen.action_lookup("fixture:shrine")
        await pilot.pause(0.3)
        shrine = app.screen.query_one(Picture)  # a fixture's card has its picture, and it flickers
        assert shrine.art.sprite == "shrine" and "▀" in str(shrine.render()) and len(shrine.loop) > 1
        assert str(app.screen.query_one(".panel-box").border_title) == "Shrine"

async def test_look_shows_the_room_as_a_picture():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        await into_a_run(app, pilot)
        await pilot.press("f4")
        await pilot.pause(0.3)
        assert isinstance(app.screen, LookScreen)
        lines = str(app.screen.query_one(".panel-box Static").render()).split("\n")
        assert set(lines[0]) <= set("▀▄ ") and len(lines[0]) <= 76  # the picture first, never wider than the panel
        assert any("@" in line for line in lines[20:])  # and the floor plan after the words


async def test_no_room_pictures_in_ascii_mode():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T", art="ascii"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        assert not screen.query(".room-card")
        await pilot.press("f4")
        await pilot.pause(0.3)
        assert str(app.screen.query_one(".panel-box Static").render()).startswith("#")  # the floor plan, as ever


async def test_ctrl_l_wipes_the_terminal_and_draws_everything_again(monkeypatch):
    from textual.drivers.headless_driver import HeadlessDriver

    app = PTGApp(Config(backend="offline", layout="classic"))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        written: list[str] = []
        monkeypatch.setattr(HeadlessDriver, "is_headless", property(lambda self: False))  # as if on a terminal
        monkeypatch.setattr(app._driver, "write", written.append)
        await pilot.press("ctrl+l")
        await pilot.pause()
        out = "".join(written)
        assert "\x1b[2J" in out and out.index("\x1b[2J") < out.index("Play")  # wiped, then every cell again


async def test_the_game_redraws_itself_every_few_turns(monkeypatch):
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        redraws = []
        monkeypatch.setattr(app, "action_redraw", lambda: redraws.append(screen.game.state.turn))
        for _ in range(app.REDRAW_EVERY):
            await pilot.press(*"hum a tune", "enter")
            await settle(app, pilot)
        await pilot.pause(0.2)
        assert len(redraws) == 1


async def test_a_secret_room_is_a_celebration(monkeypatch):
    """A bang, a fanfare, a gold banner in the story, a toast, and the room in gold on the map."""
    from conftest import Recorder

    from ptg.rules import hidden_room_beside

    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=11)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        monkeypatch.delenv("PTG_SOUND", raising=False)
        speakers = Recorder()
        monkeypatch.setattr(sound, "_sound", sound.Sound(True, 1.0, player=speakers))
        state = screen.game.state
        for room in state.rooms:
            room.monster = None
        secret = next(r for r in state.rooms if r.secret)
        beside = next(r for r in state.rooms if not r.secret and abs(r.x - secret.x) + abs(r.y - secret.y) == 1)
        state.room_id, beside.visited = beside.id, True
        screen.refresh_panels()
        index = next(i for i, a in enumerate(screen.game.choices(), 1) if a.id == f"bomb:{hidden_room_beside(state)}")
        await pilot.press(*str(index), "enter")
        await settle(app, pilot)
        await pilot.pause(0.6)  # the fanfare comes just after the bang
        assert speakers.moments.index("bomb") < speakers.moments.index("secret_room")
        assert "SECRET ROOM" in str(screen.query_one(".secret-banner").render())
        assert "{" in str(screen.query_one("#map").render())
        assert any("Secret room found" in str(n.title) for n in app._notifications)
        assert any(e.kind == "system" and "Secret room found" in e.text for e in state.log)  # and after Continue


async def test_monsters_move_on_their_tiles_the_bestiary_and_on_their_cards():
    """Their frames take turns: Here's tiles beat on the app's one clock."""
    from conftest import put_monster

    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=3)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        game = screen.game
        put_monster(game.state, game.content, key="goblin", hp=200)
        screen.refresh_panels()
        await pilot.pause(0.2)
        portrait = screen._tile_picture("goblin")
        shown = set()
        for _ in range(6):
            await pilot.pause(0.25)
            shown.add(portrait.index)
        assert portrait.key == "goblin" and shown == {0, 1}

        game.profile.bump_beast("goblin", "seen")
        await pilot.press("f6")
        await pilot.pause(0.3)
        art = app.screen.query_one("#beast-art", Picture)
        assert art.key == "goblin" and art.display and len(art.loop) == 2
        frozen = portrait.index  # (Here's behind the bestiary now: it waits)
        shown = set()
        for _ in range(6):
            await pilot.pause(0.25)
            shown.add(art.index)
        assert shown == {0, 1} and portrait.index == frozen
        await pilot.press("escape")
        await pilot.pause(0.2)

        screen.action_lookup("monster:goblin")
        await pilot.pause(0.3)
        assert isinstance(app.screen, InfoScreen)
        assert app.screen.query_one(Picture).key == "goblin"


async def test_a_shop_from_its_door_to_its_counter(monkeypatch):
    """A jingle and a banner walking in; browsing opens her screen; Enter buys, and the shop opens again after."""
    from conftest import Recorder

    from ptg.models import OPPOSITE
    from ptg.world import generate

    seed = next(s for s in range(300) if any(r.shop for r in generate(s).rooms))
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=seed)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        monkeypatch.delenv("PTG_SOUND", raising=False)
        speakers = Recorder()
        monkeypatch.setattr(sound, "_sound", sound.Sound(True, 1.0, player=speakers))
        state = screen.game.state
        for room in state.rooms:
            room.monster = None
        shop = next(r for r in state.rooms if r.shop)
        way_out = next(iter(shop.exits))
        state.room_id, state.player.keys, state.player.gold = shop.exits[way_out].to, 1, 500
        screen.refresh_panels()
        ids = [a.id for a in screen.game.choices()]
        screen.run_turn(str(ids.index(f"go:{OPPOSITE[way_out]}") + 1))
        await settle(app, pilot)
        await pilot.pause(0.6)
        assert state.room is shop and "shop" in speakers.moments
        assert "SHOP" in str(screen.query(".secret-banner").last().render())

        ids = [a.id for a in screen.game.choices()]
        screen.run_turn(str(ids.index("shop") + 1))
        await settle(app, pilot)
        await pilot.pause(0.5)
        assert isinstance(app.screen, ShopScreen)
        first = shop.shop.wares[0]
        count = first.count  # (a potion: two of them)
        await pilot.press("enter")  # buy the first
        await pilot.pause(0.4)
        await settle(app, pilot)
        await pilot.pause(0.6)
        assert state.player.gold == 500 - first.price and first.count == count - 1
        assert (first in shop.shop.wares) == (count > 1)
        assert isinstance(app.screen, ShopScreen)  # back at her counter
        assert first.item in state.player.inventory or first.item in (state.player.weapon, state.player.armor)
        assert not screen.query_one("#story").query(".loot-card")  # (bought: the story says so, in words)


async def test_what_a_monster_dropped_is_a_tile_to_take(monkeypatch):
    """Its tile says so; its Take puts it in your pack (no turn), and the tile goes. Bombs and keys are yours already."""
    from conftest import put_monster

    from ptg import combat

    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=3)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        put_monster(state, screen.game.content, key="goblin", hp=1)
        state.player.might = 50
        monkeypatch.setattr(combat, "_drops", lambda *_: ["healing_potion", "bomb", "oil_flask"])
        screen.refresh_panels()
        screen.action_verb("attack")
        await settle(app, pilot)
        await pilot.pause(0.5)
        lying = [t for t in screen.things if t.id.startswith("floor:")]
        assert [t.id for t in lying] == ["floor:healing_potion", "floor:oil_flask"] and state.room.items == [
            "healing_potion", "oil_flask"]
        turn = state.turn
        screen.action_verb("take:healing_potion")
        await settle(app, pilot)
        await pilot.pause(0.4)
        assert state.room.items == ["oil_flask"] and state.turn == turn
        assert [t.id for t in screen.things if t.id.startswith("floor:")] == ["floor:oil_flask"]

async def test_a_shop_fits_a_small_screen():
    """At 100x30 the ware you'd picked was drawn into wrapping text 20 columns wide: striped noise, twice as tall,
    with its price and Buy below the bottom of the box. Now the shop shares the screen out (her small, or not at all),
    and the ware's picture is a picture of its own, small if that's what fits. The box keeps its size from ware to
    ware (it grew and shrank with each one's words, and its counter could be cut off by it): the counter and the words
    scroll, and Buy, Haggle and the keys stay put inside it."""
    from ptg.ui.panels import ItemTile
    from ptg.world import generate

    seed = next(s for s in range(300) if any(r.shop for r in generate(s).rooms))
    for size, keeper in (((100, 30), SMALL), ((80, 24), 0), ((130, 44), DEFAULT_WIDTH)):
        app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=seed)
        async with app.run_test(size=size) as pilot:
            screen = await into_a_run(app, pilot)
            state = screen.game.state
            for room in state.rooms:
                room.monster = None
            shop = next(r for r in state.rooms if r.shop)
            state.room_id, state.player.gold = shop.id, 500
            screen.open_shop()
            await pilot.pause(0.3)
            panel = app.screen
            assert isinstance(panel, ShopScreen)
            her = panel.query_one("#shop-keeper")
            assert her.display == bool(keeper) and (not keeper or her.query_one(Picture).art.pixels == keeper)
            box = panel.query_one(".shop-box").region
            shelf = panel.query_one("#shop-shelf").region
            assert box.bottom <= size[1] and shelf.bottom < box.bottom  # the counter, inside the box
            for tile in panel.query(ItemTile):
                tile.focus()
                for _ in range(20):  # (focusing scrolls it into sight: how soon depends on how busy the machine is)
                    await pilot.pause(0.05)
                    if shelf.y <= tile.region.y and tile.region.bottom <= shelf.bottom:
                        break
                art, side = panel.query_one("#shop-art", Picture), panel.query_one("#shop-side").region
                assert art.size.height == art.art.rows and art.region.right <= side.right, (size, tile.index)
                assert art.art.pixels == (DEFAULT_WIDTH if size == (130, 44) else SMALL), size
                for line in ("#shop-buy", "#shop-barter", "#shop-hint"):
                    region = panel.query_one(line).region
                    assert region.height and region.bottom < box.bottom, (size, tile.index)  # inside its frame
                assert panel.query_one(".shop-box").region == box, (size, tile.index)  # it never moves
                assert shelf.y <= tile.region.y and tile.region.bottom <= shelf.bottom, (size, tile.index)  # in sight


async def test_the_inventory_draws_things_full_size_when_there_is_room():
    """Small pictures were fixed for its tiles, whatever the screen: now they're full size (the very picture its
    detail shows) when three of them fit across, two rows down, beside one in full; small when they don't."""
    from ptg.ui.panels import ItemTile

    for size, pixels in (((130, 44), DEFAULT_WIDTH), ((100, 30), SMALL)):
        app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
        async with app.run_test(size=size) as pilot:
            screen = await into_a_run(app, pilot)
            screen.game.state.player.inventory += ["holy_water", "stale_bread", "rubber_duck"]
            await pilot.press("f2")
            await pilot.pause(0.3)
            inventory = app.screen
            tiles = list(inventory.query(ItemTile))
            assert {tile.query_one(Picture).art.pixels for tile in tiles} == {pixels}, size
            assert all(tile.has_class("full") == (pixels == DEFAULT_WIDTH) for tile in tiles)
            detail = inventory.query_one("#inv-art", Picture)
            assert detail.art.pixels == pixels and detail.key == inventory.items[0][0], size
            assert inventory.query_one(".inventory-box").region.right <= size[0]
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T", art="ascii"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:  # ASCII art: a glyph each, on small tiles
        await into_a_run(app, pilot)
        await pilot.press("f2")
        await pilot.pause(0.3)
        glyphs = [tile.query_one(Picture).art for tile in app.screen.query(ItemTile)]
        assert glyphs and all(not art.sprite and art.pixels == SMALL and art.still.plain.strip() for art in glyphs)
        assert not app.screen.query_one("#inv-art").display  # (a glyph in the detail would only be a lot of space)


async def test_a_friendly_character_is_met_in_colour():
    """Walking in on Lucky Lenny: he's a tile in Here, alive and in his own colours, with a job for you (★) and what
    he wants in words. Click him for his card, which offers what he's there for (not a blow)."""
    from ptg import testrooms

    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), test_room=("lenny", "strong", 0))
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause(0.5)
        await settle(app, pilot)
        screen = app.screen
        state = screen.game.state
        room = testrooms.target(state)
        await take_choice(app, pilot, screen, next(f"go:{d}" for d, e in state.room.exits.items() if e.to == room.id))
        await pilot.pause(0.3)
        lenny = next(t for t in screen.things if t.id == "monster:lucky_lenny")
        assert lenny.character and lenny.badge == "★" and lenny.status == "wants his bad tooth back"
        him = screen._tile_picture("lucky_lenny")
        assert isinstance(him, Picture) and him.pose == "idle" and him in PictureClock.of(app).pictures
        assert him.art.sprite == "lucky_lenny"  # (his own picture, not a grey statue)
        assert not screen.query_one("#stage").has_class("combat")
        await pilot.click(him)
        await pilot.pause(0.3)
        assert isinstance(app.screen, InfoScreen) and app.screen.action_id == "lenny"  # give him his tooth

async def test_a_fight_on_its_tile_never_moves_it_or_runs_off_the_screen():
    """A foe's tile keeps its size through a fight's frames, in every form it can take, and says a big blow is coming
    wherever it fits (a chip too: it's a foe's warning, never dropped)."""
    from conftest import put_monster

    for size in ((130, 44), (100, 30), (80, 24), (60, 34)):
        app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
        async with app.run_test(size=size) as pilot:
            screen = await into_a_run(app, pilot)
            game = screen.game
            monster = put_monster(game.state, game.content, key="goblin", hp=200, intent="heavy")
            monster.max_hp = 200
            screen.refresh_panels()
            await pilot.pause(0.3)
            tile = screen.query(".here-tile.character").first()
            box = screen.query_one("#here" if screen.plan.two_columns else "#here-strip")
            assert tile.region.bottom <= box.region.bottom, size
            words = " ".join(str(w.render()) for w in tile.query(Static))
            assert "⚠" in words and "/200" in words, (size, words)  # the warning and its health, in any form
            heights, watching = set(), True

            async def watch() -> None:
                while watching:
                    heights.add(tile.outer_size.height)
                    await asyncio.sleep(0.01)

            watcher = asyncio.create_task(watch())
            here = game.state.room_id
            await screen._fight_animations([Event("hit", ""), Event("monster_hit", "")], ("goblin", "Goblin"), here)
            monster.intent = "strike"  # (no warning now)
            screen.refresh_panels()
            await pilot.pause(0.3)
            game.state.room.monster = None  # and the next blow kills it: it dissolves where it stood
            await screen._fight_animations([Event("hit", "")], ("goblin", "Goblin"), here)
            watching = False
            await watcher
            assert len(heights) == 1, (size, heights)

async def test_a_card_is_titled_with_what_it_is_and_says_where_it_is():
    """An item's card was titled "Item", said its powers twice and never where the thing was; fixtures, rooms and
    features were "Fixture", "Room" and "In the room". Their pictures stood still, though a monster's moved."""
    from ptg import powers

    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        state, content = screen.game.state, screen.game.content
        state.player.inventory += ["mama_s_shillelagh", "mama_s_shillelagh"]
        state.room.items = ["war_pick"]

        async def card(term: str) -> tuple[str, str]:
            screen.action_lookup(term)
            await pilot.pause(0.3)
            title, body = str(app.screen.query_one(".panel-box").border_title), app.screen.query_one("#info-text")
            await pilot.press("escape")
            await pilot.pause(0.2)
            return title, str(body.render())

        title, body = await card("item:mama_s_shillelagh")
        power = powers.describe(content.item("mama_s_shillelagh"))[0]
        assert title == "Mama's Shillelagh" and body.count(power) == 1 and "in your pack ×2" in body
        title, body = await card("item:war_pick")
        sword = content.item(state.player.weapon)
        assert title == "War Pick" and "lying here" in body and f"your {sword.name}: {sword.damage} → 1d10" in body
        screen.action_lookup("fixture:chest")
        await pilot.pause(0.3)
        assert str(app.screen.query_one(".panel-box").border_title) == "Chest"
        assert app.screen.query_one(Picture) in PictureClock.of(app).pictures  # (it glints)
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert (await card(f"room:{state.room_id}"))[0] == state.room.name
        assert (await card("rule:fate"))[0] == "Fate"
        if state.room.features:
            assert (await card("feature:0"))[0].lower() == state.room.features[0].name.lower()


# --- panels that keep their size, and fit a small screen ---------------------------------------------------------

LONG_AND_SHORT = ["healing_potion", "mama_s_shillelagh", "hard_hat", "x_64gb_ddr5_ram_kit", "swoogy_s_diaper",
                  "oil_flask", "stale_bread", "holy_water", "rubber_duck", "war_pick", "chain_shirt"]


async def test_panels_keep_their_size_whatever_you_pick():
    """The inventory's box grew and shrank with each item's words and jumped up and down the screen (a click on the
    Shillelagh moved every tile six rows, so the next click hit empty box), its shelf ran past the bottom of the box
    so the last tiles could never be seen, and on a short screen what Enter does was cut off. Now a panel is sized
    once as it opens: moving and clicking change what's in it, never the box; the shelf and the words scroll inside
    it; what Enter does and the keys stay in sight; and the tile you're on is always in view."""
    from ptg.ui.panels import ItemTile

    for size in ((130, 44), (100, 30), (80, 24)):
        app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
        async with app.run_test(size=size) as pilot:
            screen = await into_a_run(app, pilot)
            screen.game.state.player.inventory += LONG_AND_SHORT
            await pilot.press("f2")
            await pilot.pause(0.3)
            panel = app.screen
            box, close = panel.query_one(".panel-box").region, panel.query_one("#close").region
            assert box.y >= 1 and box.bottom <= size[1] - 1, size  # (a row around it, to click it closed)
            shelf = panel.query_one("#inv-shelf").region
            tiles = list(panel.query(ItemTile))
            for i, tile in enumerate(tiles[1:] + [tiles[2]]):  # each tile by the keys, then a click on the Shillelagh
                if i == len(tiles) - 1:
                    panel.query_one("#inv-shelf").scroll_to_widget(tile, animate=False)  # (scrolled back up to it)
                    await pilot.pause(0.1)
                    await pilot.click(tile)
                else:
                    await pilot.press("right")
                await pilot.pause(0.05)
                assert panel.query_one(".panel-box").region == box and panel.query_one("#close").region == close
                focused = panel.focused.region
                assert shelf.y <= focused.y and focused.bottom <= shelf.bottom, (size, panel.current)  # in sight
                for line in ("#inv-use", "#inv-hint"):
                    region = panel.query_one(line).region
                    assert region.height and region.bottom < box.bottom, (size, line, panel.current)
            assert panel.items[panel.current][0] == "mama_s_shillelagh"
            words = panel.query_one("#inv-words")
            assert words.region.bottom <= panel.query_one("#inv-use").region.y  # the words scroll above it
            await pilot.press("f6")  # the bestiary: the same height, and it doesn't move either
            await pilot.pause(0.3)
            assert isinstance(app.screen, BestiaryScreen)
            beasts = app.screen.query_one(".panel-box").region
            assert (beasts.y, beasts.height) == (box.y, box.height)


async def test_f1_to_f7_work_inside_every_panel():
    """The dimmed footer behind a panel offered F1-F7, and they did nothing until you closed it. Now they switch to
    that panel (its own key closes it), from a card too; a level-up stays put under the one you look at."""
    from ptg.rules import check_level

    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(100, 30), notifications=True) as pilot:
        screen = await into_a_run(app, pilot)
        depth = len(app.screen_stack)
        for key, panel in [("f2", InventoryScreen), ("f3", CharacterScreen), ("f5", MapScreen), ("f1", HelpScreen),
                           ("f7", JournalScreen), ("f4", LookScreen), ("f6", BestiaryScreen)]:
            await pilot.press(key)
            await pilot.pause(0.2)
            assert isinstance(app.screen, panel) and len(app.screen_stack) == depth + 1, key  # in place of the last
        await pilot.press("f6")  # its own key closes it
        await pilot.pause(0.2)
        assert app.screen is screen
        screen.action_lookup("rule:fate")
        await pilot.pause(0.3)
        await pilot.press("f2")
        await pilot.pause(0.2)
        assert isinstance(app.screen, InventoryScreen) and len(app.screen_stack) == depth + 1
        await pilot.press("escape")
        await pilot.pause(0.2)

        game = screen.game  # a level-up mid-turn: a look at your things, and back to it
        game.state.player.xp = game.state.player.next_level_xp()
        check_level(game.state, game.content)
        await pilot.press(*"hum a tune", "enter")
        for _ in range(50):
            await pilot.pause(0.1)
            if isinstance(app.screen, LevelUpScreen):
                break
        level_up = app.screen
        assert isinstance(level_up, LevelUpScreen) and not level_up.query("#close")  # a panel's frame, but no ✕
        await pilot.press("f2")
        await pilot.pause(0.3)
        assert isinstance(app.screen, InventoryScreen) and app.screen_stack[-2] is level_up
        await pilot.press("enter")  # nothing's used while a perk waits
        await pilot.pause(0.2)
        assert isinstance(app.screen, InventoryScreen)
        await pilot.press("f3")
        await pilot.pause(0.3)
        assert isinstance(app.screen, CharacterScreen) and app.screen_stack[-2] is level_up
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert app.screen is level_up
        await pilot.press("1")
        await settle(app, pilot)
        assert app.screen is screen and len(game.state.player.perks) == 1


async def test_what_happens_in_the_story_is_marked_without_frames_of_its_own():
    """A card, a quest, a new floor, a secret room found and a run picked up again each drew a frame inside the
    story's own, and fought it (a card scrolled half away left its bottom edge floating at the top). Now each is a
    bar down the left, or words between ornaments; and a moment's name is said once, not in its frame and again."""
    from ptg.ui.game_screen import secret_banner

    app = PTGApp(Config(backend="offline", layout="grid", player_name="T"), seed=1)
    async with app.run_test(size=(160, 48)) as pilot:
        screen = await into_a_run(app, pilot)
        screen.add_quest("New quest: Lucky Lenny's bad tooth", new=True)
        card = screen.add_card("The Mirror Trial", "The glass ripples.")
        screen.add_card("Lucky Lenny", "Got a tooth that's killing me.", speech=True)
        screen.add_floor_header("Floor 2 of 4", "The Goblin Warren")
        screen.add_line(secret_banner(0), "secret-banner")
        screen.add_line(secret_banner(0, "SHOP", "#4cff8a"), "secret-banner shop")
        await pilot.pause(0.3)
        for piece in screen.query_one("#story").children:
            edges = piece.styles.border
            assert not any(edge[0] not in ("", "none") for edge in (edges.top, edges.right, edges.bottom)), piece
        said = " ".join(str(line.render()) for line in card.query(StoryLine))
        assert said.count("MIRROR TRIAL") == 1 and shown(card) == "story card: The Mirror Trial"


async def test_a_level_up_waits_for_a_perk():
    """The level-up could be put off (Esc, the ✕ or a click outside), and with it the arrows and the map, till a perk
    was picked from the choices. Now it waits for one: no ✕, and Esc or a click outside only say so. A card looked at
    (a number, an arrow key) is lit, and so is what it would change on the sheet under the cards; Enter takes it."""
    from ptg.rules import check_level
    from ptg.ui.panels import PerkCard, Sheet

    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await into_a_run(app, pilot)
        game = screen.game
        game.state.player.xp = game.state.player.next_level_xp()
        check_level(game.state, game.content)
        perks = list(game.state.pending_perks)
        await pilot.press(*"hum a tune", "enter")
        for _ in range(50):
            await pilot.pause(0.1)
            if isinstance(app.screen, LevelUpScreen):
                break
        level_up = app.screen
        box = level_up.query_one(".panel-box").region
        assert box.y >= 0 and box.bottom <= 24 and level_up.query_one("#levelup-button").region.bottom < box.bottom
        assert not level_up.query("#close")
        await pilot.press("escape")
        await pilot.click(offset=(0, 0))  # (the dimmed screen round the box)
        await pilot.press("enter")  # (nothing looked at yet: nothing taken)
        await pilot.pause(0.3)
        assert app.screen is level_up and "can't wait" in str(level_up.query_one("#levelup-hint").render())
        assert game.state.pending_perks == perks

        await pilot.press("2")
        await pilot.pause(0.2)
        cards = list(level_up.query(PerkCard))
        assert level_up.looking == 1 and [c.has_class("-looking") for c in cards] == [False, True, False]
        assert game.content.perks[perks[1]].name in str(level_up.query_one("#levelup-button").render())
        await pilot.press("right", "right", "left")
        await pilot.pause(0.2)
        assert level_up.looking == 2
        await pilot.press("left")
        await pilot.pause(0.2)
        assert level_up.looking == 1 and not game.state.player.perks  # (only looked at)
        assert "★ new" in str(level_up.query_one(Sheet).query_one(".sheet-growth").render())
        await pilot.press("enter")
        for _ in range(50):
            await pilot.pause(0.1)
            if not screen.busy:
                break
        assert app.screen is screen and game.state.player.perks == [perks[1]] and not game.state.pending_perks


def test_a_perks_card_says_what_it_changes_on_the_sheet():
    """A level-up's card says what its perk would change, worked out on a copy of the game (the game's untouched):
    each stat, the blow, the rolls it raises, a fall in red; or that it changes no number."""
    from types import SimpleNamespace

    from ptg.ui.panels import perk_changes, taken
    from ptg.world import generate

    content = load_content()
    state = generate(1, content=content)
    game = SimpleNamespace(state=state, content=content)
    hp, most = state.player.hp, state.player.max_hp
    said = {key: perk_changes(game, taken(game, key)).plain for key in content.perks}
    assert said["tough"] == f"▲ HP {hp}/{most} → {hp + 8}/{most + 8}"
    assert said["glass_cannon"].startswith("▼ HP") and "▲ Damage" in said["glass_cannon"]
    assert "▲ +1 to Throw, Dodge, Flee and Pick a lock" in said["nimble"] and "▲ Defense" in said["nimble"]
    assert said["vampiric"] == "No number on your sheet: it works in play."
    assert not state.player.perks and state.player.max_hp == most  # (only ever a copy)


def test_the_hero_portrait_is_art_not_a_monster():
    """The hero's face was brought in through the maker as a monster: it's the level-up's picture, and nothing else."""
    from ptg import sprites
    from ptg.ui.panels import PORTRAIT

    assert PORTRAIT not in load_content().monsters and len(sprites.frames(PORTRAIT)) == 4


def test_help_wraps_under_its_words():
    """The help was wrapped by hand for a wider panel than it had, so its long lines broke back to the left edge and
    the hand-made indents landed mid-paragraph. Now it's tables: each rule's words wrap under its words."""
    from rich.console import Console

    from ptg.ui.panels import RULES, help_text

    assert not any("\n" in words for _, _, words in RULES)
    console = Console(width=60, record=True, color_system=None)
    console.print(help_text())
    lines = console.export_text().splitlines()
    start = next(i for i, line in enumerate(lines) if "BOMBS" in line)
    column = lines[start].index("Every floor")
    rest = lines[start + 1:start + 4]
    assert all(line[:column].strip() == "" and line[column] != " " for line in rest), rest
    keys = next(line for line in lines if "Ctrl+Q" in line)
    assert "quit" in keys  # the key and what it does, on one line


def test_legends_keep_each_entry_whole_and_the_map_names_visited_and_the_boss(content):
    from ptg.ui.widgets import legend, map_text
    from ptg.world import generate

    entries = [("@", "", "you"), ("ö", "", "a bird's nest"), ("o", "", "a knot hole"), ("!", "", "the Goblin")]
    packed = legend(entries, width=27).plain.split("\n")
    assert packed == ["@ you  ö a bird's nest", "o a knot hole  ! the Goblin"]
    assert legend(entries).plain.split("\n") == ["@ you", "ö a bird's nest", "o a knot hole", "! the Goblin"]

    state = generate(1, "T", content)
    first = state.room
    first.visited = True
    state.room_id = next(e.to for e in first.exits.values())
    state.room.visited = True
    boss = next(r for r in state.rooms if not (r.visited or r.fixture or r.monster or r.secret or r.shop))
    boss.is_boss, boss.told = True, True  # (on the map once you know of it)
    plain = map_text(state).plain
    assert "# visited" in plain and "B boss" in plain and "@ you" in plain
    assert "■ chest" not in plain or "■" in plain.split("\n@")[0]  # only marks that are on the map


async def test_the_campfire_fits_a_short_screen():
    """At 100x30 the Hall of Legends was squeezed to its totals line under a big fire, and a card whose name wrapped
    (Last Breath) lost its price; at 80x24 the buttons back down weren't there at all. Picking a card pushed its
    button in under it. Now the fire's smaller on a short screen, the legends keep some lines, a card is as tall as its
    name and price, and what a card does shows in a pane that keeps its size."""
    for size in ((100, 30), (80, 24)):
        app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            for i in range(5):
                run = app.profile.start_run(i, f"Hero {i}", ["ruins"])
                app.profile.finish_run(run, status="dead", floor=2, level=3, kills=4, gold=20, souls=30, turns=50,
                                       cause="a goblin", epitaph="Tried to pet a gelatinous cube.", epithet="the Brave",
                                       traits=[], perks=[])
            app.show_campfire()
            await pilot.pause(0.5)
            hub = app.screen
            assert hub.query_one("#campfire", Picture).art.pixels == SMALL, size
            assert hub.query_one("#legends-box").region.height >= 6, size
            descend = hub.query_one("#descend").region
            assert descend.height and descend.bottom <= size[1] - 1, size  # above the footer
            breath = next(c for c in hub.query(".unlock-card") if c.unlock.key == "last_breath")
            assert "150" in "\n".join(str(breath.render_line(y).text) for y in range(breath.size.height)), size
            pane = [hub.query_one(q).region for q in ("#unlock-pane", "#hub-tabs", "#unlock-detail")]
            await pilot.click(hub.query(".unlock-card").first())
            await pilot.pause(0.3)
            assert hub.query(".unlock-card").first().has_class("-picked")
            assert [hub.query_one(q).region for q in ("#unlock-pane", "#hub-tabs", "#unlock-detail")] == pane
            assert hub.query_one("#unlock-action").visible


async def test_look_says_how_the_room_is_now():
    """The Look panel showed the room as narrated when you walked in, forever: a fight long over, a door since
    opened, and its own Exits line after the narration's. Now what's said comes from the game as it is."""
    from conftest import put_monster

    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        state.room.description = "The Hobgoblin is here (east) and hostile. A fight begins. Exits: west (locked)."

        async def look() -> str:
            await pilot.press("f4")
            await pilot.pause(0.3)
            body = str(app.screen.query_one(".panel-box Static").render())
            await pilot.press("escape")
            await pilot.pause(0.2)
            return body

        put_monster(state, screen.game.content, key="goblin", hp=5)
        body = await look()
        assert "Goblin is here (hostile, 5/" in body and "A fight begins" not in body and body.count("Exits:") == 1
        state.room.monster = None
        state.room.items = ["war_pick"]
        body = await look()
        assert "is here" not in body and "Lying here: War Pick." in body and body.count("Exits:") == 1
        screen.action_lookup(f"room:{state.room_id}")
        await pilot.pause(0.3)
        card = str(app.screen.query_one("#info-text").render())
        assert "A fight begins" not in card and card.count("Exits:") == 1 and "Lying here: War Pick." in card


async def test_toasts_and_the_hud_keep_out_of_the_way():
    """Toasts stacked over the right of the choices and the arrow pad; now they sit at the top right. And on a
    100-column screen the status bar lost its end mid-word: now the least of it goes first."""
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(100, 30), notifications=True) as pilot:
        screen = await into_a_run(app, pilot)
        app.notify("Something happened.", title="A toast", timeout=10)
        await pilot.pause(0.3)
        toast = screen.query_one("Toast").region
        assert toast.y <= 2 and toast.right >= 98 and not toast.overlaps(screen.query_one("#choices").region)
        hud = str(screen.query_one("#hud").render())
        assert "Floor 1/4 · " in hud and "turn" not in hud and len(hud) <= 98


async def test_the_title_is_a_castle_in_a_storm_with_its_own_music(speakers):
    """The title's picture: every frame made ready before the storm starts (the rain's in each light, and several
    whole strikes), a strike that lights the castle up (the name flashing with it) with its thunder timed to the
    flash, and the title's music looping while it shows, fading out when a screen covers it."""
    from ptg.ui.storm import StormView

    app = PTGApp(Config(backend="offline", player_name="T"))
    async with app.run_test(size=(152, 43)) as pilot:
        await pilot.pause(0.3)
        title = app.screen
        assert isinstance(title, TitleScreen) and title.scene is not None
        assert title.query_one("#title-scene", StormView).frame and speakers.looping == "title_music"
        await app.workers.wait_for_complete()
        assert len(title.frames) == 4 * title.PHASES and len(title.strikes) == title.STRIKES
        title.next_strike = 0  # (now)
        lit = False
        for _ in range(20):
            await pilot.pause(0.05)
            lit = lit or title.query_one("#splash").has_class("lit")
        assert lit  # (the flash: the name lit with it)
        await pilot.pause(1.2)
        assert "thunder" in speakers.moments
        await pilot.press("s")  # (Settings: the music fades out)
        await pilot.pause(0.3)
        assert speakers.looping == ""


async def test_a_small_screen_has_the_title_without_the_picture():
    app = PTGApp(Config(backend="offline", player_name="T"))
    async with app.run_test(size=(80, 20)) as pilot:
        await pilot.pause(0.3)
        assert isinstance(app.screen, TitleScreen) and not app.screen.query_one("#title-scene").display
        assert app.screen.query_one("#new").region.bottom <= 20
