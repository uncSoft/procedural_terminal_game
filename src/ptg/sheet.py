"""The character sheet's sums (ui/panels.py CharacterScreen): each stat with what it's made of, and every bonus to
every kind of roll with where it comes from. Pure, so tested on their own (tests/test_sheet.py); the sheet only draws
them. A part that comes from something you carry names it by key, so the sheet can make it a link to its card.

Only what's always so is counted here: a bonus that depends on the moment (a monster's weakness, a stunned foe, flair)
is the dice's to show when it happens.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import powers
from .content import Content
from .models import MAX_FATE, GameState

STATS = ("might", "agility", "wits")


@dataclass
class Part:
    """One piece of a sum: "+2 A Ring, Probably Important". `item` is the key of what gives it, if something you carry
    does."""

    name: str
    value: int
    item: str = ""


@dataclass
class Line:
    """A stat or a roll: its total and what it's made of. `note` says what the parts can't (advantage, a curse)."""

    label: str
    total: int
    parts: list[Part] = field(default_factory=list)
    note: str = ""


# The rolls you make, how the rules make them (combat.py, rules.py, interactions.py): (label, its stat, the kind of
# roll an item's power helps, what else is always added).
ROLLS = [
    ("Attack", "might", "attack"),
    ("Throw", "agility", "throw"),
    ("Dodge", "agility", "dodge"),
    ("Flee", "agility", "flee"),
    ("Pick a lock", "agility", "disarm"),
    ("Smash", "might", "smash"),
    ("Search", "wits", "search"),
    ("Talk a foe down", "wits", "talk"),
    ("Ask", "wits", "ask"),
    ("Haggle", "wits", "barter"),
]
ADVANTAGE = {  # a trait that rolls two dice and keeps the best, for a kind of roll
    "talk": ("silver_tongue", "Silver Tongue"), "ask": ("silver_tongue", "Silver Tongue"),
    "barter": ("silver_tongue", "Silver Tongue"), "dodge": ("duelist", "Duelist"),
    "flee": ("escape_artist", "Escape Artist"),
}


def item_parts(state: GameState, content: Content, kind: str) -> list[Part]:
    """What the things you carry add to one kind of roll (powers.ROLLS), each under its own name and key."""
    parts = []
    for item in powers.carried(state, content):
        for power in powers.powers_of(state, item):
            value, kinds = powers.ROLLS.get(power, (0, set()))
            if value and (kinds is None or kind in kinds):
                parts.append(Part(item.name, value, item.key))
    return parts


def stat_line(state: GameState, content: Content, stat: str) -> Line:
    """Might, agility or wits: what you are without what you carry, and each thing that changes it (Lenny's Bad
    Tooth: +1 might)."""
    player = state.player
    total = player.stat(stat)
    from_items = [Part(item.name, item.stats[stat], item.key) for item in powers.carried(state, content)
                  if item.stats.get(stat)]
    base = total - sum(p.value for p in from_items)
    return Line(stat.capitalize(), total, [Part("base", base), *from_items])


def hp_line(state: GameState, content: Content) -> Line:
    player = state.player
    from_items = [Part(item.name, item.stats["max_hp"], item.key) for item in powers.carried(state, content)
                  if item.stats.get("max_hp")]
    base = player.max_hp - sum(p.value for p in from_items)
    return Line("HP", player.hp, [Part("most", player.max_hp), Part("base", base), *from_items])


def defense_line(state: GameState, content: Content) -> Line:
    player = state.player
    parts = [Part("base", 10), Part("agility", player.agility)]
    if player.armor:
        armor = content.item(player.armor)
        parts.append(Part(armor.name, armor.defense, armor.key))
    if "iron_skin" in player.perks:
        parts.append(Part("Iron Skin", 1))
    return Line("Defense", player.defense(content), [p for p in parts if p.value or p.name == "base"])


def fate_line(state: GameState, content: Content) -> Line:
    player = state.player
    parts = [Part("base", MAX_FATE)]
    if "lucky" in player.perks:
        parts.append(Part("Lucky", 1))
    if "lucky_charm" in player.inventory:
        parts.append(Part(content.item("lucky_charm").name, 1, "lucky_charm"))
    return Line("Fate", player.fate, parts, note=f"of {player.max_fate()}")


def damage_line(state: GameState, content: Content) -> Line:
    """What a blow with your weapon does, bar the moment's extras (a weakness, a crit): its dice, then what's added."""
    player = state.player
    weapon = content.item(player.weapon)
    parts = [Part(weapon.name, 0, weapon.key), Part("might", player.might)]
    if "brute" in player.traits:
        parts.append(Part("Brute", 1))
    if "glass_cannon" in player.perks:
        parts.append(Part("Glass Cannon", 3))
    if "sharp_start" in player.blessings and player.weapon == "rusty_sword":
        parts.append(Part("Sharp Start", 1))
    if player.coated:
        parts.append(Part(f"{player.coating} coating ({player.coated} hits)", 0))
    if "goblin_bane" in weapon.powers:
        parts.append(Part("+2 against goblins", 0, weapon.key))
    return Line("Damage", sum(p.value for p in parts), [p for p in parts if p.value or p.item or "coating" in p.name],
                note=weapon.damage)


def roll_lines(state: GameState, content: Content) -> list[Line]:
    """Every kind of roll you make, each with its stat and everything that's always added: the d20 plus this."""
    player = state.player
    lines = []
    for label, stat, kind in ROLLS:
        parts = [Part(stat, player.stat(stat))]
        if kind == "attack":
            parts.append(Part("level", player.level))
        if kind == "search":
            if "keen_eye" in player.blessings:
                parts.append(Part("Keen Eye", 3))
            if "treasure_nose" in player.traits:
                parts.append(Part("Treasure Nose", 2))
        parts += item_parts(state, content, kind)
        trait = ADVANTAGE.get(kind)
        note = f"advantage ({trait[1]})" if trait and trait[0] in player.traits else ""
        lines.append(Line(label, sum(p.value for p in parts), parts, note))
    parts = [Part("Improviser", 2)] * ("improviser" in player.perks) + [Part("Trickster", 1)] * (
        "trickster" in player.traits) + item_parts(state, content, "creative")
    lines.append(Line("Anything else you try", sum(p.value for p in parts), parts, "plus the stat it takes"))
    return lines


@dataclass
class Effect:
    """Something you carry and what it does for you (or to you) while you do."""

    item: str
    name: str
    worn: str  # "in hand", "worn", or "" for the pack
    says: list[str]
    cursed: bool = False


def carried_effects(state: GameState, content: Content) -> list[Effect]:
    """Everything working on you now: your weapon and armor, and each thing in your pack that does something while
    you carry it (its powers, its stats), cursed ones marked. A thing that only does something when used (a potion,
    a bomb) isn't listed: it's not working on you."""
    player = state.player
    effects = []
    for item in powers.carried(state, content):
        held = powers.powers_of(state, item)
        says = []
        worn = "in hand" if item.key == player.weapon else "worn" if item.key == player.armor else ""
        if worn == "in hand":
            says.append(f"{item.damage} damage")
        elif worn == "worn":
            says.append(f"+{item.defense} defense")
        says += [powers.POWERS[p] for p in held if p in powers.CARRYING]
        if item.stats:
            says.append(powers.stat_words(item.stats))
        if says:
            effects.append(Effect(item.key, item.name, worn, says, "cursed" in held))
    return effects
