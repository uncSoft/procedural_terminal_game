"""Fighting: attacks, telegraphed monster moves, dodging, fleeing, and what happens when something dies.

A fight can have several foes (docs/plans/multi-foe-fights.md): the room's `monster` is the one you face, the one
your blows, throws and words go to, and its `others` stand beside it. `foes` is everyone still after you, the one you
face first; `face` turns you to another (no turn); `foes_turn` is each one's go after yours, then their statuses (a
burn can finish one: `fell`, for a foe that isn't the one you face); `rally` makes the next one standing the one you
face once yours is down."""

from __future__ import annotations

import random
from dataclasses import dataclass

from . import dice, hazards, inventory, light, loot, powers, statuses
from .content import Content, ItemDef
from .events import Event
from .models import GameState, MonsterState
from .text import a, cap, mid_sentence, tell, the

INTENT_WEIGHTS = {
    "boss": {"strike": 45, "heavy": 40, "guard": 15},
    "elite": {"strike": 55, "heavy": 30, "guard": 15},
    "normal": {"strike": 65, "heavy": 22, "guard": 13},
}
VENOM = 0.25  # how often a venomous bite poisons you (a deadly one always does)
PURE_DROP = 0.25  # how often a venomous monster, slain, leaves a Pure
VENOMOUS = {"venom", "venom_spit", "deadly_venom"}
# What a monster's tricks look like over its head, with its next blow (foresee): the words for each.
TRICK_WORDS = {"steal": "grabs", "tangle": "vines", "venom": "venom", "venom_spit": "spit", "deadly_venom": "venom!",
               "burn": "fire", "spores": "spores"}
SET_ALIGHT, DAZE = 0.35, 0.5  # how often a fiery hit sets you burning, and a spore-burst stuns you (a heavy one: always)
# Winning in style pays (docs/plans/combat-and-balance.md §3.6): each a fifth more XP (1 at least) and 3 gold a tier.
STYLES = {"flawless": ("Flawless", "not a scratch on you"), "exploited": ("Exploited", "finished with its weakness")}
STYLE_XP, STYLE_GOLD = 0.2, 3
BURN = "1d6"  # a torch's flame, held to a monster (burn)


@dataclass(frozen=True)
class Foresight:
    """What a monster will do on its next go, as it's shown over its head (docs/plans/combat-and-balance.md §3.2): a
    mark, a word, and the damage it does if it lands, least to most (a strike's or a heavy blow's), with its tricks."""
    kind: str  # strike, heavy, guard, reeling (stunned: it loses its go), running (off with what it grabbed)
    mark: str
    words: str = ""
    low: int = 0
    high: int = 0
    tricks: tuple[str, ...] = ()

    def said(self) -> str:
        """In a few words: "‼ 8-20 HEAVY · venom"."""
        hurt = f"{self.low}–{self.high}" if self.high else ""
        return " · ".join(filter(None, [" ".join(filter(None, [self.mark, hurt, self.words])), *self.tricks]))


def monster_defense(monster: MonsterState, content: Content) -> int:
    return content.monster(monster.key).defense + monster.defense_mod + (4 if monster.guarding else 0)


def tricks_of(monster: MonsterState, content: Content) -> set[str]:
    """Its maker's tricks, and any it has here (Norfel's venom)."""
    return {*content.monster(monster.key).tricks, *monster.tricks}


def tier_of(monster: MonsterState, content: Content) -> int:
    """How tough it counts as, for dodging, fleeing and what it pays: its maker's tier, or the floor's for a character
    cut down to size there (npcs.sized)."""
    return monster.tier or content.monster(monster.key).tier


def choose_intent(rng: random.Random, monster: MonsterState, content: Content) -> str:
    kind = "boss" if content.monster(monster.key).boss else ("elite" if monster.elite else "normal")
    weights = INTENT_WEIGHTS[kind]
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def holds_its_ground(state: GameState, content: Content, monster: MonsterState) -> bool:
    """One nothing scares off and no smoke hides you from: a boss, a guardian (King Mouse), the warden at the stairs,
    a one-of-a-kind creature (Serpentis, the Rat King), anything from a deeper floor (tier 4), or anything still
    keeping a rare thing of its own (it would go with it). Getting away from one takes a pair of fast legs: a flee
    roll, smoke or no smoke (flee)."""
    known = content.monster(monster.key)
    keeps = any(monster.key in item.found and item.key not in state.rares for item in content.items.values())
    return known.boss or "guardian" in known.tags or monster.warden or known.once or known.tier >= 4 or keeps


def stand_firm_warning(state: GameState, content: Content) -> list[Event]:
    """A fight with one that holds its ground (holds_its_ground) says so as it starts, so nobody finds out by
    wasting a smoke bomb. (Of several foes, the first that does.)"""
    monster = next((m for m in foes(state) if holds_its_ground(state, content, m)), None)
    if monster is None:
        return []
    return [Event("warning", f"{cap(the(monster.name))} won't be scared off, and no smoke will hide you from it: to "
                             "get away, you'll have to outrun it.", data={"monster": monster.key})]


def telegraph(state: GameState, content: Content, monster: MonsterState | None = None) -> list[Event]:
    monster = monster or state.room.monster
    if monster and monster.hostile and monster.intent == "heavy":
        known = content.monster(monster.key)
        wind_up = tell(monster.name, known.tell).rstrip(" .")  # (the kids shout theirs)
        stop = "" if wind_up.endswith(("!", "?", '"')) else "."  # (out of the f-string: Python 3.11 allows no \ in one)
        return [Event("telegraph", f"{wind_up}{stop} A heavy blow is coming!",
                      data={"sound": known.cry} if known.cry else {})]
    return []


