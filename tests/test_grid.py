from types import SimpleNamespace

import pytest
from conftest import put_monster
from test_ui import into_a_run, settle

from ptg import interactions
from ptg.config import Config
from ptg.events import Action
from ptg.ui.app import PTGApp
from ptg.ui.game_screen import GameScreen
from ptg.ui.grid import (ACT_MAX, ACT_MIN, BELOW, BESIDE, EXPLORE, FIGHT, SIDE_MAX, SIDE_MIN, STORY_LEAST,
                         BigButton, ChartScreen, GridScreen, ItemCard, chart, kind_of, share, way_name)
from ptg.ui.here import things_here
from ptg.ui.tabs import TabsScreen, game_screen
from ptg.world import build_floor, generate

BOXES = ("#stage-box", "#story-box", "#decide", "#map", "#here", "#strip")
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


@pytest.mark.parametrize("size", [(110, 32), (130, 40), (160, 45), (200, 52), (240, 70), (320, 90)])
def test_the_screen_is_shared_out_from_its_size_alone(size):
    """The right column a share of the width, within bounds; the picture across the rest. Wide, the decision beside
    the story, a share of their columns, the two as tall as the rows under the picture; narrower, under it, a fixed
    height (its frame, the buttons, a blank row and the rows under them), the story never under its least."""
    width, height = size
    grid = share(width, height)
    rows = height - 2
    assert grid.side + grid.left == width and SIDE_MIN <= grid.side <= SIDE_MAX and grid.stage >= 4
    if grid.left >= BESIDE:
        assert grid.beside and grid.story == grid.decide == grid.band == rows - (grid.stage + 2)
        assert ACT_MIN <= grid.left - grid.story_w <= ACT_MAX and grid.story_w >= 60
        assert grid.bar == (7 if grid.tall else 3) and grid.ways in (4, 7, 9)
    else:
        assert not grid.beside and (grid.stage + 2) + grid.story + grid.decide == rows
        assert grid.decide == 2 + grid.bar + 1 + BELOW[grid.tall] and grid.story >= STORY_LEAST


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


@pytest.mark.parametrize("size", [(200, 52), (130, 40)])
async def test_every_box_keeps_its_place_and_meets_the_one_beside_it(size):
    """The grid's boxes are sized from the screen alone: a fight changes what's in them, never them. The picture and
    the map one band; under it, the story and the decision beside it (or under it), Here beside them, the edges met."""
    app = grid_app()
    async with app.run_test(size=size) as pilot:
        screen = await into_a_run(app, pilot)
        assert isinstance(screen, GridScreen)
        before = regions(screen)
        assert before["#stage-box"].bottom == before["#map"].bottom
        assert before["#stage-box"].x == before["#story-box"].x == 0
        assert before["#story-box"].y == before["#here"].y
        assert before["#decide"].bottom == before["#strip"].bottom
        if screen.grid.beside:
            assert before["#decide"].y == before["#story-box"].y and before["#decide"].x == before["#story-box"].right
            assert before["#decide"].right == before["#stage-box"].right
        else:
            assert before["#decide"].y == before["#story-box"].bottom and before["#decide"].x == 0
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
        assert bar["dodge"].face.styles.background.a and not bar["dodge"].styles.background.a  # (its shade inside)
        assert screen.query_one("#decide").has_class("fight")
        assert screen.query(".duel") and screen.query_one(".duel-art").key == "goblin"  # its card, big, in Here
        turn = game.state.turn
        await pilot.press("1", "enter")  # Attack, by its number
        await settle(app, pilot)
        assert game.state.turn > turn
        assert any("Attack" in entry.text for entry in game.state.log if entry.kind == "player")


async def test_heal_with_several_things_shows_them_and_a_letter_picks_one():
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
        assert isinstance(app.screen, GridScreen) and screen.tray and screen.tray[2] == "heal"
        assert buttons(screen)["heal"].look == "open" and screen.offered == screen.tray[1]
        options = [a.id for a in screen.offered]
        letter = chr(97 + options.index("use:healing_potion"))
        held = player.inventory.count("healing_potion")
        await pilot.press(letter, "enter")
        await settle(app, pilot)
        assert player.inventory.count("healing_potion") == held - 1 and screen.tray is None


