from collections import deque

import pytest

from ptg.models import OPPOSITE
from ptg.world import generate, render_map

SEEDS = range(200)


def reachable(state, through_locked: bool) -> set[int]:
    seen, queue = {0}, deque([0])
    while queue:
        room = state.rooms[queue.popleft()]
        for exit_ in room.exits.values():
            if exit_.locked and not through_locked:
                continue
            if exit_.to not in seen:
                seen.add(exit_.to)
                queue.append(exit_.to)
    return seen


def test_same_seed_same_dungeon():
    assert generate(42).model_dump() == generate(42).model_dump()
    assert generate(42).model_dump() != generate(43).model_dump()


@pytest.mark.parametrize("seed", SEEDS)
def test_dungeon_is_well_formed(seed, content):
    state = generate(seed)
    theme = content.themes[state.theme]
    boss_rooms = [r for r in state.rooms if r.is_boss]
    assert len(boss_rooms) == 1
    boss = boss_rooms[0]
    assert boss.monster and boss.monster.key == theme.boss

    # Doors connect both ways.
    for room in state.rooms:
        for direction, exit_ in room.exits.items():
            assert state.rooms[exit_.to].exits[OPPOSITE[direction]].to == room.id

    # Everything is reachable, and the boss room only through the locked door.
    assert reachable(state, through_locked=True) == set(range(len(state.rooms)))
    assert reachable(state, through_locked=False) == set(range(len(state.rooms))) - {boss.id}

    # The key is in a visible feature of a room you can reach before the boss.
    key_rooms = [r for r in state.rooms for f in r.features if theme.key_item in f.loot and not f.hidden]
    assert len(key_rooms) == 1 and not key_rooms[0].is_boss
    assert state.rooms[0].monster is None


def test_map_shows_you_and_neighbours():
    state = generate(5)
    lines = render_map(state)
    text = "\n".join(lines)
    assert text.count("@") == 1
    assert text.count("?") == len(state.room.exits)
