"""Fights against several foes at once (docs/plans/multi-foe-fights.md §1) and the timed statuses beside poison
(§2): who you face, everyone's goes, one falling and the last, fleeing, bombs, parties; Burning, Stunned, Mending."""

import random

from conftest import put_monster

from ptg import combat, encounter, statuses
from ptg.combat import fell, foes, foes_turn, rally
from ptg.models import MonsterState
from ptg.rules import available_actions, perform
from ptg.scene import RoomView
from ptg.world import ORDINALS, generate, party, titled


def crowd(state, content, keys=("goblin", "skeleton", "orc"), hp=None):
    """The first is the one you face; the rest stand beside it, each in its place."""
    put_monster(state, content, keys[0], hp=hp)
    state.room.others = []
    for i, key in enumerate(keys[1:], 1):
        made = content.monster(key)
        state.room.others.append(MonsterState(key=key, name=made.name, hp=hp or made.hp, max_hp=made.hp, place=i))
    return state.room.monster, state.room.others


def ids(state, content):
    return [a.id for a in available_actions(state, content)]


# --- who you face, and their goes ----------------------------------------------------------------------------------

def test_facing_another_foe_costs_no_turn_and_your_blows_go_to_it(content):
    state = generate(7)
    goblin, (_, orc) = crowd(state, content)
    assert state.in_combat and {"face:0", "face:1"} <= set(ids(state, content))
    turn = state.turn
    events = perform(state, content, "face:1")
    assert state.turn == turn and state.room.monster is orc and goblin in state.room.others
    assert events[0].kind == "face" and "Orc" in events[0].text
    hit = next(e for e in perform(state, content, "attack") if e.kind in ("hit", "miss"))
    assert "Orc" in hit.text


def test_every_foe_has_its_go_after_yours(content):
    state = generate(7)
    goblin, others = crowd(state, content)
    perform(state, content, "dodge")
    assert goblin.swings + sum(m.swings for m in others) >= 2  # (each that struck, the one you face first)
    for monster in [goblin, *others]:
        monster.intent = "strike"
    events = foes_turn(state, content, random.Random(3))
    hitters = [e.text.split(" ")[1] for e in events if e.kind in ("monster_hit", "monster_miss")]
    assert hitters == ["Goblin", "Skeleton", "Orc"]


def test_one_falls_and_the_next_comes_at_you(content):
    state = generate(7)
    goblin, (skeleton, orc) = crowd(state, content)
    goblin.hp = 0
    events = rally(state)
    assert state.room.monster is skeleton and state.room.others == [orc] and "comes at you now" in events[0].text


def test_one_you_dont_face_falling_to_its_burns_pays_and_leaves_you_facing_the_same(content):
    state = generate(7)
    goblin, (skeleton, orc) = crowd(state, content)
    xp = state.player.xp
    orc.hp = 0
    events = fell(state, content, random.Random(1), orc)
    assert state.room.monster is goblin and state.room.others == [skeleton] and state.player.xp > xp
    assert any(e.kind == "defeat" and "Orc" in e.text for e in events)


def test_a_boss_fight_is_won_only_when_the_last_of_its_party_falls(content):
    """The Humongous Fungus down first: the rest of it fights on. And one of its parts dying of its burns while you
    face another isn't the last of them."""
    state = generate(7, floors=5)
    state.floor = state.floors_total = 5  # (its final floor)
    state.room.is_boss = True
    boss, _ = crowd(state, content, ("humongous_fungus", "spore_mother", "rot_gill", "puff_mound"))
    boss.hp = 0
    events = combat.defeat(state, content, random.Random(1))
    assert state.status == "playing" and any("fights on" in e.text for e in events)
    rally(state)
    mother, gill, puff = state.room.monster, *state.room.others
    gill.hp = puff.hp = 0
    fell(state, content, random.Random(1), gill)
    fell(state, content, random.Random(1), puff)
    assert state.status == "playing" and state.room.monster is mother and state.room.others == []
    mother.hp = 0
    events = combat.defeat(state, content, random.Random(1))
    assert state.status == "won" and any(e.kind == "victory" for e in events)


