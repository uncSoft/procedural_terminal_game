"""Turns whatever the player typed into an Intent. Obvious commands are matched locally (no model call);
everything else goes to the language model, with the keyword matcher as the fallback."""

from __future__ import annotations

import difflib
import re

from pydantic import ValidationError

from ..content import Content
from ..intent import Intent, intent_schema
from ..models import GameState
from ..rules import Action
from .base import LLM, LLMError
from .prompts import interpreter_messages

DIRECTION_ALIASES = {"n": "north", "s": "south", "e": "east", "w": "west"}
MOVE_WORDS = {"go", "walk", "head", "move", "travel", "enter", "proceed"}
ATTACK_WORDS = {"attack", "hit", "strike", "stab", "fight", "kill", "swing", "slash", "smack", "punch", "kick"}
FLEE_WORDS = {"flee", "run", "escape", "retreat"}
REST_WORDS = {"rest", "sleep", "nap", "camp", "sit"}
TAKE_WORDS = {"take", "grab", "pick", "get", "loot", "collect"}
USE_WORDS = {"drink", "quaff", "eat", "use", "throw", "consume", "chug"}
SEARCH_WORDS = {"search", "examine", "check", "inspect", "open", "investigate", "rummage", "look"}
STOPWORDS = {"the", "a", "an", "of", "to", "with", "at", "my", "your", "in", "on", "for", "it", "up", "into", "and"}
QUESTION_STARTS = ("what", "where", "how", "who", "why", "which", "am i", "do i", "can i", "is there", "are there")


def _action(action_id: str) -> Intent:
    return Intent(kind="action", action_id=action_id, difficulty="trivial")


def _best_target(words: list[str], actions: list[Action], prefix: str) -> Action | None:
    best, best_score = None, 0
    for action in actions:
        if not action.id.startswith(prefix):
            continue
        target = {w for w in re.findall(r"[a-z']+", action.label.lower())[1:] if w not in STOPWORDS}
        score = len(target & set(words))
        if score > best_score:
            best, best_score = action, score
    return best


def offline_interpret(raw: str, actions: list[Action]) -> tuple[Intent, bool]:
    """Keyword matching. Returns the intent and whether it's confident enough to skip the language model."""
    text = raw.lower().strip(" .!")
    words = re.findall(r"[a-z']+", text)
    ids = {a.id for a in actions}
    if not words:
        return Intent(kind="flavor"), False

    labels = {a.label.lower(): a for a in actions}
    if text in labels:
        return _action(labels[text].id), True

    short = len(words) <= 3
    for word in words:
        direction = DIRECTION_ALIASES.get(word, word)
        if f"go:{direction}" in ids and (short or words[0] in MOVE_WORDS):
            return _action(f"go:{direction}"), short
    if words[0] in ATTACK_WORDS and "attack" in ids:
        return _action("attack"), len(words) <= 4
    if FLEE_WORDS & set(words) and "flee" in ids:
        return _action("flee"), short
    if words[0] in REST_WORDS and "rest" in ids:
        return _action("rest"), short
    if words[0] in TAKE_WORDS:
        match = _best_target(words, actions, "take:")
        if match:
            return _action(match.id), True
    if words[0] in USE_WORDS:
        match = _best_target(words, actions, "use:")
        if match:
            return _action(match.id), True
    if words[0] in SEARCH_WORDS:
        if {"room", "secret", "secrets", "hidden", "around"} & set(words) and "search_room" in ids:
            return _action("search_room"), short or "secrets" in words
        match = _best_target(words, actions, "search:")
        if match:
            return _action(match.id), True

    close = difflib.get_close_matches(text, list(labels), n=1, cutoff=0.8)
    if close:
        return _action(labels[close[0]].id), True
    if text.endswith("?") or text.startswith(QUESTION_STARTS):
        return Intent(kind="question", summary=raw), False
    return Intent(kind="flavor", summary=raw.strip()), False


async def interpret(llm: LLM | None, state: GameState, content: Content, raw: str,
                    actions: list[Action]) -> tuple[Intent, str | None]:
    """Returns the intent and, if the model failed, an error message for the log."""
    fallback, confident = offline_interpret(raw, actions)
    if llm is None or confident:
        return fallback, None
    system, user = interpreter_messages(state, content, raw, actions)
    try:
        intent = Intent.model_validate(await llm.complete_json(system, user, intent_schema(), max_tokens=400))
    except (LLMError, ValidationError, ValueError) as e:
        return fallback, f"interpreter: {e}"
    if intent.kind == "action" and intent.action_id not in {a.id for a in actions}:
        if fallback.kind == "action":
            return fallback, None
        return Intent(kind="flavor", summary=intent.summary or raw), None
    return intent, None
