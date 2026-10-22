"""How a roll went, seen from the player's side of the table: great, good, neutral, bad or awful.

The UI colours and pulses things by this (green when it goes your way, red when it doesn't, gold for a natural
20). It's worked out from the kind of event as well as the dice, so a monster missing you is good news, a failed
search that costs nothing is neutral, and a "failed" luck roll at the fountain that still heals you is neutral too.
"""

from __future__ import annotations

from .events import Event

GREAT, GOOD, NEUTRAL, BAD, AWFUL = "great", "good", "neutral", "bad", "awful"
TONES = (GREAT, GOOD, NEUTRAL, BAD, AWFUL)

GOOD_KINDS = {"hit", "monster_miss", "evade", "dodge_ready", "flee", "secret"}
BAD_KINDS = {"miss", "monster_hit", "dodge_fail", "flee_fail"}
NEUTRAL_KINDS = {"search_room"}

WORDS = {
    "hit": "HIT", "miss": "MISS", "monster_hit": "HIT YOU", "monster_miss": "MISSED YOU", "evade": "EVADED",
    "dodge_ready": "READY", "dodge_fail": "TOO SLOW", "flee": "ESCAPED", "flee_fail": "CUT OFF",
    "secret": "FOUND IT", "search_room": "NOTHING",
}


def tone(event: Event) -> str | None:
    """How this event's roll went for the player, or None if it had no roll."""
    roll = event.dice
    if roll is None:
        return None
    if roll.actor == "monster":
        if not roll.success or event.kind == "evade":
            return GOOD
        return AWFUL if roll.crit else BAD
    if roll.crit:
        return GREAT
    if roll.fumble:
        return AWFUL
    if event.kind == "fountain":
        return BAD if roll.kept <= 5 else (NEUTRAL if roll.kept <= 14 else GOOD)
    if event.kind in GOOD_KINDS:
        return GOOD
    if event.kind in BAD_KINDS:
        return BAD
    if event.kind in NEUTRAL_KINDS:
        return NEUTRAL
    return GOOD if roll.success else BAD


def verdict(event: Event) -> str:
    """A word or two for the roll's badge: HIT, MISSED, FOUND IT, CRITICAL!..."""
    roll, how = event.dice, tone(event)
    if roll is None:
        return ""
    if roll.actor == "player" and how == GREAT:
        return "CRITICAL!"
    if roll.actor == "player" and how == AWFUL:
        return "FUMBLE"
    if roll.actor == "monster" and how == AWFUL:
        return "CRITICAL HIT"
    if event.kind == "fountain":
        return {GOOD: "LUCKY", NEUTRAL: "CLEAN WATER", BAD: "BITTER"}[how]
    if event.kind == "chest":
        return "TRAP CAUGHT" if roll.success else "TRAPPED"
    if event.kind == "check":
        return "IT WORKS" if roll.success else "IT FAILS"
    return WORDS.get(event.kind) or ("SUCCESS" if roll.success else "FAIL")


def overall(events: list[Event]) -> str | None:
    """The turn's tone across all its rolls. A natural 20 or 1 on your own roll wins out; mixed fortunes
    (you hit it, it hits you) read as neutral. None if nothing was rolled."""
    tones = [(event, tone(event)) for event in events if event.dice]
    if not tones:
        return None
    yours = next((how for event, how in tones if event.dice.actor == "player"), None)
    if yours in (GREAT, AWFUL):
        return yours
    found = {how for _, how in tones}
    good, bad = found & {GREAT, GOOD}, found & {BAD, AWFUL}
    if good and bad:
        return NEUTRAL
    if bad:
        return AWFUL if AWFUL in found else BAD
    return GOOD if good else NEUTRAL