def test_fleeing_gets_you_away_from_all_of_them(content, monkeypatch):
    state = generate(7)
    state.room_id = next(r.id for r in state.rooms if r.exits and r.id)
    crowd(state, content)
    monkeypatch.setattr(combat.dice, "check", lambda *a, **k: _success())
    room = state.room
    perform(state, content, "flee")
    assert state.room is not room and not state.in_combat


def _success():
    from ptg.dice import Roll

    return Roll(label="agility (flee)", actor="player", dice=[20], kept=20, dc=10, success=True)


def test_a_bomb_catches_the_others_for_half(content):
    state = generate(7)
    goblin, (skeleton, orc) = crowd(state, content, hp=40)
    state.player.bombs = 1
    events = combat.bomb_monster(state, content, random.Random(2))
    blast = 40 - goblin.hp
    assert blast > 1 and 40 - skeleton.hp == 40 - orc.hp == blast // 2
    assert any(e.text.startswith("The blast catches the Skeleton") for e in events)


def test_a_party_comes_together_named_apart(content):
    """A Sporerat never comes alone (its party: another), and a boss's parts are as they're made, not deepened."""
    rat = MonsterState(key="sporerat", name="Sporerat", hp=22, max_hp=22)
    (other,) = party(random.Random(1), content, rat, 5)
    assert other.name == f"{ORDINALS[0]} Sporerat" and other.place == 1 and other.max_hp > 22  # (floor 5: deeper)
    fungus = MonsterState(key="humongous_fungus", name="The Humongous Fungus", hp=50, max_hp=50)
    parts = party(random.Random(1), content, fungus, 5)
    assert [m.key for m in parts] == ["spore_mother", "rot_gill", "puff_mound"]
    assert [m.max_hp for m in parts] == [content.monster(m.key).hp for m in parts]
    assert titled("Hulking", "The Hollowed") == "The Hulking Hollowed" and titled("Second", "Sporerat") == "Second Sporerat"


def test_here_has_a_tile_for_each_foe_to_turn_to(content):
    state = generate(7)
    crowd(state, content)
    view = RoomView(state, content)
    foes_here = [ref for ref in view.refs if ref.kind == "foe"]
    assert [ref.name for ref in foes_here] == ["Skeleton", "Orc"]
    from ptg.interactions import verbs

    assert any(a.id == "face:1" and a.label == "Face it" for a in verbs(state, content, "foe:1"))


def test_the_stage_shows_the_crowd_each_with_its_health(content):
    state = generate(7)
    goblin, others = crowd(state, content, ("goblin", "skeleton", "orc", "troll"))
    statuses.afflict(others[0], "burn")
    fight = encounter.Fight(state, content, goblin, 110, 16)
    still = fight.still().plain
    bars = still.split("\n")[-2]  # (a health bar under each, the one you face's between ▶ ◀; their marks after)
    assert bars.count("/") == 4 and "▶" in bars and "◀" in bars and "♨3" in bars
    assert bars.index("▶") < bars.index("8/8") < bars.index("◀") < bars.index("♨3")
    assert "Goblin" in still.split("\n")[-1] and still.split("\n")[0].count("⚔") == 1 and "▼" in still
    assert fight.share < encounter.FOE_SHARE  # (each smaller, the more there are)


# --- timed statuses ------------------------------------------------------------------------------------------------

def test_burning_costs_you_for_three_turns_then_burns_out(content):
    state = generate(7)
    player = state.player
    statuses.inflict(state, "burn", "The Cinder Imp")
    hp = player.hp
    for _ in range(3):
        statuses.tick(state, "round")
    assert player.hp == hp - 6 and "burn" not in player.statuses and "burn" not in player.timers


def test_burning_can_kill_you(content):
    state = generate(7)
    statuses.inflict(state, "burn")
    state.player.hp = 2
    events = statuses.tick(state, "round")
    assert state.status == "dead" and "burnt to death" in state.cause and events[-1].kind == "death"


def test_a_fountain_puts_you_out(content, monkeypatch):
    state = generate(7)
    state.room.fixture, state.room.monster = "fountain", None
    statuses.inflict(state, "burn")
    events = perform(state, content, "fountain")
    assert "burn" not in state.player.statuses and any(e.kind == "cured" for e in events)


