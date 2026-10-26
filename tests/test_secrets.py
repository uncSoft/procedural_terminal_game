"""Bombs, small keys, secret rooms and chests: the lighter Isaac-style layer for exploring (ptg/rules.py, world.py)."""

import random

from conftest import put_monster
from ptg import loot
from ptg.combat import defeat
from ptg.models import DELTA
from ptg.inventory import gain
from ptg.rules import available_actions, bombable_walls, hidden_room_beside, perform
from ptg.world import build_floor, generate


def beside_the_secret_room(seed=11):
    state = generate(seed)
    secret = next(r for r in state.rooms if r.secret)
    room = next(r for r in state.rooms if not r.secret and abs(r.x - secret.x) + abs(r.y - secret.y) == 1)
    state.room_id = room.id
    for r in state.rooms:
        r.monster = None
    return state, secret


def test_bombs_and_keys_go_on_counters(content):
    state = generate(1)
    events = gain(state, content, "bomb") + gain(state, content, "small_key")
    assert (state.player.bombs, state.player.keys) == (2, 1)
    assert "bomb" not in state.player.inventory and "small_key" not in state.player.inventory
    assert [e.data["item"] for e in events] == ["bomb", "small_key"]  # so they get loot cards


def test_bombs_are_offered_only_where_a_secret_room_could_be(content):
    """A secret room is only ever built in a gap that touches two rooms or more: that's how you work it out."""
    for seed in range(15):
        state = generate(seed)
        taken = {(r.x, r.y) for r in state.rooms if not r.secret}
        for room in (r for r in state.rooms if not r.secret):
            state.room_id = room.id
            for direction in bombable_walls(state):
                dx, dy = DELTA[direction]
                gap = (room.x + dx, room.y + dy)
                assert gap not in taken and sum((gap[0] + x, gap[1] + y) in taken for x, y in DELTA.values()) >= 2


def test_a_bomb_opens_the_secret_room_and_only_there(content):
    state, secret = beside_the_secret_room()
    direction = hidden_room_beside(state)
    events = perform(state, content, f"bomb:{direction}")
    assert events[0].kind == "secret_room" and state.room.exits[direction].to == secret.id
    assert state.player.bombs == 0 and not any(a.id.startswith("bomb") for a in available_actions(state, content))
    perform(state, content, f"go:{direction}")
    assert state.room_id == secret.id and state.room.items and loot.rare(content.item(state.room.items[0]))
    assert secret.archetype not in {r.archetype for r in state.rooms if r is not secret and
                                    abs(r.x - secret.x) + abs(r.y - secret.y) == 1}  # not the room next door again
    state.player.bombs = 3  # one secret room a floor, and that was it: no wall is worth a bomb now
    for room in state.rooms:
        state.room_id = room.id
        assert not bombable_walls(state)

    state, wrong = decoy_wall()  # and a gap that could have held it, but doesn't
    exits = dict(state.room.exits)
    events = perform(state, content, f"bomb:{wrong}")
    assert events[0].kind == "bomb" and state.room.exits == exits and state.player.bombs == 0


def decoy_wall():
    """A room with a wall worth bombing that has nothing behind it."""
    for seed in range(50):
        state = generate(seed)
        for room in (r for r in state.rooms if not r.secret):
            state.room_id, room.monster = room.id, None
            wrong = [d for d in bombable_walls(state) if d != hidden_room_beside(state)]
            if wrong:
                return state, wrong[0]
    raise AssertionError("no decoy walls in 50 seeds")


def test_a_careful_search_feels_the_draft(content):
    state, _ = beside_the_secret_room()
    state.player.wits = 50
    direction = hidden_room_beside(state)
    events = perform(state, content, "search_room")
    assert any("draft" in e.text for e in events) and state.room.draft == direction
    bomb = next(a for a in available_actions(state, content) if a.id == f"bomb:{direction}")
    assert "draft" in bomb.hint


def test_a_bomb_in_a_fight_always_goes_off(content):
    state = generate(3)
    monster = put_monster(state, content, hp=200)
    events = perform(state, content, "bomb")
    hit = next(e for e in events if e.kind == "hit")
    assert hit.dice is None and monster.hp == 200 - hit.data["damage"] and state.player.bombs == 0


def chest_room(content, seed=0):
    for seed in range(seed, seed + 50):
        state = generate(seed)
        room = next((r for r in state.rooms if r.fixture == "chest"), None)
        if room:
            state.room_id, room.monster = room.id, None
            return state
    raise AssertionError("no chest in 50 seeds")


def test_a_chest_opens_three_ways(content):
    state = chest_room(content)
    assert {"chest", "chest_smash"} <= {a.id for a in available_actions(state, content)}
    assert "chest_key" not in {a.id for a in available_actions(state, content)}
    state.player.keys, hp = 1, state.player.hp
    events = perform(state, content, "chest_key")
    assert state.player.keys == 0 and state.player.hp == hp and not any(e.dice for e in events)  # safe, no roll

    state = chest_room(content)
    state.player.might = -50  # a clumsy smash: open, but what's inside is broken
    inventory = list(state.player.inventory)
    events = perform(state, content, "chest_smash")
    assert any("smashed beyond use" in e.text or e.text.startswith("Inside:") for e in events)
    assert state.player.inventory == inventory or any(e.kind == "find" and e.data.get("item") for e in events)

    state = chest_room(content)
    state.player.agility = -50  # a bungled pick: the needle gets you, but the loot's fine
    hp = state.player.hp
    perform(state, content, "chest")
    assert state.player.hp < hp


def test_the_warden_always_drops_something_good(content):
    """Something rare where the floor allows it (tier capped: the best come later), or a small key."""
    def warden_drop(floor):
        state = generate(5)
        if floor > 1:
            state.floor = floor
            build_floor(state, content)
        stairs = next(r for r in state.rooms if r.fixture == "stairs")
        state.room_id = stairs.id
        rng = random.Random(1)
        rng.random = lambda: 0.99  # no potion, key or bomb: just what the warden always has
        dropped = [e.data["item"] for e in defeat(state, content, rng) if e.kind == "drop"]
        assert len(dropped) == 1
        return content.item(dropped[0]), state

    first, _ = warden_drop(1)
    assert first.key == "small_key"  # nothing rare of tier 1 or less for a warden: a key for a chest instead
    second, state = warden_drop(2)
    assert loot.rare(second) and second.tier <= 2 and second.key in state.rares


def test_something_heavy_breaks_through_a_wall_worth_a_bomb_without_one(content):
    """"I smash through the wall with my axe" (run 59): might, harder than a chest, and no bomb spent."""
    from ptg.intent import Intent
    from ptg.interactions import from_intent

    state, secret = beside_the_secret_room()
    direction = hidden_room_beside(state)
    said = Intent(kind="creative", summary=f"smash through the {direction} wall with my sword", difficulty="hard",
                  success_effects=["nothing"])
    use = from_intent(state, content, said)
    assert use == f"smash:rusty_sword@wall:{direction}"
    state.player.might, hp, bombs = -50, state.player.hp, state.player.bombs
    events = perform(state, content, use)
    assert events[0].kind == "breach" and state.player.hp < hp and direction not in state.room.exits
    state.player.might = 50
    events = perform(state, content, f"breach:{direction}")
    assert events[0].kind == "secret_room" and state.room.exits[direction].to == secret.id
    assert state.player.bombs == bombs and events[0].data["rerollable"]

    state, wrong = decoy_wall()  # nothing behind it: earth
    state.player.might = 50
    events = perform(state, content, f"breach:{wrong}")
    assert "earth" in events[0].text and wrong not in state.room.exits
