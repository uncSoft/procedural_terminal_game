"""Game rules: which actions are possible right now, and what actually happens when you take one.

Every function here mutates GameState and returns Events: plain-English facts the narrator turns into prose.
The language model never changes state directly.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import dice
from .content import Content
from .intent import DC, Intent
from .models import DIRECTIONS, Feature, GameState
from .world import monster_for, tier_for

MONSTER_EFFECTS = {"damage_small", "damage_medium", "damage_large", "stun", "pacify", "escape"}
ONCE_PER_ROOM = {"find_item", "find_gold", "heal_small"}
SELF_HARM = {"hurt_self_small", "hurt_self_medium"}
CREATIVE_DAMAGE = {"damage_small": "1d4", "damage_medium": "2d6", "damage_large": "3d6"}


@dataclass
class Event:
    kind: str
    text: str
    roll: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class Action:
    id: str
    label: str


# --- helpers ---------------------------------------------------------------

def the(name: str) -> str:
    lower = name.lower()
    for article in ("the ", "a ", "an "):
        if lower.startswith(article):
            return "the " + name[len(article):]
    return "the " + name


def cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _distinct(keys: list[str]) -> list[str]:
    return list(dict.fromkeys(keys))


def _rng(state: GameState) -> random.Random:
    return dice.stream(state.seed, "turn", state.turn)


def a(name: str) -> str:
    return ("an " if name[:1].lower() in "aeiou" else "a ") + name


def _check(rng: random.Random, label: str, bonus: int, dc: int) -> tuple[bool, str, int]:
    roll = dice.d20(rng)
    total = roll + bonus
    success = roll == 20 or (roll != 1 and total >= dc)
    return success, f"{label}: d20 {roll} + {bonus} = {total} vs {dc} - {'success' if success else 'fail'}", roll


# --- what can the player do? -----------------------------------------------

def available_actions(state: GameState, content: Content) -> list[Action]:
    if state.over:
        return []
    room, player = state.room, state.player
    actions: list[Action] = []
    consumables = [content.item(k) for k in _distinct(player.inventory) if content.item(k).kind == "consumable"]

    if state.in_combat:
        actions.append(Action("attack", f"Attack {the(room.monster.name)}"))
        for item in consumables:
            if item.escape or player.hp < player.max_hp:
                verb = "Throw" if item.escape else ("Eat" if item.key == "stale_bread" else "Drink")
                actions.append(Action(f"use:{item.key}", f"{verb} the {item.name}"))
        if _flee_direction(state):
            actions.append(Action("flee", "Try to flee"))
        return actions

    for key in _distinct(room.items):
        actions.append(Action(f"take:{key}", f"Pick up the {content.item(key).name}"))
    for index, feature in room.visible_features():
        if not feature.searched:
            actions.append(Action(f"search:{index}", f"Search {the(feature.name)}"))
    if room.monster:
        actions.append(Action("attack", f"Attack {the(room.monster.name)}"))
    theme = content.themes[state.theme]
    for direction in DIRECTIONS:
        exit_ = room.exits.get(direction)
        if not exit_:
            continue
        dest = state.rooms[exit_.to]
        if exit_.locked:
            has_key = theme.key_item in player.inventory
            actions.append(Action(f"go:{direction}", f"Unlock the door {direction}" if has_key else f"Go {direction} (locked)"))
        else:
            where = f" to {the(dest.name)}" if dest.visited else ""
            actions.append(Action(f"go:{direction}", f"Go {direction}{where}"))
    if player.hp < player.max_hp:
        for item in consumables:
            if item.heal:
                verb = "Eat" if item.key == "stale_bread" else "Drink"
                actions.append(Action(f"use:{item.key}", f"{verb} the {item.name}"))
    if not room.room_searched:
        actions.append(Action("search_room", "Search the room for secrets"))
    if not room.rested and player.hp < player.max_hp:
        actions.append(Action("rest", "Rest a while"))
    return actions


# --- resolving actions -----------------------------------------------------

def perform(state: GameState, content: Content, action_id: str) -> list[Event]:
    """Resolve one engine action. Unknown or impossible actions return an info event and cost nothing."""
    if state.over:
        return []
    if action_id not in {a.id for a in available_actions(state, content)}:
        return [Event("info", "You can't do that right now.")]
    rng = _rng(state)
    was_in_combat, room_before = state.in_combat, state.room_id
    verb, _, arg = action_id.partition(":")

    if verb == "attack":
        events, took_turn = _attack(state, content, rng), True
    elif verb == "go":
        events, took_turn = _move(state, content, arg)
    elif verb == "take":
        state.room.items.remove(arg)
        events, took_turn = _gain_item(state, content, arg), True
    elif verb == "search":
        events, took_turn = _search_feature(state, content, state.room.features[int(arg)]), True
    elif verb == "search_room":
        events, took_turn = _search_room(state, content, rng), True
    elif verb == "use":
        events, took_turn = _use(state, content, rng, arg)
    elif verb == "flee":
        events, took_turn = _flee(state, content, rng), True
    elif verb == "rest":
        events, took_turn = _rest(state, content, rng), True
    else:
        return [Event("info", "You can't do that right now.")]
    return _finish_turn(state, content, rng, events, took_turn, was_in_combat, room_before)


def perform_creative(state: GameState, content: Content, intent: Intent) -> tuple[Intent, list[Event]]:
    """Resolve a free-text attempt: roll the check the interpreter proposed, then apply its (clamped) effects."""
    if state.over:
        return intent, []
    intent = clamp_intent(state, content, intent)
    rng = _rng(state)
    was_in_combat, room_before = state.in_combat, state.room_id
    summary = intent.summary or "try something unexpected"

    if intent.difficulty == "trivial" or not intent.success_effects:
        events = [Event("creative", f"You {summary}.")]
        return intent, _finish_turn(state, content, rng, events, was_in_combat, was_in_combat, room_before)

    bonus = state.player.stat(intent.stat)
    if intent.difficulty == "absurd":
        roll = dice.d20(rng)
        success, detail = False, f"{intent.stat}: d20 {roll} + {bonus} vs impossible - fail"
    else:
        success, detail, _ = _check(rng, intent.stat, bonus, DC[intent.difficulty])
    events = [Event("check", f"You attempt to {summary}. It {'works' if success else 'fails'}.", roll=detail,
                    data={"success": success})]
    for effect in intent.success_effects if success else intent.failure_effects:
        events += _apply_effect(state, content, rng, effect, bonus)
        if state.over:
            break
    return intent, _finish_turn(state, content, rng, events, True, was_in_combat, room_before)


def perform_flavor(state: GameState, content: Content) -> list[Event]:
    """Harmless free text. Costs nothing outside a fight, but in a fight the monster gets its turn."""
    if not state.in_combat:
        return []
    rng = _rng(state)
    return _finish_turn(state, content, rng, [], True, True, state.room_id)


def clamp_intent(state: GameState, content: Content, intent: Intent) -> Intent:
    """Keep the interpreter honest: drop effects that can't apply here and cap how strong they can be."""
    room = state.room
    monster = room.monster if room.monster and room.monster.hp > 0 else None
    monster_def = content.monster(monster.key) if monster else None
    difficulty = intent.difficulty
    effects: list[str] = []
    for effect in intent.success_effects:
        if effect in SELF_HARM or effect == "nothing":
            continue
        if effect in MONSTER_EFFECTS and not monster:
            continue
        if effect == "escape" and not state.in_combat:
            continue
        if effect in ONCE_PER_ROOM and effect in room.creative_uses:
            continue
        if effect == "pacify":
            if monster_def.boss:
                effect = "stun"
            elif not monster_def.intelligent:
                continue
            elif monster.hostile and difficulty in ("easy", "medium"):
                difficulty = "hard"
        if effect == "damage_large" and difficulty not in ("hard", "absurd"):
            effect = "damage_medium"
        if effect.startswith("damage_") and difficulty == "easy":
            effect = "damage_small"
        if effect == "heal_small" and difficulty == "easy":
            difficulty = "medium"
        if effect not in effects:
            effects.append(effect)
    failure = [e for e in intent.failure_effects if e in SELF_HARM][:1]
    stat = intent.stat if intent.stat != "none" else "wits"
    return intent.model_copy(update={"success_effects": effects[:2], "failure_effects": failure,
                                     "difficulty": difficulty, "stat": stat})


