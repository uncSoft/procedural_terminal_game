import pytest

from ptg.dice import Roll
from ptg.events import Event
from ptg.outcome import AWFUL, BAD, GOOD, GREAT, NEUTRAL, overall, tone, verdict


def roll(kept: int, success: bool, actor: str = "player") -> Roll:
    return Roll("might", actor, [kept], kept, dc=12, success=success)


@pytest.mark.parametrize("kind,kept,success,actor,how,word", [
    ("hit", 14, True, "player", GOOD, "HIT"),
    ("hit", 20, True, "player", GREAT, "CRITICAL!"),
    ("miss", 6, False, "player", BAD, "MISS"),
    ("miss", 1, False, "player", AWFUL, "FUMBLE"),
    ("monster_miss", 5, False, "monster", GOOD, "MISSED YOU"),
    ("monster_hit", 15, True, "monster", BAD, "HIT YOU"),
    ("monster_hit", 20, True, "monster", AWFUL, "CRITICAL HIT"),
    ("evade", 15, True, "monster", GOOD, "EVADED"),
    ("search_room", 7, False, "player", NEUTRAL, "NOTHING"),
    ("secret", 16, True, "player", GOOD, "FOUND IT"),
    ("fountain", 3, False, "player", BAD, "BITTER"),
    ("fountain", 9, False, "player", NEUTRAL, "CLEAN WATER"),  # a "failed" luck roll that still heals you
    ("fountain", 17, True, "player", GOOD, "LUCKY"),
    ("chest", 15, True, "player", GOOD, "TRAP CAUGHT"),
    ("chest", 8, False, "player", BAD, "TRAPPED"),
    ("check", 13, True, "player", GOOD, "IT WORKS"),
    ("check", 9, False, "player", BAD, "IT FAILS"),
])
def test_how_a_roll_went_for_you(kind, kept, success, actor, how, word):
    event = Event(kind, "", dice=roll(kept, success, actor))
    assert tone(event) == how and verdict(event) == word


def test_no_roll_no_tone():
    assert tone(Event("enter", "")) is None and overall([Event("enter", "")]) is None


def test_a_turn_reads_as_a_whole():
    hit, miss = Event("hit", "", dice=roll(14, True)), Event("miss", "", dice=roll(5, False))
    dodged = Event("monster_miss", "", dice=roll(4, False, "monster"))
    hurt = Event("monster_hit", "", dice=roll(15, True, "monster"))
    crushed = Event("monster_hit", "", dice=roll(20, True, "monster"))
    assert overall([hit, dodged]) == GOOD
    assert overall([miss, hurt]) == BAD
    assert overall([hit, hurt]) == NEUTRAL  # mixed fortunes
    assert overall([miss, crushed]) == AWFUL
    assert overall([Event("hit", "", dice=roll(20, True)), hurt]) == GREAT  # your natural 20 wins out
    assert overall([Event("search_room", "", dice=roll(7, False))]) == NEUTRAL
