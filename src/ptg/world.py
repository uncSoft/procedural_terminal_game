"""Seeded dungeon generation. The same seed always builds the same dungeon."""

from __future__ import annotations

import random
from collections import deque

from . import dice
from .content import Content, load_content
from .models import DELTA, DIRECTIONS, OPPOSITE, Exit, Feature, GameState, MonsterState, Player, Room

HIDDEN_FEATURES = ["a loose flagstone", "a hollow-sounding wall", "a hidden alcove", "a false-bottomed niche"]


def generate(seed: int, player_name: str = "Adventurer", size: int = 10, content: Content | None = None) -> GameState:
    content = content or load_content()
    rng = dice.stream(seed, "world")
    theme = content.themes[rng.choice(sorted(content.themes))]

    coords, edges = _layout(rng, size)
    neighbors = _adjacency(len(coords), edges)
    distance = _bfs(neighbors, 0)

    # The boss waits in the farthest dead end, behind the dungeon's only locked door.
    leaves = [i for i in range(1, len(coords)) if len(neighbors[i]) == 1]
    boss_id = max(leaves or range(1, len(coords)), key=lambda i: (distance[i], i))
    _add_loops(rng, coords, edges, exclude=boss_id)
    neighbors = _adjacency(len(coords), edges)
    distance = _bfs(neighbors, 0)
    max_distance = max(distance.values())

    rooms = _build_rooms(rng, content, theme.key, coords, neighbors, distance, boss_id)
    gate = next(iter(neighbors[boss_id]))
    for exit_ in rooms[gate].exits.values():
        if exit_.to == boss_id:
            exit_.locked = True

    _place_monsters(rng, content, theme, rooms, max_distance, boss_id)
    _place_loot(rng, theme, rooms, boss_id, max_distance)

    state = GameState(seed=seed, theme=theme.key, rooms=rooms, player=Player(name=player_name))
    state.room.visited = True
    return state


def _layout(rng: random.Random, size: int) -> tuple[list[tuple[int, int]], set[frozenset[int]]]:
    """Grow rooms on a grid, favouring recent rooms so the dungeon stretches out instead of clumping."""
    coords = [(0, 0)]
    index = {(0, 0): 0}
    edges: set[frozenset[int]] = set()
    while len(coords) < size:
        source = rng.choice(coords[-3:]) if rng.random() < 0.6 else rng.choice(coords)
        dx, dy = DELTA[rng.choice(DIRECTIONS)]
        cell = (source[0] + dx, source[1] + dy)
        if cell in index:
            continue
        index[cell] = len(coords)
        coords.append(cell)
        edges.add(frozenset((index[source], index[cell])))
    return coords, edges


def _add_loops(rng: random.Random, coords: list[tuple[int, int]], edges: set[frozenset[int]], exclude: int) -> None:
    index = {c: i for i, c in enumerate(coords)}
    candidates = []
    for i, (x, y) in enumerate(coords):
        for dx, dy in ((1, 0), (0, 1)):
            j = index.get((x + dx, y + dy))
            if j is not None and exclude not in (i, j) and frozenset((i, j)) not in edges:
                candidates.append(frozenset((i, j)))
    rng.shuffle(candidates)
    edges.update(candidates[:2])


def _adjacency(count: int, edges: set[frozenset[int]]) -> dict[int, set[int]]:
    neighbors: dict[int, set[int]] = {i: set() for i in range(count)}
    for edge in edges:
        a, b = tuple(edge)
        neighbors[a].add(b)
        neighbors[b].add(a)
    return neighbors


def _bfs(neighbors: dict[int, set[int]], start: int) -> dict[int, int]:
    distance = {start: 0}
    queue = deque([start])
    while queue:
        current = queue.popleft()
        for nxt in sorted(neighbors[current]):
            if nxt not in distance:
                distance[nxt] = distance[current] + 1
                queue.append(nxt)
    return distance


def _build_rooms(rng, content, theme_key, coords, neighbors, distance, boss_id) -> list[Room]:
    theme = content.themes[theme_key]
    pool: list[str] = []
    used_names: set[str] = set()
    rooms = []
    for i, (x, y) in enumerate(coords):
        if i == boss_id:
            archetype = content.archetypes[theme.boss_room]
        else:
            if not pool:
                pool = list(theme.archetypes)
                rng.shuffle(pool)
            archetype = content.archetypes[pool.pop()]
        names = [n for n in archetype.names if n not in used_names] or archetype.names
        name = rng.choice(names)
        used_names.add(name)
        count = len(archetype.features) if i == boss_id else rng.randint(1, min(2, len(archetype.features)))
        features = [Feature(name=f) for f in rng.sample(archetype.features, count)]
        room = Room(id=i, x=x, y=y, name=name, archetype=archetype.key, distance=distance[i],
                    features=features, is_boss=i == boss_id)
        for j in sorted(neighbors[i]):
            dx, dy = coords[j][0] - x, coords[j][1] - y
            direction = next(d for d, delta in DELTA.items() if delta == (dx, dy))
            room.exits[direction] = Exit(to=j)
        rooms.append(room)
    for room in rooms:
        for direction, exit_ in room.exits.items():
            assert rooms[exit_.to].exits[OPPOSITE[direction]].to == room.id
    return rooms


