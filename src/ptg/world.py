"""Seeded dungeon generation. A run is four floors: three dungeons, each a different theme (the third's boss guards
the stairs down), then Norfel, always the fourth, with Serpentis at its bottom; once you've beaten her in any run, five,
the Underbloom under her (models.DEEPEST: meta.start_run). The same seed always builds the same run. Floors are built
one at a time as you descend."""

from __future__ import annotations

import math
import random
from collections import deque

from . import dice, hazards, layout, loot, npcs
from .light import WRAPS
from .content import Content, load_content
from .models import (DELTA, DIRECTIONS, FLOORS, OPPOSITE, Exit, Feature, GameState, MonsterState, Player,
                     Room, Shop, Ware)

HIDDEN_FEATURES = ["a loose flagstone", "a hollow-sounding wall", "a hidden alcove", "a false-bottomed niche"]
ELITES = {
    "Frenzied": {"attack_mod": 2},
    "Armored": {"defense_mod": 2},
    "Hulking": {"hp_mult": 1.5, "damage_mod": 1},
    "Cursed": {"reward_mult": 2.0},
}
ROOMS = {1: 7, 2: 7, 3: 8, 4: 10, 5: 10}  # rooms on each floor (and a secret one, and maybe a shop, and a lair)
# The deeper, the stronger the same monsters are, past where their tiers stop (tier_for): from floor 3, so it isn't
# where they stop growing (docs/plans/combat-and-balance.md §2). A floor deeper than the table has its deepest row.
DEPTH = {3: {"hp_mult": 1.1, "attack_mod": 0, "defense_mod": 0, "damage_mod": 1},
         4: {"hp_mult": 1.25, "attack_mod": 1, "defense_mod": 0, "damage_mod": 1},
         5: {"hp_mult": 1.35, "attack_mod": 2, "defense_mod": 1, "damage_mod": 1}}
VENOMOUS = 0.5  # on a floor with poison of its own, how many of its monsters bite with venom (combat.VENOM)
# Every dungeon's boss holds it whichever floor it's on, not only as the last dungeon: at its stairs on an earlier one,
# cut down to that floor's size (HP, attack, defense, damage off its dice, as npcs.sized takes them), so every
# staircase has a boss with its own clips at it (docs/plans/playtest-2026-10-30.md §2.2). Worth a warden's tier there,
# and half a boss's souls. About a floor-1 warden (16 HP or so, a d8) and a floor-2 one (an elite); the Goblin King
# alone was at (25, 3, 12, -3) on floor 1, and the bot's average player died to him there a run in four. On floor 1
# King Mouse may take the boss's place (npcs.FLOATING): the floor 2 one is always its dungeon's own.
EARLY_SIZES = {1: (20, 3, 12, -4), 2: (34, 4, 13, -3)}
EARLY_BOSSES = {key: EARLY_SIZES for key in ("goblin_king", "drowned_abbot", "thornmother")}
EARLY_BOSS_SOULS = 0.5
# Weak roaming monsters on the first floors come in groups now and then (combat.foes): a floor's chance, the most HP
# one may have to, and how many more of its kind come with it (each count's weight).
GROUPS = {1: 0.25, 2: 0.3}
WEAK = 8
GROUP_SIZES = {1: 3, 2: 1}
# A floor's lair behind a web door (Exit.webbed): its room and who's in it. Only fire gets through (rules._burn_web).
LAIRS = {"underbloom": ("matriarchs_lair", "the_sporefang_matriarch")}

def generate(seed: int, player_name: str = "Adventurer", content: Content | None = None,
             player: Player | None = None, ghost: dict | None = None, floors: int = FLOORS) -> GameState:
    """Start a new run on floor 1, `floors` deep (FLOORS; DEEPEST once you've won one: meta.start_run)."""
    content = content or load_content()
    rng = dice.stream(seed, "run")
    themes = sorted(k for k, t in content.themes.items() if not t.floor)  # (the dungeons, shuffled)
    rng.shuffle(themes)
    fixed = {t.floor: t.key for t in content.themes.values() if t.floor}  # (Norfel the fourth, the Underbloom the fifth)
    themes = [fixed.get(floor) or themes[(floor - 1) % len(themes)] for floor in range(1, floors + 1)]
    state = GameState(seed=seed, theme=themes[0], themes=themes, rooms=[], floors_total=floors,
                      player=player or Player(name=player_name), ghost=ghost)
    for key in (k for k in [*state.player.gear, *state.player.inventory] if k in content.items):
        loot.noted(content, state.rares, key)  # (what you start with is this run's one of it: a blessing's Rabbit's Foot)
    build_floor(state, content)
    return state


