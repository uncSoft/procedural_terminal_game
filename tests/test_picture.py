"""Picture: the one way an item, a character or a fixture is drawn, wherever it's shown (ui/widgets.py)."""

from rich.text import Text
from textual.app import App
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from ptg import sprites
from ptg.sprites import DEFAULT_WIDTH, SMALL
from ptg.ui.widgets import FLICKER, IDLE, Picture, PictureClock, art_for, monster_how, monster_status, status_rows


def test_full_size_whenever_it_fits(content):
    """24 pixels wide when the space is 24 columns or more and as many rows as it is tall; 12 only when it isn't."""
    full = art_for("healing_potion", "item", content, max_w=24, max_h=12)
    assert (full.sprite, full.pixels, full.columns, full.rows) == ("item_healing_potion", DEFAULT_WIDTH, 24, 12)
    assert art_for("healing_potion", "item", content, max_w=80).pixels == DEFAULT_WIDTH  # (no limit on its height)
    for too_small in ({"max_w": 23}, {"max_w": 24, "max_h": 11}):
        small = art_for("healing_potion", "item", content, **too_small)
        assert (small.pixels, small.columns, small.rows) == (SMALL, 12, 6), too_small
    chest = art_for("chest", "", content, max_w=24, max_h=8)  # a fixture is 16 pixels tall: 8 rows
    assert (chest.pixels, chest.rows) == (DEFAULT_WIDTH, 8)
    assert art_for("chest", "", content, max_w=24, max_h=7).rows == 4
    assert art_for("goblin", "monster", content).rows == 12


def test_small_is_the_hand_made_version_or_else_the_big_one_halved(content):
    hand_made = Picture("healing_potion", "item", SMALL, content=content, sprites=True)
    assert sprites.has_small("item_healing_potion")
    assert hand_made.frame_text(0) == sprites.image_text(sprites._strip("item_healing_potion", small=True)[0],
                                                         snap=True)
    halved = Picture("goblin", "monster", SMALL, content=content, sprites=True)  # (every item has a small now)
    assert not sprites.has_small("goblin")
    assert halved.frame_text(0) == sprites.image_text(sprites.halve(sprites.frames("goblin")[0]), snap=True)


def test_without_a_sprite_a_stand_in(content):
    """An item nobody has drawn gets its kind's grey stand-in; with sprites off, the ASCII art: a monster's own, an
    item's glyph as tall as its picture would be, or whatever's given (the campfire's)."""
    monster = art_for("goblin", "monster", content, sprites=False, style="#ffd166")
    assert not monster.sprite and monster.still.plain == content.monster("goblin").art
    assert monster.rows == len(content.monster("goblin").art.split("\n"))
    glyph = art_for("rusty_sword", "item", content, max_w=SMALL, sprites=False)
    assert glyph.still.plain.strip() == ")" and glyph.rows == SMALL // 2
    fire = art_for("campfire", ascii=Text("(  )"), sprites=False)
    assert fire.still.plain == "(  )" and (fire.columns, fire.rows) == (4, 1)
    assert art_for("", "monster", content) == art_for("") and not art_for("").sprite  # nothing (yet)


def test_a_story_sprite_falls_back_as_what_it_is(content):
    assert art_for("item_rusty_sword", "", content).sprite == "item_rusty_sword"
    assert art_for("goblin", "", content, sprites=False).still.plain == content.monster("goblin").art


class Pictures(App):
    """A bare app to put pictures in."""

    CSS = "#column { width: 20; height: auto; } #scroll { height: 8; }"

    def __init__(self, *pictures: Picture, scrolled: Picture | None = None) -> None:
        super().__init__()
        self.pictures, self.scrolled = pictures, scrolled

    def compose(self):
        with Vertical(id="column"):
            yield from self.pictures
        if self.scrolled is not None:
            with VerticalScroll(id="scroll"):
                yield Static("\n" * 20)
                yield self.scrolled


async def test_a_picture_never_wraps_in_a_narrow_column(content):
    """The shop drew its wares into wrapping text: in a 20-column column each 24-cell row of art wrapped into
    stripes, twice as tall, and pushed the price and Buy off the bottom. A picture of its own is cropped instead."""
    picture = Picture("bag_of_marbles", "item", 24, content=content, sprites=True)
    async with Pictures(picture).run_test(size=(60, 30)) as pilot:
        await pilot.pause()
        assert picture.size == (20, 12)  # cropped to the column, as tall as the art
        assert all(len(picture.render_line(y).text) <= 20 for y in range(picture.size.height))
        art = sprites.sprite_text("item_bag_of_marbles").plain.split("\n")
        assert [picture.render_line(y).text for y in range(12)] == [line[:20] for line in art]


