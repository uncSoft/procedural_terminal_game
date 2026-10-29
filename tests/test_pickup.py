"""Picking things up and what you do with them (ptg/rules.py, ptg/inventory.py): free and quiet, one choice for the
lot (or click each card in the story), bombs and small keys straight onto their counters; gear into your pack with
an offer to equip it, never tossed on the floor; finds lying where they turn up; dropping; and curses that stick."""

from dataclasses import replace

import pytest

from conftest import put_monster
from ptg import inventory, powers
from ptg.content import ItemDef
from ptg.llm.interpreter import offline_interpret
from ptg.inventory import gain
from ptg.rules import available_actions, perform, things_here
from ptg.text import the
from ptg.world import generate


def clear_room(seed: int = 3):
    state = generate(seed)
    state.room.monster = None
    return state


def test_picking_up_is_free_and_needs_no_narrator(content):
    state = clear_room()
    state.room.items = ["healing_potion"]
    turn = state.turn
    take = next(a for a in available_actions(state, content) if a.id.startswith("take"))
    assert take.id == "take:healing_potion" and take.hint == "no turn"
    events = perform(state, content, "take:healing_potion")
    assert state.turn == turn and "healing_potion" in state.player.inventory
    assert all(e.data.get("quiet") for e in events)


def test_one_choice_takes_the_lot_and_any_one_can_still_be_taken(content):
    state = clear_room()
    state.room.items = ["healing_potion", "oil_flask", "cheese_wheel"]
    ids = {a.id for a in available_actions(state, content)}
    assert "take_all" in ids and not any(i.startswith("take:") for i in ids)  # one choice, not three
    perform(state, content, "take:oil_flask")  # by its card in the story: not a numbered choice, but fine
    assert state.room.items == ["healing_potion", "cheese_wheel"] and "oil_flask" in state.player.inventory
    intent, _ = offline_interpret("grab the cheese", available_actions(state, content) + things_here(state, content))
    assert intent.action_id == "take:cheese_wheel"
    perform(state, content, "take_all")
    assert not state.room.items and {"healing_potion", "cheese_wheel"} <= set(state.player.inventory)


def test_nothing_is_picked_up_in_the_middle_of_a_fight(content):
    state = clear_room()
    state.room.items = ["healing_potion", "bomb"]
    put_monster(state, content, hp=50)
    assert perform(state, content, "take:healing_potion")[0].text == "Not in the middle of a fight."
    assert "bomb" in state.room.items  # bombs wait too


def test_a_slain_monsters_bomb_and_key_are_yours_as_it_falls(content, monkeypatch):
    from ptg import combat

    state = clear_room()
    put_monster(state, content, hp=1)
    state.player.might = 50  # (it falls to the first blow)
    monkeypatch.setattr(combat, "_drops", lambda *_: ["bomb", "small_key", "healing_potion"])
    bombs, keys = state.player.bombs, state.player.keys
    events = perform(state, content, "attack")
    assert state.room.monster is None and (state.player.bombs, state.player.keys) == (bombs + 1, keys + 1)
    assert state.room.items == ["healing_potion"]  # the rest is yours to take, or leave
    assert [e.data["item"] for e in events if e.kind == "take"] == ["bomb", "small_key"]


def test_a_key_pocketed_as_it_falls_is_told_with_its_drop(content, monkeypatch):
    """Run 44: "You take the Small Key" came after "You reach level 5!", as if picked up later."""
    from ptg import combat

    state = clear_room()
    put_monster(state, content, hp=1)
    state.player.might = 50
    state.player.xp = state.player.next_level_xp() - 1  # and the kill is a level
    monkeypatch.setattr(combat, "_drops", lambda *_: ["small_key"])
    kinds = [e.kind for e in perform(state, content, "attack")]
    assert kinds.index("take") == kinds.index("drop") + 1 < kinds.index("level")


def test_walking_in_collects_bombs_and_keys(content):
    state = clear_room()
    direction, exit_ = next((d, e) for d, e in state.room.exits.items() if not e.locked)
    there = state.rooms[exit_.to]
    there.monster, there.items = None, ["bomb", "healing_potion"]
    bombs = state.player.bombs
    events = perform(state, content, f"go:{direction}")
    assert state.player.bombs == bombs + 1 and there.items == ["healing_potion"]
    assert any(e.kind == "take" and e.data.get("item") == "bomb" for e in events)