def foresee(state: GameState, content: Content, monster: MonsterState | None = None) -> Foresight | None:
    """What the monster here will do on its next go (it's chosen a turn ahead: choose_intent), and what it would cost
    you: a strike's damage, a heavy blow's (its dice twice), less what keeps it at bay. None out of a fight."""
    monster = monster or state.room.monster
    if not (monster and monster.hostile and monster.hp > 0):
        return None
    if monster.stunned > 0:
        return Foresight("reeling", "✶", "REELING")
    if monster.stolen_item or monster.stolen_gold:
        return Foresight("running", "»", "RUNNING OFF")
    if monster.intent == "guard":
        return Foresight("guard", "⛨", "GUARDS")
    if "mend" in tricks_of(monster, content) and any(m is not monster and m.hp < m.max_hp and "mend" not in m.statuses
                                                     for m in foes(state)):
        return Foresight("mend", "✚", "MENDS")
    heavy = monster.intent == "heavy"
    low, high = dice.span(content.monster(monster.key).damage)
    flat = monster.damage_mod - (2 if powers.holders(state, content, "reeks") else 0)
    times = 2 if heavy else 1
    tricks = tuple(words for trick, words in TRICK_WORDS.items()
                   if trick in tricks_of(monster, content) and (trick != "venom_spit" or heavy))
    return Foresight("heavy" if heavy else "strike", "‼" if heavy else "⚔", "HEAVY" if heavy else "",
                     max(1, times * low + flat), max(1, times * high + flat), tricks)


def danger(state: GameState, content: Content, monster: MonsterState | None = None) -> int:
    """How dangerous a fight looks, 1 to 3 (☠, ☠☠, ☠☠☠): the share of your health beating it toe to toe would
    cost, from your chance to hit it and your blows against its health, its chance to hit you and its blows (its
    heavy ones as often as its kind swings them). Under a quarter is one; under three fifths, two."""
    monster = monster or state.room.monster
    player, known = state.player, content.monster(monster.key)
    weapon = content.item(player.weapon)

    def chance(bonus: int, dc: int) -> float:
        return max(0.05, min(0.95, (21 - (dc - bonus)) / 20))

    bonus = player.might + player.level + sum(n for _, n in powers.roll_bonuses(state, content, "attack"))
    weak = 2 if set(weapon.tags + ([player.coating] if player.coated else [])) & set(known.weak) else 0
    flat = player.might + weak + ("brute" in player.traits) + 3 * ("glass_cannon" in player.perks)
    blow = chance(bonus, monster_defense(monster, content)) * (dice.average(weapon.damage) + flat)
    rounds = max(1, monster.hp) / max(0.5, blow)
    weights = INTENT_WEIGHTS["boss" if known.boss else "elite" if monster.elite else "normal"]
    average = dice.average(known.damage)
    hurt = chance(known.attack + monster.attack_mod, player.defense(content)) * (
        weights["strike"] * (average + monster.damage_mod) + weights["heavy"] * (2 * average + monster.damage_mod)
    ) / sum(weights.values())
    share = rounds * max(0.0, hurt) / max(1, player.max_hp)
    return 1 if share < 0.25 else 2 if share < 0.6 else 3


def state_known(state: GameState, monster_key: str) -> list[str]:
    return state.known_weak.get(monster_key, [])


def discover(state: GameState, monster: MonsterState, tag: str) -> list[Event]:
    known = state.known_weak.setdefault(monster.key, [])
    if tag in known:
        return []
    known.append(tag)
    state.player.bump("weakness")
    return [Event("weakness", f"You've learned something: {the(monster.name)} is weak to {tag}. (Bestiary updated.)",
                  data={"monster": monster.key, "tag": tag})]


def player_attack(state: GameState, content: Content, rng: random.Random) -> list[Event]:
    room, player = state.room, state.player
    monster = room.monster
    monster_def = content.monster(monster.key)
    weapon = content.item(player.weapon)
    events: list[Event] = []
    if not monster.hostile:
        monster.hostile = True
        events.append(provoked(monster, content))
    advantage = 1 if (monster.stunned or player.advantage_next) else 0
    player.advantage_next = False
    bonuses = [("might", player.might), ("level", player.level)] + powers.roll_bonuses(state, content, "attack")
    roll = dice.check(rng, "attack", bonuses, monster_defense(monster, content), advantage=advantage)
    roll.hits_for = f"{weapon.damage} + {player.might} might" if player.might else weapon.damage
    events_on_roll = fortune(state, roll)
    if not roll.success:
        guarded = " It's guarding, and your blow glances off." if monster.guarding else ""
        events.append(Event("miss", f"You swing your {weapon.name} at {the(monster.name)} and miss.{guarded}", dice=roll))
        return events + events_on_roll

    parts = [(weapon.damage, dice.roll(weapon.damage, rng))]  # (told part by part on the roll: Roll.hurt)
    if roll.crit:
        parts.append((f"crit {weapon.damage}", dice.roll(weapon.damage, rng)))
    parts.append(("might", player.might))
    extras = []
    if "brute" in player.traits:
        parts.append(("brute", 1))
    if "glass_cannon" in player.perks:
        parts.append(("glass cannon", 3))
    if "bully" in player.perks and monster.stunned:
        parts.append(("bully", 3))
        extras.append("Bully")
    if "sharp_start" in player.blessings and player.weapon == "rusty_sword":
        parts.append(("sharp start", 1))
    coating = [player.coating] if player.coated else []  # holy water or lamp oil on the blade (interactions.RECIPES)
    weak = list(dict.fromkeys(t for t in weapon.tags + coating if t in monster_def.weak))
    if weak:
        parts.append((f"{' + '.join(weak)}!", 2))
        extras.append(f"{' + '.join(weak)}!")
    worn = ""
    if coating:
        player.coated -= 1
        if not player.coated:
            worn, player.coating = f" The {coating[0]} coating on your {weapon.name} is spent.", ""
    if "goblin_bane" in weapon.powers and powers.GOBLINS & set(monster_def.tags):
        parts.append(("goblin-bane", 2))
        extras.append("goblin-bane")
    if "monster_scholar" in player.traits and state_known(state, monster.key):
        parts.append(("scholar", 1))
    player.hits_landed += 1
    if "ruthless" in player.perks and player.hits_landed % 3 == 0:  # (the weapon's dice again, a crit's too)
        parts.append(("ruthless ×2", sum(v for name, v in parts if name in (weapon.damage, f"crit {weapon.damage}"))))
        extras.append("Ruthless x2")
    roll.damage = [(name, value) for name, value in parts if value]
    damage = sum(value for _, value in parts)
    monster.hp -= damage
    how = "land a critical hit on" if roll.crit else "hit"
    tail = f" [{', '.join(extras)}]" if extras else ""
    events.append(Event("hit", f"You {how} {the(monster.name)} with your {weapon.name} for {damage} damage "
                               f"({max(monster.hp, 0)}/{monster.max_hp} HP left).{tail}{worn}", dice=roll,
                        data={"damage": damage}))
    for tag in weak:
        events += discover(state, monster, tag)
    events += events_on_roll
    if monster.hp > 0 and "fire" in coating:  # (a blade slick with burning oil sets it alight)
        events += alight(monster)
    if monster.hp <= 0:
        events += defeat(state, content, rng, exploited=bool(weak))
    return events


