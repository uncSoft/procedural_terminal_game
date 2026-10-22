from collections import deque

import pytest

from ptg import layout
from ptg.models import OPPOSITE
from ptg.world import build_floor, generate, render_map

SEEDS = range(80)


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


def floor(seed: int, number: int, content):
    state = generate(seed)
    if number > 1:
        state.floor = number
        build_floor(state, content)
    return state


def test_same_seed_same_run(content):
    assert generate(42).model_dump() == generate(42).model_dump()
    assert generate(42).model_dump() != generate(43).model_dump()
    assert floor(42, 3, content).model_dump() == floor(42, 3, content).model_dump()


def test_each_floor_is_a_different_theme():
    for seed in SEEDS:
        state = generate(seed)
        assert len(set(state.themes)) == 3 and state.theme == state.themes[0]


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("number", [1, 2, 3])
def test_floors_are_well_formed(seed, number, content):
    state = floor(seed, number, content)
    theme = content.themes[state.theme]
    for room in state.rooms:
        for direction, exit_ in room.exits.items():
            assert state.rooms[exit_.to].exits[OPPOSITE[direction]].to == room.id
    assert state.rooms[0].monster is None and state.rooms[0].visited
    assert reachable(state, through_locked=True) == set(range(len(state.rooms)))

    if number < 3:
        stairs = [r for r in state.rooms if r.fixture == "stairs"]
        assert len(stairs) == 1 and stairs[0].monster is not None  # every staircase has a warden
        assert not any(e.locked for r in state.rooms for e in r.exits.values())
    else:
        boss = [r for r in state.rooms if r.is_boss]
        assert len(boss) == 1 and boss[0].monster.key == theme.boss
        assert reachable(state, through_locked=False) == set(range(len(state.rooms))) - {boss[0].id}
        keys = [r for r in state.rooms for f in r.features if theme.key_item in f.loot and not f.hidden]
        assert len(keys) == 1 and not keys[0].is_boss


@pytest.mark.parametrize("seed", range(20))
def test_room_layouts(seed, content):
    state = floor(seed, 2, content)
    for room in state.rooms:
        assert len(room.grid) == layout.HEIGHT + 2 and all(len(row) == layout.WIDTH + 2 for row in room.grid)
        for direction in room.exits:
            x, y = layout.DOORS[direction]
            assert room.grid[y][x] == "+"
        for feature in room.features:
            x, y = feature.pos
            assert 1 <= x <= layout.WIDTH and 1 <= y <= layout.HEIGHT


def test_elites_and_wardens_get_stronger(content):
    elites = [r.monster for seed in SEEDS for r in floor(seed, 3, content).rooms if r.monster and r.monster.elite]
    assert elites
    for monster in elites:
        assert monster.name.split()[0] == monster.elite


def test_ghost_haunts_its_floor(content):
    ghost = {"id": 7, "name": "Chubrock", "level": 3, "floor": 1, "items": ["hand_axe", "healing_potion"],
             "gold": 40, "epitaph": "Tried to tax a rat.", "cause": "slain by Giant Rat on floor 1"}
    state = generate(5, ghost=ghost)
    haunted = [r for r in state.rooms if r.monster and r.monster.ghost_of == "Chubrock"]
    assert len(haunted) == 1
    remains = [f for f in haunted[0].features if f.name == "Chubrock's remains"]
    assert remains and remains[0].loot == ["hand_axe", "healing_potion"]


def test_map_shows_you_and_neighbours():
    state = generate(5)
    text = "\n".join(render_map(state))
    assert text.count("@") == 1
    assert sum(text.count(g) for g in "?>†■◊") == len(state.room.exits)


def test_room_render_has_you_and_legend(content):
    state = generate(5)
    lines = layout.plain_lines(state, content)
    assert sum(line.count("@") for line in lines[:-1]) == 1
    assert "@ you" in lines[-1]
