"""The windows on a phone (docs/plans/mobile-view.md §3): held upright at the served page's 41x44, and on its side at
90x19, played with a finger. Each window fits the screen: nothing it needs runs off an edge."""

import random

import pytest
from conftest import put_monster
from test_ui import into_a_run

from ptg.config import Config
from ptg.dice import check
from ptg.ui import panels
from ptg.ui.app import PTGApp
from ptg.ui.dice import DiceScreen
from ptg.ui.hub import HubScreen
from ptg.ui.screens import COMPACT_TITLE, STACKED_TITLE, TitleScreen
from ptg.world import generate

UPRIGHT, SIDEWAYS = (41, 44), (90, 19)


@pytest.fixture(autouse=True)
def finger(monkeypatch):
    monkeypatch.setenv("PTG_TOUCH", "1")


def inside(app, widget) -> bool:
    """Whether a widget's drawn whole on the screen."""
    r, (w, h) = widget.region, app.size
    return r.width > 0 and r.x >= 0 and r.y >= 0 and r.right <= w and r.bottom <= h


def app_for(**kw) -> PTGApp:
    return PTGApp(Config(backend="offline", layout="grid", player_name="T", auto_roll=False), **kw)


async def test_the_title_stacks_its_name_and_its_menu_on_a_phone_held_upright():
    app = app_for()
    async with app.run_test(size=UPRIGHT) as pilot:
        await pilot.pause(0.4)
        title = app.screen
        assert isinstance(title, TitleScreen) and title.has_class("-phone")
        name = str(title.query_one("#splash").render())
        assert name.count("\n") == STACKED_TITLE.count("\n") and max(map(len, STACKED_TITLE.split("\n"))) <= 39
        assert all(inside(app, b) for b in title.query("#menu Button")), "a menu button runs off the screen"
    app = app_for()
    async with app.run_test(size=(110, 40)) as pilot:  # (room for it in a line: as it was)
        await pilot.pause(0.4)
        assert str(app.screen.query_one("#splash").render()).count("\n") == COMPACT_TITLE.count("\n")


async def test_the_campfire_is_one_column_on_a_phone_held_upright():
    app = app_for()
    async with app.run_test(size=UPRIGHT) as pilot:
        await pilot.pause(0.3)
        app.show_campfire()
        await pilot.pause(0.6)
        hub = app.screen
        assert isinstance(hub, HubScreen)
        right, left = hub.query_one("#hub-right"), hub.query_one("#hub-left")
        assert right.region.bottom <= left.region.y  # (the fire and the way down over the cards)
        assert inside(app, hub.query_one("#descend")) and inside(app, hub.query_one("#daily"))
        cards = [c for c in hub.query(".unlock-card") if c.region.width]
        assert len({c.region.x for c in cards}) == 2  # (two across)


async def test_the_dice_go_side_by_side_on_a_phone_on_its_side():
    app = app_for()
    async with app.run_test(size=SIDEWAYS) as pilot:
        await pilot.pause(0.3)
        roll = check(random.Random(1), "Attack", [("might", 3)], 12)
        app.push_screen(DiceScreen(roll, "Attack the goblin", 1, True))
        await pilot.pause(0.3)
        await pilot.press("space")
        await pilot.pause(2.0)
        dice = app.screen
        assert dice.side and dice.query_one("#dice-box").has_class("side")
        for part in ("#dice-faces", "#dice-target", "#dice-verdict", "#dice-prompt"):
            assert inside(app, dice.query_one(part)), f"{part} runs off the screen"


async def test_the_pack_and_the_shop_put_their_shelf_across_the_top_on_a_phone():
    seed = next(s for s in range(300) if any(r.shop for r in generate(s).rooms))
    app = app_for(seed=seed)
    async with app.run_test(size=UPRIGHT) as pilot:
        screen = await into_a_run(app, pilot)
        app.push_screen(screen.panel("inventory"))
        await pilot.pause(0.4)
        shelf, side = app.screen.query_one("#inv-shelf"), app.screen.query_one("#inv-side")
        assert shelf.region.bottom <= side.region.y and side.region.width >= 30  # (the picked one full width under)
        app.pop_screen()
        state = screen.game.state
        shop = next(r for r in state.rooms if r.shop)
        state.room_id, state.player.gold = shop.id, 300
        screen.refresh_panels()
        screen.open_shop()
        await pilot.pause(0.4)
        shelf, side = app.screen.query_one("#shop-shelf"), app.screen.query_one("#shop-side")
        assert shelf.region.bottom <= side.region.y and side.region.width >= 30
        assert inside(app, app.screen.query_one("#shop-buy"))


