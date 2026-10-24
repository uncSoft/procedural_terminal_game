"""The kids' creations and the shopkeepers, touched up: outlined and inside their frames like the game's own sprites,
in the maker's palette, big enough to read, with small versions that match."""

from PIL import Image

from ptg import sprites
from ptg.library import data_folder, off_palette

# Monsters touched up here (an outline, pulled in off the frame's edges) or redrawn (the shopkeepers and the rat king)
OUTLINED = ("palp_guard", "lucky_lenny", "swoogy_the_gooey", "baby_joey", "king_mouse", "swamp_bottoms",
            "granny_gristle", "granny_kamultruk", "rat_king")
# Sprites whose custom colours were tidied into the maker's palette (the hard hat keeps its lamp's two)
TIDIED = ("swoogy_the_gooey", "palp_guard", "lucky_lenny", "granny_gristle", "granny_kamultruk", "rat_king",
          "item_unusual_butter", "item_swoogy_s_diaper", "item_lenny_s_good_tooth", "item_lenny_s_bad_tooth",
          "item_pizza_rat", "item_davy_j_skull")
LAMP_ON, LAMP_DIM = (0xfb, 0xff, 0x00), (0xa5, 0xa8, 0x1a)
INK = (24, 20, 37)


def light(pixel: tuple) -> float:
    r, g, b = pixel[:3]
    return 0.3 * r + 0.59 * g + 0.11 * b


def colours(frames) -> set:
    return {pixel[:3] for frame in frames for pixel in frame.get_flattened_data() if pixel[3] >= 128}


