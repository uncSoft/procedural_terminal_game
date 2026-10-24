"""Fighting: attacks, telegraphed monster moves, dodging, fleeing, and what happens when something dies."""

from __future__ import annotations

import random

from . import dice, inventory, loot, powers
from .content import Content, ItemDef
from .events import Event
from .models import GameState, MonsterState
from .text import a, cap, mid_sentence, tell, the

INTENT_WEIGHTS = {
    "boss": {"strike": 45, "heavy": 40, "guard": 15},
    "elite": {"strike": 55, "heavy": 30, "guard": 15},
    "normal": {"strike": 65, "heavy": 22, "guard": 13},
}


def monster_defense(monster: MonsterState, content: Content) -> int:
    return content.monster(monster.key).defense + monster.defense_mod + (4 if monster.guarding else 0)


def tier_of(monster: MonsterState, content: Content) -> int:
    """How tough it counts as, for dodging, fleeing and what it pays: its maker's tier, or the floor's for a character
    cut down to size there (npcs.sized)."""
    return monster.tier or content.monster(monster.key).tier


def choose_intent(rng: random.Random, monster: MonsterState, content: Content) -> str:
    kind = "boss" if content.monster(monster.key).boss else ("elite" if monster.elite else "normal")
    weights = INTENT_WEIGHTS[kind]
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def telegraph(state: GameState, content: Content) -> list[Event]:
    monster = state.room.monster
    if monster and monster.hostile and monster.intent == "heavy":
        wind_up = tell(monster.name, content.monster(monster.key).tell).rstrip(" .")  # (the kids shout theirs)
        return [Event("telegraph", f"{wind_up}{'' if wind_up.endswith(('!', '?', '\"')) else '.'} A heavy blow is coming!")]
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
        events.append(provoked(monster, content))
    advantage = 1 if (monster.stunned or player.advantage_next) else 0
    player.advantage_next = False
    bonuses = [("might", player.might), ("level", player.level)] + powers.roll_bonuses(state, content, "attack")
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
    coating = [player.coating] if player.coated else []  # holy water or lamp oil on the blade (interactions.RECIPES)
    weak = list(dict.fromkeys(t for t in weapon.tags + coating if t in monster_def.weak))
    if weak:
        damage += 2
        extras.append(f"{weak[0]}!")
    worn = ""
    if coating:
        player.coated -= 1
        if not player.coated:
            worn, player.coating = f" The {coating[0]} coating on your {weapon.name} is spent.", ""
    if "goblin_bane" in weapon.powers and powers.GOBLINS & set(monster_def.tags):
        damage += 2
        extras.append("goblin-bane")
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
                               f"({max(monster.hp, 0)}/{monster.max_hp} HP left).{tail}{worn}", dice=roll,
                        data={"damage": damage}))
    for tag in weak:
        events += discover(state, monster, tag)
    events += events_on_roll
    if monster.hp <= 0:
        events += defeat(state, content, rng)
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
    events = fortune(state, roll)
    more = what_is_left(player, key)
    if not roll.success:
        return [Event("miss", f"You throw {the(item.name)} at {the(monster.name)} and miss. {gone}{more}",
                      dice=roll, data={"rerollable": True, **thrown})] + events
    damage = dice.roll(thrown_damage(item), rng) + (2 if weak else 0)
    monster.hp -= damage
    tail = (f" [{weak[0]}!]" if weak else "") + (f" {gone}" if item.kind == "weapon" else "")
    events.insert(0, Event("hit", f"{cap(the(item.name))} hits {the(monster.name)} for {damage} damage "
                                  f"({max(monster.hp, 0)}/{monster.max_hp} HP left).{tail}{more}", dice=roll,
                           data={"damage": damage, "rerollable": True, **thrown}))
    for tag in weak:
        events += discover(state, monster, tag)
    return events + (defeat(state, content, rng) if monster.hp <= 0 else [])


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
    tail = f" [{weak[0]}!]" if weak else ""
    events = [Event("hit", f"Your bomb goes off at {the(monster.name)}'s feet for {damage} damage "
                           f"({max(monster.hp, 0)}/{monster.max_hp} HP left).{tail}",
                    data={"damage": damage, "bomb": True})]
    for tag in weak[:1]:
        events += discover(state, monster, tag)
    return events + (defeat(state, content, rng) if monster.hp <= 0 else [])


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
    player.tangled = False  # (a tangle lasts until the monster's next go)
    if monster.stunned > 0:  # (a thief that's reeling, or can't take its eyes off something, isn't running yet)
        monster.stunned -= 1
        monster.intent = "strike"
        return [Event("stunned", f"{cap(the(monster.name))} is still reeling and can't attack.")]
    if monster.stolen_item or monster.stolen_gold:
        return _getaway(state, content, monster)

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
    damage = max(1, sum(dice.roll(monster_def.damage, rng) for _ in range(rolls)) + monster.damage_mod)  # a hit hurts
    reek = powers.holders(state, content, "reeks")
    if reek:  # it doesn't want to get close
        damage = max(1, damage - 2)
    player.hp = max(0, player.hp - damage)
    how = "lands a crushing heavy blow on you" if intent == "heavy" else (
        "lands a vicious critical hit on you" if roll.crit else "hits you")
    held_off = f" ({cap(the(reek[0].name))} keeps it at arm's length.)" if reek else ""
    events = [Event("monster_hit", f"{cap(the(monster.name))} {how} for {damage} damage "
                                   f"({player.hp}/{player.max_hp} HP left).{held_off}", dice=roll,
                    data={"damage": damage})]
    if player.hp == 0:
        events += _death_or_reprieve(state, monster)
    if not state.over:
        events += _tricks(state, content, rng, monster, monster_def)
    return events + ([] if state.over else telegraph(state, content))


