"""The model's side jobs: a suggested trick each scene, bestiary lore, epitaphs, recaps and the Void's
campfire greeting. Each has a plain fallback so the game works offline."""

from __future__ import annotations

import re

from ..content import Content
from ..creative import SPENDING, available_props
from ..meta import fallback_epitaph
from ..models import GameState
from ..text import bare, the
from .base import LLM, LLMError
from .narrator import clean
from .prompts import EPITAPH_SYSTEM, LORE_SYSTEM, RECAP_SYSTEM, SUGGEST_SYSTEM, VOID_SYSTEM, suggestion_situation

THROWING = SPENDING | {"roll"}  # outside a fight, a trick that starts with one of these spends what you carry
COMMON = {"the", "and", "for", "with", "its", "his", "her", "old"}  # words in a name that don't say which thing

SUGGEST_SCHEMA = {
    "type": "object",
    "properties": {"suggestion": {"type": "string"}},
    "required": ["suggestion"],
    "additionalProperties": False,
}


async def _text(llm: LLM, system: str, user: str, max_tokens: int = 200) -> str:
    parts = [chunk async for chunk in llm.stream_text(system, user, max_tokens=max_tokens)]
    return clean("".join(parts)).strip().strip('"')


def offline_suggestion(state: GameState, content: Content) -> str:
    """A template trick built from what's actually here, so players learn they can improvise."""
    props = available_props(state, content)
    monster = state.room.monster if state.in_combat else None
    if monster:
        name = bare(monster.name).lower()
        weak = set(content.monster(monster.key).weak) & set(state.known_weak.get(monster.key, []))
        for prop in props:
            if weak & set(prop.tags) and "throwable" in prop.tags:
                return f"Hurl {the(prop.name)} at the {name}"
        for prop in props:
            if prop.kind == "feature" and "heavy" in prop.tags:
                return f"Topple {the(prop.name)} onto the {name}"
        for prop in props:
            if "throwable" in prop.tags:
                return f"Throw {the(prop.name)} in the {name}'s face"
        if content.monster(monster.key).intelligent:
            return f"Convince the {name} you're its long-lost cousin"
        return f"Kick dust in the {name}'s eyes"
    for prop in props:
        if prop.kind == "feature" and "holy" in prop.tags:
            return f"Kneel and pray at {the(prop.name)}"
        if prop.kind == "feature" and {"heavy", "paper"} & set(prop.tags):
            return f"Look behind {the(prop.name)}"
    return "Listen at the walls for hidden passages"


async def suggestion(llm: LLM | None, state: GameState, content: Content) -> str:
    fallback = offline_suggestion(state, content)
    if llm is None:
        return fallback
    try:
        reply = await llm.complete_json(SUGGEST_SYSTEM, suggestion_situation(state, content), SUGGEST_SCHEMA,
                                        max_tokens=80)
        text = str(reply.get("suggestion", "")).strip().rstrip(".")
    except (LLMError, ValueError):
        return fallback
    return text if 3 <= len(text) <= 80 and sensible(text, state, content) else fallback


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