def build_floor(state: GameState, content: Content) -> None:
    """Replace state.rooms with a freshly generated floor for state.floor."""
    ghost = state.ghost
    rng = dice.stream(state.seed, "floor", state.floor)
    theme = content.themes[state.themes[state.floor - 1]]
    state.theme = theme.key
    final, boss = state.final_floor, state.boss_floor and bool(theme.boss)  # (one still being made waits for its own)
    size = ROOMS.get(state.floor, 8)

    coords, edges = _layout(rng, size)
    neighbors = _adjacency(len(coords), edges)
    distance = _bfs(neighbors, 0)
    leaves = [i for i in range(1, len(coords)) if len(neighbors[i]) == 1]
    end_id = max(leaves or range(1, len(coords)), key=lambda i: (distance[i], i))
    _add_loops(rng, coords, edges, exclude=end_id)
    neighbors = _adjacency(len(coords), edges)
    distance = _bfs(neighbors, 0)
    max_distance = max(distance.values())

    rooms = _build_rooms(rng, content, theme, coords, neighbors, distance, end_id, boss)
    if theme.status == "poison":  # a river on the way to the boss, a gas vent somewhere else
        hazards.shape(state, content, rooms, end_id)
    if boss:
        gate = next(iter(neighbors[end_id]))
        for exit_ in rooms[gate].exits.values():
            if exit_.to == end_id:
                exit_.locked = True
    if not final:  # (on the last dungeon's floor, behind its boss)
        rooms[end_id].fixture = "stairs"

    others = [r for r in rooms if r.id not in (0, end_id)]
    spots = rng.sample(others, min(2, len(others)))  # (drawn first, as ever: the same seed, the same floors 1-3)
    # A floor with poison of its own always has a shrine (its free cure); any other, two of the three.
    fixtures = ["shrine", rng.choice(["chest", "fountain"])] if theme.status else \
        rng.sample(["shrine", "chest", "fountain"], 2)
    for room, fixture in zip(spots, fixtures):
        room.fixture = fixture

    _place_monsters(rng, content, state, theme, rooms, end_id, boss)
    _place_loot(rng, content, state, theme, rooms, end_id, max_distance, boss)
    if ghost and ghost.get("floor", 1) == state.floor:
        _place_ghost(rng, content, state, rooms, end_id, ghost)
    secret = _secret_room(rng, content, state, theme, rooms)
    if secret:
        rooms.append(secret)
    shop = _shop(state, content, rooms, end_id)
    if shop:
        rooms.append(shop)
    lair = _lair(state, content, rooms, end_id)
    if lair:
        rooms.append(lair)
    npcs.place(state, content, rooms, end_id)  # Lucky Lenny, Swoogy, King Mouse at the stairs...

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


def _build_rooms(rng, content, theme, coords, neighbors, distance, end_id, boss) -> list[Room]:
    pool: list[str] = []
    used_names: set[str] = set()
    rooms = []
    for i, (x, y) in enumerate(coords):
        boss_room = boss and i == end_id
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


