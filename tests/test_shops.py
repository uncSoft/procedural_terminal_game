"""Shops (ptg/world.py _shop, rules.py, loot.py): rare, behind a door a small key opens or two bombs break, kept by
Granny Gristle or now and then Granny Kamultruk, with wares to buy or haggle over."""

import random
from collections import Counter

from ptg import inventory, loot
from ptg.llm.interpreter import offline_interpret
from ptg.models import OPPOSITE, Ware
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


def test_shops_are_rare_and_kamultruks_rarer_but_always_above_the_poison(content):
    keepers, count, above = Counter(), 0, 0
    for state in floors(content, range(300)):
        if state.floor == 3:  # (the floor above Norfel: always a shop, for Granny's snakeskin)
            above += any(r.shop for r in state.rooms)
            continue
        count += 1
        keepers.update(r.shop.keeper for r in state.rooms if r.shop)
    shops = sum(keepers.values())
    assert 0.18 < shops / count < 0.35 and 0.05 < keepers[loot.SHINY] / shops < 0.25 and above == 300


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
    state.player.gold, count = ware.price + 10, ware.count
    events = perform(state, content, "buy:0")
    assert events[0].kind == "buy" and events[0].data["quiet"] and state.player.gold == 10
    assert ware.count == count - 1 and (ware in shop.wares) == (count > 1)  # (her last one: gone from the counter)
    assert events[0].data["item"] == ware.item and events[0].data["how"] == "buy"
    assert events[0].text.count("You ") == 1  # one line for it: not "You buy it... You take it."
    assert perform(state, content, "buy:9")[0].text == "You can't do that right now."


def test_potions_come_in_twos_and_a_poison_floors_shop_has_two_pure(content):
    rng = random.Random(1)
    for keeper in (loot.SHOPKEEPER, loot.SHINY):
        wares = loot.wares(rng, content, [], keeper, 4, cure_for="poison")
        counts = {key: count for key, _, count in wares}
        assert counts["pure"] == 2 and all(n == 2 for k, n in counts.items() if loot.role(content.item(k)) == "potion")
        assert all(n == 1 for k, n in counts.items() if loot.role(content.item(k)) not in ("potion", "cure"))
    assert loot.price(content.item("pure"), 4) == 80 and loot.price(content.item("pure"), 4, shiny=True) == 100
    assert "pure" not in [k for k, _, _ in loot.wares(rng, content, [], loot.SHOPKEEPER, 2)]  # (no poison up there)


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
    assert "Granny Gristle keeps a shop here" in facts and "gold)" not in facts  # (the counter is the shop's to show)
    assert next(a for a in available_actions(state, content) if a.id == "shop").label == "Browse Granny Gristle's wares"
    state.player.bombs = 3  # her shop is hers: no searching it for secrets, no bombing its walls
    assert not {"search_room"} & {a.id for a in available_actions(state, content)}
    assert not any(a.id.startswith("bomb") for a in available_actions(state, content))


def test_shopkeepers_keep_out_of_fights(content):
    assert not content.monster(loot.SHOPKEEPER).roams and not content.monster(loot.SHINY).roams
    keepers = {loot.SHOPKEEPER, loot.SHINY}
    for state in floors(content, range(100)):
        assert not any(r.monster and r.monster.key in keepers for r in state.rooms)


def test_bought_gear_goes_in_your_pack_not_on_her_floor(content):
    """Buying a better weapon threw your old one on the shop's floor; a same-tier one was dead weight (F27). A better
    one goes on at once, the old one in your pack (run 66 carried Gulliver's sword unused past the Goblin King); one
    no better stays in the pack."""
    state, shop = in_the_shop(content)
    shop.wares = [Ware(item="war_pick", price=25), Ware(item="leather_jerkin", price=25),
                  Ware(item="hand_axe", price=25)]
    state.player.gold, state.player.armor = 100, None
    events = perform(state, content, "buy:0")
    assert state.player.weapon == "war_pick" and "rusty_sword" in state.player.inventory and not state.room.items
    assert [e.text for e in events if e.kind in ("buy", "equip")] == [
        "You buy the War Pick for 25 gold (75 left) and put it in your pack.",
        "You take the War Pick in hand (1d10) and put your Rusty Sword in your pack."]
    perform(state, content, "buy:0")
    assert state.player.armor == "leather_jerkin"  # nothing on, so on it goes
    perform(state, content, "buy:0")
    assert state.player.weapon == "war_pick" and "hand_axe" in state.player.inventory


