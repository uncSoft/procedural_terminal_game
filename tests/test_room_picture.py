"""Room pictures (ptg/room_picture.py): every kind of room draws from every door, in the sprites' own colours, and
shows what the room holds where the room map says it is."""

import random
from collections import defaultdict

from ptg import layout, sprites, testrooms
from ptg.models import OPPOSITE, Exit, Feature, MonsterState
from ptg.room_picture import (BRASS, DARK, FLAME, PROPS, PROPS_HALF, SELF_LIT, SPRITE_PROPS, Picture, _shadow,
                              carries_light, draw, fixture_image, look_of, picture_text, prop_at, prop_colours,
                              prop_image, prop_kind, shop_stall)
from ptg.world import build_floor, generate

DOORS = ("", "north", "south", "east", "west")  # "" is where a floor begins: as if you'd come in from the south


def room_of(content, archetype: str):
    """A state whose current room is an `archetype` room, with its decor and all its features."""
    state = generate(5, content=content)
    state.theme = next((t.key for t in content.themes.values() if archetype in [*t.archetypes, t.boss_room]),
                       state.theme)  # a shop is in no dungeon's list: it turns up in any
    room, kind = state.room, content.archetypes[archetype]
    room.archetype, room.name = archetype, kind.names[0]
    room.features = [Feature(name=f) for f in kind.features]
    room.fixture, room.monster, room.items, room.entered_from = "", None, [], ""
    layout.build(random.Random(archetype), room, kind.decor)
    return state


def kinds(state, content) -> set[str]:
    """What the picture shows: wall, floor, water, sky, ceiling, void (an unexplored doorway), locked, object."""
    picture = Picture(state, content, 72, 30)
    picture.draw()
    return {kind for row in picture.kind for kind in row}


def test_every_kind_of_room_draws_from_every_door(content):
    for archetype in content.archetypes:
        state = room_of(content, archetype)
        for door in DOORS:
            state.room.entered_from = door
            assert draw(state, content, 72, 30).size == (72, 30), (archetype, door)
    text = picture_text(state, content, 40, 16)
    assert [len(line) for line in text.plain.split("\n")] == [40] * 8  # two pixels to a row


def test_pictures_keep_to_the_colours_the_sprites_use(content):
    """A GPU terminal caches every character in every pair of colours it meets (see PTGApp.action_redraw), so the
    pictures only use the art's own colours, and a dungeon's rooms share a modest number of pairs between them."""
    allowed = set(sprites.palette())
    pairs = defaultdict(set)
    for archetype in content.archetypes:
        state = room_of(content, archetype)
        for door in ("", "east"):
            state.room.entered_from = door
            for span in picture_text(state, content, 72, 30).spans:
                colours = (span.style.color, span.style.bgcolor)
                assert all(c is None or tuple(c.triplet) in allowed for c in colours), archetype
                pairs[state.theme].add(colours)
    assert max(len(p) for p in pairs.values()) < 450, {theme: len(p) for theme, p in pairs.items()}


def test_doorways_are_in_the_walls_their_exits_are_in(content):
    state = room_of(content, "vestry")  # coming in from the south, looking north
    room = state.room
    room.exits = {"north": Exit(to=1)}
    assert "void" in kinds(state, content)  # the way on, unexplored and dark
    room.exits = {"west": Exit(to=1, locked=True)}
    seen = kinds(state, content)
    assert "locked" in seen and "void" not in seen
    room.exits = {"south": Exit(to=1)}  # the door you came in by is behind you
    assert not {"void", "locked"} & kinds(state, content)
    room.entered_from = "north"  # ...unless you came in the other way
    assert "void" in kinds(state, content)


def test_rooms_open_to_the_sky_show_it(content):
    assert "sky" in content.archetypes["fountain_court"].decor.split()
    assert "sky" in kinds(room_of(content, "fountain_court"), content)
    roofed = kinds(room_of(content, "collapsed_library"), content)
    assert "sky" not in roofed and "ceiling" in roofed


