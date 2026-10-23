"""Hand-made small versions of sprites, and halving for the ones without."""

from PIL import Image

from ptg import sprites
from ptg.library import data_folder


def test_items_drawn_small_use_their_hand_made_version():
    small = sprites.frames("item_healing_potion", sprites.SMALL)
    assert sprites.has_small("item_healing_potion")
    assert small == sprites._strip("item_healing_potion", small=True)  # the very pixels, not a shrunk copy
    assert small[0].size == (12, 12) and len(small) == sprites.frame_count("item_healing_potion")
    assert sprites.frames("item_healing_potion")[0].size == (24, 24)  # full size is unchanged


def test_every_small_version_fits_its_sprite():
    folder = data_folder() / "sprites"
    for path in sorted((folder / "small").glob("*.png")):
        assert (folder / path.name).is_file(), f"{path.name} has no full-size sprite"
        small = sprites._strip(path.stem, small=True)
        assert all(frame.size == (sprites.SMALL, sprites.SMALL) for frame in small), path.name
        assert len(small) == sprites.frame_count(path.stem), f"{path.name}: not as many frames as the sprite"


def test_halving_keeps_thin_lines_and_colour():
    img = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
    for i in range(24):  # a one-pixel diagonal in a light colour, with a near-black outline beside it
        img.putpixel((i, 23 - i), (200, 200, 220, 255))
        if i < 23:
            img.putpixel((i + 1, 23 - i), (24, 20, 37, 255))
    half = sprites.halve(img)
    assert half.size == (12, 12)
    for y in range(12):  # the old way (every other pixel) left gaps; now each row keeps its piece of the line
        row = [half.getpixel((x, y)) for x in range(12)]
        assert any(p[3] and p[:3] == (200, 200, 220) for p in row), f"row {y} lost the line"
    assert half.getpixel((0, 0))[3] == 0  # see-through stays see-through


def test_effects_keep_to_the_colours_the_sprites_use():
    """A GPU terminal caches every character in every pair of colours: made-up shades would fill it."""
    allowed = set(sprites.palette())
    for key in ("goblin", "troll", "thornmother", "item_healing_potion"):
        seen = set()
        for pose in ("idle", "windup", "dizzy", "calm", "lunge", "shake", "death"):
            for frame in range(4):
                for flash in (False, True):
                    text = sprites.sprite_text(key, frame, flash=flash, pose=pose)
                    for span in text.spans:
                        for colour in (span.style.color, span.style.bgcolor):
                            if colour is not None:
                                seen.add(tuple(colour.triplet))
        assert seen <= allowed, f"{key}: {seen - allowed}"
