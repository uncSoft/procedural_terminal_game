"""How well does a model play this game? A quick, fixed set of situations, scored.

    uv run python -m ptg.llm.check                                   # the model in your Settings
    uv run python -m ptg.llm.check --url http://localhost:11434/v1 --model llama3.2:3b

It asks the model to interpret ten typed commands (does it pick the action a player means? is its JSON valid?)
and to narrate five moments (a first visit, a return, a fight, a failed stunt, a question). Each narration goes
through the guard (guard.py), which reports what it would have cut and why. Then it says how fast it all was.
Nothing is saved: the dungeon is made up for the test, the same one every time. (The debug screen, F12, runs the
same check inside the game, and keeps a line about each run in ~/.ptg/checks.jsonl so models can be compared.)

A weaker model isn't unplayable: numbered choices never need the model, and the guard keeps the narration honest.
This shows how much of that safety net a model leans on.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

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
SCENES = ("first visit", "a return", "a fight", "a failed stunt", "a question")


@dataclass
class Report:
    model: str
    planned: int = 0  # how many cases this check runs, for a progress bar
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

    @property
    def done(self) -> int:
        return len(self.commands) + len(self.scenes)

    @property
    def speed(self) -> float:
        """Seconds to narrate a turn, on average."""
        return sum(s for *_, s in self.scenes) / (len(self.scenes) or 1)

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
        commands = len(self.commands) or 1
        understanding = ("understands typed commands well" if self.right >= 0.8 * commands else
                         "often misreads typed commands (numbered choices always work)" if self.right >= 0.5 * commands
                         else "struggles with typed commands: stick to numbered choices, or try a bigger model")
        rate = self.cut / (self.sentences or 1)
        honesty = ("narrates faithfully" if rate < 0.05 else
                   "slips now and then (the guard catches it)" if rate < 0.2 else
                   "slips a lot: the guard cuts much of what it writes")
        return f"Verdict: it {understanding}, {honesty}, about {self.speed:.1f}s to narrate a turn."


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


Progress = Callable[[Report, str], None]  # called before each case with what's next ("" when it's all done)


def _quiet(report: Report, step: str) -> None:
    pass


async def _commands(llm: LLM, content: Content, report: Report, progress: Progress) -> None:
    for typed, wanted, setup in _command_cases(_situation(content), content):
        progress(report, f"reading {typed!r}")
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
    first_visit, a_return, a_fight, a_failed_stunt, a_question = SCENES
    state = _situation(content)
    direction = sorted(state.room.exits)[0]
    first = perform(state, content, f"go:{direction}")
    yield first_visit, state, f"go {direction}", first, False
    back = next(d for d, e in state.room.exits.items() if e.to == state.prev_room_id)
    yield a_return, state, f"go {back}", perform(state, content, f"go:{back}"), False
    state.room.monster = MonsterState(key="goblin", name="Goblin", hp=30, max_hp=30, intent="strike")
    yield a_fight, state, "attack", perform(state, content, "attack"), False
    roll = Roll("agility", "player", [4], 4, [("agility", 1)], dc=13, success=False)
    stunt = [Event("check", "You attempt to swing from the rafters onto the goblin. It fails.", dice=roll)]
    yield a_failed_stunt, state, "swing from the rafters onto the goblin", stunt, False
    yield a_question, state, "what's in this room?", [], True


async def _narration(llm: LLM, content: Content, report: Report, progress: Progress) -> None:
    for name, state, typed, events, question in _scenes(content):
        progress(report, f"narrating {name}")
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


async def run(llm: LLM, content: Content | None = None, progress: Progress = _quiet) -> Report:
    content = content or load_content()
    report = Report(getattr(llm, "name", "model"))
    report.planned = len(_command_cases(_situation(content), content)) + len(SCENES)
    await _commands(llm, content, report, progress)
    await _narration(llm, content, report, progress)
    progress(report, "")
    return report


# --- earlier checks (the debug screen keeps them, to compare models) -------------------------------------------

def history_path() -> Path:
    from ..config import home

    return home() / "checks.jsonl"


def save(report: Report) -> dict:
    """Add a finished check to ~/.ptg/checks.jsonl."""
    entry = {"when": datetime.now().isoformat(timespec="seconds"), "model": report.model, "right": report.right,
             "commands": len(report.commands), "cut": report.cut, "sentences": report.sentences,
             "speed": round(report.speed, 2), "errors": len(report.errors), "lines": report.lines()}
    with history_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def history(limit: int = 30) -> list[dict]:
    """Earlier checks, newest first."""
    try:
        lines = history_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    found = []
    for line in reversed(lines):
        try:
            found.append(json.loads(line))
        except ValueError:
            continue
        if len(found) >= limit:
            break
    return found


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
