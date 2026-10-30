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


async def test_a_boss_behind_a_door_has_its_fights_made_ahead(monkeypatch):
    """Next to a boss's door, its big intro's fight and the stage's are made in the background (most of their time is
    their room's picture), and walking in uses them rather than making them then."""
    monkeypatch.setenv("PTG_BIG_INTRO", "1")
    app = PTGApp(Config(backend="offline", layout="tabs", player_name="T", auto_roll=True),
                 test_room=("goblin_king", "strong", 0))
    async with app.run_test(size=(170, 48)) as pilot:
        for _ in range(80):
            await pilot.pause(0.1)
            if isinstance(app.screen, GameScreen) and not app.screen.busy:
                break
        screen = app.screen
        def kings() -> list:  # (any other fight next door is made ahead too)
            return [f for f in screen.ahead.values() if f.monster.key == "goblin_king"]

        for _ in range(50):
            await pilot.pause(0.1)
            if len(kings()) == 2:
                break
        made = kings()
        assert len(made) == 2
        door = next(a for a in available_actions(screen.game.state, screen.game.content) if a.hint == "boss")
        screen.press(door)
        for _ in range(40):
            await pilot.pause(0.1)
            if isinstance(app.screen, BossIntro):
                break
        assert isinstance(app.screen, BossIntro) and app.screen.fight in made
        await pilot.press("escape")
        for _ in range(80):
            await pilot.pause(0.1)
            if app.screen is screen and not screen.animating:
                break
        assert screen.fight in made and not kings()


async def test_any_fight_behind_a_door_is_made_ahead():
    """Not only a boss's: walking into floor 5's Sporerats took a seventh of a second to make their fight (run 66)."""
    app = PTGApp(Config(backend="offline", layout="tabs", player_name="T", auto_roll=True),
                 test_room=("sporerat", "strong", 5))
    async with app.run_test(size=(170, 48)) as pilot:
        for _ in range(80):
            await pilot.pause(0.1)
            if isinstance(app.screen, GameScreen) and not app.screen.busy:
                break
        screen = app.screen
        for _ in range(50):
            await pilot.pause(0.1)
            if screen.ahead:
                break
        made = list(screen.ahead.values())
        assert made and any(f.monster.key == "sporerat" for f in made)
        state = screen.game.state
        way = next(w for w, e in state.room.exits.items() if state.rooms[e.to].monster
                   and state.rooms[e.to].monster.key == "sporerat")
        screen.press(next(a for a in available_actions(state, screen.game.content) if a.id == f"go:{way}"))
        for _ in range(80):
            await pilot.pause(0.1)
            if state.in_combat and not screen.animating and not screen.busy:
                break
        assert screen.fight in made


# --- called out big: its name over its head, a line over that (boss_title, Fight.closeup, Fight.titled) ---

BOSSES = ("goblin_king", "king_mouse", "drowned_abbot", "thornmother", "serpentis", "the_sporefang_matriarch",
          "humongous_fungus")


def test_a_bosss_name_is_lettered_as_big_as_fits_on_one_line_before_two():
    from ptg import boss_title

    big = boss_title.letter("Serpentis", 200, 60)
    assert big.scale == 3 and big.width <= 200 and big.height <= 60
    smaller = boss_title.letter("Serpentis", 120, 60)  # (too wide at three times: twice)
    assert smaller.scale == 2
    two = boss_title.letter("The Humongous Fungus", 140, 60)  # (too wide on one line at twice: two lines)
    assert two.scale == 2 and two.height > 2 * boss_title.ROWS * 2
    assert boss_title.letter("The Humongous Fungus", 20, 6) is None  # (no room even small)


def test_every_boss_is_called_out_over_its_head_not_over_it(content):
    """At a 160x50 screen's intro (152x46), each boss's name and its line fit in the room over the tallest head."""
    import random

    from ptg import boss_title
    from ptg.world import party

    for key in BOSSES:
        state = generate(3, floors=5)
        boss = put_monster(state, content, key)
        state.room.others = party(random.Random(1), content, boss, 5)
        fight = encounter.Fight(state, content, boss, 152, 46, [])
        lettering = boss_title.letter(encounter.plain_name(boss), fight.width - 8,
                                      fight.headroom() - encounter.TITLE_TOP - 3)
        assert lettering is not None and lettering.scale >= 2, key
        assert encounter.TITLE_TOP + lettering.height <= fight.headroom(), key
        assert content.monster(key).epithet and fight.epithet() == content.monster(key).epithet


