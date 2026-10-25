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

from . import powers
from .config import Config, save_game
from .content import Content, load_content
from .events import Action, Event
from .intent import Intent
from .llm import LLM
from .llm import extras
from .llm.interpreter import guessed, interpret, scene_choice
from .llm.narrator import narrate
from .meta import record_end
from .models import GameState, LogEntry
from .outcome import verdict
from .profile import Profile
from .rules import (arrival_facts, available_actions, locked_doors, perform, perform_creative, perform_flavor,
                    unlisted)
from .story import STORY_KINDS, Library, ProfileView, StoryEngine, load_library
from .text import the

JOURNAL_SKIP = {"miss", "monster_miss", "stunned", "check", "info", "spend", "fate", "fate_spent", "story_seen",
                "story_mark", "story_context"}
QUIET_KINDS = {"perk"}  # resolved without asking the narrator
MECHANICS = {"fate_spent", "level", "trait"}  # the screen says these (a line, the level-up screen, a banner): not told


def narratable(event: Event) -> bool:
    """Story text written in the author's exact words is shown as-is, never re-told by the narrator (nor is what its
    effects did, such as a ghost a [calm] laid to rest)."""
    if event.data.get("told_by") in ("exact", "silent") or event.kind in MECHANICS:
        return False
    return event.kind not in STORY_KINDS or (event.kind == "story" and event.data.get("voice") == "narrated")


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
                 profile: Profile | None = None, autosave: bool = True, library: Library | None = None):
        self.state = state
        self.config = config
        self.llm = llm
        self.content = content or load_content()
        self.profile = profile or Profile.open()
        self.autosave = autosave and not state.test_room  # a test room never saves over your real run
        self.pending: Pending | None = None
        self._snapshot: GameState | None = None
        self._rerolls = 0
        self._suggested_for: tuple | None = None
        self._background: set[asyncio.Task] = set()
        self.story = StoryEngine(library or load_library(self.content), self.content,
                                 ProfileView.from_profile(self.profile))
        self.story.tampered = state.modded
        self.force_event: str | None = None  # fire this story event right after the opening (for testing)

    # --- what the player sees ---

    @property
    def theme(self):
        return self.content.themes[self.state.theme]

    @property
    def actions(self) -> list[Action]:
        return available_actions(self.state, self.content)

    def choices(self) -> list[Action]:
        """The numbered choices: a scene's authored choices, or engine actions plus one suggested trick."""
        if self.state.scene:
            return self.story.scene_actions(self.state)
        actions = self.actions
        if self.state.suggestion and not self.state.pending_perks and not self.state.over:
            actions = actions + [Action("suggest", f"✦ {self.state.suggestion}", "improvise")]
        return actions

    def locked_doors(self) -> list[Action]:
        """The doors here you can't open yet, for the arrow pad: not choices, but trying one says it's locked (and
        costs nothing). None in a scene, which has its own choices."""
        return [] if self.state.scene else locked_doors(self.state, self.content)

    def suggestion_pending(self) -> bool:
        """Whether a suggested trick for this scene is still to be thought of (see refresh_suggestion)."""
        state = self.state
        return not (state.scene or state.over or state.pending_perks) and self.scene_key() != self._suggested_for

    def scene_key(self) -> tuple:
        """What the suggested trick was thought of for: where you are, who's here and how it stands with them, what you
        carry (a trick with something that's used up goes with it) and what's still to search."""
        state, room = self.state, self.state.room
        monster = room.monster
        return (state.floor, room.id, state.in_combat, monster.key if monster else "",
                bool(monster and monster.hostile), bool(monster and monster.distracted),
                tuple(state.known_weak.get(monster.key, []) if monster else ()), tuple(sorted(state.player.inventory)),
                state.player.gold, tuple(f.searched for f in room.features), room.room_searched)

    def fate_left(self) -> int:
        """Fate available for a reroll of the pending turn."""
        if self._snapshot is None:
            return self.state.player.fate
        return self._snapshot.player.fate - self._rerolls

    def floor_entry(self) -> LogEntry:
        """The story's header for the floor you're on."""
        return LogEntry(kind="floor", title=f"Floor {self.state.floor} of {self.state.floors_total}",
                        text=self.theme.name)

    def can_reroll(self) -> bool:
        primary = self.pending.primary if self.pending else None
        return bool(primary and not primary.dice.success and self._snapshot and self.fate_left() > 0)

    # --- turns ---

    async def opening(self, on_text: Callable[[str], None]) -> TurnResult:
        room, state = self.state.room, self.state
        where = (f"somewhere in {self.theme.name}" if state.test_room else f"at the entrance of {self.theme.name}")
        told = f"You stand in {the(room.name)}, {where}. {arrival_facts(state, self.content)}"
        arrival = Event("enter", told.strip(), data={"first": True, "room": room.id})
        text, error = await narrate(self.llm, self.state, self.content, "", [arrival], self.config.tone, on_text,
                                    opening=True)
        room.description = self.content.archetypes[room.archetype].blurb  # (what the narrator said goes stale)
        self.state.journal.append(f"You arrived in {the(room.name)}, {where.replace('at the', 'the')}.")
        self.state.log.append(self.floor_entry())
        self.state.log.append(LogEntry(kind="narration", text=text))
        events = [] if state.test_room else self.story.on_run_start(state)  # (a test room isn't a run's start)
        if self.force_event:
            events += self.story.force(self.state, self.force_event)
            self.force_event = None
        self._record_story(events)
        self._save()
        return TurnResult(text, [arrival] + events, errors=[error] if error else [])

    async def begin(self, raw: str, action: Action | None = None) -> Pending:
        """Work out what the player meant and resolve it (the narrator comes in `finish`). An `action` given is taken
        as it is: the shop's own screen buys and barters this way, outside the numbered choices."""
        raw = raw.strip()
        errors: list[str] = []
        if action is not None:
            intent, shown, error = Intent(kind="action", action_id=action.id, difficulty="trivial"), action.label, None
        elif self.state.scene:
            intent, shown, error = await self._read_scene_input(raw)
        elif not raw.isdigit() and self.story.wants_say(self.state, raw):
            intent, shown, error = Intent(kind="action", action_id="story:say", difficulty="trivial"), raw, None
        else:
            choices = self.choices()
            guess = guessed(raw, choices) if raw.isdigit() else None  # while Swoogy waits, "3" is a guess of 3
            chosen = next(a for a in choices if a.id == guess) if guess else \
                choices[int(raw) - 1] if raw.isdigit() and 1 <= int(raw) <= len(choices) else None
            if chosen and chosen.id == "suggest":
                if self.state.suggestion_id:  # just the use it was thought of as: not its words, read again
                    chosen = Action(self.state.suggestion_id, self.state.suggestion)
                else:
                    raw, chosen = self.state.suggestion, None
            if chosen:
                intent, shown, error = Intent(kind="action", action_id=chosen.id, difficulty="trivial"), chosen.label, None
            else:
                intent, error = await interpret(self.llm, self.state, self.content, raw,
                                                self.actions + unlisted(self.state, self.content))
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
        # One line for each token spent, counted from before the roll (a token the new roll wins is its own line).
        snapshot_fate = self._snapshot.player.fate
        self.pending.events[:0] = [Event("fate_spent", f"You spend a Fate token to reroll ({snapshot_fate - n} left).")
                                   for n in range(1, self._rerolls + 1)]
        return self.pending

    async def _read_scene_input(self, raw: str) -> tuple[Intent, str, str | None]:
        """In a scene, input picks one of the authored choices: by number, by the author's keywords, by the
        interpreter's best guess, or else the scene's catch-all."""
        actions = self.story.scene_actions(self.state)
        if raw.isdigit() and 1 <= int(raw) <= len(actions):
            action = actions[int(raw) - 1]
            return Intent(kind="action", action_id=action.id, difficulty="trivial"), action.label, None
        index = self.story.match(self.state, raw)
        if index is not None:
            return Intent(kind="action", action_id=f"scene:{index}", difficulty="trivial"), raw, None
        error = None
        _, node = self.story.current(self.state)
        if self.llm is not None and node is not None:
            index, question, error = await scene_choice(self.llm, node.text, [a.label for a in actions], raw)
            if question:
                return Intent(kind="question", summary=raw), raw, error
            if index is not None:
                return Intent(kind="action", action_id=f"scene:{index}", difficulty="trivial"), raw, error
        if node is not None and node.fallback is not None:
            return Intent(kind="action", action_id="scene:else", difficulty="trivial"), raw, error
        return Intent(kind="flavor", summary=raw), raw, error

    def _resolve(self) -> None:
        pending, state = self.pending, self.state
        intent = pending.original
        story_turn = True
        if intent.kind == "action" and intent.action_id.startswith("scene:"):
            ref = intent.action_id.partition(":")[2]
            events = self.story.choose(state, None if ref == "else" else int(ref))
        elif intent.kind == "action" and intent.action_id == "story:say":
            events = self.story.on_say(state, pending.raw)
        elif state.scene and intent.kind in ("question", "flavor"):
            _, node = self.story.current(state)
            events = [Event("story_context", "A scripted scene is under way, and nothing in it moves or changes "
                                              "until the player chooses. React or answer without making anything "
                                              f"happen. The scene: {node.text}" if node else "")]
        else:
            story_turn = False
        if story_turn:
            powers.settle_stats(state, self.content)  # (a story can give or take things)
            pending.intent, pending.events = intent, events
            return
        if intent.kind == "action":
            events = perform(state, self.content, intent.action_id)
        elif intent.kind == "creative":
            intent, events = perform_creative(state, self.content, intent)
        elif intent.kind == "flavor":
            events = perform_flavor(state, self.content, intent.summary or pending.raw)
        else:
            events = []
        events += self.story.after_turn(state, events)
        powers.settle_stats(state, self.content)
        pending.intent = intent
        pending.events = events

    async def finish(self, on_text: Callable[[str], None]) -> TurnResult:
        pending, state = self.pending, self.state
        self.pending, self._snapshot = None, None
        state.log.append(LogEntry(kind="player", text=pending.shown))
        for event in pending.events:
            if event.roll:  # (with the badge's word, as shown: "- fail" read as one on a search that cost nothing)
                said = f"{event.dice.describe(verdict=False)}  {verdict(event)}" + \
                    (f"  → {event.dice.told()}" if event.dice.told() else "")
                state.log.append(LogEntry(kind="mechanic", text=said))
        if any(e.kind == "descend" for e in pending.events):
            state.log.append(self.floor_entry())
        for event in pending.events:
            if event.kind == "secret_room":
                state.log.append(LogEntry(kind="system", text=f"✧ Secret room found: "
                                                               f"{state.rooms[event.data['room']].name} ✧"))

        errors = list(pending.errors)
        told = [e for e in pending.events if narratable(e)]
        if told and all(e.kind in QUIET_KINDS or e.data.get("quiet") for e in told):  # (cards beside it say theirs)
            text = " ".join(e.text for e in told)
            on_text(text)
        elif pending.events and not told:
            text = ""  # an authored moment (or a character's own words): its cards say it all
        else:
            words = pending.shown if pending.intent.kind != "action" else f"(chose) {pending.shown}"
            text, error = await narrate(self.llm, state, self.content, words, told, self.config.tone,
                                        on_text, question=pending.intent.kind == "question")
            if error:
                errors.append(error)
        for event in pending.events:
            if event.kind in ("enter", "descend") and event.data.get("first"):
                there = state.rooms[event.data["room"]]
                there.description = self.content.archetypes[there.archetype].blurb
        state.journal += [e.data.get("journal", e.text) for e in pending.events  # moves: a line, not the whole room
                          if e.kind not in JOURNAL_SKIP and not e.kind.startswith("story")
                          and e.data.get("journal", e.text)]
        if text:
            state.log.append(LogEntry(kind="narration", text=text))
        self._record_story(pending.events)
        for error in errors:
            state.log.append(LogEntry(kind="system", text=error))
        if self.scene_key() != self._suggested_for:
            state.suggestion, state.suggestion_id = "", ""
        self._update_profile(pending.events)
        if state.over:
            state.epitaph = await extras.epitaph(self.llm, state)
            state.log.append(LogEntry(kind="system", text=f"Epitaph: {state.epitaph}"))
            record_end(self.profile, state)
        self._save()
        return TurnResult(text, pending.events, pending.intent, errors)

    async def act(self, raw: str, on_text: Callable[[str], None],
                  on_resolved: Callable[[list[Event]], None] | None = None, action: Action | None = None) -> TurnResult:
        """One whole turn with no rerolls (plain mode, tests)."""
        pending = await self.begin(raw, action)
        if on_resolved:
            on_resolved(pending.events)
        return await self.finish(on_text)

    # --- extras ---

    async def refresh_suggestion(self) -> str:
        """Ask for a fresh suggested trick when the scene changes (scene_key). Cheap to call every turn. It's one of
        the interaction grid's uses that would do something here (extras.ideas), or none."""
        key = self.scene_key()
        if self.state.over or key == self._suggested_for:
            return self.state.suggestion
        self._suggested_for = key
        idea = await extras.suggestion(self.llm, self.state, self.content)
        self.state.suggestion, self.state.suggestion_id = (idea.label, idea.id) if idea else ("", "")
        return self.state.suggestion

    async def recap(self, stand_in: bool = True) -> str:
        return await extras.recap(self.llm, self.state, stand_in)

    def _record_story(self, events: list[Event]) -> None:
        """Log story cards and their effects, and save what the profile should remember (nothing, in a test room)."""
        state, profile = self.state, self.profile
        test = bool(state.test_room)
        for event in events:
            if event.kind == "story" and event.data.get("voice") == "exact":  # (a character's words: npcs.say)
                state.log.append(LogEntry(kind="card", text=event.text, title=event.data.get("title", ""),
                                          art=event.data.get("sprite", ""), speaker=event.data.get("speaker", "")))
            elif event.kind == "story_effect" and event.text:
                state.log.append(LogEntry(kind="mechanic", text=f"◆ {event.text}"))
            elif event.kind == "story_secret":
                if test or profile.add_secret(event.data["event"], state.run_id):
                    state.log.append(LogEntry(kind="system", text=f"✧ {event.text}"))
                else:
                    event.data["repeat"] = True  # already in the Book of Secrets
            elif event.kind == "story_seen" and not test:
                profile.mark_seen(event.data["event"])
            elif event.kind == "story_mark" and not test:
                profile.set_mark(event.data["mark"])
            if event.kind in ("story", "story_effect") and event.text:  # (a character's words, with who said them)
                said = f"{event.data['title']}: {event.text}" if event.data.get("speaker") else event.text
                state.journal.append(said)
        state.journal = state.journal[-200:]
        state.marks_pending.clear()
        self.story.view = ProfileView.from_profile(profile)

    def _update_profile(self, events: list[Event]) -> None:
        profile, state = self.profile, self.state
        if state.test_room:  # (a test room's run counts for nothing: not even in the bestiary)
            return
        for event in events:
            monster = event.data.get("monster")
            if event.kind in ("enter", "ambush", "descend", "story_effect") and monster:
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
