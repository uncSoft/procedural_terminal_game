from textual import events
from textual.geometry import Offset, Region
from textual.widgets import Static

from ptg import sound
from ptg.config import Config, load_game, save_game, save_path
from ptg.content import load_content
from ptg.dice import Roll
from ptg.events import Event
from ptg.sprites import DEATH_FRAMES, DEFAULT_WIDTH
from ptg.ui.app import PTGApp
from ptg.ui.dice import DiceScreen
from ptg.ui.game_screen import GameScreen
from ptg.ui.hub import EndScreen, HubScreen
from ptg.ui.effects import Popup
from ptg.ui.panels import (BestiaryScreen, CharacterScreen, FloorScreen, HelpScreen, InfoScreen, InventoryScreen,
                           JournalScreen, LevelUpScreen, LookScreen, MapScreen, ShopScreen)
from ptg.meta import start_run
from ptg.ui.screens import AbandonScreen, IntroScreen, SetupScreen, TitleScreen
from ptg.ui.widgets import AnimatedSprite, ChoiceItem, roll_text


async def settle(app, pilot, limit: float = 10.0) -> None:
    """Wait for the current turn to finish, rolling any dice and picking any perks along the way."""
    for _ in range(int(limit / 0.1)):
        await pilot.pause(0.1)
        if isinstance(app.screen, DiceScreen):
            await pilot.press("space")
            await pilot.pause(1.5)
            await pilot.press("enter")
        elif isinstance(app.screen, LevelUpScreen):
            await pilot.press("1")
        elif isinstance(app.screen, GameScreen) and not app.screen.busy:
            return


async def test_campfire_descent_panels_and_continue():
    app = PTGApp(Config(backend="offline", player_name="Tester"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, TitleScreen)
        await pilot.press("n")
        await pilot.pause(0.5)
        assert isinstance(app.screen, HubScreen)
        await pilot.press("d")
        await pilot.pause(0.5)
        assert isinstance(app.screen, IntroScreen)  # first descent ever
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, GameScreen)
        for command in ["1", "search the room for secrets", "sing a sea shanty", "2"]:
            await pilot.press(*command, "enter")
            await settle(app, pilot)
        assert len(app.screen.query_one("#story").query(Static)) > 6
        turns = app.screen.game.state.turn
        assert turns > 0
        for key, panel in [("f2", InventoryScreen), ("f3", CharacterScreen), ("f4", LookScreen),
                           ("f6", BestiaryScreen)]:
            await pilot.press(key)
            await pilot.pause(0.2)
            assert isinstance(app.screen, panel)
            await pilot.press("escape")
            await pilot.pause(0.1)
        await pilot.press("i", "enter")  # typed IF-style command opens the inventory
        await pilot.pause(0.2)
        assert isinstance(app.screen, InventoryScreen)
        await pilot.press("escape")  # the inventory closes
        await pilot.press("escape")  # "Press Esc again for the title screen": an Esc too many doesn't end a run
        await pilot.pause(0.3)
        assert isinstance(app.screen, GameScreen)
        await pilot.press("escape")
        await pilot.pause(0.3)
        assert isinstance(app.screen, TitleScreen)
        await pilot.press("c")
        await settle(app, pilot)
        assert isinstance(app.screen, GameScreen) and app.screen.game.state.turn == turns


async def test_a_run_in_progress_comes_first_and_picks_up_where_it_was():
    app = PTGApp(Config(backend="offline", player_name="T"))
    state = start_run(app.profile, load_content(), "T", seed=5)
    state.room.monster, state.room.items = None, ["healing_potion"]
    save_game(state)
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause(0.3)
        title = app.screen
        assert [w.id for w in title.query_one("#menu").children][:3] == ["continue", "run-info", "new"]
        assert app.focused.id == "continue" and str(title.query_one("#new").label) == "New run"
        assert "Floor 1/3" in str(title.query_one("#run-info").render())
        await pilot.press("n")  # a new run, not without asking
        await pilot.pause(0.3)
        assert isinstance(app.screen, AbandonScreen)
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert app.screen is title and load_game() is not None
        await pilot.press("n")
        await pilot.pause(0.3)
        await pilot.press("enter")  # "Continue it" is the one already chosen
        await settle(app, pilot)
        await pilot.pause(0.5)
        story = app.screen.query_one("#story")
        classes = [c for w in story.children for c in w.classes]
        assert "continued" in classes and "room-row" in classes and "recap" not in classes  # offline: no repeat
        assert any("click to take" in str(card.query_one(".loot-text").render()) for card in story.query(".loot-card"))
        assert str(story.children[-1].render()).strip().startswith("You're in the ")


