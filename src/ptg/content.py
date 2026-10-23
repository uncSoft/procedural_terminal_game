"""Loads the static game data (themes, rooms, items, monsters, perks, unlocks, art) shipped in ptg/data."""

from __future__ import annotations

import difflib
import re
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Callable, Literal

from .powers import POWERS

# Where an item with `found` may turn up (see loot.py): a chest, a hidden stash, a floor's secret room, or the warden
# by the stairs (or any elite). An item can also name the monster that drops it.
FOUND_IN = ("chest", "stash", "secret", "warden")


@dataclass(frozen=True)
class Theme:
    key: str
    name: str
    blurb: str
    goal: str
    archetypes: list[str]
    monster_tags: list[str]
    boss: str
    boss_room: str
    key_item: str


@dataclass(frozen=True)
class Archetype:
    key: str
    names: list[str]
    blurb: str
    features: list[str]
    decor: str = ""


@dataclass(frozen=True)
class ItemDef:
    key: str
    name: str
    kind: Literal["weapon", "armor", "consumable", "key", "trinket"]
    damage: str = ""
    defense: int = 0
    heal: int = 0
    escape: bool = False
    tier: int = 0
    tags: list[str] = field(default_factory=list)
    desc: str = ""
    powers: list[str] = field(default_factory=list)  # what it does beyond its numbers (see powers.py)
    found: list[str] = field(default_factory=list)  # the only places it turns up, if it's that rare (see loot.py)


@dataclass(frozen=True)
class MonsterDef:
    key: str
    name: str
    hp: int
    defense: int
    attack: int
    damage: str
    xp: int
    tier: int
    tags: list[str] = field(default_factory=list)
    intelligent: bool = False
    boss: bool = False
    ghost: bool = False
    weak: list[str] = field(default_factory=list)
    tell: str = "winds up a powerful attack"
    desc: str = ""  # what it looks like and how it behaves, in its creator's words (the narrator gets it too)
    art: str = ""


@dataclass(frozen=True)
class Perk:
    key: str
    name: str
    desc: str
    color: str = "white"


@dataclass(frozen=True)
class Unlock:
    key: str
    kind: Literal["blessing", "gift"]
    name: str
    icon: str
    cost: int
    desc: str
    item: str = ""
    requires: str = ""


@dataclass(frozen=True)
class Content:
    themes: dict[str, Theme]
    archetypes: dict[str, Archetype]
    items: dict[str, ItemDef]
    monsters: dict[str, MonsterDef]
    perks: dict[str, Perk]
    unlocks: dict[str, Unlock]
    keyword_tags: dict[str, list[str]]
    splash: str

    def item(self, key: str) -> ItemDef:
        return self.items[key]

    def monster(self, key: str) -> MonsterDef:
        return self.monsters[key]

    def feature_tags(self, name: str) -> list[str]:
        """Tags for a room feature, from the words in its name ("a stew cauldron" -> heavy, fire, food)."""
        tags: list[str] = []
        for word in re.findall(r"[a-z]+", name.lower()):
            for tag in self.keyword_tags.get(word, []):
                if tag not in tags:
                    tags.append(tag)
        return tags


class ContentError(ValueError):
    """Broken game data. The message lists every problem found, file by file."""


def _read(name: str) -> str:
    return (resources.files("ptg") / "data" / name).read_text(encoding="utf-8")


def _parse_art(text: str) -> dict[str, str]:
    art: dict[str, str] = {}
    for match in re.finditer(r"^=== (\w+) ===\n(.*?)(?=^=== |\Z)", text, re.M | re.S):
        art[match.group(1)] = match.group(2).rstrip("\n")
    return art


# What each kind of entry may contain: field -> (kind of value, required?)
SCHEMAS: dict[str, dict[str, tuple[str, bool]]] = {
    "theme": {"key": ("name", True), "name": ("text", True), "blurb": ("text", True), "goal": ("text", True),
              "archetypes": ("names", True), "monster_tags": ("names", True), "boss": ("name", True),
              "boss_room": ("name", True), "key_item": ("name", True)},
    "archetype": {"names": ("texts", True), "blurb": ("text", True), "features": ("texts", True),
                  "decor": ("text", False)},
    "item": {"name": ("text", True), "kind": ("item_kind", True), "damage": ("dice", False),
             "defense": ("count", False), "heal": ("count", False), "escape": ("bool", False),
             "tier": ("count", False), "tags": ("names", False), "desc": ("text", False),
             "powers": ("powers", False), "found": ("names", False)},
    "monster": {"name": ("text", True), "hp": ("positive", True), "defense": ("count", True),
                "attack": ("int", True), "damage": ("dice", True), "xp": ("count", True), "tier": ("tier", True),
                "tags": ("names", False), "intelligent": ("bool", False), "boss": ("bool", False),
                "ghost": ("bool", False), "weak": ("names", False), "tell": ("text", False),
                "desc": ("text", False)},
    "perk": {"name": ("text", True), "desc": ("text", True), "color": ("color", False)},
    "unlock": {"name": ("text", True), "icon": ("text", True), "cost": ("count", True), "desc": ("text", True),
               "item": ("name", False), "requires": ("name", False)},
}
COLORS = ("red", "green", "cyan", "magenta", "yellow", "blue", "white")
_NAME = re.compile(r"^[a-z0-9_]+$")
_DICE = re.compile(r"^\s*\d+d\d+\s*([+-]\s*\d+)?\s*$")


