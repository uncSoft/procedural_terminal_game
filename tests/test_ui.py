from textual.widgets import Static

from ptg.config import Config
from ptg.ui.app import PTGApp
from ptg.ui.dice import DiceScreen
from ptg.ui.game_screen import GameScreen
from ptg.ui.hub import EndScreen, HubScreen
from ptg.ui.panels import BestiaryScreen, CharacterScreen, InventoryScreen, LevelUpScreen, LookScreen
from ptg.ui.screens import IntroScreen, SetupScreen, TitleScreen


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
