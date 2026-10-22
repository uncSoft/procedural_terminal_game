from textual.widgets import Static

from ptg.config import Config
from ptg.events import Event
from ptg.sprites import DEATH_FRAMES
from ptg.ui.app import PTGApp
from ptg.ui.dice import DiceScreen
from ptg.ui.game_screen import GameScreen
from ptg.ui.hub import EndScreen, HubScreen
from ptg.ui.panels import BestiaryScreen, CharacterScreen, InventoryScreen, LevelUpScreen, LookScreen
from ptg.ui.screens import IntroScreen, SetupScreen, TitleScreen
from ptg.ui.widgets import AnimatedSprite


async def settle(app, pilot, limit: float = 10.0) -> None:
    """Wait for the current turn to finish, rolling any dice and picking any perks along the way."""
    for _ in range(int(limit / 0.1)):
        await pilot.pause(0.1)
        if isinstance(app.screen, DiceScreen):
            await pilot.press("space")
            await pilot.pause(1.5)
            await pilot.press("enter")
        elif isinstance(app.screen, LevelUpScreen):
            await pilot.press("1")
        elif isinstance(app.screen, GameScreen) and not app.screen.busy:
            return


async def test_campfire_descent_panels_and_continue():
    app = PTGApp(Config(backend="offline", player_name="Tester"), seed=1)
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
        await pilot.press("escape")
        await pilot.press("escape")
        await pilot.pause(0.3)
        assert isinstance(app.screen, TitleScreen)
        await pilot.press("c")
        await settle(app, pilot)
        assert isinstance(app.screen, GameScreen) and app.screen.game.state.turn == turns


async def test_death_goes_to_the_tombstone_then_the_campfire():
    app = PTGApp(Config(backend="offline", player_name="Doomed"), seed=1)
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
    app = PTGApp(Config(backend="offline", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        game = screen.game
        played = []
        play = screen._play_scene

        async def spy(key, name, steps):
            played.append([pose for pose, _, _ in steps])
            await play(key, name, steps)
        screen._play_scene = spy

        from conftest import put_monster

        put_monster(game.state, game.content, key="hobgoblin")
        here = game.state.room_id
        await screen._fight_animations([Event("hit", ""), Event("monster_hit", "")], ("hobgoblin", "Hobgoblin"), here)
        game.state.room.monster = None  # and the next blow kills it
        await screen._fight_animations([Event("hit", "")], ("hobgoblin", "Hobgoblin"), here)
        assert played == [["idle"] * 4 + ["lunge", "lunge", "idle"], ["idle"] * 4 + ["death"] * DEATH_FRAMES]
        assert not screen.animating

        played.clear()
        await screen._fight_animations([Event("hit", "")], ("hobgoblin", "Hobgoblin"), here + 1)  # fled
        game.config.art = "ascii"
        await screen._fight_animations([Event("hit", "")], ("hobgoblin", "Hobgoblin"), here)
        assert played == [["idle"] * 4]  # ASCII art still flashes, but doesn't dissolve


async def test_fixtures_come_alive():
    app = PTGApp(Config(backend="offline", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        game = screen.game
        narration = screen.add_line("…", "narration")
        await screen._fixture_moment([Event("chest", "")], narration)
        chest = screen.query(".story-sprite").last()
        assert chest.key == "chest" and chest._timer is None  # played once, then rests open
        await screen._fixture_moment([Event("descend", "")], narration)
        await pilot.pause()
        assert [s.key for s in screen.query(AnimatedSprite)] == ["chest"]  # the stairs dissolved and went

        game.state.room.fixture, game.state.room.fixture_used = "shrine", False
        screen._arrival_sprite([Event("enter", "", data={"first": True})])
        await pilot.pause()
        shrine = screen.live_sprites[-1]
        assert shrine.key == "shrine" and shrine._timer is not None  # alive while you're here
        await pilot.press(*"sing a sea shanty", "enter")
        await settle(app, pilot)
        assert shrine._timer is None and not screen.live_sprites  # the next turn stills it

        game.config.art = "ascii"
        await screen._fixture_moment([Event("chest", "")], narration)
        assert len(screen.query(AnimatedSprite)) == 2  # no new sprite in ASCII mode
