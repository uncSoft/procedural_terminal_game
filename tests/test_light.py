"""Light and the dark (ptg/light.py): the Underbloom's torch, what it's like down there without one, burning things,
lamp oil, and how you can tell which you've got (docs/plans/floor-5.md §4)."""

from conftest import put_monster

from ptg import light, loot, rules, testrooms
from ptg.models import Feature
from ptg.rules import available_actions, perform
from ptg.scene import RoomView
from ptg.ui.widgets import light_cue
from ptg.world import build_floor, generate


def ids(state, content):
    return [a.id for a in available_actions(state, content)]


def down_there(content, torch=True, seed=11):
    """Floor 5, the Underbloom, next door to the Dark Hollow (a test room's): a torch and lamp oil, or no light."""
    return testrooms.build(content, "underbloom" if torch else "underbloom_dark", seed=seed)


def into_the_hollow(state, content):
    hollow = testrooms.target(state, content)
    way = next(d for d, e in state.room.exits.items() if e.to == hollow.id)
    return hollow, perform(state, content, f"go:{way}")


def wrapped_thing(state, loot_=("pure",), gold=12):
    state.room.features.append(Feature(name="a cocoon wrapped in white threads", loot=list(loot_), gold=gold,
                                       pos=(3, 3)))
    return len(state.room.features) - 1


def test_by_the_glow_your_searches_are_at_a_disadvantage_and_a_torch_lifts_it(content):
    state = down_there(content, torch=False)
    assert light.darkness(state, content) == light.DIM and not light.lit(state, content)
    roll = perform(state, content, "search_room")[0].dice
    assert len(roll.dice) == 2 and roll.kept == min(roll.dice) and roll.hindered == light.DIM
    state = down_there(content)
    assert light.lit(state, content) and light.darkness(state, content) == ""
    assert len(perform(state, content, "search_room")[0].dice.dice) == 1


def test_in_the_dark_it_strikes_first_and_every_roll_is_at_a_disadvantage(content):
    state = down_there(content, torch=False)
    hollow, events = into_the_hollow(state, content)
    kinds = [e.kind for e in events]
    assert light.darkness(state, content) == light.DARK and state.in_combat
    assert "warning" in kinds and kinds.index("ambush") < kinds.index(next(k for k in kinds if k.startswith("monster")))
    assert hollow.monster.swings == 1  # (its first blow, before you could do a thing)
    roll = next(e.dice for e in perform(state, content, "attack") if e.dice and e.dice.actor == "player")
    assert len(roll.dice) == 2 and roll.hindered == light.DARK and "in the dark" in roll.describe()


def test_with_a_torch_the_dark_hollow_is_only_a_room(content):
    state = down_there(content)
    hollow, events = into_the_hollow(state, content)
    assert state.in_combat and hollow.monster.swings == 0 and "ambush" not in [e.kind for e in events]
    assert "Your torch is lit" in events[0].text  # (and the narrator's told so)
    assert not light.hindrance(state, content).disadvantage


def test_your_torch_burns_a_monster_for_a_flame_of_its_light(content):
    state = down_there(content)
    into_the_hollow(state, content)
    monster = state.room.monster
    assert "burn" in ids(state, content) and "fire" in content.monster(monster.key).weak
    monster.hp = 999
    burnt = before = light.left(state)
    for _ in range(light.FLAMES - 1):  # (short of its last flame: that one's its own test)
        events = perform(state, content, "burn")
        hit = next(e for e in events if e.kind in ("hit", "miss"))
        if hit.kind == "hit":
            assert hit.dice.advantage == 1 and ("fire!", 2) in hit.dice.damage  # (its weakness: and now you know)
            burnt -= 1
        else:
            assert light.left(state) == burnt  # (a miss burns nothing)
        if state.over or not state.in_combat:
            break
    assert light.left(state) == burnt < before and "fire" in state.known_weak[monster.key]


def test_a_wrapped_thing_opens_only_to_fire(content):
    state = down_there(content, torch=False)
    index = wrapped_thing(state)
    assert f"burn:{index}" not in ids(state, content)  # (no torch, no fire)
    turn, events = state.turn, perform(state, content, f"search:{index}")
    assert events[0].kind == "info" and "Fire would open it" in events[0].text and state.turn == turn
    assert not state.room.features[index].searched
    assert "torch" in rules.why_not(state, content, f"burn:{index}")
    state = down_there(content)
    index = wrapped_thing(state)
    events = perform(state, content, f"burn:{index}")
    assert events[0].kind == "burn" and "pure" in state.room.items and light.left(state) == light.FLAMES - 1
    assert state.room.features[index].searched