def provoked(monster: MonsterState, content: Content) -> Event:
    """Attacking something that wasn't fighting you: a character who never was (Lucky Lenny) yelps (what he yells is
    his, on his card: npcs.react), and a monster you'd talked down is back at it."""
    name = cap(the(monster.name))
    if content.monster(monster.key).npc:
        return Event("provoke", f"{name} yelps and puts up a fight.", data={"monster": monster.key})
    return Event("provoke", f"{name} had stopped fighting. Not any more.", data={"monster": monster.key})


def what_is_left(player, key: str) -> str:
    """After using one up: how many more you carry (" (1 more in your pack.)"), or nothing if that was the last."""
    count = player.inventory.count(key)
    return f" ({count} more in your pack.)" if count else ""


def thrown_damage(item: ItemDef) -> str:
    """What a thing does thrown: its own dice, or, one that isn't made to be thrown, what it's made of does."""
    if item.damage:
        return item.damage
    tags = set(item.tags)
    return "1d6" if "heavy" in tags else "1d4" if tags & {"glass", "sharp", "metal", "hard"} else "1d2"


def throw(state: GameState, content: Content, rng: random.Random, key: str) -> list[Event]:
    """Throw something you carry at the monster: an agility roll against its defense, with advantage and 2 more damage
    if it's weak to the thing. It hits for its own dice if it's made to be thrown (a throw power), otherwise for what
    it's made of (thrown_damage). Hit or miss it's gone, unless it's a spare weapon: that lands at the monster's feet,
    to pick up once the fight's over."""
    player, monster, item = state.player, state.room.monster, content.item(key)
    weak = [t for t in item.tags if t in content.monster(monster.key).weak]
    if item.kind == "weapon":
        player.inventory.remove(key)
        state.room.items.append(key)
        thrown, gone = inventory.moved(key, "throw", "pack", "room"), "It lands at its feet."
    else:
        thrown, gone = inventory.consume(state, key, "throw"), "It's gone."
    monster.hostile = True
    bonuses = [("agility", player.agility)] + powers.roll_bonuses(state, content, "throw")
    roll = dice.check(rng, f"throw {the(item.name)}", bonuses, monster_defense(monster, content),
                      advantage=1 if weak else 0)
    roll.hits_for = thrown_damage(item)
    events = fortune(state, roll)
    more = what_is_left(player, key)
    if not roll.success:
        return [Event("miss", f"You throw {the(item.name)} at {the(monster.name)} and miss. {gone}{more}",
                      dice=roll, data={"rerollable": True, **thrown})] + events
    parts = [(thrown_damage(item), dice.roll(thrown_damage(item), rng))]
    if roll.crit:  # (a critical throw hits twice as hard, as a critical blow does)
        parts.append((f"crit {thrown_damage(item)}", dice.roll(thrown_damage(item), rng)))
    if weak:
        parts.append((f"{' + '.join(weak)}!", 2))
    roll.damage = parts
    damage = sum(value for _, value in parts)
    monster.hp -= damage
    tail = (f" [{' + '.join(weak)}!]" if weak else "") + (f" {gone}" if item.kind == "weapon" else "")
    events.insert(0, Event("hit", f"{cap(the(item.name))} hits {the(monster.name)} for {damage} damage "
                                  f"({max(monster.hp, 0)}/{monster.max_hp} HP left).{tail}{more}", dice=roll,
                           data={"damage": damage, "rerollable": True, **thrown}))
    for tag in weak:
        events += discover(state, monster, tag)
    events += alight(monster) if "fire" in item.tags and monster.hp > 0 else []  # (lamp oil, lava: it burns on)
    return events + (defeat(state, content, rng, exploited=bool(weak)) if monster.hp <= 0 else [])


