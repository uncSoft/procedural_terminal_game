"""Turns resolved events into prose: streamed from the language model, or stitched from facts when offline."""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from typing import Callable

from ..content import Content
from ..models import GameState
from ..events import Event
from ..text import the
from .base import LLM, LLMError, log_exchange
from .guard import Gate, Rules, sentence_limit
from .prompts import INTRO_SYSTEM, OFFLINE_INTRO, health_word, narrator_messages, plain

TextSink = Callable[[str], None]
EARLIER = re.compile(r" Earlier here: .*$")  # (what the model is told of a room's past: the stage shows how it is)


def clean(text: str) -> str:
    text = re.sub(r"[*_#`]+", "", text)
    return re.sub(r"\s+\n", "\n", text).strip()


def offline_answer(state: GameState, content: Content) -> str:
    """A question put to the dungeon with no model: how you are and what you hold, in a line, not the status block."""
    player = state.player
    carried = [f"{content.item(key).name}{f' ×{n}' if n > 1 else ''}" for key, n in Counter(player.inventory).items()]
    carried += [f"{n} {word}{'s' if n > 1 else ''}" for n, word in ((player.gold, "gold"), (player.bombs, "bomb"),
                                                                 (player.keys, "small key")) if n]
    armor = f"wear {the(content.item(player.armor).name)}" if player.armor else "wear no armor"
    return (f"You are {health_word(player.hp, player.max_hp)}. You wield {the(content.item(player.weapon).name)} and "
            f"{armor}. In your pack: {', '.join(carried) or 'nothing'}.")


def offline_narration(state: GameState, content: Content, events: list[Event], raw: str = "",
                      question: bool = False, opening: bool = False) -> str:
    """The story with no model (or none of what it said fit to show): the room's blurb on arrival, then what happened in
    the facts' own words, without the numbers the screen shows (damage, HP, XP, counts), and without listing what's
    here, which the screen shows too. A question is answered, not read the prompt."""
    parts: list[str] = []
    if opening:
        parts.append(content.themes[state.theme].blurb)
    for event in events:
        if event.kind in ("enter", "descend") and event.data.get("first"):
            parts.append(content.archetypes[state.rooms[event.data["room"]].archetype].blurb)
        parts.append(EARLIER.sub("", plain(event.text, health=False)))
    if question:
        parts.append(offline_answer(state, content))
    if not parts:  # words that came to nothing: told as tried, never as done ("You give the tooth to lenny.")
        said = re.sub(r"^i\s+", "", raw.strip().rstrip(".!").lower())
        parts.append(f"You try to {said}, but nothing comes of it. The dungeon is unimpressed." if said
                     else "Nothing happens.")
    return " ".join(parts)


async def narrate(llm: LLM | None, state: GameState, content: Content, raw: str, events: list[Event],
                  tone: str, on_text: TextSink, question: bool = False, opening: bool = False,
                  stop: asyncio.Event | None = None) -> tuple[str, str | None]:
    """Streams narration to on_text a sentence at a time, each checked against the facts first (see guard.py),
    and returns (final text, error or None). Set `stop` to cut it short (the player's moved on): what's been told so
    far, whole sentences only, stands, or the engine's own words if nothing had been yet."""
    if llm is None:
        text = offline_narration(state, content, events, raw, question, opening)
        on_text(text)
        return text, None
    system, user = narrator_messages(state, content, raw, events, tone, question=question, opening=opening)
    rules = Rules.for_turn(state, content, events, opening, question)
    gate = Gate(rules, sentence_limit(rules.first_visit, state.in_combat))
    error = None

    async def tell() -> None:
        async for chunk in llm.stream_text(system, user, max_tokens=500):
            for sentence in gate.feed(chunk):
                on_text(sentence + " ")

    cut = False
    try:
        if stop is None:
            await tell()
        else:
            telling, stopped = asyncio.ensure_future(tell()), asyncio.ensure_future(stop.wait())
            await asyncio.wait({telling, stopped}, return_when=asyncio.FIRST_COMPLETED)
            stopped.cancel()
            if not telling.done():  # (cut short: the stream's dropped, which stops the model too)
                cut = True
                telling.cancel()
                await asyncio.gather(telling, return_exceptions=True)
            else:
                telling.result()
    except LLMError as e:
        error = f"narrator: {e}"
    for sentence in [] if cut else gate.finish():  # (cut, a sentence half told is left out)
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
