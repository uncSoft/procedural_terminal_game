"""Turns resolved events into prose: streamed from the language model, or stitched from facts when offline."""

from __future__ import annotations

import re
from typing import Callable

from ..content import Content
from ..models import GameState
from ..events import Event
from ..rules import room_facts
from .base import LLM, LLMError, log_exchange
from .guard import Gate, Rules, sentence_limit
from .prompts import INTRO_SYSTEM, OFFLINE_INTRO, narrator_messages, player_status

TextSink = Callable[[str], None]


def clean(text: str) -> str:
    text = re.sub(r"[*_#`]+", "", text)
    return re.sub(r"\s+\n", "\n", text).strip()


def offline_narration(state: GameState, content: Content, events: list[Event], raw: str = "",
                      question: bool = False, opening: bool = False) -> str:
    parts: list[str] = []
    if opening:
        parts.append(content.themes[state.theme].blurb)
    for event in events:
        if event.kind in ("enter", "descend") and event.data.get("first"):
            parts.append(content.archetypes[state.rooms[event.data["room"]].archetype].blurb)
        parts.append(event.text)
    if question:
        parts += [player_status(state, content), room_facts(state, content)]
    if not parts:
        parts.append(f"You {raw.strip().rstrip('.').lower()}. The dungeon is unimpressed." if raw else "Nothing happens.")
    return " ".join(parts)


async def narrate(llm: LLM | None, state: GameState, content: Content, raw: str, events: list[Event],
                  tone: str, on_text: TextSink, question: bool = False, opening: bool = False) -> tuple[str, str | None]:
    """Streams narration to on_text a sentence at a time, each checked against the facts first (see guard.py),
    and returns (final text, error or None)."""
    if llm is None:
        text = offline_narration(state, content, events, raw, question, opening)
        on_text(text)
        return text, None
    system, user = narrator_messages(state, content, raw, events, tone, question=question, opening=opening)
    rules = Rules.for_turn(state, content, events, opening, question)
    gate = Gate(rules, sentence_limit(rules.first_visit, state.in_combat))
    error = None
    try:
        async for chunk in llm.stream_text(system, user, max_tokens=500):
            for sentence in gate.feed(chunk):
                on_text(sentence + " ")
    except LLMError as e:
        error = f"narrator: {e}"
    for sentence in gate.finish():
        on_text(sentence + " ")
    if gate.dropped:
        log_exchange("guard", [f"{why}: {sentence}" for sentence, why in gate.dropped], gate.text)
    text = gate.text
    if not text:
        text = offline_narration(state, content, events, raw, question, opening)
        on_text(text)
    return text, error


async def intro(llm: LLM | None, name: str, dungeon: str, on_text: TextSink) -> str:
    if llm is not None:
        parts: list[str] = []
        try:
            async for chunk in llm.stream_text(INTRO_SYSTEM.format(name=name, dungeon=dungeon), "Begin.", max_tokens=300):
                parts.append(chunk)
                on_text(chunk)
        except LLMError:
            pass
        if "".join(parts).strip():
            return clean("".join(parts))
    text = OFFLINE_INTRO.format(name=name, dungeon=dungeon)
    on_text(text)
    return text
