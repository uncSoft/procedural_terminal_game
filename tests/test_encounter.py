"""Combat as an event (docs/plans/combat-and-balance.md §2-3): the balance pass's rules, what a monster will do next
and how dangerous it looks, winning in style, the stage's fight view, and how a fight is told."""

import random

import pytest
from rich.text import Text

from conftest import put_monster
from ptg import combat, encounter, interactions, loot, npcs
from ptg.config import Config
from ptg.events import Action, Event
from ptg.game import Game
from ptg.models import MonsterState
from ptg.rules import perform
from ptg.world import DEPTH, build_floor, depth, generate, tier_for, warden_tier


# --- the balance pass ---------------------------------------------------------------------------------------------

def test_monster_tiers_follow_how_far_down_the_run_is():
    """Floor 1 is all tier 1 and floor 2 all tier 2 (a newcomer met tier 3 on floor 2 and died there half the time);
    the top tier from three quarters of the way down, on runs of any length."""
    assert [tier_for(f, 4) for f in range(1, 5)] == [1, 2, 3, 3]
    assert [tier_for(f, 6) for f in range(1, 7)] == [1, 1, 2, 2, 3, 3]
    assert [tier_for(f, 12) for f in (1, 4, 5, 9, 12)] == [1, 1, 2, 3, 3]
    assert [warden_tier(f, 4) for f in range(1, 5)] == [2, 2, 3, 3]


def test_the_deeper_floors_make_monsters_stronger_and_a_longer_run_keeps_the_deepest():
    assert depth(1) == depth(2) == {}
    assert depth(3)["damage_mod"] == 1 and depth(4)["attack_mod"] == 1
    assert depth(9) == DEPTH[max(DEPTH)]


def test_ruthless_doubles_the_weapons_dice_not_every_bonus(content):
    """The run's Ruthless doubled +5 might, +3 Glass Cannon and the rest too: 36-44 a swing."""
    state = generate(3)
    player = state.player
    player.perks, player.might, player.hits_landed = ["ruthless", "glass_cannon"], 50, 2  # (the third hit lands)
    put_monster(state, content, key="troll", hp=500)
    events = combat.player_attack(state, content, random.Random(9))
    hit = next(e for e in events if e.kind == "hit")
    parts = dict(hit.dice.damage)
    weapon = content.item(player.weapon).damage
    dice_rolled = parts[weapon] + parts.get(f"crit {weapon}", 0)
    assert parts["ruthless ×2"] == dice_rolled  # (not might, nor glass cannon)


def test_acrobatics_doesnt_take_a_heavy_blow(content):
    state = generate(3)
    state.player.perks = ["acrobatics"]
    state.player.agility = -50
    put_monster(state, content, key="hobgoblin", intent="heavy")
    events = combat.monster_turn(state, content, random.Random(1))
    assert any(e.kind == "monster_hit" for e in events) and not any(e.kind == "evade" for e in events)
    state.room.monster.intent = "strike"
    assert any(e.kind == "evade" for e in combat.monster_turn(state, content, random.Random(1)))


def test_a_character_cut_down_to_size_pays_xp_for_its_size(content):
    """Swoogy on floor 1 paid his full 120 XP: two levels at once."""
    state = generate(3)
    state.room.monster = npcs.sized(content, npcs.SWOOGY, 1, npcs.SWOOGY_SIZE, hostile=True, mood="angry")
    xp = state.player.xp
    combat.defeat(state, content, random.Random(1))
    hp = npcs.SWOOGY_SIZE[1][0]
    assert state.player.xp - xp == round(content.monster(npcs.SWOOGY).xp * hp / content.monster(npcs.SWOOGY).hp)


def test_a_chest_doesnt_hand_you_a_second_of_your_gear_while_it_has_anything_else(content):
    """A chest's "weapon 3+" with your Silvered Blade the only one gave a second (the 10-28 run)."""
    have = ["silvered_blade"]
    for seed in range(40):
        key = loot.produce(random.Random(seed), content, [], ["weapon 3+", "potion 1"], "chest", have)
        assert key != "silvered_blade", seed