def ids(state, content):
    return [a.id for a in available_actions(state, content)]


def typed(state, content, words):
    """What the offline interpreter makes of `words`, given everything the game would hand it."""
    actions = available_actions(state, content) + things_here(state, content) + inventory.moves(state, content)
    return offline_interpret(words, actions)[0].action_id


# --- gear: into your pack, and an offer to put it on ---------------------------------

@pytest.mark.parametrize("worn, better", [
    ("leather_jerkin", "king_mouses_vest"), ("hard_hat", "king_mouses_vest"),  # King Mouse's trophy (F4)
    ("scale_hauberk", "moonsilver_vest"), ("adamant_stewpot", "moonsilver_vest"),  # the secret room's prize
    ("silvered_blade", "the_compensator"), ("silvered_blade", "sword_still_in_the_stone"),  # same tier, better
    ("war_pick", "snitch"),  # as good, and goblin-bane
])
def test_better_gear_of_the_same_tier_is_offered_and_can_be_put_on(content, worn, better):
    state = clear_room()
    slot = content.item(worn).kind
    setattr(state.player, slot, worn)
    turn = state.turn
    events = gain(state, content, better)
    assert getattr(state.player, slot) == worn and better in state.player.inventory  # into your pack...
    assert not state.room.items and events[0].data["to"] == "pack"  # ...and nothing on the floor
    offer = next(a for a in available_actions(state, content) if a.id == f"equip:{better}")
    name = content.item(worn).name
    assert offer.label.startswith(f"Equip {the(content.item(better).name)} (") and "→" in offer.label
    assert offer.hint == f"replaces {name} · no turn"
    events = perform(state, content, f"equip:{better}")
    assert getattr(state.player, slot) == better and worn in state.player.inventory and state.turn == turn
    assert events[0].data["replaced"] == worn and events[0].data["quiet"]
    assert f"equip:{worn}" not in ids(state, content)  # not offered back: it's worse


def test_the_offer_says_by_how_much_and_what_it_replaces(content):
    state = clear_room()
    gain(state, content, "the_compensator")
    offer = next(a for a in available_actions(state, content) if a.id.startswith("equip:"))
    assert (offer.label, offer.hint) == ("Equip the Compensator (1d6 → 2d6+2)", "replaces Rusty Sword · no turn")
    state.player.armor = "leather_jerkin"
    gain(state, content, "king_mouses_vest")
    offer = next(a for a in available_actions(state, content) if a.id == "equip:king_mouses_vest")
    assert (offer.label, offer.hint) == ("Equip King Mouse's Vest (+1 → +2 defense)",
                                         "replaces Leather Jerkin · no turn")


CHOICE_ROW = 79  # a choice's row in the choices box at 100x30: the box less its border, padding and the arrow pad


@pytest.mark.parametrize("slot", ["weapon", "armor"])
def test_the_offers_numbers_fit_a_100x30_choices_box(content, slot):
    """'1. Equip the Sword Still in the Stone (replaces Silve…': the comparison was cut off (F4). What it replaces is
    in the hint, after the numbers."""
    gear = [k for k, item in content.items.items() if item.kind == slot]
    longest = ""
    for worn in gear:
        for better in gear:
            state = clear_room()
            setattr(state.player, slot, worn)
            state.player.inventory = [better]
            offer = next((a for a in inventory.choices(state, content) if a.id == f"equip:{better}"), None)
            if offer:
                longest = max(longest, f"9. {offer.label}", key=len)
    assert "→" in longest and len(longest) <= CHOICE_ROW, longest


def test_worse_gear_waits_in_your_pack_and_goes_on_if_you_say_so(content):
    state = clear_room()
    state.player.weapon = "war_pick"
    gain(state, content, "hand_axe")
    assert not any(i.startswith("equip:") for i in ids(state, content))  # no choice for it...
    assert typed(state, content, "wield the hand axe") == "equip:hand_axe"  # ...but say so
    perform(state, content, "equip:hand_axe")
    assert state.player.weapon == "hand_axe" and "war_pick" in state.player.inventory


def test_only_the_best_of_your_spares_is_offered(content):
    state = clear_room()
    for key in ("hand_axe", "war_pick", "silvered_blade"):
        gain(state, content, key)
    assert [i for i in ids(state, content) if i.startswith("equip:")] == ["equip:silvered_blade"]