async def test_abandoning_a_run_from_the_title_ends_it_as_a_death():
    app = PTGApp(Config(backend="offline", player_name="T"))
    state = start_run(app.profile, load_content(), "T", seed=5)
    state.souls = 9
    save_game(state)
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("n")
        await pilot.pause(0.3)
        await pilot.click("#abandon")
        await pilot.pause(0.5)
        assert isinstance(app.screen, HubScreen) and app.profile.souls >= 9 and load_game() is None
        assert app.profile.runs(limit=1)[0]["cause"] == "abandoned on floor 1"
        await pilot.press("escape")  # the title: nothing to continue now
        await pilot.pause(0.3)
        assert app.screen.query_one("#continue").disabled and app.focused.id == "new"
        assert str(app.screen.query_one("#new").label) == "Play"


async def test_a_daily_from_the_command_line_asks_about_a_run_in_progress():
    app = PTGApp(Config(backend="offline", player_name="T"), daily=True)
    save_game(start_run(app.profile, load_content(), "T", seed=5))
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause(0.3)
        assert isinstance(app.screen, AbandonScreen)


async def test_a_run_that_cant_be_continued_says_why():
    save_path().write_text('{"version": 1, "status": "playing"}')
    app = PTGApp(Config(backend="offline", player_name="T"))
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause(0.3)
        info = app.screen.query_one("#run-info")
        assert info.display and "an older version of the game saved it" in str(info.render())
        assert app.screen.query_one("#continue").disabled and app.focused.id == "new"