def test_what_the_room_holds_is_in_the_picture(content):
    state = room_of(content, "feast_hall")
    empty = draw(state, content, 72, 30).tobytes()
    goblin = content.monster("goblin")
    state.room.monster = MonsterState(key="goblin", name=goblin.name, hp=goblin.hp, max_hp=goblin.hp)
    with_goblin = draw(state, content, 72, 30).tobytes()
    assert with_goblin != empty
    state.room.monster.hostile = False  # calm: still in its own colours (never a grey statue), right where it was
    assert draw(state, content, 72, 30).tobytes() == with_goblin
    state.room.monster = None
    state.room.items = ["healing_potion"]
    assert draw(state, content, 72, 30).tobytes() != empty


def test_a_calm_character_stands_in_their_own_colours(content):
    """Lucky Lenny (red hair, green jumper) was drawn in five greys, like a statue, because the picture posed anyone
    who wasn't hostile as "calm". Characters are always in colour."""
    state = room_of(content, "vestry")
    lenny = content.monster("lucky_lenny")
    state.room.monster = MonsterState(key="lucky_lenny", name=lenny.name, hp=lenny.hp, max_hp=lenny.hp, hostile=False)
    picture = Picture(state, content, 72, 30)
    picture.draw()
    (him,) = [p for p in picture.placed if p.tag == "occupant"]
    colours = {pixel[:3] for pixel in him.img.get_flattened_data() if pixel[3] >= 128}
    own = {pixel[:3] for pixel in sprites.frames("lucky_lenny")[0].get_flattened_data() if pixel[3] >= 128}
    assert colours <= own and not colours <= set(sprites.GREYS)


def test_the_same_room_always_looks_the_same(content):
    state = room_of(content, "ossuary")
    assert draw(state, content, 72, 30).tobytes() == draw(state, content, 72, 30).tobytes()


def test_features_are_drawn_as_what_they_are(content):
    assert prop_kind("a half-sunken pew") == "pew" and prop_kind("a stew cauldron") == "cauldron"
    assert prop_kind("a vine-covered plinth") == "plinth"  # the noun, not the vines
    assert prop_kind("a sealed burial shelf") == "niche" and prop_kind("the throne of chairs") == "throne"
    assert prop_kind("the drowned altar") == "altar" and prop_kind("a ledge above the waterline") == ""
    assert prop_kind("a mysterious doohickey") == "crate"  # anything new still gets something
    known = set(PROPS) | set(SPRITE_PROPS) | {"fungus", ""}
    features = [f for kind in content.archetypes.values() for f in kind.features]
    assert all(prop_kind(f) in known for f in features)
    letters = set(prop_colours(look_of("sunken_crypt"))) | {"."}
    for kind, rows in PROPS.items():
        assert len({len(row) for row in rows}) == 1, f"{kind}: rows of different lengths"
        assert set("".join(rows)) <= letters, f"{kind}: letters with no colour"


def test_spent_fixtures_look_spent(content):
    state = room_of(content, "vestry")
    for fixture in ("chest", "fountain", "shrine"):
        state.room.fixture, state.room.fixture_used = fixture, False
        full = draw(state, content, 72, 30).tobytes()
        state.room.fixture_used = True  # an opened chest, a fountain drunk dry, a shrine gone dark
        assert draw(state, content, 72, 30).tobytes() != full, fixture
    look = look_of(state.theme)
    for key in ("chest", "shrine"):  # emptied, candles out: their last frame, not the treasure or the flames
        assert fixture_image(key, look, spent=True).tobytes() == sprites._strip(key)[-1].tobytes()
        assert fixture_image(key, look).tobytes() == sprites._strip(key)[0].tobytes()
    assert prop_image("altar", look, "a cracked altar", spent=True).tobytes() == sprites._strip("shrine")[-1].tobytes()


