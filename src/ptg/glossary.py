"""Things the story can mention: monsters, characters, items, room features, fixtures, rooms and game terms.

The UI uses this to highlight them in the narration and to explain them on hover or click. Terms are
built from the content library plus what's actually around the player, so "the cauldron" lights up in the
room that has one, and "potion" means the potion you're carrying.

A creature's kind is "monster" (a foe's colour), or "character" for someone who isn't a danger: anyone tagged npc
(Lucky Lenny, Swoogy, the shopkeepers) unless the one here is fighting you, and any creature here that has stopped
fighting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import npcs, powers, statuses
from .content import Content
from .models import GameState
from .text import bare

FIXTURES = {
    "shrine": "A shrine that trades blood for Fate, or gold for healing. One use.",
    "chest": "An iron-bound chest, probably trapped. Open it with a small key, pick the lock (agility: the trap "
             "may get you) or smash it (might: what's inside may break).",
    "fountain": "A strange fountain. Drink and roll: it might hurt, heal, grant Fate, or bless a stat. Its water "
                "puts out a fire on you.",
    "stairs": "Stairs down to the next floor. There's no coming back up.",
    "shop": "A shop, behind a locked door (a small key, or two bombs). Buy what's on the counter with gold, or haggle "
            "(wits): talk her down a third, or put it up a quarter. Once a ware.",
}
# Head nouns that are also everyday words ("you stand", "in case"): only the full name counts for these.
COMMON_WORDS = {"stand", "case", "rail", "pile", "heap", "hole", "gap", "wall", "rack", "box", "bench", "ledge",
                "bowl", "knot", "sack", "rope", "table", "chart", "cart", "cage", "plates", "boots", "stubs", "debris",
                "bucket", "nest", "hand", "heart", "sword", "bones", "skulls"}
# Words an item's short name mustn't be on its own, since the story uses them for other things (water in a puddle, light
# from a torch, the stone walls, the dice you roll, ducking a blow): the full name still counts.
EVERYDAY = {"water", "oil", "light", "stone", "important", "foot", "rat", "pick", "wrap", "stick", "kit", "dice", "duck",
            "wheel", "scores", "pointer", "bag"}
FIXTURE_WORDS = {"shrine": "shrine", "chest": "chest", "fountain": "fountain", "stairs": "stairs",
                 "staircase": "stairs", "shop": "shop", "counter": "shop"}
STATUS_WORDS = {"poison": ("poison", "venom"), "burn": ("set alight", "on fire"), "stun": ("dazed", "seeing stars"),
                "mend": ("mends",)}  # what else the story calls a status, besides its name
RULES = {
    "fate": ("Fate", "Spend a Fate token to reroll a failed check. Earn it with flair, perfect dodges, natural 20s "
                     "and shrines."),
    "souls": ("Souls", "Earned by defeating monsters and going deeper. They survive death: spend them at the "
                       "campfire on blessings and gifts."),
    "advantage": ("Advantage", "Roll two d20s and keep the higher. Earned by stuns, perfect dodges and using a "
                               "monster's weakness against it."),
    "flair": ("Flair", "Using a real prop from the room or your pack adds a bonus to the roll and earns Fate on "
                       "success."),
}


@dataclass(frozen=True)
class Term:
    id: str  # "monster:goblin", "item:healing_potion", "feature:2", "fixture:shrine", "room:4", "rule:fate"
    kind: str
    name: str
    summary: str


def build(state: GameState, content: Content, bestiary: dict | None = None) -> dict[str, Term]:
    """Every alias (lower case) the narration might use, mapped to the thing it refers to."""
    bestiary = bestiary or {}
    terms: dict[str, Term] = {}
    room, player = state.room, state.player

    def add(alias: str, term: Term) -> None:
        alias = alias.lower().strip()
        if len(alias) >= 3 and alias not in terms:
            terms[alias] = term

    # Monsters: by full name those who are here, on this floor or in the bestiary (seen); short names for the floor's.
    on_floor = {r.monster.key: r.monster for r in state.rooms if r.monster}
    near = set(on_floor) | set(bestiary) | {r.shop.keeper for r in state.rooms if r.shop}
    for key, monster in content.monsters.items():
        if monster.ghost or key not in near:
            continue
        term = Term(f"monster:{key}", creature_kind(state, content, key), monster.name.removeprefix("The "),
                    monster_summary(state, content, key, bestiary.get(key)))
        add(monster.name.removeprefix("The "), term)
        if key in on_floor:
            last = monster.name.split()[-1]
            add(last, term)
            add(last + "s", term)
    for state_monster in on_floor.values():
        kind = creature_kind(state, content, state_monster.key)
        term = Term(f"monster:{state_monster.key}", kind, state_monster.name,
                    monster_summary(state, content, state_monster.key, bestiary.get(state_monster.key)))
        add(state_monster.name, term)
        if state_monster.ghost_of:
            add(f"ghost of {state_monster.ghost_of}", term)
            add(state_monster.ghost_of, term)

    # Items: full names for anything; short names for what you carry or can see.
    nearby = [*player.gear, *player.inventory, *room.items]
    for key, item in content.items.items():
        term = Term(f"item:{key}", "item", item.name, item_summary(content, key))
        add(item.name, term)
        if key in nearby:
            for alias in short_names(item.name):
                add(alias, term)

    # Features of this room: "a stew cauldron" -> "stew cauldron" and "cauldron".
    for index, feature in room.visible_features():
        name = bare(feature.name)
        tags = content.feature_tags(feature.name)
        status = "searched" if feature.searched else "not searched yet"
        summary = f"{name} · {', '.join(tags) if tags else 'no special properties'} · {status}"
        term = Term(f"feature:{index}", "feature", name, summary)
        add(name, term)
        head = re.sub(r"'s$", "", name.split()[-1])
        if head.lower() not in COMMON_WORDS:
            add(head, term)

    if room.fixture:
        for word, fixture in FIXTURE_WORDS.items():
            if fixture == room.fixture:
                add(word, Term(f"fixture:{fixture}", "fixture", fixture, FIXTURES[fixture]))

    for other in state.rooms:
        if other.visited:
            add(other.name, Term(f"room:{other.id}", "room", other.name,
                                 f"{other.name} · exits {', '.join(other.exits)}"
                                 + (" · you are here" if other.id == state.room_id else "")))

    # Place names, so the words inside them ("Goblin" in The Goblin Warren) aren't taken for what they're named after:
    # found, they're left plain (Lexicon.find).
    for place in [*(theme.name for theme in content.themes.values()), *(other.name for other in state.rooms)]:
        for alias in (place, place.removeprefix("The ")):
            add(alias, Term("", "place", place, ""))

    for key, (name, summary) in RULES.items():
        add(name, Term(f"rule:{key}", "rule", name, summary))
    for key, status in statuses.DEFS.items():  # (what ails you, or a foe, or mends: a card of its own)
        term = Term(f"status:{key}", "status", status.name, status.blurb)
        for alias in (status.name, *STATUS_WORDS.get(key, ())):
            add(alias, term)
    light_term = Term("status:light", "status", "Light", "Down on the dark floors, a light of your own matters.")
    for alias in ("pitch dark", "darkness", "the dark"):
        add(alias, light_term)
    return terms


def short_names(name: str) -> list[str]:
    """What the story may call an item you carry or can see, besides its full name: "Flask of Lamp Oil" -> "flask",
    "lamp oil"; "Lucky Rabbit's Foot" -> "rabbit's foot"; "A Ring, Probably Important" -> "ring". Never an everyday
    word on its own (EVERYDAY): "Vial of Holy Water" is "holy water" and "vial", but plain water stays water."""
    name = name.split(",")[0]
    for article in ("A ", "An ", "The "):
        name = name.removeprefix(article)
    for joint in (" of ", " o' ", " in the "):
        if joint in name:
            head, tail = name.split(joint, 1)
            names = [head.split()[0]] if joint == " in the " else [head, tail, tail.split()[-1]]
            break
    else:
        words = name.split()
        names = [words[-1]] + ([" ".join(words[-2:])] if len(words) > 2 else [])
    return [alias for alias in dict.fromkeys(names) if alias.lower() not in EVERYDAY]


def pattern(terms: dict[str, Term]) -> re.Pattern | None:
    if not terms:
        return None
    aliases = sorted(terms, key=len, reverse=True)
    return re.compile(r"(?<![\w-])(" + "|".join(re.escape(a) for a in aliases) + r")(?![\w-])", re.IGNORECASE)


def creature_kind(state: GameState, content: Content, key: str) -> str:
    """"character" for someone who's no danger (anyone tagged npc, unless the one here is fighting you, and anyone
    here who's stopped fighting), else "monster"."""
    here = state.room.monster if state.room.monster and state.room.monster.key == key else None
    if here is not None:
        return "monster" if here.hostile else "character"
    return "character" if content.monster(key).npc else "monster"