def burn(state: GameState, content: Content, rng: random.Random) -> list[Event]:
    """Your torch held to the monster, down in the dark where it's lit (light.py): a might roll against its defense,
    with advantage and 2 more damage if fire's its weakness, for the flame's BURN. Landed, it costs a flame of the
    torch's light; missed, it costs only the turn."""
    player, monster = state.player, state.room.monster
    weak = "fire" in content.monster(monster.key).weak
    events: list[Event] = [] if monster.hostile else [provoked(monster, content)]
    monster.hostile = True
    bonuses = [("might", player.might), ("level", player.level)] + powers.roll_bonuses(state, content, "attack")
    roll = dice.check(rng, "burn", bonuses, monster_defense(monster, content), advantage=1 if weak else 0)
    roll.hits_for = BURN
    luck = fortune(state, roll)
    if not roll.success:
        return events + [Event("miss", f"You thrust your torch at {the(monster.name)}, and it ducks the flame.",
                               dice=roll)] + luck
    parts = [(BURN, dice.roll(BURN, rng))]
    if roll.crit:  # (a critical burn, twice the flame, as a critical blow is twice the weapon)
        parts.append((f"crit {BURN}", dice.roll(BURN, rng)))
    if weak:
        parts.append(("fire!", 2))
    roll.damage = parts
    damage = sum(value for _, value in parts)
    monster.hp -= damage
    events.append(Event("hit", f"You hold your torch to {the(monster.name)} and it burns for {damage} damage "
                               f"({max(monster.hp, 0)}/{monster.max_hp} HP left).{' [fire!]' if weak else ''}",
                        dice=roll, data={"damage": damage, "burn": True}))
    events += light.burn(state, content) + (discover(state, monster, "fire") if weak else []) + luck
    events += alight(monster) if monster.hp > 0 else []
    return events + (defeat(state, content, rng, exploited=weak) if monster.hp <= 0 else [])


def alight(monster: MonsterState) -> list[Event]:
    """A monster set burning by your fire (the torch, lamp oil thrown, a fire-coated blade, a bomb): it burns for a
    few turns of the fight (statuses.monster_tick). Said once, as it catches."""
    if not statuses.afflict(monster, "burn"):
        return []
    return [Event("alight", f"{cap(the(monster.name))} catches fire!", data={"monster": monster.key, "status": "burn"})]


def distract(state: GameState, content: Content, key: str) -> list[Event]:
    """Draw the monster's eye with something (a distract power, or a shiny thing it's weak to: your gold, even),
    once a fight: it loses its next attack."""
    monster = state.room.monster
    shown = "your gold" if key == "gold" else the(content.item(key).name)
    monster.distracted = True
    monster.stunned = max(monster.stunned, 1)
    return [Event("distract", f"You get out {shown}. {cap(the(monster.name))} can't take its eyes off it and "
                              "forgets its next attack.")]


def bomb_monster(state: GameState, content: Content, rng: random.Random) -> list[Event]:
    """Throw a bomb: no roll, it always goes off, and harder on anything weak to fire or noise."""
    player, monster = state.player, state.room.monster
    player.bombs -= 1
    monster.hostile = True
    weak = [t for t in ("fire", "loud") if t in content.monster(monster.key).weak]
    damage = dice.roll("2d6", rng) + 2 * state.floor + (3 if weak else 0)
    monster.hp -= damage
    tail = f" [{' + '.join(weak)}!]" if weak else ""
    events = [Event("hit", f"Your bomb goes off at {the(monster.name)}'s feet for {damage} damage "
                           f"({max(monster.hp, 0)}/{monster.max_hp} HP left).{tail}",
                    data={"damage": damage, "bomb": True})]
    for tag in weak[:1]:
        events += discover(state, monster, tag)
    caught = [m for m in foes(state) if m is not monster]  # (the blast catches the others, for half)
    for other in caught:
        other.hp -= damage // 2
        events.append(Event("hit", f"The blast catches {the(other.name)} for {damage // 2} "
                                   f"({max(other.hp, 0)}/{other.max_hp} HP left).", data={"damage": damage // 2,
                                                                                         "blast": True}))
    events += defeat(state, content, rng, exploited=bool(weak)) if monster.hp <= 0 else []
    for other in caught:
        if other.hp <= 0 and not state.over:
            events += fell(state, content, rng, other)
    return events


def fortune(state: GameState, roll: dice.Roll) -> list[Event]:
    """Natural 20s (and, with Fortune's Fool, natural 1s) top up Fate."""
    player = state.player
    if roll.actor != "player":
        return []
    if roll.fumble:
        player.bump("fumbles")
    earned = roll.crit or (roll.fumble and "fortunes_fool" in player.traits)
    if earned and player.fate < player.max_fate():
        player.fate += 1
        roll.effects.append(f"+1 Fate ({player.fate}/{player.max_fate()})")
        why = "A natural 20!" if roll.crit else "Fortune's Fool: your blunder pleases the gods."
        return [Event("fate", f"{why} You gain a Fate token ({player.fate}/{player.max_fate()}).")]
    return []


