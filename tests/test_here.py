"""Here (ui/here.py): the room's characters and things as tiles, with the engine's own actions for buttons."""

from ptg import npcs, testrooms
from ptg.events import Action
from ptg.interactions import verbs
from ptg.ui.here import CARD, CHIP, MINI, ROW, Thing, arrange, compare, foe_status, measure, things_here

FORMS = (CARD, MINI, ROW)


def in_room(content, who: str, loadout: str = "random", seed: int = 3):
    """A test room's target, walked into."""
    state = testrooms.build(content, who, loadout, seed=seed)
    room = testrooms.target(state)
    state.room_id, room.visited = room.id, True
    return state


def by_id(things: list[Thing]) -> dict[str, Thing]:
    return {t.id: t for t in things}


def test_lenny_is_a_character_with_a_job_for_you(content):
    state = in_room(content, "lenny")
    lenny = things_here(state, content)[0]
    assert lenny.id == f"monster:{npcs.LENNY}" and lenny.character and lenny.badge == "★"
    assert lenny.status == "wants his bad tooth back" and lenny.pose == "idle"
    assert "talk:lucky_lenny" in {a.id for a in lenny.verbs} or "ask" in {a.id for a in lenny.verbs}
    assert all(a.id in {v.id for v in verbs(state, content, lenny.id)} for a in lenny.verbs)  # (the engine's own)


def test_a_foe_shows_its_health_and_a_big_blow_coming(content):
    state = in_room(content, "swamp_bottoms", seed=5)
    monster = state.room.monster
    monster.hp, monster.intent = monster.max_hp - 3, "heavy"
    foe = things_here(state, content)[0]
    assert foe.character and foe.pose == "windup" and foe.status.startswith("⚠ big hit next!")
    assert f"{monster.hp}/{monster.max_hp}" in foe.status and f"{monster.hp}/{monster.max_hp}" in foe.compact
    assert "⚠" in foe.compact  # (the chip form shows it too: a hostile one is never in a form that hides it)
    assert any(a.id == "attack" for a in foe.verbs)
    monster.intent = "strike"
    assert "big hit" not in foe_status(monster)[0]


def test_a_shop_lists_its_keeper_and_each_ware_with_a_price(content):
    state = in_room(content, "shop", "strong", seed=4)
    things = things_here(state, content)
    keeper = things[0]
    assert keeper.id.startswith("keeper:") and keeper.character
    wares = [t for t in things if t.id.startswith("ware:")]
    assert wares and len(wares) == len(state.room.shop.wares)
    assert all(w.verbs and w.status for w in wares)
    state.player.gold = 0  # (broke: a button that can't be pressed, and why)
    broke = [t for t in things_here(state, content) if t.id.startswith("ware:")]
    assert all(w.verbs == [Action("", f"need {w.status.split()[-1]}")] for w in broke)
    assert all(w.status.startswith("need ") for w in broke)


def test_something_lying_here_says_how_it_compares_with_what_you_have_on(content):
    state = in_room(content, "goblin", "new", seed=4)
    state.room.monster = None
    state.room.items = ["war_pick", "chain_shirt", "healing_potion"]
    things = by_id(things_here(state, content))
    pick, shirt, potion = things["floor:war_pick"], things["floor:chain_shirt"], things["floor:healing_potion"]
    assert "Rusty Sword" in pick.status and pick.status[0] in "▲=▼"
    assert shirt.status.startswith("▲ you have none")  # (no armor on)
    assert potion.status == "heals 8" or potion.status.startswith("heals")
    assert {a.id for a in pick.verbs} >= {"take:war_pick"} and "take:healing_potion" in {a.id for a in potion.verbs}
    assert compare(state, content, "rusty_sword")[0].startswith("the same as")


def test_cursed_things_warn_on_their_tile(content):
    state = in_room(content, "goblin", "new", seed=4)
    state.room.monster = None
    cursed = next(i.key for i in content.items.values() if "cursed" in i.powers)
    state.room.items = [cursed]
    assert things_here(state, content)[0].status == "cursed! sticks to you"


