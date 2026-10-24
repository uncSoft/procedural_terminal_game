"""Hand-made small versions of sprites, and halving for the ones without."""

from dataclasses import replace

from PIL import Image

from ptg import sprites
from ptg.content import ItemDef
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


def test_items_nobody_has_drawn_get_a_grey_stand_in(content):
    """Not the old glyph, which looked like a broken picture next to the drawn ones."""
    from ptg import loot
    from ptg.ui.widgets import BLANKS, art_for, blank_art, item_words

    allowed = set(sprites.palette())
    for role in {loot.role(item) for item in content.items.values()} | set(BLANKS):
        design = BLANKS.get(role, BLANKS["trinket"])
        assert len(design) == sprites.SMALL and all(len(row) == sprites.SMALL for row in design), role
        art = blank_art(role)
        lines = art.plain.split("\n")
        assert len(lines) == sprites.SMALL // 2 and all(len(line) == sprites.SMALL for line in lines), role
        colours = {tuple(c.triplet) for s in art.spans for c in (s.style.color, s.style.bgcolor) if c is not None}
        assert colours and colours <= allowed, role  # greys the GPU terminal has already cached
    roast = ItemDef(key="roast_boar", name="Roast Boar", kind="consumable", heal=12, tier=2, tags=["food"])
    content = replace(content, items={**content.items, "roast_boar": roast})  # nobody has drawn it
    for size in (sprites.DEFAULT_WIDTH, sprites.SMALL):  # at either size, like a drawn one
        art = art_for("roast_boar", "item", content, size)
        assert art.blank and not art.sprite and art.still.plain == blank_art("food", size).plain
        assert (art.columns, art.rows) == (size, size // 2)
    glyph = art_for("roast_boar", "item", content, sprites=False)  # ASCII art: its glyph, as tall as its picture
    assert glyph.still.plain.strip() == "!" and glyph.rows == sprites.DEFAULT_WIDTH // 2
    words = item_words(content, "roast_boar", "heals 12")
    assert not words.style and words.plain == "Roast Boar\n\nheals 12"  # (a name on up to two lines)
