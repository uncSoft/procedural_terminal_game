"""Picking things up (ptg/rules.py): free and quiet, one choice for the lot (or click each card in the story), and
bombs and small keys straight onto their counters."""

from conftest import put_monster
from ptg.llm.interpreter import offline_interpret
from ptg.rules import available_actions, gain_item, perform, things_here
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
    assert perform(state, content, "take:healing_potion")[0].text == "You can't do that right now."
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


def test_what_you_trade_up_from_is_left_lying_there(content):
    state = clear_room()
    event = gain_item(state, content, "war_pick")[0]
    assert event.data == {"item": "war_pick", "left": "rusty_sword"} and state.room.items == ["rusty_sword"]