def test_a_monster_named_for_its_venom_isnt_called_venomous_twice(content):
    from ptg.world import monster_for

    norfel = next(k for k, t in content.themes.items() if t.status == "poison")
    for seed in range(60):
        monster = monster_for(random.Random(seed), content, norfel, 3, floor=4)
        assert "Venomous Venom" not in monster.name
        assert ("venom" in monster.tricks) == ("venom" in monster.name.lower())


def test_rarer_rare_things_from_wardens(content, monkeypatch):
    """A warden leaves something rare a third of the time, a small key or a bomb otherwise."""
    state = generate(5)
    state.floor = 2
    build_floor(state, content)
    stairs = next(r for r in state.rooms if r.fixture == "stairs")
    state.room_id = stairs.id
    rng = random.Random(1)
    rng.random = lambda: 0.5  # (over WARDEN_DROP: no rare thing; and no potion, key or bomb from its pockets)
    dropped = [e.data["item"] for e in combat.defeat(state, content, rng) if e.kind == "drop"]
    assert loot.WARDEN_DROP < 0.5 and dropped and set(dropped) <= {*loot.WARDEN_ELSE}


# --- what it'll do next, and how dangerous it looks ---------------------------------------------------------------

def test_a_monsters_next_move_is_shown_with_what_it_would_cost(content):
    state = generate(3)
    goblin = put_monster(state, content, key="goblin")
    seen = combat.foresee(state, content)
    assert (seen.kind, seen.low, seen.high) == ("strike", 1, 6) and seen.said() == "⚔ 1–6"
    goblin.intent = "heavy"
    goblin.damage_mod = 1
    seen = combat.foresee(state, content)
    assert (seen.kind, seen.low, seen.high, seen.words) == ("heavy", 3, 13, "HEAVY")  # its dice twice, +1
    goblin.intent = "guard"
    assert combat.foresee(state, content).kind == "guard"
    goblin.stunned = 1
    assert combat.foresee(state, content).said() == "✶ REELING"
    toad = put_monster(state, content, key="serpentis", intent="heavy")
    assert "spit" in combat.foresee(state, content).tricks and "venom" in combat.foresee(state, content).tricks
    toad.hostile = False
    assert combat.foresee(state, content) is None


def test_how_dangerous_a_fight_looks(content):
    state = generate(3)
    put_monster(state, content, key="giant_rat")
    assert combat.danger(state, content) == 1
    put_monster(state, content, key="goblin_king")
    assert combat.danger(state, content) == 3
    state.player.level, state.player.might, state.player.max_hp = 8, 9, 90
    assert combat.danger(state, content) < 3  # (against you: stronger, it's less)


# --- winning in style -----------------------------------------------------------------------------------------------

def test_a_flawless_win_and_one_with_its_weakness_pay_more(content):
    state = generate(3)
    goblin = put_monster(state, content, key="goblin", hp=1)
    goblin.swings = 2  # (it went for you twice, and never drew blood)
    xp, gold = state.player.xp, state.player.gold
    events = combat.defeat(state, content, random.Random(1), exploited=True)
    styles = [e.data["style"] for e in events if e.kind == "style"]
    assert styles == ["flawless", "exploited"]
    base = next(e for e in events if e.kind == "defeat").data["xp"]
    assert state.player.xp - xp == base + 2 * max(1, round(base * combat.STYLE_XP))
    assert state.player.style["flawless"] == 1

    hurt = put_monster(state, content, key="goblin", hp=1)
    hurt.swings, hurt.dealt = 1, 3
    assert not [e for e in combat.defeat(state, content, random.Random(1)) if e.kind == "style"]
    never = put_monster(state, content, key="goblin", hp=1)  # (one it never had a go at you: nothing to boast of)
    assert not [e for e in combat.defeat(state, content, random.Random(1)) if e.kind == "style"]
    assert never.swings == 0