async def test_a_press_on_a_choice_just_replaced_is_dropped(monkeypatch):
    """Run 44 crashed here: a click on a choice in the instant it was replaced, which Textual took for the start of a
    text selection in a widget no longer on the screen."""
    app = PTGApp(Config(backend="offline", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        gone = screen.query(ChoiceItem).first()
        x, y = gone.region.x + 1, gone.region.y
        await gone.remove()
        # the screen's map of what's where, a moment behind: the old choice is still there
        monkeypatch.setattr(screen, "get_widget_and_offset_at", lambda *_: (gone, Offset(1, 0)))
        monkeypatch.setattr(screen, "get_widget_at", lambda *_: (gone, Region(x - 1, y, 20, 1)))
        await app.on_event(events.MouseDown(None, x, y, 0, 0, 1, False, False, False, screen_x=x, screen_y=y))
        assert app.screen is screen


async def test_a_click_on_a_choice_is_that_choice_wherever_it_is_now():
    app = PTGApp(Config(backend="offline", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        first = screen.query(ChoiceItem).first()
        screen.refresh_choices()
        assert screen.query(ChoiceItem).first() is first  # nothing changed, so nothing was swapped out
        turn = screen.game.state.turn
        screen.post_message(ChoiceItem.Chosen(1, "go:nowhere"))  # a choice that's gone: nothing happens
        await pilot.pause(0.3)
        assert screen.game.state.turn == turn
        assert [a.id for a in screen.game.choices()].index("search_room") > 0
        screen.post_message(ChoiceItem.Chosen(1, "search_room"))  # its number was 1 in an older list
        await settle(app, pilot)
        assert screen.game.state.room.room_searched


def told_since(story, start: int) -> list[str]:
    """What the story has shown since its `start`th piece, by kind."""
    kinds = ("player-line", "floor-header", "secret-banner", "room-row", "story-sprite", "loot-row", "narration")
    return [next((k for k in kinds if k in widget.classes), type(widget).__name__)
            for widget in list(story.children)[start:]]


async def take_choice(app, pilot, screen, action_id: str) -> None:
    ids = [a.id for a in screen.game.choices()]
    screen.run_turn(str(ids.index(action_id) + 1))
    for _ in range(60):
        await pilot.pause(0.2)
        if isinstance(app.screen, FloorScreen):
            await pilot.press("enter")
        elif isinstance(app.screen, GameScreen) and not app.screen.busy:
            break


async def test_a_room_comes_before_what_lies_in_it(monkeypatch):
    """Run 44: a potion lying in a room came above the room's picture and its chest after what was said of it; on the
    stairs, the new floor's potion came above the floor's header."""
    from ptg import rules
    from ptg.world import generate

    seed = next(s for s in range(500) if any(not e.locked and generate(s).rooms[e.to].fixture == "chest"
                                             for e in generate(s).room.exits.values()))
    app = PTGApp(Config(backend="offline", player_name="T", auto_roll=True), seed=seed)
    async with app.run_test(size=(130, 46)) as pilot:
        screen = await into_a_run(app, pilot)
        state, story = screen.game.state, screen.query_one("#story")
        direction, way = next((d, e) for d, e in state.room.exits.items()
                              if not e.locked and state.rooms[e.to].fixture == "chest")
        state.rooms[way.to].monster, state.rooms[way.to].items = None, ["healing_potion"]
        start = len(story.children)
        await take_choice(app, pilot, screen, f"go:{direction}")
        assert told_since(story, start) == ["player-line", "room-row", "story-sprite", "loot-row", "narration"]
        logged = [text for (text,) in app.profile.db.execute(
            "select text from turns where run_id = ? and turn = ? and kind = 'shown'", (state.run_id, state.turn))]
        assert logged[:4] == [f"> Go {direction}", f"picture: {state.room.name}", "sprite: chest",
                              "cards: Healing Potion (on the floor)"]  # the turn log keeps it as it looked

        build = rules.build_floor

        def with_a_potion(state, content):
            build(state, content)
            state.room.monster, state.room.items = None, ["healing_potion"]

        monkeypatch.setattr(rules, "build_floor", with_a_potion)
        for room in state.rooms:
            room.monster = None
        state.room_id = next(r.id for r in state.rooms if r.fixture == "stairs")
        start = len(story.children)
        await take_choice(app, pilot, screen, "descend")
        assert told_since(story, start)[:2] == ["player-line", "floor-header"]
        assert told_since(story, start)[-3:] == ["room-row", "loot-row", "narration"]


async def test_a_hosted_game_keeps_its_narrator_and_debug_screen_to_itself(monkeypatch):
    """Served to several players (ptg serve), Settings can't point the server's narrator elsewhere, and the debug
    screen, which shows the model log, stays shut."""
    from textual.widgets import Input

    from ptg.ui.debug import DebugScreen

    monkeypatch.setenv("PTG_HOSTED", "1")
    app = PTGApp(Config(backend="anthropic", model="claude-haiku-5-5", player_name="Ava"), debug=True)
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause(0.3)
        await pilot.press("f12")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, DebugScreen) and app.check_action("toggle_sound", ()) is False
        await pilot.press("s")
        await pilot.pause(0.3)
        assert isinstance(app.screen, SetupScreen) and not any(w.display for w in app.screen.query(".local"))
        app.screen.query_one("#name", Input).value = "Ava Rose"
        app.screen.action_save()
        await pilot.pause(0.2)
        assert (app.config.player_name, app.config.backend, app.config.model) == ("Ava Rose", "anthropic",
                                                                                  "claude-haiku-5-5")


async def test_death_goes_to_the_tombstone_then_the_campfire():
    app = PTGApp(Config(backend="offline", player_name="Doomed"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause()
        app.show_campfire()
        await pilot.pause(0.3)
        app.profile.set("intro_seen", 1)
        app.start_descent()
        await pilot.pause(0.5)
        if isinstance(app.screen, IntroScreen):
            await pilot.press("enter")
        await settle(app, pilot)
        game = app.screen.game
        from conftest import put_monster

        put_monster(game.state, game.content, key="orc", hp=999)
        game.state.player.hp = 1
        game.state.player.agility = -50
        app.screen.refresh_panels()
        for _ in range(10):
            if not isinstance(app.screen, GameScreen):
                break
            await pilot.press("a", "t", "t", "a", "c", "k", "enter")
            await settle(app, pilot)
        await pilot.pause(1.5)
        assert isinstance(app.screen, EndScreen)
        assert app.profile.runs()[0]["status"] == "dead"
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert isinstance(app.screen, HubScreen)


async def test_first_run_opens_settings():
    app = PTGApp(None)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, SetupScreen)


async def into_a_run(app, pilot) -> GameScreen:
    await pilot.pause()
    app.show_campfire()
    await pilot.pause(0.3)
    app.profile.set("intro_seen", 1)
    app.start_descent()
    await pilot.pause(0.5)
    if isinstance(app.screen, IntroScreen):
        await pilot.press("enter")
    await settle(app, pilot)
    return app.screen


async def test_fights_flash_lunge_and_dissolve():
    app = PTGApp(Config(backend="offline", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        game = screen.game
        played = []
        play = screen._play_scene

        async def spy(key, name, steps):
            played.append([pose for pose, _, _ in steps])
            await play(key, name, steps)
        screen._play_scene = spy

        from conftest import put_monster

        put_monster(game.state, game.content, key="hobgoblin")
        here = game.state.room_id
        await screen._fight_animations([Event("hit", ""), Event("monster_hit", "")], ("hobgoblin", "Hobgoblin"), here)
        game.state.room.monster = None  # and the next blow kills it
        await screen._fight_animations([Event("hit", "")], ("hobgoblin", "Hobgoblin"), here)
        assert played == [["idle"] * 4 + ["lunge", "lunge", "idle"], ["idle"] * 4 + ["death"] * DEATH_FRAMES]
        assert not screen.animating

        played.clear()
        await screen._fight_animations([Event("hit", "")], ("hobgoblin", "Hobgoblin"), here + 1)  # fled
        game.config.art = "ascii"
        await screen._fight_animations([Event("hit", "")], ("hobgoblin", "Hobgoblin"), here)
        assert played == [["idle"] * 4]  # ASCII art still flashes, but doesn't dissolve


async def test_fixtures_come_alive():
    app = PTGApp(Config(backend="offline", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        game = screen.game
        here = (game.state.floor, game.state.room_id)
        story = screen.query_one("#story")

        # Walking in: the chest waits, shut (it only glints).
        game.state.room.fixture, game.state.room.fixture_used = "chest", False
        screen._arrival_sprite([Event("enter", "", data={"first": True})])
        await pilot.pause()
        chest = screen.live_sprites[-1]
        assert chest.key == "chest" and chest._timer is not None and set(chest.loop) == {0, 1}
        await pilot.press(*"sing a sea shanty", "enter")
        await settle(app, pilot)
        assert chest._timer is None and not screen.live_sprites  # the next turn stills it

        # Opening it: the same chest moves down to the moment and plays it, so there's only ever one.
        narration = screen.add_line("…", "narration")
        await screen._fixture_moment([Event("chest", "")], narration, here)
        assert [s for s in screen.query(AnimatedSprite) if s.key == "chest"] == [chest]
        assert story.children.index(chest) == story.children.index(narration) - 1
        assert chest._timer is None  # played once, then rests open

        # The stairs dissolve and go; a moment with no sprite waiting gets a fresh one.
        await screen._fixture_moment([Event("descend", "")], narration, (9, 9))
        await pilot.pause()
        assert [s.key for s in screen.query(AnimatedSprite)] == ["chest"]

        game.config.art = "ascii"
        await screen._fixture_moment([Event("shrine", "")], narration, (9, 9))
        assert len(screen.query(AnimatedSprite)) == 1  # no new sprite in ASCII mode


def close_on_border(screen) -> bool:
    box, close = screen.query_one(".panel-box").region, screen.query_one("#close").region
    return (close.y, close.right) == (box.y, box.right - 2)


async def test_panels_close_with_the_mouse():
    app = PTGApp(Config(backend="offline", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        screen.game.state.player.inventory += ["oil_flask", "stale_bread", "holy_water"]
        for key, panel in [("f1", HelpScreen), ("f2", InventoryScreen), ("f3", CharacterScreen), ("f4", LookScreen),
                           ("f5", MapScreen), ("f6", BestiaryScreen), ("f7", JournalScreen)]:
            await pilot.press(key)
            await pilot.pause(0.3)
            assert isinstance(app.screen, panel) and close_on_border(app.screen), key
            await pilot.click("#close")
            await pilot.pause(0.2)
            assert isinstance(app.screen, GameScreen), f"{key}: the ✕ closes it"
            await pilot.press(key)
            await pilot.pause(0.3)
            await pilot.click(offset=(1, 1))
            await pilot.pause(0.2)
            assert isinstance(app.screen, GameScreen), f"{key}: a click outside closes it"
        await pilot.press("f2")
        await pilot.pause(0.3)
        await pilot.press("down", "down", "down")  # each item's notes resize the box; the ✕ follows
        await pilot.pause(0.3)
        assert close_on_border(app.screen)
        panel = app.screen
        panel.action_close()
        panel.action_close()  # a double click
        await pilot.pause(0.2)
        assert isinstance(app.screen, GameScreen)  # closed the panel, not the game under it


async def test_dice_roll_and_reroll_with_the_mouse():
    app = PTGApp(Config(backend="offline", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        await into_a_run(app, pilot)
        results = []
        failed = Roll("might", "player", [4], 4, [("Might", 1)], dc=14, success=False)
        app.push_screen(DiceScreen(failed, "Lift the portcullis", 1, True), results.append)
        await pilot.pause(0.2)
        await pilot.click("#dice-box")  # click to roll
        assert app.screen.stage == "rolling"
        await pilot.pause(3.2)
        assert app.screen.stage == "done" and app.screen.query_one("#dice-box").has_class("tone-bad")
        await pilot.click("#dice-fate")
        await pilot.pause(0.2)
        assert results == ["reroll"]

        made = Roll("might", "player", [15], 15, [("Might", 1)], dc=14, success=True)
        app.push_screen(DiceScreen(made, "Lift the portcullis", 1, True), results.append)
        await pilot.pause(0.2)
        await pilot.click(offset=(1, 1))  # anywhere rolls...
        await pilot.pause(3.2)
        assert app.screen.query_one("#dice-box").has_class("tone-good") and not app.screen.query_one("#dice-fate").display
        await pilot.click(offset=(1, 1))  # ...and carries on
        await pilot.pause(0.2)
        assert results == ["reroll", "accept"]


async def test_rolls_light_up_the_story():
    app = PTGApp(Config(backend="offline", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        game = screen.game
        from conftest import put_monster

        put_monster(game.state, game.content, key="orc", hp=30)
        hit = Event("hit", "", dice=Roll("attack", "player", [15], 15, dc=12, success=True), data={"damage": 6})
        hurt = Event("monster_hit", "", dice=Roll("Orc attacks", "monster", [16], 16, dc=11, success=True),
                     data={"damage": 4})
        assert "✔ HIT" in roll_text(hit).plain and "✘ HIT YOU" in roll_text(hurt).plain
        game.state.player.hp -= 4
        await screen._roll_feedback([hit, hurt], game.state.player.hp + 4)
        story = screen.query_one("#story")
        assert story.has_class("tone-neutral")  # you hit it and it hit you: mixed
        assert len(screen.query(Popup)) == 2 and screen.query_one("#hud").has_class("hurt")
        await pilot.pause(1.4)
        assert not screen.query(Popup) and not story.has_class("tone-neutral")


async def test_a_new_floor_waits_for_you():
    app = PTGApp(Config(backend="offline", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        game = screen.game
        assert len(screen.query(".floor-header")) == 1  # floor 1's banner
        stairs = next(r for r in game.state.rooms if r.fixture == "stairs")
        game.state.room_id, stairs.monster, stairs.visited = stairs.id, None, True
        screen.refresh_panels()
        await pilot.press(*"descend", "enter")
        for _ in range(80):
            await pilot.pause(0.1)
            if not screen.busy:
                break
        assert isinstance(app.screen, FloorScreen)  # no timeout: it stays until you're done reading
        await pilot.click(offset=(60, 20))
        await pilot.pause(0.2)
        assert isinstance(app.screen, GameScreen) and game.state.floor == 2
        assert len(screen.query(".floor-header")) == 2
        assert [e.kind for e in game.state.log].count("floor") == 2
        lines = list(screen.query_one("#story").children)
        header, card = screen.query(".floor-header").last(), screen.query(".room-card").last()
        assert str(card.border_title) == f"✦ {game.state.room.name}"  # the new floor's first room, under its banner
        assert lines.index(header) < lines.index(card.parent)


async def test_the_mouse_can_begin_and_end_a_run():
    app = PTGApp(Config(backend="offline", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        await pilot.pause()
        app.show_campfire()
        await pilot.pause(0.3)
        app.start_descent()
        await pilot.pause(0.5)
        assert isinstance(app.screen, IntroScreen)
        await pilot.click("#intro-hint")
        await settle(app, pilot)
        assert isinstance(app.screen, GameScreen)
        app.screen.game.state.status = "dead"
        app.end_run(app.screen)
        await pilot.pause(0.5)
        assert isinstance(app.screen, EndScreen)
        await pilot.click(app.screen.query(".end-hint Clickable").first())
        await pilot.pause(0.3)
        assert isinstance(app.screen, HubScreen)


async def test_the_moments_make_sounds(monkeypatch):
    app = PTGApp(Config(backend="offline", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        from conftest import Recorder, put_monster

        monkeypatch.delenv("PTG_SOUND", raising=False)
        speakers = Recorder()
        monkeypatch.setattr(sound, "_sound", sound.Sound(True, 1.0, player=speakers))
        put_monster(screen.game.state, screen.game.content, key="orc", hp=200)
        screen.refresh_panels()
        await pilot.press(*"attack", "enter")
        await settle(app, pilot)
        heard = speakers.moments
        assert heard[:2] == ["select", "dice_small"] and {"hit", "crit_hit", "miss", "awful"} & set(heard)
        await pilot.press("f2")
        await pilot.pause(0.3)
        await pilot.click("#close")
        await pilot.pause(0.2)
        assert speakers.moments[-2:] == ["open", "close"]


async def test_items_drawn_in_the_maker_show_their_art(monkeypatch):
    from rich.text import Text

    from ptg.ui import panels

    monkeypatch.setattr(panels, "sprite_text", lambda key, width=24: Text("<ART>") if key.startswith("item_") else None)
    app = PTGApp(Config(backend="offline", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        key = screen.game.state.player.inventory[0]
        screen.action_lookup(f"item:{key}")
        await pilot.pause(0.3)
        assert "<ART>" in str(app.screen.query_one(".panel-box Static").render())
        await pilot.press("escape")
        await pilot.press("f2")
        await pilot.pause(0.3)
        assert "<ART>" in str(app.screen.query_one("#inv-detail").render())


async def test_the_inventory_is_tiles_and_enter_uses_the_one_picked(monkeypatch):
    from ptg.ui import panels
    from ptg.ui.panels import ItemTile

    drawn = panels.sprite_text  # pretend nobody has drawn the oil yet
    monkeypatch.setattr(panels, "sprite_text", lambda key, **kw: None if key == "item_oil_flask" else drawn(key, **kw))
    app = PTGApp(Config(backend="offline", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        player = screen.game.state.player
        player.inventory = ["healing_potion", "healing_potion", "oil_flask"]
        player.hp = 10
        await pilot.press("f2")
        await pilot.pause(0.3)
        inventory = app.screen
        assert isinstance(inventory, InventoryScreen)
        assert len(inventory.query(ItemTile)) == 3  # the sword in hand, both potions on one tile, the oil
        detail = lambda: str(inventory.query_one("#inv-detail").render())  # noqa: E731
        assert "No picture yet" not in detail()  # the sword is drawn
        await pilot.press("right", "right")
        await pilot.pause(0.1)
        assert "No picture yet" in detail()  # the oil isn't
        await pilot.press("left")
        await pilot.pause(0.1)
        assert inventory.items[inventory.current][0] == "healing_potion"
        assert "Drink the Healing Potion" in str(inventory.query_one("#inv-use").render())
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, GameScreen)
        assert player.inventory.count("healing_potion") == 1 and player.hp > 10


async def test_found_loot_shows_with_its_art():
    app = PTGApp(Config(backend="offline", player_name="T"), seed=4)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        index, feature = next((i, f) for i, f in state.room.visible_features() if not f.searched)
        feature.loot = ["superior_healing_potion"]
        number = next(n for n, a in enumerate(screen.game.choices(), 1) if a.id == f"search:{index}")
        await pilot.press(*str(number), "enter")
        await settle(app, pilot)
        [card] = screen.query(".loot-card")
        assert str(card.border_title) == "✦ found"
        art = card.query_one(AnimatedSprite)
        assert art.key == "item_superior_healing_potion" and art.width == DEFAULT_WIDTH  # the full picture
        assert "Superior Healing Potion" in str(card.query_one(".loot-text", Static).render())
        await pilot.click(".loot-card")
        await pilot.pause(0.3)
        assert isinstance(app.screen, InfoScreen)  # its card, with the full art and what it does
        assert "Superior Healing Potion" in str(app.screen.query_one(".panel-box Static").render())


async def test_a_room_you_walk_into_is_pictured_once():
    app = PTGApp(Config(backend="offline", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        story = screen.query_one("#story")
        [card] = screen.query(".room-card")
        assert str(card.border_title) == f"✦ {state.room.name}" and "▀" in str(card.query_one(Static).render())
        lines = list(story.children)
        narration = next(w for w in lines if w.has_class("narration"))
        assert lines.index(card.parent) < lines.index(narration)  # the picture, then the words
        for room in state.rooms:
            room.monster = None
        go = next(n for n, a in enumerate(screen.game.choices(), 1)
                  if a.id.startswith("go:") and not state.room.exits[a.id[3:]].locked)
        came_from = state.room.name
        await pilot.press(*str(go), "enter")
        await settle(app, pilot)
        assert [str(c.border_title) for c in screen.query(".room-card")] == [f"✦ {came_from}", f"✦ {state.room.name}"]
        back = next(n for n, a in enumerate(screen.game.choices(), 1)
                    if a.id.startswith("go:") and state.rooms[state.room.exits[a.id[3:]].to].name == came_from)
        await pilot.press(*str(back), "enter")
        await settle(app, pilot)
        assert len(screen.query(".room-card")) == 2  # been here before: no new picture


async def test_the_pad_lights_the_ways_out_and_takes_you_there():
    app = PTGApp(Config(backend="offline", player_name="T"), seed=57)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        for room in state.rooms:
            room.monster = None
        ways = {a.id[3:] for a in screen.game.choices() if a.id.startswith("go:")}
        for direction in ("north", "south", "east", "west"):
            assert screen.query_one(f"#dpad-{direction}").has_class("off") == (direction not in ways)
        go = next(c for c in screen.query(ChoiceItem) if "Go " in str(c.render()))
        assert str(go.render()).split(". ")[1][0] in "▲▼▶◀"  # the way's arrow by its choice
        way = sorted(ways)[0]
        target = state.room.exits[way].to
        await pilot.click(f"#dpad-{way}")
        await settle(app, pilot)
        assert state.room_id == target
        here = state.room_id
        off = next(d for d in ("north", "south", "east", "west") if screen.query_one(f"#dpad-{d}").has_class("off"))
        await pilot.click(f"#dpad-{off}")  # no door that way: nothing happens
        await settle(app, pilot)
        assert state.room_id == here


async def test_the_choices_box_keeps_its_height():
    """Nothing moves under the mouse: the box doesn't grow or shrink, and more choices start a second column."""
    app = PTGApp(Config(backend="offline", player_name="T"), seed=57)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        box = screen.query_one("#choices")
        height = box.size.height
        assert not screen.query_one("#choice-more").display
        state = screen.game.state
        state.player.inventory += ["healing_potion", "stale_bread", "smoke_bomb"]
        state.player.hp, state.room.items = 10, ["war_pick", "oil_flask", "hand_axe"]
        screen.refresh_choices()
        await pilot.pause(0.2)
        assert len(screen.game.choices()) > 8 and box.size.height == height
        assert screen.query_one("#choice-more").display and len(screen.query_one("#choice-list").children) == 8


async def test_pictures_in_the_story_open_their_cards():
    app = PTGApp(Config(backend="offline", player_name="T"), seed=57)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        screen.query_one("#story").scroll_home(animate=False)
        await pilot.pause(0.2)
        await pilot.click(".room-card")  # the room you're in: look around
        await pilot.pause(0.3)
        assert isinstance(app.screen, LookScreen)
        await pilot.press("escape")
        await pilot.pause(0.2)
        await pilot.click("#scene")  # no fight: the sidebar's floor plan looks around too
        await pilot.pause(0.3)
        assert isinstance(app.screen, LookScreen)
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert screen._card_of("chest") == "screen.lookup('fixture:chest')"
        assert screen._card_of("goblin") == "screen.lookup('monster:goblin')"
        assert screen._card_of("item_rusty_sword") == "screen.lookup('item:rusty_sword')"
        screen.action_lookup("fixture:shrine")
        await pilot.pause(0.3)
        assert "▀" in str(app.screen.query_one(".panel-box Static").render())  # a fixture's card has its picture


async def test_look_shows_the_room_as_a_picture():
    app = PTGApp(Config(backend="offline", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        await into_a_run(app, pilot)
        await pilot.press("f4")
        await pilot.pause(0.3)
        assert isinstance(app.screen, LookScreen)
        lines = str(app.screen.query_one(".panel-box Static").render()).split("\n")
        assert set(lines[0]) <= set("▀▄ ") and len(lines[0]) <= 76  # the picture first, never wider than the panel
        assert any("@" in line for line in lines[20:])  # and the floor plan after the words


async def test_no_room_pictures_in_ascii_mode():
    app = PTGApp(Config(backend="offline", player_name="T", art="ascii"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        assert not screen.query(".room-card")
        await pilot.press("f4")
        await pilot.pause(0.3)
        assert str(app.screen.query_one(".panel-box Static").render()).startswith("#")  # the floor plan, as ever


async def test_ctrl_l_wipes_the_terminal_and_draws_everything_again(monkeypatch):
    from textual.drivers.headless_driver import HeadlessDriver

    app = PTGApp(Config(backend="offline"))
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        written: list[str] = []
        monkeypatch.setattr(HeadlessDriver, "is_headless", property(lambda self: False))  # as if on a terminal
        monkeypatch.setattr(app._driver, "write", written.append)
        await pilot.press("ctrl+l")
        await pilot.pause()
        out = "".join(written)
        assert "\x1b[2J" in out and out.index("\x1b[2J") < out.index("Play")  # wiped, then every cell again


async def test_the_game_redraws_itself_every_few_turns(monkeypatch):
    app = PTGApp(Config(backend="offline", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        redraws = []
        monkeypatch.setattr(app, "action_redraw", lambda: redraws.append(screen.game.state.turn))
        for _ in range(app.REDRAW_EVERY):
            await pilot.press(*"hum a tune", "enter")
            await settle(app, pilot)
        await pilot.pause(0.2)
        assert len(redraws) == 1


async def test_a_secret_room_is_a_celebration(monkeypatch):
    """A bang, a fanfare, a gold banner in the story, a toast, and the room in gold on the map."""
    from conftest import Recorder

    from ptg.rules import hidden_room_beside

    app = PTGApp(Config(backend="offline", player_name="T"), seed=11)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        monkeypatch.delenv("PTG_SOUND", raising=False)
        speakers = Recorder()
        monkeypatch.setattr(sound, "_sound", sound.Sound(True, 1.0, player=speakers))
        state = screen.game.state
        for room in state.rooms:
            room.monster = None
        secret = next(r for r in state.rooms if r.secret)
        beside = next(r for r in state.rooms if not r.secret and abs(r.x - secret.x) + abs(r.y - secret.y) == 1)
        state.room_id, beside.visited = beside.id, True
        screen.refresh_panels()
        index = next(i for i, a in enumerate(screen.game.choices(), 1) if a.id == f"bomb:{hidden_room_beside(state)}")
        await pilot.press(*str(index), "enter")
        await settle(app, pilot)
        await pilot.pause(0.6)  # the fanfare comes just after the bang
        assert speakers.moments.index("bomb") < speakers.moments.index("secret_room")
        assert "SECRET ROOM" in str(screen.query_one(".secret-banner").render())
        assert "{" in str(screen.query_one("#map").render())
        assert any("Secret room found" in str(n.title) for n in app._notifications)
        assert any(e.kind == "system" and "Secret room found" in e.text for e in state.log)  # and after Continue


async def test_monsters_move_in_the_sidebar_the_bestiary_and_on_their_cards():
    """Their frames take turns: the sidebar's timer was once silently dead (Textual's own _animate hid it)."""
    from conftest import put_monster

    app = PTGApp(Config(backend="offline", player_name="T"), seed=3)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        game = screen.game
        put_monster(game.state, game.content, key="goblin", hp=200)
        screen.refresh_panels()
        before = screen.frame
        await pilot.pause(1.5)
        assert screen.frame >= before + 2

        game.profile.bump_beast("goblin", "seen")
        await pilot.press("f6")
        await pilot.pause(0.3)
        art = app.screen.query_one("#beast-art", AnimatedSprite)
        assert art.key == "goblin" and art.display and len(art.loop) == 2
        shown = set()
        for _ in range(6):
            await pilot.pause(0.25)
            shown.add(art.index)
        assert shown == {0, 1}
        await pilot.press("escape")
        await pilot.pause(0.2)

        screen.action_lookup("monster:goblin")
        await pilot.pause(0.3)
        assert isinstance(app.screen, InfoScreen)
        assert app.screen.query_one(AnimatedSprite).key == "goblin"


async def test_a_shop_from_its_door_to_its_counter(monkeypatch):
    """A jingle and a banner walking in; browsing opens her screen; Enter buys, and the shop opens again after."""
    from conftest import Recorder

    from ptg.models import OPPOSITE
    from ptg.world import generate

    seed = next(s for s in range(300) if any(r.shop for r in generate(s).rooms))
    app = PTGApp(Config(backend="offline", player_name="T"), seed=seed)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        monkeypatch.delenv("PTG_SOUND", raising=False)
        speakers = Recorder()
        monkeypatch.setattr(sound, "_sound", sound.Sound(True, 1.0, player=speakers))
        state = screen.game.state
        for room in state.rooms:
            room.monster = None
        shop = next(r for r in state.rooms if r.shop)
        way_out = next(iter(shop.exits))
        state.room_id, state.player.keys, state.player.gold = shop.exits[way_out].to, 1, 500
        screen.refresh_panels()
        ids = [a.id for a in screen.game.choices()]
        screen.run_turn(str(ids.index(f"go:{OPPOSITE[way_out]}") + 1))
        await settle(app, pilot)
        await pilot.pause(0.6)
        assert state.room is shop and "shop" in speakers.moments
        assert "SHOP" in str(screen.query(".secret-banner").last().render())

        ids = [a.id for a in screen.game.choices()]
        screen.run_turn(str(ids.index("shop") + 1))
        await settle(app, pilot)
        await pilot.pause(0.5)
        assert isinstance(app.screen, ShopScreen)
        first = shop.shop.wares[0]
        await pilot.press("enter")  # buy the first
        await pilot.pause(0.4)
        await settle(app, pilot)
        await pilot.pause(0.6)
        assert state.player.gold == 500 - first.price and first not in shop.shop.wares
        assert isinstance(app.screen, ShopScreen)  # back at her counter


async def test_click_what_a_monster_dropped_to_take_it(monkeypatch):
    """Its card says so; a click puts it in your pack (no turn), and the card says it's taken. Bombs and keys are
    yours already."""
    from conftest import put_monster

    from ptg import combat

    app = PTGApp(Config(backend="offline", player_name="T"), seed=3)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        put_monster(state, screen.game.content, key="goblin", hp=1)
        state.player.might = 50
        monkeypatch.setattr(combat, "_drops", lambda *_: ["healing_potion", "bomb", "oil_flask"])
        screen.refresh_panels()
        await pilot.press(*str([a.id for a in screen.game.choices()].index("attack") + 1), "enter")
        await settle(app, pilot)
        await pilot.pause(0.5)
        lying = [c for c in screen.query(".loot-card") if "click to take" in str(c.query_one(".loot-text").render())]
        assert len(lying) == 2 and state.room.items == ["healing_potion", "oil_flask"]
        turn = state.turn
        await pilot.click(lying[0])
        await settle(app, pilot)
        await pilot.pause(0.4)
        assert state.room.items == ["oil_flask"] and state.turn == turn
        assert lying[0].has_class("taken") and lying[0].border_title == "✓ taken"
