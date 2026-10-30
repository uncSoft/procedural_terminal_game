"""Each layout at the size it's played at, its key moments played through the way a player meets them: JT's grid in a
215x59 terminal, a tester's tabs (the default) in a 1440x900 browser (about 150x40), and classic, what a small screen
falls back to, at 100x30. The rest of the suite mostly plays classic at 130x44, with the dice rolled for it; a bug
of one layout's (the grid's map not redrawing as a door opened) gets past that. Dice rolled by hand, as JT does."""

import pytest
from conftest import put_monster
from textual.widgets import Static

from ptg.config import Config
from ptg.rules import available_actions
from ptg.ui.app import PTGApp
from ptg.ui.boss_intro import BossIntro
from ptg.ui.dice import DiceScreen
from ptg.ui.game_screen import GameScreen
from ptg.ui.grid import GridScreen
from ptg.ui.model_view import FoundScreen
from ptg.ui.panels import FloorScreen, InfoScreen, LevelUpScreen, ShopScreen
from ptg.ui.tabs import TabsScreen

LAYOUTS = [pytest.param("grid", (215, 59), GridScreen, id="grid-215x59"),
           pytest.param("tabs", (150, 40), TabsScreen, id="tabs-150x40"),
           pytest.param("classic", (100, 30), GameScreen, id="classic-100x30")]
ARROWS = {"north": "up", "south": "down", "east": "right", "west": "left"}


def played(layout: str, **kw) -> PTGApp:
    return PTGApp(Config(backend="offline", layout=layout, player_name="T", auto_roll=False), **kw)


async def play_out(app, pilot, screen, limit: float = 15.0) -> None:
    """The turn played out as a player would: the dice rolled and read, a floor's card read, a perk taken, a card
    about something new closed; till the screen's free again."""
    for _ in range(int(limit / 0.1)):
        await pilot.pause(0.1)
        if isinstance(app.screen, DiceScreen):
            await pilot.press("space")
            await pilot.pause(1.2)
            await pilot.press("enter")
        elif isinstance(app.screen, FloorScreen):
            await pilot.press("enter")
        elif isinstance(app.screen, LevelUpScreen):
            await pilot.press("1")
        elif isinstance(app.screen, FoundScreen | InfoScreen):
            await pilot.press("escape")
        elif app.screen is screen and not screen.busy:
            return
    raise AssertionError(f"the turn never finished: {type(app.screen).__name__} in front")


async def into_the_room(app, pilot):
    """A test room's opening played out: the game's screen, free."""
    for _ in range(100):
        await pilot.pause(0.1)
        if isinstance(app.screen, GameScreen):
            break
    screen = app.screen
    await play_out(app, pilot, screen)
    return screen


@pytest.mark.parametrize(("layout", "size", "kind"), LAYOUTS)
async def test_a_walk_a_fight_and_a_level_up(layout, size, kind):
    from test_ui import into_a_run

    app = played(layout, seed=1)
    async with app.run_test(size=size) as pilot:
        screen = await into_a_run(app, pilot)  # (from the campfire, down the stairs)
        await play_out(app, pilot, screen)
        assert type(screen) is kind
        state, content = screen.game.state, screen.game.content

        way = next(d for d, e in state.room.exits.items()
                   if not e.locked and not (state.rooms[e.to].monster and state.rooms[e.to].monster.hostile))
        ahead = state.room.exits[way].to
        await pilot.press(ARROWS[way])  # a step, by the arrow keys
        await play_out(app, pilot, screen)
        assert state.room_id == ahead and state.rooms[ahead].visited

        put_monster(state, content, key="goblin", hp=1)
        state.player.xp = state.player.next_level_xp() - 1  # (the goblin's XP levels you up)
        level = state.player.level
        screen.refresh_panels()
        for _ in range(8):  # (a miss or two, then it falls)
            attack = next(a for a in screen.game.choices() if a.id == "attack")
            screen.press(attack)
            await play_out(app, pilot, screen)
            if not state.in_combat:
                break
        assert not state.in_combat and state.status == "playing"
        assert state.player.level == level + 1 and len(state.player.perks) == 1 and not state.pending_perks
        assert screen.fight is None  # (the stage back to the room)


@pytest.mark.parametrize(("layout", "size", "kind"), LAYOUTS)
async def test_a_boss_comes_in_big_and_settles_onto_the_stage(layout, size, kind, monkeypatch):
    monkeypatch.setenv("PTG_BIG_INTRO", "1")
    app = played(layout, test_room=("goblin_king", "strong", 0))
    async with app.run_test(size=size) as pilot:
        screen = await into_the_room(app, pilot)
        assert type(screen) is kind
        state = screen.game.state
        epithet = screen.game.content.monster("goblin_king").epithet
        door = next(a for a in available_actions(state, screen.game.content) if a.hint == "boss")
        screen.press(door)
        called = False
        for _ in range(200):  # (played through, not skipped: the landing, the close-up, its name, the rise)
            await pilot.pause(0.1)
            if isinstance(app.screen, BossIntro):
                called = called or epithet in str(app.screen.query_one("#intro-art", Static).render())
            elif app.screen is screen and not screen.busy and state.in_combat:
                break
        assert called, "its name was never called out"
        assert app.screen is screen and state.in_combat and state.room.monster.key == "goblin_king"
        if screen.plan is not None and screen.plan.stage_rows:
            assert screen.fight is not None and screen.fight.monster.key == "goblin_king"


@pytest.mark.parametrize(("layout", "size", "kind"), LAYOUTS)
async def test_into_a_shop_and_buying_at_her_counter(layout, size, kind):
    app = played(layout, test_room=("shop", "new", 0))
    async with app.run_test(size=size) as pilot:
        screen = await into_the_room(app, pilot)
        assert type(screen) is kind
        state = screen.game.state
        way = next(d for d, e in state.room.exits.items() if state.rooms[e.to].shop)
        await pilot.press(ARROWS[way])  # (its door unlocked with the key the room gave, and in)
        await play_out(app, pilot, screen)
        assert state.room.shop is not None
        state.player.gold = 500
        screen.press(next(a for a in screen.game.choices() if a.id == "shop"))
        for _ in range(30):
            await pilot.pause(0.1)
            if isinstance(app.screen, ShopScreen):
                break
        shop = app.screen
        assert isinstance(shop, ShopScreen)
        price = state.room.shop.wares[0].price
        await pilot.press("enter")  # buy the first thing on the counter
        for _ in range(40):
            await pilot.pause(0.1)
            if not screen.busy and state.player.gold != 500:
                break
        assert state.player.gold == 500 - price and app.screen is shop
        await pilot.press("escape")
        await play_out(app, pilot, screen)
        assert app.screen is screen
