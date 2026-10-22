from ptg.sprites import frame_count, frames, sprite_text
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


def test_missing_sprites_fall_back_to_ascii(content):
    assert sprite_text("no_such_monster") is None
    art = portrait("goblin", content, sprites=False)
    assert art.plain == content.monster("goblin").art