def _value_error(kind: str, value: object) -> str:
    """Why a value doesn't fit its kind ("" if it does)."""
    is_int = isinstance(value, int) and not isinstance(value, bool)
    checks = {
        "text": (isinstance(value, str) and value.strip(), "must be some text in quotes"),
        "texts": (isinstance(value, list) and value and all(isinstance(v, str) and v.strip() for v in value),
                  'must be a list of text, like ["a", "b"]'),
        "name": (isinstance(value, str) and _NAME.match(value), "must be a key like hand_axe (lowercase, _)"),
        "names": (isinstance(value, list) and all(isinstance(v, str) and _NAME.match(v) for v in value),
                  'must be a list of keys, like ["fire", "holy"]'),
        "int": (is_int, "must be a whole number"),
        "count": (is_int and value >= 0, "must be a whole number, 0 or more"),
        "positive": (is_int and value > 0, "must be a whole number above 0"),
        "tier": (is_int and 1 <= value <= 4, "must be a tier from 1 to 4"),
        "bool": (isinstance(value, bool), "must be true or false"),
        "dice": (isinstance(value, str) and _DICE.match(value), "must be dice like 1d6 or 2d4+1"),
        "item_kind": (value in ("weapon", "armor", "consumable", "key", "trinket"),
                      "must be weapon, armor, consumable, key or trinket"),
        "color": (value in COLORS, f"must be one of {', '.join(COLORS)}"),
        "powers": (isinstance(value, list) and all(v in POWERS for v in value),
                   f"must be a list of powers the game knows: {', '.join(POWERS)}"),
    }
    ok, message = checks[kind]
    return "" if ok else message


def _fields(where: str, data: object, schema: dict[str, tuple[str, bool]], problems: list[str]) -> dict | None:
    """Check one entry against its schema. Returns the clean fields, or None if anything is wrong."""
    if not isinstance(data, dict):
        problems.append(f"{where}: expected a table of fields")
        return None
    before = len(problems)
    for key in data:
        if key not in schema:
            close = difflib.get_close_matches(key, list(schema), n=1)
            hint = f" (did you mean {close[0]!r}?)" if close else ""
            problems.append(f"{where}: unknown field {key!r}{hint}")
    for key, (kind, required) in schema.items():
        if key not in data:
            if required:
                problems.append(f"{where}: missing {key!r}")
            continue
        error = _value_error(kind, data[key])
        if error:
            problems.append(f"{where}: {key} {error} (got {data[key]!r})")
    return dict(data) if len(problems) == before else None


def _sections(name: str, doc: dict, expected: tuple[str, ...], problems: list[str]) -> None:
    for section in doc:
        if section not in expected:
            close = difflib.get_close_matches(section, list(expected), n=1)
            hint = f" (did you mean {close[0]!r}?)" if close else ""
            problems.append(f"{name}: unknown section [{section}]{hint}")


