import warnings

import pytest
from PIL import Image

from ptg.dice_art import CRIMSON, DIGITS, EDGE, FACE, GOLD, INK, LIT, OUTLINE, SHADED, SIZE, d20, die_image
from ptg.library import data_folder, read_frames
from ptg.sprites import (DEATH_FRAMES, DEFAULT_WIDTH, SMALL, SPENT, count_frames, engrave, frame_count, frames,
                         idle_frames, palette, posed, splash, splash_sizes, splash_text, sprite_text)
from ptg.ui.dice import dice_row
from ptg.ui.widgets import portrait


def test_every_monster_has_an_animated_sprite(content):
    for key in content.monsters:
        assert frame_count(key) >= 2, key
    assert frame_count("campfire") == 3


def test_half_blocks_pack_two_pixels_per_cell():
    text = sprite_text("goblin")
    lines = text.plain.split("\n")
    assert len(lines) == 12 and all(len(line) == 24 for line in lines)
    assert set(text.plain) <= {"▀", "▄", " ", "\n"}


def test_frames_differ_and_flash_changes_colours():
    assert sprite_text("goblin", 0).plain != sprite_text("goblin", 1).plain
    normal, flashed = sprite_text("troll"), sprite_text("troll", flash=True)
    assert normal.plain == flashed.plain and normal.spans != flashed.spans


def test_sprites_scale_to_any_width():
    assert frames("goblin", 12)[0].size == (12, 12)
    assert len(sprite_text("goblin", width=12).plain.split("\n")) == 6


def test_norfel_has_splash_art_in_every_size_its_card_draws():
    """Its card's picture (data/splash/norfel/, made by tools/make_splash.py), widest first, every size in whole rows
    of cells and in the sprites' own colours (a terminal caches each pair of colours it meets)."""
    sizes = splash_sizes("norfel")
    assert sizes[0] == (160, 90) and len(sizes) >= 3
    assert [w for w, _ in sizes] == sorted((w for w, _ in sizes), reverse=True)
    colours = set(palette())
    for width, height in sizes:
        art = splash("norfel", width)
        assert art.size == (width, height) and height % 2 == 0
        assert {pixel[:3] for pixel in art.get_flattened_data()} <= colours
    assert splash_sizes("no_such_floor") == () and splash("no_such_floor", 64) is None


def test_splash_art_shrinks_to_a_size_it_doesnt_come_in():
    art = splash("norfel", 50)  # (from the next size up, 64)
    assert art.size == (50, 28) and {pixel[:3] for pixel in art.get_flattened_data()} <= set(palette())
    text = splash_text("norfel", 50)
    assert len(text.plain.split("\n")) == 14 and set(text.plain) <= {"▀", "\n"}
    assert splash("norfel", 400) is None  # (never drawn bigger than it was made)


def test_missing_sprites_fall_back_to_ascii(content):
    assert sprite_text("no_such_monster") is None
    art = portrait("goblin", content, sprites=False)
    assert art.plain == content.monster("goblin").art


def test_fixtures_and_story_art_animate():
    expected = {"campfire": 3, "shrine": 4, "fountain": 3, "chest": 5, "stairs": 3, "mirror": 4, "sunglasses": 5,
                "tombstone": 1, "crown": 5}
    for key, count in expected.items():
        assert frame_count(key) == count, key
        assert len({frame.tobytes() for frame in frames(key)}) == count, key  # every frame is different


def solid_rows(img) -> list[int]:
    return [sum(1 for x in range(img.width) if img.getpixel((x, y))[3]) for y in range(img.height)]


def brightness(img, rows) -> float:
    pixels = [img.getpixel((x, y)) for y in rows for x in range(img.width) if img.getpixel((x, y))[3]]
    return sum(0.3 * r + 0.59 * g + 0.11 * b for r, g, b, _ in pixels) / len(pixels)


