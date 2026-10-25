"""The debug screen (F12): everything at a glance, sounds to play, and the model check inside the game."""

import pytest
from rich.console import Console
from textual.widgets import DataTable, ProgressBar, Select, TabbedContent, Tree

from ptg import sound
from ptg.config import Config
from ptg.content import load_content
from ptg.llm import check
from ptg.llm.base import log_exchange
from ptg.llm.openai_compat import OpenAICompatLLM
from ptg.story import load_library
from ptg.ui import debug
from ptg.ui.app import PTGApp
from ptg.ui.debug import DebugScreen


@pytest.fixture(autouse=True)
def pretend_server(monkeypatch):
    """The Models tab asks the server what it has: answer for it, so no test talks to a real one."""
    async def catalog(self):
        return [("pretend-model", True), ("other-model", False)]

    monkeypatch.setattr(OpenAICompatLLM, "catalog", catalog)


def plain(renderable) -> str:
    console = Console(width=120, record=True)
    console.print(renderable)
    return console.export_text()


def tab(app, kind):
    return app.screen.query_one(kind)


async def until(pilot, check, limit: float = 3.0) -> bool:
    """Wait for something to come true (a busy test run can be slow to handle a click)."""
    for _ in range(int(limit / 0.05)):
        if check():
            return True
        await pilot.pause(0.05)
    return check()


async def test_f12_opens_every_tab_and_closes_again():
    content = load_content()
    app = PTGApp(Config(backend="offline", layout="classic"))
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        await pilot.press("f12")
        await pilot.pause(0.3)
        assert isinstance(app.screen, DebugScreen)
        for n, key in zip("1234567890", debug.TABS):
            await pilot.press(n)
            await pilot.pause(0.2)
            assert app.screen.query_one(TabbedContent).active == f"debug-{key}"
            assert app.screen.query_one(f"#debug-{key}").query_one(debug.DebugTab).loaded
        rows = {key: app.screen.query_one(f"#debug-{key}").query_one(DataTable).row_count
                for key in ("monsters", "items", "art", "sounds", "story")}
        assert rows["monsters"] == len(content.monsters)
        assert rows["items"] == len(content.items)
        assert rows["sounds"] == len(sound.MOMENTS)
        assert rows["story"] == len(load_library(content).events)
        assert rows["art"] >= len(content.monsters)
        await pilot.press("2", "down")
        await pilot.pause(0.2)
        assert tab(app, debug.MonstersTab).current == list(content.monsters)[1]
        await pilot.press("f12")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, DebugScreen)


async def test_the_art_tab_animates_any_pose():
    app = PTGApp(Config(backend="offline", layout="classic"))
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        app.push_screen(DebugScreen("art"))
        await pilot.pause(0.3)
        art = tab(app, debug.ArtTab)
        await pilot.click("#art-poses", offset=(len("Animate:  idle  ") + 1, 0))
        await pilot.pause(0.2)
        assert art.chosen_pose == "windup" and art.query_one(debug.PoseSprite).pose == "windup"
        await pilot.press("down")
        await pilot.pause(0.2)
        assert art.query_one(debug.PoseSprite).pose == "windup"  # the next sprite keeps the pose


async def test_the_art_tab_points_out_art_drawn_small_and_custom_colours():
    """Art in under half its frame looks tiny in the game; colours off the maker's palette are one more to draw."""
    app = PTGApp(Config(backend="offline", layout="classic"))
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        app.push_screen(DebugScreen("art"))
        await pilot.pause(0.3)
        table = tab(app, debug.ArtTab).query_one(DataTable)
        fills = list(debug.ArtTab.columns).index("Fills")
        torch, goblin = table.get_row("item_torch")[fills], table.get_row("goblin")[fills]
        assert torch.plain == "38%" and str(torch.style) == debug.WARN
        assert not str(goblin.style)
    assert "draw it bigger" in debug.fills_line("item_torch").plain
    assert "draw it bigger" not in debug.fills_line("item_davy_j_skull").plain
    assert "#fbff00" in debug.colours_line("item_hard_hat").plain
    assert debug.colours_line("item_pizza_rat").plain.endswith("all from the maker's palette")


async def test_ptg_debug_opens_it_straight_away():
    app = PTGApp(Config(backend="offline", layout="classic"), debug=True)
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause(0.3)
        assert isinstance(app.screen, DebugScreen)


async def test_sounds_play_on_a_click_or_enter(speakers):
    app = PTGApp(Config(backend="offline", layout="classic"))
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        app.push_screen(DebugScreen("sounds"))
        await pilot.pause(0.3)
        await pilot.press("enter")  # the table has the keyboard, on the first moment
        await pilot.pause(0.3)
        assert speakers.moments[-1] == "select"
        hit = list(sound.MOMENTS).index("hit")
        table = app.screen.query_one("#debug-sounds DataTable")
        for _ in range(2):  # one click plays it; so does clicking it again
            await pilot.click(table, offset=(3, 1 + hit))
            await pilot.pause(0.3)
        assert speakers.moments[-2:] == ["hit", "hit"]
        assert speakers.moments.count("hit") == 2
        await pilot.click("#sound-play")
        await pilot.pause(0.3)
        assert speakers.moments.count("hit") == 3


def test_sound_preview_plays_one_clip_even_with_sound_off(speakers):
    sound.engine().enabled = False  # off in Settings
    clip = sound.engine().bank["coin"][0]
    assert sound.preview(clip) is None
    assert speakers.moments == ["coin"]
    assert sound.play("coin") is False  # the game itself stays quiet
    assert 0 < sound.clip_length(clip) < 3
    bars = sound.envelope(clip, 20)
    assert 0 < len(bars) <= 20 and set(bars) <= set(sound.BARS)