def test_armor_goes_on_by_itself_only_when_you_wear_none(content):
    state = clear_room()
    assert state.player.armor is None
    events = gain(state, content, "leather_jerkin")
    assert state.player.armor == "leather_jerkin" and events[0].kind == "equip"
    assert events[0].text == "You take the Leather Jerkin and put it on (+1 defense)."
    gain(state, content, "chain_shirt")  # better, but you're wearing something: it waits for you to say
    assert state.player.armor == "leather_jerkin" and "chain_shirt" in state.player.inventory


def test_order_doesnt_decide_what_you_hold(content):
    """'Pick up everything' left you holding whichever of two swords came last (F24)."""
    for order in (["silvered_blade", "the_compensator"], ["the_compensator", "silvered_blade"]):
        state = clear_room()
        state.room.items = list(order)
        perform(state, content, "take_all")
        assert state.player.weapon == "rusty_sword" and not state.room.items
        assert "equip:the_compensator" in ids(state, content)


def test_taking_your_armor_off_and_putting_it_back_on(content):
    state = clear_room()
    state.player.armor = "chain_shirt"
    assert typed(state, content, "take off the chain shirt") == "unequip:armor"
    assert typed(state, content, "remove my armor") == "unequip:armor"
    perform(state, content, "unequip:armor")
    assert state.player.armor is None and "chain_shirt" in state.player.inventory
    assert "equip:chain_shirt" in ids(state, content)  # anything beats nothing
    assert typed(state, content, "put on the chain shirt") == "equip:chain_shirt"


def test_gear_lying_here_can_be_put_on_straight_away(content):
    state = clear_room()
    state.room.items = ["war_pick"]
    assert typed(state, content, "wield the war pick") == "equip:war_pick"
    events = perform(state, content, "equip:war_pick")
    assert state.player.weapon == "war_pick" and "rusty_sword" in state.player.inventory and not state.room.items
    assert [e.kind for e in events] == ["take", "equip"]


def test_putting_gear_on_in_a_fight_takes_a_turn(content):
    state = clear_room()
    gain(state, content, "war_pick")
    put_monster(state, content, hp=50)
    turn = state.turn
    assert "equip:war_pick" not in ids(state, content)  # no choice for it mid-fight, but say so
    assert typed(state, content, "wield the war pick") == "equip:war_pick"
    perform(state, content, "equip:war_pick")
    assert state.player.weapon == "war_pick" and state.turn == turn + 1


# --- finds lie where they turn up ---------------------------------------------------

def test_what_a_search_or_a_chest_turns_up_lies_there_to_take_or_leave(content):
    """Searching put everything straight in your pack, junk gear and cursed things too (F28)."""
    state = clear_room()
    state.player.weapon = "war_pick"
    index, feature = next((i, f) for i, f in state.room.visible_features())
    feature.loot = ["hand_axe", "healing_potion", "bomb"]
    bombs, pack = state.player.bombs, list(state.player.inventory)
    events = perform(state, content, f"search:{index}")
    assert state.room.items == ["hand_axe", "healing_potion"] and state.player.inventory == pack
    assert state.player.bombs == bombs + 1  # a bomb's counted at once
    assert all(e.data["to"] == "room" for e in events if e.kind == "find" and e.data.get("item") != "bomb")
    assert "take_all" in ids(state, content)
    state.room.items, state.room.fixture, state.room.fixture_used = [], "chest", False
    state.player.keys = 1
    perform(state, content, "chest_key")
    assert len(state.room.items) <= 1 and state.player.inventory == pack  # what's in it, lying in the chest's room


def test_a_stunts_find_lies_there_too(content):
    from ptg.intent import Intent
    from ptg.rules import perform_creative

    state = clear_room()
    state.player.wits = 50
    pack = list(state.player.inventory)
    _, events = perform_creative(state, content, Intent(kind="creative", stat="wits", difficulty="easy",
                                                        success_effects=["find_item"], summary="rummage about"))
    found = next(e for e in events if e.kind == "find")
    assert found.data["item"] in state.room.items + ["bomb", "small_key"] and state.player.inventory == pack


# --- dropping -----------------------------------------------------------------------

