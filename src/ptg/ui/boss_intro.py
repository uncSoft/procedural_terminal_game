"""A boss's entrance played big, in the middle of the whole screen, before the fight settles into the stage's strip.
The stage only has a strip of the screen, so a boss's clips (made up to 84 pixels tall: spikes/goblin3d) and the
room's art mostly play small. Here, as a fight with a boss (or a guardian) starts, the screen dims and the fight is
drawn as big as the screen allows (encounter.Fight at the screen's size: the room's own picture behind, every foe's
clips at their biggest): the boss drops in, its sting and its name called out on the card; it holds a moment, then
its entrance runs backwards (Fight.rise), up and away the way it came; and the screen gives way to the stage, where it
drops in again, quietly, small (game_screen._encounter). Any key or a click skips it.

It's on unless Settings says otherwise (Boss entrances: Config.boss_intros); PTG_BIG_INTRO=0 turns it off whatever
they say (the tests do), and =1 on.

    uv run ptg --test-room goblin_king
    uv run ptg --test-room humongous_fungus --loadout strong     # the Spore Bed, all four big
"""

from __future__ import annotations

import asyncio
import os
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import Static

from .. import encounter, sound
from .effects import paced

HOLD = 0.8  # seconds it stands, called out, before it goes back up
MARGIN = (4, 2)  # columns and rows left round it, so the game shows at its edges, dimmed


def wanted(config) -> bool:
    """Whether a boss comes in big: as Settings say (Config.boss_intros), unless PTG_BIG_INTRO says otherwise."""
    forced = os.environ.get("PTG_BIG_INTRO", "")
    return forced != "0" if forced in ("0", "1") else config.boss_intros


class BossIntro(ModalScreen[None]):
    """The big entrance over everything (see the module's docstring). Any key or a click skips it."""

    DEFAULT_CSS = """
    BossIntro {
        align: center middle;
        background: #070814 85%;
    }
    BossIntro #intro-art {
        width: auto;
        height: auto;
    }
    """
    BINDINGS: ClassVar = [Binding("escape,enter,space", "skip", "Skip", show=False)]

    def __init__(self, fight: encounter.Fight, side: int = 1) -> None:
        super().__init__()
        self.fight, self.side = fight, side
        self.skipped = False

    @classmethod
    def made(cls, state, content, monster, known: list[str], size, side: int = 1) -> BossIntro | None:
        """The intro at the screen's size, or None if the screen's no bigger than the stage would be anyway."""
        width, height = size.width - 2 * MARGIN[0], size.height - 2 * MARGIN[1]
        if width < 60 or height < 20:
            return None
        return cls(encounter.Fight(state, content, monster, width, height, known), side)

    def compose(self) -> ComposeResult:
        yield Static(id="intro-art")

    def on_mount(self) -> None:
        self.run_worker(self.play(), exclusive=True)

    async def play(self) -> None:
        art, fight = self.query_one("#intro-art", Static), self.fight
        async for frame, _, cue in paced(fight.entrance(self.side)):
            if self.skipped:
                break
            art.update(frame)
            if cue:
                sound.play(cue)
        if not self.skipped:
            await asyncio.sleep(HOLD)
        async for frame, _ in paced(fight.rise(self.side)):
            if self.skipped:
                break
            art.update(frame)
        self.dismiss()

    def action_skip(self) -> None:
        self.skipped = True

    def on_click(self) -> None:
        self.skipped = True
