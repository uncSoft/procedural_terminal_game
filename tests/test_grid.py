from types import SimpleNamespace

import pytest
from conftest import put_monster
from test_ui import into_a_run, settle

from ptg import interactions
from ptg.config import Config
from ptg.events import Action
from ptg.ui.app import PTGApp
from ptg.ui.game_screen import GameScreen
from ptg.ui.grid import EXPLORE, FIGHT, BigButton, ChartScreen, GridScreen, chart, kind_of, share
from ptg.ui.here import things_here
from ptg.ui.tabs import TabsScreen, game_screen
from ptg.world import build_floor, generate

BOXES = ("#stage-box", "#story", "#decide", "#map", "#here", "#strip")
KEYS = {"north": "up", "south": "down", "west": "left", "east": "right"}


def grid_app(**config) -> PTGApp:
    return PTGApp(Config(backend="offline", layout="grid", player_name="T", **config), seed=1)


def regions(screen) -> dict:
    return {box: screen.query_one(box).region for box in BOXES}


def buttons(screen) -> dict[str, BigButton]:
    return {button.kind: button for button in screen.query(BigButton)}


def test_the_grid_is_a_layout_you_can_choose(monkeypatch):
    """Settings' "Grid", if the terminal's big enough and it's played with a mouse; else the classic screen."""
    grid = SimpleNamespace(config=Config(layout="grid"))
    assert isinstance(game_screen(grid, True, 160, 45), GridScreen)
    assert type(game_screen(grid, True, 100, 30)) is GameScreen  # too small for it
    assert isinstance(game_screen(SimpleNamespace(config=Config(layout="tabs")), True, 160, 45), TabsScreen)
    monkeypatch.setenv("PTG_TOUCH", "1")
    assert type(game_screen(grid, True, 160, 45)) is GameScreen  # played by touch


@pytest.mark.parametrize("size", [(110, 32), (120, 40), (160, 45), (200, 52), (260, 70)])
def test_the_screen_is_shared_out_from_its_size_alone(size):
    """The left column's boxes fill its height, the story never under its least, the decision its buttons, the rows
    under them and the command line; icons only on a tall screen, the compass's names only on a wide one."""
    width, height = size
    grid = share(width, height)
    assert (grid.stage + 2) + grid.story + grid.decide == height - 2
    assert grid.story >= 8 and grid.stage >= 4
    assert grid.side + grid.left == width
    assert grid.decide == 2 + grid.bar + grid.below + 1
    assert grid.tall == (height - 2 >= 44) and grid.bar == (7 if grid.tall else 3)


def test_actions_find_their_buttons(content):
    assert kind_of(Action("attack", "Attack the goblin"), content, True) == "attack"
    assert kind_of(Action("use:healing_potion", "Drink the Healing Potion"), content, True) == "heal"
    assert kind_of(Action("bomb", "Throw a bomb at the goblin"), content, True) == "throw"
    assert kind_of(Action("throw:holy_water", "Throw the Vial of Holy Water"), content, True) == "throw"
    assert kind_of(Action("flee", "Try to flee"), content, True) == "flee"
    assert kind_of(Action("search_room", "Search the room for secrets"), content, False) == "search"
    assert kind_of(Action("rest", "Rest a while"), content, False) == "rest"
    assert kind_of(Action("bomb:east", "Bomb the east wall"), content, False) == "bomb"
    assert kind_of(Action("equip:hand_axe", "Equip the Hand Axe"), content, False) == "gear"
    assert kind_of(Action("use:healing_potion", "Drink the Healing Potion"), content, False) == "heal"
    assert kind_of(Action("go:north", "Go north"), content, False) == ""  # (the compass's)
    assert kind_of(Action("suggest", "✦ Tap the walls"), content, False) == ""  # (a button under them)


