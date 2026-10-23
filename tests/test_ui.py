from textual.widgets import Static

from ptg import sound
from ptg.config import Config
from ptg.dice import Roll
from ptg.events import Event
from ptg.sprites import DEATH_FRAMES, SMALL
from ptg.ui.app import PTGApp
from ptg.ui.dice import DiceScreen
from ptg.ui.game_screen import GameScreen
from ptg.ui.hub import EndScreen, HubScreen
from ptg.ui.effects import Popup
from ptg.ui.panels import (BestiaryScreen, CharacterScreen, FloorScreen, HelpScreen, InventoryScreen, JournalScreen,
                           LevelUpScreen, LookScreen, MapScreen)
from ptg.ui.screens import IntroScreen, SetupScreen, TitleScreen
from ptg.ui.widgets import AnimatedSprite, roll_text


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
        await pilot.press("escape")
        await pilot.press("escape")
        await pilot.pause(0.3)
        assert isinstance(app.screen, TitleScreen)
        await pilot.press("c")
        await settle(app, pilot)
        assert isinstance(app.screen, GameScreen) and app.screen.game.state.turn == turns


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
        assert art.key == "item_superior_healing_potion" and art.width == SMALL  # its hand-made small version
        assert "Superior Healing Potion" in str(card.query_one(".loot-text", Static).render())


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
