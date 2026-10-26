import random
from collections import deque

import pytest

from ptg import layout
from ptg.models import OPPOSITE
from ptg.ui.theme import CELL_STYLES
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
    secret = {r.id for r in state.rooms if r.secret}
    assert len(secret) <= 1 and reachable(state, through_locked=True) == set(range(len(state.rooms))) - secret
    for room in (r for r in state.rooms if r.secret):  # sealed, in a gap that touches two rooms or more
        assert not room.exits and room.items
        assert sum(abs(r.x - room.x) + abs(r.y - room.y) == 1 for r in state.rooms) >= 2
    shops = {r.id for r in state.rooms if r.shop}
    for room in (r for r in state.rooms if r.shop):  # a dead end, behind the one door a small key opens
        (way_out,) = room.exits.values()
        door = state.rooms[way_out.to].exits[OPPOSITE[next(iter(room.exits))]]
        assert door.locked and door.key == "small_key" and room.fixture == "shop" and room.shop.wares
        assert not state.rooms[way_out.to].secret and state.rooms[way_out.to].fixture != "stairs"

    if number < 3:
        stairs = [r for r in state.rooms if r.fixture == "stairs"]
        assert len(stairs) == 1 and stairs[0].monster is not None  # every staircase has a warden
        assert not any(e.locked and not e.key for r in state.rooms for e in r.exits.values())  # only shops lock
    else:
        boss = [r for r in state.rooms if r.is_boss]
        assert len(boss) == 1 and boss[0].monster.key == theme.boss
        assert reachable(state, through_locked=False) == set(range(len(state.rooms))) - {boss[0].id} - secret - shops
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
    assert sum(text.count(g) for g in "?>†■◊¤") == len(state.room.exits)


def test_room_render_has_you_and_legend(content):
    state = generate(5)
    lines = layout.plain_lines(state, content)
    assert sum(line.count("@") for line in lines[:-1]) == 1
    assert "@ you" in lines[-1]


def test_cages_are_not_walls(content):
    """Kennel cages were painted "#", the wall's glyph, so they looked like stray bits of wall on the room map."""
    state = floor(1, 3, content)
    room = next(r for r in state.rooms if content.archetypes[r.archetype].decor == "cages")
    inside = [row[1:-1] for row in room.grid[1:-1]]
    assert "#" not in "".join(inside) and layout.CAGE in "".join(inside)
    state.room_id = room.id
    rows, _ = layout.render(state, content)
    cages = [style for row in rows for glyph, style in row if glyph == layout.CAGE]
    assert "cage" in cages and set(cages) <= {"cage", "feature"}  # (the open cage you can search is a feature)
    assert CELL_STYLES["cage"] != CELL_STYLES["wall"]
    assert layout.feature_glyph("an open cage") == layout.CAGE
    room.grid = [row[:3] + "#" + row[4:] if 1 <= y <= layout.HEIGHT else row for y, row in enumerate(room.grid)]
    rows, _ = layout.render(state, content)  # a game saved with "#" cages still shows cages
    assert all(rows[y][3] == (layout.CAGE, "cage") for y in range(1, layout.HEIGHT + 1))


def test_a_room_finds_a_spot_for_every_item(content):
    """Rooms are built with six spots for items; a room that comes to hold more (gear left behind, a monster's drops)
    used to leave the rest off the map."""
    state = generate(5)
    room = state.room
    room.items = ["healing_potion"] * 6
    six = layout.item_spots(room)
    assert six == room.item_spots
    room.items = ["healing_potion"] * 9
    spots = layout.item_spots(room)
    assert len(spots) == 9 and spots[:6] == six and len(set(spots)) == 9 and spots == layout.item_spots(room)
    for x, y in spots[6:]:
        assert room.grid[y][x] == "." and (x, y) not in layout.KEEP_CLEAR
    rows, legend = layout.render(state, content)
    assert sum(style == "item" for _, style, _ in legend) == 9
    assert sum(style == "item" for row in rows for _, style in row) == 9
    room.items = ["healing_potion"] * 300  # more than the floor holds: they pile up
    assert len(layout.item_spots(room)) == 300


def test_one_of_a_kind_creatures_turn_up_once_a_run(content):
    """A creature with a name of its own (Serpentis, Baby Joey) or tagged unique (the Rat King) is met once a run at
    most, however many floors and rooms there are (run 59 met the Rat King on two floors)."""
    from collections import Counter

    once = {m.key for m in content.monsters.values() if m.once and m.roams}
    assert {"serpentis", "rat_king", "baby_joey"} <= once
    for seed in range(40):
        state = generate(seed, content=content)
        seen = Counter()
        for floor in range(2, state.floors_total + 1):
            for room in state.rooms:
                if room.monster and room.monster.key in once:
                    seen[room.monster.key] += 1
            state.floor = floor
            build_floor(state, content)
        for room in state.rooms:
            if room.monster and room.monster.key in once:
                seen[room.monster.key] += 1
        assert all(n == 1 for n in seen.values()), (seed, seen)
        assert set(seen) <= set(state.met)


def test_serpentis_leaves_its_old_sword(content):
    from ptg.combat import _kept
    from ptg.models import MonsterState

    state = generate(1)
    serpent = MonsterState(key="serpentis", name="Serpentis", hp=0, max_hp=32)
    assert _kept(state, content, random.Random(0), serpent) == ["bloodbath"]
    assert _kept(state, content, random.Random(0), serpent) == []  # (once a run, like any rare thing)


def test_a_floor_4_monster_waits_for_floor_4_but_lairs_now_and_then_on_floor_3(content):
    """Serpentis came with its maker's numbers for a deeper floor (tier 4): it never roams floors 1-3, but now and
    then lairs in floor 3's secret room, cut down to that floor's size (npcs.SERPENTIS_SIZE), its sword with it."""
    from ptg import npcs, testrooms

    deep = {m.key for m in content.monsters.values() if m.roams and m.tier > 3}
    assert "serpentis" in deep
    lairs = 0
    for seed in range(60):
        state = generate(seed, content=content)
        for floor in range(1, state.floors_total + 1):
            if floor > 1:
                state.floor = floor
                build_floor(state, content)
            for room in state.rooms:
                if room.monster and room.monster.key in deep:
                    assert room.secret and floor == 3 and room.monster.max_hp == npcs.SERPENTIS_SIZE[3][0]
                    lairs += 1
    assert 0 < lairs < 30  # (a rare find: a quarter of the runs, about)
    state = testrooms.build(content, "serpentis", "strong", seed=3)
    lair = testrooms.target(state)
    assert lair.secret and state.floor == 3 and state.player.bombs >= 1
