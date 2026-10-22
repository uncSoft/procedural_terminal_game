import random

from ptg.meta import epithet, make_player, record_end, share_card, souls_earned, start_run
from ptg.world import generate


def test_buying_unlocks_costs_souls(profile, content):
    assert profile.souls == 0 and not profile.buy("vigor", 40)
    profile.add_souls(100)
    assert profile.buy("vigor", 40) and profile.souls == 60
    assert not profile.buy("vigor", 40)  # already owned
    assert "vigor" in profile.unlocked() and "coin_bag" in profile.unlocked()


def test_blessings_and_gifts_shape_the_adventurer(profile, content):
    profile.add_souls(500)
    for key in ("vigor", "fortune", "oil_flask"):
        profile.buy(key, content.unlocks[key].cost)
    player = make_player("Chubrock", profile, content, gift="oil_flask")
    assert player.max_hp == 35 and player.fate == 2 and "oil_flask" in player.inventory
    assert set(player.blessings) == {"vigor", "fortune"}
    # An unowned gift falls back to the coin bag.
    assert make_player("X", profile, content, gift="lucky_charm").gold == 15


def test_a_finished_run_banks_souls_and_leaves_a_ghost(profile, content):
    state = start_run(profile, content, "Chubrock", seed=3)
    state.souls, state.player.gold = 20, 55
    state.status, state.cause, state.floor = "dead", "slain by Troll on floor 2", 2
    souls = record_end(profile, state)
    assert souls == souls_earned(state) == 25 and profile.souls == 25
    run = profile.runs()[0]
    assert run["status"] == "dead" and run["floor"] == 2 and "Chubrock" in run["epitaph"]
    ghost = profile.pick_ghost(random.Random(0), chance=1.0)
    assert ghost["name"] == "Chubrock" and ghost["floor"] == 2 and "rusty_sword" in ghost["items"]
    profile.rest_ghost(ghost["id"])
    assert profile.pick_ghost(random.Random(0), chance=1.0) is None


def test_ghosts_show_up_in_later_runs(profile, content):
    profile.add_ghost(1, "Chubrock", 2, 1, ["hand_axe"], 30, "Tried to tax a rat.", "slain by Giant Rat")
    haunted = 0
    for seed in range(20):
        state = start_run(profile, content, "Next", seed=seed)
        haunted += any(r.monster and r.monster.ghost_of == "Chubrock" for r in state.rooms)
    assert 0 < haunted < 20


def test_bestiary_remembers(profile):
    assert profile.bump_beast("goblin", "seen") == 1
    assert profile.bump_beast("goblin", "seen") == 2
    profile.add_weakness("goblin", "shiny")
    profile.add_weakness("goblin", "shiny")
    profile.set_lore("goblin", "Loves coins.")
    entry = profile.bestiary()["goblin"]
    assert entry["weak"] == ["shiny"] and entry["lore"] == "Loves coins." and entry["seen"] == 2
    assert profile.weaknesses() == {"goblin": ["shiny"]}


def test_daily_runs_share_a_seed_and_skip_ghosts(profile, content):
    profile.add_ghost(1, "Chubrock", 2, 1, [], 0, "", "")
    a = start_run(profile, content, "A", daily=True)
    b = start_run(profile, content, "B", daily=True)
    assert a.seed == b.seed and a.daily and a.ghost is None
    a.status = "won"
    record_end(profile, a)
    assert profile.daily_run(a.daily)["name"] == "A"
    assert "Daily" in share_card(a)


def test_epithet_follows_play_style(content):
    state = generate(1)
    assert epithet(state) == "the Brief"
    state.player.style.update({"pacify": 3, "kills": 1})
    assert epithet(state) == "the Silver-Tongued"