def _finish_turn(state, content, rng, events, took_turn, was_in_combat, room_before) -> list[Event]:
    if took_turn:
        state.turn += 1
        if was_in_combat and state.room_id == room_before and state.in_combat and not state.over:
            events += _monster_turn(state, content, rng)
    return events


# --- individual rules --------------------------------------------------------

def _attack(state: GameState, content: Content, rng: random.Random) -> list[Event]:
    room, player = state.room, state.player
    monster = room.monster
    monster_def = content.monster(monster.key)
    weapon = content.item(player.weapon)
    events = []
    if not monster.hostile:
        monster.hostile = True
        events.append(Event("provoke", f"{cap(the(monster.name))} had stopped fighting. It hasn't now."))
    hit, detail, roll = _check(rng, "attack", player.attack_bonus, monster_def.defense)
    if not hit:
        events.append(Event("miss", f"You swing your {weapon.name} at {the(monster.name)} and miss.", roll=detail))
        return events
    crit = roll == 20
    damage = dice.roll(weapon.damage, rng) + (dice.roll(weapon.damage, rng) if crit else 0) + player.might
    monster.hp -= damage
    how = "land a critical hit on" if crit else "hit"
    events.append(Event("hit", f"You {how} {the(monster.name)} with your {weapon.name} for {damage} damage "
                               f"({max(monster.hp, 0)}/{monster.max_hp} HP left).", roll=detail))
    if monster.hp <= 0:
        events += _defeat(state, content, rng)
    return events


