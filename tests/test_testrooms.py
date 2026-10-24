"""Test rooms (ptg/testrooms.py): straight to a character, a shop, a boss or any monster, next door, with the kit you
pick, in a run that counts for nothing."""

import pytest

from ptg import npcs, testrooms
from ptg.cli import main
from ptg.config import Config, save_path
from ptg.game import Game
from ptg.meta import record_end
from ptg.models import DELTA, Player
from ptg.rules import bombable_walls


def way_to(state):
    """Which way whoever you're testing is, from where you start."""
    here, there = state.room, testrooms.target(state)
    return next(d for d, (dx, dy) in DELTA.items() if (here.x + dx, here.y + dy) == (there.x, there.y))


async def do(game, action_id):
    action = next(a for a in game.choices() if a.id == action_id)
    return await game.act(action.label, lambda _: None, action=action)


def test_everyone_is_next_door_with_every_kit(content):
    for who in testrooms.choices(content):
        for kit in testrooms.LOADOUTS:
            state = testrooms.build(content, who, kit, seed=4)
            assert state.test_room == who and state.run_id is None and way_to(state)
            assert not (state.room.monster and state.room.monster.hostile)  # somewhere safe to stand
    assert testrooms.build(content, "goblin", floor=3, seed=4).floor == 3
    assert testrooms.build(content, "drowned_abbot", floor=1, seed=4).floor == 3  # a boss is only ever on 3
    with pytest.raises(ValueError, match="no test room"):
        testrooms.build(content, "nobody")


async def test_lenny_wants_the_tooth_in_your_pack(content, profile):
    state = testrooms.build(content, "lenny", "new", seed=4)
    game = Game(state, Config(backend="offline"), None, content, profile)
    await do(game, f"go:{way_to(state)}")
    await do(game, "lenny")
    assert npcs.GOOD_TOOTH in state.player.inventory


async def test_swoogy_is_behind_a_wall_with_a_bomb_for_it(content, profile):
    state = testrooms.build(content, "swoogy", "new", seed=4)
    assert bombable_walls(state) == [way_to(state)] and state.player.bombs >= 1
    game = Game(state, Config(backend="offline"), None, content, profile)
    await do(game, f"bomb:{way_to(state)}")
    await do(game, f"go:{way_to(state)}")
    assert state.room.secret and "swoogy" in [a.id for a in game.choices()]


async def test_a_shop_door_and_a_key_for_it(content, profile):
    for who, keeper in (("shop", "granny_gristle"), ("shiny_shop", "granny_kamultruk")):
        state = testrooms.build(content, who, "strong", seed=4)
        game = Game(state, Config(backend="offline"), None, content, profile)
        await do(game, f"go:{way_to(state)}")
        assert state.room.shop.keeper == keeper and "shop" in [a.id for a in game.choices()]


async def test_a_boss_behind_its_door_with_its_key(content, profile):
    state = testrooms.build(content, "goblin_king", "strong", seed=4)
    assert content.themes[state.theme].key_item in state.player.inventory
    game = Game(state, Config(backend="offline"), None, content, profile)
    await do(game, f"go:{way_to(state)}")
    assert state.room.is_boss and state.room.monster.key == "goblin_king"


def test_the_kits(content):
    assert testrooms.build(content, "goblin", "new", seed=4).player == Player(name="Tester")
    strong = testrooms.build(content, "goblin", "strong", seed=4).player
    assert (strong.weapon, strong.armor, strong.level, len(strong.perks)) == ("silvered_blade", "scale_hauberk", 5, 4)
    assert strong.inventory.count("superior_healing_potion") == 3 and (strong.bombs, strong.keys) == (3, 2)
    random_one = testrooms.build(content, "goblin", "random", floor=2, seed=4).player
    assert random_one.level == 3 and len(random_one.perks) == 2 and random_one.xp == 55
    own = testrooms.build(content, "goblin", "weapon=war_pick, items=pickle+pickle+holy_water, level=2, gold=9",
                          seed=4).player
    assert (own.weapon, own.inventory, own.level, own.gold) == ("war_pick", ["pickle", "pickle", "holy_water"], 2, 9)
    with pytest.raises(ValueError, match="a kit is"):
        testrooms.build(content, "goblin", "sword=big")
    with pytest.raises(ValueError, match="no item 'a_unicorn'"):
        testrooms.build(content, "goblin", "items=a_unicorn")
    with pytest.raises(ValueError, match="'pickle' isn't a weapon"):
        testrooms.build(content, "goblin", "weapon=pickle")
    assert testrooms.build(content, "shop", "new", seed=4).player.gold == testrooms.SHOP_GOLD  # something to spend
    assert testrooms.describe(content, testrooms.build(content, "lenny", "strong", seed=4))[0][1].startswith(
        "Lucky Lenny, ")


