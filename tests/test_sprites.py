from ptg.dice_art import DIGITS, FACE, GOLD, INK, SIZE, d20, die_image
from ptg.sprites import DEATH_FRAMES, frame_count, frames, posed, sprite_text
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


def test_missing_sprites_fall_back_to_ascii(content):
    assert sprite_text("no_such_monster") is None
    art = portrait("goblin", content, sprites=False)
    assert art.plain == content.monster("goblin").art


def test_fixtures_and_story_art_animate():
    expected = {"campfire": 3, "shrine": 3, "fountain": 3, "chest": 4, "stairs": 3, "mirror": 4, "sunglasses": 5}
    for key, count in expected.items():
        assert frame_count(key) == count, key
        assert len({frame.tobytes() for frame in frames(key)}) == count, key  # every frame is different


def test_sprites_need_not_be_square():
    assert frames("sunglasses")[0].size == (24, 12)
    assert len(sprite_text("sunglasses").plain.split("\n")) == 6
    assert frames("sunglasses", 12)[0].size == (12, 6)


def test_poses_change_the_picture():
    img = frames("goblin")[0]
    for pose in ("windup", "dizzy", "calm", "lunge", "shake"):
        assert posed(img, pose).tobytes() != img.tobytes(), pose
    assert posed(img, "windup", 0).tobytes() != posed(img, "windup", 1).tobytes()  # the glow pulses
    assert posed(img, "nonsense") is img


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


def test_dice_row_puts_dice_side_by_side():
    lines = dice_row([3, 18]).plain.split("\n")
    assert {len(line) for line in lines} == {2 * (SIZE + 2) + 2}
    assert dice_row([None]).plain == d20(None).plain


def test_dice_tumble_out_of_step_and_land_upright():
    landed = dice_row([4, 13]).plain.split("\n")
    assert landed == [a + "  " + b for a, b in zip(d20(4).plain.split("\n"), d20(13).plain.split("\n"))]
    tumbling = dice_row([4, 13], turn=0).plain.split("\n")
    assert tumbling != landed  # the second die is a quarter-turn ahead
