"""How the game screen is shared out (ui/plan.py): the story keeps its rows, and nothing shrinks as the window grows."""

from ptg.ui.plan import (NUDGE, PAD_ROWS, STAGE_CAP, STAGE_MIN, STORY_MIN, STORY_WITH_STAGE, TWO_COLUMNS_AT, make_plan)


SMALLEST_ROWS = 24


def swept(fixed: int, along: str, values, touch: bool = False):
    """Plans for a window growing in one direction (the other kept at `fixed`), each with the one before it."""
    plans = [make_plan(v, fixed, touch) if along == "W" else make_plan(fixed, v, touch) for v in values]
    return list(zip(plans, plans[1:]))


def test_two_columns_from_88_and_one_below():
    assert make_plan(TWO_COLUMNS_AT, 40).two_columns and not make_plan(TWO_COLUMNS_AT - 1, 40).two_columns
    assert make_plan(100, 30).two_columns and not make_plan(60, 44).two_columns


def test_a_wide_short_landscape_screen_keeps_two_columns():
    assert make_plan(84, 17).two_columns and make_plan(80, 24).two_columns
    assert not make_plan(60, 20).two_columns  # (too narrow for two, whatever its shape)


def test_a_switch_waits_a_nudge_past_its_line_before_it_flips_back():
    wide = make_plan(TWO_COLUMNS_AT, 40)
    assert make_plan(TWO_COLUMNS_AT - 1, 40, previous=wide).two_columns  # (dragged back across the line: kept)
    assert not make_plan(TWO_COLUMNS_AT - NUDGE - 1, 40, previous=wide).two_columns
    narrow = make_plan(TWO_COLUMNS_AT - 1, 40)
    assert not make_plan(TWO_COLUMNS_AT, 40, previous=narrow).two_columns
    assert make_plan(TWO_COLUMNS_AT + NUDGE, 40, previous=narrow).two_columns


def test_the_stage_waits_a_nudge_past_the_rows_it_needs_before_it_shows():
    shown = next(make_plan(130, rows) for rows in range(20, 60) if make_plan(130, rows).stage_rows)
    assert shown.stage_rows >= STAGE_MIN
    before = make_plan(130, shown.rows - 1)
    assert before.stage_rows == 0
    assert make_plan(130, shown.rows, previous=before).stage_rows == 0  # (not yet: it'd flicker on and off)
    assert make_plan(130, shown.rows + NUDGE, previous=before).stage_rows >= STAGE_MIN


def test_the_story_always_keeps_its_rows_and_more_with_a_stage():
    for columns in range(36, 260, 3):
        for rows in range(16, 80):
            for touch in (False, True):
                plan = make_plan(columns, rows, touch)
                assert plan.story_rows >= STORY_MIN or rows < SMALLEST_ROWS, (columns, rows)  # (under it: "make it bigger")
                if plan.stage_rows:
                    assert plan.story_rows >= STORY_WITH_STAGE[plan.two_columns], (columns, rows)
                    assert plan.stage_rows >= STAGE_MIN and plan.stage_width <= STAGE_CAP


def test_the_stage_is_shaped_like_a_room():
    for columns, rows in [(130, 44), (100, 30), (200, 56), (150, 46), (90, 60)]:
        plan = make_plan(columns, rows)
        assert plan.stage_rows and 3.4 <= plan.stage_width / plan.stage_rows <= 4.9, (columns, rows, plan)


def test_nothing_shrinks_as_the_window_grows_taller():
    """Bar the story giving the stage its rows the moment it first shows, the switch between one column and two (a
    landscape screen that grows taller turns into a phone's), and a short screen's compact chrome giving way to
    frames and a footer (then the stage and Here give those rows up, never the story)."""
    for columns in (40, 52, 60, 80, 100, 130, 170, 220):
        for before, after in swept(columns, "H", range(12, 80)):
            appears = not before.stage_rows and after.stage_rows
            columns_switched = before.two_columns != after.two_columns
            swapped = before.compact != after.compact or columns_switched
            for name in ("story_rows", "stage_rows", "here_rows"):
                if getattr(after, name) < getattr(before, name):
                    assert (name == "story_rows" and (appears or columns_switched)) or \
                        (name != "story_rows" and swapped) or (name == "here_rows" and appears), \
                        (columns, before.rows, name)


def test_the_stage_and_here_never_shrink_as_the_window_grows_wider():
    for rows in (20, 24, 30, 36, 46, 60):
        for before, after in swept(rows, "W", range(36, 260)):
            if before.two_columns == after.two_columns:
                assert after.stage_rows >= before.stage_rows and after.here_rows >= before.here_rows, \
                    (rows, before.columns)


def test_the_story_keeps_one_plan_as_the_window_grows_wider_without_a_stage_to_feed():
    """The story gives rows only to a stage that's growing with the width; once the stage is as big as it gets, a
    wider window leaves it alone."""
    for rows in (36, 46, 60):
        plans = [make_plan(columns, rows) for columns in range(160, 260)]
        assert len({(p.story_rows, p.stage_rows, p.here_rows) for p in plans}) == 1, rows


def test_the_screens_rows_are_all_accounted_for():
    for columns, rows in [(130, 44), (100, 30), (70, 26), (200, 56), (48, 60)]:
        plan = make_plan(columns, rows)
        chrome = 1 + (1 if plan.compact else 3) + (0 if plan.compact else 1)  # status bar, command line, footer
        used = chrome + plan.choice_rows + 1 + plan.ways_rows
        used += plan.stage_rows + plan.edge if plan.stage_rows else 0
        used += plan.story_rows + plan.edge
        if not plan.two_columns:
            used += plan.here_rows + plan.edge
        assert used <= rows, (columns, rows, plan, used)
        if plan.two_columns:
            assert plan.here_rows + PAD_ROWS + plan.edge <= rows, (columns, rows)


def test_touch_gives_the_ways_out_buttons_three_rows_tall():
    assert make_plan(60, 44, touch=True).ways_rows == 3 and make_plan(60, 44).ways_rows == 1
    assert make_plan(130, 44, touch=True).ways_rows == 0  # (two columns: the arrow pad is in the side column)


def test_the_side_column_grows_only_once_the_stage_has_reached_its_cap():
    assert make_plan(150, 46).side == 30 and make_plan(172, 46).side == 30 or make_plan(172, 46).side < 56
    assert make_plan(260, 56).side == 56
    sides = [make_plan(columns, 46).side for columns in range(100, 260)]
    assert sides == sorted(sides)  # (never narrower as the window widens)
