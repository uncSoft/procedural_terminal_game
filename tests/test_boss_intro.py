"""A spike (ui/boss_intro.py, PTG_BIG_INTRO=1): a boss's entrance big over the whole screen, then quietly into the
stage's strip."""

from conftest import put_monster

from ptg import encounter
from ptg.config import Config
from ptg.rules import available_actions
from ptg.ui.app import PTGApp
from ptg.ui.boss_intro import BossIntro
from ptg.ui.game_screen import GameScreen
from ptg.world import generate


def test_a_quiet_entrance_has_no_card_and_no_sting(content):
    state = generate(7)
    king = put_monster(state, content, "goblin_king")
    fight = encounter.Fight(state, content, king, 110, 16)
    loud, quiet = list(fight.entrance()), list(fight.entrance(quiet=True))
    assert any(cue for _, _, cue in loud) and not any(cue for _, _, cue in quiet)
    assert any("✦" in frame.plain for frame, _, _ in loud) and not any("✦" in frame.plain for frame, _, _ in quiet)


def test_it_rises_back_up_the_way_it_came(content):
    """Its entrance run backwards from where it lands: the last picture has it gone, up out of the frame."""
    state = generate(7)
    king = put_monster(state, content, "goblin_king")
    fight = encounter.Fight(state, content, king, 110, 16)
    risen = list(fight.rise())
    land = fight.clips["entrance"].land
    assert len(risen) == land + 1  # (every frame of it, back to the first)
    assert "Goblin King" not in risen[-1][0].plain and risen[-1][0].plain == fight.still(0, clip="entrance",
                                                                                         banner=False).plain


def test_too_small_a_screen_has_no_big_intro(content):
    from textual.geometry import Size

    state = generate(7)
    king = put_monster(state, content, "goblin_king")
    assert BossIntro.made(state, content, king, [], Size(70, 22)) is None
    assert BossIntro.made(state, content, king, [], Size(170, 48)) is not None


async def test_with_the_spike_on_a_boss_comes_in_big_then_into_the_strip(monkeypatch):
    monkeypatch.setenv("PTG_BIG_INTRO", "1")
    app = PTGApp(Config(backend="offline", layout="tabs", player_name="T", auto_roll=True),
                 test_room=("goblin_king", "strong", 0))
    async with app.run_test(size=(170, 48)) as pilot:
        for _ in range(80):
            await pilot.pause(0.1)
            if isinstance(app.screen, GameScreen) and not app.screen.busy:
                break
        screen = app.screen
        door = next(a for a in available_actions(screen.game.state, screen.game.content) if a.hint == "boss")
        screen.press(door)
        for _ in range(40):
            await pilot.pause(0.1)
            if isinstance(app.screen, BossIntro):
                break
        assert isinstance(app.screen, BossIntro)
        await pilot.press("escape")  # (any key skips it)
        for _ in range(80):
            await pilot.pause(0.1)
            if app.screen is screen and not screen.animating:
                break
        assert app.screen is screen and screen.game.state.in_combat


def test_its_on_unless_settings_or_the_environment_say_otherwise(monkeypatch):
    from ptg.ui.boss_intro import wanted

    monkeypatch.delenv("PTG_BIG_INTRO", raising=False)
    assert Config().boss_intros and wanted(Config())
    assert not wanted(Config(boss_intros=False))
    monkeypatch.setenv("PTG_BIG_INTRO", "1")
    assert wanted(Config(boss_intros=False))
    monkeypatch.setenv("PTG_BIG_INTRO", "0")
    assert not wanted(Config())


async def test_settings_can_keep_boss_entrances_on_the_stage():
    from textual.widgets import Select

    from ptg.config import load_config
    from ptg.ui.screens import SetupScreen

    app = PTGApp(None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, SetupScreen)
        intros = app.screen.query_one("#intros", Select)
        assert intros.value == "big"  # (the default)
        intros.value = "stage"
        app.screen.action_save()
        await pilot.pause(0.3)
        assert load_config().boss_intros is False