async def test_the_bestiary_lists_over_the_creature_on_a_phone_and_hides_an_empty_list(content):
    app = app_for(seed=1)
    async with app.run_test(size=UPRIGHT) as pilot:
        screen = await into_a_run(app, pilot)
        app.push_screen(screen.panel("bestiary"))
        await pilot.pause(0.3)
        assert not app.screen.query_one("#beast-list").display  # (nothing met yet)
        app.pop_screen()
        state = screen.game.state
        put_monster(state, content, "goblin")
        screen.game.profile.bump_beast("goblin", "seen")
        app.push_screen(screen.panel("bestiary"))
        await pilot.pause(0.3)
        listed, body = app.screen.query_one("#beast-list"), app.screen.query_one("#beast-body")
        assert listed.display and listed.region.bottom <= body.region.y and body.region.width >= 30


async def test_a_menu_has_rows_a_finger_can_hit_and_scrolls_where_they_dont_fit():
    for size in (UPRIGHT, SIDEWAYS):
        app = app_for(seed=1)
        async with app.run_test(size=size) as pilot:
            screen = await into_a_run(app, pilot)
            screen.action_menu()
            await pilot.pause(0.3)
            menu = app.screen
            assert isinstance(menu, panels.MenuScreen) and menu.has_class("touch")
            rows = list(menu.query(".menu-row"))
            assert all(r.region.height == 3 for r in rows if r.region.height)
            box = menu.query_one(".menu-box")
            assert inside(app, box)
            if size == SIDEWAYS:
                assert box.max_scroll_y > 0  # (the rest are a scroll away, not cut off)


async def test_the_sheet_the_floor_card_and_a_look_fit_a_phone_held_upright():
    app = app_for(seed=1)
    async with app.run_test(size=UPRIGHT) as pilot:
        screen = await into_a_run(app, pilot)
        game = screen.game
        app.push_screen(screen.panel("character"))
        await pilot.pause(0.3)
        from rich.table import Table

        rolls = app.screen.query_one(panels.Sheet)._rolls(game.state)
        assert len(rolls.renderables) > 3 and not any(isinstance(r, Table) for r in rolls.renderables)  # (lines)
        app.pop_screen()
        app.push_screen(panels.FloorScreen(2, 4, game.content.themes[game.state.theme], False))
        await pilot.pause(0.3)
        assert app.screen.shown is not None and app.screen.shown[2] > 0  # (its splash art, shrunk to fit)
        app.pop_screen()
        app.push_screen(screen.panel("look"))
        await pilot.pause(0.3)
        assert app.screen.picture() is not None


# --- the game screen made for a finger (ui/phone.py), the creature viewer (ui/creature.py), the art layer ---

def spore_bed(size, **kw) -> PTGApp:
    return PTGApp(Config(backend="offline", layout="grid", player_name="T", auto_roll=True),
                  test_room=("humongous_fungus", "strong", 0), **kw)


async def free(app, pilot, screen=None):
    from ptg.ui.game_screen import GameScreen

    for _ in range(150):
        await pilot.pause(0.1)
        if isinstance(app.screen, GameScreen) and not app.screen.busy and (screen is None or app.screen is screen):
            return app.screen
    raise AssertionError(f"never free: {type(app.screen).__name__}")


async def into_the_spore_bed(app, pilot):
    from ptg.rules import available_actions

    screen = await free(app, pilot)
    door = next(a for a in available_actions(screen.game.state, screen.game.content) if a.hint == "boss")
    screen.press(door)
    for _ in range(150):
        await pilot.pause(0.1)
        if app.screen is screen and not screen.busy and screen.game.state.in_combat:
            return screen
    raise AssertionError("the fight never began")


