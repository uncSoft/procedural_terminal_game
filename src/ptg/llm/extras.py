"""The model's side jobs: a suggested trick each scene, bestiary lore, epitaphs, recaps and the Void's
campfire greeting. Each has a plain fallback so the game works offline.

The suggested trick is always one of the interaction grid's uses that would really do something here (ideas): the
model only picks which and puts it in its own words, and picking it does just that use, whatever the words."""

from __future__ import annotations

import re

from .. import interactions
from ..content import Content
from ..creative import SPENDING, available_props
from ..events import Action
from ..meta import fallback_epitaph
from ..models import GameState
from ..scene import RoomView, words as named_by
from ..text import bare, the
from .base import LLM, LLMError
from .narrator import clean
from .prompts import EPITAPH_SYSTEM, LORE_SYSTEM, RECAP_SYSTEM, SUGGEST_SYSTEM, VOID_SYSTEM, suggestion_situation

THROWING = SPENDING | {"roll"}  # outside a fight, a trick that starts with one of these spends what you carry
COMMON = {"the", "and", "for", "with", "its", "his", "her", "old"}  # words in a name that don't say which thing
IDEAS = 6  # how many the model picks from

SUGGEST_SCHEMA = {
    "type": "object",
    "properties": {"idea": {"type": "integer"}, "suggestion": {"type": "string"}},
    "required": ["idea", "suggestion"],
    "additionalProperties": False,
}


async def _text(llm: LLM, system: str, user: str, max_tokens: int = 200) -> str:
    parts = [chunk async for chunk in llm.stream_text(system, user, max_tokens=max_tokens)]
    return clean("".join(parts)).strip().strip('"')


def ideas(state: GameState, content: Content) -> list[Action]:
    """What the suggested trick may be: uses of the interaction grid that would really do something here, the best
    first, each a whole use (its id, and how it's said). In a fight, something you carry turned on the monster: what
    it's known to be weak to first, then what isn't a numbered choice already (a thing that isn't made for throwing,
    thrown; a bribe), then the rest. Never anything that heals (you'll want it), your getaway, a bomb or a key: those
    are numbered choices, there when you need them. Out of a fight, a feature with something in it, or the walls of a
    room with something hidden in it. Nothing, if nothing would do: no stunts that roll for nothing and can hurt."""
    from ..rules import available_actions, hidden_room_beside

    if state.over or state.pending_perks or state.scene:
        return []
    view = RoomView(state, content)
    monster, room = view.monster, state.room
    if monster is not None and state.in_combat:
        listed = {a.label.lower(): a.id for a in available_actions(state, content)}
        known = set(state.known_weak.get(monster.key, []))
        found = []
        for ref in view.of("item", "gold"):
            item = content.item(ref.key) if ref.kind == "item" else None
            if item is not None and (item.heal or item.escape):
                continue
            use = interactions.Use("use", ref.key, monster.id)
            row = interactions.plan(state, content, use, view)
            if row is None or not row.works or not row.label:
                continue
            action_id = row.alias or listed.get(row.label.lower()) or interactions.use_id("use", ref.key, monster.id)
            rank = 0 if known & set(ref.tags) else 1 if row.label.lower() not in listed else 2
            found.append((rank, len(found), Action(action_id, row.label, row.hint)))
        return [action for *_, action in sorted(found)]
    if monster is not None and monster.state["hostile"]:
        return []
    out = []
    for i, feature in room.visible_features():
        if not feature.searched and (feature.loot or feature.gold):
            how = "Look behind" if {"heavy", "paper"} & set(content.feature_tags(feature.name)) else "Rummage through"
            out.append(Action(f"search:{i}", f"{how} {the(bare(feature.name))}"))
    hidden = any(f.hidden for f in room.features) or hidden_room_beside(state)
    if hidden and not room.room_searched and not room.shop:
        out.append(Action("search_room", "Tap the walls for hollow spots"))
    return out


async def suggestion(llm: LLM | None, state: GameState, content: Content) -> Action | None:
    """The trick to suggest: one of the ideas (its id is what picking it does), in the model's words for it if a
    model's there and its words are about it, else as the grid says it. None if nothing would do."""
    found = ideas(state, content)[:IDEAS]
    if llm is None or not found:
        return found[0] if found else None
    listed = "\n".join(f"{i}. {idea.label}" for i, idea in enumerate(found, 1))
    try:
        reply = await llm.complete_json(SUGGEST_SYSTEM, f"{suggestion_situation(state, content)}\n\nIDEAS:\n{listed}",
                                        SUGGEST_SCHEMA, max_tokens=80)
        pick, text = int(reply.get("idea", 1)), str(reply.get("suggestion", "")).strip().rstrip(".")
    except (LLMError, ValueError, TypeError):
        return found[0]
    idea = found[pick - 1] if 1 <= pick <= len(found) else found[0]
    if 3 <= len(text) <= 80 and says(text, idea, state, content):
        return Action(idea.id, text, idea.hint)
    return idea