async def test_a_picker_shows_its_options_under_the_buttons_not_a_window():
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
        assert isinstance(app.screen, GridScreen) and screen.tray and screen.tray[1]
        assert screen.offered == screen.tray[1]


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
        screen.groups["bomb"] = walls[:1]  # even with one wall to bomb, its options show first
        screen.action_bar("bomb")
        await pilot.pause(0.3)
        assert screen.tray and screen.tray[2] == "bomb" and game.state.player.bombs == 2


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


async def test_the_map_panel_is_the_floor_on_parchment_and_a_room_clicked_is_where_you_go():
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
        assert isinstance(panel, ChartScreen) and "M A P" in str(panel.box.border_title)
        drawn = panel.query_one("#chart")
        plain = str(drawn.render())
        assert state.rooms[start].name in plain and "▀" in plain  # (drawn in pixels, its names in ink over them)
        assert not panel.query_one(".chart-head").display  # (the floor's name is on the parchment)
        spot = None
        for y in range(drawn.size.height):
            x = 0
            for segment in drawn.render_line(y):
                if spot is None and segment.style is not None and segment.style.meta.get("travel") == start:
                    spot = (x, y)
                x += segment.cell_length
        assert spot is not None
        await pilot.click(drawn, offset=spot)
        await settle(app, pilot)
        assert isinstance(app.screen, GridScreen) and state.room_id == start


async def test_with_ascii_art_the_buttons_are_words():
    app = grid_app(art="ascii")
    async with app.run_test(size=(200, 52)) as pilot:
        screen = await into_a_run(app, pilot)
        assert all(str(b.face.render()).strip() == {k: w for k, w, _ in EXPLORE}[b.kind] for b in buttons(screen).values())


@pytest.mark.parametrize("size", [(110, 32), (160, 45), (240, 70)])
async def test_the_command_line_is_at_the_foot_of_the_story(size):
    """What's typed is seen, under the story's newest lines, inside its frame."""
    app = grid_app()
    async with app.run_test(size=size) as pilot:
        screen = await into_a_run(app, pilot)
        box, command, story = screen.query_one("#story-box"), screen.query_one("#command"), screen.query_one("#story")
        assert box.content_region.contains_region(command.region) and story.region.bottom == command.region.y


async def test_a_hovered_button_shades_its_face_and_is_never_reversed():
    """Hovered, a big button takes a tint of its colour inside its frame (a shade under the frame shows outside the
    line), and nothing on it is reversed (a pixel icon reversed is a white block)."""
    app = grid_app()
    async with app.run_test(size=(200, 52), tooltips=True) as pilot:
        screen = await into_a_run(app, pilot)
        search = buttons(screen)["search"]
        await pilot.hover(search)
        await pilot.pause(0.3)
        assert search.has_class("-hover") and search.face.styles.background.a and not search.styles.background.a
        assert "reverse" not in str(search.styles.text_style) + str(search.face.styles.text_style)
        await pilot.hover("#story")
        await pilot.pause(0.3)
        assert not search.has_class("-hover")
        await pilot.hover(".compass-cell.middle")
        await pilot.pause(0.3)
        assert "reverse" not in str(screen.query_one(".compass-cell.middle").styles.text_style)