def test_drop_anything_and_it_stays_where_you_leave_it(content):
    """No way to put anything down, and a model's 'drop the bread' used it up (F5)."""
    state = clear_room()
    state.player.inventory += ["stale_bread"]
    assert typed(state, content, "drop the stale bread") == "drop:stale_bread"
    assert typed(state, content, "leave the bread here") == "drop:stale_bread"
    turn = state.turn
    events = perform(state, content, "drop:stale_bread")
    assert "stale_bread" not in state.player.inventory and state.room.items == ["stale_bread"] and state.turn == turn
    assert events[0].text == "You leave the Stale Bread here." and events[0].data["to"] == "room"
    assert not any(i.startswith("take") for i in ids(state, content))  # no choice keeps offering it back...
    assert typed(state, content, "grab the bread") == "take:stale_bread"  # ...but it's yours to take
    state.room.items.append("healing_potion")
    assert "take:healing_potion" in ids(state, content)  # (one thing to take, as the choices go)
    perform(state, content, "take:stale_bread")
    assert "stale_bread" in state.player.inventory and not state.room.left


def test_what_youll_need_stays_with_you(content):
    state = clear_room()
    state.player.inventory.append("reliquary_key")
    events = perform(state, content, "drop:reliquary_key")
    assert events[0].kind == "info" and "reliquary_key" in state.player.inventory and not state.room.items
    events = perform(state, content, "drop:rusty_sword")  # the sword in your hand: take up another first
    assert events[0].kind == "info" and state.player.weapon == "rusty_sword"
    put_monster(state, content, hp=50)
    assert perform(state, content, "drop:healing_potion")[0].kind == "info"  # not in a fight


def test_drop_and_leave_dont_use_things_up_any_more(content):
    from ptg.creative import spends

    assert not spends("drop the stale bread") and not spends("leave the cheese here")
    assert spends("throw the bread at it")


# --- curses -------------------------------------------------------------------------

RING, DIAPER = "a_ring_probably_importan", "swoogy_s_diaper"


def test_a_cursed_thing_says_so_and_warns_you_before_you_take_it(content):
    """'Pick up the Ring, Probably Important' with nothing about its curse (F72)."""
    state = clear_room()
    state.room.items = [RING]
    take = next(a for a in available_actions(state, content) if a.id == f"take:{RING}")
    assert take.hint.startswith("cursed!")
    events = perform(state, content, f"take:{RING}")
    assert events[0].kind == "warn" and "cursed" in events[0].text and RING in state.room.items
    assert RING not in state.player.inventory  # you can still leave it
    take = next(a for a in available_actions(state, content) if a.id == f"take:{RING}")
    assert take.label == "Take the Ring, Probably Important anyway"
    perform(state, content, f"take:{RING}")
    assert RING in state.player.inventory and not state.room.items


def test_taking_everything_never_takes_the_cursed_thing(content):
    """Once warned of the Ring and left it, 'Pick up everything here (2)' took it with the rest, unsaid (F72)."""
    state = clear_room()
    state.room.items = ["healing_potion", RING]
    take_all = next(a for a in available_actions(state, content) if a.id == "take_all")
    assert take_all.label == "Pick up everything but the Ring, Probably Important (1)" and "cursed!" in take_all.hint
    perform(state, content, "take_all")
    assert state.room.items == [RING] and state.player.inventory.count("healing_potion") == 2
    assert RING not in state.player.inventory
    events = perform(state, content, f"take:{RING}")  # warned of it, you leave it...
    assert events[0].kind == "warn" and state.room.items == [RING]
    state.room.items.append("oil_flask")  # ...then something else turns up
    take_all = next(a for a in available_actions(state, content) if a.id == "take_all")
    assert take_all.label == "Pick up everything but the Ring, Probably Important (1)"
    perform(state, content, "take_all")
    assert state.room.items == [RING] and RING not in state.player.inventory and "oil_flask" in state.player.inventory
    assert typed(state, content, "take the ring") == f"take:{RING}"  # it's taken only on its own
    perform(state, content, f"take:{RING}")
    assert RING in state.player.inventory and not state.room.items


