"""Shops (ptg/world.py _shop, rules.py, loot.py): rare, behind a door a small key opens or two bombs break, kept by
Granny Gristle or now and then Granny Kamultruk, with wares to buy or haggle over."""

from collections import Counter

from ptg import loot
from ptg.models import OPPOSITE
from ptg.rules import available_actions, exit_notes, perform, room_facts
from ptg.world import build_floor, generate, render_map


def floors(content, seeds):
    for seed in seeds:
        state = generate(seed)
        for floor in (1, 2, 3):
            if floor > 1:
                state.floor = floor
                build_floor(state, content)
            yield state


def at_the_door(content, keeper: str = loot.SHOPKEEPER):
    """A floor with `keeper`'s shop, the player in the room by its door with nothing hostile about."""
    state, shop = next((s, r) for s in floors(content, range(400)) for r in s.rooms if r.shop and r.shop.keeper == keeper)
    way_out = next(iter(shop.exits))
    state.room_id = shop.exits[way_out].to
    state.room.visited = True
    for room in state.rooms:
        room.monster = None
    return state, shop, OPPOSITE[way_out]


def in_the_shop(content, keeper: str = loot.SHOPKEEPER):
    """In `keeper`'s shop: the state and the shop (her wares)."""
    state, room, door = at_the_door(content, keeper)
    state.room.exits[door].locked = False
    perform(state, content, f"go:{door}")
    assert state.room is room
    return state, room.shop


def test_shops_are_rare_and_kamultruks_rarer(content):
    keepers, count = Counter(), 0
    for state in floors(content, range(300)):
        count += 1
        keepers.update(r.shop.keeper for r in state.rooms if r.shop)
    shops = sum(keepers.values())
    assert 0.18 < shops / count < 0.35 and 0.05 < keepers[loot.SHINY] / shops < 0.25


def test_a_shop_changes_nothing_else_on_its_floor(content, monkeypatch):
    def floor_without_the_shop(chance):
        monkeypatch.setattr(loot, "SHOP_CHANCE", chance)
        state = generate(7)
        return [(r.name, [(f.name, f.loot, f.gold) for f in r.features], r.items, r.monster and r.monster.key,
                 sorted(d for d, e in r.exits.items() if not state.rooms[e.to].shop))
                for r in state.rooms if not r.shop]

    assert floor_without_the_shop(1.0) == floor_without_the_shop(0.0)


def test_a_small_key_opens_the_door(content):
    state, shop, door = at_the_door(content)
    state.player.keys = 0
    assert perform(state, content, f"go:{door}")[0].kind == "locked" and state.room is not shop
    assert "locked; a shop beyond" in exit_notes(state)
    state.player.keys = 1
    unlock = next(a for a in available_actions(state, content) if a.id == f"go:{door}")
    assert unlock.label == f"Unlock the shop door {door}"
    perform(state, content, f"go:{door}")
    assert state.room is shop and state.player.keys == 0


def test_two_bombs_break_it_in(content):
    state, shop, door = at_the_door(content)
    state.player.keys, state.player.bombs = 0, 2
    assert "two bombs" in next(a for a in available_actions(state, content) if a.id == f"bomb:{door}").hint
    perform(state, content, f"bomb:{door}")
    assert state.room.exits[door].locked and state.room.exits[door].cracked and state.player.bombs == 1
    perform(state, content, f"bomb:{door}")
    assert not state.room.exits[door].locked and state.player.bombs == 0
    perform(state, content, f"go:{door}")
    assert state.room is shop


def test_what_they_sell(content):
    gristle, kamultruk, shillelagh = Counter(), Counter(), 0
    for state in floors(content, range(300)):
        for room in (r for r in state.rooms if r.shop):
            wares = [w.item for w in room.shop.wares]
            assert 3 <= len(wares) <= 4 and len(set(wares)) == len(wares) and all(w.price > 0 for w in room.shop.wares)
            (kamultruk if room.shop.keeper == loot.SHINY else gristle).update(
                "rare" if loot.rare(content.item(k)) else loot.role(content.item(k)) for k in wares)
            shillelagh += "mama_s_shillelagh" in wares
    assert kamultruk["rare"] / sum(kamultruk.values()) > 0.3 > gristle["rare"] / sum(gristle.values())
    assert gristle["potion"] and gristle["weapon"] + gristle["armor"] and shillelagh
    assert loot.where(content, "mama_s_shillelagh") == ["shops"]  # found nowhere else


def test_prices_go_up_with_what_and_where(content):
    potion, axe = content.item("healing_potion"), content.item("hand_axe")
    assert loot.price(potion, 1) < loot.price(potion, 3) < loot.price(potion, 3, shiny=True)
    assert loot.price(content.item("superior_healing_potion"), 1) > loot.price(potion, 1)
    assert loot.price(content.item("snitch"), 2) > loot.price(content.item("war_pick"), 2)  # rare: dearer
    assert loot.price(axe, 2) % 5 == 0


def test_buying(content):
    state, shop = in_the_shop(content)
    ware = shop.wares[0]
    state.player.gold = ware.price - 1
    assert perform(state, content, "buy:0")[0].kind == "info" and shop.wares[0] is ware
    state.player.gold = ware.price + 10
    events = perform(state, content, "buy:0")
    assert events[0].kind == "buy" and events[0].data["quiet"] and state.player.gold == 10
    assert ware not in shop.wares and any(e.data.get("item") == ware.item for e in events[1:])
    assert perform(state, content, "buy:9")[0].text == "You can't do that right now."


def test_haggling(content):
    state, shop = in_the_shop(content)
    first, second = shop.wares[0], shop.wares[1]
    was = first.price
    state.player.wits = 50
    perform(state, content, "barter:0")
    assert first.price == round(was * 2 / 3) and first.haggled == "down"
    assert "won't haggle" in perform(state, content, "barter:0")[0].text and first.price == round(was * 2 / 3)
    state.player.wits = -50
    was = second.price
    perform(state, content, "barter:1")
    assert second.price == round(was * 1.25) and second.haggled == "up"


def test_the_map_and_the_narrator_know_the_shop(content):
    state, shop, door = at_the_door(content)
    assert "¤" in "".join(render_map(state)) and "=" in "".join(render_map(state))
    state, shop = in_the_shop(content)
    facts = room_facts(state, content)
    assert "Granny Gristle keeps a shop here" in facts and f"({shop.wares[0].price} gold)" in facts
    assert next(a for a in available_actions(state, content) if a.id == "shop").label == "Browse Granny Gristle's wares"
    state.player.bombs = 3  # her shop is hers: no searching it for secrets, no bombing its walls
    assert not {"search_room"} & {a.id for a in available_actions(state, content)}
    assert not any(a.id.startswith("bomb") for a in available_actions(state, content))


def test_shopkeepers_keep_out_of_fights(content):
    assert not content.monster(loot.SHOPKEEPER).roams and not content.monster(loot.SHINY).roams
    keepers = {loot.SHOPKEEPER, loot.SHINY}
    for state in floors(content, range(100)):
        assert not any(r.monster and r.monster.key in keepers for r in state.rooms)