def says(text: str, idea: Action, state: GameState, content: Content) -> bool:
    """Whether a model's words for an idea are about it: they share a word that names something with how the grid
    says it, and name nothing else you carry ("Throw the potion at it" is no way to say the holy water), and they
    don't throw or use up what you carry outside a fight (sensible)."""
    said = named_by(text)
    if not said & {w for w in named_by(idea.label.partition(" ")[2]) if len(w) > 2 and w not in COMMON}:
        return False
    used = (interactions.parse(idea.id) or interactions.Use("", idea.id.partition(":")[2])).subject
    other = RoomView(state, content).match(said, ("item", "gear"))
    return (other is None or other.key == used) and sensible(text, state, content)


def sensible(text: str, state: GameState, content: Content) -> bool:
    """Whether a suggested trick names something that's really here and, outside a fight, doesn't throw or use up what
    you carry. (A model copied its prompt's example, "Pry up the loose stones by the altar", into rooms with neither,
    and suggested scattering a Bag of Marbles under everything.)"""
    words = [w.rstrip("s") for w in re.findall(r"[a-z]+", text.lower())]
    if not words or (not state.in_combat and words[0] in THROWING):
        return False
    props = available_props(state, content)
    names = [p.name for p in props if state.in_combat or p.kind == "feature"]
    names += [state.room.monster.name] if state.room.monster else []
    here = {w.rstrip("s") for name in names for w in re.findall(r"[a-z]+", name.lower())
            if len(w) > 2 and w not in COMMON}  # "a half-sunken pew": pew counts, "the" doesn't
    return bool(here & set(words))


async def lore(llm: LLM | None, content: Content, monster_key: str) -> str:
    monster = content.monster(monster_key)
    if llm is None:
        return ""
    user = f"Monster: {monster.name}. Kind: {', '.join(monster.tags)}. Secretly weak to: {', '.join(monster.weak)}."
    try:
        return await _text(llm, LORE_SYSTEM, user, max_tokens=120)
    except LLMError:
        return ""


async def epitaph(llm: LLM | None, state: GameState) -> str:
    fallback = fallback_epitaph(state)
    if llm is None:
        return fallback
    outcome = f"they won and lived ({state.cause})" if state.status == "won" else f"they died ({state.cause})"
    user = (f"Name: {state.player.name}. Outcome: {outcome}. Level {state.player.level}, "
            f"{state.player.kills} kills, {state.turn} turns. Last moments:\n" + "\n".join(state.journal[-5:]))
    try:
        text = await _text(llm, EPITAPH_SYSTEM, user, max_tokens=80)
    except LLMError:
        return fallback
    return text or fallback


async def recap(llm: LLM | None, state: GameState, stand_in: bool = True) -> str:
    """What's happened so far, for a run picked up again. With no model (or a failing one) the last narration
    stands in, unless `stand_in` is off: the game's screen shows the story itself, so it would only repeat it."""
    fallback = next((e.text for e in reversed(state.log) if e.kind == "narration"), "") if stand_in else ""
    if llm is None or not state.journal:
        return fallback
    try:
        return await _text(llm, RECAP_SYSTEM, "\n".join(state.journal[-10:]), max_tokens=150) or fallback
    except LLMError:
        return fallback


async def void_line(llm: LLM | None, last_run: dict | None, name: str) -> str:
    if last_run is None:
        fallback = f"Ah, {name}. Fresh meat for the dark. Sit by the fire, spend your souls, then go down."
    elif last_run["status"] == "won":
        fallback = f"{last_run['name']} came back up. Insufferable. The dark wants a rematch."
    else:
        fallback = f"Back again? {last_run['name']} is still down there, {last_run['cause'] or 'somewhere'}. Restless."
    if llm is None:
        return fallback
    user = (f"Player: {name}. Last run: {last_run['name']} {last_run['epithet']}, {last_run['status']}, "
            f"{last_run['cause']}, epitaph: {last_run['epitaph']}" if last_run else f"Player {name} has never descended.")
    try:
        return await _text(llm, VOID_SYSTEM, user, max_tokens=80) or fallback
    except LLMError:
        return fallback