def test_a_used_shrine_or_altar_gives_no_light(content):
    state = room_of(content, "vestry")
    room = state.room
    room.features = []
    room.fixture, room.fixture_used = "shrine", False
    lit = Picture(state, content, 72, 30)
    lit.draw()
    room.fixture_used = True
    dark = Picture(state, content, 72, 30)
    dark.draw()
    assert len(dark.lights) == len(lit.lights) - 1
    room.fixture = ""
    room.features = [Feature(name="a cracked altar", pos=(5, 3))]
    lit = Picture(state, content, 72, 30)
    lit.draw()
    room.features[0].searched = True
    dark = Picture(state, content, 72, 30)
    dark.draw()
    assert len(dark.lights) == len(lit.lights) - 1


def test_a_dungeon_without_a_look_borrows_one(content):
    state = room_of(content, "vestry")
    state.theme = "a_dungeon_someone_just_added"
    assert look_of(state.theme) is look_of("sunken_crypt")
    assert draw(state, content, 72, 30).size == (72, 30)


# --- what matters stays in sight (fixed seeds, through doors the rooms really have) -------------------------------

def floor_of(content, seed: int, number: int):
    state = generate(seed, content=content)
    if number > 1:
        state.floor = number
        build_floor(state, content)
    return state


def solid(img) -> int:
    return sum(1 for pixel in img.get_flattened_data() if pixel[3] >= 128)


def hidden_by(picture, index: int, by: int) -> float:
    """How much of placed sprite `index` the sprite `by` covers."""
    placed = picture.placed[index]
    x0, y0 = placed.box[0] - placed.img.getbbox()[0], placed.box[1] - placed.img.getbbox()[1]
    spots = [(x0 + x, y0 + y) for y in range(placed.img.height) for x in range(placed.img.width)
             if placed.img.getpixel((x, y))[3] >= 128 and 0 <= x0 + x < picture.w and 0 <= y0 + y < picture.h]
    return sum(picture.owner[y][x] == by for x, y in spots) / max(1, len(spots))


def views(content):
    """Rooms with someone in them and a fixture, on fixed seeds, from each door they have; and the audits' worst (the
    last: the Rat King over a rusty sword, in a room with no fixture)."""
    for seed in range(1, 9):
        for number in (1, 2, 3):
            state = floor_of(content, seed, number)
            for room in state.rooms:
                if room.monster and room.fixture:
                    for door in room.exits:
                        yield state, room, door
    for seed, number, room_id, door in ((6, 1, 6, "east"), (34, 2, 1, "west"), (22, 2, 5, "west"), (34, 2, 6, "west"),
                                        (30, 1, 3, "east"), (16, 2, 3, "east"), (1, 2, 2, "north")):
        state = floor_of(content, seed, number)
        assert door in state.rooms[room_id].exits, (seed, number, room_id, door)
        yield state, state.rooms[room_id], door
    state = testrooms.build(content, "king_mouse", seed=2)
    stairs = testrooms.target(state)
    yield state, stairs, OPPOSITE[next(d for d, e in state.room.exits.items() if e.to == stairs.id)]


SHORT = ((36, 16), (41, 18), (61, 26), (76, 20))  # narrow story cards (100 columns: 41x18), Look on a short screen


def test_whoever_is_in_the_room_is_never_hidden(content):
    """The fixture used to cover them: King Mouse behind his stairs, Lucky Lenny behind a chest. They're drawn last
    and step aside, so they're whole; and the fixture loses no more than about a quarter to them, nor all told to
    them and whatever else stands in front of it (items, features), in the smallest pictures too. Drawn last, they
    covered what was near them instead (a rusty sword wholly under the Rat King): they step aside from that too, and
    items and features from them (going by the boxes they fill), so an item loses about a third to them at most, and
    a feature about half."""
    seen = 0
    for state, room, door in views(content):
        room.entered_from = door
        room.items = ["healing_potion", "rusty_sword"]
        for size in ((72, 30), (76, 36), *SHORT):
            picture = Picture(state, content, *size, room)
            picture.draw()
            tags = [p.tag for p in picture.placed]
            them = tags.index("occupant")
            occupant = picture.placed[them]
            assert picture.showing(them) == 1.0 and occupant.pixels == solid(occupant.img), (room.monster.key, door)
            where = (state.seed, state.floor, room.id, door, size)
            if room.fixture:
                fixture = tags.index("fixture")
                assert hidden_by(picture, fixture, them) <= 0.3, where
                assert picture.showing(fixture) >= 2 / 3, where  # whatever covers it
            crowded = 0.15 if size[0] < 40 else 0  # (the smallest picture has room for little: Lenny over a skeleton)
            for index, tag in enumerate(tags):
                if tag in ("item", "feature"):
                    assert hidden_by(picture, index, them) <= (0.4 if tag == "item" else 0.55) + crowded, (tag, *where)
            seen += 1
    assert seen > 180


