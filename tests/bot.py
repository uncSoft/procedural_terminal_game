"""A simple player that only uses the listed actions. Used to fuzz the rules and sanity-check balance.

The plain bot is thorough and steady: it picks up everything, searches every feature and opens every chest, explores
every room before the stairs, dodges every heavy blow it's warned of, and drinks a potion at a third of its health.
Poisoned, it drinks a Pure if it has one, or else prays at the nearest shrine it's seen (walking there). It never
improvises, shops, bombs a wall or flees. Habits make it more like a person (see PLAYERS): it misses some
warnings, forgets or hoards its potions, leaves things behind and heads for the stairs once it's seen them."""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass

from ptg.content import Content
from ptg.models import GameState
from ptg.rules import available_actions, perform


def _route_to_unexplored(state: GameState, content: Content) -> str | None:
    """First step (a direction) toward the nearest room we haven't visited, or the boss door once we have the key."""
    key = content.themes[state.theme].key_item
    has_key = key in state.player.inventory
    start = state.room_id
    queue = deque([(start, None)])
    seen = {start}
    while queue:
        room_id, first = queue.popleft()
        room = state.rooms[room_id]
        if room_id != start and not room.visited:
            return first
        for direction, exit_ in room.exits.items():
            if exit_.locked and (exit_.key or not has_key):  # a shop's door, or the boss's without its key
                continue
            if exit_.to not in seen:
                seen.add(exit_.to)
                queue.append((exit_.to, first or direction))
    return None


def _route_to_unsearched(state: GameState) -> str | None:
    """First step toward the nearest room with something in it not yet searched or picked up (where a bot that
    walked past things goes back to, when it's missing the boss's key)."""
    def left(room) -> bool:
        return bool(room.items) or any(not f.searched and not f.hidden for f in room.features)
    targets = [r.id for r in state.rooms if r.visited and left(r) and r.id != state.room_id]
    steps = [step for step in (_route_to(state, t) for t in targets) if step]
    return steps[0] if steps else None


def _route_to(state: GameState, target: int) -> str | None:
    queue = deque([(state.room_id, None)])
    seen = {state.room_id}
    while queue:
        room_id, first = queue.popleft()
        if room_id == target:
            return first
        for direction, exit_ in state.rooms[room_id].exits.items():
            if not exit_.locked and exit_.to not in seen:
                seen.add(exit_.to)
                queue.append((exit_.to, first or direction))
    return None


def _cure(state: GameState, content: Content, actions) -> str | None:
    """A Pure (or anything that cures) to drink, while something ails it that it cures."""
    return next((a for a in actions if a.startswith("use:") and a[4:] in content.items
                 and set(content.item(a[4:]).cures) & set(state.player.statuses)), None)


@dataclass(frozen=True)
class Habits:
    """How a player plays, as chances: 1.0 everywhere is the plain bot."""
    reads_tells: float = 1.0  # dodges a heavy blow it's warned of
    heals_at: float = 0.35  # drinks a potion in a fight below this much of its health...
    drinks: float = 1.0  # ...if it remembers to (run 59 drank none of its eight)
    thorough: float = 1.0  # picks up, searches and opens what it finds rather than walking past
    explores: float = 1.0  # sees the whole floor before going down, rather than heading for the stairs once seen


PLAYERS = {
    "bot": Habits(),
    "careful": Habits(reads_tells=0.85, heals_at=0.4, drinks=0.9, thorough=0.95, explores=0.9),
    "average": Habits(reads_tells=0.6, heals_at=0.3, drinks=0.6, thorough=0.8, explores=0.6),
    "sloppy": Habits(reads_tells=0.35, heals_at=0.25, drinks=0.35, thorough=0.6, explores=0.3),
}