def test_the_killing_blow_with_a_weakness_is_exploited(content):
    state = generate(3)
    state.player.might = 50
    put_monster(state, content, key="skeleton", hp=1)  # (weak to heavy and holy)
    state.player.weapon = next(k for k, i in content.items.items() if i.kind == "weapon" and "heavy" in i.tags)
    events = perform(state, content, "attack")
    while state.room.monster:
        events = perform(state, content, "attack")
    assert any(e.kind == "style" and e.data["style"] == "exploited" for e in events)


def test_the_spoils_are_read_from_the_kill(content):
    state = generate(3)
    goblin = put_monster(state, content, key="goblin", hp=1)
    goblin.swings = 1
    events = combat.defeat(state, content, random.Random(2))
    spoils = encounter.Spoils.of(events, "Goblin")
    assert spoils.xp == content.monster("goblin").xp and spoils.styles and spoils.gold > 0
    assert spoils.all_xp > spoils.xp and spoils.all_gold > spoils.gold
    assert encounter.Spoils.of([Event("hit", "")], "Goblin") is None


# --- the stage's pictures -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("rows", [8, 15, 30])
def test_the_fight_view_fits_its_stage(content, rows):
    state = generate(7)
    monster = put_monster(state, content, key="troll", intent="heavy")
    fight = encounter.Fight(state, content, monster, 90, rows, known=["fire"])
    still = fight.still()
    lines = still.plain.split("\n")
    assert len(lines) == rows and all(len(line) == 90 for line in lines)
    assert "Troll" in still.plain and "☠" in still.plain
    assert ("HEAVY" in still.plain) == (rows >= 7)
    assert fight.scale in ((1.5, 2.0) if rows >= 30 else (1.0,) if rows >= 12 else (0.5,))
    frames = [frame for frame, _, _ in fight.entrance()]
    assert len(frames) == 8 and "Troll" not in frames[0].plain and "Troll" in frames[-1].plain
    assert len(list(fight.shatter())) == encounter.SHATTER_FRAMES


def test_the_spoils_card_and_the_wipe(content):
    state = generate(7)
    monster = put_monster(state, content, key="goblin")
    fight = encounter.Fight(state, content, monster, 80, 16)
    spoils = encounter.Spoils("Goblin", xp=10, souls=3, gold=4, styles=[("Flawless", 2, 3)],
                              drops=["healing_potion", next(k for k, i in content.items.items() if loot.rare(i))],
                              levels=[2])
    card = encounter.spoils_text(fight.empty(), spoils, content, 2, 40).plain
    assert "SPOILS" in card and "LEVEL 2" in card and "+7 gold" in card and "FLAWLESS" in card
    assert "Healing Potion" in card
    assert "Healing Potion" not in encounter.spoils_text(fight.empty(), spoils, content, 2, 40, step=1).plain
    room = fight.empty()
    frames = encounter.wipe(card_text := encounter.spoils_text(fight.empty(), spoils, content, 2, 40), room)
    assert frames[-1].plain == room.plain and card_text.plain != room.plain


# --- a boss's own entrance ---------------------------------------------------------------------------------------

def test_the_goblin_king_has_an_entrance_and_an_idle_in_three_sizes():
    from ptg import sprites

    clips = sprites.clips("goblin_king")
    assert set(clips) == {"entrance", "idle", "attack", "windup"}
    assert {tuple(c.size for c in sizes) for sizes in clips.values()} == {(40, 48, 64)}
    assert (len(clips["attack"][0].frames), clips["attack"][0].land, len(clips["windup"][0].frames)) == (20, 6, 11)
    entrance = clips["entrance"][1]
    assert len(entrance.frames) == 73 and entrance.fps == 24 and entrance.land == 8
    assert entrance.frames[0].getbbox() is None  # (he drops in from above: nothing there at first)
    assert len(clips["idle"][0].frames) == 24
    assert sprites.clips("goblin") == {}
    mouse = sprites.clips("king_mouse")
    assert set(mouse) == {"entrance", "idle", "attack", "windup"} and [c.size for c in mouse["idle"]] == [40, 48, 64, 84]
    assert (mouse["entrance"][0].land, mouse["attack"][0].land) == (10, 8)
    stands = [(box := sprites.art_box(c.frames))[3] - box[1] for c in mouse["idle"]]
    assert stands == [21, 25, 32, 42]  # (the heights the stage picks from: docs/plans/combat-and-balance.md §9)


