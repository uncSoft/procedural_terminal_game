"""Fighting: attacks, telegraphed monster moves, dodging, fleeing, and what happens when something dies."""

from __future__ import annotations

import random

from . import dice
from .content import Content
from .events import Event
from .models import GameState, MonsterState
from .text import cap, the

INTENT_WEIGHTS = {
    "boss": {"strike": 45, "heavy": 40, "guard": 15},
    "elite": {"strike": 55, "heavy": 30, "guard": 15},
    "normal": {"strike": 65, "heavy": 22, "guard": 13},
}


def monster_defense(monster: MonsterState, content: Content) -> int:
    return content.monster(monster.key).defense + monster.defense_mod + (4 if monster.guarding else 0)


def choose_intent(rng: random.Random, monster: MonsterState, content: Content) -> str:
    kind = "boss" if content.monster(monster.key).boss else ("elite" if monster.elite else "normal")
    weights = INTENT_WEIGHTS[kind]
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def telegraph(state: GameState, content: Content) -> list[Event]:
    monster = state.room.monster
    if monster and monster.hostile and monster.intent == "heavy":
        tell = content.monster(monster.key).tell
        return [Event("telegraph", f"{cap(the(monster.name))} {tell}. A heavy blow is coming!")]
    return []


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
        events.append(Event("provoke", f"{cap(the(monster.name))} had stopped fighting. It hasn't now."))
    advantage = 1 if (monster.stunned or player.advantage_next) else 0
    player.advantage_next = False
    bonuses = [("might", player.might), ("level", player.level)]
    roll = dice.check(rng, "attack", bonuses, monster_defense(monster, content), advantage=advantage)
    events_on_roll = fortune(state, roll)
    if not roll.success:
        guarded = " It's guarding, and your blow glances off." if monster.guarding else ""
        events.append(Event("miss", f"You swing your {weapon.name} at {the(monster.name)} and miss.{guarded}", dice=roll))
        return events + events_on_roll

    damage = dice.roll(weapon.damage, rng) + (dice.roll(weapon.damage, rng) if roll.crit else 0) + player.might
    extras = []
    if "brute" in player.traits:
        damage += 1
    if "glass_cannon" in player.perks:
        damage += 3
    if "bully" in player.perks and monster.stunned:
        damage += 3
        extras.append("Bully")
    if "sharp_start" in player.blessings and player.weapon == "rusty_sword":
        damage += 1
    weak = [t for t in weapon.tags if t in monster_def.weak]
    if weak:
        damage += 2
        extras.append(f"{weak[0]}!")
    if "monster_scholar" in player.traits and state_known(state, monster.key):
        damage += 1
    player.hits_landed += 1
    if "ruthless" in player.perks and player.hits_landed % 3 == 0:
        damage *= 2
        extras.append("Ruthless x2")
    monster.hp -= damage
    how = "land a critical hit on" if roll.crit else "hit"
    tail = f" [{', '.join(extras)}]" if extras else ""
    events.append(Event("hit", f"You {how} {the(monster.name)} with your {weapon.name} for {damage} damage "
                               f"({max(monster.hp, 0)}/{monster.max_hp} HP left).{tail}", dice=roll,
                        data={"damage": damage}))
    for tag in weak:
        events += discover(state, monster, tag)
    events += events_on_roll
    if monster.hp <= 0:
        events += defeat(state, content, rng)
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
        why = "A natural 20!" if roll.crit else "Fortune's Fool: your blunder pleases the gods."
        return [Event("fate", f"{why} You gain a Fate token ({player.fate}/{player.max_fate()}).")]
    return []


def monster_turn(state: GameState, content: Content, rng: random.Random) -> list[Event]:
    room, player = state.room, state.player
    monster = room.monster
    monster_def = content.monster(monster.key)
    monster.guarding = False
    dodging, player.dodging = player.dodging, False
    if monster.stunned > 0:
        monster.stunned -= 1
        monster.intent = "strike"
        return [Event("stunned", f"{cap(the(monster.name))} is still reeling and can't attack.")]

    intent = monster.intent
    monster.intent = choose_intent(rng, monster, content)
    if intent == "guard":
        monster.guarding = True
        events = [Event("guard", f"{cap(the(monster.name))} hunkers down and guards itself (+4 defense).")]
        return events + telegraph(state, content)

    if dodging:
        perfect = intent == "heavy"
        events = [Event("dodge", f"You slip aside and {the(monster.name)}'s "
                                 f"{'heavy blow' if perfect else 'attack'} hits nothing but air.")]
        if perfect:
            player.advantage_next = True
            if player.fate < player.max_fate():
                player.fate += 1
            events.append(Event("fate", "Perfect dodge! Your next attack has advantage, and you gain a Fate token "
                                        f"({player.fate}/{player.max_fate()})."))
        return events + telegraph(state, content)

    attack = monster_def.attack + monster.attack_mod
    label = f"{monster.name} {'HEAVY attack' if intent == 'heavy' else 'attacks'}"
    roll = dice.check(rng, label, [("attack", attack)], player.defense(content), actor="monster")
    if not roll.success:
        return [Event("monster_miss", f"{cap(the(monster.name))} attacks you and misses.", dice=roll)] + telegraph(state, content)

    room_key = f"{state.floor}:{room.id}"
    if "acrobatics" in player.perks and room_key not in player.evaded_rooms:
        player.evaded_rooms.append(room_key)
        return [Event("evade", f"Acrobatics! You tumble clear of {the(monster.name)}'s blow.", dice=roll)] + telegraph(state, content)

    rolls = 2 if intent == "heavy" else (2 if roll.crit else 1)  # heavy blows and crits don't stack
    damage = sum(dice.roll(monster_def.damage, rng) for _ in range(rolls))
    damage += monster.damage_mod
    player.hp = max(0, player.hp - damage)
    how = "lands a crushing heavy blow on you" if intent == "heavy" else (
        "lands a vicious critical hit on you" if roll.crit else "hits you")
    events = [Event("monster_hit", f"{cap(the(monster.name))} {how} for {damage} damage "
                                   f"({player.hp}/{player.max_hp} HP left).", dice=roll, data={"damage": damage})]
    if player.hp == 0:
        events += _death_or_reprieve(state, monster)
    return events + ([] if state.over else telegraph(state, content))