def test_nothing_that_matters_is_cut_off_at_the_edges(content):
    """Big sprites near you used to lose their heads off the top of the picture (Lucky Lenny's hair, the Wight's
    crown): now they come down, or a size smaller, but never out of the frame."""
    for state, room, door in views(content):
        room.entered_from = door
        room.items = ["healing_potion", "rusty_sword"]
        for size in ((72, 30), (76, 36), (40, 16), (140, 58)):
            picture = Picture(state, content, *size, room)
            picture.draw()
            for placed in picture.placed:
                if placed.tag in ("occupant", "fixture", "item"):
                    assert placed.pixels == solid(placed.img), (placed.tag, state.seed, room.id, door, size)
                    assert placed.box[1] >= 0 and placed.box[3] <= size[1]


def test_items_are_drawn_no_smaller_than_their_small_pictures(content):
    """They used to be shrunk to 3 or 6 pixels, a speck you couldn't make out: in a picture as tall as the story
    card's they're always their small pictures' own size."""
    state = floor_of(content, 1, 1)
    room = state.rooms[3]
    room.items = ["healing_potion", "rusty_sword", "holy_water", "small_key"]
    for door in room.exits:
        room.entered_from = door
        for size in ((72, 30), (76, 36)):
            picture = Picture(state, content, *size, room)
            picture.draw()
            drawn = [p.img.size for p in picture.placed if p.tag == "item"]
            assert drawn == [(sprites.SMALL, sprites.SMALL)] * len(room.items), (door, size)