def test_the_stairs_go_down_into_the_dark():
    """Wide, lit steps nearest you at the bottom, narrowing into the dark at the top: not a funnel."""
    for img in frames("stairs"):
        widths = solid_rows(img)
        top, bottom = range(0, img.height // 2), range(img.height // 2, img.height)
        assert max(widths[y] for y in bottom) > max(widths[y] for y in top)
        assert widths.index(max(widths)) >= img.height // 2
        assert brightness(img, bottom) > brightness(img, top)


def test_used_up_fixtures_look_it():
    """The last frame of a chest is it emptied (only the lock is gold), of a shrine its candles snuffed out; neither
    is part of the idle animation."""
    gold = {(254, 231, 97), (254, 174, 52)}
    flame = {(247, 118, 34), (254, 231, 97), (254, 174, 52)}

    def count(img, colours):
        return sum(1 for pixel in img.get_flattened_data() if pixel[3] and pixel[:3] in colours)

    closed, *_, opened, sparkling, emptied = frames("chest")
    assert count(emptied, gold) == count(closed, gold) < count(opened, gold)
    *lit, out = frames("shrine")
    assert count(out, flame) == 0 and all(count(frame, flame) for frame in lit)
    assert SPENT == ("chest", "shrine")
    assert idle_frames("chest") == [0, 1, 2, 3] and idle_frames("shrine") == [0, 1, 2]
    assert idle_frames("fountain") == [0, 1, 2] and idle_frames("tombstone") == [0]
    assert idle_frames("goblin") == [0, 1] and idle_frames("no_such_sprite") == [0]


def test_every_strip_stores_its_frame_count():
    """Frames are 24 pixels wide (12 small), and each PNG says how many it holds, so none is cut in the wrong place."""
    folder = data_folder() / "sprites"
    for path in sorted(folder.rglob("*.png")):
        size = SMALL if path.parent.name == "small" else DEFAULT_WIDTH
        with Image.open(path) as sheet:
            assert sheet.info.get("frames"), f"{path.name}: no frame count stored"
            assert int(sheet.info["frames"]) * size == sheet.width, f"{path.name}: {sheet.width} wide"


def test_a_strip_that_lost_its_frame_count_is_still_cut_right(tmp_path):
    """Picture editors drop the PNG's text when they save: the non-square strips still split into 24-pixel frames."""
    folder = data_folder() / "sprites"
    for key in ("stairs", "chest", "shrine", "fountain", "sunglasses", "crown"):
        bare = tmp_path / f"{key}.png"
        with Image.open(folder / f"{key}.png") as sheet:
            sheet.save(bare)  # no pnginfo: the "frames" text is gone
        with Image.open(bare) as sheet:
            assert "frames" not in sheet.info
        assert [f.tobytes() for f in read_frames(bare)] == [f.tobytes() for f in frames(key)], key
    blank = Image.new("RGBA", (24, 12))
    assert count_frames(blank, small=True) == 2 and count_frames(blank) == 1
    assert count_frames(Image.new("RGBA", (64, 32))) == 2  # art taller than a frame: square frames
    assert count_frames(Image.new("RGBA", (32, 16))) == 2
    with pytest.warns(UserWarning, match="frames can't be told apart"):
        assert count_frames(Image.new("RGBA", (50, 16)), name="odd.png") == 3
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        count_frames(Image.new("RGBA", (72, 16)))


def test_words_carved_into_a_picture():
    stone = Image.new("RGBA", (24, 8), (139, 155, 180, 255))
    text = engrave(stone, {1: "R.I.P.", 2: "Sir Reginald Pumpernickel", 9: "off the stone"})
    lines = text.plain.split("\n")
    assert len(lines) == 4 and {len(line) for line in lines} == {24}
    assert lines[1] == "▀" * 9 + "R.I.P." + "▀" * 9
    assert lines[2] == "Sir Reginald Pumpernickel"[:24]
    allowed = set(palette())
    for span in text.spans:
        for colour in (span.style.color, span.style.bgcolor):
            assert colour is None or tuple(colour.triplet) in allowed


def test_the_tombstone_and_crown_are_pixel_art():
    from ptg.ui.hub import tombstone

    stone = tombstone("Tester", 3)
    lines = stone.plain.split("\n")
    assert "R.I.P." in lines[2] and "Tester" in lines[4] and "floor 3" in lines[5]
    assert {len(line) for line in lines} == {DEFAULT_WIDTH}
    assert "Sir Reginald P" in tombstone("Sir Reginald Pumpernickel", 1).plain  # cut to fit, as the ASCII one was
    assert sprite_text("crown") is not None and frame_count("crown") > 1  # the crown glints


def test_sprites_need_not_be_square():
    assert frames("sunglasses")[0].size == (24, 12)
    assert len(sprite_text("sunglasses").plain.split("\n")) == 6
    assert frames("sunglasses", 12)[0].size == (12, 6)


def test_poses_change_the_picture():
    img = frames("goblin")[0]
    for pose in ("windup", "dizzy", "lunge", "shake"):
        assert posed(img, pose).tobytes() != img.tobytes(), pose
    assert posed(img, "windup", 0).tobytes() != posed(img, "windup", 1).tobytes()  # the glow pulses
    assert posed(img, "nonsense") is img


def test_characters_are_always_in_their_own_colours():
    """Calm used to turn a sprite five shades of grey (it was made for a pacified monster), so Lucky Lenny and every
    friendly character turned up as a stone statue. Calm is the sprite just as it is."""
    for key in ("lucky_lenny", "swoogy_the_gooey", "goblin"):
        img = frames(key)[0]
        assert posed(img, "calm") is img
        assert sprite_text(key, pose="calm") == sprite_text(key)


def test_death_dissolves_to_nothing():
    img = frames("troll")[0]
    solid = [sum(1 for pixel in posed(img, "death", step).get_flattened_data() if pixel[3]) for step in range(DEATH_FRAMES)]
    assert solid[0] > 0 and solid[-1] == 0
    assert solid == sorted(solid, reverse=True)
    assert posed(img, "death", 0).tobytes() == img.tobytes()  # a beat, whole, before it goes
    assert sprite_text("troll", 0, pose="death").plain != sprite_text("troll", 1, pose="death").plain


def ink(img) -> list[tuple[int, int]]:
    return [(x, y) for y in range(img.height) for x in range(img.width) if img.getpixel((x, y))[:3] == INK]


def test_the_d20_shows_every_number_on_its_face():
    for value in [*range(1, 21), None]:
        img = die_image(value)
        label = "?" if value is None else str(value)
        assert len(ink(img)) == sum(row.count("1") for ch in label for row in DIGITS[ch]), value
        for x, y in ink(img):  # the digits sit on the light face, clear of the edges
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                assert img.getpixel((nx, ny))[:3] in (INK, FACE), (value, x, y)


def test_the_d20_tumbles_bounces_glows_and_greys():
    plain = die_image(7)
    assert die_image(7, turn=1).tobytes() != plain.tobytes()
    assert die_image(7, bounce=2).getbbox()[1] == plain.getbbox()[1] - 2
    assert GOLD not in [p[:3] for p in plain.get_flattened_data()]
    assert GOLD in [p[:3] for p in die_image(20, glow=GOLD).get_flattened_data()]
    assert FACE not in [p[:3] for p in die_image(7, dim=True).get_flattened_data()]
    lines = d20(7).plain.split("\n")
    assert len(lines) == (SIZE + 3) // 2 and {len(line) for line in lines} == {SIZE + 2}


def test_the_d20_keeps_to_a_few_fixed_colours():
    """A GPU terminal's glyph cache only meets a fixed few colours (see sprites.palette), whatever the die shows and
    however it's turned, raised, lit or greyed; and they are the die's own, not snapped to the sprites' greys."""
    seen = set()
    for value in (*range(1, 21), None):
        for turn in range(4):
            for bounce in (0, 2):
                for glow in (None, GOLD, CRIMSON):
                    for dim in (False, True):
                        drawn = {p[:3] for p in die_image(value, turn, bounce, glow, dim).get_flattened_data() if p[3]}
                        shown = {tuple(colour.triplet) for span in d20(value, turn, bounce, glow, dim).spans
                                 for colour in (span.style.color, span.style.bgcolor) if colour}
                        assert shown == drawn, (value, turn, bounce, glow, dim)
                        seen |= drawn
    assert {FACE, LIT, SHADED, EDGE, OUTLINE, INK, GOLD, CRIMSON} <= seen
    assert len(seen) <= 26


def test_dice_row_puts_dice_side_by_side():
    lines = dice_row([3, 18]).plain.split("\n")
    assert {len(line) for line in lines} == {2 * (SIZE + 2) + 2}
    assert dice_row([None]).plain == d20(None).plain


def test_dice_tumble_out_of_step_and_land_upright():
    landed = dice_row([4, 13]).plain.split("\n")
    assert landed == [a + "  " + b for a, b in zip(d20(4).plain.split("\n"), d20(13).plain.split("\n"))]
    tumbling = dice_row([4, 13], turn=0).plain.split("\n")
    assert tumbling != landed  # the second die is a quarter-turn ahead