def test_a_boss_without_a_line_of_its_own_is_called_what_it_is(content):
    import dataclasses

    state = generate(7)
    king = put_monster(state, content, "goblin_king")
    plain = dataclasses.replace(content, monsters={**content.monsters, "goblin_king": dataclasses.replace(
        content.monster("goblin_king"), epithet="")})
    fight = encounter.Fight(state, plain, king, 150, 40)
    assert fight.epithet().startswith("Boss of ")
    assert encounter.Fight(state, content, put_monster(state, content, "goblin"), 150, 40).epithet() == ""


def test_it_lands_to_its_sting_with_no_card_then_the_view_rushes_in_and_its_name_burns_in(content):
    state = generate(7)
    king = put_monster(state, content, "goblin_king")
    fight = encounter.Fight(state, content, king, 150, 44)
    landing = list(fight.entrance(card=False))
    assert fight.sting in [cue for _, _, cue in landing] and not any("✦" in f.plain for f, _, _ in landing)
    close = list(fight.closeup())
    assert len(close) == 6 and close[-1][1] > close[0][1]  # (rushing in, then held)
    titled = list(fight.titled(2.0))
    assert len(titled) == 48 and titled[0][2] == "boss_title" and not any(cue for _, _, cue in titled[1:])
    epithet = content.monster("goblin_king").epithet
    assert epithet not in titled[0][0].plain and epithet in titled[-1][0].plain  # (fading in after the name)
    assert titled[0][0].plain != titled[-1][0].plain  # (burning in, and it idles under it)


async def test_the_big_intro_calls_the_boss_out_by_name_then_a_click_skips_it(monkeypatch):
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
        epithet = screen.game.content.monster("goblin_king").epithet
        for _ in range(100):
            await pilot.pause(0.1)
            if isinstance(app.screen, BossIntro) and epithet in str(app.screen.query_one("#intro-art").render()):
                break
        assert isinstance(app.screen, BossIntro), "the intro never called it out"
        await pilot.click("#intro-art")
        for _ in range(80):
            await pilot.pause(0.1)
            if app.screen is screen and not screen.animating:
                break
        assert app.screen is screen and screen.game.state.in_combat


def test_the_spore_beds_four_drop_in_one_at_a_time_the_fungus_last(content):
    """JT: "for the spore boss - make each one fall at a time - not all at once". Each of its three starts as the one
    before lands, a stab as each lands, then the Fungus to its sting; back out the same way, the last in first. Once
    it's been seen big, the stage has them all at once."""
    import random
    from itertools import pairwise

    from ptg.world import party

    state = generate(3, floors=5)
    fungus = put_monster(state, content, "humongous_fungus")
    state.room.others = party(random.Random(1), content, fungus, 5)
    fight = encounter.Fight(state, content, fungus, 152, 46, [])
    arrivals, landings = fight.arrivals(), fight._landings(fight.arrivals())
    helpers = sorted(m.place for m in fight.others)
    assert [arrivals[p] for p in helpers] == sorted(arrivals[p] for p in helpers)  # (left to right)
    assert arrivals[fungus.place] > max(landings[p] for p in helpers)  # (the Fungus last, once they're all down)
    for before, after in pairwise(helpers):
        assert arrivals[after] > landings[before]  # (one at a time)
    frames = list(fight.entrance(card=False))
    cues = [cue for _, _, cue in frames if cue]
    assert cues == ["encounter"] * 3 + [fight.sting]
    def drawn(entering):  # (its colours: every cell's a half block, so its plain text says nothing)
        return fight.still(0, clip="entrance", banner=False, entering=entering).spans

    assert drawn(0) != drawn(landings[helpers[0]]) != drawn(arrivals[fungus.place] - 1) \
        != drawn(landings[fungus.place])  # (each comes in, in turn)
    assert len(list(fight.entrance(quiet=True))) < len(frames)  # (on the stage after: all at once)
    assert len(list(fight.rise())) == max(landings.values()) + 1