def test_a_curse_sticks_until_a_shrine_lifts_it(content):
    state = clear_room()
    state.player.inventory += [RING, DIAPER]
    state.warned += [RING, DIAPER]
    for words in ("drop the ring", "throw away the diaper"):
        events = perform(state, content, typed(state, content, words))
        assert events[0].kind == "info" and "cursed" in events[0].text
    assert {RING, DIAPER} <= set(state.player.inventory) and not state.room.items
    state.room.fixture, state.room.fixture_used = "shrine", False
    pray = next(a for a in available_actions(state, content) if a.id == "shrine_pray")
    assert "Ring" in pray.hint and "Diaper" in pray.hint
    events = perform(state, content, "shrine_pray")
    assert "the curse lifts" in events[0].text and not state.room.fixture_used  # (a prayer isn't the shrine's one use)
    assert not powers.holders(state, content, "cursed")  # no more max HP on the stairs...
    assert powers.holders(state, content, "reeks")  # ...and it still does the rest
    perform(state, content, f"drop:{RING}")
    assert state.room.items == [RING]


def test_cursed_gear_never_goes_on_by_itself_and_wont_come_off(content):
    helm = ItemDef(key="grim_helm", name="Grim Helm", kind="armor", defense=3, tier=2, powers=["cursed"])
    content = replace(content, items={**content.items, helm.key: helm})
    state = clear_room()
    gain(state, content, "grim_helm")
    assert state.player.armor is None and "equip:grim_helm" not in ids(state, content)
    perform(state, content, "equip:grim_helm")  # say so, and on it goes...
    assert state.player.armor == "grim_helm"
    assert perform(state, content, "unequip:armor")[0].kind == "info"  # ...for good
    gain(state, content, "chain_shirt")
    assert perform(state, content, "equip:chain_shirt")[0].kind == "info" and state.player.armor == "grim_helm"


def test_a_cursed_thing_isnt_spent_on_a_stunt_nor_handed_to_swoogy(content):
    from ptg.intent import Intent
    from ptg.rules import perform_creative

    state = clear_room()
    put_monster(state, content, hp=50)
    state.player.inventory.append(DIAPER)
    state.warned.append(DIAPER)
    _, events = perform_creative(state, content, Intent(kind="creative", stat="might", difficulty="easy",
                                                        success_effects=["stun"], uses=["Swoogy's Diaper"],
                                                        summary="throw the diaper at it"))
    assert events[0].kind == "info" and DIAPER in state.player.inventory
    from ptg import npcs

    assert not any(DIAPER in a.id for a in npcs.offers(state, content, everything=True))


def test_what_you_put_down_stays_yours_beside_the_same_thing_found(content):
    state = clear_room()
    state.player.inventory.append("stale_bread")
    perform(state, content, "drop:stale_bread")
    state.room.items.append("stale_bread")  # and another, found here
    assert "take:stale_bread" in ids(state, content)  # the one that isn't yours
    perform(state, content, "take:stale_bread")
    assert state.room.items == state.room.left == ["stale_bread"] and not any(i.startswith("take") for i in
                                                                               ids(state, content))


def test_a_thing_is_new_to_you_the_first_time_its_ever_yours(content, profile, found_cards):
    """Game.first_finds: what came your way that's never been yours, in any run (its card: ui/model_view.py
    FoundScreen), each once and in the order it came; taken, bought, given, onto a counter too; never a move of your
    own things between your pack, your hand and your back. A test room notes nothing, so there it's always new."""
    from ptg.config import Config
    from ptg.game import FOUND, Game

    state = clear_room()
    game = Game(state, Config(backend="offline"), None, content, profile)
    state.room.items = ["oil_flask", "healing_potion", "bomb", "oil_flask"]
    events = perform(state, content, "take_all")
    assert game.first_finds(events) == ["oil_flask", "healing_potion", "bomb"]
    assert {FOUND + key for key in ("oil_flask", "healing_potion", "bomb")} <= profile.marks()
    state.room.items = ["oil_flask", "cheese_wheel"]
    assert game.first_finds(perform(state, content, "take_all")) == ["cheese_wheel"]  # (once, ever)
    state.player.inventory.append("hand_axe")
    assert game.first_finds(perform(state, content, "equip:hand_axe")) == []  # (yours already: only moved)
    state.test_room = "goblin"
    state.room.items = ["pickle"]
    assert game.first_finds(perform(state, content, "take:pickle")) == ["pickle"]
    assert FOUND + "pickle" not in profile.marks() and game.first_finds(perform(state, content, "drop:pickle")) == []