async def test_one_clock_moves_every_picture_in_sight(content):
    goblin = Picture("goblin", "monster", content=content, sprites=True)
    potion = Picture("healing_potion", "item", content=content, sprites=True)
    fire = Picture("campfire", flicker=True, sprites=True)
    hidden = Picture("troll", "monster", content=content, sprites=True)  # scrolled out of sight
    app = Pictures(goblin, potion, fire, scrolled=hidden)
    async with app.run_test(size=(60, 40)) as pilot:
        await pilot.pause()
        clock = PictureClock.of(app)
        assert clock.pictures == {goblin, potion, fire, hidden} and clock.timer is not None  # one timer for them all
        seen = {picture: set() for picture in (goblin, potion, fire, hidden)}
        for _ in range(round(2 * IDLE / FLICKER) + 2):
            await pilot.pause(FLICKER)
            for picture, frames in seen.items():
                frames.add(picture.index)
        assert seen[goblin] == seen[potion] == {0, 1} and len(seen[fire]) == 3  # (flames flicker faster)
        assert seen[hidden] == {0}  # nothing to see, nothing drawn

        app.push_screen(ModalScreen())  # a panel in front: what's behind it waits
        await pilot.pause()
        index = goblin.index
        await pilot.pause(2 * IDLE)
        assert goblin.index == index
        app.pop_screen()

        goblin.freeze()
        assert goblin not in clock.pictures
        await goblin.play([(0, "idle", True), (1, "lunge", False), (0, "death", False)], delay=0.01)
        assert goblin.content == sprites.sprite_text("goblin", 0, pose="death")  # it stays on the last step
        goblin.resume()
        assert goblin in clock.pictures and clock.interval == FLICKER
        for picture in (fire, hidden):
            await picture.remove()
        assert clock.interval == IDLE and clock.timer is not None  # nothing flickers now: it ticks at the idle pace
        seen = set()
        for _ in range(4):
            await pilot.pause(IDLE / 2)
            seen.add(goblin.index)
        assert seen == {0, 1}
        await potion.remove()
        goblin.freeze()
        assert not clock.pictures and clock.timer is None  # nothing to move: no ticks at all


async def test_a_picture_keeps_its_height_whatever_it_shows(content):
    """A pose, a flash or a dissolve never changes its size; becoming something else takes that one's."""
    goblin = Picture("goblin", "monster", content=content, sprites=True)
    async with Pictures(goblin).run_test(size=(60, 40)) as pilot:
        await pilot.pause()
        heights = set()
        for pose in ("idle", "windup", "dizzy", "lunge", "shake", "death"):
            goblin.set_pose(pose)
            await goblin.play([(frame, pose, flash) for frame in range(3) for flash in (False, True)], delay=0)
            await pilot.pause()
            heights.add(goblin.outer_size.height)
        assert heights == {12}
        goblin.become("chest", "")
        await pilot.pause()
        assert goblin.outer_size.height == 8 and goblin.loop == sprites.idle_frames("chest")
        goblin.fit(20)  # too narrow for full size now
        await pilot.pause()
        assert goblin.cells == (12, 4) and goblin.outer_size.height == 4


def test_the_sidebar_says_how_a_monster_is_in_the_same_number_of_lines(content):
    """The monster card ended with a status line, but the frames of a fight didn't: the panel jumped a row (three,
    with the heavy-blow warning wrapping) every time anything was hit."""
    from conftest import put_monster

    from ptg.world import generate

    state = generate(1)
    monster = put_monster(state, content, key="goblin")
    lines = set()
    for change in ({}, {"hostile": False}, {"stunned": True}, {"intent": "heavy"}, {"guarding": True}):
        for field, value in {"hostile": True, "stunned": False, "intent": "strike", "guarding": False,
                             **change}.items():
            setattr(monster, field, value)
        text = monster_status(state, content, "goblin")
        assert all(len(line) <= 27 for line in text.plain.split("\n")), change  # (the sidebar's width)
        assert monster_how(state, "goblin").plain in text.plain
        lines.add(len(text.plain.split("\n")))
        short = monster_status(state, content, "goblin", short=True)  # (on a tiny screen how it is goes on the frame)
        assert len(short.plain.split("\n")) == status_rows(state, short=True) == 1, change
    state.room.monster = None
    lines.add(len(monster_status(state, content, "goblin").plain.split("\n")))  # gone: dissolving
    assert lines == {status_rows(state)} == {2}
    state.player.blessings.append("lorekeeper")
    assert len(monster_status(state, content, "goblin").plain.split("\n")) == status_rows(state) == 3
