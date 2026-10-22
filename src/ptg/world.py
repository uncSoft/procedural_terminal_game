"""Seeded dungeon generation. A run is three floors, each a different theme; the same seed always builds
the same run. Floors are built one at a time as you descend."""

from __future__ import annotations

import random
from collections import deque

from . import dice, layout
from .content import Content, load_content
from .models import DELTA, DIRECTIONS, FLOORS, OPPOSITE, Exit, Feature, GameState, MonsterState, Player, Room

HIDDEN_FEATURES = ["a loose flagstone", "a hollow-sounding wall", "a hidden alcove", "a false-bottomed niche"]
ELITES = {
    "Frenzied": {"attack_mod": 2},
    "Armored": {"defense_mod": 2},
    "Hulking": {"hp_mult": 1.5, "damage_mod": 1},
    "Cursed": {"reward_mult": 2.0},
}
THEME_TRINKETS = {"sunken_crypt": "holy_water", "goblin_warren": "bag_of_marbles", "overgrown_ruins": "oil_flask"}


def generate(seed: int, player_name: str = "Adventurer", content: Content | None = None,
             player: Player | None = None, ghost: dict | None = None) -> GameState:
    """Start a new run on floor 1."""
    content = content or load_content()
    rng = dice.stream(seed, "run")
    themes = sorted(content.themes)
    rng.shuffle(themes)
    themes = (themes * FLOORS)[:FLOORS]
    state = GameState(seed=seed, theme=themes[0], themes=themes, rooms=[],
                      player=player or Player(name=player_name), ghost=ghost)
    build_floor(state, content)
    return state


def build_floor(state: GameState, content: Content) -> None:
    """Replace state.rooms with a freshly generated floor for state.floor."""
    ghost = state.ghost
    rng = dice.stream(state.seed, "floor", state.floor)
    theme = content.themes[state.themes[state.floor - 1]]
    state.theme = theme.key
    final = state.floor >= state.floors_total
    size = 8 if final else 7

    coords, edges = _layout(rng, size)
    neighbors = _adjacency(len(coords), edges)
    distance = _bfs(neighbors, 0)
    leaves = [i for i in range(1, len(coords)) if len(neighbors[i]) == 1]
    end_id = max(leaves or range(1, len(coords)), key=lambda i: (distance[i], i))
    _add_loops(rng, coords, edges, exclude=end_id)
    neighbors = _adjacency(len(coords), edges)
    distance = _bfs(neighbors, 0)
    max_distance = max(distance.values())

    rooms = _build_rooms(rng, content, theme, coords, neighbors, distance, end_id, final)
    if final:
        gate = next(iter(neighbors[end_id]))
        for exit_ in rooms[gate].exits.values():
            if exit_.to == end_id:
                exit_.locked = True
    else:
        rooms[end_id].fixture = "stairs"

    others = [r for r in rooms if r.id not in (0, end_id)]
    for room, fixture in zip(rng.sample(others, min(2, len(others))), rng.sample(["shrine", "chest", "fountain"], 2)):
        room.fixture = fixture

    _place_monsters(rng, content, state, theme, rooms, max_distance, end_id, final)
    _place_loot(rng, state, theme, rooms, end_id, max_distance, final)
    if ghost and ghost.get("floor", 1) == state.floor:
        _place_ghost(rng, content, rooms, end_id, ghost)

    for room in rooms:
        layout.build(dice.stream(state.seed, "layout", state.floor, room.id), room,
                     content.archetypes[room.archetype].decor)

    state.rooms = rooms
    state.room_id = 0
    state.prev_room_id = None
    rooms[0].visited = True


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


def _build_rooms(rng, content, theme, coords, neighbors, distance, end_id, final) -> list[Room]:
    pool: list[str] = []
    used_names: set[str] = set()
    rooms = []
    for i, (x, y) in enumerate(coords):
        boss_room = final and i == end_id
        if boss_room:
            archetype = content.archetypes[theme.boss_room]
        else:
            if not pool:
                pool = list(theme.archetypes)
                rng.shuffle(pool)
            archetype = content.archetypes[pool.pop()]
        names = [n for n in archetype.names if n not in used_names] or archetype.names
        name = rng.choice(names)
        used_names.add(name)
        count = len(archetype.features) if boss_room else rng.randint(1, min(2, len(archetype.features)))
        features = [Feature(name=f) for f in rng.sample(archetype.features, count)]
        room = Room(id=i, x=x, y=y, name=name, archetype=archetype.key, distance=distance[i],
                    features=features, is_boss=boss_room)
        for j in sorted(neighbors[i]):
            dx, dy = coords[j][0] - x, coords[j][1] - y
            direction = next(d for d, delta in DELTA.items() if delta == (dx, dy))
            room.exits[direction] = Exit(to=j)
        rooms.append(room)
    for room in rooms:
        for direction, exit_ in room.exits.items():
            assert rooms[exit_.to].exits[OPPOSITE[direction]].to == room.id
    return rooms


