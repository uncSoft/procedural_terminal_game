"""Small English helpers for engine-written facts."""

from __future__ import annotations


def the(name: str) -> str:
    lower = name.lower()
    for article in ("the ", "a ", "an "):
        if lower.startswith(article):
            return "the " + name[len(article):]
    return "the " + name


def a(name: str) -> str:
    lower = name.lower()
    if lower.startswith(("the ", "a ", "an ")):
        return name
    return ("an " if lower[:1] in "aeiou" else "a ") + name


def cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def bare(name: str) -> str:
    """'a stew cauldron' -> 'stew cauldron'."""
    lower = name.lower()
    for article in ("the ", "a ", "an "):
        if lower.startswith(article):
            return name[len(article):]
    return name
