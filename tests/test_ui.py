from textual.widgets import Static

from ptg.config import Config
from ptg.ui.app import GameScreen, IntroScreen, PTGApp, SetupScreen, TitleScreen


async def test_new_game_play_and_continue():
    app = PTGApp(Config(backend="offline", player_name="Tester"), seed=1)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, TitleScreen)
        await pilot.press("n")
        await pilot.pause(0.3)
        assert isinstance(app.screen, IntroScreen)
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert isinstance(app.screen, GameScreen)
        for command in ["1", "go west", "attack", "sing a sea shanty"]:
            await pilot.press(*command, "enter")
            await pilot.pause(0.2)
        story = app.screen.query_one("#story")
        assert len(story.query(Static)) > 6
        turns = app.screen.game.state.turn
        assert turns > 0
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert isinstance(app.screen, TitleScreen)
        await pilot.press("c")
        await pilot.pause(0.3)
        assert isinstance(app.screen, GameScreen) and app.screen.game.state.turn == turns


async def test_first_run_opens_settings():
    app = PTGApp(None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, SetupScreen)