def monster_for(rng: random.Random, content: Content, theme_key: str, tier: int, elite: str = "",
                met: list[str] | None = None, floor: int = 1) -> MonsterState:
    """A monster of the theme's for a tier. One of a kind (MonsterDef.once) that's in `met` already isn't picked
    again, and one picked now is noted there. Below the dungeons it's stronger (DEPTH), and on a floor with poison of
    its own, it may bite with venom (VENOMOUS)."""
    theme = content.themes[theme_key]
    pool = [m for m in content.monsters.values()
            if m.roams and m.lives_in(theme) and not (m.once and m.key in (met or ()))]
    pool = [m for m in pool if not m.floors or floor in m.floors] or pool  # (kept to some floors: MonsterDef.floors)
    exact = [m for m in pool if m.tier == tier] or [m for m in pool if m.tier <= tier] or pool
    chosen = rng.choice(sorted(exact, key=lambda m: m.key))
    if chosen.once and met is not None:
        met.append(chosen.key)
    monster = MonsterState(key=chosen.key, name=chosen.name, hp=chosen.hp, max_hp=chosen.hp)
    named = "venom" in chosen.name.lower()  # (a Venom Toad always has it there, and isn't "Venomous Venom Toad")
    if theme.status == "poison" and "venom" not in chosen.tricks and (rng.random() < VENOMOUS or named):
        monster.tricks.append("venom")
        monster.name = chosen.name if named else titled("Venomous", chosen.name)
    deep = depth(floor)
    if deep:
        monster.max_hp = monster.hp = round(chosen.hp * deep["hp_mult"])
        monster.attack_mod, monster.defense_mod, monster.damage_mod = \
            deep["attack_mod"], deep["defense_mod"], deep["damage_mod"]
    if elite:
        mods = ELITES[elite]
        monster.elite = elite
        monster.name = titled(elite, monster.name)
        monster.max_hp = monster.hp = round(monster.max_hp * mods.get("hp_mult", 1.0))
        monster.attack_mod += mods.get("attack_mod", 0)
        monster.defense_mod += mods.get("defense_mod", 0)
        monster.damage_mod += mods.get("damage_mod", 0)
        monster.reward_mult = mods.get("reward_mult", 1.5)
    return monster


ORDINALS = ("Second", "Third", "Fourth", "Fifth")  # how a party's others of the same kind are told apart


def titled(word: str, name: str) -> str:
    """A name with a word put before it (an elite's, an ordinal): after its "The", if it has one ("The Hulking
    Hollowed", not "Hulking The Hollowed")."""
    rest = name.removeprefix("The ")
    return f"The {word} {rest}" if rest != name else f"{word} {name}"


def party(rng: random.Random, content: Content, leader: MonsterState, floor: int) -> list[MonsterState]:
    """Who comes into the fight with `leader` (its monster's `party`: a Sporerat's other Sporerat, a boss's parts),
    each as strong as the floor makes it (DEPTH), and named apart where they're alike ("Second Sporerat")."""
    out: list[MonsterState] = []
    seen = [leader.name]
    bosses = content.monster(leader.key).boss  # (a boss's parts are as made, as the boss is: no depth for them)
    for key in content.monster(leader.key).party:
        made = content.monster(key)
        member = MonsterState(key=key, name=made.name, hp=made.hp, max_hp=made.hp)
        deep = depth(floor) if not (made.boss or bosses) else {}
        if deep:
            member.max_hp = member.hp = round(made.hp * deep["hp_mult"])
            member.attack_mod, member.defense_mod, member.damage_mod = \
                deep["attack_mod"], deep["defense_mod"], deep["damage_mod"]
        alike = sum(name == made.name for name in seen)
        if alike:
            member.name = titled(ORDINALS[min(alike, len(ORDINALS)) - 1], made.name)
        seen.append(made.name)
        member.place = len(out) + 1
        out.append(member)
    return out


def depth(floor: int) -> dict:
    """How much stronger monsters are this far down (DEPTH): nothing above its first row, its deepest row below it."""
    if floor in DEPTH:
        return DEPTH[floor]
    return DEPTH[max(DEPTH)] if DEPTH and floor > max(DEPTH) else {}


def tier_for(floor: int, floors: int = FLOORS) -> int:
    """The tier of a floor's monsters, by how far down the run it is: the top tier (3) from three quarters of the way
    down. A run of four floors is 1, 2, 3, 3; a newcomer met tier 3 on floor 2 and died there half the time."""
    return max(1, min(3, math.ceil(3 * floor / max(1, floors))))


