"""Turns whatever the player typed into an Intent. Obvious commands are matched locally (no model call);
everything else goes to the language model, with the keyword matcher as the fallback."""

from __future__ import annotations

import difflib
import re

from pydantic import ValidationError

from ..content import Content
from ..intent import Intent, intent_schema
from ..models import GameState
from ..events import Action
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
DODGE_WORDS = {"dodge", "duck", "evade", "sidestep", "roll", "jump"}
DISTRACT_WORDS = {"distract", "wave", "shine", "squeak", "pop", "show"}
BOMB_WORDS = {"bomb", "bombs", "blast", "blow"}
ASK_WORDS = {"ask", "question", "inquire", "interrogate", "quiz", "pester"}
WATCH_WORDS = {"watch", "follow", "observe", "trail"}
TIP_WORDS = {"secret", "secrets", "hidden", "hide", "treasure", "loot", "stash", "know", "knows", "rumor", "rumors",
             "rumour", "rumours", "gossip", "lore", "where", "tip", "tips"}
FIXTURE_WORDS = {
    "descend": {"descend", "downstairs", "stairs"},
    "shrine_blood": {"blood", "bleed"},
    "shrine_gold": {"gold", "coins", "pay"},
    "chest": {"chest"},
    "fountain": {"fountain", "drink"},
}
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
    if BOMB_WORDS & set(words):  # "bomb the east wall", "blow up the west wall", or in a fight, "throw a bomb"
        for word in words:
            if f"bomb:{DIRECTION_ALIASES.get(word, word)}" in ids:
                return _action(f"bomb:{DIRECTION_ALIASES.get(word, word)}"), True
        if "bomb" in ids:
            return _action("bomb"), True
    for word in words:
        direction = DIRECTION_ALIASES.get(word, word)
        if f"go:{direction}" in ids and (short or words[0] in MOVE_WORDS):
            return _action(f"go:{direction}"), short
    if words[0] in ATTACK_WORDS and "attack" in ids:
        return _action("attack"), len(words) <= 4
    if words[0] in DODGE_WORDS and "dodge" in ids:
        return _action("dodge"), len(words) <= 3
    for action_id, keywords in FIXTURE_WORDS.items():
        if action_id in ids and keywords & set(words) and (short or action_id == "descend"):
            return _action(action_id), True
    if FLEE_WORDS & set(words) and "flee" in ids:
        return _action("flee"), short
    if words[0] in REST_WORDS and "rest" in ids:
        return _action("rest"), short
    if words[0] in TAKE_WORDS:
        match = _best_target(words, actions, "take:")
        if match:
            return _action(match.id), True
    if words[0] in USE_WORDS:
        match = (_best_target(words, actions, "use:") or _best_target(words, actions, "throw:")
                 or _best_target(words, actions, "reveal:"))
        if match:
            return _action(match.id), True
    if words[0] in DISTRACT_WORDS:
        match = _best_target(words, actions, "distract:")
        if match:
            return _action(match.id), True
    if "ask" in ids:  # a calm creature: "ask the goblin about secrets", "watch the rat" (small talk isn't asking)
        if words[0] in ASK_WORDS and (TIP_WORDS & set(words) or len(words) <= 3):
            return _action("ask"), True
        if words[0] in WATCH_WORDS and (_best_target(words, actions, "ask") or len(words) <= 2):
            return _action("ask"), True
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
                    actions: list[Action], trust_keywords: bool = True) -> tuple[Intent, str | None]:
    """Returns the intent and, if the model failed, an error message for the log. Commands the keyword matcher is
    sure of skip the model, unless `trust_keywords` is off (when checking what the model itself makes of them)."""
    fallback, confident = offline_interpret(raw, actions)
    if llm is None or (confident and trust_keywords):
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


SCENE_SYSTEM = """\
You match a player's typed words to the choices in a scripted scene of a text adventure.
Reply with JSON: {"choice": N, "question": false}
- choice: the number of the choice the player's words mean or amount to. Judge the action, not the exact
  wording: "let my sword arm fall to my side" amounts to lowering a weapon; "smash it" amounts to attacking.
  Use 0 if the words don't fit any choice.
- question: true only if the player is asking about the scene instead of doing something.
"""

SCENE_SCHEMA = {
    "type": "object",
    "properties": {"choice": {"type": "integer"}, "question": {"type": "boolean"}},
    "required": ["choice", "question"],
    "additionalProperties": False,
}


async def scene_choice(llm: LLM, scene_text: str, labels: list[str], raw: str) -> tuple[int | None, bool, str | None]:
    """Which of a scene's choices the player's words amount to: (index or None, is it a question, error)."""
    listed = "\n".join(f"{i}. {label}" for i, label in enumerate(labels, 1))
    user = f"SCENE:\n{scene_text}\n\nCHOICES:\n{listed}\n\nPLAYER TYPED:\n{raw}"
    try:
        reply = await llm.complete_json(SCENE_SYSTEM, user, SCENE_SCHEMA, max_tokens=60)
        choice, question = int(reply.get("choice", 0)), bool(reply.get("question", False))
    except (LLMError, ValueError, TypeError) as e:
        return None, False, f"scene: {e}"
    return (choice - 1 if 1 <= choice <= len(labels) else None), question, None
