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
    first = words.split()[0].strip(".,!?'\"").lower() if words else ""
    if first and first in {w.lower() for w in name.split() if w.lower() not in ("the", "a", "an")}:
        return words
    letters = [c for c in words if c.isalpha()]
    if words.endswith("!") or (letters and all(c.isupper() for c in letters)):
        return f'{cap(the(name))} yells, "{words}"'
    return f"{cap(the(name))} {mid_sentence(words)}"


def _owned(name: str) -> bool:
    """Someone's, by name: "Brannoc's remains" takes no article (a "mourner's lantern" and "the Saint's Alcove", a
    place's title, still do)."""
    first, _, rest = name.partition(" ")
    return first[:1].isupper() and first.endswith(("'s", "s'")) and rest[:1].islower()


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