@pytest.mark.parametrize("boss", ["serpentis", "drowned_abbot", "thornmother"])
def test_every_other_boss_drops_in_too(boss):
    """Their clips came from the same Blender pipeline: Serpentis drops in and lands coiled, rears for a heavy blow
    and strikes to the side; the Abbot drops in with a splash, raises his crozier and brings it down; the
    Thornmother's bud blooms as she lands, and she lashes out with a vine."""
    from ptg import sprites

    clips = sprites.clips(boss)
    assert set(clips) == {"entrance", "idle", "attack", "windup"}
    assert {tuple(c.size for c in sizes) for sizes in clips.values()} == {(40, 48, 64, 84)}
    entrance = clips["entrance"][1]
    assert (len(entrance.frames), entrance.fps, entrance.land) == (72, 24, 10)
    assert [len(clips[clip][0].frames) for clip in ("idle", "attack", "windup")] == [24, 20, 10]


def test_a_boss_with_an_entrance_clip_drops_in_and_stands_in_its_idle(content):
    """The stage plays the clip (every frame of it, 24 a second, as made), the sting on the frame its feet
    land, then its banner; and it fights in the clip's idle, at the biggest size whose standing art fits."""
    state = generate(7)
    king = put_monster(state, content, key="goblin_king")
    fight = encounter.Fight(state, content, king, 110, 16)
    assert fight.clips["idle"].size == 48 and fight.scale == 1.0
    frames = list(fight.entrance())
    assert len(frames) == len(fight.clips["entrance"].frames) + 1  # (every frame of it, as made)
    assert [i for i, (_, _, cue) in enumerate(frames) if cue in encounter.STINGS] == [8]  # (the frame his feet land)
    assert frames[8][2] == "boss_encounter"
    assert all(seconds == pytest.approx(1 / 24) for _, seconds, _ in frames[:-1])
    assert "Goblin King" not in frames[0][0].plain and "Goblin King" in frames[-1][0].plain
    assert fight.foe(0).tobytes() != fight.foe(1).tobytes()  # (it breathes: its idle's first and middle)
    assert len(list(fight.shatter())) == encounter.SHATTER_FRAMES

    big = encounter.Fight(state, content, king, 120, 24)
    assert big.clips["idle"].size == 64
    tiny = encounter.Fight(state, content, king, 60, 8)  # (no room for even the smallest: the sprite, sweeping in)
    assert not tiny.clips and [s for _, s, _ in list(tiny.entrance())[:7]] == [0.035] * 7


