"""Small English helpers for engine-written facts."""

from __future__ import annotations


# Names that take no article: characters, not things ("Lucky Lenny", not "the Lucky Lenny"). content.load_content
# fills it from the monsters tagged npc or named.
NAMED: set[str] = set()


def the(name: str) -> str:
    lower = name.lower()
    for article in ("the ", "a ", "an "):
        if lower.startswith(article):
            return "the " + name[len(article):]
    return name if _owned(name) or name in NAMED else "the " + name


def a(name: str) -> str:
    lower = name.lower()
    if lower.startswith(("the ", "a ", "an ")):
        return name[:1].lower() + name[1:]  # "A Ring, Probably Important" mid-sentence
    if _owned(name) or name in NAMED:
        return name
    return ("an " if lower[:1] in "aeiou" else "a ") + name


def tell(name: str, words: str) -> str:
    """A monster winding up, as its maker wrote it: after its name ("The Troll rips a slab out of the wall"), as a
    sentence of its own when it names itself ("Swoogy charges up his flaps..."), or yelled when it's a shout ("Baby
    Joey yells, "Gimme dat!!"")."""
    words = words.strip()
    lead = [w.strip(".,!?'\"").lower() for w in words.split()[:2]]
    if lead[:1] in (["the"], ["a"], ["an"]):  # ("The Sporerat's caps flare green": it names itself as well)
        lead = lead[1:]
    first = lead[0].removesuffix("'s").removesuffix("’s") if lead else ""
    if first and first in {w.lower() for w in name.split() if w.lower() not in ("the", "a", "an")}:
        return words
    letters = [c for c in words if c.isalpha()]
    if words.endswith("!") or (letters and all(c.isupper() for c in letters)):
        return f'{cap(the(name))} yells, "{words}"'
    return f"{cap(the(name))} {mid_sentence(words)}"


# What a place's or a thing's title can be named for that isn't anybody: "the Saint's Alcove", not "Saint's Alcove".
NOBODY = {"saint", "abbot", "monk", "priest", "king", "queen", "lord", "lady", "knight", "giant", "dragon", "troll",
          "goblin", "ogre", "wizard", "witch", "hermit", "miner", "butcher", "hunter", "warden", "jester", "beggar",
          "thief", "smith", "sailor", "fool", "devil", "demon", "angel", "god", "rabbit", "wolf", "bird", "cat", "dog"}


def _owned(name: str) -> bool:
    """Someone's, by name, which takes no article: "Brannoc's remains", a character's ("Swoogy's Diaper", "Granny
    Gristle's Shop", "Lenny's Bad Tooth"), or anyone's at all ("Mama's Shillelagh"). A thing named for something that
    isn't anybody still takes one: "a mourner's lantern", "the Lucky Rabbit's Foot", "the Saint's Alcove"."""
    words = name.split()
    mark = next((i for i, w in enumerate(words) if w.endswith(("'s", "s'"))), None)
    if mark is None or not all(w[:1].isupper() for w in words[:mark + 1]):
        return False
    stem = words[mark][:-2] if words[mark].endswith("'s") else words[mark][:-1]
    owner, rest = words[:mark] + [stem], words[mark + 1:]
    if not rest or rest[0][:1].islower():  # "Brannoc's remains"
        return True
    characters = [n.split() for n in NAMED]
    if any(owner == n[i:i + len(owner)] for n in characters for i in range(len(n))):  # Lenny, of Lucky Lenny
        return True
    return len(owner) == 1 and words[mark].endswith("'s") and owner[0].lower() not in NOBODY


def cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def mid_sentence(text: str) -> str:
    """Words written as a sentence, carrying on one instead: "Slowly circles." -> "slowly circles" (an acronym
    like "NPC" keeps its capitals)."""
    text = text.strip().rstrip(" .!")
    return text[:1].lower() + text[1:] if text[:1].isupper() and not text[1:2].isupper() else text


def bare(name: str) -> str:
    """'a stew cauldron' -> 'stew cauldron'."""
    lower = name.lower()
    for article in ("the ", "a ", "an "):
        if lower.startswith(article):
            return name[len(article):]
    return name