def test_sound_preview_respects_ptg_sound_0():
    clip = sound.engine().bank["coin"][0]
    assert "PTG_SOUND=0" in sound.preview(clip)


async def test_state_shows_the_run_its_flags_and_the_profile():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="Tester"), seed=1)
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        app.show_campfire()
        await pilot.pause(0.3)
        app.start_descent()
        await pilot.pause(0.5)
        state = app.screen.game.state  # the intro holds the game on a first run
        state.flags.append("rang_the_bell")
        app.profile.set_mark("met_the_mirror")
        await pilot.press("f12", "7")
        await pilot.pause(0.3)
        tree = tab(app, debug.StateTab).query_one(Tree)
        assert tree.root.data["flags"] == ["rang_the_bell"]
        assert {str(child.label).split(" ")[0] for child in tree.root.children} >= {"player", "rooms", "flags"}
    text = plain(debug.run_summary(state, "the run in progress", load_content()))
    assert "rang_the_bell" in text and "Tester" in text
    assert "met_the_mirror" in plain(debug.profile_summary(app.profile, load_content()))


async def test_story_events_fire_on_the_next_descent_and_reload():
    app = PTGApp(Config(backend="offline", layout="classic"))
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        app.push_screen(DebugScreen("story"))
        await pilot.pause(0.3)
        story = tab(app, debug.StoryTab)
        await pilot.click("#story-fire")
        assert await until(pilot, lambda: app.event == story.current)
        fire = app.screen.query_one("#story-fire")
        assert await until(pilot, lambda: not fire.has_class("-active"))  # a button ignores clicks while it's pressed
        await pilot.click("#story-fire")  # again: never mind
        assert await until(pilot, lambda: app.event is None)
        await pilot.click("#story-reload")
        events = len(load_library(load_content()).events)
        assert await until(pilot, lambda: story.query_one(DataTable).row_count == events)


async def test_the_model_check_runs_in_the_app_and_is_kept(monkeypatch, fake_llm):
    model = fake_llm(reply={"kind": "flavor", "action_id": "", "difficulty": "trivial"}, text="You hum. Nothing.")
    monkeypatch.setattr(debug, "make_llm", lambda config: model)
    app = PTGApp(Config(backend="offline", layout="classic"))
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        app.push_screen(DebugScreen("models"))
        await pilot.pause(0.3)
        await app.workers.wait_for_complete()
        assert app.screen.query_one("#check-model", Select).value == "pretend-model"  # the loaded one
        await pilot.click("#check-run")
        await pilot.pause(0.2)
        await app.workers.wait_for_complete()
        await pilot.pause(0.2)
        bar = app.screen.query_one(ProgressBar)
        assert bar.total and bar.progress == bar.total
        assert app.screen.query_one("#check-history", DataTable).row_count == 1
    [earlier] = check.history()
    assert earlier["model"] == "fake" and earlier["commands"] >= 9 and earlier["lines"][-1].startswith("Verdict")


async def test_a_model_that_isnt_loaded_comes_with_a_warning():
    app = PTGApp(Config(backend="offline", layout="classic"))
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        app.push_screen(DebugScreen("models"))
        await pilot.pause(0.3)
        await app.workers.wait_for_complete()
        models = tab(app, debug.ModelsTab)
        app.screen.query_one("#check-model", Select).value = "other-model"
        await pilot.pause(0.2)
        assert "Not loaded" in str(app.screen.query_one("#check-note").content)
        assert models.chosen().model == "other-model" and models.chosen().api_key == ""


async def test_use_for_the_narrator_saves_the_model():
    app = PTGApp(Config(backend="offline", layout="classic"))
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        app.push_screen(DebugScreen("models"))
        await pilot.pause(0.3)
        await app.workers.wait_for_complete()
        await pilot.click("#check-use")
        await pilot.pause(0.1)
    assert (app.config.backend, app.config.model) == ("openai", "pretend-model")


async def test_the_log_tab_reads_the_model_log():
    log_exchange("json", {"model": "m", "messages": [{"role": "user", "content": "PLAYER TYPED: kick the door"}]},
                 '{"kind": "creative"}')
    log_exchange("guard", ["exit claim: You see a door to the east."], "The room is quiet.")
    app = PTGApp(Config(backend="offline", layout="classic"))
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        app.push_screen(DebugScreen("log"))
        await pilot.pause(0.3)
        log = tab(app, debug.LogTab)
        assert log.query_one(DataTable).row_count == 2
        assert [e.label for e in log.entries.values()] == ["guard", "json"]  # newest first
        assert debug.gist(log.entries["1"]) == "kick the door"
        assert "CUT" in str(debug.exchange_text(log.entries["0"]))
        app.screen.query_one("#log-filter", Select).value = "guard"
        await pilot.pause(0.2)
        assert log.query_one(DataTable).row_count == 1


async def test_check_reports_progress_and_keeps_a_history(fake_llm):
    steps = []
    report = await check.run(fake_llm(), load_content(), lambda r, step: steps.append(step))
    assert report.done == report.planned == len(steps) - 1 and steps[-1] == ""
    assert steps[0].startswith("reading") and steps[-2].startswith("narrating")
    check.save(report)
    check.save(report)
    assert len(check.history()) == 2 and check.history(1)[0]["speed"] >= 0
