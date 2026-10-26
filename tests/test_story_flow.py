"""W10: the story column shows each turn from its start; the turn is kept by a marker, not a count of children."""

import asyncio

from test_ui import into_a_run, settle, take_choice
from ptg.config import Config
from ptg.events import Event
from ptg.game import Game
from ptg.rules import perform
from ptg.ui.app import PTGApp
from ptg.ui.game_screen import pickup_line
from ptg.world import generate


def chest_room_seed() -> int:
    return next(s for s in range(500) if any(not e.locked and generate(s).rooms[e.to].fixture == "chest"
                                             for e in generate(s).room.exits.values()))


def logged(app, state) -> list[str]:
    return [text for (text,) in app.profile.db.execute(
        "select text from turns where run_id = ? and turn = ? and kind = 'shown'", (state.run_id, state.turn))]


def in_view(story, widget) -> bool:
    top = story.scroll_offset.y
    return top <= widget.virtual_region.y < top + story.scrollable_content_region.height


async def walk_into_the_chest_room(app, pilot):
    screen = await into_a_run(app, pilot)
    state, story = screen.game.state, screen.query_one("#story")
    direction, way = next((d, e) for d, e in state.room.exits.items()
                          if not e.locked and state.rooms[e.to].fixture == "chest")
    state.rooms[way.to].monster, state.rooms[way.to].items = None, ["healing_potion", "war_pick"]
    await take_choice(app, pilot, screen, f"go:{direction}")
    return screen, state, story


async def test_using_the_fixture_keeps_the_command_in_the_turn_log():
    """Whatever the turn mounts or moves, its own '> ...' line is the first row in the log (run 44, turns 113 and 120,
    where a sprite moved down to the turn shifted every count of the story's children)."""
    app = PTGApp(Config(backend="offline", player_name="T", auto_roll=True), seed=chest_room_seed())
    async with app.run_test(size=(130, 46)) as pilot:
        screen, state, story = await walk_into_the_chest_room(app, pilot)
        ids = [a.id for a in screen.game.choices()]
        screen.run_turn(str(ids.index("chest_smash") + 1))
        await settle(app, pilot)  # (the roll's dice, and whatever the chest does)
        rows = logged(app, state)
        assert rows[0] == "> Smash the chest open"
        assert not any(row == "" for row in rows)  # (the marker is never a row of its own)


async def test_the_command_stays_in_view_on_a_first_visit():
    """A turn taller than a small story used to end scrolled to the narration, with the command gone (run 44, and the
    audit at 100x30 and 150x46). The room's picture is the stage's now, above the story, never scrolled away. (The
    classic screen's: the tabs screen puts it beside the story.)"""
    for size in [(100, 30), (150, 46)]:
        app = PTGApp(Config(backend="offline", player_name="T", auto_roll=True, layout="classic"),
                     seed=chest_room_seed())
        async with app.run_test(size=size) as pilot:
            screen, state, story = await walk_into_the_chest_room(app, pilot)
            await pilot.pause(0.5)
            command = [w for w in story.query(".player-line")][-1]
            assert in_view(story, command), size
            stage = screen.query_one("#stage-box")
            assert not stage.display or stage.region.y >= 0 and stage.region.bottom <= story.region.y, size