def build_content(read: Callable[[str], str] = _read) -> Content:
    """Load and check every data file. `read` returns a file's text by name (tests pass their own)."""
    problems: list[str] = []

    def toml(name: str, expected: tuple[str, ...]) -> dict:
        try:
            doc = tomllib.loads(read(name))
        except FileNotFoundError:
            problems.append(f"{name}: the file is missing")
            return {}
        except tomllib.TOMLDecodeError as e:
            problems.append(f"{name}: {e}")
            return {}
        _sections(name, doc, expected, problems)
        return doc

    def table(name: str, doc: dict, section: str, kind: str) -> dict[str, dict]:
        entries = doc.get(section, {})
        if not isinstance(entries, dict):
            problems.append(f"{name}: [{section}] should hold [{section}.some_key] tables")
            return {}
        clean = {}
        for key, data in entries.items():
            where = f"{name} [{section}.{key}]"
            if not _NAME.match(key):
                problems.append(f"{where}: keys use lowercase letters, numbers and _")
            fields = _fields(where, data, SCHEMAS[kind], problems)
            if fields is not None:
                clean[key] = fields
        return clean

    themes_doc = toml("themes.toml", ("theme",))
    themes = {}
    for i, data in enumerate(themes_doc.get("theme", [])):
        fields = _fields(f"themes.toml [[theme]] #{i + 1}", data, SCHEMAS["theme"], problems)
        if fields is not None:
            themes[fields["key"]] = Theme(**fields)

    archetypes = {k: Archetype(key=k, **v) for k, v in
                  table("rooms.toml", toml("rooms.toml", ("archetype",)), "archetype", "archetype").items()}
    items = {k: ItemDef(key=k, **v) for k, v in
             table("items.toml", toml("items.toml", ("item",)), "item", "item").items()}
    try:
        art = _parse_art(read("art.txt"))
    except FileNotFoundError:
        problems.append("art.txt: the file is missing")
        art = {}
    monsters = {k: MonsterDef(key=k, art=art.get(k, ""), **v) for k, v in
                table("monsters.toml", toml("monsters.toml", ("monster",)), "monster", "monster").items()}
    perks = {k: Perk(key=k, **v) for k, v in
             table("perks.toml", toml("perks.toml", ("perk",)), "perk", "perk").items()}
    unlock_doc = toml("unlocks.toml", ("blessing", "gift"))
    unlocks = {k: Unlock(key=k, kind=kind, **v) for kind in ("blessing", "gift")
               for k, v in table("unlocks.toml", unlock_doc, kind, "unlock").items()}

    keyword_tags = toml("tags.toml", ("keywords",)).get("keywords", {})
    for word, tags in keyword_tags.items():
        error = _value_error("names", tags)
        if error:
            problems.append(f"tags.toml [keywords] {word}: {error} (got {tags!r})")
    try:
        splash = read("splash.txt")
    except FileNotFoundError:
        problems.append("splash.txt: the file is missing")
        splash = ""

    content = Content(themes, archetypes, items, monsters, perks, unlocks, keyword_tags, splash)
    if not problems:  # cross-checks only make sense once every entry is well-formed
        problems += _cross_check(content)
    if problems:
        raise ContentError("Problems in the game data files:\n  " + "\n  ".join(problems))
    return content


@lru_cache(maxsize=1)
def load_content() -> Content:
    return build_content()


def _cross_check(content: Content) -> list[str]:
    """Fail loudly on broken data instead of silently playing without it (the v1 monsters.json bug)."""
    problems = []
    for theme in content.themes.values():
        for key in [*theme.archetypes, theme.boss_room]:
            if key not in content.archetypes:
                problems.append(f"themes.toml theme {theme.key}: unknown archetype {key!r}")
        if theme.boss not in content.monsters:
            problems.append(f"themes.toml theme {theme.key}: unknown boss {theme.boss!r}")
        if theme.key_item not in content.items:
            problems.append(f"themes.toml theme {theme.key}: unknown key item {theme.key_item!r}")
        pool = [m for m in content.monsters.values() if not (m.boss or m.ghost)]
        for tier in (1, 2, 3):
            if not any(set(m.tags) & set(theme.monster_tags) and m.tier == tier for m in pool):
                problems.append(f"themes.toml theme {theme.key}: no tier {tier} monsters match its tags")
    for item in content.items.values():
        if item.kind == "weapon" and not item.damage:
            problems.append(f"items.toml [item.{item.key}]: a weapon needs damage, like \"1d6\"")
        if item.kind == "armor" and item.defense <= 0:
            problems.append(f"items.toml [item.{item.key}]: armor needs defense above 0")
        if item.kind == "consumable" and not (item.heal or item.escape):
            problems.append(f"items.toml [item.{item.key}]: a consumable needs heal or escape = true")
        if "throw" in item.powers and not item.damage:
            problems.append(f"items.toml [item.{item.key}]: something to throw needs damage, like \"2d4\"")
        for place in item.found:
            if place not in FOUND_IN and place not in content.monsters:
                problems.append(f"items.toml [item.{item.key}]: found in {place!r}? It can be found in "
                                f"{', '.join(FOUND_IN)}, or name a monster that drops it")
    for monster in content.monsters.values():
        if not monster.art:
            problems.append(f"art.txt: monster {monster.key} has no art (add an '=== {monster.key} ===' block)")
    for unlock in content.unlocks.values():
        if unlock.item and unlock.item not in content.items:
            problems.append(f"unlocks.toml {unlock.key}: unknown item {unlock.item!r}")
        if unlock.requires and unlock.requires not in content.unlocks:
            problems.append(f"unlocks.toml {unlock.key}: unknown requirement {unlock.requires!r}")
    return problems
