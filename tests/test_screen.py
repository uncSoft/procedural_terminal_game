"""The new game screen: a stage over a story of words, Here beside it or under it, the choices as a strip."""

from textual.widgets import Footer

from test_ui import into_a_run, settle, take_choice
from ptg import interactions, npcs, testrooms
from ptg.config import Config
from ptg.ui.app import PTGApp
from ptg.ui.game_screen import GameScreen
from ptg.ui.panels import InventoryScreen, LookScreen, MenuScreen, PickScreen
from ptg.ui.widgets import ChoiceItem, Picture


def shown(screen, selector: str) -> bool:
    widget = screen.query_one(selector)
    return widget.display and widget.region.width > 0


async def walk_in(app, pilot):
    """A test room's start, next door to someone: walked into."""
    await pilot.pause(0.5)
    await settle(app, pilot)
    screen = app.screen
    state = screen.game.state
    target = testrooms.target(state)
    direction = next(d for d, e in state.room.exits.items() if e.to == target.id)
    await take_choice(app, pilot, screen, f"go:{direction}")
    await pilot.pause(0.3)
    return screen


async def test_a_wide_screen_has_a_stage_here_beside_it_and_a_strip_of_choices():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=3)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        plan = screen.plan
        assert plan.two_columns and plan.stage_rows and not screen.has_class("one")
        assert shown(screen, "#stage") and shown(screen, "#here") and shown(screen, "#side")
        assert not shown(screen, "#here-strip") and not shown(screen, "#ways")
        stage, story = screen.query_one("#stage-box").region, screen.query_one("#story").region
        assert stage.y < story.y and stage.bottom <= story.y  # (the room over the words)
        assert story.height >= plan.story_rows
        assert len(screen.query("#choices .choice-line")) <= plan.choice_rows


async def test_a_narrow_screen_is_one_column_with_a_strip_a_ways_bar_and_a_short_status():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=3)
    async with app.run_test(size=(60, 34)) as pilot:
        screen = await into_a_run(app, pilot)
        assert not screen.plan.two_columns and screen.has_class("one") and screen.has_class("compact")
        assert not shown(screen, "#side") and shown(screen, "#here-strip") and shown(screen, "#ways")
        assert shown(screen, "#hud-short") and shown(screen, "#hud-menu") and not shown(screen, "#hud")
        assert not screen.query_one(Footer).display
        assert screen.query_one("#command").region.height == 1
        assert len(screen.query(".way")) == 4  # (the arrows, lit where there is a door)


async def test_the_screen_is_laid_out_again_when_the_window_changes():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=3)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        assert shown(screen, "#side") and not screen.has_class("one")
        await pilot.resize_terminal(60, 34)
        await pilot.pause(0.6)
        assert screen.has_class("one") and shown(screen, "#here-strip") and not shown(screen, "#side")
        await pilot.resize_terminal(130, 44)
        await pilot.pause(0.6)
        assert not screen.has_class("one") and shown(screen, "#here") and not shown(screen, "#here-strip")


async def test_the_story_holds_words_only():
    """No picture, loot card or sprite in the story any more: they are the stage's and Here's."""
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T", auto_roll=True), seed=3)
    async with app.run_test(size=(130, 46)) as pilot:
        screen = await into_a_run(app, pilot)
        state, story = screen.game.state, screen.query_one("#story")
        direction = next(iter(state.room.exits))
        state.rooms[state.room.exits[direction].to].items = ["healing_potion"]
        await take_choice(app, pilot, screen, f"go:{direction}")
        assert not story.query(Picture) and not story.query(".loot-card") and not story.query(".room-card")


async def test_a_characters_tile_has_buttons_numbered_first_and_typing_a_number_presses_one():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), test_room=("lenny", "new", 0))
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await walk_in(app, pilot)
        lenny = screen.things[0]
        assert lenny.id == f"monster:{npcs.LENNY}" and lenny.badge == "★" and lenny.verbs
        assert [a.id for a in screen.numbered[:len(screen.tile_verbs)]] == [a.id for a in screen.tile_verbs]
        strip = [c for c in screen.query(ChoiceItem)]
        assert strip and strip[0].index == len(screen.tile_verbs) + 1  # (the strip carries on from the buttons)
        first = screen.tile_verbs[0]
        before = screen.game.state.turn
        await pilot.press("1", "enter")
        await settle(app, pilot)
        said = [str(w.render()).strip() for w in screen.query(".player-line")]  # ("> Turn in his tooth · Lucky Lenny")
        assert any(line.startswith(f"> {first.label}") for line in said) or screen.game.state.turn > before


async def test_taking_something_from_its_tile_empties_its_place_and_says_where_it_went():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        state.room.monster, state.room.items = None, ["healing_potion"]
        screen.refresh_panels()
        assert any(t.id == "floor:healing_potion" for t in screen.things)
        screen.action_verb("take:healing_potion")
        await settle(app, pilot)
        assert "healing_potion" not in state.room.items and "healing_potion" in state.player.inventory
        assert not any(t.id == "floor:healing_potion" for t in screen.things)  # (Here is rebuilt: nothing stale)
        assert str(screen.query(".pickup-line").last().render()).strip() == "+ Healing Potion → pack"