def _monster_turn(state: GameState, content: Content, rng: random.Random) -> list[Event]:
    monster, player = state.room.monster, state.player
    monster_def = content.monster(monster.key)
    if monster.stunned > 0:
        monster.stunned -= 1
        return [Event("stunned", f"{cap(the(monster.name))} is still reeling and can't attack.")]
    hit, detail, roll = _check(rng, f"{monster.name} attacks", monster_def.attack, player.defense(content))
    if not hit:
        return [Event("monster_miss", f"{cap(the(monster.name))} attacks you and misses.", roll=detail)]
    crit = roll == 20
    damage = dice.roll(monster_def.damage, rng) + (dice.roll(monster_def.damage, rng) if crit else 0)
    player.hp = max(0, player.hp - damage)
    how = "lands a vicious critical hit on you" if crit else "hits you"
    events = [Event("monster_hit", f"{cap(the(monster.name))} {how} for {damage} damage "
                                   f"({player.hp}/{player.max_hp} HP left).", roll=detail)]
    if player.hp == 0:
        state.status = "dead"
        events.append(Event("death", f"You fall to {the(monster.name)}. Your adventure ends here."))
    return events


def _defeat(state: GameState, content: Content, rng: random.Random) -> list[Event]:
    room, player = state.room, state.player
    monster = room.monster
    monster_def = content.monster(monster.key)
    room.monster = None
    player.xp += monster_def.xp
    player.kills += 1
    events = [Event("defeat", f"{cap(the(monster.name))} is defeated. You gain {monster_def.xp} XP.")]
    if monster_def.boss:
        theme = content.themes[state.theme]
        state.status = "won"
        events.append(Event("victory", f"You have conquered {theme.name}. {theme.goal} Done."))
        return events
    gold = rng.randint(1, 6) * monster_def.tier
    player.gold += gold
    events.append(Event("loot", f"You find {gold} gold on the body."))
    if rng.random() < 0.3:
        room.items.append("healing_potion")
        events.append(Event("drop", f"{cap(the(monster.name))} dropped a Healing Potion."))
    return events + _check_level(state)


def _check_level(state: GameState) -> list[Event]:
    player = state.player
    events = []
    while player.next_level_xp() is not None and player.xp >= player.next_level_xp():
        player.level += 1
        player.max_hp += 6
        player.hp += 6
        events.append(Event("level", f"You reach level {player.level}! Max HP +6 and your attacks improve."))
    return events


def _move(state: GameState, content: Content, direction: str) -> tuple[list[Event], bool]:
    exit_ = state.room.exits.get(direction)
    if not exit_:
        return [Event("info", f"There is no way {direction}.")], False
    events = []
    if exit_.locked:
        key = content.item(content.themes[state.theme].key_item)
        if key.key not in state.player.inventory:
            return [Event("locked", f"The door to the {direction} is locked. It looks like it needs the {key.name}.")], False
        exit_.locked = False
        events.append(Event("unlock", f"You unlock the door to the {direction} with the {key.name}."))
    return events + _travel(state, content, direction, exit_.to), True