def monster_turn(state: GameState, content: Content, rng: random.Random,
                 monster: MonsterState | None = None) -> list[Event]:
    """A foe's go (the one you face, unless it says another): a blow, a guard, or what its tricks have it do instead
    (a mender mends its side)."""
    room, player = state.room, state.player
    monster = monster or room.monster
    monster_def = content.monster(monster.key)
    monster.guarding = False
    dodging, player.dodging = player.dodging, False
    player.tangled = False  # (a tangle lasts until the monster's next go)
    if monster.stunned > 0:  # (a thief that's reeling, or can't take its eyes off something, isn't running yet)
        monster.stunned -= 1
        monster.intent = "strike"
        return [Event("stunned", f"{cap(the(monster.name))} is still reeling and can't attack.")]
    if monster.stolen_item or monster.stolen_gold:
        return _getaway(state, content, monster)
    mended = _mend(state, content, monster)
    if mended:  # (a mender with someone of its side hurt: it mends them instead of striking)
        monster.intent = choose_intent(rng, monster, content)
        return mended

    intent = monster.intent
    monster.intent = choose_intent(rng, monster, content)
    if intent == "guard":
        monster.guarding = True
        events = [Event("guard", f"{cap(the(monster.name))} hunkers down and guards itself (+4 defense).")]
        return events + telegraph(state, content, monster)

    monster.swings += 1
    if dodging:
        perfect = intent == "heavy"
        events = [Event("dodge", f"You slip aside and {the(monster.name)}'s "
                                 f"{'heavy blow' if perfect else 'attack'} hits nothing but air.",
                        data={"foe": monster.place})]
        if perfect:
            player.advantage_next = True
            if player.fate < player.max_fate():
                player.fate += 1
            events.append(Event("fate", "Perfect dodge! Your next attack has advantage, and you gain a Fate token "
                                        f"({player.fate}/{player.max_fate()})."))
        return events + telegraph(state, content, monster)

    attack = monster_def.attack + monster.attack_mod
    label = f"{monster.name} {'HEAVY attack' if intent == 'heavy' else 'attacks'}"
    roll = dice.check(rng, label, [("attack", attack)], player.defense(content), actor="monster")
    roll.hits_for = f"{monster_def.damage} ×2" if intent == "heavy" else monster_def.damage
    if not roll.success:
        return [Event("monster_miss", f"{cap(the(monster.name))} attacks you and misses.", dice=roll,
                      data={"foe": monster.place})] + telegraph(state, content, monster)

    room_key = f"{state.floor}:{room.id}"
    if "acrobatics" in player.perks and room_key not in player.evaded_rooms and intent != "heavy":
        player.evaded_rooms.append(room_key)
        return [Event("evade", f"Acrobatics! You tumble clear of {the(monster.name)}'s blow.", dice=roll,
                      data={"foe": monster.place})] + telegraph(state, content, monster)

    rolls = 2 if intent == "heavy" else (2 if roll.crit else 1)  # heavy blows and crits don't stack
    parts = [(monster_def.damage, dice.roll(monster_def.damage, rng))]
    if rolls == 2:
        parts.append((f"{'heavy' if intent == 'heavy' else 'crit'} {monster_def.damage}",
                      dice.roll(monster_def.damage, rng)))
    parts.append(("its strength" if monster.damage_mod > 0 else "weakened", monster.damage_mod))
    reek = powers.holders(state, content, "reeks")
    if reek:  # it doesn't want to get close
        parts.append(("kept at bay", -2))
    if sum(value for _, value in parts) < 1:  # a hit always hurts
        parts.append(("a hit hurts", 1 - sum(value for _, value in parts)))
    roll.damage = [(name, value) for name, value in parts if value]
    damage = sum(value for _, value in parts)
    player.hp = max(0, player.hp - damage)
    monster.dealt += damage
    how = "lands a crushing heavy blow on you" if intent == "heavy" else (
        "lands a vicious critical hit on you" if roll.crit else "hits you")
    held_off = f" ({cap(the(reek[0].name))} keeps it at arm's length.)" if reek else ""
    events = [Event("monster_hit", f"{cap(the(monster.name))} {how} for {damage} damage "
                                   f"({player.hp}/{player.max_hp} HP left).{held_off}", dice=roll,
                    data={"damage": damage, "foe": monster.place})]
    if player.hp == 0:
        events += _death_or_reprieve(state, monster)
    if not state.over:
        events += _tricks(state, content, rng, monster, monster_def, heavy=intent == "heavy")
    return events + ([] if state.over else telegraph(state, content, monster))


def _tricks(state: GameState, content: Content, rng: random.Random, monster: MonsterState, monster_def,
            heavy: bool = False) -> list[Event]:
    """What a monster with tricks does when it hits you (see content.TRICKS): grab something, tangle you up, or
    poison you."""
    player, events = state.player, []
    if "steal" in monster_def.tricks and not (monster.stolen_item or monster.stolen_gold):
        food = [k for k in player.inventory
                if "food" in content.item(k).tags and not inventory.sticky(state, content, k)]  # (a curse holds on)
        if food:
            monster.stolen_item = rng.choice(food)
            inventory.give(state, monster.stolen_item, monster.key, "steal")
            what = the(content.item(monster.stolen_item).name)
        elif player.gold:
            monster.stolen_gold = min(player.gold, rng.randint(5, 10) * state.floor)
            player.gold -= monster.stolen_gold
            what = f"{monster.stolen_gold} of your gold"
        else:
            what = ""
        if what:
            events.append(Event("steal", f"{cap(the(monster.name))} grabs {what} and gets ready to run! Stop it "
                                         "now, or it's gone.", data={"item": monster.stolen_item}))
    if "tangle" in monster_def.tricks:
        player.tangled = True
        events.append(Event("tangle", f"{cap(the(monster.name))}'s vines wrap round your legs: no running away "
                                      "until it's had its next go."))
    tricks = tricks_of(monster, content)
    spat = "venom_spit" in tricks and heavy
    if "deadly_venom" in tricks or spat or ("venom" in tricks and rng.random() < VENOM):
        events += statuses.inflict(state, "poison", cap(the(monster.name)) + ("'s spit" if spat else "'s bite"),
                                   content)
    if "burn" in tricks and (heavy or rng.random() < SET_ALIGHT) and not state.over:
        events += statuses.inflict(state, "burn", cap(the(monster.name)), content)
    if "spores" in tricks and (heavy or rng.random() < DAZE) and not state.over:
        events += statuses.inflict(state, "stun", cap(the(monster.name)) + "'s burst of spores", content)
    return events