REGIONS = ("#stage-box", "#phone-tabs", "#pane-box", "#ways", "#decide")


async def test_the_phone_screen_keeps_every_box_where_it_is_from_a_room_into_a_fight():
    """JT: "be mindful of objects shifting during play (the nav bars, the here/map ...) so they dont hop around"."""
    from ptg.ui.phone import PhoneScreen

    app = spore_bed(UPRIGHT)
    async with app.run_test(size=UPRIGHT) as pilot:
        screen = await free(app, pilot)
        assert isinstance(screen, PhoneScreen) and screen.upright
        before = {box: screen.query_one(box).region for box in REGIONS}
        assert all(inside(app, screen.query_one(box)) for box in REGIONS)
        await into_the_spore_bed(app, pilot)
        assert {box: screen.query_one(box).region for box in REGIONS} == before  # (nothing moved)
        screen.action_tab("here")
        await pilot.pause(0.3)
        assert {box: screen.query_one(box).region for box in REGIONS} == before  # (a tab: only the pane changes)
        assert screen.query_one("#pane").display and not screen.query_one("#story").display


async def test_the_phone_buttons_have_every_choice_heres_first_so_attack_is_one_tap():
    from ptg.ui.phone import PhoneButton

    app = spore_bed(UPRIGHT)
    async with app.run_test(size=UPRIGHT) as pilot:
        screen = await into_the_spore_bed(app, pilot)
        buttons = list(screen.query(PhoneButton))
        assert buttons[0].action.id == "attack" and buttons[0].has_class("-first")
        assert all(b.region.height == 2 for b in buttons if b.region.height)  # (two rows tall, for a thumb)
        hp = screen.game.state.room.monster.hp
        screen.pressed(buttons[0].number, buttons[0].action)
        await free(app, pilot, screen)
        log = [e.text for e in screen.game.state.log[-12:]]
        assert any("attack" in line.lower() or "hit" in line.lower() or "miss" in line.lower() for line in log) \
            or screen.game.state.room.monster.hp < hp


async def test_a_folding_phone_opened_out_gets_the_wide_phone_screen():
    app = spore_bed((87, 39))
    async with app.run_test(size=(87, 39)) as pilot:
        screen = await into_the_spore_bed(app, pilot)
        assert type(screen).__name__ == "PhoneScreen" and not screen.upright
        stage, story, side = (screen.query_one(b).region for b in ("#stage-box", "#story", "#side"))
        assert story.y >= stage.bottom and side.x >= stage.right  # (the picture and the story; the rest beside them)
        assert all(inside(app, screen.query_one(b)) for b in REGIONS)


@pytest.mark.parametrize("layout", ["classic", "grid", "tabs"])
async def test_tapping_the_fight_watches_the_foe_up_close_in_every_layout(layout, monkeypatch):
    """JT: "for all view modes, tapping the bosses showing the higher res animations"."""
    from ptg.ui.creature import CreatureView

    monkeypatch.delenv("PTG_TOUCH", raising=False)  # (a mouse: each layout as chosen)
    app = PTGApp(Config(backend="offline", layout=layout, player_name="T", auto_roll=True),
                 test_room=("goblin_king", "strong", 0))
    async with app.run_test(size=(215, 59)) as pilot:
        from ptg.rules import available_actions

        screen = await free(app, pilot)
        door = next(a for a in available_actions(screen.game.state, screen.game.content) if a.hint == "boss")
        screen.press(door)
        for _ in range(150):
            await pilot.pause(0.1)
            if app.screen is screen and not screen.busy and screen.game.state.in_combat:
                break
        await pilot.click("#stage")
        await pilot.pause(0.5)
        view = app.screen
        assert isinstance(view, CreatureView) and view.key == "goblin_king"
        assert [name for name, _ in view.playlist][:2] == ["entrance", "idle"] and view.clips  # (its own clips)
        await pilot.press("escape")
        await pilot.pause(0.3)
        assert app.screen is screen