class Player:
    """A bot with habits: its own dice for them (seeded by the run, so a run plays the same every time), and what it
    has made up its mind about (whether to explore this floor, what it's walked past)."""

    def __init__(self, habits: Habits, seed: int) -> None:
        self.habits, self.rng = habits, random.Random(seed * 7919 + 17)
        self.minds: dict = {}

    def does(self, chance: float) -> bool:
        return chance >= 1.0 or self.rng.random() < chance

    def once(self, key, chance: float) -> bool:
        """A decision made once and kept: what it walked past stays walked past."""
        if key not in self.minds:
            self.minds[key] = self.does(chance)
        return self.minds[key]


def choose(state: GameState, content: Content, who: Player | None = None) -> str:
    actions = {a.id: a for a in available_actions(state, content)}
    player = state.player
    habits = who.habits if who else PLAYERS["bot"]
    if state.pending_perks:
        return who.rng.choice(list(actions)) if who else next(iter(actions))
    if state.in_combat:
        heal = next((a for a in actions if a.startswith("use:") and "potion" in a), None)
        if player.hp <= player.max_hp * habits.heals_at and heal and (not who or who.does(habits.drinks)):
            return heal
        if state.room.monster.intent == "heavy" and (not who or who.does(habits.reads_tells)):
            return "dodge"
        cure = _cure(state, content, actions)
        if cure and (not who or who.does(habits.drinks)):
            return cure
        return "attack"
    cure = _cure(state, content, actions) or ("shrine_pray" if player.statuses and "shrine_pray" in actions else None)
    if cure and (not who or who.does(habits.drinks)):  # poisoned, first (its rolls are at a disadvantage)
        return cure
    key = content.themes[state.theme].key_item
    # Missing the boss's key with the whole floor seen: back to look properly where it walked past things.
    hunting = bool(who) and state.boss_floor and key not in player.inventory \
        and _route_to_unexplored(state, content) is None
    for prefix in ("take", "equip:", "search:", "chest", "fountain", "disarm"):  # (take: one thing, take_all: the lot)
        found = next((a for a in actions if a.startswith(prefix) and
                      (not who or hunting or a == f"take:{key}"
                       or who.once((state.floor, state.room_id, a), habits.thorough))), None)
        if found:
            return found
    if player.statuses:  # still poisoned, with no Pure: the way to the nearest shrine it's seen
        shrines = [r.id for r in state.rooms if r.fixture == "shrine" and r.visited and r.id != state.room_id]
        steps = [step for step in (_route_to(state, s) for s in shrines) if step]
        if steps and f"go:{steps[0]}" in actions and (not who or who.once(("shrine", state.turn // 20), 0.8)):
            return f"go:{steps[0]}"
    if "shrine_gold" in actions and player.hp < player.max_hp * 0.6:
        return "shrine_gold"
    if "shrine_blood" in actions and player.hp > player.max_hp * 0.8:
        return "shrine_blood"
    if player.hp < player.max_hp * 0.6:
        heal = next((a for a in actions if a.startswith("use:") and content.item(a[4:]).heal), None)
        if heal and (not who or who.does(habits.drinks)):
            return heal
        if "rest" in actions:
            return "rest"
    stairs_seen = any(r.fixture == "stairs" and r.visited for r in state.rooms)
    explore = not (who and stairs_seen) or who.once(("explore", state.floor), habits.explores)
    direction = _route_to_unexplored(state, content) if explore else None
    if direction and f"go:{direction}" in actions:
        return f"go:{direction}"
    if "descend" in actions:
        return "descend"
    stairs = next((r.id for r in state.rooms if r.fixture == "stairs"), None)
    if stairs is not None:
        step = _route_to(state, stairs)
        if step:
            return f"go:{step}"
    step = _route_to_unsearched(state) if hunting else None
    if step and f"go:{step}" in actions:
        return f"go:{step}"
    if "search_room" in actions:
        return "search_room"
    return next(a for a in actions if a.startswith("go:"))


def play(state: GameState, content: Content, max_turns: int = 600, habits: Habits | None = None) -> GameState:
    player = Player(habits, state.seed) if habits and habits != PLAYERS["bot"] else None  # (the plain bot's are none)
    for _ in range(max_turns):
        if state.over:
            break
        perform(state, content, choose(state, content, player))
    return state