# --- several foes ---------------------------------------------------------------------------------------------------

def foes(state: GameState) -> list[MonsterState]:
    """Everyone in this room's fight still standing and after you: the one you face first, then the others."""
    room = state.room
    return [m for m in [room.monster, *room.others] if m is not None and m.hostile and m.hp > 0]


def face(state: GameState, content: Content, index: int) -> list[Event]:
    """Turn to another of the foes (the `index`th of the others): it's the one your blows go to now. No turn."""
    room = state.room
    other = room.others[index]
    room.others[index], room.monster = room.monster, other
    return [Event("face", f"You turn to face {the(other.name)}.", data={"monster": other.key, "quiet": True})]


def rally(state: GameState) -> list[Event]:
    """The one you faced is down (or talked down, or ran off): the next of the others still fighting comes at you,
    the one you face now. The fallen are cleared away; a foe talked down stays, calm, among the others."""
    room = state.room
    if room.monster is not None and room.monster.hostile and room.monster.hp > 0:
        return []
    fighting = [m for m in room.others if m.hostile and m.hp > 0]
    if not fighting:
        room.others = [m for m in room.others if m.hp > 0]
        return []
    after = fighting[0]
    room.others = [m for m in room.others if m is not after and m.hp > 0]
    if room.monster is not None and room.monster.hp > 0:  # (talked down: it stands aside)
        room.others.append(room.monster)
    room.monster = after
    return [Event("face", f"{cap(the(after.name))} comes at you now.", data={"monster": after.key})]


def fell(state: GameState, content: Content, rng: random.Random, foe: MonsterState, how: str = "slain",
         exploited: bool = False) -> list[Event]:
    """A foe beaten: the one you face (defeat, as ever), or one of the others (a burn, a blast): its rewards and
    drops all the same, and the one you face still the one you face."""
    room = state.room
    if foe is room.monster:
        return defeat(state, content, rng, how, exploited)
    facing, at = room.monster, room.others.index(foe)
    # (swapped for its defeat: the one you face stands in its place among the others, so the fight isn't won while
    # it's still standing)
    room.monster = foe
    if facing is not None:
        room.others[at] = facing
    else:
        del room.others[at]
    events = defeat(state, content, rng, how, exploited)
    calm = room.monster is foe  # (talked down: it stands aside, calm, where it was)
    if facing is not None:
        room.others[at] = foe
    elif calm:
        room.others.insert(at, foe)
    if not calm and foe in room.others:
        room.others.remove(foe)
    room.monster = facing
    return events


def foes_turn(state: GameState, content: Content, rng: random.Random) -> list[Event]:
    """After your go, each foe still standing has its own (the one you face first, then the others in turn), then a
    fight's turn of their statuses: a burn can finish one (fell), a mending heals."""
    events: list[Event] = []
    for foe in foes(state):
        if state.over:
            return events
        if foe.hp > 0 and foe.hostile:
            events += monster_turn(state, content, rng, foe)
    for foe in [m for m in [state.room.monster, *state.room.others] if m is not None and m.hp > 0]:
        events += statuses.monster_tick(foe)
        if foe.hp <= 0 and not state.over:
            events += fell(state, content, rng, foe)
    return events


def _mend(state: GameState, content: Content, monster: MonsterState) -> list[Event]:
    """A mender's go (the `mend` trick): the most hurt of the others on its side that isn't mending already is
    Mending now (it gets health back each turn: statuses.monster_tick). Never itself, so it can be killed first.
    Nothing, if none of them is hurt: then it strikes."""
    if "mend" not in tricks_of(monster, content):
        return []
    hurt = [m for m in foes(state) if m is not monster and m.hp < m.max_hp and "mend" not in m.statuses]
    if not hurt:
        return []
    worst = min(hurt, key=lambda m: m.hp / m.max_hp)
    statuses.afflict(worst, "mend")
    return [Event("mend", f"{cap(the(monster.name))} pulses with a soft light, and {the(worst.name)} begins to "
                          "mend.", data={"monster": worst.key})]


def _getaway(state: GameState, content: Content, monster: MonsterState) -> list[Event]:
    """A thief with something of yours runs off with it, on its next go if you didn't stop it."""
    what = the(content.item(monster.stolen_item).name) if monster.stolen_item else f"your {monster.stolen_gold} gold"
    if state.room.monster is monster:
        state.room.monster = None
    elif monster in state.room.others:
        state.room.others.remove(monster)
    state.room.remember(f"{the(monster.name)} ran off with {what}")
    return [Event("getaway", f"{cap(the(monster.name))} scampers off into the dark with {what}!")]


def _death_or_reprieve(state: GameState, monster: MonsterState) -> list[Event]:
    return statuses.fall(state, the(monster.name), f"slain by {the(monster.name)} on floor {state.floor}",
                         {"monster": monster.key})


def dodge(state: GameState, content: Content, rng: random.Random) -> list[Event]:
    monster = state.room.monster
    player = state.player
    tier = tier_of(monster, content)
    advantage = 1 if "duelist" in player.traits else 0
    bonuses = [("agility", player.agility)] + powers.roll_bonuses(state, content, "dodge")
    roll = dice.check(rng, "agility (dodge)", bonuses, 9 + tier, advantage=advantage)
    events = fortune(state, roll)
    if roll.success:
        player.dodging = True
        player.bump("dodged")
        return [Event("dodge_ready", "You read the attack and get ready to move.", dice=roll,
                      data={"rerollable": True})] + events
    return [Event("dodge_fail", "You try to get out of the way, but you're a step too slow.", dice=roll,
                  data={"rerollable": True})] + events