def _tricks(state: GameState, content: Content, rng: random.Random, monster: MonsterState, monster_def) -> list[Event]:
    """What a monster with tricks does when it hits you (see content.TRICKS): grab something, or tangle you up."""
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
    return events


def _getaway(state: GameState, content: Content, monster: MonsterState) -> list[Event]:
    """A thief with something of yours runs off with it, on its next go if you didn't stop it."""
    what = the(content.item(monster.stolen_item).name) if monster.stolen_item else f"your {monster.stolen_gold} gold"
    state.room.monster = None
    state.room.remember(f"{the(monster.name)} ran off with {what}")
    return [Event("getaway", f"{cap(the(monster.name))} scampers off into the dark with {what}!")]


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
    state.cause = f"slain by {the(monster.name)} on floor {state.floor}"
    return [Event("death", f"You fall to {the(monster.name)}. Your adventure ends here.", data={"monster": monster.key})]


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
        dc = 10 + tier_of(monster, content)
        advantage = 1 if "escape_artist" in state.player.traits else 0
        bonuses = [("agility", state.player.agility)] + powers.roll_bonuses(state, content, "flee")
        roll = dice.check(rng, "agility (flee)", bonuses, dc, advantage=advantage)
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
    """The monster in this room is gone: slain or talked down. Rewards, drops, and maybe the win. One you'd talked
    down already has had its reward: killing it after (or calming it again) pays nothing more. A character talked
    down isn't a monster beaten: it's npcs.calm's to say how it takes it (no reward, and it keeps what it has)."""
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
    xp = round(monster_def.xp * (0.6 if how == "pacified" else 1.0) * (1.5 if monster.elite else 1.0))
    souls = round((40 if monster_def.boss else 3 * tier_of(monster, content)) * monster.reward_mult)
    player.xp += xp
    state.souls += souls
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
        events.append(Event("ghost_rest", f"The ghost of {monster.ghost_of}, your own earlier life, finally rests. "
                                          "Their belongings are yours to take. +15 souls.", data=data))
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
    events += _give_back(state, content, monster)
    if how == "slain":
        gold = rng.randint(1, 6) * tier_of(monster, content) * (2 if monster.elite else 1)
        player.gold += gold
        events.append(Event("loot", f"You find {gold} gold on the body."))
        for dropped in _drops(state, content, rng, monster):
            events.append(Event("drop", f"{cap(the(monster.name))} dropped {a(content.item(dropped).name)}.",
                                data=inventory.lay(state, dropped, "drop", monster.key)))
    elif not monster.ghost_of:  # talked down, it still parts with what it was keeping (a warden always has something)
        for kept in _kept(state, content, rng, monster):
            events.append(Event("drop", f"{cap(the(monster.name))} leaves {a(content.item(kept).name)} at your feet.",
                                data=inventory.lay(state, kept, "drop", monster.key)))
    return events + check_level(state, content)


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
    """What a slain monster leaves: sometimes a potion, a small key or a bomb, and whatever it was keeping (_kept)."""
    drops = [loot.pick(rng, content, loot.DROP)] if rng.random() < 0.3 else []
    drops += _kept(state, content, rng, monster)
    if rng.random() < (0.5 if monster.elite else 0.25):
        drops.append("small_key")
    if rng.random() < (0.25 if monster.elite else 0.12):
        drops.append("bomb")
    return [d for d in drops if d]


def _kept(state: GameState, content: Content, rng: random.Random, monster: MonsterState) -> list[str]:
    """What a monster was keeping, which it leaves slain or talked down: the rare thing that names it as the one that
    drops it, or else (sometimes, from an elite; always, from the warden by the stairs) something rare."""
    own = [i.key for i in content.items.values() if monster.key in i.found and i.key not in state.rares]
    warden = monster.warden  # (not whatever crept up on you while you rested by the stairs)
    if own:
        state.rares.append(own[0])
        return own[:1]
    if (warden or monster.elite) and rng.random() < (loot.WARDEN_DROP if warden else loot.ELITE_DROP):
        kept = loot.produce(rng, content, state.rares, loot.WARDEN[min(state.floor, 3)], "warden")
        return [kept] if kept else []
    return []
