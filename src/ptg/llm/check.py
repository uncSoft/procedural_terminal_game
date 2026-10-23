"""How well does a model play this game? A quick, fixed set of situations, scored.

    uv run python -m ptg.llm.check                                   # the model in your Settings
    uv run python -m ptg.llm.check --url http://localhost:11434/v1 --model llama3.2:3b

It asks the model to interpret ten typed commands (does it pick the action a player means? is its JSON valid?)
and to narrate five moments (a first visit, a return, a fight, a failed stunt, a question). Each narration goes
through the guard (guard.py), which reports what it would have cut and why. Then it says how fast it all was.
Nothing is saved: the dungeon is made up for the test, the same one every time.

A weaker model isn't unplayable: numbered choices never need the model, and the guard keeps the narration honest.
This shows how much of that safety net a model leans on.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import Iterator

from pydantic import ValidationError

from ..content import Content, load_content
from ..dice import Roll
from ..events import Event
from ..models import MonsterState
from ..rules import available_actions, perform
from ..world import generate
from .base import LLM, LLMError
from .guard import Rules, check, sentence_limit
from .interpreter import interpret
from .prompts import narrator_messages

SEED = 7
TONE = "darkly funny, vivid and fair"


@dataclass
class Report:
    model: str
    commands: list[tuple[str, str, str, float]] = field(default_factory=list)  # (typed, wanted, got, seconds)
    errors: list[str] = field(default_factory=list)
    scenes: list[tuple[str, int, list[tuple[str, str]], float]] = field(default_factory=list)  # (name, kept, cut, s)

    @property
    def right(self) -> int:
        return sum(1 for _, wanted, got, _ in self.commands if got == wanted)

    @property
    def cut(self) -> int:
        return sum(len(dropped) for _, _, dropped, _ in self.scenes)

    @property
    def sentences(self) -> int:
        return sum(kept + len(dropped) for _, kept, dropped, _ in self.scenes)

    def lines(self) -> list[str]:
        out = [f"Model: {self.model}", "", "Typed commands (does it pick what the player means?)"]
        for typed, wanted, got, seconds in self.commands:
            mark = "✔" if got == wanted else "✘"
            out.append(f"  {mark} {typed!r:<46} wanted {wanted:<18} got {got:<18} {seconds:4.1f}s")
        out += ["", "Narration (what the guard would cut)"]
        for name, kept, dropped, seconds in self.scenes:
            out.append(f"  {name:<14} {kept} sentence(s) kept, {len(dropped)} cut  {seconds:4.1f}s")
            out += [f"      cut ({why}): {sentence[:90]}" for sentence, why in dropped]
        out += [""] + [f"  error: {e}" for e in self.errors]
        out.append(self.verdict())
        return out

    def verdict(self) -> str:
        commands, scenes = len(self.commands) or 1, len(self.scenes) or 1
        speed = sum(s for *_, s in self.scenes) / scenes
        understanding = ("understands typed commands well" if self.right >= 0.8 * commands else
                         "often misreads typed commands (numbered choices always work)" if self.right >= 0.5 * commands
                         else "struggles with typed commands: stick to numbered choices, or try a bigger model")
        rate = self.cut / (self.sentences or 1)
        honesty = ("narrates faithfully" if rate < 0.05 else
                   "slips now and then (the guard catches it)" if rate < 0.2 else
                   "slips a lot: the guard cuts much of what it writes")
        return f"Verdict: it {understanding}, {honesty}, about {speed:.1f}s to narrate a turn."


def _situation(content: Content):
    """The made-up dungeon: an explorable room, a fight to start, and a pocket worth throwing."""
    state = generate(SEED)
    state.player.inventory += ["stale_bread"]
    return state


def _command_cases(state, content: Content) -> list[tuple[str, str, object]]:
    """(typed, what it should mean, a function that sets the scene) for each command."""
    exit_ = sorted(state.room.exits)[0]
    feature = next((i for i, f in state.room.visible_features()), None)

    def fight(s):
        s.room.monster = MonsterState(key="goblin", name="Goblin", hp=8, max_hp=8, intent="strike")

    def calm(s):
        s.room.monster = None

    cases = [
        (f"head {exit_} through the doorway", f"go:{exit_}", calm),
        ("what am I even carrying right now?", "question", calm),
        ("hum a little tune to myself", "flavor", calm),
        ("summon a dragon to carry me out of here", "creative", calm),
        ("stab the goblin", "attack", fight),
        ("throw my stale bread at its face", "creative", fight),
        ("get out of here, run!", "flee", fight),
        ("tell the goblin I'll pay it to leave me alone", "creative", fight),
        ("whistle at the goblin like it's a dog", "creative", fight),
    ]
    if feature is not None:
        name = state.room.features[feature].name
        cases.insert(1, (f"search the {name.removeprefix('a ').removeprefix('an ').removeprefix('the ')}",
                         f"search:{feature}", calm))
    return cases


async def _commands(llm: LLM, content: Content, report: Report) -> None:
    for typed, wanted, setup in _command_cases(_situation(content), content):
        state = _situation(content)
        setup(state)
        actions = available_actions(state, content)
        started = time.perf_counter()
        try:
            intent, error = await interpret(llm, state, content, typed, actions, trust_keywords=False)
        except (LLMError, ValidationError) as e:
            intent, error = None, str(e)
        if error:
            report.errors.append(f"{typed!r}: {error}")
        got = "error" if intent is None or error else (intent.action_id if intent.kind == "action" else intent.kind)
        report.commands.append((typed, wanted, got, time.perf_counter() - started))


def _scenes(content: Content) -> Iterator[tuple[str, object, str, list[Event], bool]]:
    """(name, state, what the player typed, the facts, is it a question) for each moment to narrate."""
    state = _situation(content)
    direction = sorted(state.room.exits)[0]
    first = perform(state, content, f"go:{direction}")
    yield "first visit", state, f"go {direction}", first, False
    back = next(d for d, e in state.room.exits.items() if e.to == state.prev_room_id)
    yield "a return", state, f"go {back}", perform(state, content, f"go:{back}"), False
    state.room.monster = MonsterState(key="goblin", name="Goblin", hp=30, max_hp=30, intent="strike")
    yield "a fight", state, "attack", perform(state, content, "attack"), False
    roll = Roll("agility", "player", [4], 4, [("agility", 1)], dc=13, success=False)
    stunt = [Event("check", "You attempt to swing from the rafters onto the goblin. It fails.", dice=roll)]
    yield "a failed stunt", state, "swing from the rafters onto the goblin", stunt, False
    yield "a question", state, "what's in this room?", [], True


async def _narration(llm: LLM, content: Content, report: Report) -> None:
    for name, state, typed, events, question in _scenes(content):
        system, user = narrator_messages(state, content, typed, events, TONE, question=question)
        rules = Rules.for_turn(state, content, events, question=question)
        started = time.perf_counter()
        parts: list[str] = []
        try:
            async for chunk in llm.stream_text(system, user, max_tokens=500):
                parts.append(chunk)
        except LLMError as e:
            report.errors.append(f"{name}: {e}")
        gate = check("".join(parts), rules, sentence_limit(rules.first_visit, state.in_combat))
        report.scenes.append((name, len(gate.kept), gate.dropped, time.perf_counter() - started))


async def run(llm: LLM, content: Content | None = None) -> Report:
    content = content or load_content()
    report = Report(getattr(llm, "name", "model"))
    await _commands(llm, content, report)
    await _narration(llm, content, report)
    return report


async def _main(args: argparse.Namespace) -> int:
    from ..config import Config, load_config
    from . import make_llm

    config = load_config() or Config()
    os.environ["PTG_HOME"] = tempfile.mkdtemp(prefix="ptg-check-")  # read your Settings, then write nothing there
    updates = {k: v for k, v in (("url", args.url), ("model", args.model), ("backend", args.backend)) if v}
    llm = make_llm(config.model_copy(update=updates))
    if llm is None:
        print("The narrator is set to Offline: there's no model to check. Pass --url (and --model).")
        return 1
    try:
        await llm.prepare()
        print(f"Checking {llm.name} (about a minute)...\n")
        report = await run(llm)
    except LLMError as e:
        print(f"Can't use the model: {e}")
        return 1
    finally:
        await llm.aclose()
    print("\n".join(report.lines()))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", help="OpenAI-compatible server URL (default: your Settings)")
    parser.add_argument("--model", help="model name (default: your Settings, or whatever is loaded)")
    parser.add_argument("--backend", choices=["openai", "anthropic"])
    sys.exit(asyncio.run(_main(parser.parse_args())))


if __name__ == "__main__":
    main()
