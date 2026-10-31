"""The windows on a phone (docs/plans/mobile-view.md §3): held upright at the served page's 41x44, and on its side at
90x19, played with a finger. Each window fits the screen: nothing it needs runs off an edge."""

import random

import pytest
from conftest import put_monster
from test_ui import into_a_run

from ptg.config import Config
from ptg.dice import check
from ptg.ui import panels
from ptg.ui.app import PTGApp
from ptg.ui.dice import DiceScreen
from ptg.ui.hub import HubScreen
from ptg.ui.screens import COMPACT_TITLE, STACKED_TITLE, TitleScreen
from ptg.world import generate

UPRIGHT, SIDEWAYS = (41, 44), (90, 19)


@pytest.fixture(autouse=True)
def finger(monkeypatch):
    monkeypatch.setenv("PTG_TOUCH", "1")


def inside(app, widget) -> bool:
    """Whether a widget's drawn whole on the screen."""
    r, (w, h) = widget.region, app.size
    return r.width > 0 and r.x >= 0 and r.y >= 0 and r.right <= w and r.bottom <= h


def app_for(**kw) -> PTGApp:
    return PTGApp(Config(backend="offline", layout="grid", player_name="T", auto_roll=False), **kw)


async def test_the_title_stacks_its_name_and_its_menu_on_a_phone_held_upright():
    app = app_for()
    async with app.run_test(size=UPRIGHT) as pilot:
        await pilot.pause(0.4)
        title = app.screen
        assert isinstance(title, TitleScreen) and title.has_class("-phone")
        name = str(title.query_one("#splash").render())
        assert name.count("\n") == STACKED_TITLE.count("\n") and max(map(len, STACKED_TITLE.split("\n"))) <= 39
        assert all(inside(app, b) for b in title.query("#menu Button")), "a menu button runs off the screen"
    app = app_for()
    async with app.run_test(size=(110, 40)) as pilot:  # (room for it in a line: as it was)
        await pilot.pause(0.4)
        assert str(app.screen.query_one("#splash").render()).count("\n") == COMPACT_TITLE.count("\n")


async def test_the_campfire_is_one_column_on_a_phone_held_upright():
    app = app_for()
    async with app.run_test(size=UPRIGHT) as pilot:
        await pilot.pause(0.3)
        app.show_campfire()
        await pilot.pause(0.6)
        hub = app.screen
        assert isinstance(hub, HubScreen)
        right, left = hub.query_one("#hub-right"), hub.query_one("#hub-left")
        assert right.region.bottom <= left.region.y  # (the fire and the way down over the cards)
        assert inside(app, hub.query_one("#descend")) and inside(app, hub.query_one("#daily"))
        cards = [c for c in hub.query(".unlock-card") if c.region.width]
        assert len({c.region.x for c in cards}) == 2  # (two across)


async def test_the_dice_go_side_by_side_on_a_phone_on_its_side():
    app = app_for()
    async with app.run_test(size=SIDEWAYS) as pilot:
        await pilot.pause(0.3)
        roll = check(random.Random(1), "Attack", [("might", 3)], 12)
        app.push_screen(DiceScreen(roll, "Attack the goblin", 1, True))
        await pilot.pause(0.3)
        await pilot.press("space")
        await pilot.pause(2.0)
        dice = app.screen
        assert dice.side and dice.query_one("#dice-box").has_class("side")
        for part in ("#dice-faces", "#dice-target", "#dice-verdict", "#dice-prompt"):
            assert inside(app, dice.query_one(part)), f"{part} runs off the screen"


async def test_the_pack_and_the_shop_put_their_shelf_across_the_top_on_a_phone():
    seed = next(s for s in range(300) if any(r.shop for r in generate(s).rooms))
    app = app_for(seed=seed)
    async with app.run_test(size=UPRIGHT) as pilot:
        screen = await into_a_run(app, pilot)
        app.push_screen(screen.panel("inventory"))
        await pilot.pause(0.4)
        shelf, side = app.screen.query_one("#inv-shelf"), app.screen.query_one("#inv-side")
        assert shelf.region.bottom <= side.region.y and side.region.width >= 30  # (the picked one full width under)
        app.pop_screen()
        state = screen.game.state
        shop = next(r for r in state.rooms if r.shop)
        state.room_id, state.player.gold = shop.id, 300
        screen.refresh_panels()
        screen.open_shop()
        await pilot.pause(0.4)
        shelf, side = app.screen.query_one("#shop-shelf"), app.screen.query_one("#shop-side")
        assert shelf.region.bottom <= side.region.y and side.region.width >= 30
        assert inside(app, app.screen.query_one("#shop-buy"))


async def test_the_bestiary_lists_over_the_creature_on_a_phone_and_hides_an_empty_list(content):
    app = app_for(seed=1)
    async with app.run_test(size=UPRIGHT) as pilot:
        screen = await into_a_run(app, pilot)
        app.push_screen(screen.panel("bestiary"))
        await pilot.pause(0.3)
        assert not app.screen.query_one("#beast-list").display  # (nothing met yet)
        app.pop_screen()
        state = screen.game.state
        put_monster(state, content, "goblin")
        screen.game.profile.bump_beast("goblin", "seen")
        app.push_screen(screen.panel("bestiary"))
        await pilot.pause(0.3)
        listed, body = app.screen.query_one("#beast-list"), app.screen.query_one("#beast-body")
        assert listed.display and listed.region.bottom <= body.region.y and body.region.width >= 30


async def test_a_menu_has_rows_a_finger_can_hit_and_scrolls_where_they_dont_fit():
    for size in (UPRIGHT, SIDEWAYS):
        app = app_for(seed=1)
        async with app.run_test(size=size) as pilot:
            screen = await into_a_run(app, pilot)
            screen.action_menu()
            await pilot.pause(0.3)
            menu = app.screen
            assert isinstance(menu, panels.MenuScreen) and menu.has_class("touch")
            rows = list(menu.query(".menu-row"))
            assert all(r.region.height == 3 for r in rows if r.region.height)
            box = menu.query_one(".menu-box")
            assert inside(app, box)
            if size == SIDEWAYS:
                assert box.max_scroll_y > 0  # (the rest are a scroll away, not cut off)


async def test_the_sheet_the_floor_card_and_a_look_fit_a_phone_held_upright():
    app = app_for(seed=1)
    async with app.run_test(size=UPRIGHT) as pilot:
        screen = await into_a_run(app, pilot)
        game = screen.game
        app.push_screen(screen.panel("character"))
        await pilot.pause(0.3)
        from rich.table import Table

        rolls = app.screen.query_one(panels.Sheet)._rolls(game.state)
        assert len(rolls.renderables) > 3 and not any(isinstance(r, Table) for r in rolls.renderables)  # (lines)
        app.pop_screen()
        app.push_screen(panels.FloorScreen(2, 4, game.content.themes[game.state.theme], False))
        await pilot.pause(0.3)
        assert app.screen.shown is not None and app.screen.shown[2] > 0  # (its splash art, shrunk to fit)
        app.pop_screen()
        app.push_screen(screen.panel("look"))
        await pilot.pause(0.3)
        assert app.screen.picture() is not None