def monster_summary(state: GameState, content: Content, key: str, entry: dict | None) -> str:
    monster = content.monster(key)
    known = state.known_weak.get(key) or (entry or {}).get("weak") or []
    standing = npcs.status(state, content, key)  # a character: "wants his bad tooth back"
    parts = [monster.name.removeprefix("The "), "boss" if monster.boss else standing or f"tier {monster.tier}"]
    here = state.room.monster
    if here and here.key == key:
        parts.append(f"{max(0, here.hp)}/{here.max_hp} HP")
        if here.intent == "heavy" and here.hostile:
            parts.append("winding up a heavy blow!")
    parts.append("weak to " + ", ".join(known) if known else "weakness unknown")
    if monster.intelligent:
        parts.append("can be reasoned with")
    return " · ".join(parts)


def item_stats(item) -> str:
    """What an item is and does, its powers aside: "weapon, 1d8 damage", "restores 8 HP"."""
    return {"weapon": f"weapon, {item.damage} damage", "armor": f"armor, +{item.defense} defense",
            "helm": f"helm, +{item.defense} defense",
            "consumable": "escape" if item.escape else f"restores {item.heal} HP",
            "key": "key", "trinket": "trinket: use it creatively"}[item.kind]


def item_summary(content: Content, key: str) -> str:
    item = content.item(key)
    stats = item_stats(item)
    if item.powers:
        stats += "; " + "; ".join(powers.describe(item))
    tags = f" · {', '.join(item.tags)}" if item.tags else ""
    return f"{item.name} · {stats}{tags}"


class Lexicon:
    """A built set of terms plus the regex that finds them in text."""

    def __init__(self, terms: dict[str, Term]):
        self.terms = terms
        self.regex = pattern(terms)

    def find(self, text: str) -> list[tuple[int, int, Term]]:
        if self.regex is None:
            return []
        found = [(m.start(), m.end(), self.terms[m.group(0).lower()]) for m in self.regex.finditer(text)]
        return [hit for hit in found if hit[2].kind != "place"]
