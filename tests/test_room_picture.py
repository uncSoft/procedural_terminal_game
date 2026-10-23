"""Room pictures (ptg/room_picture.py): every kind of room draws from every door, in the sprites' own colours, and
shows what the room holds where the room map says it is."""

import random
from collections import defaultdict

from ptg import layout, sprites
from ptg.models import Exit, Feature, MonsterState
from ptg.room_picture import PROPS, SPRITE_PROPS, Picture, draw, look_of, picture_text, prop_colours, prop_kind
from ptg.world import generate

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
    state.room.monster.hostile = False  # pacified: greyed out, like its portrait
    assert draw(state, content, 72, 30).tobytes() not in (empty, with_goblin)
    state.room.monster = None
    state.room.items = ["healing_potion"]
    assert draw(state, content, 72, 30).tobytes() != empty


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
    for fixture in ("chest", "fountain"):
        state.room.fixture, state.room.fixture_used = fixture, False
        full = draw(state, content, 72, 30).tobytes()
        state.room.fixture_used = True  # an opened chest, a fountain drunk dry
        assert draw(state, content, 72, 30).tobytes() != full, fixture


def test_a_dungeon_without_a_look_borrows_one(content):
    state = room_of(content, "vestry")
    state.theme = "a_dungeon_someone_just_added"
    assert look_of(state.theme) is look_of("sunken_crypt")
    assert draw(state, content, 72, 30).size == (72, 30)