async def test_a_foe_is_a_tile_with_its_health_and_attacking_it_is_a_button():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T", auto_roll=True), test_room=("swamp_bottoms", "new", 0))
    async with app.run_test(size=(130, 46)) as pilot:
        screen = await walk_in(app, pilot)
        foe = screen.things[0]
        monster = screen.game.state.room.monster
        assert foe.character and f"{monster.hp}/{monster.max_hp}" in foe.status
        assert any(a.id == "attack" for a in screen.tile_verbs)
        assert all(c.action_id != "attack" for c in screen.query(ChoiceItem))  # (on its tile only)
        hp = monster.hp
        screen.action_verb("attack")
        await settle(app, pilot)
        assert screen.game.state.turn > 0 and (not screen.game.state.room.monster or monster.hp <= hp)


async def test_a_picker_button_opens_a_list_of_what_could_be_used_on_the_foe():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), test_room=("swamp_bottoms", "new", 0))
    async with app.run_test(size=(130, 46)) as pilot:
        screen = await walk_in(app, pilot)
        screen.game.state.player.inventory += ["holy_water", "rubber_duck"]
        screen.refresh_panels()
        picker = next((a for a in screen.tile_verbs if interactions.is_picker(a.id)), None)
        assert picker is not None and picker.label == "Use…"
        screen.press(picker)
        await pilot.pause(0.3)
        assert isinstance(app.screen, PickScreen) and app.screen.options
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert isinstance(app.screen, GameScreen) and not screen.busy


async def test_typing_look_around_opens_the_look_panel_not_a_turn():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=3)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        turn = screen.game.state.turn
        await pilot.press(*"look around", "enter")
        await pilot.pause(0.4)
        assert isinstance(app.screen, LookScreen) and screen.game.state.turn == turn


async def test_the_menu_on_a_short_screen_opens_the_panels():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=3)
    async with app.run_test(size=(60, 34)) as pilot:
        screen = await into_a_run(app, pilot)
        screen.action_menu()
        await pilot.pause(0.3)
        assert isinstance(app.screen, MenuScreen)
        app.screen.action_choose("inventory")
        await pilot.pause(0.4)
        assert isinstance(app.screen, InventoryScreen)


async def test_the_stage_shows_the_room_and_a_click_on_it_looks_around():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=3)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        stage = screen.query_one("#stage")
        assert str(stage.border_title) == f"✦ {screen.game.state.room.name}"
        await pilot.click("#stage")
        await pilot.pause(0.4)
        assert isinstance(app.screen, LookScreen)


def test_what_changes_hands_with_a_character_is_a_line_each(content):
    from ptg.events import Event
    from ptg.ui.game_screen import exchange_lines

    events = [Event("give", "", data={"item": npcs.BAD_TOOTH, "how": "give", "from": "pack", "to": npcs.LENNY}),
              Event("take", "", data={"item": npcs.DIAPER, "how": "win", "from": npcs.SWOOGY, "to": "pack"}),
              Event("give", "", data={"gold": 30, "how": "give", "from": "purse", "to": npcs.SWOOGY}),
              Event("take", "", data={"item": "healing_potion", "how": "take", "from": "room", "to": "pack"})]
    lines = exchange_lines(events, content)
    assert lines == [f"→ given to {content.monster(npcs.LENNY).name}: {content.item(npcs.BAD_TOOTH).name}",
                     f"← a gift from {content.monster(npcs.SWOOGY).name}: {content.item(npcs.DIAPER).name}",
                     f"→ given to {content.monster(npcs.SWOOGY).name}: 30 gold"]


async def test_a_foes_use_button_stands_in_for_a_row_a_thing_in_the_strip():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), test_room=("swamp_bottoms", "new", 0))
    async with app.run_test(size=(130, 46)) as pilot:
        screen = await walk_in(app, pilot)
        screen.game.state.player.inventory += ["holy_water", "rubber_duck"]
        screen.refresh_panels()
        assert any(a.id.startswith("use:@") for a in screen.tile_verbs)
        assert any(a.id.startswith("throw:") for a in screen.game.choices())  # (the engine still lists them)
        assert not any(c.action_id.startswith(("throw:", "use:", "distract:")) for c in screen.query(ChoiceItem))
        assert any(c.action_id in ("dodge", "flee") for c in screen.query(ChoiceItem))  # (tactics stay in the strip)


async def test_many_things_to_use_are_one_chip_that_opens_them():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        state.room.monster = None
        state.player.hp = 10
        state.player.inventory += ["healing_potion", "stale_bread", "pickle"]
        screen.refresh_panels()
        await pilot.pause(0.3)
        assert len([a for a in screen.game.choices() if a.id.startswith("use:")]) > 1  # (a row each, in the engine)
        chips = [c for c in screen.query(ChoiceItem)]
        assert not any(c.action_id.startswith("use:") and "@" not in c.action_id for c in chips)
        [use] = [c for c in chips if c.action_id.startswith("use:@")]
        screen.press(next(a for a in screen.numbered if a.id == use.action_id))
        await pilot.pause(0.3)
        assert isinstance(app.screen, PickScreen) and len(app.screen.options) > 1