def _death_or_reprieve(state: GameState, monster: MonsterState) -> list[Event]:
    player = state.player
    if "second_wind" in player.perks and player.second_wind_floor != state.floor:
        player.second_wind_floor = state.floor
        player.hp = 1
        return [Event("reprieve", "Second Wind! You refuse to fall and stagger up with 1 HP.")]
    if "last_breath" in player.blessings and not player.last_breath_used:
        player.last_breath_used = True
        player.hp = 1
        return [Event("reprieve", "Last Breath: something in the dark isn't finished with you. You live, with 1 HP.")]
    state.status = "dead"
    state.cause = f"slain by {monster.name} on floor {state.floor}"
    return [Event("death", f"You fall to {the(monster.name)}. Your adventure ends here.", data={"monster": monster.key})]


def dodge(state: GameState, content: Content, rng: random.Random) -> list[Event]:
    monster = state.room.monster
    player = state.player
    tier = content.monster(monster.key).tier
    advantage = 1 if "duelist" in player.traits else 0
    roll = dice.check(rng, "agility (dodge)", [("agility", player.agility)], 9 + tier, advantage=advantage)
    events = fortune(state, roll)
    if roll.success:
        player.dodging = True
        player.bump("dodged")
        return [Event("dodge_ready", "You read the attack and get ready to move.", dice=roll,
                      data={"rerollable": True})] + events
    return [Event("dodge_fail", "You try to get out of the way, but you're a step too slow.", dice=roll,
                  data={"rerollable": True})] + events


def flee_direction(state: GameState) -> str | None:
    open_exits = [(d, e) for d, e in state.room.exits.items() if not e.locked]
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
    if not guaranteed:
        dc = 10 + content.monster(monster.key).tier
        advantage = 1 if "escape_artist" in state.player.traits else 0
        roll = dice.check(rng, "agility (flee)", [("agility", state.player.agility)], dc, advantage=advantage)
        events += fortune(state, roll)
        if not roll.success:
            return [Event("flee_fail", f"You try to flee, but {the(monster.name)} cuts you off.", dice=roll,
                          data={"rerollable": True})] + events
        events.insert(0, Event("flee", f"You escape from {the(monster.name)}, running {direction}.", dice=roll,
                               data={"rerollable": True}))
    else:
        events.append(Event("flee", f"You escape from {the(monster.name)}, running {direction}."))
    state.player.bump("fled")
    monster.intent = "strike"
    return events + travel(state, content, direction, state.room.exits[direction].to)


def defeat(state: GameState, content: Content, rng: random.Random, how: str = "slain") -> list[Event]:
    """The monster in this room is gone: slain or talked down. Rewards, drops, and maybe the win."""
    from .rules import check_level

    room, player = state.room, state.player
    monster = room.monster
    monster_def = content.monster(monster.key)
    room.monster = None if how == "slain" else monster
    xp = round(monster_def.xp * (0.6 if how == "pacified" else 1.0) * (1.5 if monster.elite else 1.0))
    souls = round((40 if monster_def.boss else 3 * monster_def.tier) * monster.reward_mult)
    player.xp += xp
    state.souls += souls
    data = {"monster": monster.key, "how": how, "ghost_id": monster.ghost_id}
    if how == "slain":
        player.kills += 1
        player.bump("kills")
        events = [Event("defeat", f"{cap(the(monster.name))} is defeated. +{xp} XP, +{souls} souls.", data=data)]
    else:
        player.bump("pacify")
        events = [Event("pacify", f"{cap(the(monster.name))} stops fighting you. +{xp} XP, +{souls} souls.", data=data)]
    if monster.ghost_of:
        room.monster = None
        state.souls += 15
        events.append(Event("ghost_rest", f"The ghost of {monster.ghost_of} finally rests. Their belongings are yours "
                                          "to take. +15 souls.", data=data))
    if monster_def.boss:
        theme = content.themes[state.theme]
        state.status = "won"
        state.cause = f"conquered {theme.name}"
        events.append(Event("victory", f"You have conquered {theme.name}. {theme.goal} Done.", data=data))
        return events
    if "vampiric" in player.perks and player.hp < player.max_hp:
        healed = min(3, player.max_hp - player.hp)
        player.hp += healed
        events.append(Event("heal", f"Vampiric: you drink in {healed} HP."))
    if how == "slain":
        gold = rng.randint(1, 6) * monster_def.tier * (2 if monster.elite else 1)
        player.gold += gold
        events.append(Event("loot", f"You find {gold} gold on the body."))
        if rng.random() < 0.3:
            room.items.append("healing_potion")
            events.append(Event("drop", f"{cap(the(monster.name))} dropped a Healing Potion."))
    return events + check_level(state, content)
