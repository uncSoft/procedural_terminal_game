"""The Underbloom in the run (docs/plans/multi-foe-fights.md §3-4): five floors once you've won one, the web door and
the Sporefang Matriarch behind it (her screech, her trade: the Ring for the Philter of Light), and the Humongous
Fungus's Spore Bed."""

import random

import pytest

from ptg import combat, encounter, light, meta, testrooms
from ptg.models import DEEPEST, FLOORS
from ptg.rules import available_actions, perform
from ptg.ui.effects import event_sound
from ptg.world import LAIRS, build_floor, generate, render_map

MATRIARCH, RING, PHILTER = "the_sporefang_matriarch", "a_ring_probably_importan", "philter_of_light"


def ids(state, content):
    return [a.id for a in available_actions(state, content)]


def underbloom(content, seed=3):
    state = generate(seed, content=content, floors=DEEPEST)
    state.floor = DEEPEST
    build_floor(state, content)
    return state


def at_the_web(content, loadout="strong", torch=True, seed=11):
    """The Matriarch's test room: you start by the web, a torch and the Ring in your pack (or no torch)."""
    state = testrooms.build(content, "matriarch", loadout, seed=seed)
    if not torch:
        state.player.inventory = [k for k in state.player.inventory if "torch" not in content.item(k).powers]
        state.player.lit = light.lit(state, content)
    return state, next(d for d, e in state.room.exits.items() if e.webbed)


# --- the run ------------------------------------------------------------------------------------------------------

def test_a_run_goes_down_to_the_underbloom_once_youve_won_one(content, profile):
    assert meta.floors_for(profile) == FLOORS
    run_id = profile.start_run(1, "Tester", ["sunken_crypt"])
    profile.finish_run(run_id, status="won", floor=4)
    assert meta.floors_for(profile) == DEEPEST and meta.floors_for(profile, daily=True) == FLOORS
    state = meta.start_run(profile, content, "Tester", seed=5)
    assert state.floors_total == DEEPEST and state.themes[-1] == "underbloom" and state.themes[3] == "norfel"


def test_on_a_five_floor_run_serpentis_falling_cracks_the_floor_open(content):
    state = generate(5, content=content, floors=DEEPEST)
    state.floor = 4
    build_floor(state, content)
    lair = next(r for r in state.rooms if r.is_boss)
    state.room_id = lair.id
    lair.monster.hp = 0
    events = combat.defeat(state, content, random.Random(1))
    conquered = next(e for e in events if e.kind == "conquered")
    assert state.status == "playing" and "cracks open" in conquered.text and lair.fixture == "stairs"


def test_the_spore_bed_has_the_fungus_and_its_three_parts_behind_the_locked_door(content):
    state = underbloom(content)
    bed = next(r for r in state.rooms if r.is_boss)
    assert bed.archetype == "spore_bed" and bed.monster.key == "humongous_fungus"
    assert [m.key for m in bed.others] == ["spore_mother", "rot_gill", "puff_mound"]
    assert any(e.locked and e.to == bed.id for r in state.rooms for e in r.exits.values())
    assert bed.fixture != "stairs"  # (the bottom of the run)


def test_the_underbloom_test_room_for_its_boss(content):
    state = testrooms.build(content, "humongous_fungus", "strong", seed=4)
    gate = next(a for a in available_actions(state, content) if a.hint == "boss")
    perform(state, content, gate.id)
    assert state.in_combat and len(combat.foes(state)) == 4
    faces = [a for a in available_actions(state, content) if a.id.startswith("face:")]
    assert [a.hint.split(" · ")[1] for a in faces] == ["mends the others", "poisons", "stuns"]


def test_on_a_dark_floor_the_key_is_never_wrapped_where_only_fire_gets_in(content):
    key = content.themes["underbloom"].key_item
    for seed in range(40):
        state = underbloom(content, seed)
        (holder,) = [f for r in state.rooms for f in r.features if key in f.loot]
        assert not any(word in holder.name.lower() for word in light.WRAPS), (seed, holder.name)


# --- the web door -------------------------------------------------------------------------------------------------

def test_one_room_on_the_floor_has_a_web_door_with_the_matriarch_behind_it(content):
    state = underbloom(content)
    webs = [(r, e) for r in state.rooms for e in r.exits.values() if e.webbed]
    assert len(webs) == 1
    lair = state.rooms[webs[0][1].to]
    assert lair.archetype == LAIRS["underbloom"][0] and lair.monster.key == MATRIARCH and lair.monster.hostile
    assert "x" in "".join(render_map(_mapped(state)))


def _mapped(state):
    state.mapped_floor = state.floor
    return state


def test_coming_in_you_are_warned_of_the_web_hissing_and_spore_dust(content):
    state, _ = at_the_web(content)
    back = next(d for d, e in state.room.exits.items() if not e.shut and not state.rooms[e.to].secret)
    perform(state, content, f"go:{back}")
    state.room.monster, state.room.others = None, []
    there = {"north": "south", "south": "north", "east": "west", "west": "east"}[back]
    state.rooms[state.prev_room_id].visited = False  # (as if for the first time)
    warning = next(e for e in perform(state, content, f"go:{there}") if e.data.get("web"))
    assert "hisses" in warning.text and "spore dust" in warning.text and "torch would burn" in warning.text


def test_no_hand_blade_or_bomb_gets_through_the_web(content):
    state, web = at_the_web(content)
    turn = state.turn
    events = perform(state, content, f"go:{web}")
    assert state.turn == turn and events[0].kind == "locked" and "Only fire" in events[0].text
    assert f"go:{web}" not in ids(state, content) and f"bomb:{web}" not in ids(state, content)