def _travel(state: GameState, content: Content, direction: str, to: int) -> list[Event]:
    state.prev_room_id, state.room_id = state.room_id, to
    room = state.room
    first = not room.visited
    room.visited = True
    arrival = f"You go {direction} into {the(room.name)}" + (" for the first time." if first else ", where you've been before.")
    return [Event("enter", f"{arrival} {room_facts(state, content)}", data={"first": first, "room": room.id})]


def room_facts(state: GameState, content: Content) -> str:
    room = state.room
    lines = []
    features = [f.name for _, f in room.visible_features()]
    if features:
        lines.append("In the room: " + ", ".join(features) + ".")
    if room.items:
        lines.append("On the floor: " + ", ".join(content.item(k).name for k in room.items) + ".")
    exits = [f"{d} (locked)" if e.locked else d for d, e in room.exits.items()]
    lines.append("Exits: " + ", ".join(exits) + ".")
    if room.monster:
        if room.monster.hostile:
            lines.append(f"{cap(the(room.monster.name))} is here and hostile. A fight begins.")
        else:
            lines.append(f"{cap(the(room.monster.name))} is here, but no longer wants to fight.")
    return " ".join(lines)


def _gain_item(state: GameState, content: Content, key: str) -> list[Event]:
    player, item = state.player, content.item(key)
    if item.kind == "weapon":
        current = content.item(player.weapon)
        if item.tier > current.tier:
            player.weapon = key
            return [Event("equip", f"You take the {item.name} ({item.damage}) and toss aside your {current.name}.")]
    if item.kind == "armor":
        current = content.item(player.armor) if player.armor else None
        if current is None or item.tier > current.tier:
            player.armor = key
            swap = f" and leave your {current.name} behind" if current else ""
            return [Event("equip", f"You put on the {item.name} (+{item.defense} defense){swap}.")]
    player.inventory.append(key)
    if item.kind == "key":
        return [Event("key", f"You take the {item.name}. It must open something important.")]
    return [Event("take", f"You take the {item.name}.")]


def _search_feature(state: GameState, content: Content, feature: Feature) -> list[Event]:
    feature.searched = True
    events = []
    for key in feature.loot:
        events.append(Event("find", f"You search {the(feature.name)} and find the {content.item(key).name}."))
        events += _gain_item(state, content, key)
    feature.loot = []
    if feature.gold:
        state.player.gold += feature.gold
        events.append(Event("find", f"You search {the(feature.name)} and find {feature.gold} gold."))
        feature.gold = 0
    return events or [Event("search", f"You search {the(feature.name)} but find nothing useful.")]


def _search_room(state: GameState, content: Content, rng: random.Random) -> list[Event]:
    room = state.room
    room.room_searched = True
    success, detail, _ = _check(rng, "wits", state.player.wits, 12)
    hidden = [f for f in room.features if f.hidden]
    if success and hidden:
        for feature in hidden:
            feature.hidden = False
        names = ", ".join(f.name for f in hidden)
        return [Event("secret", f"Searching carefully, you discover something hidden: {names}.", roll=detail)]
    return [Event("search_room", "You search every corner but find nothing hidden.", roll=detail)]


def _use(state: GameState, content: Content, rng: random.Random, key: str) -> tuple[list[Event], bool]:
    player, item = state.player, content.item(key)
    if item.escape:
        if not state.in_combat:
            return [Event("info", f"You decide to save the {item.name} for an emergency.")], False
        player.inventory.remove(key)
        return [Event("use", f"You hurl the {item.name} at your feet. Thick smoke fills the room.")] + _flee(
            state, content, rng, guaranteed=True), True
    if player.hp >= player.max_hp:
        return [Event("info", f"You're not hurt, so you keep the {item.name}.")], False
    healed = min(item.heal, player.max_hp - player.hp)
    player.hp += healed
    player.inventory.remove(key)
    verb = "eat" if key == "stale_bread" else "drink"
    return [Event("heal", f"You {verb} the {item.name} and recover {healed} HP ({player.hp}/{player.max_hp}).")], True