def monster_for(rng: random.Random, content: Content, theme_key: str, tier: int, elite: str = "") -> MonsterState:
    theme = content.themes[theme_key]
    pool = [m for m in content.monsters.values()
            if not (m.boss or m.ghost) and set(m.tags) & set(theme.monster_tags)]
    exact = [m for m in pool if m.tier == tier] or [m for m in pool if m.tier <= tier] or pool
    chosen = rng.choice(sorted(exact, key=lambda m: m.key))
    monster = MonsterState(key=chosen.key, name=chosen.name, hp=chosen.hp, max_hp=chosen.hp)
    if elite:
        mods = ELITES[elite]
        monster.elite = elite
        monster.name = f"{elite} {chosen.name}"
        monster.max_hp = monster.hp = round(chosen.hp * mods.get("hp_mult", 1.0))
        monster.attack_mod = mods.get("attack_mod", 0)
        monster.defense_mod = mods.get("defense_mod", 0)
        monster.damage_mod = mods.get("damage_mod", 0)
        monster.reward_mult = mods.get("reward_mult", 1.5)
    return monster


def tier_for(distance: int, max_distance: int, floor: int = 1) -> int:
    """Floor 1 ramps from tier 1 to 2, floor 2 from 2 to 3, floor 3 is tier 3 nearly everywhere."""
    depth = distance / max(1, max_distance)
    return max(1, min(3, floor + (1 if depth > 0.6 else 0)))


def _place_monsters(rng, content, state, theme, rooms: list[Room], max_distance: int, end_id: int, final: bool) -> None:
    if final:
        boss = content.monster(theme.boss)
        rooms[end_id].monster = MonsterState(key=boss.key, name=boss.name, hp=boss.hp, max_hp=boss.hp)
    else:
        # Every staircase has a warden; from floor 2 on, it's an elite.
        elite = rng.choice(sorted(ELITES)) if state.floor > 1 else ""
        rooms[end_id].monster = monster_for(rng, content, theme.key, min(3, state.floor + 1), elite=elite)

    candidates = [r for r in rooms if r.id not in (0, end_id) and r.fixture != "shrine"]
    rng.shuffle(candidates)
    elite_chance = {1: 0.0, 2: 0.25, 3: 0.4}.get(state.floor, 0.4)
    for room in candidates[:max(2, round(len(candidates) * 0.5))]:
        elite = rng.choice(sorted(ELITES)) if rng.random() < elite_chance else ""
        room.monster = monster_for(rng, content, theme.key, tier_for(room.distance, max_distance, state.floor), elite)


def _place_loot(rng, state: GameState, theme, rooms: list[Room], end_id: int, max_distance: int, final: bool) -> None:
    others = [r for r in rooms if r.id not in (0, end_id)]
    if final:
        # The key sits in a visible feature somewhere past the halfway point (never in the boss room).
        deep = [r for r in others if r.distance >= max(1, max_distance // 2)] or others
        rng.choice(rng.choice(deep).features).loot.append(theme.key_item)

    loot = {
        1: ["hand_axe", "leather_jerkin", "healing_potion", "healing_potion", "stale_bread"],
        2: [rng.choice(["war_pick", "chain_shirt"]), "healing_potion", "healing_potion", "smoke_bomb", "cheese_wheel"],
        3: ["greater_healing_potion", "healing_potion", "healing_potion", rng.choice(["war_pick", "chain_shirt"])],
    }.get(state.floor, ["healing_potion"])
    loot.append(THEME_TRINKETS.get(theme.key, "oil_flask"))
    for item in loot:
        room = rng.choice(others)
        if item.endswith("potion") and rng.random() < 0.35:
            room.items.append(item)
        else:
            rng.choice(room.features).loot.append(item)

    for room in others:
        for feature in room.features:
            if not feature.loot and rng.random() < 0.5:
                feature.gold = rng.randint(2, 8) * max(1, room.distance) + 2 * state.floor

    secret_room = rng.choice(others)
    secret_room.features.append(Feature(
        name=rng.choice(HIDDEN_FEATURES), hidden=True, gold=rng.randint(15, 30) * state.floor,
        loot=[rng.choice(["silvered_blade", "scale_hauberk", "greater_healing_potion", "lucky_charm"])],
    ))


def _place_ghost(rng, content: Content, rooms: list[Room], end_id: int, ghost: dict) -> None:
    """A previous adventurer died on this floor. Their ghost guards what they carried."""
    spots = [r for r in rooms if r.id not in (0, end_id) and not r.fixture] or [r for r in rooms if r.id != 0]
    room = rng.choice(spots)
    base = content.monster("ghost")
    level = int(ghost.get("level", 1))
    hp = base.hp + 4 * (level - 1)
    room.monster = MonsterState(key="ghost", name=f"Ghost of {ghost['name']}", hp=hp, max_hp=hp,
                                attack_mod=level // 2, ghost_id=ghost.get("id"), ghost_of=ghost["name"],
                                reward_mult=2.0)
    items = [k for k in ghost.get("items", []) if k in content.items and content.item(k).kind != "key"][:3]
    room.features.append(Feature(name=f"{ghost['name']}'s remains", loot=items, gold=int(ghost.get("gold", 0)) // 2))


def render_map(state: GameState) -> list[str]:
    """ASCII map of this floor. @ you, ! danger, ? unexplored, > stairs, † shrine, ■ chest, ◊ fountain."""
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
        grid[cy][cx - 1], grid[cy][cx], grid[cy][cx + 1] = "[", map_glyph(state, room), "]"
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


def map_glyph(state: GameState, room: Room) -> str:
    if room.id == state.room_id:
        return "@"
    if room.monster and room.monster.hostile and room.visited:
        return "!"
    if room.fixture and not room.fixture_used:
        return layout.FIXTURE_GLYPHS[room.fixture]  # you can see what's through the door, like Tiny Rogues
    if room.is_boss:
        return "B"
    return "#" if room.visited else "?"
