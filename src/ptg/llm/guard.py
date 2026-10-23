"""Keeps the narrator honest: its prose is checked against the facts a sentence at a time, as it streams.

Small local models drift in the same few ways. They echo the prompt, talk about "the player" or being an AI, ask
the player what they'll do, call a room they've never seen familiar, invent exits, items and monsters, and run on.
The facts are the truth, so a sentence that breaks one of these rules is left out before anyone sees it, and the
rest is kept. If nothing survives, the narration falls back to the facts themselves. Each dropped sentence and the
reason is returned (and written to llm.log), so `python -m ptg.llm.check` can show how often a model slips.

The rules are deliberately narrow: they look for contradictions of things the game knows, not for good writing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..content import Content
from ..events import Event
from ..models import GameState

SENTENCE_END = re.compile(r"[.!?…]+[\"'”’)]*\s+|\n+")
ECHO = re.compile(r"^\W*(setting|recently|this turn|room|player typed|facts|how you described|location|exits)\b.{0,40}:",
                  re.I)
META = re.compile(r"\b(as an ai|language model|i'm sorry|i cannot|i can't help|let me know|the player|the narrator|"
                  r"the facts|narration)\b", re.I)
QUESTION = re.compile(r"^(what|will|do|would|shall|where|which|how|are|can)\b[^?]*\byou\b[^?]*\?\W*$", re.I)
OPTIONS = re.compile(r"\b(your (options|choices) (are|include)|options?:|you (could|can|may|might) (choose|decide|either)"
                     r"|would you like)\b", re.I)
# Familiar words only count against the room the player is in ("back into the Alcove you just left"); going back
# the way you came ("the path west leads back to the Forge") is fine.
FAMILIAR = re.compile(r"\b(back (in|into|inside|to the)|again|once more|return(s|ing|ed)? to|familiar|you just left|"
                      r"as before)\b", re.I)
BEEN_HERE = re.compile(r"\byou('ve| have) (been|seen) (here|this)\b", re.I)
# A direction with one of these a few words away claims a way out ("a passage north", "the only way out is to
# the east", "you can head west"); positions in the room ("a pew sits to the north") don't.
EXIT_WORDS = {"exit", "exits", "door", "doors", "doorway", "doorways", "passage", "passages", "corridor", "corridors",
              "arch", "archway", "archways", "path", "paths", "way", "opening", "openings", "tunnel", "tunnels",
              "stairs", "staircase", "lead", "leads", "leading", "head", "heads", "heading", "go", "goes", "continue"}
NEAR = 5
YOU_CAN = re.compile(r"\byou (can|could|may|might)\b", re.I)
DIRECTION = re.compile(r"(north|south|east|west)(ern|ward|wards)?$")
SIMILE = re.compile(r"\b(like|as)\s+(a|an)\s*$", re.I)


def tidy(sentence: str) -> str:
    """No markdown, no list markers, one line."""
    sentence = re.sub(r"[*_#`]+", "", sentence)
    sentence = re.sub(r"^\s*(?:[-•>]|\d+[.)])\s+", "", sentence)
    return re.sub(r"\s+", " ", sentence).strip()


@dataclass
class Rules:
    """What the game knows this turn, and the narrow checks a sentence must pass."""

    exits: set[str]
    first_visit: bool
    known: str  # everything the model was told, lower case: facts, setting, recent lines, what's here
    things: list[str]  # names of items and monsters it could invent
    room: str = ""  # the room the player is in, lower case
    travel: set[str] = field(default_factory=set)  # the way the player moved this turn

    @classmethod
    def for_turn(cls, state: GameState, content: Content, events: list[Event], opening: bool = False,
                 question: bool = False) -> Rules:
        from .prompts import situation

        room = state.room
        arrived = next((e for e in events if e.kind in ("enter", "descend")), None)
        player = state.player
        known = [e.text for e in events] + state.journal[-6:]
        known += [content.themes[state.theme].blurb, content.archetypes[room.archetype].blurb, room.name]
        known += [f.name for f in room.features] + [content.item(k).name for k in room.items]
        known += [content.item(k).name for k in [player.weapon, player.armor, *player.inventory] if k]
        known += [room.monster.name, content.monster(room.monster.key).desc] if room.monster else []
        if question:
            known.append(situation(state, content))
        things = sorted({i.name.lower() for i in content.items.values()} |
                        {m.name.lower() for m in content.monsters.values()}, key=len, reverse=True)
        travel = {e.data["direction"] for e in events if e.kind == "enter" and e.data.get("direction")}
        return cls(set(room.exits), opening or bool(arrived and arrived.data.get("first")), " ".join(known).lower(),
                   things, room.name.lower(), travel)

    def _names_room(self, lowered: str) -> bool:
        head = self.room.split()[-1] if self.room else ""
        return bool(self.room) and (self.room in lowered or re.search(rf"\b{re.escape(head)}\b", lowered) is not None)

    def _ways_out(self, sentence: str) -> set[str]:
        """The directions the sentence claims there's a way out (or in) towards."""
        words = re.findall(r"[\w'-]+", sentence.lower())
        found = set()
        for i, word in enumerate(words):
            if (m := DIRECTION.match(word)) and EXIT_WORDS & set(words[max(0, i - NEAR):i + NEAR + 1]):
                found.add(m.group(1))
        return found

    def problem(self, sentence: str) -> str | None:
        """Why this sentence can't be kept, or None."""
        if ECHO.search(sentence):
            return "echoes the prompt"
        if META.search(sentence):
            return "talks about the game, not in it"
        if QUESTION.search(sentence) or OPTIONS.search(sentence):
            return "puts choices to the player"
        lowered = sentence.lower()
        if self.first_visit and (BEEN_HERE.search(sentence) or (FAMILIAR.search(sentence) and self._names_room(lowered))):
            return "calls a new room familiar"
        ways = self._ways_out(sentence)
        if ways - self.exits - self.travel:
            return f"invents a way {', '.join(sorted(ways - self.exits - self.travel))}"
        if ways and YOU_CAN.search(sentence) and ways != self.exits:
            return "lists only some of the exits"
        for name in self.things:  # "the ghost of a plan" and "pale as a ghost" aren't monsters
            for match in re.finditer(rf"(?<![-\w]){re.escape(name)}s?(?![-\w])(?! of\b)", lowered):
                if name not in self.known and not SIMILE.search(lowered[:match.start()]):
                    return f"invents {name}"
        return None