async def test_a_creature_without_clips_stands_in_its_poses_and_the_bestiary_opens_it():
    from ptg.ui.creature import CreatureView

    app = app_for(seed=1)
    async with app.run_test(size=UPRIGHT) as pilot:
        screen = await into_a_run(app, pilot)
        screen.game.profile.bump_beast("goblin", "seen")
        app.push_screen(screen.panel("bestiary"))
        await pilot.pause(0.3)
        app.screen.action_watch()
        await pilot.pause(0.5)
        view = app.screen
        assert isinstance(view, CreatureView) and view.key == "goblin" and view.poses and not view.clips
        assert [name for name, _ in view.playlist] == ["idle", "windup", "dizzy", "lunge"]
        await pilot.press("escape")


async def test_on_the_web_a_fights_moments_stay_pictures_and_never_drop_to_half_blocks(monkeypatch):
    """JT: a foe going for you "changes the background art to the super low res version while they attack and grow
    large - its fighting with the resolution for a frame or two over and over". A fight's moments (each foe's swing,
    the numbers rising) go to the page as pictures too, frame by frame, from the copy at the layer's pixels: the
    stage's picture never steps aside for them."""
    from ptg.rules import available_actions
    from ptg.ui import art_layer

    sent = []
    monkeypatch.setattr(art_layer, "active", lambda app: True)
    monkeypatch.setattr(art_layer, "_send", lambda app, message: sent.append(message))
    app = spore_bed((120, 40))
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await into_the_spore_bed(app, pilot)
        for _ in range(60):  # (the fight's copy at the layer's pixels is made off the screen's thread)
            await pilot.pause(0.1)
            if screen.hires_now() is not None:
                break
        assert screen.hires_now() is not None
        state = screen.game.state
        state.player.hp = state.player.max_hp = 500
        sent.clear()
        screen.press(next(a for a in available_actions(state, screen.game.content) if a.id == "dodge"))
        for _ in range(150):
            await pilot.pause(0.1)
            if type(app.screen).__name__ == "DiceScreen":
                await pilot.press("space")
            elif app.screen is screen and not screen.busy:
                break
        stage = [m["do"] for m in sent if m["id"] == "stage"]
        after = stage[stage.index("show"):]  # (from the dice window's going: it hid the stage while it was over it)
        assert "hide" not in after  # (never stepped aside for half blocks)
        assert len(after) >= 12  # (four foes' swings and numbers, a frame at a time)


async def test_on_the_web_the_stage_goes_to_the_page_as_an_image_with_its_words_over_it(monkeypatch):
    """The art layer (ui/art_layer.py): the room's picture, then the fight's, each a PNG and where it goes in cells;
    the foes' next moves as chips; hidden while another screen's over it."""
    import base64

    from ptg.ui import art_layer

    sent = []
    monkeypatch.setattr(art_layer, "active", lambda app: True)
    monkeypatch.setattr(art_layer, "_send", lambda app, message: sent.append(message))
    app = spore_bed(UPRIGHT)
    async with app.run_test(size=UPRIGHT) as pilot:
        screen = await free(app, pilot)
        for _ in range(40):  # (the room's drawn off the screen's thread)
            await pilot.pause(0.1)
            if any(m["do"] == "show" and m["id"] == "stage" for m in sent):
                break
        room = next(m for m in sent if m["do"] == "show" and m["id"] == "stage")
        assert base64.b64decode(room["png"])[:4] == b"\x89PNG" and room["region"][2] == UPRIGHT[0]
        sent.clear()
        await into_the_spore_bed(app, pilot)
        for _ in range(40):
            await pilot.pause(0.1)
            if any(m["do"] == "show" and m["chips"] for m in sent):
                break
        fight = next(m for m in sent if m["do"] == "show" and m["chips"])
        assert len(fight["chips"]) == 4  # (the Fungus and its three: each one's next move)
        assert fight["region"][3] == screen.plan.stage_rows - screen.fight.banner_rows  # (the banner stays words)
        sent.clear()
        screen.action_menu()
        await pilot.pause(0.3)
        assert {"do": "hide", "id": "stage"} in [{k: m[k] for k in ("do", "id")} for m in sent]