def test_in_a_short_picture_items_keep_to_scale(content):
    """At their small pictures' size in a narrow story card, a potion stood as tall as Lucky Lenny beside it. In a
    shorter picture than the story card's they're halved wherever he'd be (never more), so he stands taller."""
    state = room_of(content, "vestry")
    room = state.room
    room.features, room.fixture = [], ""
    lenny = content.monster("lucky_lenny")
    room.monster = MonsterState(key="lucky_lenny", name=lenny.name, hp=lenny.hp, max_hp=lenny.hp, hostile=False)
    for size in SHORT:
        for gy in range(1, 7):  # far enough in that he stands where the map has him, not further back
            room.monster_pos, room.items, room.item_spots = (8, gy), ["healing_potion"], [(14, gy)]
            picture = Picture(state, content, *size)
            picture.draw()
            (him,) = [p for p in picture.placed if p.tag == "occupant"]
            (potion,) = [p for p in picture.placed if p.tag == "item"]
            assert potion.img.width == max(sprites.SMALL // 2, min(sprites.SMALL, him.img.width // 2)), (size, gy)
            taller = him.box[3] - him.box[1] > potion.box[3] - potion.box[1]
            assert taller or him.img.width == sprites.SMALL // 2, (size, gy)  # a speck himself, far back in a tiny one


def test_items_keep_clear_of_the_fixture(content):
    """In a small picture a potion lying in front of a chest covered most of it, and one lying behind the stairs was
    lost behind them: like whoever's in the room, they're moved aside."""
    state = room_of(content, "vestry")
    room = state.room
    room.features, room.fixture = [], "chest"
    x, y = layout.CENTRE
    for size in ((72, 30), (76, 36), *SHORT):
        for dy in (-2, -1, 1, 2):  # seen from the south: behind it, then in front of it
            room.items, room.item_spots = ["healing_potion"], [(x, y + dy)]
            picture = Picture(state, content, *size)
            picture.draw()
            tags = [p.tag for p in picture.placed]
            fixture, item = tags.index("fixture"), tags.index("item")
            assert picture.showing(fixture) >= 0.7 and picture.showing(item) >= 0.7, (size, dy)


def test_a_shop_shows_her_and_her_wares_whole(content):
    """The stall was halved to a smear in the story card and lost its shelf of wares off the top in Look: now she's
    full size, with her wares on the shelf where the picture is tall enough, else on the counter beside her."""
    state = testrooms.build(content, "shop", seed=5)
    shop = testrooms.target(state)
    shop.entered_from = OPPOSITE[next(d for d, e in state.room.exits.items() if e.to == shop.id)]
    keeper = sprites._strip(shop.shop.keeper)[0]
    for size in ((72, 30), (76, 36), (76, 40), (100, 42), (140, 58)):
        picture = Picture(state, content, *size, shop)
        picture.draw()
        (stall,) = [p for p in picture.placed if p.tag == "fixture"]
        assert stall.pixels == solid(stall.img), size  # nothing cut off
        shelf = shop_stall(shop.shop)
        assert stall.img.tobytes() in (shelf.tobytes(), shop_stall(shop.shop, size[0]).tobytes()), size
    counter = shop_stall(shop.shop, 72)
    assert counter.height == keeper.height + 2 and counter.width <= 72  # short, with room on the counter for wares
    assert counter.width > shop_stall(shop.shop, keeper.width + 8).width
    assert shop_stall(shop.shop, 140).width > counter.width  # wider pictures, more wares


def test_halved_props_keep_their_colours(content):
    """Halved block by block, a shelf came out one flat colour and in shadow the void's own black: a hole in the
    wall where the bookshelves were. Some props have half-size drawings, and shadows stop short of the void."""
    look = look_of("sunken_crypt")
    letters = set(prop_colours(look)) | {"."}
    for kind, rows in PROPS_HALF.items():
        assert len({len(row) for row in rows}) == 1 and set("".join(rows)) <= letters, kind
        assert abs(len(rows[0]) - len(PROPS[kind][0]) // 2) <= 1 and abs(len(rows) - len(PROPS[kind]) // 2) <= 1
    for kind in PROPS:
        half = prop_at(kind, look, 0.5)
        assert half.width < len(PROPS[kind][0])
        assert len({half.getpixel((x, y)) for x in range(half.width) for y in range(half.height)
                    if half.getpixel((x, y))[3] >= 128}) >= 2, kind
    for colour in sprites.palette():
        if sprites._light(colour) >= sprites.OUTLINE:
            assert _shadow(colour, 0.5) != DARK, colour


def test_bookshelves_in_the_dark_are_not_holes(content):
    state = floor_of(content, 4, 1)
    room = state.rooms[3]
    assert "▤" in "".join(room.grid) and "north" in room.exits
    room.entered_from = "north"
    picture = Picture(state, content, 72, 30, room)
    img = picture.draw()
    shelves = [(x, y) for y in range(30) for x in range(72)
               if picture.owner[y][x] >= 0 and picture.placed[picture.owner[y][x]].tag == "decor"]
    assert shelves and sum(img.getpixel(p) == DARK for p in shelves) < 0.05 * len(shelves)


def test_crypt_rooms_are_dark_but_not_lost(content):
    """The Crypt is meant to be dark, but its props were drawn in the walls' own tones and shadowed into them (a
    basin's bowl floating on the wall), and a locked gate was one more grey box."""
    look = look_of("sunken_crypt")
    assert look.prop_stone[0] == look.wall[2]  # stone props start two steps above the walls
    light, black, count = 0.0, 0, 0
    crypts = [(seed, n) for seed in range(1, 20) for n in (1, 2, 3) if generate(seed).themes[n - 1] == "sunken_crypt"]
    for seed, number in crypts[:6]:
        state = floor_of(content, seed, number)
        for room in state.rooms:
            room.entered_from = next(iter(room.exits), "")
            for r, g, b in draw(state, content, 72, 30, room).get_flattened_data():
                level = 0.299 * r + 0.587 * g + 0.114 * b
                light, black, count = light + level, black + (level < 40), count + 1
    assert light / count > 52 and black / count < 0.36, (light / count, black / count)  # it was 49, and 40% black


def test_a_locked_door_is_barred_in_brass(content):
    state = room_of(content, "vestry")
    state.room.exits = {"north": Exit(to=1, locked=True)}
    picture = Picture(state, content, 72, 30)
    img = picture.draw()
    locked = {img.getpixel((x, y)) for y in range(30) for x in range(72) if picture.kind[y][x] == "locked"}
    assert set(BRASS) <= locked  # the bands and the lock, the colour of a locked way on the maps


def test_whoever_is_in_the_room_stands_where_the_map_has_them(content):
    """The picture is drawn from the door you came in by; whoever's here stands on their own side of it, as the room
    map and the narrator have them, not in the middle."""
    state = room_of(content, "vestry")
    room = state.room
    room.features, room.fixture = [], ""
    goblin = content.monster("goblin")
    room.monster = MonsterState(key="goblin", name=goblin.name, hp=goblin.hp, max_hp=goblin.hp)
    for door, west_is_left in (("south", True), ("north", False)):
        room.entered_from = door
        for x, on_left in ((4, west_is_left), (layout.WIDTH - 3, not west_is_left)):
            room.monster_pos = (x, 5)
            picture = Picture(state, content, 72, 30)
            picture.draw()
            (them,) = [p for p in picture.placed if p.tag == "occupant"]
            assert ((them.box[0] + them.box[2]) / 2 < 36) == on_left, (door, x)


def test_doorways_can_say_which_way_they_go(content):
    state = room_of(content, "vestry")
    room = state.room
    room.exits = {"north": Exit(to=1), "south": Exit(to=2), "east": Exit(to=3)}
    room.entered_from = "east"  # looking west: south on the left, north on the right
    picture = Picture(state, content, 72, 30)
    picture.draw()
    marks = {way: column for way, column, _ in picture.door_marks()}
    assert set(marks) == {"north", "south"} and marks["south"] < 36 < marks["north"]
    text = picture_text(state, content, 72, 30, compass=True).plain
    assert "N" in text and "S" in text and "N" not in picture_text(state, content, 72, 30).plain


def test_a_room_with_more_than_six_items_shows_them_all(content):
    state = room_of(content, "feast_hall")
    state.room.items = ["healing_potion"] * 8
    picture = Picture(state, content, 72, 30)
    picture.draw()
    assert sum(p.tag == "item" for p in picture.placed) == 8


# --- the Underbloom: dark, but for what grows there and the torch you bring -------------------------------------------

def luminance(img) -> float:
    return sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b in img.get_flattened_data()) / (img.width * img.height)


def test_the_underbloom_is_lit_by_what_grows_there_and_the_torch_you_bring(content):
    """A dark floor: no light but what grows there (a cold teal, bright where it's thickest) and what you carry. With
    a torch, the floor near you is warm and the room lighter; without one, eyes used to the dark. In the Dark Hollow
    nothing grows, so nothing glows."""
    warm = set(look_of("underbloom").floor_warm[1:])
    for archetype in content.themes["underbloom"].archetypes:
        state = room_of(content, archetype)
        assert state.theme == "underbloom"
        pictures = {torch: Picture(state, content, 72, 30, torch=torch) for torch in (False, True)}
        images = {torch: picture.draw() for torch, picture in pictures.items()}
        assert luminance(images[True]) > luminance(images[False]) + 3, archetype
        for torch, picture in pictures.items():
            near = [images[torch].getpixel((x, y)) for y in range(24, 30) for x in range(10, 62)
                    if picture.kind[y][x] == "floor"]
            assert (sum(p in warm for p in near) > len(near) / 2) == torch, (archetype, torch)
        glowing = set(images[False].get_flattened_data()) & SELF_LIT
        assert bool(glowing) == (archetype != "dark_hollow"), archetype


def test_a_torch_of_your_own_is_in_the_picture(content):
    """Carry a torch and it's in the bottom left of a dark floor's pictures, big enough to see at a glance on a
    stage with room for it, its flame flickering between the stage's frames; and a picture kept from before you had it
    isn't shown again after."""
    state = room_of(content, "glowcap_grove")
    assert not carries_light(state, content)
    before = picture_text(state, content, 72, 30)
    state.player.inventory.append("torch")
    assert carries_light(state, content) and picture_text(state, content, 72, 30).spans != before.spans
    corner = [[draw(state, content, 72, 30, frame=f).getpixel((x, y)) for x in range(9) for y in range(12, 30)]
              for f in (0, 1)]
    assert all(set(FLAME) & set(seen) for seen in corner) and corner[0] != corner[1]  # (its flame, moving)
    flame = [(x, y) for x in range(9) for y in range(12, 30) if draw(state, content, 72, 30).getpixel((x, y)) in FLAME]
    assert len(flame) >= 25 and max(y for _, y in flame) - min(y for _, y in flame) >= 8  # (a torch, not a spark)
    small = [draw(state, content, 40, 20).getpixel((x, y)) for x in range(8) for y in range(10, 20)]
    assert set(FLAME) & set(small)  # (a small stage has the little one)
    state.theme = "sunken_crypt"  # (a lit floor: your lantern does, and no torch is drawn)
    assert not set(FLAME[2:]) & {draw(state, content, 72, 30).getpixel((x, y)) for x in range(4) for y in range(26, 30)}


def test_what_the_underbloom_gets_into_sprouts_glowing_caps(content):
    """A prop there has glowing caps on its top (two rows taller for them) and glows; the same prop elsewhere
    doesn't; and the fungus itself doesn't sprout more fungus."""
    crypt, bloom = look_of("sunken_crypt"), look_of("underbloom")
    plain, grown = prop_image("crate", crypt, "a crate"), prop_image("crate", bloom, "a crate")
    assert grown.height == plain.height + 2 and not {p[:3] for p in plain.get_flattened_data()} & SELF_LIT
    assert {p[:3] for p in grown.get_flattened_data()} & SELF_LIT
    assert prop_image("cap", bloom, "a giant glowcap's stalk").size == prop_image("cap", crypt, "a stalk").size
    assert prop_kind("a fallen glowcap, soft as bread") == "cap" and prop_kind("a pillar's hollow cap") == "crate"


def test_the_underbloom_keeps_to_its_colour_budget_with_a_torch_or_without(content):
    """As every dungeon does (test_pictures_keep_to_the_colours_the_sprites_use), torch or no torch."""
    pairs = set()
    for archetype in content.themes["underbloom"].archetypes:
        state = room_of(content, archetype)
        for torch in (False, True):
            if torch:
                state.player.inventory.append("torch")
            for door in ("", "east"):
                state.room.entered_from = door
                pairs |= {(s.style.color, s.style.bgcolor) for s in picture_text(state, content, 72, 30).spans}
            state.player.inventory.clear()
    assert len(pairs) < 520, len(pairs)


def test_the_underbloom_s_decor_is_painted_on_its_room_maps():
    """Glowcaps as tall as trees, never side by side; curtains of threads; puffballs."""
    from ptg.models import Room

    room = Room(id=0, name="", archetype="glowcap_grove", x=0, y=0, exits={"south": Exit(to=1)})
    layout.build(random.Random(3), room, "caps threads puffballs")
    cells = [(x, y, ch) for y, line in enumerate(room.grid) for x, ch in enumerate(line)]
    caps = [(x, y) for x, y, ch in cells if ch == "♠"]
    assert len(caps) >= 3 and any(ch == "¦" for *_, ch in cells) and any(ch == "●" for *_, ch in cells)
    assert all(abs(a - c) + abs(b - d) > 4 for i, (a, b) in enumerate(caps) for c, d in caps[i + 1:])