def warden_tier(floor: int, floors: int = FLOORS) -> int:
    """The tier of a floor's toughest: the warden by its stairs, whatever's in its secret room, and a character cut
    down to size for it (npcs.sized). Tier 2 at least: floor 1's is the first real fight."""
    return max(2, tier_for(floor, floors))


def _place_monsters(rng, content, state, theme, rooms: list[Room], end_id: int, boss: bool) -> None:
    if boss:
        boss = content.monster(theme.boss)
        rooms[end_id].monster = MonsterState(key=boss.key, name=boss.name, hp=boss.hp, max_hp=boss.hp)
        rooms[end_id].others = party(rng, content, rooms[end_id].monster, state.floor)  # (the Humongous Fungus's parts)
    else:
        # Every staircase has a warden; from floor 2 on, it's an elite. A dungeon's boss who always holds it is there
        # instead (EARLY_BOSSES), the warden drawn all the same (not met): the rest of the floor is as it was.
        early = EARLY_BOSSES.get(theme.boss, {}).get(state.floor)
        elite = rng.choice(sorted(ELITES)) if state.floor > 1 else ""
        rooms[end_id].monster = monster_for(rng, content, theme.key, warden_tier(state.floor, state.floors_total),
                                             elite=elite, met=list(state.met) if early else state.met,
                                             floor=state.floor)
        rooms[end_id].monster.warden = True
        if early:
            rooms[end_id].monster = early_boss(content, theme.boss, state.floor, state.floors_total)
        rooms[end_id].others = party(rng, content, rooms[end_id].monster, state.floor)

    candidates = [r for r in rooms if r.id not in (0, end_id) and r.fixture != "shrine"]
    rng.shuffle(candidates)
    elite_chance = {1: 0.0, 2: 0.25, 3: 0.4, 4: 0.25, 5: 0.25}.get(state.floor, 0.4)  # (floor 4 on: deeper already)
    for room in candidates[:max(2, round(len(candidates) * 0.5))]:
        elite = rng.choice(sorted(ELITES)) if rng.random() < elite_chance else ""
        room.monster = monster_for(rng, content, theme.key, tier_for(state.floor, state.floors_total), elite,
                                   met=state.met, floor=state.floor)
        room.others = party(rng, content, room.monster, state.floor)  # (a Sporerat never comes alone)
        if not room.others:
            room.others = group(dice.stream(state.seed, "group", state.floor, room.id), content, room.monster,
                                state.floor)


def group(rng: random.Random, content: Content, leader: MonsterState, floor: int) -> list[MonsterState]:
    """Now and then on the first floors, a weak monster comes with others of its kind (GROUPS): a rat in a pack of
    two or three. Not one of a kind, an elite, or one with a name. Its own random stream (the caller's), so the rest
    of the floor is as it would have been."""
    made = content.monster(leader.key)
    if floor not in GROUPS or made.hp > WEAK or made.once or made.named or leader.elite or rng.random() >= GROUPS[floor]:
        return []
    more = rng.choices(list(GROUP_SIZES), weights=list(GROUP_SIZES.values()))[0]
    out = []
    for i in range(more):
        member = MonsterState(key=leader.key, name=titled(ORDINALS[i], leader.name), hp=made.hp, max_hp=made.hp,
                              tricks=list(leader.tricks), place=i + 1)
        out.append(member)
    return out


def met_on(content: Content, key: str) -> dict[int, set[str]]:
    """Which floors a monster can turn up on, and as what ("roams": a room's; "stairs": the warden by the stairs;
    "boss"; "group"), in a run of four floors or of DEEPEST (monster_for's rules, worked out: the debug screen's)."""
    from .models import DEEPEST, DUNGEONS

    made = content.monster(key)
    found: dict[int, set[str]] = {}
    for floors in sorted({FLOORS, DEEPEST}):
        for floor in range(1, floors + 1):
            themes = [t for t in content.themes.values() if (t.floor == floor if t.floor else floor <= DUNGEONS)]
            for theme in themes:
                if theme.boss == key and (floor >= min(DUNGEONS, floors) or floor in EARLY_BOSSES.get(key, {})):
                    found.setdefault(floor, set()).add("boss")
                pool = [m for m in content.monsters.values() if m.roams and m.lives_in(theme)]
                pool = [m for m in pool if not m.floors or floor in m.floors] or pool
                for how, tier in (("roams", tier_for(floor, floors)), ("stairs", warden_tier(floor, floors))):
                    if how == "stairs" and (floor >= min(DUNGEONS, floors) or theme.boss in EARLY_BOSSES):
                        continue  # (a boss holds those stairs)
                    exact = [m for m in pool if m.tier == tier] or [m for m in pool if m.tier <= tier] or pool
                    if made in exact:
                        found.setdefault(floor, set()).add(how)
                        if how == "roams" and floor in GROUPS and made.hp <= WEAK and not made.once and not made.named:
                            found[floor].add("group")
    return found