async def test_the_map_s_rooms_keep_their_looks_and_one_clicked_is_where_you_go():
    """A room you can get back to is a plain box on the side map, not a link (Textual's links are underlined and
    repainted, frame and all); clicked, you travel there."""
    app = grid_app()
    async with app.run_test(size=(200, 52)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        start = state.room_id
        direction = next(d for d, e in state.room.exits.items()
                         if not e.locked and not (state.rooms[e.to].monster and state.rooms[e.to].monster.hostile))
        await pilot.press(KEYS[direction])
        await settle(app, pilot)
        drawn = screen.query_one("#map-art")
        spot = None
        for y in range(drawn.size.height):
            x = 0
            for segment in drawn.render_line(y):
                style = segment.style
                if style is not None:
                    assert not style.underline
                    if spot is None and style.meta.get("travel") == start and segment.text.strip():
                        spot = (x, y)
                x += segment.cell_length
        assert spot is not None
        await pilot.click(drawn, offset=spot)
        await settle(app, pilot)
        assert state.room_id == start


async def test_a_story_line_laid_out_too_short_is_laid_out_again():
    """A story line that kept a height from before all its words came (now and then one does: its end is lost under
    the next line) measures itself afresh and is laid out again."""
    app = grid_app()
    async with app.run_test(size=(160, 45)) as pilot:
        screen = await into_a_run(app, pilot)
        line = screen.add_line("A short line.", "narration")
        await pilot.pause(0.3)
        assert line.size.height == 1
        line.update("A much longer line, " * 30, layout=False)  # (its words in, no layout asked for)
        await pilot.pause(0.3)
        assert line.size.height > 1


def test_the_compass_names_a_fixture_as_the_map_does_and_dead_buttons_say_why(content):
    state = generate(1, content=content)
    stairs = next(r for r in state.rooms if r.fixture == "stairs")
    beside, direction = next((r, d) for r in state.rooms for d, e in r.exits.items()
                             if e.to == stairs.id and not e.locked)
    state.room_id = beside.id
    assert way_name(state, direction)[0] == "stairs down"  # (not "a stairs")


async def test_search_and_rest_say_why_they_cant_be_used():
    app = grid_app()
    async with app.run_test(size=(200, 52)) as pilot:  # (wide enough for the notes under the buttons)
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        state.room.room_searched = True
        state.player.hp = state.player.max_hp
        screen.refresh_panels()
        await pilot.pause(0.3)
        bar = buttons(screen)
        assert bar["search"].border_subtitle == "searched" and bar["rest"].border_subtitle == "not hurt"


async def test_a_wide_screen_gives_the_right_column_more_and_the_story_a_reading_width():
    assert share(320, 90).side > 64 and share(240, 70).side > 64  # (it was held at 64)
    app = grid_app()
    async with app.run_test(size=(240, 70)) as pilot:
        screen = await into_a_run(app, pilot)
        story = screen.query_one("#story")
        lines = [line for line in story.children if line.size.width]
        assert lines and all(line.size.width <= GridScreen.STORY_WIDTH for line in lines)
        left = min(line.region.x for line in lines) - story.region.x
        right = story.region.right - max(line.region.right for line in lines)
        assert abs(left - right) <= 4  # (a column down its middle)


async def test_here_is_in_sections_with_lately_in_the_rows_left():
    """Who's here, the things (a picture each), what there is to search, a heading each; a spent chest a line; then
    the journal's last lines, as many as the rows left (at most ten), fewer as things take the rows."""
    app = grid_app()
    async with app.run_test(size=(240, 70)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        room = state.room
        state.journal += [f"Something happened, the {n}th thing." for n in range(14)]
        room.fixture, room.fixture_used = "chest", True
        screen.refresh_panels()
        await pilot.pause(0.5)
        here = screen.query_one("#here")
        heads = [str(h.render()).split()[0] for h in here.query(".here-head")]
        assert heads[-1] == "LATELY" and len(str(here.query_one(".lately").render()).splitlines()) == 10
        spent = next(t for t in here.query("Tile") if t.thing.id.startswith("fixture:"))
        assert spent.form == "chip" and "spent" in spent.thing.name
        room.items += ["healing_potion", "hard_hat", "holy_water", "bomb_fairy"]
        screen.refresh_panels()
        await pilot.pause(0.5)
        heads = [str(h.render()).split()[0] for h in here.query(".here-head")]
        assert heads[0] == "THINGS" and "TO" in heads
        lately = here.query_one("#lately")
        assert not here.query_one("#here-lately").display or len(str(lately.render()).splitlines()) < 10  # (the
        # things took its rows)


def test_the_small_map_gives_a_long_name_a_second_line_and_the_full_one_grows(content):
    state = generate(1, content=content)
    rooms = [r for r in state.rooms if not r.secret]
    for room in rooms:
        room.visited = True
    names = [r.name for r in rooms]
    across = max(r.x for r in rooms) - min(r.x for r in rooms) + 1
    width = across * (9 + 4) + (across - 1) * 2  # (nine columns a name: too few for most on one line)
    drawn = chart(state, width, 100, roomy=False)
    assert drawn is not None and "…" not in drawn.plain
    assert all(word in drawn.plain for name in names for word in name.split())
    big, small = chart(state, 400, 120, roomy=True), chart(state, 100, 30, roomy=True)
    assert big is not None and small is not None
    assert len(big.plain.splitlines()) > len(small.plain.splitlines())
    assert max(map(len, big.plain.splitlines())) > max(map(len, small.plain.splitlines()))


async def test_a_quest_too_long_for_the_map_is_cut_short_not_lost(monkeypatch):
    from ptg import npcs
    long = "Lucky Lenny lost his bad tooth, and wants help finding it somewhere on this floor, and soon"
    monkeypatch.setattr(npcs, "quest_log", lambda state, content: [("lenny", long, True)])
    app = grid_app()
    async with app.run_test(size=(160, 45)) as pilot:
        screen = await into_a_run(app, pilot)
        screen.map_drawn = None
        screen.draw_map()
        await pilot.pause(0.3)
        notes = screen.query_one("#map-notes")
        lines = str(notes.render()).splitlines()
        assert len(lines) == notes.size.height and lines[-1].endswith("…")
        assert all(len(line) <= notes.size.width for line in lines)


async def test_on_a_wide_screen_compass_names_and_button_notes_are_whole():
    app = grid_app()
    async with app.run_test(size=(240, 70)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        stairs = next(r for r in state.rooms if r.fixture == "stairs")
        beside = next(r for r in state.rooms for e in r.exits.values() if e.to == stairs.id and not e.locked)
        state.room_id, beside.visited = beside.id, True
        for exit_ in beside.exits.values():
            state.rooms[exit_.to].visited = state.rooms[exit_.to].visited or exit_.to != stairs.id
        state.player.inventory = ["healing_potion"]
        state.player.hp -= 10
        screen.refresh_panels()
        await pilot.pause(0.5)
        ways = [str(cell.render()) for cell in screen.query(".compass-cell.way")]
        assert any("stairs down" in way for way in ways) and not any("…" in way for way in ways)
        assert buttons(screen)["heal"].border_subtitle == "Healing Potion"


async def test_the_compass_cells_never_move_or_change_size():
    """Five cells, north, west, you, east and south, in the same places and the same sizes in every room, whatever
    its ways out: a wall is faint, in its place, and only a way out can be clicked."""
    app = grid_app()
    async with app.run_test(size=(240, 70)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state

        def cells() -> list:
            return [(c.region, c.has_class("way")) for c in screen.query(".compass-cell") if not c.has_class("blank")]

        before = cells()
        assert len(before) == 5 and sum(way for _, way in before) == len(state.room.exits)
        direction = next(d for d, e in state.room.exits.items()
                         if not e.locked and not (state.rooms[e.to].monster and state.rooms[e.to].monster.hostile))
        await pilot.press(KEYS[direction])
        await settle(app, pilot)
        after = cells()
        assert [region for region, _ in after] == [region for region, _ in before]
        assert sum(way for _, way in after) == len(state.room.exits)


async def test_your_things_are_cards_under_the_buttons_lit_when_theres_something_to_do_with_them():
    """Out of a fight, under the compass: what you carry, a card each, its picture and words; one you can use now
    lit, with its letter (typed, it's done), one you can't dim, with why."""
    app = grid_app()
    async with app.run_test(size=(240, 70)) as pilot:
        screen = await into_a_run(app, pilot)
        player = screen.game.state.player
        player.inventory = ["healing_potion"]
        player.hp = player.max_hp
        screen.refresh_panels()
        await pilot.pause(0.5)
        card = screen.query_one(ItemCard)
        assert card.action is None and card.has_class("idle") and "full HP" in str(card.tooltip)
        player.hp -= 10
        screen.refresh_panels()
        await pilot.pause(0.5)
        card = screen.query_one(ItemCard)
        assert card.action is not None and card.action.id == "use:healing_potion" and screen.offered == [card.action]
        await pilot.press("a", "enter")
        await settle(app, pilot)
        assert "healing_potion" not in player.inventory


async def test_in_a_fight_your_things_take_the_compass_place_and_say_what_its_weak_to():
    app = grid_app()
    async with app.run_test(size=(240, 70)) as pilot:
        screen = await into_a_run(app, pilot)
        game = screen.game
        game.state.player.bombs = 1
        put_monster(game.state, game.content, key="tallow_saint", hp=99)
        screen.refresh_panels()
        await pilot.pause(0.5)
        assert not screen.query_one("#compass").display
        cards = {card.action.id: card for card in screen.query(ItemCard) if card.action}
        assert "bomb" in cards and "weak to fire" in str(cards["bomb"].query(".card-words").first().render())


async def test_heal_lights_up_when_youre_low():
    app = grid_app()
    async with app.run_test(size=(200, 52)) as pilot:
        screen = await into_a_run(app, pilot)
        player = screen.game.state.player
        player.inventory = ["healing_potion"]
        player.hp = player.max_hp // 3
        screen.refresh_panels()
        await pilot.pause(0.5)
        heal = buttons(screen)["heal"]
        assert heal.look == "hot" and heal.border_subtitle == "low HP!"


async def test_the_journal_is_written_on_parchment_and_the_panels_have_their_names_spaced_out():
    app = grid_app()
    async with app.run_test(size=(200, 52)) as pilot:
        screen = await into_a_run(app, pilot)
        await pilot.press("f7")
        await pilot.pause(0.5)
        box = app.screen.box
        assert box.has_class("parchment") and str(box.border_title).startswith("✦ J O U R N A L ✦")
        await pilot.press("f2")
        await pilot.pause(0.5)
        assert str(app.screen.box.border_title).startswith("✦ I N V E N T O R Y ✦")


async def test_a_room_you_can_travel_to_lights_up_under_the_mouse():
    """On the side map and on the parchment: hovered, a room you can get back to is drawn in gold, so it's plain
    that it's a click away."""
    app = grid_app()
    async with app.run_test(size=(200, 52)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        start = state.room_id
        direction = next(d for d, e in state.room.exits.items()
                         if not e.locked and not (state.rooms[e.to].monster and state.rooms[e.to].monster.hostile))
        await pilot.press(KEYS[direction])
        await settle(app, pilot)

        def spot(line) -> tuple[int, int]:
            for y in range(line.size.height):
                x = 0
                for segment in line.render_line(y):
                    if segment.style is not None and segment.style.meta.get("travel") == start:
                        return x, y
                    x += segment.cell_length
            raise AssertionError("no room to travel to")

        def colours(line) -> set[str]:
            return {str(seg.style.color.triplet.hex) for y in range(line.size.height) for seg in line.render_line(y)
                    if seg.style is not None and seg.style.meta.get("travel") == start and seg.style.color
                    and seg.style.color.triplet}

        side = screen.query_one("#map-art")
        assert "#ffd166" not in colours(side)
        await pilot.hover(side, offset=spot(side))
        await pilot.pause(0.3)
        assert screen.map_hover == start and "#ffd166" in colours(side)
        screen.action_panel("map")
        await pilot.pause(0.5)
        chart = app.screen.query_one("#chart")
        await pilot.hover(chart, offset=spot(chart))
        await pilot.pause(0.3)
        assert app.screen.hover == start and "#feae34" in colours(chart)


async def test_in_a_fight_the_last_turn_is_called_out_under_the_foe():
    """How it went, hits, misses and damage, in a line a roll under the foe's card, where you're looking; and in the
    story the badge and the damage lead each roll's line, the sum after them."""
    app = grid_app()
    async with app.run_test(size=(240, 70)) as pilot:
        screen = await into_a_run(app, pilot)
        game = screen.game
        game.state.player.hp = game.state.player.max_hp = 200
        put_monster(game.state, game.content, key="goblin", hp=200)
        screen.refresh_panels()
        await pilot.pause(0.3)
        await pilot.press("1", "enter")
        await settle(app, pilot)
        await pilot.pause(0.5)
        last = str(screen.query_one(".here-last").render())
        assert last.startswith("LAST TURN") and ("HIT" in last or "MISS" in last)
        line = next(w for w in screen.query("#story .mechanic") if "⚄" in str(w.render()))
        words = str(line.render()).strip()
        assert words.index("⚄") > max(words.find("HIT"), words.find("MISS"))  # (how it went before the sum)


def test_a_rolls_badge_keeps_its_colour_to_itself():
    """The damage after a roll's badge is in its own colour, on the screen's dark: not on the badge's colour too."""
    from ptg.dice import Roll
    from ptg.events import Event
    from ptg.ui.widgets import roll_headline
    hit = Event("hit", "", dice=Roll("attack", "player", [15], 15, dc=12, success=True, damage=[("1d6", 6)]))
    text = roll_headline(hit)
    damage = text.plain.index("→")
    assert not text.style and all(span.end <= damage for span in text.spans if "on " in str(span.style))


def test_every_cell_of_a_rooms_box_on_the_map_is_that_room(content):
    """Where a passage met a room's wall, the cell was nobody's, and a click there did nothing ("finicky", 10-28)."""
    from rich.console import Console

    state = generate(1)
    for room in state.rooms:
        room.visited = True
    text = chart(state, 60, 30, False)
    console = Console()
    joints = [i for i, ch in enumerate(text.plain) if ch in "├┤┬┴"]
    assert joints and all("room" in text.get_style_at_offset(console, i).meta for i in joints)


async def test_a_move_made_mid_turn_waits_for_the_turn_and_a_room_with_no_way_says_why(monkeypatch):
    """A click while a turn's animations played (a fight coming in, its spoils) was lost unless the narrator was
    talking: now it's made once the turn's done. The map's rooms come back to life when a fight ends where you
    stand, and one there's no way to says why."""
    from conftest import put_monster

    app = grid_app()
    async with app.run_test(size=(160, 48)) as pilot:
        screen = await into_a_run(app, pilot)
        state, content = screen.game.state, screen.game.content
        start = state.room_id
        direction = next(d for d, e in state.room.exits.items()
                         if not e.locked and not (state.rooms[e.to].monster and state.rooms[e.to].monster.hostile))
        await pilot.press(KEYS[direction])
        await settle(app, pilot)

        def travels(line) -> bool:
            return any(seg.style is not None and "travel" in seg.style.meta
                       for y in range(line.size.height) for seg in line.render_line(y))

        side = screen.query_one("#map-art")
        put_monster(state, content, key="goblin")
        screen.refresh_panels()
        await pilot.pause(0.3)
        assert not travels(side)  # (no travelling out of a fight)
        state.room.monster = None
        screen.refresh_panels()
        await pilot.pause(0.3)
        assert travels(side)

        screen.busy = True  # (mid-turn, the narrator quiet: an animation playing)
        screen.action_travel(start)
        assert screen.queued is not None and not screen.later(lambda: None)  # (the first move counts)
        screen.busy = False
        queued, screen.queued = screen.queued, None
        queued()
        await settle(app, pilot)
        assert state.room_id == start

        said = []
        monkeypatch.setattr(screen, "notify", lambda message, **kw: said.append(message))
        far = next(r.id for r in state.rooms if not r.visited)
        screen.why_not_travel(far)
        screen.why_not_travel(state.room_id)
        assert said == ["You haven't been in there yet.", "You're here."]


async def test_an_arrow_always_answers_and_a_perk_left_waiting_comes_back_with_it(monkeypatch):
    """The arrows could stop working, the map with them: the perk cards could be put off, and while the perks waited
    as the choices an arrow did nothing at all. The cards can't be put off now, but a run saved while they could be
    still has perks waiting: an arrow or a room on the map brings the cards back, and goes once one's taken. Any other
    arrow that can't go says why, and ↑ still goes with words left typed."""
    from ptg.rules import check_level
    from ptg.ui.panels import LevelUpScreen

    app = grid_app()
    async with app.run_test(size=(160, 48)) as pilot:
        screen = await into_a_run(app, pilot)
        state, content = screen.game.state, screen.game.content
        said = []
        monkeypatch.setattr(screen, "notify", lambda message, **kw: said.append(message))
        wall = next(d for d in KEYS if d not in state.room.exits)
        await pilot.press(KEYS[wall])
        await settle(app, pilot)
        assert said == [f"There's no way {wall} from here."]

        async def cards() -> LevelUpScreen:
            for _ in range(50):
                await pilot.pause(0.1)
                if isinstance(app.screen, LevelUpScreen):
                    break
            assert isinstance(app.screen, LevelUpScreen)
            return app.screen

        direction = next(d for d, e in state.room.exits.items()
                         if not e.locked and not (state.rooms[e.to].monster and state.rooms[e.to].monster.hostile))
        start, ahead = state.room_id, state.room.exits[direction].to
        state.player.xp = state.player.next_level_xp()
        check_level(state, content)  # (the perks waiting, with no cards: as a run saved with them put off)
        screen.refresh_panels()
        await pilot.press(KEYS[direction])
        await cards()
        assert state.room_id == start
        await pilot.press("1", "enter")
        await settle(app, pilot)
        assert len(state.player.perks) == 1 and not state.pending_perks and state.room_id == ahead
        assert not screen.busy and screen.queued is None

        state.player.xp = state.player.next_level_xp()
        check_level(state, content)
        screen.refresh_panels()
        screen.why_not_travel(start)  # the map's the same
        await cards()
        await pilot.press("2", "2")  # (the same card again takes it)
        await settle(app, pilot)
        assert len(state.player.perks) == 2 and state.room_id == start

        screen.query_one("#command").value = "hum"
        north_or_south = next((d for d in ("north", "south") if d in state.room.exits), None)
        await pilot.press(KEYS[north_or_south or "north"])
        await settle(app, pilot)
        if north_or_south:
            assert state.room_id != start and screen.query_one("#command").value == "hum"

        put_monster(state, content, key="goblin")
        screen.refresh_panels()
        screen.query_one("#command").value = ""
        said.clear()
        screen.action_go(next(iter(state.room.exits)))
        assert said and said[0].startswith("Not with the") and "flee" in said[0]