def monster_for(rng: random.Random, content: Content, theme_key: str, tier: int) -> MonsterState:
    theme = content.themes[theme_key]
    pool = [m for m in content.monsters.values() if not m.boss and set(m.tags) & set(theme.monster_tags)]
    exact = [m for m in pool if m.tier == tier] or [m for m in pool if m.tier <= tier] or pool
    chosen = rng.choice(sorted(exact, key=lambda m: m.key))
    return MonsterState(key=chosen.key, name=chosen.name, hp=chosen.hp, max_hp=chosen.hp)


def tier_for(distance: int, max_distance: int) -> int:
    return max(1, min(3, 1 + round(2 * distance / max(1, max_distance))))


def _place_monsters(rng, content, theme, rooms: list[Room], max_distance: int, boss_id: int) -> None:
    boss = content.monster(theme.boss)
    rooms[boss_id].monster = MonsterState(key=boss.key, name=boss.name, hp=boss.hp, max_hp=boss.hp)

    candidates = [r for r in rooms if r.id not in (0, boss_id)]
    rng.shuffle(candidates)
    wanted = max(3, round(len(candidates) * 0.45))
    for room in candidates[:wanted]:
        room.monster = monster_for(rng, content, theme.key, tier_for(room.distance, max_distance))


def _place_loot(rng, theme, rooms: list[Room], boss_id: int, max_distance: int) -> None:
    others = [r for r in rooms if r.id not in (0, boss_id)]

    # The key sits in a visible feature somewhere past the halfway point (but never in the boss room).
    deep = [r for r in others if r.distance >= max(1, max_distance // 2)] or others
    key_room = rng.choice(deep)
    rng.choice(key_room.features).loot.append(theme.key_item)

    loot = ["hand_axe", "leather_jerkin", "healing_potion", "healing_potion", "healing_potion", "smoke_bomb", "stale_bread"]
    loot.append(rng.choice(["war_pick", "chain_shirt"]))
    for item in loot:
        room = rng.choice(others)
        if item.endswith("potion") and rng.random() < 0.35:
            room.items.append(item)
        else:
            rng.choice(room.features).loot.append(item)

    for room in others:
        for feature in room.features:
            if not feature.loot and rng.random() < 0.5:
                feature.gold = rng.randint(2, 8) * max(1, room.distance)

    secret_room = rng.choice(others)
    secret_room.features.append(Feature(
        name=rng.choice(HIDDEN_FEATURES), hidden=True, gold=rng.randint(15, 30),
        loot=[rng.choice(["silvered_blade", "scale_hauberk", "greater_healing_potion"])],
    ))


def render_map(state: GameState) -> list[str]:
    """ASCII map of visited rooms and the doors leading out of them. @ is you, ? is unexplored."""
    known = {r.id for r in state.rooms if r.visited}
    for room_id in list(known):
        known.update(e.to for e in state.rooms[room_id].exits.values())
    rooms = [state.rooms[i] for i in known]
    min_x, max_x = min(r.x for r in rooms), max(r.x for r in rooms)
    min_y, max_y = min(r.y for r in rooms), max(r.y for r in rooms)
    width, height = (max_x - min_x) * 4 + 3, (max_y - min_y) * 2 + 1
    grid = [[" "] * width for _ in range(height)]
    for room in rooms:
        cx, cy = (room.x - min_x) * 4 + 1, (room.y - min_y) * 2
        if room.id == state.room_id:
            glyph = "@"
        elif not room.visited:
            glyph = "?"
        elif room.monster and room.monster.hostile:
            glyph = "!"
        else:
            glyph = "#"
        grid[cy][cx - 1], grid[cy][cx], grid[cy][cx + 1] = "[", glyph, "]"
        if not room.visited:
            continue
        for direction, exit_ in room.exits.items():
            door = "=" if exit_.locked else ("-" if direction in ("east", "west") else "|")
            if direction == "east":
                grid[cy][cx + 2] = door
            elif direction == "west":
                grid[cy][cx - 2] = door
            elif direction == "south":
                grid[cy + 1][cx] = door
            elif direction == "north":
                grid[cy - 1][cx] = door
    return ["".join(row).rstrip() for row in grid]
