"""One play session. A turn has two phases so the dice can be shown (and rerolled with Fate) before the
narrator commits to a story:

    pending = await game.begin("throw the oil at the troll")   # interpret + resolve
    if pending.can_reroll: pending = game.reroll()             # spend Fate: rewind and roll again
    result = await game.finish(on_text)                        # narrate, log, save, update the profile

Both the Textual UI and the plain text mode drive the game through this class.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Callable

from .config import Config, save_game
from .content import Content, load_content
from .events import Action, Event
from .intent import Intent
from .llm import LLM
from .llm import extras
from .llm.interpreter import interpret
from .llm.narrator import narrate
from .meta import record_end
from .models import GameState, LogEntry
from .profile import Profile
from .rules import available_actions, perform, perform_creative, perform_flavor, room_facts
from .text import the

JOURNAL_SKIP = {"miss", "monster_miss", "stunned", "check", "info", "spend", "fate"}
QUIET_KINDS = {"perk"}  # resolved without asking the narrator


@dataclass
class Pending:
    raw: str
    shown: str
    intent: Intent
    original: Intent
    events: list[Event] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def primary(self) -> Event | None:
        """The roll a Fate token could change: the player's first skill check this turn."""
        return next((e for e in self.events if e.dice and e.dice.actor == "player" and e.data.get("rerollable")), None)


@dataclass
class TurnResult:
    narration: str
    events: list[Event] = field(default_factory=list)
    intent: Intent | None = None
    errors: list[str] = field(default_factory=list)


