"""Small English helpers for engine-written facts."""

from __future__ import annotations


def the(name: str) -> str:
    lower = name.lower()
    for article in ("the ", "a ", "an "):
        if lower.startswith(article):
            return "the " + name[len(article):]
    return name if _owned(name) else "the " + name


def a(name: str) -> str:
    lower = name.lower()
    if lower.startswith(("the ", "a ", "an ")):
        return name[:1].lower() + name[1:]  # "A Ring, Probably Important" mid-sentence
    if _owned(name):
        return name
    return ("an " if lower[:1] in "aeiou" else "a ") + name


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