def test_the_chart_draws_each_room_as_a_box_with_its_name(content):
    state = generate(1, content=content)
    state.floor = 3  # (the boss's floor: its door's locked)
    build_floor(state, content)
    for room in state.rooms:
        room.visited = True
    roomy = chart(state, 400, 120, roomy=True)
    assert roomy is not None
    plain = roomy.plain
    assert all(room.name in plain for room in state.rooms if not room.secret)
    assert "╭" in plain and "@" in plain
    assert "═" in plain or "║" in plain  # the boss's locked door, doubled
    foes = [r.monster.name for r in state.rooms if r.monster and r.monster.hostile and r.id != state.room_id]
    assert foes and all(name in plain for name in foes)  # (the full chart says who's where)
    compact = chart(state, 400, 120, roomy=False)
    assert compact is not None and len(compact.plain.splitlines()) < len(plain.splitlines())
    assert chart(state, 20, 5, roomy=False) is None  # (too small: the map falls back to its marks)


async def test_every_box_keeps_its_place_and_meets_the_one_beside_it():
    """The grid's boxes are sized from the screen alone: a fight changes what's in them, never them."""
    app = grid_app()
    async with app.run_test(size=(160, 45)) as pilot:
        screen = await into_a_run(app, pilot)
        assert isinstance(screen, GridScreen)
        before = regions(screen)
        assert before["#stage-box"].bottom == before["#map"].bottom  # the picture and the map, one band
        assert before["#story"].y == before["#here"].y
        assert before["#decide"].bottom == before["#strip"].bottom
        assert before["#stage-box"].x == before["#story"].x == before["#decide"].x == 0
        game = screen.game
        put_monster(game.state, game.content, key="goblin", hp=99, intent="heavy")
        screen.refresh_panels()
        await pilot.pause(0.3)
        assert regions(screen) == before


async def test_a_fight_has_its_six_buttons_and_the_foes_card():
    app = grid_app()
    async with app.run_test(size=(200, 52)) as pilot:
        screen = await into_a_run(app, pilot)
        game = screen.game
        game.state.player.hp = game.state.player.max_hp = 200
        put_monster(game.state, game.content, key="goblin", hp=99, intent="heavy")
        screen.refresh_panels()
        await pilot.pause(0.3)
        bar = buttons(screen)
        assert list(bar) == [kind for kind, _, _ in FIGHT]
        assert [str(b.border_title) for b in bar.values()] == ["1", "2", "3", "4", "5", "6"]
        assert bar["dodge"].look == "hot" and bar["attack"].look == "live"  # (a heavy blow's coming)
        assert screen.query_one("#decide").has_class("fight")
        assert screen.query(".duel") and screen.query_one(".duel-art").key == "goblin"  # its card, big, in Here
        turn = game.state.turn
        await pilot.press("1", "enter")  # Attack, by its number
        await settle(app, pilot)
        assert game.state.turn > turn
        assert any("Attack" in entry.text for entry in game.state.log if entry.kind == "player")


async def test_heal_with_several_things_opens_a_row_and_a_letter_picks_one():
    """No window over the picture: the things to heal with, under the buttons, a letter each."""
    app = grid_app()
    async with app.run_test(size=(160, 45)) as pilot:
        screen = await into_a_run(app, pilot)
        game = screen.game
        player = game.state.player
        player.inventory += ["healing_potion", "greater_healing_potion"]
        player.hp = player.max_hp - 15
        put_monster(game.state, game.content, key="goblin", hp=99)
        screen.refresh_panels()
        await pilot.pause(0.3)
        screen.action_bar("heal")
        await pilot.pause(0.3)
        assert isinstance(app.screen, GridScreen) and screen.tray and screen.tray[3] == "heal"
        assert buttons(screen)["heal"].look == "open"
        options = [a.id for a in screen.tray[2]]
        letter = chr(97 + options.index("use:healing_potion"))
        held = player.inventory.count("healing_potion")
        await pilot.press(letter, "enter")
        await settle(app, pilot)
        assert player.inventory.count("healing_potion") == held - 1 and screen.tray is None


