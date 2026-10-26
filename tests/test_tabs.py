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
        assert screen.tab == "map" and screen.query(".map-holder")
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


async def test_the_footer_has_every_key_and_who_is_narrating():
    from textual.widgets import Footer

    shown = {b.key: b.description for b in TabsScreen.BINDINGS if b.show}
    assert shown == {"f1": "Help", "f2": "Pack", "f3": "Sheet", "f4": "Here", "f5": "Map", "f6": "Bestiary",
                     "f7": "Journal", "escape": "Title"}
    app = PTGApp(Config(backend="offline", player_name="T"), test_room=("lenny", "new", 0))
    async with app.run_test(size=(152, 43)) as pilot:
        screen = await walk_in(app, pilot)
        footer = screen.query_one(Footer)
        assert footer.display and footer.region.height == 1
        assert screen.query_one("#command").region.bottom <= footer.region.y  # (nothing under it)
        narrator = screen.query_one("#footer-narrator")
        assert str(narrator.render()) == "offline narrator" and narrator.region.y == footer.region.y


async def test_the_opening_is_told_once():
    """The tabs screen's own on_mount once called GameScreen's again, and the opening ran twice: two floor headers."""
    app = PTGApp(Config(backend="offline", player_name="T"), test_room=("lenny", "new", 0))
    async with app.run_test(size=(152, 43)) as pilot:
        await pilot.pause(0.5)
        await settle(app, pilot)
        assert len(app.screen.query(".floor-header")) == 1


async def test_the_tab_stays_where_you_put_it_from_room_to_room_and_a_fight_brings_here():
    app = PTGApp(Config(backend="offline", player_name="T"), test_room=("hobgoblin", "new", 0))
    async with app.run_test(size=(152, 43)) as pilot:
        await pilot.pause(0.5)
        await settle(app, pilot)
        screen = app.screen
        await pilot.press("f2")  # (the pack)
        await pilot.pause(0.2)
        assert screen.tab == "pack"
        screen = await walk_in(app, pilot)  # (into the hobgoblin's room: a fight)
        assert screen.tab == "here"
        await pilot.press("f5")
        await pilot.pause(0.2)
        screen.refresh_panels()  # (the same room, the same fight: the map stays)
        assert screen.tab == "map"


async def test_a_bare_here_is_filled_with_the_floor_and_what_happened_lately():
    app = PTGApp(Config(backend="offline", player_name="T"), test_room=("lenny", "new", 0))
    async with app.run_test(size=(152, 43)) as pilot:
        await pilot.pause(0.5)
        await settle(app, pilot)
        screen = app.screen
        screen.game.state.room.features = []
        screen.game.state.room.items = []
        screen.refresh_panels()
        await pilot.pause(0.3)
        words = " ".join(str(w.render()) for w in screen.query("#pane .pane-rule"))
        assert "FLOOR" in words or "LATELY" in words


async def test_the_decision_is_a_fixed_twelve_rows_and_notifications_land_in_the_docked_journal():
    app = PTGApp(Config(backend="offline", player_name="T"), test_room=("lenny", "new", 0))
    async with app.run_test(size=(152, 43), notifications=True) as pilot:
        screen = await walk_in(app, pilot)
        assert screen.query_one("#decide").region.height == tabs.DECIDE_ROWS
        assert screen.query_one("#command").region.height == 1  # (one line: it doesn't wrap)
        lately = screen.query_one("#lately")
        assert lately.display and screen.lately_lines >= tabs.LATELY_LEAST
        screen.notify("The Hobgoblin is weak to shiny.", title="Bestiary")
        await pilot.pause(0.2)
        assert "Bestiary: The Hobgoblin is weak to shiny." in str(lately.render())
        assert lately.has_class("noted")


def test_gold_bombs_and_keys_found_say_so_in_chips_with_how_many_you_have_now():
    from ptg.ui.game_screen import purse_chips

    before = {"gold": 15, "bombs": 1, "keys": 0}
    chips = purse_chips(before, {"gold": 21, "bombs": 2, "keys": 0})
    assert chips is not None and "+6 ¤ gold" in chips.plain and "(21)" in chips.plain and "+1 ● bomb" in chips.plain
    assert "key" not in chips.plain
    assert purse_chips(before, {"gold": 5, "bombs": 1, "keys": 0}) is None  # (spending isn't news)


async def test_gold_found_lights_its_counter():
    from ptg.ui.game_screen import purse

    app = PTGApp(Config(backend="offline", player_name="T"), test_room=("lenny", "new", 0))
    async with app.run_test(size=(152, 43)) as pilot:
        screen = await walk_in(app, pilot)
        before = purse(screen.game.state)
        screen.game.state.player.gold += 7
        await screen._purse_feedback(before)
        hud = screen.query_one("#hud")
        assert hud.lit == {"gold"} and "gold" in hud.at


async def test_settings_offer_apple_intelligence_through_apfel():
    """Apple's on-device model, served OpenAI-style by apfel on Ollama's port: told apart by its 127.0.0.1."""
    from textual.widgets import Input, Select

    from ptg.config import DEFAULT_URLS, load_config
    from ptg.ui.screens import SetupScreen

    app = PTGApp(None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, SetupScreen)
        app.screen.query_one("#backend", Select).value = "apple"
        await pilot.pause(0.3)
        assert app.screen.query_one("#url", Input).value == DEFAULT_URLS["apple"]
        app.screen.action_save()
        await pilot.pause(0.3)
        config = load_config()
        assert config.backend == "openai" and config.url == DEFAULT_URLS["apple"]


