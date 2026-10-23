"""A simple player that only uses the listed actions. Used to fuzz the rules and sanity-check balance."""

from __future__ import annotations

from collections import deque

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


def choose(state: GameState, content: Content) -> str:
    actions = {a.id: a for a in available_actions(state, content)}
    player = state.player
    if state.pending_perks:
        return next(iter(actions))
    if state.in_combat:
        heal = next((a for a in actions if a.startswith("use:") and "potion" in a), None)
        if player.hp <= player.max_hp * 0.35 and heal:
            return heal
        if state.room.monster.intent == "heavy":
            return "dodge"
        return "attack"
    for prefix in ("take", "search:", "chest", "fountain"):  # (take: one thing, take_all: the lot)
        found = next((a for a in actions if a.startswith(prefix)), None)
        if found:
            return found
    if "shrine_gold" in actions and player.hp < player.max_hp * 0.6:
        return "shrine_gold"
    if "shrine_blood" in actions and player.hp > player.max_hp * 0.8:
        return "shrine_blood"
    if player.hp < player.max_hp * 0.6:
        heal = next((a for a in actions if a.startswith("use:")), None)
        if heal:
            return heal
        if "rest" in actions:
            return "rest"
    direction = _route_to_unexplored(state, content)
    if direction and f"go:{direction}" in actions:
        return f"go:{direction}"
    if "descend" in actions:
        return "descend"
    stairs = next((r.id for r in state.rooms if r.fixture == "stairs"), None)
    if stairs is not None:
        step = _route_to(state, stairs)
        if step:
            return f"go:{step}"
    if "search_room" in actions:
        return "search_room"
    return next(a for a in actions if a.startswith("go:"))


def play(state: GameState, content: Content, max_turns: int = 600) -> GameState:
    for _ in range(max_turns):
        if state.over:
            break
        perform(state, content, choose(state, content))
    return state