def early_boss(content: Content, key: str, floor: int, floors: int = FLOORS) -> MonsterState:
    """A dungeon's boss at its stairs on an earlier floor than the last dungeon's (EARLY_BOSSES): the floor's size,
    a warden's tier, half a boss's souls."""
    boss = npcs.sized(content, key, floor, EARLY_BOSSES[key], warden=True)
    boss.tier = warden_tier(floor, floors)
    boss.reward_mult = EARLY_BOSS_SOULS
    return boss


def _place_loot(rng, content: Content, state: GameState, theme, rooms: list[Room], end_id: int, max_distance: int,
                boss: bool) -> None:
    """The floor's loot (see loot.py), spread out: one thing to a hiding place, and each room's turn before any room
    gets a second, never more than loot.MOST_PER_ROOM to a room. The key and what a chest or a wall waits on go
    first; potions sometimes just lie on the floor, as do a potion, food, a bomb or a small key there's no hiding
    place left for. Anything else with nowhere left to go isn't there at all."""
    others = [r for r in rooms if r.id not in (0, end_id)]
    if boss:
        # The key sits in a visible feature somewhere past the halfway point (never in the boss room); on a dark floor,
        # never in a thing wrapped in threads, that only fire opens (light.WRAPS): no torch mustn't mean no way on.
        deep = [r for r in others if r.distance >= max(1, max_distance // 2)] or others
        bare = [[f for f in r.features if not (theme.dark and any(w in f.name.lower() for w in WRAPS))] for r in deep]
        room = rng.choice([r for r, open_ in zip(deep, bare) if open_] or deep)
        rng.choice(bare[deep.index(room)] or room.features).loot.append(theme.key_item)

    most = loot.most_gear(state)
    own = dice.stream(state.seed, "dungeon gear", state.floor)  # (its own gear's pick, on a stream of its own)
    found = [loot.dungeon_gear(own, content, state.rares, theme.key, slot, most)
             if slot.startswith("gear ") and own.random() < loot.DUNGEON_GEAR_CHANCE else None
             for slot in loot.FLOORS.get(state.floor, ["potion 1"])]
    found = [key or loot.give(rng, content, state.rares, slot, most=most)
             for key, slot in zip(found, loot.FLOORS.get(state.floor, ["potion 1"]))]
    found.append(loot.DUNGEON_TRINKETS.get(theme.key, "oil_flask"))
    found = sorted(filter(None, found), key=lambda key: key not in loot.ESSENTIAL)  # (stable: the rest keep order)
    spots = _spots(rng, others)
    for item in found:
        spots = [(room, feature) for room, feature in spots if held(room) < loot.MOST_PER_ROOM]
        if spots and not (loot.role(content.item(item)) == "potion" and rng.random() < 0.35):
            spots.pop(0)[1].loot.append(item)
        elif item in loot.ESSENTIAL or loot.role(content.item(item)) in ("potion", "food"):
            _emptiest(rng, others).items.append(item)

    for room in others:
        for feature in room.features:
            if not feature.loot and rng.random() < 0.5:
                feature.gold = rng.randint(2, 8) * max(1, room.distance) + 2 * state.floor

    stash_room = _emptiest(rng, others)  # (never on top of a room that's full already)
    stash = loot.STASH.get(state.floor, loot.STASH[max(loot.STASH)])
    stash_room.features.append(Feature(
        name=rng.choice(HIDDEN_FEATURES), hidden=True, gold=rng.randint(15, 30) * state.floor,
        loot=[key for key in [loot.produce(rng, content, state.rares, stash, "stash", loot.owned(state, content),
                                           most)] if key],
    ))


def _spots(rng: random.Random, rooms: list[Room]) -> list[tuple[Room, Feature]]:
    """Where a floor's loot goes, in turn: a free spot in each room (the rooms in a random order), then a second spot
    in each, and so on. So things spread out over the floor instead of piling up three to a cupboard."""
    free: dict[int, list[Feature]] = {}
    for room in rooms:
        empty = [f for f in room.features if not f.loot]
        if empty:
            free[room.id] = rng.sample(empty, len(empty))
    order = [r for r in rng.sample(rooms, len(rooms)) if r.id in free]
    return [(r, free[r.id][depth]) for depth in range(max(map(len, free.values()), default=0))
            for r in order if depth < len(free[r.id])]


def held(room: Room) -> int:
    """How many things a room has lying about or hidden in it."""
    return len(room.items) + sum(len(f.loot) for f in room.features)


def _emptiest(rng: random.Random, rooms: list[Room]) -> Room:
    """One of the rooms with the least lying about or hidden in it so far."""
    fewest = min(map(held, rooms))
    return rng.choice([r for r in rooms if held(r) == fewest])


def _secret_room(rng: random.Random, content: Content, state: GameState, theme, rooms: list[Room]) -> Room | None:
    """Each floor's secret room: built in a gap in the map that touches two rooms or more (as many as can be had),
    with no doors at all until a bomb makes one. It keeps something rare, and now and then something guarding it."""
    taken = {(r.x, r.y) for r in rooms}
    touching = {}
    for x, y in taken:
        for dx, dy in DELTA.values():
            cell = (x + dx, y + dy)
            if cell not in taken:
                touching[cell] = touching.get(cell, 0) + 1
    gaps = [cell for cell, n in touching.items() if n >= 2]
    if not gaps:
        return None
    most = max(touching[cell] for cell in gaps)
    x, y = rng.choice(sorted(cell for cell in gaps if touching[cell] == most))
    near = [r for r in rooms if abs(r.x - x) + abs(r.y - y) == 1]
    # A kind of room the floor hasn't had (or at least not next door), so it isn't the room you bombed out of again.
    unused = [k for k in theme.archetypes if k not in {r.archetype for r in rooms}]
    archetype = content.archetypes[rng.choice(unused or [k for k in theme.archetypes
                                                         if k not in {r.archetype for r in near}])]
    names = [n for n in archetype.names if n not in {r.name for r in rooms}] or archetype.names
    name = rng.choice(names).removeprefix("The ")  # ("the Hidden Clutch", not "the Hidden The Clutch": run 66)
    room = Room(id=len(rooms), x=x, y=y, name=f"Hidden {name}", archetype=archetype.key,
                distance=min(r.distance for r in near) + 1, secret=True,
                features=[Feature(name=rng.choice(archetype.features), gold=rng.randint(10, 20) * state.floor)])
    prize = loot.produce(rng, content, state.rares, loot.SECRET, "secret", loot.owned(state, content),
                         loot.most_gear(state))
    if prize:
        room.items.append(prize)
    if rng.random() < 0.3:  # something got here first, and won't share
        room.monster = monster_for(rng, content, theme.key, warden_tier(state.floor, state.floors_total),
                                   elite=rng.choice(sorted(ELITES)),
                                   met=state.met, floor=state.floor)
        room.others = party(rng, content, room.monster, state.floor)
    return room


def _shop(state: GameState, content: Content, rooms: list[Room], end_id: int) -> Room | None:
    """Now and then, a floor has a shop: a nook off one room, behind a door a small key opens (or two bombs break).
    Granny Gristle keeps it, or once in a while Granny Kamultruk. It has a random stream of its own, so whether
    there's a shop changes nothing else about the floor."""
    rng = dice.stream(state.seed, "shop", state.floor)
    keepers = [k for k in (loot.SHOPKEEPER, loot.SHINY) if k in content.monsters]
    theme = content.themes[state.theme]
    status = theme.status  # (a floor with poison of its own: a shop more often, with the cure; a dark one, lights)
    below = content.themes[state.themes[state.floor]] if state.floor < len(state.themes) else None
    chance = loot.STATUS_SHOP_CHANCE if status or theme.dark else \
        loot.BEFORE_STATUS_SHOP_CHANCE if below and (below.status or below.dark) else loot.SHOP_CHANCE  # (above: all)
    if not keepers or rng.random() >= chance:
        return None
    keeper = keepers[-1] if len(keepers) > 1 and rng.random() < loot.SHINY_CHANCE else keepers[0]
    taken = {(r.x, r.y) for r in rooms}
    nooks = sorted((x + dx, y + dy, r.id) for r in rooms if r.id != end_id and not r.secret
                   for x, y in [(r.x, r.y)] for dx, dy in DELTA.values()
                   if (x + dx, y + dy) not in taken and sum((x + dx + ex, y + dy + ey) in taken
                                                             for ex, ey in DELTA.values()) == 1)
    if not nooks:
        return None
    x, y, by = rng.choice(nooks)
    door = next(d for d, (dx, dy) in DELTA.items() if (rooms[by].x + dx, rooms[by].y + dy) == (x, y))
    room = Room(id=len(rooms), x=x, y=y, name=f"{content.monster(keeper).name}'s Shop", archetype="shop",
                distance=rooms[by].distance + 1, fixture="shop",
                shop=Shop(keeper=keeper, wares=[Ware(item=k, price=p, count=n) for k, p, n in
                                                loot.wares(rng, content, state.rares, keeper, state.floor,
                                                           cure_for=status,
                                                           lights=theme.dark or bool(below and below.dark),
                                                           most=loot.most_gear(state))]))
    rooms[by].exits[door] = Exit(to=room.id, locked=True, key="small_key")
    room.exits[OPPOSITE[door]] = Exit(to=by)
    return room


def _lair(state: GameState, content: Content, rooms: list[Room], end_id: int) -> Room | None:
    """A floor's lair (LAIRS: the Sporefang Matriarch's, in the Underbloom): a nook off one room, its way in sealed with
    web as thick as a sail that only fire gets through (rules._burn_web), and its keeper in it, at full strength, as a
    guardian is. A random stream of its own, as the shop has, so it changes nothing else about the floor."""
    archetype_key, who = LAIRS.get(state.theme, ("", ""))
    if archetype_key not in content.archetypes or who not in content.monsters:
        return None
    rng = dice.stream(state.seed, "lair", state.floor)
    taken = {(r.x, r.y) for r in rooms}
    nooks = sorted((x + dx, y + dy, r.id) for r in rooms if r.id not in (0, end_id) and not r.secret and not r.shop
                   for x, y in [(r.x, r.y)] for dx, dy in DELTA.values()
                   if (x + dx, y + dy) not in taken and sum((x + dx + ex, y + dy + ey) in taken
                                                             for ex, ey in DELTA.values()) == 1)
    if not nooks:
        return None
    x, y, by = rng.choice(nooks)
    door = next(d for d, (dx, dy) in DELTA.items() if (rooms[by].x + dx, rooms[by].y + dy) == (x, y))
    archetype, keeper = content.archetypes[archetype_key], content.monster(who)
    # (the last one who came: their gear's still on them)
    wrapped = [loot.give(rng, content, state.rares, "gear 3+", most=loot.most_gear(state))]
    room = Room(id=len(rooms), x=x, y=y, name=archetype.names[0], archetype=archetype.key,
                distance=rooms[by].distance + 1,
                features=[Feature(name=archetype.features[0], loot=[k for k in wrapped if k]),
                          *(Feature(name=f, gold=rng.randint(15, 25) * state.floor) for f in archetype.features[1:])])
    room.monster = MonsterState(key=keeper.key, name=keeper.name, hp=keeper.hp, max_hp=keeper.hp)
    rooms[by].exits[door] = Exit(to=room.id, webbed=True)
    room.exits[OPPOSITE[door]] = Exit(to=by)
    return room


def _place_ghost(rng, content: Content, state: GameState, rooms: list[Room], end_id: int, ghost: dict) -> None:
    """A previous adventurer died on this floor. Their ghost guards what they carried (somewhere with nothing else to
    find, if there's such a room, so it isn't one big heap): not a key, nor what a character gave them or a quest
    was about (Lenny's teeth, Swoogy's diaper: those are this run's to earn), nor a one-of-a-kind thing this run has
    had already (loot.single). One in the remains is this run's one of it."""
    spots = [r for r in rooms if r.id not in (0, end_id) and not r.fixture] or [r for r in rooms if r.id != 0]
    room = rng.choice([r for r in spots if not r.items and not any(f.loot for f in r.features)] or spots)
    base = content.monster("ghost")
    level = int(ghost.get("level", 1))
    hp = base.hp + 4 * (level - 1)
    room.monster = MonsterState(key="ghost", name=f"Ghost of {ghost['name']}", hp=hp, max_hp=hp,
                                attack_mod=level // 2, ghost_id=ghost.get("id"), ghost_of=ghost["name"],
                                reward_mult=2.0)
    items = []
    for key in (k for k in ghost.get("items", []) if k in content.items):
        item = content.item(key)
        quest = "quest" in item.found or any(p in content.monsters and content.monster(p).npc for p in item.found)
        if len(items) < 3 and not (item.kind == "key" or quest or key in state.rares):
            items.append(key)
            loot.noted(content, state.rares, key)
    room.features.append(Feature(name=f"{ghost['name']}'s remains", loot=items, gold=int(ghost.get("gold", 0)) // 2))


def render_map(state: GameState) -> list[str]:
    """ASCII map of this floor. @ you, ! danger, ? unexplored, > stairs, † shrine, ■ chest, ◊ fountain, $ something
    hidden that you were told about, ☺ someone who wants something of you (Lucky Lenny, his tooth); the secret room
    in braces, {✧}. Once you've been handed the floor's map, every room and door is on it (except a secret room no
    bomb has opened). A room you were told about is on it too, before you've found the way there."""
    mapped = state.mapped_floor == state.floor
    known = {r.id for r in state.rooms if r.visited or (mapped and (not r.secret or r.exits))}
    for room_id in list(known):
        known.update(e.to for e in state.rooms[room_id].exits.values())
    known.update(r.id for r in state.rooms if r.told or any(f.told for f in r.features))
    rooms = [state.rooms[i] for i in known]
    min_x, max_x = min(r.x for r in rooms), max(r.x for r in rooms)
    min_y, max_y = min(r.y for r in rooms), max(r.y for r in rooms)
    width, height = (max_x - min_x) * 4 + 3, (max_y - min_y) * 2 + 1
    grid = [[" "] * width for _ in range(height)]
    for room in rooms:
        cx, cy = (room.x - min_x) * 4 + 1, (room.y - min_y) * 2
        left, right = "{}" if room.secret else "[]"
        grid[cy][cx - 1], grid[cy][cx], grid[cy][cx + 1] = left, map_glyph(state, room), right
        if not (room.visited or mapped):
            continue
        for direction, exit_ in room.exits.items():
            back = state.rooms[exit_.to].exits.get(OPPOSITE[direction])  # (a door's drawn from both its rooms: shut
            sides = [exit_, *([back] if back else [])]  # from either side, it's shut)
            door = "=" if any(e.locked for e in sides) else "x" if any(e.webbed for e in sides) else \
                ("-" if direction in ("east", "west") else "|")
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
    if any(f.told and not f.searched for f in room.features):
        return "$"
    if room.secret:
        return "✧"
    if room.monster and room.visited and npcs.waiting(state, room.monster):
        return "☺"  # (a character you've met, waiting on you: Lenny for his tooth)
    if room.fixture and not room.fixture_used:
        return layout.FIXTURE_GLYPHS[room.fixture]  # you can see what's through the door, like Tiny Rogues
    if room.is_boss:
        return "B"
    return "#" if room.visited else "?"
