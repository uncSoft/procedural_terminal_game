"""How the game screen is shared out for the size it has: a stage (the room's picture) over a story of words, with Here
(who and what is in the room) beside them or in a strip under the stage, the choices in a compact strip, and, on a
narrow screen, a bar of ways out. Pure sums, so they're tested on their own (tests/test_plan.py) and the screen
only applies the answer (GameScreen.relayout).

The story is shared out first, so it always keeps its rows (at least STORY_MIN, and STORY_WITH_STAGE whenever there's a
stage too), then the choices, the ways out and the least of Here, and the stage, shaped like a room, gets what's left.
As the screen grows taller nothing shrinks, bar the one moment a stage first appears (the story gives it rows, down to
STORY_WITH_STAGE) and the moment a short screen's compact chrome gives way to frames and a footer (the stage and Here
give those rows up, never the story). As it grows wider the stage grows with it, taking the rows its narrower picture
didn't need from the story, which keeps at least STORY_WITH_STAGE. Each switch waits NUDGE columns or rows past its
line before it flips back, so dragging a window edge doesn't flicker (the iOS toolbar changes a phone's height by 3-4
rows).
"""

from __future__ import annotations

from dataclasses import dataclass

TWO_COLUMNS_AT = 88  # columns; below this, one column (unless it's a wide, short landscape screen)
LANDSCAPE = 2.5  # a screen this many times wider than tall keeps two columns, from LANDSCAPE_AT columns
LANDSCAPE_AT = 70
NUDGE = 2  # how far past a line the screen must go before the layout switches back (no flicker while dragging)
SIDE_MIN, SIDE_MAX = 30, 56  # the side column's width: it grows only once the stage has reached its cap
STAGE_CAP = 140  # the widest a room picture is drawn, in columns
STAGE_ROWS_CAP = 30
STAGE_SHAPE = 4.8  # columns per row: a room picture is about 2.4:1 in pixels, and a row is two pixels
STORY_MIN = 8  # the story's rows that nothing takes away
STORY_WITH_STAGE = {True: 12, False: 10}  # (two columns?) the story's rows when there's a stage too
STAGE_MIN = 6  # a stage shorter than this isn't worth showing
PAD_ROWS = 5  # the arrow pad, with its border
HERE_SHARE = 0.3  # of the rows between the choices and the ways out: what Here's strip keeps (one column)
COMPACT_BELOW = 30  # rows; a shorter screen drops the footer and the frames, and the command line is one row


@dataclass(frozen=True)
class Plan:
    columns: int
    rows: int
    two_columns: bool
    compact: bool  # a 1-row command line, no footer, a short status bar, a rule above each box instead of a frame
    touch: bool
    side: int  # the side column's width (two columns), else 0
    stage_rows: int  # 0: no stage
    stage_width: int
    choice_rows: int  # the most lines of choices shown at once (fewer when fewer will do)
    ways_rows: int  # the bar of ways out (one column), else 0
    here_rows: int  # what the Here strip (one column) or panel (two) may use, inside its box
    story_rows: int  # what's left for the story, inside its box (never under STORY_MIN)

    @property
    def edge(self) -> int:
        """Rows a box's frame takes: 1 for a rule above it (compact), 2 for a frame."""
        return 1 if self.compact else 2

    def describe(self) -> str:
        shape = "two columns" if self.two_columns else "one column"
        return (f"{self.columns}x{self.rows} · {shape}{' · compact' if self.compact else ''}"
                f"{' · touch' if self.touch else ''} · stage {self.stage_rows} · story {self.story_rows}+")


def make_plan(columns: int, rows: int, touch: bool = False, previous: Plan | None = None) -> Plan:
    """Share the screen out (see the module's docstring). `previous` is the plan it replaces, for the nudge."""
    line = TWO_COLUMNS_AT + (0 if previous is None else -NUDGE if previous.two_columns else NUDGE)
    two = columns >= line or (columns >= LANDSCAPE_AT and columns >= LANDSCAPE * rows)
    compact = not two or rows < COMPACT_BELOW
    edge = 1 if compact else 2
    avail = rows - 1 - (1 if compact else 3) - (0 if compact else 1)  # less the status bar, command line, footer
    if two:
        side = max(SIDE_MIN, min(SIDE_MAX, columns - STAGE_CAP - 4))
        left = columns - side
        choice_rows = 3 if rows >= 34 else 2
        ways, strip = 0, 0
    else:
        side, left = 0, columns
        choice_rows = 3 if rows >= 40 else 2
        ways = 3 if touch else 1
    main = avail - (choice_rows + 1) - ways  # (the choices have a rule above them, not a frame)
    if not two:
        strip = max(1, round(HERE_SHARE * main) - edge) + edge  # Here's strip: its share, and never under a line of chips
    width = min(STAGE_CAP, left - 2)
    wanted = min(STAGE_ROWS_CAP, round(width / STAGE_SHAPE))
    rest = main - strip - (STORY_MIN + edge)
    story_extra = max(0, round(0.4 * main) - STORY_MIN) if two else 0  # the story's fair share, when there's room
    least = STORY_WITH_STAGE[two] - STORY_MIN  # (a stage that would leave the story less than this, isn't shown)
    stage = min(wanted, rest - edge - max(story_extra, least))
    if stage < STAGE_MIN:
        stage = min(wanted, rest - edge - least)  # the story at its least, before the stage goes
    if stage < STAGE_MIN + (NUDGE if previous is not None and not previous.stage_rows else 0):
        stage = 0
    if stage and stage < wanted:
        width = min(width, round(stage * STAGE_SHAPE))  # a narrower picture, rather than bars beside it
    rest -= stage + edge if stage else 0
    if two:
        here, story = main - PAD_ROWS - edge, STORY_MIN + rest
    else:  # the strip keeps its share, and the story has the rest
        here, story = strip - edge, STORY_MIN + rest
    return Plan(columns, rows, two, compact, touch, side, stage, width if stage else 0, choice_rows, ways, here, story)