def test_a_boss_is_called_out_by_name_as_it_lands(content, monkeypatch):
    """After it lands, a boss's name is spelled out on a card where its banner will be, a tick for each frame of it,
    and what it's boss of under it; then the banner. One that sweeps in (no clip) gets its card once it's there."""
    state = generate(7)
    state.theme = "goblin_warren"
    king = put_monster(state, content, key="goblin_king")
    fight = encounter.Fight(state, content, king, 110, 16)
    frames = list(fight.entrance())
    cues = [cue for _, _, cue in frames]
    spelled = -(-len("T H E   G O B L I N   K I N G") // encounter.SPELL)
    assert cues[8:8 + spelled] == ["boss_encounter"] + ["dice_tick"] * (spelled - 1) and not any(cues[8 + spelled:])
    assert "✦" not in frames[7][0].plain and "✦  T H" in frames[8][0].plain  # (SPELL letters a frame, from landing)
    card = frames[8 + spelled][0].plain
    assert "T H E   G O B L I N   K I N G" in card and "BOSS OF THE GOBLIN WARREN" in card
    assert "✦" not in frames[-1][0].plain and "The Goblin King" in frames[-1][0].plain

    thornmother = put_monster(state, content, key="thornmother")
    with monkeypatch.context() as bare:  # (every boss has its clips now: one without sweeps in)
        bare.setattr(encounter.sprites, "clips", lambda key: {})
        swept = list(encounter.Fight(state, content, thornmother, 110, 16).entrance())
    assert [cue for _, _, cue in swept][7] == "boss_encounter" and "T H O R N M O T H E R" in swept[-2][0].plain
    mouse = state.room.monster = npcs.sized(content, npcs.KING_MOUSE, 2, npcs.KING_MOUSE_SIZE, warden=True)
    guarded = list(encounter.Fight(state, content, mouse, 110, 16).entrance())  # (a guardian is called out too)
    assert "K I N G   M O U S E" in guarded[-2][0].plain and "GUARDIAN OF THE STAIRS" in guarded[-2][0].plain
    assert [cue for _, _, cue in guarded].count("boss_encounter") == 1
    goblin = put_monster(state, content, key="goblin")
    plain = list(encounter.Fight(state, content, goblin, 110, 16).entrance())
    assert [cue for _, _, cue in plain] == [""] * 7 + ["encounter"] and "✦" not in plain[-1][0].plain


def test_the_kings_own_swing_and_his_pan_held_high_for_a_heavy_blow(content):
    """His attack clip (the swing at the end of his fall) plays when he goes for you, in place of the lunge; and with
    a heavy blow coming he holds the pan high (his windup clip), glowing as any monster does."""
    state = generate(7)
    king = put_monster(state, content, key="goblin_king")
    fight = encounter.Fight(state, content, king, 110, 16)
    swing = list(fight.swing())
    assert len(swing) == 20 and all(seconds == pytest.approx(1 / 24) for _, seconds in swing)
    assert fight.foe(0, "windup").tobytes() != sprites_posed(fight, "windup")
    goblin = encounter.Fight(state, content, put_monster(state, content, key="goblin"), 110, 16)
    assert list(goblin.swing()) == []


def sprites_posed(fight, pose):
    """The King's idle frame in a pose, without his windup clip: what he'd look like without it."""
    from ptg import sprites

    return sprites.posed(fight.clips["idle"].frames[0], pose, 0).tobytes()


def test_make_clip_writes_a_strip_with_its_count_speed_and_landing(tmp_path):
    import sys

    from PIL import Image

    sys.path.insert(0, "tools")
    from make_clip import make
    from ptg import sprites

    folder = tmp_path / "frames"
    folder.mkdir()
    for i, top in enumerate([None, None, 0, 4, 8, 8]):  # (empty, empty, falling, falling, landed, standing)
        frame = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        if top is not None:
            frame.paste((200, 60, 60, 255), (6, top, 10, top + 8))
        frame.save(folder / f"{i:04d}.png")
    made = make(folder, "test_monster", "entrance", 24, out=tmp_path / "clips")
    strip = Image.open(made)
    assert made.name == "entrance.16.png" and strip.size == (96, 16)
    assert (strip.info["frames"], strip.info["fps"], strip.info["land"]) == ("6", "24", "4")
    assert sprites.count_frames(strip) == 6
    swing = Image.open(make(folder, "test_monster", "attack", 24, out=tmp_path / "clips", spans="2:4,5:", land=1))
    assert (swing.size, swing.info["frames"], swing.info["land"]) == ((48, 16), "3", "1")


# --- what a click is told as ----------------------------------------------------------------------------------------

def test_a_pickers_option_is_told_as_the_whole_use(content):
    """The run's first move threw its potion at a Lantern Moth, told only as "Healing Potion"."""
    state = generate(3)
    put_monster(state, content, key="lantern_moth")
    option = next(a for a in interactions.choices(state, content, "use:@monster:lantern_moth")
                  if a.id.startswith("use:healing_potion"))
    assert option.label == "Healing Potion"
    assert interactions.said(state, content, option) == "Throw the Healing Potion at the Lantern Moth"
    assert interactions.said(state, content, Action("attack", "Attack the Lantern Moth")) == "Attack the Lantern Moth"


def test_one_click_in_a_fight_never_throws_away_what_heals(content):
    from ptg.ui.grid import wasted

    assert wasted(content, "use:healing_potion@monster:lantern_moth")
    assert not wasted(content, "use:holy_water@monster:lantern_moth")
    assert not wasted(content, "use:healing_potion")  # (drinking it, from Heal, is another thing)


# --- how a fight is told ----------------------------------------------------------------------------------------------

async def test_a_fights_blow_for_blow_goes_by_in_a_line(content, fake_llm, profile):
    """With a narrator, the opening and the end of a fight are told in prose; the blows between, in a line."""
    from ptg.world import generate as fresh

    llm = fake_llm(text="Prose.")
    game = Game(fresh(3), Config(backend="offline"), llm, profile=profile)
    troll = put_monster(game.state, game.content, key="troll", hp=200)
    player = game.state.player
    player.max_hp = player.hp = 10_000
    told = []
    for _ in range(3):
        troll.intent, player.fate = "strike", player.max_fate()  # (no perfect dodge, no Fate for a 20: nothing new)
        await game.begin("1", Action("dodge", "Dodge"))
        told.append((await game.finish(lambda _: None)).narration)
    assert "Prose." not in told and all(told)  # (a dodge and its blow: in a line)
    game.state.player.might = 500
    await game.begin("1", Action("attack", "Attack the Troll"))
    assert (await game.finish(lambda _: None)).narration == "Prose."  # (the end of it: told)


# --- on the screen ------------------------------------------------------------------------------------------------

async def test_a_fight_comes_in_on_the_stage_and_ends_with_its_spoils(monkeypatch):
    """A foe walked in on sweeps onto the dimmed stage, its next move over it and its banner under it; slain, it breaks
    apart, its spoils come up, and the room sweeps back in."""
    from test_ui import into_a_run, take_choice

    from ptg.ui.app import PTGApp

    entrances, spoiled = [], []
    entrance, shatter = encounter.Fight.entrance, encounter.Fight.shatter
    monkeypatch.setattr(encounter.Fight, "entrance",
                        lambda self, *a, **kw: entrances.append(1) or entrance(self, *a, **kw))
    monkeypatch.setattr(encounter.Fight, "shatter", lambda self, *a, **kw: spoiled.append(1) or shatter(self, *a, **kw))
    app = PTGApp(Config(backend="offline", layout="grid", player_name="T", auto_roll=True), seed=1)
    async with app.run_test(size=(160, 50)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        direction = next(d for d, e in state.room.exits.items() if not e.locked)
        there = state.rooms[state.room.exits[direction].to]
        there.monster = MonsterState(key="goblin", name="Goblin", hp=8, max_hp=8)
        await take_choice(app, pilot, screen, f"go:{direction}")
        stage = str(screen.query_one("#stage-art").render())
        assert entrances and screen.fight is not None
        assert "Goblin" in stage and "☠" in stage and "⚔" in stage

        state.player.might = 50
        for _ in range(4):
            if not state.room.monster:
                break
            await take_choice(app, pilot, screen, "attack")
        assert state.room.monster is None and spoiled and screen.fight is None
        assert "Goblin" not in str(screen.query_one("#stage-art").render())  # (the room again)


def test_a_foe_with_clips_stands_in_its_whole_idle_played_through(content):
    """The stage plays a clip-made foe's idle through, a frame a tick (still's `tick`), not two pictures taking turns;
    one without clips has nothing to loop."""
    state = generate(7)
    king = put_monster(state, content, key="goblin_king")
    fight = encounter.Fight(state, content, king, 110, 16)
    idle = fight.clips["idle"].frames
    assert fight.loops()
    assert [fight.foe(0, tick=t).tobytes() for t in range(len(idle))] == [frame.tobytes() for frame in idle]
    assert fight.foe(0, tick=len(idle)).tobytes() == idle[0].tobytes()  # (round again)
    goblin = encounter.Fight(state, content, put_monster(state, content, key="goblin"), 110, 16)
    assert not goblin.loops()


async def test_clips_play_at_their_own_speed_however_long_a_frame_takes_to_draw():
    import time

    from ptg.ui.effects import paced

    def frames():
        for i in range(10):
            time.sleep(0.01)  # (as long as drawing a big stage might take)
            yield i, 0.02
    start = time.monotonic()
    shown = [i async for i, _ in paced(frames())]
    took = time.monotonic() - start
    assert shown == list(range(10)) and took < 0.27  # (10 × 0.02 s, not 10 × 0.03 s)


async def _in_the_kings_fight(app, pilot):
    """Through the test room's boss door, into the Goblin King's fight, its entrance over: the screen."""
    from ptg.rules import available_actions
    from ptg.ui.game_screen import GameScreen

    for _ in range(80):
        await pilot.pause(0.1)
        if isinstance(app.screen, GameScreen) and not app.screen.busy:
            break
    screen = app.screen
    door = next(a for a in available_actions(screen.game.state, screen.game.content) if a.hint == "boss")
    screen.press(door)
    for _ in range(80):
        await pilot.pause(0.1)
        if screen.game.state.in_combat and not screen.busy and not screen.animating:
            break
    return screen


def _kings_test_room():
    from ptg.config import Config
    from ptg.ui.app import PTGApp

    return PTGApp(Config(backend="offline", layout="tabs", player_name="T", auto_roll=True),
                  test_room=("goblin_king", "strong", 0))


async def test_the_stage_loops_a_boss_through_its_idle_in_a_fight():
    app = _kings_test_room()
    async with app.run_test(size=(150, 45)) as pilot:
        screen = await _in_the_kings_fight(app, pilot)
        ticks = screen.loop_tick
        await pilot.pause(1.0)
        assert screen.looping and screen.loop_tick - ticks >= 10  # (many frames a second, not one every 0.6)


async def test_the_stage_loop_plays_on_through_a_turn_but_not_over_the_stages_own_moments():
    """Run 66: the Fungus and its three stood frozen through every turn (the dice, the beat before their go, the
    words being written), seconds at a time. Only the stage's own moments (a blow, a fall) hold it, and a fight
    left behind (fled) isn't drawn over the room you're in."""
    app = _kings_test_room()
    async with app.run_test(size=(150, 45)) as pilot:
        screen = await _in_the_kings_fight(app, pilot)
        state = screen.game.state
        screen.busy = True  # (a turn underway)
        ticks = screen.loop_tick
        await pilot.pause(0.5)
        assert screen.loop_tick - ticks >= 5
        screen.animating = True  # (a blow on the stage)
        ticks = screen.loop_tick
        await pilot.pause(0.3)
        assert screen.loop_tick == ticks
        screen.animating = False
        here, state.room_id = state.room_id, next(r.id for r in state.rooms if r.id != state.room_id)
        await pilot.pause(0.3)
        assert screen.loop_tick == ticks
        state.room_id, screen.busy = here, False


def test_a_wipe_goes_up_or_down_as_well_as_across():
    old, new = Text("aaaa\naaaa\naaaa\naaaa"), Text("bbbb\nbbbb\nbbbb\nbbbb")
    down = encounter.wipe(old, new, steps=4, up=1)  # (going north: the next room from the top)
    assert down[0].plain.split("\n")[0] == "bbbb" and down[0].plain.split("\n")[-1] == "aaaa"
    assert down[-1].plain == new.plain
    rising = encounter.wipe(old, new, steps=4, up=-1)  # (south: from the bottom)
    assert rising[0].plain.split("\n")[-1] == "bbbb" and rising[0].plain.split("\n")[0] == "aaaa"


async def test_walking_through_a_door_wipes_the_next_room_in_from_that_way(monkeypatch):
    from test_ui import into_a_run, take_choice

    from ptg.ui.app import PTGApp

    wiped = []
    real = encounter.wipe
    monkeypatch.setattr(encounter, "wipe", lambda *a, **kw: wiped.append((kw.get("side"), kw.get("up"))) or
                        real(*a, **kw))
    app = PTGApp(Config(backend="offline", layout="tabs", player_name="T", auto_roll=True), seed=1)
    async with app.run_test(size=(160, 50)) as pilot:
        screen = await into_a_run(app, pilot)
        state = screen.game.state
        for room in state.rooms:
            room.monster, room.others = None, []
        way = next(d for d, e in state.room.exits.items() if not e.shut)
        for _ in range(50):  # (the room's on the stage first: a busy machine may take a moment to draw it)
            if screen.stage_still is not None:
                break
            await pilot.pause(0.1)
        await pilot.pause(2.5)  # (past a beat of the stage: a room where nothing moves stops keeping a second frame)
        here = state.room_id
        await take_choice(app, pilot, screen, f"go:{way}")
        for _ in range(50):  # (and the move made: on a busy machine the turn may not have begun yet)
            if state.room_id != here and not screen.busy:
                break
            await pilot.pause(0.1)
        expected = {"east": (1, 0), "west": (-1, 0), "north": (1, 1), "south": (1, -1)}[way]
        assert wiped and wiped[-1] == expected


async def test_the_map_moves_on_before_the_room_wipes_in(monkeypatch):
    """Run 66: the wipe, the step, then the map read as a hitch. The map (and Here) say where you are first."""
    from test_ui import into_a_run, take_choice

    from ptg.ui.app import PTGApp

    seen = []
    real = encounter.wipe
    app = PTGApp(Config(backend="offline", layout="grid", player_name="T", auto_roll=True), seed=1)
    async with app.run_test(size=(160, 50)) as pilot:
        screen = await into_a_run(app, pilot)
        monkeypatch.setattr(encounter, "wipe", lambda *a, **kw: seen.append(screen.map_drawn[2]) or real(*a, **kw))
        state = screen.game.state
        for room in state.rooms:
            room.monster, room.others = None, []
        way = next(d for d, e in state.room.exits.items() if not e.shut)
        for _ in range(50):
            if screen.stage_still is not None:
                break
            await pilot.pause(0.1)
        await pilot.pause(2.5)
        here = state.room_id
        await take_choice(app, pilot, screen, f"go:{way}")
        for _ in range(50):
            if state.room_id != here and not screen.busy:
                break
            await pilot.pause(0.1)
        assert seen and seen[0] == state.room_id != here


def test_a_frame_the_size_of_the_last_isnt_laid_out_again():
    """24 frames a second, each laying the whole screen out again, stuttered run 66's floor 5."""
    from rich.text import Text

    from ptg.ui import effects

    class Art:
        def __init__(self):
            self.layouts = []

        def update(self, frame, layout=True):
            self.layouts.append(layout)

    art = Art()
    shown = effects.show_frame(art, Text("ab\ncd"), None)
    shown = effects.show_frame(art, Text("xy\nzw"), shown)
    shown = effects.show_frame(art, Text("xyz\nzw"), shown)
    effects.show_frame(art, "abc\nde", shown)
    assert art.layouts == [True, False, True, False]


def test_a_posed_frame_is_kept():
    """A clip's frames come round again and again in a fight's loop: a windup's glow (plain Python over every pixel)
    is drawn once a frame, not once a tick."""
    from ptg import sprites

    img = encounter.Image.new("RGBA", (12, 12), (0, 0, 0, 0))
    img.putpixel((6, 6), (200, 10, 10, 255))
    assert sprites.posed(img, "windup", 0) is sprites.posed(img, "windup", 2)
    assert sprites.posed(img, "windup", 1) is not sprites.posed(img, "windup", 0)
    assert sprites.dimmed(img) is sprites.dimmed(img) and sprites.posed(img, "idle") is img
    assert sprites.posed(img, "windup", 1).getpixel((6, 4))[3] == 255  # (the glow, a pixel out, the sprite up one)
