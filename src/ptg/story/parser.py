"""Reads story files (Markdown with a small header) into StoryEvents, and checks them against the game's
content so a typo fails loudly with a file and line number instead of silently doing nothing.

    ---
    id: mirror_trial
    title: The Mirror Trial
    when: enter_room
    if: floor >= 2; not in_combat; chance 25%
    once: profile
    voice: exact
    secret: yes
    hint: Not every fight is won by fighting.
    ---
    Opening text...

    * Attack your reflection (attack, fight, strike)
      -> What happens. [hp -6]
    * (anything else)
      -> What happens otherwise.

    ## another_part
    More text, more choices...

See docs/writing-events.md for the full reference.
"""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path

from .. import sprites
from ..content import Content
from .model import ONCE, TRIGGERS, VOICES, Choice, Condition, Effect, Node, StoryError, StoryEvent

HEADER_KEYS = {"id", "title", "when", "if", "once", "voice", "secret", "hint", "sprite"}
EFFECT = re.compile(r"\[([a-z_]+)((?:\s+[^\]\s]+)*)\s*\]")
NAME = re.compile(r"^[a-z0-9_]+$")
NUMERIC = re.compile(r"^(floor|level|hp|gold|fate|souls|turn|runs|deaths|wins)\s*(>=|<=|==|=|>|<)\s*(-?\d+)$")
WITH_ARG = {"theme", "room", "fixture", "has", "flag", "mark", "seen", "monster"}
BARE = {"in_combat", "first_visit", "seen", "tampered"}

# verb -> (min args, max args, kind of argument)
EFFECTS = {
    "hp": (1, 1, "number"), "gold": (1, 1, "number"), "souls": (1, 1, "number"), "fate": (1, 1, "number"),
    "xp": (1, 1, "number"), "heal": (0, 0, ""), "give": (1, 1, "item"), "take": (1, 1, "item"),
    "perk": (1, 1, "perk"), "flag": (1, 1, "name"), "unflag": (1, 1, "name"), "mark": (1, 1, "name"),
    "secret": (0, 1, "event"), "spawn": (1, 1, "monster"), "goto": (1, 1, "node"), "end": (0, 0, ""),
}