async def test_a_short_turn_follows_the_end_of_the_story():
    app = PTGApp(Config(backend="offline", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        story = screen.query_one("#story")
        for n in range(80):  # (the past: a story taller than the screen)
            screen.add_line(f"line {n}", "narration")
        screen._mark_turn()
        last = screen.add_line("> now", "player-line")
        await pilot.pause(0.5)
        assert story.max_scroll_y - story.scroll_y <= 1 and in_view(story, last)


async def test_a_new_floor_opens_at_its_top():
    app = PTGApp(Config(backend="offline", player_name="T", auto_roll=True), seed=1)
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await into_a_run(app, pilot)
        game, story = screen.game, screen.query_one("#story")
        stairs = next(r for r in game.state.rooms if r.fixture == "stairs")
        game.state.room_id, stairs.monster, stairs.visited = stairs.id, None, True
        screen.refresh_panels()
        await take_choice(app, pilot, screen, "descend")
        await pilot.pause(0.5)
        assert story.scroll_y == 0 and game.state.floor == 2


async def test_pageup_and_pagedown_read_back_through_the_story():
    app = PTGApp(Config(backend="offline", player_name="T"), seed=1)
    async with app.run_test(size=(100, 30)) as pilot:
        screen = await into_a_run(app, pilot)
        story = screen.query_one("#story")
        for n in range(80):
            screen.add_line(f"line {n}", "narration")
        screen._mark_turn()  # (a turn that fits: the story follows its end)
        screen.add_line("> now", "player-line")
        await pilot.pause(0.5)
        end = story.scroll_y
        assert end > 0
        await pilot.press("pageup")
        await pilot.pause(0.2)
        assert story.scroll_y < end
        await pilot.press("pagedown")
        await pilot.pause(0.2)
        assert story.scroll_y >= end - 1


async def test_nothing_is_taken_while_a_continued_run_waits_on_its_recap(monkeypatch):
    """With a real narrator the recap takes seconds; a turn taken meanwhile was logged twice, before the seam and
    after it (F65)."""
    app = PTGApp(Config(backend="offline", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        started = asyncio.Event()

        async def slow(self, stand_in: bool = True) -> str:
            started.set()
            await asyncio.sleep(0.6)
            return "You were in the thick of it."

        monkeypatch.setattr(Game, "recap", slow)
        screen.pick_up_again()
        await asyncio.wait_for(started.wait(), 5)
        assert screen.busy  # (Enter and the choices wait)
        for _ in range(40):
            await pilot.pause(0.1)
            if not screen.busy:
                break
        assert not screen.busy
        recap = [w for w in screen.query(".recap")]
        assert recap and "thick of it" in str(recap[0].render())


async def test_the_continued_history_says_what_the_badge_said(content, profile):
    """The log held 'vs 12 - fail' for a monster's hit, where live play showed 'HIT YOU' (F65)."""
    game = Game(generate(3), Config(backend="offline"), None, profile=profile)
    await game.opening(lambda _: None)
    await game.act("go north", lambda _: None)
    await game.act("attack", lambda _: None)
    rolls = [e.text for e in game.state.log if e.kind == "mechanic"]
    assert rolls and all(" - " not in roll for roll in rolls)
    assert any(word in roll for roll in rolls for word in ("HIT", "MISS", "CRITICAL", "FUMBLE"))


def test_a_pickup_is_a_line_saying_where_it_went(content):
    state = generate(3)
    state.room.monster = None
    state.room.items = ["healing_potion"]
    events = perform(state, content, "take:healing_potion")
    assert pickup_line(events, content) == "+ Healing Potion → pack"
    state.room.items = ["small_key"]
    assert pickup_line(perform(state, content, "take:small_key"), content) == "+ Small Key → keys"
    state.room.items = ["healing_potion", "small_key"]  # (a key lying there is yours at once, with the rest)
    assert pickup_line(perform(state, content, "take_all"), content) == "+ Healing Potion → pack   + Small Key → keys"
    assert pickup_line([Event("hit", "You hit it.")], content) is None
    assert pickup_line(events + [Event("hit", "You hit it.")], content) is None  # (a turn with more in it is told)
    assert pickup_line([], content) is None


async def test_clicking_something_up_shows_the_compact_line():
    app = PTGApp(Config(backend="offline", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        state.room.monster, state.room.items = None, ["healing_potion"]
        screen.refresh_panels()
        screen.run_turn("", action=next(a for a in screen.game.choices() if a.id == "take:healing_potion"))
        for _ in range(60):
            await pilot.pause(0.1)
            if not screen.busy:
                break
        line = screen.query(".pickup-line").last()
        assert str(line.render()).strip() == "+ Healing Potion → pack"