async def test_a_picker_opens_its_row_not_a_window():
    app = grid_app()
    async with app.run_test(size=(160, 45)) as pilot:
        screen = await into_a_run(app, pilot)
        game = screen.game
        game.state.player.inventory += ["holy_water", "healing_potion"]
        put_monster(game.state, game.content, key="goblin", hp=99)
        screen.refresh_panels()
        foe = next(t for t in things_here(game.state, game.content) if t.kind == "monster")
        picker = next(v for v in foe.verbs if interactions.is_picker(v.id))
        screen.press(picker)
        await pilot.pause(0.3)
        assert isinstance(app.screen, GridScreen) and screen.tray and screen.tray[2]


async def test_out_of_a_fight_the_rooms_buttons_and_a_bomb_shows_its_wall_first():
    app = grid_app()
    async with app.run_test(size=(160, 45)) as pilot:
        screen = await into_a_run(app, pilot)
        game = screen.game
        game.state.player.bombs = 2
        screen.refresh_panels()
        await pilot.pause(0.3)
        assert list(buttons(screen)) == [kind for kind, _, _ in EXPLORE]
        assert buttons(screen)["gear"].look == "dead"  # (nothing to change into: its reason under it)
        walls = screen.groups["bomb"]
        assert walls
        screen.groups["bomb"] = walls[:1]  # even with one wall to bomb, its row opens first
        screen.action_bar("bomb")
        await pilot.pause(0.3)
        assert screen.tray and screen.tray[3] == "bomb" and game.state.player.bombs == 2


async def test_heres_things_wear_their_verbs_one_click_away():
    """Take is on the thing, numbered on from the six buttons, and one click takes it."""
    app = grid_app()
    async with app.run_test(size=(160, 45)) as pilot:
        screen = await into_a_run(app, pilot)
        game = screen.game
        game.state.room.items.append("healing_potion")
        screen.refresh_panels()
        await pilot.pause(0.3)
        take = next(a for a in screen.tile_verbs if a.id == "take:healing_potion")
        assert min(n for n, (what, _) in screen.slots.items() if what == "action") == 7
        assert ("action", take) in screen.slots.values()
        held = game.state.player.inventory.count("healing_potion")
        screen.action_verb(take.id)  # (its button, clicked)
        await settle(app, pilot)
        assert game.state.player.inventory.count("healing_potion") == held + 1


async def test_the_compass_and_the_arrow_keys_take_you_through_a_door():
    app = grid_app()
    async with app.run_test(size=(200, 52)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        assert len(screen.query(".compass-cell.way")) == len(state.room.exits)
        direction, exit_ = next((d, e) for d, e in state.room.exits.items()
                                if not e.locked and not (state.rooms[e.to].monster and state.rooms[e.to].monster.hostile))
        await pilot.press(KEYS[direction])
        await settle(app, pilot)
        assert state.room_id == exit_.to


async def test_the_map_panel_is_the_chart_and_a_room_clicked_is_where_you_go():
    app = grid_app()
    async with app.run_test(size=(200, 52)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        start = state.room_id
        direction = next(d for d, e in state.room.exits.items()
                         if not e.locked and not (state.rooms[e.to].monster and state.rooms[e.to].monster.hostile))
        await pilot.press(KEYS[direction])
        await settle(app, pilot)
        assert state.room_id != start
        screen.action_panel("map")
        await pilot.pause(0.5)
        panel = app.screen
        assert isinstance(panel, ChartScreen)
        drawn = panel.query_one("#chart").render()
        assert state.rooms[start].name in str(drawn) and "╭" in str(drawn)
        panel.action_travel(start)
        await settle(app, pilot)
        assert isinstance(app.screen, GridScreen) and state.room_id == start


async def test_with_ascii_art_the_buttons_are_words():
    app = grid_app(art="ascii")
    async with app.run_test(size=(200, 52)) as pilot:
        screen = await into_a_run(app, pilot)
        assert all(str(b.render()).strip() == {k: w for k, w, _ in EXPLORE}[b.kind] for b in buttons(screen).values())