def test_stunned_you_lose_your_next_go_but_never_two_in_a_row(content):
    state = generate(7)
    goblin = put_monster(state, content, "goblin")
    statuses.inflict(state, "stun", "The Puff Mound")
    swings = goblin.swings
    events = perform(state, content, "attack")
    assert events[0].kind == "stunned_you" and not any(e.kind in ("hit", "miss") for e in events)
    assert goblin.swings == swings + 1 and "stun" not in state.player.statuses
    again = statuses.inflict(state, "stun", "The Puff Mound")
    assert again[0].kind == "guarded" and "stun" not in state.player.statuses  # (braced, after a lost go)


def test_a_mender_mends_the_most_hurt_of_its_side_never_itself(content):
    state = generate(7)
    mother, (gill, puff) = crowd(state, content, ("spore_mother", "rot_gill", "puff_mound"))
    mother.hp, gill.hp, puff.hp = 1, gill.max_hp - 2, 3
    events = combat.monster_turn(state, content, random.Random(1), mother)
    assert events[0].kind == "mend" and "mend" in puff.statuses and "mend" not in mother.statuses
    assert combat.foresee(state, content, mother).words == "MENDS"
    before = puff.hp
    statuses.monster_tick(puff)
    assert puff.hp == before + statuses.MONSTER_MEND


def test_a_burning_monster_burns_each_turn_and_can_fall_to_it(content):
    state = generate(7)
    goblin, (skeleton,) = crowd(state, content, ("goblin", "skeleton"))
    assert combat.alight(skeleton)[0].kind == "alight" and not combat.alight(skeleton)  # (said once)
    skeleton.hp = statuses.MONSTER_BURN
    for monster in (goblin, skeleton):
        monster.intent = "guard"
    events = foes_turn(state, content, random.Random(1))
    assert skeleton not in state.room.others and any(e.kind == "defeat" for e in events)
    assert foes(state) == [goblin]


def test_your_timed_statuses_say_how_long_they_have_left(content):
    from ptg.ui.widgets import Hud

    state = generate(7)
    statuses.inflict(state, "burn")
    assert statuses.left(state, "burn") == 3
    assert statuses.ailing(state) and statuses.ailing(state)[0].key == "burn"
    statuses.inflict(state, "mend")
    assert [s.key for s in statuses.ailing(state)] == ["burn"]  # (Mending's good: no ailing heart for it)
    assert Hud  # (the status bar shows "♨ Burning 3": tests/test_ui.py has it drawn)


def test_in_a_crowd_each_foe_with_clips_of_its_own_plays_them(content):
    """The bosses' clips at the size each one's slice of the stage takes: every foe stands in its own idle, they all
    come in together on the entrance, a heavy blow coming shows in its windup, and a turn's blows play each striker's
    own attack, all at once."""
    state = generate(7)
    king, others = crowd(state, content, ("goblin_king", "thornmother", "serpentis", "drowned_abbot"))
    others[0].intent = "heavy"
    fight = encounter.Fight(state, content, king, 120, 22)
    assert {"idle", "entrance", "attack", "windup"} <= set(fight.clips)
    for monster in fight.others:
        look = fight.look(monster.key)
        assert look.clips and look.box[2] - look.box[0] <= fight.wide  # (fits its slice)
    thorn, serpentis = fight.others[0], fight.others[1]
    coming = fight.look(serpentis.key).clips["entrance"].frames[0]
    assert fight.other(serpentis, 0, clip="entrance")[0].getbbox() == coming.getbbox()
    assert fight.other(thorn, 0, "windup")[0].tobytes() != fight.other(thorn, 0)[0].tobytes()  # (its windup, glowing)
    everyone = frozenset(m.place for m in fight.lineup())
    longest = max(len(c.frames) for c in [fight.clips["attack"]] + [fight.look(m.key).clips["attack"]
                                                                       for m in fight.others])
    every = max(1, round(fight.clips["attack"].fps / encounter.sprites.CLIP_FPS))
    assert len(list(fight.swing(everyone))) == -(-longest // every)
    assert list(fight.swing(frozenset({99}))) == []  # (nobody who struck has an attack of its own)