def test_the_touched_up_monsters_have_a_dark_outline_inside_the_frame():
    """Swoogy and friends were drawn to the frame's edge with coloured edges; every other sprite has a dark outline."""
    for key in OUTLINED:
        for n, frame in enumerate(sprites._strip(key)):
            px, (w, h) = frame.load(), frame.size
            for y in range(h):
                for x in range(w):
                    if px[x, y][3] < 128:
                        continue
                    edge = any(not (0 <= x + dx < w and 0 <= y + dy < h) or px[x + dx, y + dy][3] < 128
                               for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
                    assert not edge or light(px[x, y]) < sprites.OUTLINE, f"{key} frame {n}: ({x}, {y}) isn't outline"


def test_the_shopkeepers_and_the_rat_king_are_drawn_in_few_colours():
    """They were 24, 20 and 16 colours of noise at game size; about ten reads as a face."""
    for key in ("granny_gristle", "granny_kamultruk", "rat_king"):
        assert len(colours(sprites._strip(key))) <= 11, key


def test_the_kids_colours_are_the_makers():
    for key in TIDIED:
        assert off_palette(list(sprites._strip(key))) == [], key
        if sprites.has_small(key):
            assert off_palette(list(sprites._strip(key, small=True))) == [], f"small {key}"
    assert set(off_palette(list(sprites._strip("item_hard_hat")))) == {"#fbff00", "#a5a81a"}  # the lamp, on purpose


def test_quest_rewards_and_little_things_fill_their_frames():
    """Davy J's Skull was 10 pixels in 24, Pizza Rat a strip along the bottom; Lenny's teeth looked like gamepads."""
    for key in ("item_davy_j_skull", "item_pizza_rat", "item_lenny_s_good_tooth", "item_lenny_s_bad_tooth"):
        assert sprites.fill(key) >= 0.5, key
    for frame in sprites._strip("item_pizza_rat"):  # its walk doesn't run off the edge any more
        left, top, right, bottom = frame.getbbox()
        assert top >= 4 and bottom <= 23
    assert sprites.fill("no_such_sprite") == 0
    assert 0.3 < sprites.fill("item_torch") < 0.5  # a torch is thin, and that's fine: the Art tab only points it out


def test_lennys_teeth_and_pizza_rat_have_small_versions():
    for key in ("item_lenny_s_good_tooth", "item_lenny_s_bad_tooth", "item_pizza_rat"):
        assert sprites.has_small(key), key
        assert sprites.frames(key, sprites.SMALL) == sprites._strip(key, small=True)  # drawn, not halved


def test_small_versions_match_their_sprites():
    for key in ("item_lenny_s_good_tooth", "item_lenny_s_bad_tooth", "item_pizza_rat", "item_hard_hat",
                "item_weighted_dice", "item_unusual_butter", "item_swoogy_s_diaper", "item_davy_j_skull"):
        assert colours(sprites._strip(key, small=True)) <= colours(sprites._strip(key)), key
    skull, small_skull = sprites._strip("item_davy_j_skull"), sprites._strip("item_davy_j_skull", small=True)
    assert sprites.fill("item_davy_j_skull", sprites.SMALL) >= 0.5  # the 6x6 skull drawn for the old picture is gone

    def open_eyes(frame, row, xs):
        return tuple(frame.getpixel((x, row))[:3] == INK for x in xs)

    for big, small in zip(skull, small_skull):  # it winks the same eye at both sizes, one eye and then the other
        assert open_eyes(big, 9, (6, 17)) == open_eyes(small, 4, (3, 8))
    assert {open_eyes(frame, 4, (3, 8)) for frame in small_skull} == {(True, False), (False, True)}


def test_no_small_version_is_emptier_than_its_sprite():
    """A small version is the big picture redrawn, so it takes up about as much of its tile; one drawn for an older,
    smaller picture (as Davy J's Skull's was) looks lost in it."""
    for path in sorted((data_folder() / "sprites" / "small").glob("*.png")):
        assert sprites.fill(path.stem, sprites.SMALL) >= 0.75 * sprites.fill(path.stem), path.name
    hat, small_hat = sprites._strip("item_hard_hat"), sprites._strip("item_hard_hat", small=True)
    for big, small, lamp in zip(hat, small_hat, (LAMP_ON, LAMP_DIM)):  # the lamp blinks at both sizes
        assert lamp in colours([big]) and lamp in colours([small])
    for frame in sprites._strip("item_weighted_dice", small=True):  # a 5 and a 6, as on the big dice
        assert sum(pixel[:3] == INK for pixel in frame.get_flattened_data()) == 11


def bob(frame: Image.Image, feet: int = 5) -> Image.Image:
    """The game's idle frame (tools/build_sprites.bob): everything above the bottom `feet` rows sinks a pixel."""
    out = frame.copy()
    top = frame.height - feet
    out.paste((0, 0, 0, 0), (0, 0, frame.width, top + 1))
    out.alpha_composite(frame.crop((0, 0, frame.width, top)), (0, 1))
    out.alpha_composite(frame.crop((0, top, frame.width, frame.height)), (0, top))
    return out


def sealed(frame: Image.Image) -> Image.Image:
    """Outline added only where colour meets see-through: the gap a bob opens where the body sinks onto its feet."""
    out, px, (w, h) = frame.copy(), frame.load(), frame.size
    for y in range(h):
        for x in range(w):
            if px[x, y][3] < 128 and any(0 <= x + dx < w and 0 <= y + dy < h and px[x + dx, y + dy][3] >= 128
                                         and px[x + dx, y + dy][:3] != INK
                                         for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                out.putpixel((x, y), (*INK, 255))
    return out


def lone_ink(frame: Image.Image) -> int:
    """Outline pixels with no colour round them, even corner to corner: a second dark ring outside the first."""
    px, (w, h) = frame.load(), frame.size
    return sum(1 for y in range(h) for x in range(w) if px[x, y][3] >= 128 and px[x, y][:3] == INK
               and not any(0 <= x + dx < w and 0 <= y + dy < h and px[x + dx, y + dy][3] >= 128
                           and px[x + dx, y + dy][:3] != INK for dx in (-1, 0, 1) for dy in (-1, 0, 1)))


def test_idle_frames_are_outlined_once():
    """The redrawn idle frames were outlined again after the bob, so a dark halo pulsed round them on every tick.
    They're the outlined picture sunk a pixel with the feet planted (Palp Guard's robe gets four pixels of outline
    where it meets his shoes), and no idle frame anywhere grows a ring."""
    for key in ("granny_gristle", "granny_kamultruk", "palp_guard"):
        first, idle = sprites._strip(key)
        assert idle.tobytes() == sealed(bob(first)).tobytes(), key
    for path in sorted((data_folder() / "sprites").glob("*.png")):
        first, *rest = sprites._strip(path.stem)
        for n, frame in enumerate(rest, 2):  # the bob can leave a couple where the body sinks onto its feet
            assert lone_ink(frame) <= lone_ink(first) + 2, f"{path.name} frame {n} has a second outline"


def test_idle_frames_dont_lose_their_feet():
    """A one-picture creation used to bob by sliding the whole frame down, cutting off its bottom row."""
    folder = data_folder() / "sprites"
    for small in (False, True):
        for path in sorted((folder / "small" if small else folder).glob("*.png")):
            strip = sprites._strip(path.stem, small)
            first = strip[0]
            slid = Image.new("RGBA", first.size, (0, 0, 0, 0))
            slid.paste(first, (0, 1))
            cut = sum(pixel[3] >= 128 for pixel in first.crop((0, first.height - 1, first.width, first.height))
                      .get_flattened_data())
            for frame in strip[1:]:
                assert not (cut and frame.tobytes() == slid.tobytes()), f"{path.name}: the bottom row falls off"
