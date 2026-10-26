"""Item powers (ptg/powers.py): what trinkets and the odd weapon or armor do beyond their numbers."""

import random
from dataclasses import replace

from conftest import put_monster
from ptg import powers, rules
from ptg.content import ItemDef
from ptg.meta import souls_earned
from ptg.models import Feature, GameState
from ptg.inventory import gain
from ptg.rules import available_actions, perform
from ptg.world import generate, render_map


def player_roll(events):
    return next(e.dice for e in events if e.dice and e.dice.actor == "player")


def test_weighted_dice_add_one_to_every_roll_and_the_torch_to_searching(content):
    state = generate(3)
    put_monster(state, content, hp=200)
    state.player.inventory += ["weighted_dice", "torch"]
    assert ("Weighted Dice", 1) in player_roll(perform(state, content, "attack")).bonuses
    assert ("Torch", 1) not in player_roll(perform(state, content, "dodge")).bonuses
    state.room.monster = None
    search = player_roll(perform(state, content, "search_room")).bonuses
    assert ("Weighted Dice", 1) in search and ("Torch", 1) in search


def test_bonuses_go_only_to_their_own_rolls(content):
    state = generate(1)
    state.player.inventory += ["ten_foot_pole", "a_ring_probably_importan"]
    assert powers.roll_bonuses(state, content, "disarm") == [("Ten-Foot Pole", 2)]
    assert powers.roll_bonuses(state, content, "flee") == [("A Ring, Probably Important", 2)]
    assert powers.roll_bonuses(state, content, "attack") == []
    state.player.inventory += ["ten_foot_pole"]
    assert powers.roll_bonuses(state, content, "disarm") == [("Ten-Foot Pole", 2)]  # two count once


def test_the_stairs_curse_the_ring_and_reward_the_almanac(content):
    state = generate(3)
    state.player.inventory += ["a_ring_probably_importan", "almanac_of_future_scores"]
    state.player.fate = 0
    stairs = next(r for r in state.rooms if r.fixture == "stairs")
    state.room_id, stairs.monster = stairs.id, None
    events = perform(state, content, "descend")
    assert state.player.max_hp == 28 and state.player.fate == 1
    assert {"curse", "fate"} <= {e.kind for e in events}


def test_treasure_you_carry_out_is_worth_souls(content):
    state = generate(1)
    before = souls_earned(state)
    state.player.inventory.append("x_64gb_ddr5_ram_kit")
    assert souls_earned(state) == before + 30


def test_a_stewpot_cooks_while_you_rest(content):
    def rest(armor):
        state = generate(1)
        state.player.hp, state.player.armor = 5, armor
        rng = random.Random(4)
        rng.random = lambda: 0.99  # nothing creeps up
        return rules._rest(state, content, rng)[0].text, state.player.hp

    plain, cooked = rest(None), rest("adamant_stewpot")
    assert cooked[1] == plain[1] + 4 and "hot meal" in cooked[0]


def test_the_snitch_bites_goblins(content):
    state = generate(2)
    state.player.weapon = "snitch"
    state.player.max_hp = state.player.hp = 999
    put_monster(state, content, key="goblin", hp=500)
    hits = []
    while not hits:
        hits = [e.text for e in perform(state, content, "attack") if e.kind == "hit"]
    assert "goblin-bane" in hits[0]


def test_the_floppy_disk_hands_you_the_map(content):
    state = generate(11)
    rooms = [r for r in state.rooms if not r.secret]
    assert "".join(render_map(state)).count("[") < len(rooms)
    events = gain(state, content, "mysterious_floppy_disk")
    assert state.mapped_floor == 1 and any(e.kind == "map" for e in events)
    assert "".join(render_map(state)).count("[") == len(rooms)  # every room, but not the sealed secret one


def test_thrown_things_hit_harder_where_it_hurts_and_are_gone(content):
    state = generate(3)
    put_monster(state, content, key="troll", hp=200)  # trolls fear fire
    state.player.inventory.append("oil_flask")
    events = perform(state, content, "throw:oil_flask")
    assert player_roll(events).advantage == 1 and "oil_flask" not in state.player.inventory
    assert "fire" in state.known_weak.get("troll", []) or not player_roll(events).success


def test_a_distraction_costs_the_monster_an_attack_once_a_fight(content):
    state = generate(3)
    put_monster(state, content, hp=200)
    state.player.inventory.append("laser_pointer")
    hp = state.player.hp
    events = perform(state, content, "distract:laser_pointer")
    assert any(e.kind == "stunned" for e in events) and state.player.hp == hp
    assert "laser_pointer" in state.player.inventory  # you keep it...
    assert "distract:laser_pointer" not in {a.id for a in available_actions(state, content)}  # ...but once a fight


