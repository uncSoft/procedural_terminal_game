"""Python's garbage collector, kept out of the frames' way.

A fight's stage draws 24 frames a second, and every one makes and drops a heap of Rich and Textual objects. Left as it
comes, the collector swept everything the game holds about twice a second on run 66's floor 5, 40-80 ms each time
(more as a run's heap grows), holding the screen's thread, so animations stuttered, and the sound's, so the speakers
ran dry and sounds clipped (sound.Mixer keeps only LEAD seconds queued). So: young sweeps far less often, the whole heap
almost never, and what lasts (the game's content, its clips, the floor) frozen out of the collector's sight once it's
loaded, after one sweep at a pause (a new floor's card).

PTG_GC=0 leaves the collector as Python has it (the tests do: they start hundreds of games in one process).
"""

from __future__ import annotations

import gc
import os

THRESHOLDS = (10_000, 50, 1_000)  # Python's own are (700, 10, 10)


def tuned() -> bool:
    return os.environ.get("PTG_GC", "1") != "0"


def tune() -> None:
    """The collector's thresholds raised, once, as the game starts."""
    if tuned():
        gc.set_threshold(*THRESHOLDS)


def freeze() -> None:
    """What's alive now set aside where the collector never looks: after the clips are read ahead (a moment's work,
    no sweep: one would hold everything up)."""
    if tuned():
        gc.freeze()


def settle() -> None:
    """One sweep of what's come and gone since the last, then what's left frozen: at a pause (a new floor's card)."""
    if tuned():
        gc.collect()
        gc.freeze()
