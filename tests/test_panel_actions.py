"""W13: panels and cards send the engine's own actions: whatever it says you can do, not only a numbered choice."""

from test_screen import walk_in
from test_ui import into_a_run, settle
from ptg import npcs
from ptg.config import Config
from ptg.ui.app import PTGApp
from ptg.ui.panels import InfoScreen, InventoryScreen, PickScreen, ShopScreen


async def open_card(app, pilot, screen, term_id: str) -> InfoScreen:
    screen.action_lookup(term_id)
    await pilot.pause(0.3)
    assert isinstance(app.screen, InfoScreen)
    return app.screen


async def test_a_card_for_one_of_several_things_lying_here_offers_to_take_it():
    """With two or more lying here the choices list only 'take everything', so the card had nothing to offer (F29)."""
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        state.room.monster, state.room.items = None, ["hand_axe", "healing_potion", "chain_shirt"]
        screen.refresh_panels()
        assert not any(a.id == "take:chain_shirt" for a in screen.game.choices())  # (no such numbered choice)
        card = await open_card(app, pilot, screen, "item:chain_shirt")
        assert card.action_id == "take:chain_shirt"
        await pilot.press("enter")
        await settle(app, pilot)
        assert "chain_shirt" in (state.player.armor, *state.player.inventory)
        assert sorted(state.room.items) == ["hand_axe", "healing_potion"]  # the others still lie there


async def test_a_calm_characters_card_offers_what_they_are_after_never_a_blow():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), test_room=("lenny", "strong", 0))
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await walk_in(app, pilot)
        card = await open_card(app, pilot, screen, f"monster:{npcs.LENNY}")
        assert card.action_id == "lenny"  # (give him his tooth: not "attack")
        await pilot.press("escape")
        await pilot.pause(0.2)
        tooth = await open_card(app, pilot, screen, f"item:{npcs.BAD_TOOTH}")
        assert tooth.action_id and tooth.action_id.startswith("give:") and "monster:lucky_lenny" in tooth.action_id
        await pilot.press("enter")  # the card hands it over, as the tile's button would
        await settle(app, pilot)
        assert npcs.BAD_TOOTH not in screen.game.state.player.inventory


async def test_the_inventory_has_a_button_for_everything_you_can_do_with_the_thing():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(130, 44)) as pilot:
        screen = await into_a_run(app, pilot)
        player = screen.game.state.player
        screen.game.state.room.monster = None
        player.inventory = ["healing_potion", "war_pick", "rubber_duck"]
        player.hp = 10
        await pilot.press("f2")
        await pilot.pause(0.3)
        inventory = app.screen
        assert isinstance(inventory, InventoryScreen)
        words = lambda: " ".join(str(b.render()) for b in inventory.query(".inv-verb"))  # noqa: E731
        keys = [item[0] for item in inventory.items]
        await pilot.press(*["right"] * keys.index("war_pick"))
        await pilot.pause(0.2)
        assert inventory.items[inventory.current][0] == "war_pick"
        assert "Equip" in words() and "Drop" in words()  # (swap it for your sword, or put it down)
        await pilot.press("enter")  # Enter puts it on (a use of it): it never drops it
        await settle(app, pilot)
        assert player.weapon == "war_pick" and "rusty_sword" in player.inventory


async def test_a_button_in_the_inventory_that_picks_a_target_opens_the_list():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), test_room=("swamp_bottoms", "new", 0))
    async with app.run_test(size=(130, 46)) as pilot:
        screen = await walk_in(app, pilot)
        screen.game.state.player.inventory += ["holy_water"]
        await pilot.press("f2")
        await pilot.pause(0.3)
        inventory = app.screen
        keys = [item[0] for item in inventory.items]
        await pilot.press(*["right"] * keys.index("holy_water"))
        await pilot.pause(0.2)
        buttons = inventory.items[inventory.current][2]
        index = next(i for i, a in enumerate(buttons) if a.label == "Use on…")
        inventory.action_verb(index)
        await pilot.pause(0.4)
        assert isinstance(app.screen, PickScreen) and app.screen.options


async def test_the_shop_compares_gear_warns_of_a_spare_and_sells():
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), test_room=("shop", "strong", 0))
    async with app.run_test(size=(130, 46)) as pilot:
        screen = await walk_in(app, pilot)
        state = screen.game.state
        wares = state.room.shop.wares
        gear = next((i for i, w in enumerate(wares) if screen.game.content.item(w.item).kind in ("weapon", "armor")),
                    None)
        screen.action_shop_counter()
        await pilot.pause(0.4)
        shop = app.screen
        assert isinstance(shop, ShopScreen)
        if gear is not None:
            shop.show_detail(gear)
            assert "vs yours:" in str(shop.query_one("#shop-detail").render())
        state.player.inventory.append("rubber_duck")
        await pilot.press("s")
        await pilot.pause(0.4)
        assert isinstance(app.screen, PickScreen) and app.screen.options
        await pilot.press("escape")
        await pilot.pause(0.3)


async def test_a_weapon_lying_here_can_be_equipped_from_its_card():
    """The card offered only its first action (Take), so a sword you found could only be put on from the choices."""
    app = PTGApp(Config(backend="offline", layout="classic", player_name="T"), seed=1)
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        state.room.monster, state.room.items = None, ["sword_still_in_the_stone"]
        screen.refresh_panels()
        card = await open_card(app, pilot, screen, "item:sword_still_in_the_stone")
        assert card.action_id == "take:sword_still_in_the_stone"
        assert [a.id for a in card.more] == ["equip:sword_still_in_the_stone"]
        equip = [b for b in card.query(".card-verb") if "Equip" in str(b.render())]
        assert equip, "an Equip button beside Take"
        await pilot.click(equip[0])
        await settle(app, pilot)
        assert state.player.weapon == "sword_still_in_the_stone" and "rusty_sword" in state.player.inventory