def test_the_room_picture_draws_whoever_is_here_in_either_idle_frame():
    from ptg.room_picture import picture_text

    game = a_game()
    state = game.state
    state.room_id = next(r.id for r in state.rooms if r.monster and r.monster.key == npcs.LENNY)
    first, second = (picture_text(state, game.content, 70, 32, frame=f) for f in (0, 1))
    assert (first.plain, first.spans) != (second.plain, second.spans)  # (the same room, Lenny breathing)


async def test_everything_pictured_animates_items_and_thumbnails_too_and_the_stage_breathes():
    """Only characters used to animate in Here, and never a thumbnail; the stage's room picture was a still."""
    from ptg.ui.widgets import Picture, PictureClock

    app = PTGApp(Config(backend="offline", player_name="T"), test_room=("lenny", "strong", 0))
    async with app.run_test(size=(152, 43)) as pilot:
        screen = await walk_in(app, pilot)
        await pilot.press("f2")  # (the pack: things, not characters)
        await pilot.pause(0.3)
        clock = PictureClock.of(app)
        pictures = list(screen.query("#pane").first().query(Picture))
        assert pictures and all(p in clock.pictures for p in pictures)
        assert screen.query(".thumb-art") and all(p in clock.pictures for p in screen.query(".thumb-art"))
        screen.stage_step()  # (its second frame, drawn off the screen's thread...)
        await app.workers.wait_for_complete()
        await pilot.pause(0.1)
        assert len(screen.stage_frames) == 2 and screen.stage_frames[1] is not None
        beat = screen.stage_beat
        screen.stage_step()  # (...then the swap)
        assert screen.stage_beat == beat + 1


async def test_a_move_made_while_the_narrator_talks_cuts_it_short_and_is_made(monkeypatch):
    """The screen used to wait for the whole narration (and the suggested trick after it) before the next move."""
    import time

    from test_narration import SlowLLM

    from ptg.ui import app as app_module

    llm = SlowLLM(pause=0.05)  # (a quick opening...)
    monkeypatch.setattr(app_module, "make_llm", lambda config: llm)
    app = PTGApp(Config(backend="openai", player_name="T"), test_room=("lenny", "new", 0))
    async with app.run_test(size=(152, 43)) as pilot:
        await settle(app, pilot, limit=15)
        screen = app.screen
        state = screen.game.state
        start = state.room_id
        way = next(d for d, e in state.room.exits.items() if not e.locked)
        back = {"north": "south", "south": "north", "east": "west", "west": "east"}[way]
        llm.pause = 2.0  # (...then a narration of six seconds, if it's let finish)
        screen.action_go(way)
        await pilot.pause(0.3)
        assert screen.busy and screen.narration_stop is not None  # (somewhere new: the narrator's talking)
        began = time.monotonic()
        screen.action_go(back)  # (on the way back already)
        for _ in range(60):  # (made as soon as the first move's done)
            await pilot.pause(0.1)
            if state.room_id == start and not screen.busy:
                break
        assert state.room_id == start and time.monotonic() - began < 4.0  # (well short of the six)


async def test_here_wears_a_dot_while_another_tab_shows_and_the_room_has_something():
    app = PTGApp(Config(backend="offline", player_name="T"), test_room=("lenny", "new", 0))
    async with app.run_test(size=(152, 43)) as pilot:
        screen = await walk_in(app, pilot)  # (Lenny's here)
        assert "●" not in screen.tab_text().plain  # (Here's showing: nothing to point at)
        await pilot.press("f5")
        await pilot.pause(0.3)
        assert screen.waiting_here() and "Here ●" in screen.tab_text().plain
        screen.things = []  # (an empty room)
        assert not screen.waiting_here() and "●" not in screen.tab_text().plain


async def test_a_room_on_the_map_you_can_get_back_to_is_a_click_away():
    app = PTGApp(Config(backend="offline", player_name="T"), test_room=("lenny", "strong", 0))
    async with app.run_test(size=(152, 43)) as pilot:
        await pilot.pause(0.5)
        await settle(app, pilot)
        state = app.screen.game.state
        start = state.room_id
        screen = await walk_in(app, pilot)  # (next door, to Lenny: calm)
        assert state.room_id != start
        drawn = big_map(state, 200, 60)
        clicks = {span.style.meta.get("@click") for span in drawn.spans if not isinstance(span.style, str)}
        assert f"screen.travel({start})" in clicks
        state.wandered[str(state.floor)] = 99  # (nothing on the way, this time)
        screen.action_travel(start)
        await settle(app, pilot)
        assert state.room_id == start
        assert "make your way back" in " ".join(str(w.render()) for w in screen.query("#story .narration"))


async def test_walking_into_one_that_holds_its_ground_puts_a_warning_in_the_story():
    app = PTGApp(Config(backend="offline", player_name="T"), test_room=("serpentis", "strong", 0))
    async with app.run_test(size=(152, 43)) as pilot:
        screen = await walk_in(app, pilot)
        said = " ".join(str(w.render()) for w in screen.query("#story .system-line"))
        assert "⚠ Serpentis won't be scared off" in said