def test_a_wrapped_thing_burns_open_from_the_grid_and_from_what_you_say(content):
    state = down_there(content)
    index = wrapped_thing(state)
    view = RoomView(state, content)
    assert rules.interactions.read(view, "burn the cocoon").target == f"feature:{index}"
    assert rules.interactions.plan(state, content, rules.interactions.Use("use", "torch", f"feature:{index}")).alias \
        == f"burn:{index}"
    assert "Burn it open" in [a.label for a in rules.interactions.verbs(state, content, f"feature:{index}")]


def test_lamp_oil_puts_every_flame_back(content):
    state = down_there(content)
    assert "refill" not in ids(state, content)  # (it's burning as bright as it can)
    state.player.burnt = 3
    assert "refill" in ids(state, content)
    events = perform(state, content, "refill")
    assert events[0].kind == "light" and light.left(state) == light.FLAMES and light.OIL not in state.player.inventory
    assert "refill" not in ids(state, content)


def test_its_last_flame_and_its_gone_and_another_is_lit(content):
    state = down_there(content)
    state.player.inventory.append("torch")
    state.player.burnt = light.FLAMES - 1
    events = light.burn(state, content)
    assert "goes out" in events[0].text and "another" in events[0].text and state.player.inventory.count("torch") == 1
    assert light.lit(state, content) and light.left(state) == light.FLAMES
    state.player.burnt = light.FLAMES - 1
    events = light.burn(state, content)
    assert "torch" not in state.player.inventory and light.HINT in events[0].text
    assert light.darkness(state, content) == light.DIM and not state.player.lit


def test_picked_up_its_lit_and_put_down_the_dark_closes_in(content):
    state = down_there(content, torch=False)
    state.room.items.append("torch")
    events = perform(state, content, "take:torch")
    assert events[-1].kind == "light" and events[-1].text.startswith("You light your torch")
    events = perform(state, content, "drop:torch")
    assert events[-1].kind == "light" and light.HINT in events[-1].text


def test_up_on_a_lit_floor_the_torch_stays_packed(content):
    state = generate(3)
    put_monster(state, content, "walking_toadstool")
    state.player.inventory.append("torch")
    assert not light.lit(state, content) and light.darkness(state, content) == ""
    assert "burn" not in ids(state, content) and "packed away" in rules.why_not(state, content, "burn")
    assert light_cue(state, content) is None


def test_coming_down_into_the_dark(content):
    def down(torch):
        state = generate(5, content=content)
        state.themes.append("underbloom")
        state.floors_total, state.floor = 5, 4
        build_floor(state, content)
        stairs = next(r for r in state.rooms if r.fixture == "stairs")
        state.room_id, stairs.monster = stairs.id, None
        state.player.inventory += ["torch"] if torch else []
        return state, perform(state, content, "descend")
    state, events = down(torch=True)
    assert state.theme == "underbloom" and events[-1].text.startswith("You light your torch")
    state, events = down(torch=False)
    assert next(e for e in events if e.kind == "warning").text.endswith(light.HINT)


def test_above_a_dark_floor_shes_always_open_with_torches_and_oil(content):
    for seed in range(6):
        state = generate(seed, content=content)
        state.themes.append("underbloom")
        state.floors_total, state.floor = 5, 4
        build_floor(state, content)
        shop = next(r.shop for r in state.rooms if r.shop)
        stock = {w.item: w.count for w in shop.wares}
        assert stock["torch"] == 2 and stock[light.OIL] == 2
    assert all(key in content.items for key in loot.LIGHTS)


def test_you_can_see_at_a_glance_which_youve_got(content):
    state = down_there(content)
    assert light_cue(state, content).plain == "☼ torch ▲▲▲▲▲"
    state.player.burnt = 2
    assert light_cue(state, content).plain == "☼ torch ▲▲▲△△"
    state = down_there(content, torch=False)
    assert light_cue(state, content).plain == "☼ no light"
    into_the_hollow(state, content)
    assert light_cue(state, content).plain == "☼ in the dark"


def test_the_underbloom_test_rooms(content):
    for who, torch in testrooms.DARK_ROOMS.items():
        state = testrooms.build(content, who, seed=4)
        hollow = testrooms.target(state, content)
        assert state.floor == 5 and state.theme == "underbloom" and light.pitch_dark(content, hollow)
        assert hollow.monster and hollow.monster.hostile and not light.pitch_dark(content, state.room)
        assert ("torch" in state.player.inventory) == torch == light.lit(state, content) == state.player.lit
        assert "pitch dark" in dict(testrooms.describe(content, state))["Next door"]
