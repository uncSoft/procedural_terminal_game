"""The story engine: watches each turn for the moments the story files describe, and plays them out.

Like the rules, it only changes GameState, so a Fate reroll rewinds it cleanly. Anything that has to
outlive the run (events seen, marks, secrets) goes out as events, and Game commits them to the profile
once the turn is final.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .. import dice
from ..content import Content
from ..events import Action, Event
from ..models import GameState, MonsterState, SceneState
from ..rules import apply_perk, check_level, gain_item
from ..text import a, cap
from .model import Effect, Node, StoryEvent
from .parser import Library, normalize

# Kinds of event the story engine produces. Game shows cards, records the rest, and keeps them all away
# from the narrator (except cards written in the "narrated" voice).
STORY_KINDS = {"story", "story_effect", "story_secret", "story_seen", "story_mark"}
MAX_GOTO_DEPTH = 8


@dataclass
class ProfileView:
    """What the profile remembers, as the engine needs it. Refreshed by Game after each turn."""

    seen: set[str] = field(default_factory=set)
    marks: set[str] = field(default_factory=set)
    secrets: set[str] = field(default_factory=set)
    runs: int = 0
    deaths: int = 0
    wins: int = 0

    @classmethod
    def from_profile(cls, profile) -> ProfileView:
        totals = profile.totals()
        return cls(profile.story_seen(), profile.marks(), set(profile.secrets()),
                   totals["runs"], totals["runs"] - totals["wins"], totals["wins"])


class StoryEngine:
    def __init__(self, library: Library, content: Content, view: ProfileView | None = None):
        self.library = library
        self.content = content
        self.view = view or ProfileView()
        self.tampered = False  # have the game's own data files been edited? (see ptg.integrity)

    # --- triggers ---------------------------------------------------------------

    def wants_say(self, state: GameState, raw: str) -> bool:
        """Would this typed text set off a story event? (Checked before the interpreter sees it.)"""
        return self._say_event(state, raw) is not None

    def on_say(self, state: GameState, raw: str) -> list[Event]:
        event = self._say_event(state, raw)
        return self._fire(state, event) if event else []

    def on_run_start(self, state: GameState) -> list[Event]:
        return self._trigger(state, "run_start", {})

    def after_turn(self, state: GameState, events: list[Event]) -> list[Event]:
        """Look at what just happened and fire any story events it sets off."""
        if state.over or state.scene:
            return []
        out: list[Event] = []
        for event in list(events):
            if event.kind in ("enter", "descend"):
                out += self._trigger(state, "enter_room", {"first": bool(event.data.get("first"))})
            elif event.kind in ("defeat", "pacify") and event.data.get("monster"):
                out += self._trigger(state, event.kind, {"monster": event.data["monster"]})
            elif event.dice and event.dice.actor == "player" and (event.dice.crit or event.dice.fumble):
                out += self._trigger(state, "roll", {"roll": "nat20" if event.dice.crit else "nat1"})
            if state.scene or state.over:
                return out
        return out + self._trigger(state, "turn", {})

    def force(self, state: GameState, event_id: str) -> list[Event]:
        """Fire an event now, ignoring its trigger and conditions (for testing story files)."""
        event = self.library.get(event_id)
        if event is None:
            raise KeyError(f"no story event called {event_id!r}")
        return self._fire(state, event)

    def _say_event(self, state: GameState, raw: str) -> StoryEvent | None:
        if state.scene or state.over:
            return None
        text = f" {normalize(raw)} "
        for event in self.library:
            if event.trigger == "say" and any(f" {p} " in text for p in event.trigger_args) \
                    and self._eligible(state, event, {}):
                return event
        return None

    def _trigger(self, state: GameState, trigger: str, context: dict) -> list[Event]:
        out: list[Event] = []
        for event in self.library:
            if event.trigger != trigger:
                continue
            if trigger == "roll" and event.trigger_args[0] != context.get("roll"):
                continue
            if event.is_scene and (state.scene or state.in_combat):
                continue
            if self._eligible(state, event, context):
                out += self._fire(state, event)
                if state.scene or state.over:
                    break
        return out

    # --- conditions -------------------------------------------------------------

    def _eligible(self, state: GameState, event: StoryEvent, context: dict) -> bool:
        if event.once != "always" and event.id in state.story_seen:
            return False
        if event.once == "profile" and event.id in self.view.seen:
            return False
        return all(self._check(state, event, c, context) for c in event.conditions)

    def _check(self, state: GameState, event: StoryEvent, condition, context: dict) -> bool:
        return self._predicate(state, event, condition, context) != condition.negate

    def _predicate(self, state: GameState, event: StoryEvent, condition, context: dict) -> bool:
        name, value = condition.name, condition.value
        player, room = state.player, state.room
        if condition.op:
            actual = {"floor": state.floor, "level": player.level, "hp": player.hp, "gold": player.gold,
                      "fate": player.fate, "souls": state.souls, "turn": state.turn, "runs": self.view.runs,
                      "deaths": self.view.deaths, "wins": self.view.wins}[name]
            target = int(value)
            return {">=": actual >= target, "<=": actual <= target, ">": actual > target, "<": actual < target,
                    "==": actual == target, "=": actual == target}[condition.op]
        if name == "chance":
            rng = dice.stream(state.seed, "story", event.id, state.floor, state.room_id, state.turn)
            return rng.random() * 100 < int(value)
        if name == "theme":
            return state.theme == value
        if name == "room":
            return room.archetype == value
        if name == "fixture":
            return room.fixture == value
        if name == "has":
            return value in player.inventory or value in (player.weapon, player.armor)
        if name == "flag":
            return value in state.flags
        if name == "mark":
            return value in self.view.marks or value in state.marks_pending
        if name == "seen":
            target = value or event.id
            return target in self.view.seen or target in state.story_seen
        if name == "monster":
            here = context.get("monster") or (room.monster.key if room.monster else "")
            return here == value
        if name == "in_combat":
            return state.in_combat
        if name == "first_visit":
            return bool(context.get("first"))
        if name == "tampered":
            return self.tampered
        raise ValueError(f"unknown condition {name!r}")

    # --- scenes -----------------------------------------------------------------

    def current(self, state: GameState) -> tuple[StoryEvent | None, Node | None]:
        if not state.scene:
            return None, None
        event = self.library.get(state.scene.event)
        if event is None or state.scene.node not in event.nodes:
            state.scene = None  # the story file changed under an old save
            return None, None
        return event, event.nodes[state.scene.node]

    def scene_actions(self, state: GameState) -> list[Action]:
        _, node = self.current(state)
        return [Action(f"scene:{i}", choice.label) for i, choice in enumerate(node.options)] if node else []

    def scene_title(self, state: GameState) -> str:
        event, _ = self.current(state)
        return event.title if event else ""

    def match(self, state: GameState, raw: str) -> int | None:
        """Match typed text against the authored keywords (and labels) of the current choices."""
        _, node = self.current(state)
        if node is None:
            return None
        text = f" {normalize(raw)} "
        best, best_length = None, 0
        for index, choice in enumerate(node.options):
            for phrase in [*choice.keywords, normalize(choice.label)]:
                if phrase and f" {phrase} " in text and len(phrase) > best_length:
                    best, best_length = index, len(phrase)
        return best

    def choose(self, state: GameState, index: int | None) -> list[Event]:
        """Play out a choice in the current scene (None means the catch-all)."""
        event, node = self.current(state)
        if node is None:
            return [Event("info", "There's nothing to choose right now.")]
        choice = node.fallback if index is None else (node.options[index] if 0 <= index < len(node.options) else None)
        if choice is None:
            return [Event("info", "Nothing comes of that.")]
        out: list[Event] = []
        if choice.text and event.voice != "silent":
            out.append(self._card(event, choice.text))
        state.scene = None
        effects, goto, end = self._apply(state, event, choice.effects)
        out += effects
        if goto and not end and not state.over and not state.in_combat:
            out += self._enter(state, event, goto)
        state.turn += 1
        return out

    # --- firing and effects -------------------------------------------------------

    def _fire(self, state: GameState, event: StoryEvent) -> list[Event]:
        state.story_seen.append(event.id)
        events = self._enter(state, event, "start")
        first_card = next((e for e in events if e.kind == "story"), None)
        if first_card is not None and event.sprite:
            first_card.data["sprite"] = event.sprite
        return [Event("story_seen", "", data={"event": event.id})] + events

    def _enter(self, state: GameState, event: StoryEvent, node_id: str, depth: int = 0) -> list[Event]:
        node = event.nodes[node_id]
        out: list[Event] = []
        if node.text and event.voice != "silent":
            out.append(self._card(event, node.text))
        effects, goto, end = self._apply(state, event, node.effects)
        out += effects
        if goto and not end and depth < MAX_GOTO_DEPTH and not state.over:
            return out + self._enter(state, event, goto, depth + 1)
        if node.choices and not end and not state.in_combat and not state.over:
            state.scene = SceneState(event=event.id, node=node_id)
        elif state.scene and state.scene.event == event.id:
            state.scene = None
        return out

    def _card(self, event: StoryEvent, text: str) -> Event:
        return Event("story", text, data={"event": event.id, "title": event.title, "voice": event.voice})

    def _apply(self, state: GameState, event: StoryEvent, effects: list[Effect]) -> tuple[list[Event], str, bool]:
        player, content = state.player, self.content
        out: list[Event] = []
        notes: list[str] = []
        goto, end, leveled = "", False, False
        for effect in effects:
            verb, args = effect.verb, effect.args
            amount = int(args[0]) if verb in ("hp", "gold", "souls", "fate", "xp") else 0
            if verb == "hp":
                before = player.hp
                player.hp = max(1, min(player.max_hp, player.hp + amount))  # story damage never kills
                notes.append(f"{player.hp - before:+d} HP")
            elif verb == "heal":
                notes.append(f"+{player.max_hp - player.hp} HP")
                player.hp = player.max_hp
            elif verb == "gold":
                player.gold = max(0, player.gold + amount)
                notes.append(f"{amount:+d} gold")
            elif verb == "souls":
                state.souls = max(0, state.souls + amount)
                notes.append(f"{amount:+d} souls")
            elif verb == "fate":
                before = player.fate
                player.fate = max(0, min(player.max_fate(), player.fate + amount))
                notes.append(f"{player.fate - before:+d} Fate")
            elif verb == "xp":
                player.xp += amount
                notes.append(f"+{amount} XP")
                leveled = True
            elif verb == "give":
                notes += [e.text for e in gain_item(state, content, args[0])]
            elif verb == "take":
                if args[0] in player.inventory:
                    player.inventory.remove(args[0])
                    notes.append(f"lost the {content.item(args[0]).name}")
            elif verb == "perk":
                if apply_perk(state, content, args[0]):
                    notes.append(f"perk: {content.perks[args[0]].name}")
            elif verb == "flag":
                if args[0] not in state.flags:
                    state.flags.append(args[0])
            elif verb == "unflag":
                if args[0] in state.flags:
                    state.flags.remove(args[0])
            elif verb == "mark":
                state.marks_pending.append(args[0])
                out.append(Event("story_mark", "", data={"mark": args[0]}))
            elif verb == "secret":
                target = self.library.get(args[0]) if args else event
                out.append(Event("story_secret", f"Secret found: {target.title}",
                                 data={"event": target.id, "title": target.title}))
            elif verb == "spawn":
                monster_def = content.monster(args[0])
                state.room.monster = MonsterState(key=monster_def.key, name=monster_def.name,
                                                  hp=monster_def.hp, max_hp=monster_def.hp)
                notes.append(f"{cap(a(monster_def.name))} appears!")
                out.append(Event("story_effect", "", data={"monster": monster_def.key}))
            elif verb == "goto":
                goto = args[0]
            elif verb == "end":
                end = True
        if leveled:
            notes += [e.text for e in check_level(state, content)]
        notes = [n for n in notes if not n.startswith(("+0 ", "-0 "))]  # e.g. a heal at full health
        if notes:
            out.insert(0, Event("story_effect", " · ".join(notes), data={"event": event.id}))
        return out, goto, end