async def test_a_test_room_counts_for_nothing(content, profile):
    state = testrooms.build(content, "goblin", "strong", seed=4)
    game = Game(state, Config(backend="offline"), None, content, profile)
    assert not game.autosave
    await do(game, f"go:{way_to(state)}")
    state.room.monster.hp, state.player.might = 1, 50
    while state.room.monster:  # (a 1 on the die still misses)
        await do(game, "attack")
    assert state.room.monster is None and state.player.kills == 1
    assert not save_path().exists()  # your real run's save is left alone
    assert profile.bestiary() == {} and profile.runs() == [] and profile.souls == 0
    state.status = "dead"
    assert record_end(profile, state) == 0 and profile.runs() == [] and profile.souls == 0  # no ghost, no souls


def test_the_command_line_lists_them(capsys):
    main(["--test-room", "list"])
    out = capsys.readouterr().out
    assert "lenny" in out and "shiny_shop" in out and "goblin_king" in out and "Kits: new" in out


def test_the_tooth_or_the_key_in_your_pack_is_the_only_one(content):
    """18 Lenny test rooms in 60 hid a second tooth on the floor, and Lenny let slip where it was while you held one."""
    def on_the_floor(state, key):
        return sum(r.items.count(key) + sum(f.loot.count(key) for f in r.features) for r in state.rooms)

    for seed in range(60):
        state = testrooms.build(content, "lenny", "strong", seed=seed)
        assert state.player.inventory.count(npcs.BAD_TOOTH) == 1 and on_the_floor(state, npcs.BAD_TOOTH) == 0
        assert npcs.tooth_spot(state) is None
    for seed in range(10):
        state = testrooms.build(content, "goblin_king", "new", seed=seed)
        assert on_the_floor(state, content.themes[state.theme].key_item) == 0


async def test_lenny_still_missing_his_tooth(content, profile):
    """The Lenny room always put his tooth in your pack, so the half of his quest a player meets first (Lenny without
    it, his telling you where, finding it) couldn't be tried (F79)."""
    for seed in range(20):
        state = testrooms.build(content, "lenny_quest", "strong", seed=seed)
        teeth = [(r, f) for r in state.rooms for f in r.features if npcs.BAD_TOOTH in f.loot]
        assert npcs.BAD_TOOTH not in state.player.inventory and len(teeth) == 1 and teeth[0][1].hidden
        assert teeth[0][0] not in (state.room, testrooms.target(state)) and state.quests == {}
    state = testrooms.build(content, "lenny_quest", "new", seed=4)
    game = Game(state, Config(backend="offline"), None, content, profile)
    result = await do(game, f"go:{way_to(state)}")
    assert [e.data["moment"] for e in result.events if e.kind == "story"] == ["meet"]
    result = await do(game, f"talk:{npcs.LENNY}")
    assert any(e.kind == "tip" for e in result.events) and npcs.tooth_spot(state) is None  # (on your map now)


def test_lenny_with_his_tooth_is_as_if_you_found_it_first(content):
    state = testrooms.build(content, "lenny", "new", seed=4)
    assert state.quests == {npcs.LENNY: "found_item"} and testrooms.floor_for(content, "lenny_quest") == 1
    assert testrooms.build(content, "lenny_quest", "new", floor=2, seed=4).floor == 2  # (his floor can be 1 or 2)
