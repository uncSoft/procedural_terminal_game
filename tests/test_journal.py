"""The journal (game.journal_lines, ui/panels.py JournalScreen): what happened, each roll with its bonuses and what
came of it, and everything that changed hands; a name in it opens its card."""

from test_ui import into_a_run, settle
from ptg import dice, testrooms
from ptg.config import Config
from ptg.game import journal_lines
from ptg.rules import perform
from ptg.ui.app import PTGApp
from ptg.ui.panels import InfoScreen, JournalScreen
from ptg.ui.widgets import StoryLine


def test_a_gift_that_worked_is_written_down_with_its_roll(content, monkeypatch):
    """Giving Stale Bread to a hobgoblin is a wits check, a kind the journal skipped, so the gift went unrecorded."""
    monkeypatch.setattr(dice, "d20", lambda rng: 20)
    state = testrooms.build(content, "hobgoblin", "new", seed=3)
    room = testrooms.target(state)
    state.room_id, room.visited = room.id, True
    state.player.inventory.append("stale_bread")
    lines = journal_lines(perform(state, content, "give:stale_bread@monster:hobgoblin"))
    assert lines[0].startswith("⚄ ") and "wits" in lines[0]
    assert any("Stale Bread" in line and not line.startswith("⚄") for line in lines)
    assert any("Fate" in line for line in lines)  # (a natural 20: the Fate it won is written down too)


async def test_a_name_in_the_journal_opens_its_card_and_what_you_do_there_is_your_turn():
    app = PTGApp(Config(backend="offline", player_name="T"), seed=1)
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        state.room.monster = None
        state.player.inventory.append("war_pick")
        state.journal.append("You found the War Pick under a pew.")
        await pilot.press("f7")
        await pilot.pause(0.3)
        journal = app.screen
        assert isinstance(journal, JournalScreen)
        terms = {span.style.meta.get("term") for line in journal.query(StoryLine)
                 for span in line.render().spans if getattr(span.style, "meta", None)}
        assert "item:war_pick" in terms
        journal.action_lookup("item:war_pick")
        await pilot.pause(0.3)
        assert isinstance(app.screen, InfoScreen) and app.screen.action_id == "equip:war_pick"
        await pilot.press("enter")
        await settle(app, pilot)
        assert state.player.weapon == "war_pick"
