"""One play session: interpret input, resolve it with the rules, narrate the result, autosave.

Both the Textual UI and the plain text mode drive the game through this class.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .config import Config, save_game
from .content import Content, load_content
from .intent import Intent
from .llm import LLM
from .llm.interpreter import interpret
from .llm.narrator import narrate
from .models import GameState, LogEntry
from .rules import Action, Event, available_actions, perform, perform_creative, perform_flavor, room_facts, the

JOURNAL_SKIP = {"miss", "monster_miss", "stunned", "check", "info"}


@dataclass
class TurnResult:
    narration: str
    events: list[Event] = field(default_factory=list)
    intent: Intent | None = None
    errors: list[str] = field(default_factory=list)


class Game:
    def __init__(self, state: GameState, config: Config, llm: LLM | None = None,
                 content: Content | None = None, autosave: bool = True):
        self.state = state
        self.config = config
        self.llm = llm
        self.content = content or load_content()
        self.autosave = autosave

    @property
    def actions(self) -> list[Action]:
        return available_actions(self.state, self.content)

    @property
    def theme(self):
        return self.content.themes[self.state.theme]

    async def opening(self, on_text: Callable[[str], None]) -> TurnResult:
        room = self.state.room
        arrival = Event("enter", f"You stand in {the(room.name)}, at the entrance of {self.theme.name}. "
                                 f"{room_facts(self.state, self.content)} Your goal: {self.theme.goal}",
                        data={"first": True, "room": room.id})
        text, error = await narrate(self.llm, self.state, self.content, "", [arrival], self.config.tone, on_text,
                                    opening=True)
        self.state.room.description = text
        self.state.journal.append(f"You arrived in {self.state.room.name}, the entrance of {self.theme.name}.")
        self.state.log.append(LogEntry(kind="narration", text=text))
        self._save()
        return TurnResult(text, errors=[error] if error else [])

    async def act(self, raw: str, on_text: Callable[[str], None],
                  on_resolved: Callable[[list[Event]], None] | None = None) -> TurnResult:
        raw = raw.strip()
        actions = self.actions
        errors: list[str] = []
        if raw.isdigit() and 1 <= int(raw) <= len(actions):
            chosen = actions[int(raw) - 1]
            intent, shown = Intent(kind="action", action_id=chosen.id, difficulty="trivial"), chosen.label
        else:
            intent, error = await interpret(self.llm, self.state, self.content, raw, actions)
            shown = raw
            if error:
                errors.append(error)
        self.state.log.append(LogEntry(kind="player", text=shown))

        if intent.kind == "action":
            events = perform(self.state, self.content, intent.action_id)
        elif intent.kind == "creative":
            intent, events = perform_creative(self.state, self.content, intent)
        elif intent.kind == "flavor":
            events = perform_flavor(self.state, self.content)
        else:
            events = []
        for event in events:
            if event.roll:
                self.state.log.append(LogEntry(kind="mechanic", text=event.roll))
        if on_resolved:
            on_resolved(events)

        player_words = shown if intent.kind != "action" else f"(chose) {shown}"
        text, error = await narrate(self.llm, self.state, self.content, player_words, events, self.config.tone,
                                    on_text, question=intent.kind == "question")
        if error:
            errors.append(error)
        for event in events:
            if event.kind == "enter" and event.data.get("first"):
                self.state.rooms[event.data["room"]].description = text
        self.state.journal += [e.text for e in events if e.kind not in JOURNAL_SKIP]
        self.state.journal = self.state.journal[-30:]
        self.state.log.append(LogEntry(kind="narration", text=text))
        for error in errors:
            self.state.log.append(LogEntry(kind="system", text=error))
        self._save()
        return TurnResult(text, events, intent, errors)

    def _save(self) -> None:
        if self.autosave:
            save_game(self.state)

    async def aclose(self) -> None:
        if self.llm is not None:
            await self.llm.aclose()