class Game:
    def __init__(self, state: GameState, config: Config, llm: LLM | None = None, content: Content | None = None,
                 profile: Profile | None = None, autosave: bool = True):
        self.state = state
        self.config = config
        self.llm = llm
        self.content = content or load_content()
        self.profile = profile or Profile.open()
        self.autosave = autosave
        self.pending: Pending | None = None
        self._snapshot: GameState | None = None
        self._rerolls = 0
        self._suggested_for: tuple | None = None
        self._background: set[asyncio.Task] = set()

    # --- what the player sees ---

    @property
    def theme(self):
        return self.content.themes[self.state.theme]

    @property
    def actions(self) -> list[Action]:
        return available_actions(self.state, self.content)

    def choices(self) -> list[Action]:
        """The numbered choices: engine actions, plus one suggested trick when there is one."""
        actions = self.actions
        if self.state.suggestion and not self.state.pending_perks and not self.state.over:
            actions = actions + [Action("suggest", f"✦ {self.state.suggestion}", "improvise")]
        return actions

    def scene_key(self) -> tuple:
        room = self.state.room
        return (self.state.floor, room.id, self.state.in_combat, room.monster.key if room.monster else "")

    def fate_left(self) -> int:
        """Fate available for a reroll of the pending turn."""
        if self._snapshot is None:
            return self.state.player.fate
        return self._snapshot.player.fate - self._rerolls

    def can_reroll(self) -> bool:
        primary = self.pending.primary if self.pending else None
        return bool(primary and not primary.dice.success and self._snapshot and self.fate_left() > 0)

    # --- turns ---

    async def opening(self, on_text: Callable[[str], None]) -> TurnResult:
        room = self.state.room
        arrival = Event("enter", f"You stand in {the(room.name)}, at the entrance of {self.theme.name}, floor 1 of "
                                 f"{self.state.floors_total}. {room_facts(self.state, self.content)}",
                        data={"first": True, "room": room.id})
        text, error = await narrate(self.llm, self.state, self.content, "", [arrival], self.config.tone, on_text,
                                    opening=True)
        room.description = text
        self.state.journal.append(f"You arrived in {room.name}, the entrance of {self.theme.name}.")
        self.state.log.append(LogEntry(kind="narration", text=text))
        self._save()
        return TurnResult(text, [arrival], errors=[error] if error else [])

    async def begin(self, raw: str) -> Pending:
        raw = raw.strip()
        choices = self.choices()
        errors: list[str] = []
        chosen = choices[int(raw) - 1] if raw.isdigit() and 1 <= int(raw) <= len(choices) else None
        if chosen and chosen.id == "suggest":
            raw, chosen = self.state.suggestion, None
        if chosen:
            intent, shown = Intent(kind="action", action_id=chosen.id, difficulty="trivial"), chosen.label
        else:
            intent, error = await interpret(self.llm, self.state, self.content, raw, self.actions)
            shown = raw
            if error:
                errors.append(error)
        self._snapshot = self.state.model_copy(deep=True)
        self._rerolls = 0
        self.pending = Pending(raw, shown, intent, intent, errors=errors)
        self._resolve()
        return self.pending

    def reroll(self) -> Pending:
        """Spend a Fate token: rewind to before the roll and resolve the same intent with fresh dice."""
        if not self.can_reroll():
            raise RuntimeError("nothing to reroll")
        self._rerolls += 1
        restored = self._snapshot.model_copy(deep=True)
        restored.player.fate -= self._rerolls
        restored.reroll = self._rerolls  # a different random stream for the same turn
        self.state = restored
        self._resolve()
        self.pending.events.insert(0, Event("fate_spent", f"You spend a Fate token to reroll "
                                                          f"({self.state.player.fate} left)."))
        return self.pending

    def _resolve(self) -> None:
        pending, state = self.pending, self.state
        intent = pending.original
        if intent.kind == "action":
            events = perform(state, self.content, intent.action_id)
        elif intent.kind == "creative":
            intent, events = perform_creative(state, self.content, intent)
        elif intent.kind == "flavor":
            events = perform_flavor(state, self.content)
        else:
            events = []
        pending.intent = intent
        pending.events = events

    async def finish(self, on_text: Callable[[str], None]) -> TurnResult:
        pending, state = self.pending, self.state
        self.pending, self._snapshot = None, None
        state.log.append(LogEntry(kind="player", text=pending.shown))
        for event in pending.events:
            if event.roll:
                state.log.append(LogEntry(kind="mechanic", text=event.roll))

        errors = list(pending.errors)
        if pending.events and all(e.kind in QUIET_KINDS for e in pending.events):
            text = " ".join(e.text for e in pending.events)
            on_text(text)
        else:
            words = pending.shown if pending.intent.kind != "action" else f"(chose) {pending.shown}"
            text, error = await narrate(self.llm, state, self.content, words, pending.events, self.config.tone,
                                        on_text, question=pending.intent.kind == "question")
            if error:
                errors.append(error)
        for event in pending.events:
            if event.kind in ("enter", "descend") and event.data.get("first"):
                state.rooms[event.data["room"]].description = text
        state.journal += [e.text for e in pending.events if e.kind not in JOURNAL_SKIP]
        state.journal = state.journal[-200:]
        state.log.append(LogEntry(kind="narration", text=text))
        for error in errors:
            state.log.append(LogEntry(kind="system", text=error))
        if self.scene_key() != self._suggested_for:
            state.suggestion = ""
        self._update_profile(pending.events)
        if state.over:
            state.epitaph = await extras.epitaph(self.llm, state)
            state.log.append(LogEntry(kind="system", text=f"Epitaph: {state.epitaph}"))
            record_end(self.profile, state)
        self._save()
        return TurnResult(text, pending.events, pending.intent, errors)

    async def act(self, raw: str, on_text: Callable[[str], None],
                  on_resolved: Callable[[list[Event]], None] | None = None) -> TurnResult:
        """One whole turn with no rerolls (plain mode, tests)."""
        pending = await self.begin(raw)
        if on_resolved:
            on_resolved(pending.events)
        return await self.finish(on_text)

    # --- extras ---

    async def refresh_suggestion(self) -> str:
        """Ask for a fresh suggested trick when the scene changes. Cheap to call every turn."""
        key = self.scene_key()
        if self.state.over or key == self._suggested_for:
            return self.state.suggestion
        self._suggested_for = key
        self.state.suggestion = await extras.suggestion(self.llm, self.state, self.content)
        return self.state.suggestion

    async def recap(self) -> str:
        return await extras.recap(self.llm, self.state)

    def _update_profile(self, events: list[Event]) -> None:
        profile, state = self.profile, self.state
        for event in events:
            monster = event.data.get("monster")
            if event.kind in ("enter", "ambush", "descend") and monster:
                if profile.bump_beast(monster, "seen") == 1:
                    self._spawn(self._write_lore(monster))
            elif event.kind == "defeat" and monster:
                profile.bump_beast(monster, "killed")
            elif event.kind == "pacify" and monster:
                profile.bump_beast(monster, "pacified")
            elif event.kind == "death" and monster:
                profile.bump_beast(monster, "killed_you")
            elif event.kind == "weakness" and monster:
                profile.add_weakness(monster, event.data["tag"])
            if event.kind == "ghost_rest" and event.data.get("ghost_id"):
                profile.rest_ghost(event.data["ghost_id"])
        profile.log(state.run_id, state.turn, [(e.kind, e.text) for e in events])

    async def _write_lore(self, monster: str) -> None:
        text = await extras.lore(self.llm, self.content, monster)
        if text:
            self.profile.set_lore(monster, text)

    def _spawn(self, coro) -> None:
        try:
            task = asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            coro.close()
            return
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    def _save(self) -> None:
        if self.autosave:
            save_game(self.state)

    async def aclose(self) -> None:
        for task in list(self._background):
            try:
                await asyncio.wait_for(task, timeout=10)
            except (asyncio.TimeoutError, Exception):
                task.cancel()
        if self.llm is not None:
            await self.llm.aclose()