def flee_direction(state: GameState) -> str | None:
    open_exits = [(d, e) for d, e in state.room.exits.items() if not e.shut and not hazards.blocked(state, d)]
    for direction, exit_ in open_exits:
        if exit_.to == state.prev_room_id:
            return direction
    return open_exits[0][0] if open_exits else None


def flee(state: GameState, content: Content, rng: random.Random, guaranteed: bool = False) -> list[Event]:
    from .rules import travel

    monster = state.room.monster
    direction = flee_direction(state)
    if direction is None:
        return [Event("info", "There is nowhere to run.")]
    events: list[Event] = []
    after_you = foes(state) or [monster]  # (all of them: as hard as the hardest makes it)
    firm = next((m for m in after_you if holds_its_ground(state, content, m)), None)
    smoke = guaranteed and firm is not None  # (smoke helps, but it's still a run for it)
    said = [Event("info", f"The smoke would hide you from most things, but not from {the(firm.name)}: you make a "
                          "run for it.")] if smoke else []
    guaranteed = guaranteed and not smoke
    names = inventory.listing([the(m.name) for m in after_you], "and")
    if not guaranteed:
        dc = 10 + max(tier_of(m, content) for m in after_you)
        advantage = 1 if "escape_artist" in state.player.traits or smoke else 0
        bonuses = [("agility", state.player.agility)] + powers.roll_bonuses(state, content, "flee")
        roll = dice.check(rng, "agility (flee)", bonuses, dc, advantage=advantage)
        events += fortune(state, roll)
        if not roll.success:
            return said + [Event("flee_fail", f"You try to flee, but {the(monster.name)} cuts you off.", dice=roll,
                                 data={"rerollable": True})] + events
        events.insert(0, Event("flee", f"You escape from {names}, running {direction}.", dice=roll,
                               data={"rerollable": True}))
        events = said + events
    else:
        events.append(Event("flee", f"You escape from {names}, running {direction}."))
    state.player.bump("fled")
    for foe in after_you:
        foe.intent = "strike"
    return events + travel(state, content, direction, state.room.exits[direction].to)


def defeat(state: GameState, content: Content, rng: random.Random, how: str = "slain",
           exploited: bool = False) -> list[Event]:
    """The monster in this room is gone: slain or talked down. Rewards, drops, and maybe the win. One you'd talked
    down already has had its reward: killing it after (or calming it again) pays nothing more. A character talked
    down isn't a monster beaten: it's npcs.calm's to say how it takes it (no reward, and it keeps what it has). Slain
    in style pays more (styled): without a scratch, or `exploited`, finished with a weakness."""
    from .rules import check_level

    room, player = state.room, state.player
    monster = room.monster
    monster_def = content.monster(monster.key)
    if how != "slain" and monster_def.npc:
        from . import npcs

        return npcs.calm(state, content, monster)
    room.monster = None if how == "slain" else monster
    room.remember(f"you killed {the(monster.name)}" if how == "slain" else f"you talked {the(monster.name)} down")
    data = {"monster": monster.key, "how": how, "ghost_id": monster.ghost_id}
    if monster.rewarded and not monster_def.boss:
        if how == "slain":
            player.kills += 1
            player.bump("kills")
            done = Event("defeat", f"{cap(the(monster.name))} is defeated. No reward this time: you'd already talked "
                                   f"{the(monster.name)} down.", data=data)
        else:
            done = Event("pacify", f"{cap(the(monster.name))} stops fighting you again.", data=data)
        return [done] + _give_back(state, content, monster)  # (what it grabbed since is still yours)
    monster.rewarded = how != "slain"
    sized = min(1.0, monster.max_hp / monster_def.hp) if monster.tier and monster_def.hp else 1.0  # (npcs.sized)
    xp = round(monster_def.xp * sized * (0.6 if how == "pacified" else 1.0) * (1.5 if monster.elite else 1.0))
    souls = round((40 if monster_def.boss else 3 * tier_of(monster, content)) * monster.reward_mult)
    player.xp += xp
    state.souls += souls
    data = {**data, "xp": xp, "souls": souls}
    if how == "slain":
        player.kills += 1
        player.bump("kills")
        events = [Event("defeat", f"{cap(the(monster.name))} is defeated. +{xp} XP, +{souls} souls.", data=data)]
        events += styled(state, content, monster, xp, exploited)
    else:
        player.bump("pacify")
        events = [Event("pacify", f"{cap(the(monster.name))} stops fighting you. +{xp} XP, +{souls} souls.", data=data)]
    if monster.ghost_of:
        room.monster = None
        state.souls += 15
        events.append(Event("ghost_rest", f"The ghost of {monster.ghost_of}, your own earlier life, finally rests. "
                                          "Their belongings are yours to take. +15 souls.", data=data))
    last = not any(m.hostile and m.hp > 0 for m in room.others)  # (a party fights on till its last falls)
    beaten = last and (monster_def.boss or room.is_boss)  # (the boss, and the last of its party)
    if monster_def.boss and not last:
        events.append(Event("info", f"{cap(the(monster.name))} is down, but the rest of it fights on!", data=data))
    if beaten and state.final_floor:
        theme = content.themes[state.theme]
        state.status = "won"
        state.cause = f"conquered {theme.name}"
        events.append(Event("victory", f"You have conquered {theme.name}. {theme.goal} Done.", data=data))
        return events
    if beaten and state.boss_floor:  # a boss floor's: behind it, the way down (its room's stairs)
        theme = content.themes[state.theme]
        below = content.themes.get(state.themes[state.floor]) if state.floor < len(state.themes) else None
        down = "where it fell, the floor cracks open, and a stair of broken rock leads down into a cold glow" \
            if below and below.dark else \
            "behind where it stood, stairs lead further down, and the air coming up them stings your throat"
        events.append(Event("conquered", f"You have conquered {theme.name}. {theme.goal} Done. But it isn't over: "
                                         f"{down}.", data=data))
    elif beaten:  # one holding its dungeon on an earlier floor (world.EARLY_BOSSES), by its stairs
        theme = content.themes[state.theme]
        events.append(Event("conquered", f"You have conquered {theme.name}. {theme.goal} Done. The stairs down are "
                                         "yours.", data=data))
    if "vampiric" in player.perks and player.hp < player.max_hp:
        healed = min(3, player.max_hp - player.hp)
        player.hp += healed
        events.append(Event("heal", f"Vampiric: you drink in {healed} HP."))
    events += _give_back(state, content, monster)
    if how == "slain":
        gold = rng.randint(1, 6) * tier_of(monster, content) * (2 if monster.elite else 1)
        player.gold += gold
        events.append(Event("loot", f"You find {gold} gold on the body.", data={"gold": gold}))
        for dropped in _drops(state, content, rng, monster):
            # (a bomb or small key is yours at once, in the next event; anything else lies there until it's taken)
            lies = "" if dropped in inventory.PICKUPS else "; it lies on the floor (not picked up)"
            events.append(Event("drop", f"{cap(the(monster.name))} dropped {a(content.item(dropped).name)}{lies}.",
                                data=inventory.lay(state, dropped, "drop", monster.key)))
    elif not monster.ghost_of:  # talked down, it still parts with what it was keeping (a warden always has something)
        for kept in _kept(state, content, rng, monster):
            events.append(Event("drop", f"{cap(the(monster.name))} leaves {a(content.item(kept).name)} at your feet.",
                                data=inventory.lay(state, kept, "drop", monster.key)))
    return events + check_level(state, content)