def _flee_direction(state: GameState) -> str | None:
    open_exits = [(d, e) for d, e in state.room.exits.items() if not e.locked]
    for direction, exit_ in open_exits:
        if exit_.to == state.prev_room_id:
            return direction
    return open_exits[0][0] if open_exits else None


def _flee(state: GameState, content: Content, rng: random.Random, guaranteed: bool = False) -> list[Event]:
    monster = state.room.monster
    direction = _flee_direction(state)
    if direction is None:
        return [Event("info", "There is nowhere to run.")]
    if not guaranteed:
        dc = 10 + content.monster(monster.key).tier
        success, detail, _ = _check(rng, "agility", state.player.agility, dc)
        if not success:
            return [Event("flee_fail", f"You try to flee, but {the(monster.name)} cuts you off.", roll=detail)]
    escape = Event("flee", f"You escape from {the(monster.name)}, running {direction}.")
    return [escape] + _travel(state, content, direction, state.room.exits[direction].to)


def _rest(state: GameState, content: Content, rng: random.Random) -> list[Event]:
    room, player = state.room, state.player
    room.rested = True
    if rng.random() < 0.25:
        max_distance = max(r.distance for r in state.rooms)
        room.monster = monster_for(rng, content, state.theme, tier_for(room.distance, max_distance))
        events = [Event("ambush", f"While you rest, {a(room.monster.name)} creeps up on you!")]
        return events + _monster_turn(state, content, rng)
    healed = min(dice.roll("1d6", rng) + player.wits, player.max_hp - player.hp)
    player.hp += healed
    return [Event("rest", f"You rest for a while and recover {healed} HP ({player.hp}/{player.max_hp}).")]


def _apply_effect(state: GameState, content: Content, rng: random.Random, effect: str, bonus: int) -> list[Event]:
    room, player = state.room, state.player
    monster = room.monster
    if effect in ONCE_PER_ROOM:
        room.creative_uses.append(effect)
    if effect in CREATIVE_DAMAGE:
        damage = dice.roll(CREATIVE_DAMAGE[effect], rng) + max(0, bonus)
        monster.hp -= damage
        monster.hostile = True
        events = [Event("hit", f"{cap(the(monster.name))} takes {damage} damage "
                               f"({max(monster.hp, 0)}/{monster.max_hp} HP left).")]
        return events + (_defeat(state, content, rng) if monster.hp <= 0 else [])
    if effect == "stun":
        monster.stunned = 2  # covers this turn's attack and the next one, so a stun buys a free action
        return [Event("stun", f"{cap(the(monster.name))} is stunned and loses its next two attacks.")]
    if effect == "pacify":
        monster.hostile = False
        xp = content.monster(monster.key).xp // 2
        player.xp += xp
        return [Event("pacify", f"{cap(the(monster.name))} stops fighting you. You gain {xp} XP.")] + _check_level(state)
    if effect == "escape":
        return _flee(state, content, rng, guaranteed=True)
    if effect == "reveal_secret":
        hidden = [f for f in room.features if f.hidden]
        room.room_searched = True
        for feature in hidden:
            feature.hidden = False
        if hidden:
            return [Event("secret", "You uncover something hidden: " + ", ".join(f.name for f in hidden) + ".")]
        return [Event("info", "There turns out to be nothing hidden here.")]
    if effect == "find_item":
        key = rng.choice(["stale_bread", "stale_bread", "healing_potion", "smoke_bomb"])
        return [Event("find", f"You turn up {a(content.item(key).name)}.")] + _gain_item(state, content, key)
    if effect == "find_gold":
        gold = rng.randint(2, 8) * max(1, room.distance)
        player.gold += gold
        return [Event("find", f"You find {gold} gold.")]
    if effect == "heal_small":
        healed = min(dice.roll("1d4+2", rng), player.max_hp - player.hp)
        player.hp += healed
        return [Event("heal", f"You recover {healed} HP ({player.hp}/{player.max_hp}).")]
    if effect in SELF_HARM:
        damage = dice.roll("1d4" if effect == "hurt_self_small" else "1d6+1", rng)
        player.hp = max(1, player.hp - damage)
        return [Event("hurt", f"You hurt yourself for {damage} damage ({player.hp}/{player.max_hp} HP).")]
    return []
