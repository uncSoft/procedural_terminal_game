"""Loads the static game data (themes, rooms, items, monsters, perks, unlocks, art) shipped in ptg/data."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from typing import Literal


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


def _read(name: str) -> str:
    return (resources.files("ptg") / "data" / name).read_text(encoding="utf-8")


def _parse_art(text: str) -> dict[str, str]:
    art: dict[str, str] = {}
    for match in re.finditer(r"^=== (\w+) ===\n(.*?)(?=^=== |\Z)", text, re.M | re.S):
        art[match.group(1)] = match.group(2).rstrip("\n")
    return art


@lru_cache(maxsize=1)
def load_content() -> Content:
    themes = {t["key"]: Theme(**t) for t in tomllib.loads(_read("themes.toml"))["theme"]}
    archetypes = {
        key: Archetype(key=key, **data)
        for key, data in tomllib.loads(_read("rooms.toml"))["archetype"].items()
    }
    items = {key: ItemDef(key=key, **data) for key, data in tomllib.loads(_read("items.toml"))["item"].items()}
    art = _parse_art(_read("art.txt"))
    monsters = {
        key: MonsterDef(key=key, art=art.get(key, ""), **data)
        for key, data in tomllib.loads(_read("monsters.toml"))["monster"].items()
    }
    perks = {key: Perk(key=key, **data) for key, data in tomllib.loads(_read("perks.toml"))["perk"].items()}
    unlock_data = tomllib.loads(_read("unlocks.toml"))
    unlocks = {
        key: Unlock(key=key, kind=kind, **data)
        for kind in ("blessing", "gift")
        for key, data in unlock_data[kind].items()
    }
    keyword_tags = tomllib.loads(_read("tags.toml"))["keywords"]
    content = Content(themes, archetypes, items, monsters, perks, unlocks, keyword_tags, _read("splash.txt"))
    _validate(content)
    return content


def _validate(content: Content) -> None:
    """Fail loudly on broken data instead of silently playing without it (the v1 monsters.json bug)."""
    problems = []
    for theme in content.themes.values():
        for key in [*theme.archetypes, theme.boss_room]:
            if key not in content.archetypes:
                problems.append(f"theme {theme.key}: unknown archetype {key!r}")
        if theme.boss not in content.monsters:
            problems.append(f"theme {theme.key}: unknown boss {theme.boss!r}")
        if theme.key_item not in content.items:
            problems.append(f"theme {theme.key}: unknown key item {theme.key_item!r}")
        pool = [m for m in content.monsters.values() if not (m.boss or m.ghost)]
        for tier in (1, 2, 3):
            if not any(set(m.tags) & set(theme.monster_tags) and m.tier == tier for m in pool):
                problems.append(f"theme {theme.key}: no tier {tier} monsters match its tags")
    for monster in content.monsters.values():
        if not monster.art:
            problems.append(f"monster {monster.key}: missing art")
    for unlock in content.unlocks.values():
        if unlock.item and unlock.item not in content.items:
            problems.append(f"unlock {unlock.key}: unknown item {unlock.item!r}")
        if unlock.requires and unlock.requires not in content.unlocks:
            problems.append(f"unlock {unlock.key}: unknown requirement {unlock.requires!r}")
    if problems:
        raise ValueError("Invalid game content:\n  " + "\n  ".join(problems))