def test_sell_what_you_carry_for_half_her_price(content):
    state, shop = in_the_shop(content)
    state.player.gold = 0
    state.player.inventory += ["hand_axe", "stale_bread"]
    actions = available_actions(state, content) + inventory.moves(state, content)
    assert offline_interpret("sell the hand axe", actions)[0].action_id == "sell:hand_axe"
    price = loot.price(content.item("hand_axe"), state.floor) // 2
    turn = state.turn
    events = perform(state, content, "sell:hand_axe")
    assert state.player.gold == price and "hand_axe" not in state.player.inventory and state.turn == turn
    assert events[0].kind == "sell" and events[0].data["quiet"] and f"{price} gold" in events[0].text
    state.player.armor = "chain_shirt"  # the armor off your back too
    perform(state, content, "sell:chain_shirt")
    assert state.player.armor is None and state.player.gold > price


def test_granny_kamultruk_pays_more(content):
    state, _ = in_the_shop(content, loot.SHINY)
    state.player.inventory.append("hand_axe")
    assert inventory.sale_price(state, content, "hand_axe") == loot.price(content.item("hand_axe"), state.floor,
                                                                        shiny=True) // 2


def test_she_wont_buy_a_key_a_quests_things_or_a_curse(content):
    state, _ = in_the_shop(content)
    state.player.inventory += ["reliquary_key", "lenny_s_good_tooth", "a_ring_probably_importan"]
    for key in ("reliquary_key", "lenny_s_good_tooth", "a_ring_probably_importan"):
        gold = state.player.gold
        events = perform(state, content, f"sell:{key}")
        assert events[0].kind == "info" and key in state.player.inventory and state.player.gold == gold


def test_selling_is_only_at_a_shop(content):
    state, shop, door = at_the_door(content)
    state.player.inventory.append("hand_axe")
    assert perform(state, content, "sell:hand_axe")[0].text == "You can't do that right now."


def test_selling_by_saying_so(content):
    """'sell my sword to granny' sold a Healing Potion at once (her name, in every sale's label, matched first), and
    'sell the hand axe' in your hand or 'sell my armor' were narrated as done while nothing changed (review)."""
    state, _ = in_the_shop(content)
    state.player.weapon, state.player.armor = "hand_axe", "leather_jerkin"
    state.player.inventory = ["healing_potion", "healing_potion", "war_pick"]
    gold = state.player.gold

    def said(words):
        actions = available_actions(state, content) + inventory.moves(state, content)
        intent, confident = offline_interpret(words, actions)
        return intent.action_id, confident

    for words in ("sell the hand axe", "sell my weapon"):  # the one in your hand: she says why not
        assert said(words) == ("sell:hand_axe", True)
        events = perform(state, content, "sell:hand_axe")
        assert events[0].kind == "info" and "Take up another weapon first" in events[0].text
    for words in ("sell my sword to granny", "sell something to granny", "sell junk to granny gristle"):
        assert said(words) == ("sell:", False)  # nothing by that name: she says what she'd buy
        events = perform(state, content, "sell:")
        assert events[0].kind == "info" and "Healing Potion" in events[0].text and "War Pick" in events[0].text
    assert state.player.gold == gold and state.player.weapon == "hand_axe"
    assert state.player.inventory == ["healing_potion", "healing_potion", "war_pick"]
    assert said("sell my armor") == ("sell:leather_jerkin", True)
    perform(state, content, "sell:leather_jerkin")
    assert state.player.armor is None and state.player.gold > gold