@dataclass
class Gate:
    """Lets the narrator's sentences through as each one finishes, if it passes the rules, up to `limit`."""

    rules: Rules
    limit: int = 5
    kept: list[str] = field(default_factory=list)
    dropped: list[tuple[str, str]] = field(default_factory=list)
    buffer: str = ""

    def feed(self, chunk: str) -> list[str]:
        """Add streamed text; returns the sentences it completed that can be shown."""
        self.buffer += chunk
        out = []
        while (end := SENTENCE_END.search(self.buffer)) is not None:
            sentence, self.buffer = self.buffer[:end.end()], self.buffer[end.end():]
            if (kept := self._admit(sentence)) is not None:
                out.append(kept)
        return out

    def finish(self) -> list[str]:
        rest, self.buffer = self.buffer, ""
        kept = self._admit(rest)
        return [kept] if kept is not None else []

    def _admit(self, sentence: str) -> str | None:
        sentence = tidy(sentence)
        if not sentence:
            return None
        reason = "goes on too long" if len(self.kept) >= self.limit else self.rules.problem(sentence)
        if reason:
            self.dropped.append((sentence, reason))
            return None
        self.kept.append(sentence)
        return sentence

    @property
    def text(self) -> str:
        return " ".join(self.kept)


def sentence_limit(first_visit: bool, in_combat: bool) -> int:
    """The prompt asks for 3-5, 1-3 or 2-4 sentences; allow one more than the most before cutting."""
    return 6 if first_visit else (4 if in_combat else 5)


def check(text: str, rules: Rules, limit: int = 5) -> Gate:
    """Run finished text through the gate (for text that wasn't streamed, and for tests)."""
    gate = Gate(rules, limit)
    gate.feed(text)
    gate.finish()
    return gate

