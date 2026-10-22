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
            if exit_.locked and not has_key:
                continue
            if exit_.to not in seen:
                seen.add(exit_.to)
                queue.append((exit_.to, first or direction))
    return None


def choose(state: GameState, content: Content) -> str:
    actions = {a.id: a for a in available_actions(state, content)}
    player = state.player
    if state.in_combat:
        heal = next((a for a in actions if a.startswith("use:") and "potion" in a), None)
        if player.hp <= player.max_hp * 0.35 and heal:
            return heal
        return "attack"
    for prefix in ("take:", "search:"):
        found = next((a for a in actions if a.startswith(prefix)), None)
        if found:
            return found
    if player.hp < player.max_hp * 0.6:
        heal = next((a for a in actions if a.startswith("use:")), None)
        if heal:
            return heal
        if "rest" in actions:
            return "rest"
    direction = _route_to_unexplored(state, content)
    if direction and f"go:{direction}" in actions:
        return f"go:{direction}"
    if "search_room" in actions:
        return "search_room"
    # Everything explored: head for any unlocked unexplored exit, else wander.
    return next(a for a in actions if a.startswith("go:"))


def play(state: GameState, content: Content, max_turns: int = 400) -> GameState:
    for _ in range(max_turns):
        if state.over:
            break
        perform(state, content, choose(state, content))
    return state
