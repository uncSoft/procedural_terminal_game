"""A run left unfinished (ptg/config.py read_save, meta.py abandon): Continue picks it up, and starting a new one
instead ends it as a death, kept in the Hall of Legends with its souls and a ghost."""

import json
import random

from ptg.config import load_game, read_save, save_game, save_path
from ptg.llm import extras
from ptg.meta import abandon, run_summary, souls_earned, start_run
from ptg.models import LogEntry


def test_abandoning_a_run_is_a_death(content, profile):
    state = start_run(profile, content, "Quitter", seed=5)
    state.souls, state.player.gold = 12, 40
    save_game(state)
    banked = profile.souls
    kept = abandon(profile, state)
    assert kept == souls_earned(state) >= 16 and profile.souls == banked + kept
    run = profile.runs(limit=1)[0]
    assert (run["status"], run["cause"]) == ("dead", "abandoned on floor 1")
    assert run["epitaph"] == "Here lies Quitter the Brief, abandoned on floor 1."
    ghost = profile.pick_ghost(random.Random(0), chance=1.0)
    assert (ghost["name"], ghost["floor"], ghost["cause"]) == ("Quitter", 1, "abandoned on floor 1")
    assert read_save() == (None, "")  # nothing left to continue


def test_a_daily_left_unfinished_leaves_no_ghost(content, profile):
    abandon(profile, start_run(profile, content, "Quitter", daily=True))
    assert profile.runs(limit=1)[0]["status"] == "dead" and profile.pick_ghost(random.Random(0), chance=1.0) is None


def test_a_save_that_cant_be_continued_says_why(content, profile):
    save_game(start_run(profile, content, "Old", seed=5))
    assert read_save()[0].seed == 5
    data = json.loads(save_path().read_text())
    save_path().write_text(json.dumps({**data, "version": 1}))
    assert read_save() == (None, "an older version of the game saved it") and load_game() is None
    save_path().write_text("{not json")
    assert read_save() == (None, "its save is damaged")
    save_path().write_text(json.dumps({**data, "status": "won"}))
    assert read_save() == (None, "")  # finished: nothing to explain


async def test_the_game_screen_gets_no_stand_in_for_a_recap(content, profile):
    """Offline, "Previously…" was the last narration again, just under the story that ends with it."""
    state = start_run(profile, content, "Back", seed=5)
    state.log.append(LogEntry(kind="narration", text="The fountain burbles."))
    assert await extras.recap(None, state) == "The fountain burbles."  # plain mode shows no story to scroll back
    assert await extras.recap(None, state, stand_in=False) == ""


def test_a_run_in_short(content, profile):
    who, where, how = run_summary(start_run(profile, content, "Back", seed=5))
    assert who == "Back, level 1" and where.startswith("Floor 1/4 · The ") and how.endswith("HP · turn 0")