def styled(state: GameState, content: Content, monster: MonsterState, xp: int, exploited: bool) -> list[Event]:
    """What winning in style pays (STYLES): Flawless, if it had a go at you and never drew blood; Exploited, if the
    killing blow found its weakness. Each a fifth more of its XP (1 at least) and 3 gold a tier."""
    won = [key for key, earned in (("flawless", monster.swings and not monster.dealt), ("exploited", exploited))
           if earned]
    events = []
    for key in won:
        name, why = STYLES[key]
        more, gold = max(1, round(xp * STYLE_XP)), STYLE_GOLD * tier_of(monster, content)
        state.player.xp += more
        state.player.gold += gold
        state.player.bump(key)
        events.append(Event("style", f"{name}: {why}. +{more} XP, +{gold} gold.",
                            data={"style": key, "name": name, "xp": more, "gold": gold}))
    return events


def _give_back(state: GameState, content: Content, monster: MonsterState) -> list[Event]:
    """What a thief grabbed, back where it belongs: and no longer its to run off with."""
    events = []
    if monster.stolen_gold:
        state.player.gold += monster.stolen_gold
        events.append(Event("loot", f"You get your {monster.stolen_gold} gold back."))
    if monster.stolen_item:
        events.append(Event("drop", f"{cap(the(monster.name))} drops your {content.item(monster.stolen_item).name}.",
                            data=inventory.lay(state, monster.stolen_item, "drop", monster.key)))
    monster.stolen_gold, monster.stolen_item = 0, ""
    return events


def _drops(state: GameState, content: Content, rng: random.Random, monster: MonsterState) -> list[str]:
    """What a slain monster leaves: sometimes a potion, a small key or a bomb, a Pure from a venomous one, and
    whatever it was keeping (_kept)."""
    drops = [loot.pick(rng, content, loot.DROP)] if rng.random() < 0.3 else []
    drops += _kept(state, content, rng, monster)
    if rng.random() < (0.5 if monster.elite else 0.25):
        drops.append("small_key")
    if rng.random() < (0.25 if monster.elite else 0.12):
        drops.append("bomb")
    tricks = tricks_of(monster, content)
    if tricks & VENOMOUS and "pure" in content.items and rng.random() < PURE_DROP:
        drops.append("pure")  # (what it bit you with, it carries the cure for)
    return [d for d in drops if d]


def _kept(state: GameState, content: Content, rng: random.Random, monster: MonsterState) -> list[str]:
    """What a monster was keeping, which it leaves slain or talked down: the rare thing that names it as the one that
    drops it, or else (now and then, from an elite; a third of the time, from the warden by the stairs) something
    rare. A warden always leaves something: a small key or a bomb, if not that."""
    own = [i.key for i in content.items.values() if monster.key in i.found and i.key not in state.rares]
    warden = monster.warden  # (not whatever crept up on you while you rested by the stairs)
    if own:
        state.rares.append(own[0])
        return own[:1]
    if (warden or monster.elite) and rng.random() < (loot.WARDEN_DROP if warden else loot.ELITE_DROP):
        kept = loot.produce(rng, content, state.rares, loot.WARDEN[min(state.floor, 3)], "warden",
                            loot.owned(state, content))
        return [kept] if kept else []
    return [rng.choice(loot.WARDEN_ELSE)] if warden else []
