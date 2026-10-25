"""The game screen in tabs (ui/tabs.py): which screen a game gets, the tabs and their pane, the numbering it shares
with the classic screen, and the pane's sums (the big map, the notes under it, everything the status bar shortens)."""

from rich.console import Console
from test_screen import walk_in
from test_ui import settle

from ptg import npcs, testrooms
from ptg.config import Config
from ptg.content import load_content
from ptg.game import Game
from ptg.ui import tabs
from ptg.ui.app import PTGApp
from ptg.ui.game_screen import GameScreen
from ptg.ui.panels import InventoryScreen, MapScreen
from ptg.ui.tabs import (
    TabsScreen,
    big_map,
    game_screen,
    map_notes,
    status_lines,
    steps_to,
)


def plain(renderable, width: int = 100) -> str:
    console = Console(width=width, record=True, file=open("/dev/null", "w"))  # noqa: SIM115
    console.print(renderable)
    return console.export_text()


def a_game(layout: str = "tabs", who: str = "lenny") -> Game:
    content = load_content()
    state = testrooms.build(content, who, "new", 0, seed=4)
    return Game(state, Config(backend="offline", layout=layout), None, content)


def test_a_big_enough_screen_gets_tabs_and_the_rest_the_classic_one(monkeypatch):
    monkeypatch.delenv("PTG_TOUCH", raising=False)
    assert type(game_screen(a_game(), True, 152, 43)) is TabsScreen
    assert type(game_screen(a_game(), True, 100, 43)) is GameScreen  # (too narrow)
    assert type(game_screen(a_game(), True, 152, 28)) is GameScreen  # (too short)
    assert type(game_screen(a_game("classic"), True, 200, 60)) is GameScreen  # (the player's choice)
    monkeypatch.setenv("PTG_TOUCH", "1")
    assert type(game_screen(a_game(), True, 200, 60)) is GameScreen  # (a finger: mobile comes later)


def test_the_big_map_names_the_rooms_youve_been_and_gives_up_when_the_floor_is_too_big():
    game = a_game()
    state = game.state
    drawn = big_map(state, 200, 60)
    assert drawn is not None and "@" in drawn.plain
    assert all(r.name.removeprefix("The ")[:6] in drawn.plain for r in state.rooms if r.visited)
    assert big_map(state, 5, 2) is None


def test_the_notes_under_the_map_say_the_goal_the_quests_and_the_key():
    game = a_game()
    state, content = game.state, game.content
    words = plain(map_notes(state, content))
    assert "GOAL" in words and "Find the stairs down" in words and "KEY" in words and "TIPS" in words
    stairs = next(r for r in state.rooms if r.fixture == "stairs")
    state.mapped_floor = state.floor  # (the floor's map in hand: the stairs are on it, and how far)
    words = plain(map_notes(state, content))
    assert stairs.name in words and ("from here" in words or "you're there" in words)
    assert "You have this floor's map" in words
    assert steps_to(state, state.room_id) == 0


def test_the_sheet_says_in_full_everything_the_status_bar_shortens():
    game = a_game()
    words = plain(status_lines(game.state, game.content))
    for label in ("Health", "Defense", "Fate", "Gold", "Souls", "Bombs", "Small keys", "Level", "Floor"):
        assert label in words, label


async def test_tabs_change_only_the_pane_and_pressed_again_open_the_panel_in_full():
    app = PTGApp(Config(backend="offline", player_name="T"), test_room=("lenny", "new", 0))
    async with app.run_test(size=(152, 43)) as pilot:
        screen = await walk_in(app, pilot)
        assert isinstance(screen, TabsScreen)
        assert screen.tab == "here"  # (someone's here)
        assert screen.query(".focus") and screen.things[0].id == f"monster:{npcs.LENNY}"
        stage, story = screen.query_one("#stage"), screen.query_one("#story")
        await pilot.press("f5")
        await pilot.pause(0.3)
        assert screen.tab == "map" and screen.query(".map-frame")
        assert screen.query_one("#stage") is stage and screen.query_one("#story") is story  # (nothing else rebuilt)
        await pilot.press("f5")  # (again: the map in full)
        await pilot.pause(0.3)
        assert isinstance(app.screen, MapScreen)
        await pilot.press("escape")
        await pilot.pause(0.3)
        for key, tab in (("f2", "pack"), ("f3", "sheet"), ("f7", "journal"), ("f6", "bestiary"), ("f4", "here")):
            await pilot.press(key)
            await pilot.pause(0.2)
            assert screen.tab == tab and screen.query_one("#pane").children, tab
        await pilot.press("f2")
        await pilot.pause(0.2)
        screen.action_expand()  # (the ⤢: this tab's panel, in full)
        await pilot.pause(0.3)
        assert isinstance(app.screen, InventoryScreen)


async def test_clicking_a_tab_brings_it_in():
    app = PTGApp(Config(backend="offline", player_name="T"), test_room=("lenny", "new", 0))
    async with app.run_test(size=(152, 43)) as pilot:
        screen = await walk_in(app, pilot)
        offset = len(" Here F4  ") + 2  # (the Map tab's first letters)
        await pilot.click("#tab-bar", offset=(offset, 0))
        await pilot.pause(0.3)
        assert screen.tab == "map" and app.screen is screen


async def test_buttons_are_numbered_first_and_the_choices_carry_on_one_to_a_line_without_the_ways_out():
    app = PTGApp(Config(backend="offline", player_name="T"), test_room=("lenny", "new", 0))
    async with app.run_test(size=(152, 43)) as pilot:
        screen = await walk_in(app, pilot)
        assert [a.id for a in screen.numbered[:len(screen.tile_verbs)]] == [a.id for a in screen.tile_verbs]
        assert not [a for a in screen.numbered if a.id.startswith("go:")]  # (the arrows have those)
        rows = list(screen.query("#choices .choice"))
        assert rows and rows[0].index == len(screen.tile_verbs) + 1
        lit = [d for d in tabs.ARROWS if not screen.query_one(f"#dpad-{d}").has_class("off")]
        assert lit  # (the way back, at least)
        before = screen.game.state.turn
        await pilot.press("1", "enter")  # (Lenny's first button)
        await settle(app, pilot)
        assert screen.game.state.turn > before or screen.query(".player-line")


async def test_a_thumbnail_brings_its_thing_into_the_frame():
    app = PTGApp(Config(backend="offline", player_name="T"), test_room=("lenny", "new", 0))
    async with app.run_test(size=(152, 43)) as pilot:
        screen = await walk_in(app, pilot)
        pictured = [t for t in screen.things if t.art and t.sprite]
        if len(pictured) < 2:
            return  # (nothing else to look at in this room)
        screen.action_focus_thing(pictured[1].id)
        await pilot.pause(0.3)
        frame = screen.query_one(".focus .focus-art")
        assert frame.key == pictured[1].sprite


async def test_settings_offer_the_game_screen_and_save_the_choice():
    from textual.widgets import Select

    from ptg.config import load_config
    from ptg.ui.screens import SetupScreen

    app = PTGApp(None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, SetupScreen)
        layout = app.screen.query_one("#layout", Select)
        assert layout.value == "tabs"  # (the default)
        layout.value = "classic"
        app.screen.action_save()
        await pilot.pause(0.3)
        assert load_config().layout == "classic"