def parse(text: str, source: str = "<story>") -> StoryEvent:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise StoryError(f"{source}:1: a story file starts with a '---' header")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise StoryError(f"{source}: the header is never closed with '---'") from None

    header: dict[str, tuple[str, int]] = {}
    for number, line in enumerate(lines[1:end], start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        key = key.strip().lower()
        if not sep or key not in HEADER_KEYS:
            raise StoryError(f"{source}:{number}: unknown header line {line.strip()!r} "
                             f"(expected one of: {', '.join(sorted(HEADER_KEYS))})")
        header[key] = (value.strip().strip('"'), number)

    if "id" not in header or "when" not in header:
        raise StoryError(f"{source}: the header needs at least 'id' and 'when'")
    event_id = header["id"][0]
    trigger, trigger_args = _trigger(header["when"][0], source, header["when"][1])
    conditions = _conditions(header.get("if", ("", 0))[0], source, header.get("if", ("", 0))[1])
    once = header.get("once", ("run", 0))[0]
    voice = header.get("voice", ("exact", 0))[0]
    nodes = _body(lines[end + 1:], end + 2, source)
    return StoryEvent(
        id=event_id, title=header.get("title", (event_id.replace("_", " ").title(), 0))[0],
        trigger=trigger, trigger_args=trigger_args, conditions=conditions, once=once, voice=voice,
        secret=header.get("secret", ("no", 0))[0].lower() in ("yes", "true", "1"),
        hint=header.get("hint", ("", 0))[0], nodes=nodes, source=source,
        sprite=header.get("sprite", ("", 0))[0],
    )


def _trigger(value: str, source: str, line: int) -> tuple[str, list[str]]:
    name, _, rest = value.strip().partition(" ")
    if name not in TRIGGERS:
        raise StoryError(f"{source}:{line}: unknown trigger {name!r} (expected one of: {', '.join(TRIGGERS)})")
    if name == "say":
        phrases = [normalize(p) for p in rest.split("|") if normalize(p)]
        if not phrases:
            raise StoryError(f"{source}:{line}: 'say' needs at least one phrase, e.g. 'when: say open sesame'")
        return name, phrases
    if name == "roll":
        if rest.strip() not in ("nat20", "nat1"):
            raise StoryError(f"{source}:{line}: 'roll' takes nat20 or nat1")
        return name, [rest.strip()]
    if rest.strip():
        raise StoryError(f"{source}:{line}: {name!r} doesn't take anything after it (use 'if:' for conditions)")
    return name, []


def _conditions(value: str, source: str, line: int) -> list[Condition]:
    conditions = []
    for part in [p.strip() for p in value.split(";") if p.strip()]:
        negate = part.startswith("not ")
        body = part[4:].strip() if negate else part
        numeric = NUMERIC.match(body)
        chance = re.match(r"^chance\s+(\d+)%$", body)
        if numeric:
            conditions.append(Condition(numeric.group(1), negate, numeric.group(2), numeric.group(3), line))
        elif chance:
            conditions.append(Condition("chance", negate, "", chance.group(1), line))
        else:
            name, _, arg = body.partition(" ")
            if name in WITH_ARG and arg.strip():
                conditions.append(Condition(name, negate, "", arg.strip(), line))
            elif name in BARE and not arg.strip():
                conditions.append(Condition(name, negate, "", "", line))
            else:
                raise StoryError(f"{source}:{line}: can't read the condition {part!r}")
    return conditions


def _effects(text: str, source: str, line: int) -> tuple[str, list[Effect]]:
    effects = [Effect(m.group(1), m.group(2).split(), line) for m in EFFECT.finditer(text)]
    for effect in effects:
        if effect.verb not in EFFECTS:
            raise StoryError(f"{source}:{line}: unknown effect [{effect.verb}] "
                             f"(expected one of: {', '.join(EFFECTS)})")
    clean = EFFECT.sub("", text)
    clean = re.sub(r"[ \t]+", " ", clean)
    clean = re.sub(r" +([.,!?;:])", r"\1", clean)
    return clean.strip(), effects


def _body(lines: list[str], first_line: int, source: str) -> dict[str, Node]:
    nodes: dict[str, Node] = {}
    node = Node("start", line=first_line)
    nodes["start"] = node
    paragraphs: list[str] = []
    choice: Choice | None = None
    outcome: list[str] = []
    outcome_line = 0

    def close_choice() -> None:
        nonlocal choice, outcome
        if choice is not None:
            choice.text, choice.effects = _effects(" ".join(outcome), source, outcome_line or choice.line)
        choice, outcome = None, []

    def close_node() -> None:
        close_choice()
        # Paragraph breaks survive: _effects only collapses spaces and tabs.
        node.text, node.effects = _effects("\n\n".join(p.strip() for p in paragraphs if p.strip()), source, node.line)

    for number, raw in enumerate(lines, start=first_line):
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("## "):
            close_node()
            node_id = stripped[3:].strip().lower().replace(" ", "_")
            if not NAME.match(node_id):
                raise StoryError(f"{source}:{number}: part names use letters, numbers and _ only: {node_id!r}")
            if node_id in nodes:
                raise StoryError(f"{source}:{number}: there's already a part called {node_id!r}")
            node = Node(node_id, line=number)
            nodes[node_id] = node
            paragraphs = []
            continue
        if stripped.startswith("* "):
            close_choice()
            choice = _choice(stripped[2:].strip(), source, number)
            node.choices.append(choice)
            continue
        if stripped.startswith("->"):
            if choice is None:
                raise StoryError(f"{source}:{number}: '->' needs a '* choice' line above it")
            outcome = [stripped[2:].strip()]
            outcome_line = number
            continue
        if choice is not None:
            if stripped and raw[:1] in (" ", "\t") and outcome:
                outcome.append(stripped)  # an indented continuation of the outcome
                continue
            if stripped:
                raise StoryError(f"{source}:{number}: text after the choices needs a new '## part' heading, "
                                 "or indent it to continue the outcome above")
            continue
        if not stripped:
            paragraphs.append("")
        elif paragraphs and paragraphs[-1]:
            paragraphs[-1] += " " + stripped
        else:
            paragraphs.append(stripped)
    close_node()
    return nodes


def _choice(text: str, source: str, line: int) -> Choice:
    if text.lower() in ("(anything else)", "(otherwise)"):
        return Choice("", [], fallback=True, line=line)
    match = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", text)
    label, keywords = (match.group(1), match.group(2)) if match else (text, "")
    if not label:
        raise StoryError(f"{source}:{line}: a choice needs some words before its keywords")
    return Choice(label, [normalize(k) for k in keywords.split(",") if normalize(k)], line=line)


def normalize(text: str) -> str:
    text = re.sub(r"[^a-z0-9' ]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def validate(event: StoryEvent, content: Content, event_ids: set[str]) -> list[str]:
    problems = []
    where = event.source
    if not NAME.match(event.id):
        problems.append(f"{where}: id {event.id!r} should use lowercase letters, numbers and _")
    if event.once not in ONCE:
        problems.append(f"{where}: once must be one of {', '.join(ONCE)}")
    if event.voice not in VOICES:
        problems.append(f"{where}: voice must be one of {', '.join(VOICES)}")
    if event.sprite and sprites.Image is not None and not sprites.frame_count(event.sprite):
        problems.append(f"{where}: no sprite called {event.sprite!r} in data/sprites")
    for condition in event.conditions:
        if condition.name == "chance" and not 0 <= int(condition.value) <= 100:
            problems.append(f"{where}:{condition.line}: chance must be 0-100%")
        lookups = {"theme": content.themes, "room": content.archetypes, "has": content.items,
                   "monster": content.monsters, "seen": event_ids}
        if condition.name in lookups and condition.value and condition.value not in lookups[condition.name]:
            problems.append(f"{where}:{condition.line}: unknown {condition.name} {condition.value!r}")
        if condition.name == "fixture" and condition.value not in ("shrine", "chest", "fountain", "stairs"):
            problems.append(f"{where}:{condition.line}: unknown fixture {condition.value!r}")
    for node in event.nodes.values():
        effect_lists = [node.effects] + [c.effects for c in node.choices]
        for effects in effect_lists:
            for effect in effects:
                problems += _check_effect(effect, event, content, event_ids)
    return problems


def _check_effect(effect: Effect, event: StoryEvent, content: Content, event_ids: set[str]) -> list[str]:
    where = f"{event.source}:{effect.line}"
    low, high, kind = EFFECTS[effect.verb]
    if not low <= len(effect.args) <= high:
        return [f"{where}: [{effect.verb}] takes {low if low == high else f'{low}-{high}'} argument(s)"]
    if not effect.args:
        return []
    arg = effect.args[0]
    checks = {
        "number": (re.fullmatch(r"[+-]?\d+", arg), "a number like 5, +5 or -5"),
        "item": (arg in content.items, "an item key from items.toml"),
        "perk": (arg in content.perks, "a perk key from perks.toml"),
        "monster": (arg in content.monsters, "a monster key from monsters.toml"),
        "name": (NAME.match(arg), "a name made of lowercase letters, numbers and _"),
        "event": (arg in event_ids, "the id of a story event"),
        "node": (arg in event.nodes, f"the name of a part in this file ({', '.join(event.nodes)})"),
    }
    ok, expected = checks[kind]
    return [] if ok else [f"{where}: [{effect.verb} {arg}] needs {expected}"]


class Library:
    """Every story event in the game, in a stable order."""

    def __init__(self, events: list[StoryEvent]):
        self.events = {e.id: e for e in events}

    def __iter__(self):
        return iter(self.events.values())

    def get(self, event_id: str) -> StoryEvent | None:
        return self.events.get(event_id)

    @property
    def secrets(self) -> list[StoryEvent]:
        return [e for e in self.events.values() if e.secret]


def load_files(paths: list[tuple[str, str]], content: Content) -> Library:
    """Parse and validate (name, text) pairs; raises StoryError listing every problem found."""
    events, problems = [], []
    for name, text in paths:
        try:
            events.append(parse(text, name))
        except StoryError as e:
            problems.append(str(e))
    ids = [e.id for e in events]
    for duplicate in sorted({i for i in ids if ids.count(i) > 1}):
        problems.append(f"two story files use the id {duplicate!r}")
    for event in events:
        problems += validate(event, content, set(ids))
    if problems:
        raise StoryError("Problems in the story files:\n  " + "\n  ".join(problems))
    return Library(events)


_LIBRARY: Library | None = None


def load_library(content: Content) -> Library:
    """The story events shipped in ptg/data/story (loaded once)."""
    global _LIBRARY
    if _LIBRARY is None:
        folder = resources.files("ptg") / "data" / "story"
        files = sorted((p for p in folder.iterdir() if p.name.endswith(".md")), key=lambda p: p.name)
        _LIBRARY = load_files([(f"story/{p.name}", p.read_text(encoding="utf-8")) for p in files], content)
    return _LIBRARY


def load_folder(folder: Path, content: Content) -> Library:
    files = sorted(folder.glob("*.md"))
    return load_files([(str(p), p.read_text(encoding="utf-8")) for p in files], content)