def test_your_torch_burns_through_and_takes_you_in(content):
    state, web = at_the_web(content)
    burn = next(a for a in available_actions(state, content) if a.id == f"burn:{web}")
    assert "a flame" in burn.hint
    events = perform(state, content, burn.id)
    assert state.room.archetype == "matriarchs_lair" and state.in_combat and state.player.burnt == 1
    assert [e.kind for e in events][:2] == ["burn", "enter"]


def test_without_a_torch_theres_no_burning_it_and_youre_told_so(content):
    state, web = at_the_web(content, torch=False)
    assert f"burn:{web}" not in ids(state, content)
    assert light.HINT in perform(state, content, f"go:{web}")[0].text


def test_neither_fleeing_nor_quick_travel_goes_through_a_web(content):
    state, web = at_the_web(content)
    lair = state.rooms[state.room.exits[web].to]
    lair.visited = True
    from ptg.rules import journey

    assert journey(state, lair.id) is None
    assert all(not e.webbed for d, e in state.room.exits.items() if d == combat.flee_direction(state))


# --- the Matriarch --------------------------------------------------------------------------------------------------

def test_she_screeches_as_she_lands_and_as_she_rears_up(content):
    state, web = at_the_web(content)
    perform(state, content, f"burn:{web}")
    fight = encounter.Fight(state, content, state.room.monster, 110, 16)
    assert fight.sting == "screech" and "screech" in [cue for _, _, cue in fight.entrance()]
    assert "GUARDIAN OF THE UNDERBLOOM" in fight.subtitle()
    state.room.monster.intent = "heavy"
    (rears,) = combat.telegraph(state, content)
    assert event_sound(rears) == "screech"


def test_give_her_the_ring_and_she_leaves_you_the_philter(content):
    state, web = at_the_web(content)
    perform(state, content, f"burn:{web}")
    give = next(a for a in available_actions(state, content) if a.id.startswith("give:"))
    assert RING in give.id and give.hint == "it wants it!"
    events = perform(state, content, give.id)
    assert not state.in_combat and RING not in state.player.inventory and PHILTER in state.room.items
    assert [e.kind for e in events][:3] == ["trade", "pacify", "drop"]
    max_hp = state.player.max_hp
    perform(state, content, f"take:{PHILTER}")
    assert state.player.max_hp == max_hp + 5 and light.lamp(state, content).key == PHILTER


def test_the_ring_is_cursed_but_she_takes_it_and_no_one_else_will(content):
    from ptg.interactions import Use, plan

    state, web = at_the_web(content)
    assert "cursed" in content.item(RING).powers
    perform(state, content, f"burn:{web}")
    assert plan(state, content, Use("give", RING, f"monster:{MATRIARCH}")).run is not None
    state.room.monster.key = "goblin"  # (anyone else: it won't leave you)
    assert "cursed" in plan(state, content, Use("give", RING, "monster:goblin")).refusal


def test_killed_she_leaves_no_philter(content):
    state, web = at_the_web(content)
    perform(state, content, f"burn:{web}")
    state.room.monster.hp = 0
    combat.defeat(state, content, random.Random(1))
    assert PHILTER not in state.room.items


def test_the_philter_is_a_light_that_never_burns_down_but_no_fire(content):
    state, web = at_the_web(content, torch=False)
    state.player.inventory.append(PHILTER)
    assert light.lit(state, content) and not light.fire(state, content) and light.darkness(state, content) == ""
    assert f"burn:{web}" not in ids(state, content)


# --- their clips (the bosses' 3D pipeline: spikes/goblin3d) ----------------------------------------------------------

@pytest.mark.parametrize("key", [MATRIARCH, "humongous_fungus", "spore_mother", "rot_gill", "puff_mound"])
def test_the_underblooms_own_have_clips_made_as_the_bosses_were(key):
    """Four clips in four sizes each, the entrance landing on a frame of its own (where the sting, or her screech,
    goes)."""
    from ptg import sprites

    clips = sprites.clips(key)
    assert set(clips) == {"entrance", "idle", "attack", "windup"}
    assert {tuple(c.size for c in sizes) for sizes in clips.values()} == {(40, 48, 64, 84)}
    assert all(c.land for c in clips["entrance"])


def test_the_spore_bed_comes_in_together_and_stands_at_one_size(content):
    """The Humongous Fungus and its three, each in its own clips, all at the one size (the parts a head shorter, as
    made), each standing whole on the stage, the boss's sting as the Fungus lands; and a turn's blows swing them all."""
    state = testrooms.build(content, "humongous_fungus", "strong", seed=4)
    perform(state, content, next(a.id for a in available_actions(state, content) if a.hint == "boss"))
    fight = encounter.Fight(state, content, state.room.monster, 120, 22)
    looks = [fight.look(m.key) for m in fight.others]
    assert {fight.clips["idle"].size, *(look.clips["idle"].size for look in looks)} == {64}
    assert all(look.box[3] - look.box[1] < fight.box[3] - fight.box[1] for look in looks)
    for monster in fight.lineup():
        half = (fight._wide_as(monster) + 1) // 2
        assert half <= fight.centre(monster) <= fight.width - half
    assert "boss_encounter" in [cue for _, _, cue in fight.entrance()]
    assert len(list(fight.swing(frozenset(m.place for m in fight.lineup())))) > 1


def test_drifting_spores_dont_make_the_puff_mound_any_taller():
    """It's fitted and stood by its body (sprites.stance), not by the spores floating up off it."""
    from ptg import sprites

    idle = next(c for c in sprites.clips("puff_mound")["idle"] if c.size == 64)
    body, everything = sprites.stance("puff_mound", 64), sprites.art_box(idle.frames)
    assert body[3] == everything[3] and body[3] - body[1] < everything[3] - everything[1] - 8