def test_the_fixture_and_features_to_search_are_tiles_and_a_searched_one_is_not(content):
    state = in_room(content, "goblin", "new", seed=4)
    state.room.monster = None
    state.room.fixture, state.room.fixture_used = "chest", False
    things = things_here(state, content)
    chest = next(t for t in things if t.id == "fixture:chest")
    assert chest.loop == [0, 0, 0, 1] and not chest.character and chest.verbs
    searchable = [t for t in things if t.id.startswith("feature:")]
    assert searchable and not any(t.art for t in searchable)  # (words only: a chip)
    state.room.features[0].searched = True
    assert len([t for t in things_here(state, content) if t.id.startswith("feature:")]) == len(searchable) - 1
    state.room.fixture_used = True
    assert next(t for t in things_here(state, content) if t.id == "fixture:chest").status == "spent"


def test_a_cracked_wall_stays_in_the_room(content):
    from ptg.rules import bombable_walls
    from ptg.world import generate

    state = next(s for s in map(generate, range(1, 40)) if bombable_walls(s))
    wall = bombable_walls(state)[0]
    assert not any(t.id.startswith("wall:") for t in things_here(state, content))  # (a candidate wall isn't a thing)
    state.room.draft = wall
    state.player.bombs = 1
    tile = next(t for t in things_here(state, content) if t.id == f"wall:{wall}")
    assert tile.name == f"cracked {wall} wall" and f"bomb:{wall}" in {a.id for a in tile.verbs} and not tile.art


def thing(name: str, **kwargs) -> Thing:
    return Thing(f"floor:{name}", name, "item", name.title(), kwargs.pop("status", "a trinket"), "#9a9cc0",
                 kwargs.pop("verbs", [Action(f"take:{name}", "Take")]), **kwargs)


def test_characters_get_the_biggest_form_that_fits_them_all_then_things(content):
    people = [Thing(f"monster:{k}", k, "monster", k.title(), "friendly", "#4cff8a", [Action("ask", "Talk")], True)
              for k in ("goblin", "giant_rat")]
    stuff = [thing("war_pick"), thing("rubber_duck")]
    layout, hidden = arrange(people + stuff, 56, 40, False, FORMS, content)
    assert hidden == 0
    forms = {t.id: form for line in layout for t, form, _ in line}
    assert forms["monster:goblin"] == forms["monster:giant_rat"]  # (one form for the group)
    assert forms["floor:war_pick"] == forms["floor:rubber_duck"]
    short, hidden = arrange(people + stuff, 56, 5, False, FORMS, content)
    assert all(form == CHIP for line in short for _, form, _ in line)  # (the least that fits them all)


def test_when_even_chips_do_not_fit_it_says_how_many_are_left(content):
    many = [thing(f"thing_{i}") for i in range(12)]
    layout, hidden = arrange(many, 20, 4, False, FORMS, content)
    assert hidden > 0 and hidden + sum(len(line) for line in layout) == len(many)
    assert sum(max(h for _, _, (_, h) in line) for line in layout) <= 4


def test_a_thing_with_no_picture_is_always_a_chip(content):
    search = Thing("feature:0", "", "", "Stew Cauldron", "", "#9a9cc0", [Action("search:0", "Search")], art=False)
    layout, _ = arrange([search], 30, 12, False, FORMS, content)
    assert layout[0][0][1] == CHIP


def test_buttons_take_their_columns_and_wrap_rather_than_being_cut(content):
    heavy = Thing("monster:goblin", "goblin", "monster", "Goblin", "x", "#ff4b4b",
                  [Action("attack", "Attack"), Action("use:@", "Use…"), Action("a", "Another"), Action("b", "Last")], True)
    assert measure(heavy, CARD, 30, False, content)[1] > measure(heavy, CARD, 80, False, content)[1] or \
        measure(heavy, CARD, 30, False, content)[0] >= 26
    assert measure(heavy, CARD, 20, False, content)[1] == 999  # (too narrow for a card at all)
    touch = measure(heavy, CHIP, 80, True, content)
    assert touch[1] >= 3  # (touch buttons are three rows tall)