def test_a_glow_stick_shows_everything_hidden(content):
    state = generate(3)
    state.room.features.append(Feature(name="a loose flagstone", hidden=True, gold=10))
    state.player.inventory.append("glow_stick")
    events = perform(state, content, "reveal:glow_stick")
    assert not any(f.hidden for f in state.room.features) and "glow_stick" not in state.player.inventory
    assert any(e.kind == "secret" for e in events) and state.room.room_searched


def test_every_power_is_described(content):
    for item in content.items.values():
        assert len(powers.describe(item)) == len(item.powers) + bool(item.stats)  # (and a line for stats)
    assert set(powers.SHORT) == set(powers.POWERS)


def test_a_spare_weapon_or_armor_does_nothing_in_your_pack(content):
    """A Hard Hat's seeker, a Stewpot's cooking, any stats: only while they're on (F73). Trinkets work from the
    pack."""
    state = generate(3)
    state.room.monster = None
    state.player.armor = "chain_shirt"
    state.player.inventory += ["hard_hat", "adamant_stewpot", "torch"]
    assert powers.roll_bonuses(state, content, "search") == [("Torch", 1)]
    assert not powers.holders(state, content, "cook")
    perform(state, content, "equip:hard_hat")
    assert ("Hard Hat", 1) in powers.roll_bonuses(state, content, "search")
    buff = ItemDef(key="mighty_axe", name="Mighty Axe", kind="weapon", damage="1d8", tier=1, stats={"might": 2})
    content = replace(content, items={**content.items, buff.key: buff})
    might = state.player.might
    state.player.inventory.append("mighty_axe")
    powers.settle_stats(state, content)
    assert state.player.might == might
    perform(state, content, "equip:mighty_axe")
    assert state.player.might == might + 2


def test_putting_a_thing_down_and_taking_it_back_does_not_heal_you(content):
    """Dropping and taking back the Unusual Butter (+5 max HP), or taking off and putting on armor with max HP, gave
    the HP again each time, for no turn: 5/35 to 30/35 in five goes (W5 review). It comes the first time only."""
    state = generate(3)
    state.room.monster = None
    player = state.player
    hp, most = player.hp, player.max_hp
    state.room.items = ["unusual_butter"]
    perform(state, content, "take:unusual_butter")
    assert (player.hp, player.max_hp) == (hp + 5, most + 5)  # the first time, it comes with as much HP
    player.hp = 5
    for _ in range(5):
        perform(state, content, "drop:unusual_butter")
        assert player.max_hp == most
        perform(state, content, "take:unusual_butter")
    assert (player.hp, player.max_hp) == (5, most + 5)

    vest = ItemDef(key="hearty_vest", name="Hearty Vest", kind="armor", defense=1, tier=1, stats={"max_hp": 5})
    content = replace(content, items={**content.items, vest.key: vest})
    state.room.items.append("hearty_vest")
    perform(state, content, "take:hearty_vest")  # (straight on: there's no armor on you)
    assert (player.armor, player.hp, player.max_hp) == ("hearty_vest", 10, most + 10)
    for _ in range(4):
        perform(state, content, "unequip:armor")
        assert player.max_hp == most + 5
        perform(state, content, "equip:hearty_vest")
    assert (player.hp, player.max_hp) == (10, most + 10)
    restored = GameState.model_validate_json(state.model_dump_json())
    assert restored.player.hp_given == ["unusual_butter", "hearty_vest"]  # a save keeps track


def test_the_bomb_fairy_makes_every_bomb_found_two(content):
    """The kids' Bomb Fairy (a run ran out of bombs before the secret room): each bomb picked up counts twice."""
    state = generate(1)
    before = state.player.bombs
    gain(state, content, "bomb")
    assert state.player.bombs == before + 1
    gain(state, content, "bomb_fairy")
    events = gain(state, content, "bomb")
    assert state.player.bombs == before + 3 and "makes it two" in events[0].text
    assert "bombs count double" in powers.SHORT["twin_bombs"]


def test_the_magical_cards_hold_one_more_fate_and_deal_one_once(content):
    state = generate(1)
    player = state.player
    room, fate = player.max_fate(), player.fate
    gain(state, content, "magical_cards")
    powers.settle_stats(state, content)
    assert player.max_fate() == room + 1 and player.fate == fate + 1
    player.inventory.remove("magical_cards")  # put down...
    powers.settle_stats(state, content)
    assert player.max_fate() == room and player.fate <= room
    gain(state, content, "magical_cards")  # ...and picked up again: the room comes back, not another token
    powers.settle_stats(state, content)
    assert player.max_fate() == room + 1 and player.fate <= fate + 1
    assert "+1 Fate held" in powers.describe(content.item("magical_cards"))[-1]
