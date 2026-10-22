"""Game rules: which actions are possible right now, and what actually happens when you take one.

Every function here mutates GameState and returns Events: plain-English facts the narrator turns into prose.
The language model never changes state directly.
"""

from __future__ import annotations

import random

from . import dice, layout
from .combat import dodge, flee, flee_direction, fortune, monster_turn, player_attack, telegraph
from .content import Content
from .creative import perform_creative as _creative
from .events import Action, Event
from .intent import Intent
from .models import DIRECTIONS, OPPOSITE, Feature, GameState
from .text import a, cap, the
from .world import build_floor, monster_for, tier_for

# Traits are earned by how you play: (name, style counter, threshold, what it does)
TRAITS = {
    "silver_tongue": ("Silver Tongue", "pacify", 2, "Talking monsters down has advantage."),
    "showboat": ("Showboat", "flair", 3, "+1 more flair when you use props."),
    "trickster": ("Trickster", "creative_win", 4, "+1 on every creative check."),
    "escape_artist": ("Escape Artist", "fled", 2, "Fleeing has advantage."),
    "brute": ("Brute", "kills", 6, "+1 damage on every weapon hit."),
    "treasure_nose": ("Treasure Nose", "searched", 6, "+2 when searching a room for secrets."),
    "fortunes_fool": ("Fortune's Fool", "fumbles", 3, "Natural 1s give you a Fate token."),
    "monster_scholar": ("Monster Scholar", "weakness", 3, "+1 damage against monsters whose weakness you know."),
    "duelist": ("Duelist", "dodged", 3, "Dodging has advantage."),
}

HEAL_VERBS = {"stale_bread": "Eat", "cheese_wheel": "Eat"}
CHEST_LOOT = {1: ["leather_jerkin", "oil_flask", "smoke_bomb", "healing_potion"],
              2: ["chain_shirt", "war_pick", "greater_healing_potion", "lucky_charm"],
              3: ["scale_hauberk", "silvered_blade", "greater_healing_potion", "lucky_charm"]}
FIXTURE_FACTS = {
    "stairs": "A staircase leads down into the dark.",
    "shrine": "A small shrine stands in the middle of the room, hungry for an offering.",
    "chest": "An iron-bound chest sits in the middle of the room.",
    "fountain": "A fountain of strange, shimmering water burbles in the middle of the room.",
}


def _distinct(keys: list[str]) -> list[str]:
    return list(dict.fromkeys(keys))


def _rng(state: GameState) -> random.Random:
    return dice.stream(state.seed, "turn", state.turn, state.reroll)


# --- what can the player do? -----------------------------------------------

def available_actions(state: GameState, content: Content) -> list[Action]:
    if state.over:
        return []
    if state.pending_perks:
        return [Action(f"perk:{k}", f"{content.perks[k].name}: {content.perks[k].desc}", "level up")
                for k in state.pending_perks]
    room, player = state.room, state.player
    actions: list[Action] = []
    consumables = [content.item(k) for k in _distinct(player.inventory) if content.item(k).kind == "consumable"]

    if state.in_combat:
        monster = room.monster
        actions.append(Action("attack", f"Attack {the(monster.name)}", "it's guarding" if monster.guarding else ""))
        actions.append(Action("dodge", "Dodge", "counter the heavy blow!" if monster.intent == "heavy" else ""))
        for item in consumables:
            if item.escape or player.hp < player.max_hp:
                verb = "Throw" if item.escape else HEAL_VERBS.get(item.key, "Drink")
                actions.append(Action(f"use:{item.key}", f"{verb} the {item.name}"))
        if flee_direction(state):
            actions.append(Action("flee", "Try to flee"))
        return actions

    for key in _distinct(room.items):
        actions.append(Action(f"take:{key}", f"Pick up the {content.item(key).name}"))
    for index, feature in room.visible_features():
        if not feature.searched:
            actions.append(Action(f"search:{index}", f"Search {the(feature.name)}"))
    actions += _fixture_actions(state)
    if room.monster:
        actions.append(Action("attack", f"Attack {the(room.monster.name)}", "it's calm"))
    theme = content.themes[state.theme]
    for direction in DIRECTIONS:
        exit_ = room.exits.get(direction)
        if not exit_:
            continue
        dest = state.rooms[exit_.to]
        if exit_.locked:
            has_key = theme.key_item in player.inventory
            label = f"Unlock the door {direction}" if has_key else f"Go {direction}"
            actions.append(Action(f"go:{direction}", label, "boss" if has_key else "locked"))
            continue
        hint = ""
        if dest.fixture and not dest.fixture_used:
            hint = {"stairs": "stairs down"}.get(dest.fixture, dest.fixture)
        elif dest.visited and dest.monster and dest.monster.hostile:
            hint = "danger"
        where = f" to {the(dest.name)}" if dest.visited else ""
        actions.append(Action(f"go:{direction}", f"Go {direction}{where}", hint))
    if player.hp < player.max_hp:
        for item in consumables:
            if item.heal:
                actions.append(Action(f"use:{item.key}", f"{HEAL_VERBS.get(item.key, 'Drink')} the {item.name}"))
    if not room.room_searched:
        actions.append(Action("search_room", "Search the room for secrets"))
    if not room.rested and player.hp < player.max_hp:
        actions.append(Action("rest", "Rest a while", "risky"))
    return actions


def _fixture_actions(state: GameState) -> list[Action]:
    room, player = state.room, state.player
    if not room.fixture or room.fixture_used or (room.monster and room.monster.hostile):
        return []
    if room.fixture == "stairs":
        return [Action("descend", f"Descend the stairs to floor {state.floor + 1}", "no way back")]
    if room.fixture == "shrine":
        actions = []
        if player.hp > 6:
            actions.append(Action("shrine_blood", "Offer blood at the shrine", "-6 HP, +1 Fate"))
        if player.gold >= 10:
            actions.append(Action("shrine_gold", "Offer 10 gold at the shrine", "full heal"))
        return actions
    if room.fixture == "chest":
        return [Action("chest", "Open the iron-bound chest", "trapped?")]
    if room.fixture == "fountain":
        return [Action("fountain", "Drink from the strange fountain", "roll the dice")]
    return []


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

    took_turn = True
    if verb == "perk":
        return choose_perk(state, content, arg)
    if verb == "attack":
        events = player_attack(state, content, rng)
    elif verb == "dodge":
        events = dodge(state, content, rng)
    elif verb == "go":
        events, took_turn = _move(state, content, arg)
    elif verb == "take":
        state.room.items.remove(arg)
        events = gain_item(state, content, arg)
    elif verb == "search":
        events = _search_feature(state, content, state.room.features[int(arg)])
    elif verb == "search_room":
        events = _search_room(state, rng)
    elif verb == "use":
        events, took_turn = _use(state, content, rng, arg)
    elif verb == "flee":
        events = flee(state, content, rng)
    elif verb == "rest":
        events = _rest(state, content, rng)
    elif verb in ("shrine_blood", "shrine_gold", "chest", "fountain"):
        events = _fixture(state, content, rng, verb)
    elif verb == "descend":
        events = _descend(state, content)
    else:
        return [Event("info", "You can't do that right now.")]
    return finish_turn(state, content, rng, events, took_turn, was_in_combat, room_before)


def perform_creative(state: GameState, content: Content, intent: Intent) -> tuple[Intent, list[Event]]:
    if state.over:
        return intent, []
    rng = _rng(state)
    was_in_combat, room_before = state.in_combat, state.room_id
    intent, events, took_turn = _creative(state, content, intent, rng)
    return intent, finish_turn(state, content, rng, events, took_turn, was_in_combat, room_before)


def perform_flavor(state: GameState, content: Content) -> list[Event]:
    """Harmless free text. Costs nothing outside a fight, but in a fight the monster gets its turn."""
    if not state.in_combat:
        return []
    return finish_turn(state, content, _rng(state), [], True, True, state.room_id)


def finish_turn(state, content, rng, events, took_turn, was_in_combat, room_before) -> list[Event]:
    if took_turn:
        state.turn += 1
        state.reroll = 0
        if was_in_combat and state.room_id == room_before and state.in_combat and not state.over:
            events += monster_turn(state, content, rng)
    if not state.over:
        events += check_traits(state)
    return events


# --- progression -------------------------------------------------------------

def check_level(state: GameState, content: Content) -> list[Event]:
    player = state.player
    events = []
    while player.next_level_xp() is not None and player.xp >= player.next_level_xp():
        player.level += 1
        player.max_hp += 2
        player.hp += 2
        if state.pending_perks:
            state.perk_debt += 1
        else:
            _offer_perks(state, content)
        events.append(Event("level", f"You reach level {player.level}! Choose a perk.", data={"level": player.level}))
    return events


def _offer_perks(state: GameState, content: Content) -> None:
    player = state.player
    rng = dice.stream(state.seed, "perks", player.level, len(player.perks))
    pool = sorted(k for k in content.perks if k not in player.perks)
    state.pending_perks = rng.sample(pool, min(3, len(pool)))


def choose_perk(state: GameState, content: Content, key: str) -> list[Event]:
    state.pending_perks = []
    events = apply_perk(state, content, key)
    if state.perk_debt:
        state.perk_debt -= 1
        _offer_perks(state, content)
    return events


def apply_perk(state: GameState, content: Content, key: str) -> list[Event]:
    player = state.player
    if key in player.perks:
        return []
    player.perks.append(key)
    if key == "tough":
        player.max_hp += 8
        player.hp += 8
    elif key == "brawler":
        player.might += 1
    elif key == "nimble":
        player.agility += 1
    elif key == "sharp_mind":
        player.wits += 1
    elif key == "lucky":
        player.fate = min(player.max_fate(), player.fate + 1)
    elif key == "glass_cannon":
        player.max_hp = max(6, player.max_hp - 6)
        player.hp = min(player.hp, player.max_hp)
    perk = content.perks[key]
    return [Event("perk", f"You take the perk {perk.name}: {perk.desc}", data={"perk": key})]


def check_traits(state: GameState) -> list[Event]:
    player = state.player
    events = []
    for key, (name, counter, threshold, desc) in TRAITS.items():
        if key not in player.traits and player.style.get(counter, 0) >= threshold:
            player.traits.append(key)
            events.append(Event("trait", f"Trait earned: {name}. {desc}", data={"trait": key}))
    return events


# --- moving around -----------------------------------------------------------

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
    return events + travel(state, content, direction, exit_.to), True


def travel(state: GameState, content: Content, direction: str, to: int) -> list[Event]:
    state.prev_room_id, state.room_id = state.room_id, to
    room = state.room
    room.entered_from = OPPOSITE[direction]
    first = not room.visited
    room.visited = True
    arrival = f"You go {direction} into {the(room.name)}" + (" for the first time." if first else ", where you've been before.")
    events = [Event("enter", f"{arrival} {room_facts(state, content)}",
                    data={"first": first, "room": room.id, "monster": room.monster.key if room.monster else ""})]
    if room.monster and room.monster.hostile:
        events += telegraph(state, content)
    return events


def room_facts(state: GameState, content: Content) -> str:
    room = state.room
    lines = []
    features = [f"{f.name} ({layout.where(f.pos)})" for _, f in room.visible_features()]
    if features:
        lines.append("In the room: " + ", ".join(features) + ".")
    if room.items:
        lines.append("On the floor: " + ", ".join(content.item(k).name for k in room.items) + ".")
    if room.fixture and not room.fixture_used:
        lines.append(FIXTURE_FACTS[room.fixture])
    exits = [f"{d} (locked)" if e.locked else d for d, e in room.exits.items()]
    lines.append("Exits: " + ", ".join(exits) + ".")
    monster = room.monster
    if monster:
        if monster.ghost_of and state.ghost:
            ghost = state.ghost
            lines.append(f"The restless ghost of {monster.ghost_of}, the player's previous adventurer, is here and "
                         f"hostile. In life they were {ghost.get('cause', 'killed down here')}. "
                         f"Their epitaph read: \"{ghost.get('epitaph', '')}\"")
        elif monster.hostile:
            elite = " It looks unusually dangerous." if monster.elite else ""
            lines.append(f"{cap(the(monster.name))} is here ({layout.where(room.monster_pos)}) and hostile. "
                         f"A fight begins.{elite}")
        else:
            lines.append(f"{cap(the(monster.name))} is here, but no longer wants to fight.")
    return " ".join(lines)


def _descend(state: GameState, content: Content) -> list[Event]:
    old_theme = content.themes[state.theme].name
    state.floor += 1
    state.souls += 10
    build_floor(state, content)
    theme = content.themes[state.theme]
    room = state.room
    goal = f" Your goal: {theme.goal}" if state.final_floor else ""
    text = (f"You descend from {old_theme} into floor {state.floor}: {theme.name}. {theme.blurb} "
            f"You arrive in {the(room.name)}. {room_facts(state, content)}{goal} +10 souls.")
    return [Event("descend", text, data={"first": True, "room": room.id, "floor": state.floor})]


# --- items and searching -----------------------------------------------------

def gain_item(state: GameState, content: Content, key: str) -> list[Event]:
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
    state.player.bump("searched")
    events = []
    for key in feature.loot:
        events.append(Event("find", f"You search {the(feature.name)} and find the {content.item(key).name}."))
        events += gain_item(state, content, key)
    feature.loot = []
    gold = feature.gold + (3 if feature.gold and "scavenger" in state.player.perks else 0)
    if gold:
        state.player.gold += gold
        events.append(Event("find", f"You search {the(feature.name)} and find {gold} gold."))
        feature.gold = 0
    return events or [Event("search", f"You search {the(feature.name)} but find nothing useful.")]


def _search_room(state: GameState, rng: random.Random) -> list[Event]:
    room, player = state.room, state.player
    room.room_searched = True
    player.bump("searched")
    bonuses = [("wits", player.wits)]
    if "keen_eye" in player.blessings:
        bonuses.append(("Keen Eye", 3))
    if "treasure_nose" in player.traits:
        bonuses.append(("Treasure Nose", 2))
    roll = dice.check(rng, "wits (search)", bonuses, 12)
    hidden = [f for f in room.features if f.hidden]
    events = fortune(state, roll)
    if roll.success and hidden:
        for feature in hidden:
            feature.hidden = False
        names = ", ".join(f.name for f in hidden)
        return [Event("secret", f"Searching carefully, you discover something hidden: {names}.", dice=roll,
                      data={"rerollable": True})] + events
    # Only worth a Fate reroll if there really was something to find.
    return [Event("search_room", "You search every corner but find nothing hidden.", dice=roll,
                  data={"rerollable": bool(hidden)})] + events


def _use(state: GameState, content: Content, rng: random.Random, key: str) -> tuple[list[Event], bool]:
    player, item = state.player, content.item(key)
    if item.escape:
        if not state.in_combat:
            return [Event("info", f"You decide to save the {item.name} for an emergency.")], False
        player.inventory.remove(key)
        return [Event("use", f"You hurl the {item.name} at your feet. Thick smoke fills the room.")] + flee(
            state, content, rng, guaranteed=True), True
    if player.hp >= player.max_hp:
        return [Event("info", f"You're not hurt, so you keep the {item.name}.")], False
    heal = round(item.heal * (1.5 if "alchemist" in player.perks else 1))
    healed = min(heal, player.max_hp - player.hp)
    player.hp += healed
    player.inventory.remove(key)
    verb = HEAL_VERBS.get(key, "Drink").lower()
    return [Event("heal", f"You {verb} the {item.name} and recover {healed} HP ({player.hp}/{player.max_hp}).")], True


def _rest(state: GameState, content: Content, rng: random.Random) -> list[Event]:
    room, player = state.room, state.player
    room.rested = True
    if rng.random() < 0.25:
        max_distance = max(r.distance for r in state.rooms)
        room.monster = monster_for(rng, content, state.theme, tier_for(room.distance, max_distance, state.floor))
        events = [Event("ambush", f"While you rest, {a(room.monster.name)} creeps up on you!",
                        data={"monster": room.monster.key})]
        events += monster_turn(state, content, rng)
        return events
    healed = min(dice.roll("1d6", rng) + player.wits + state.floor, player.max_hp - player.hp)
    player.hp += healed
    return [Event("rest", f"You rest for a while and recover {healed} HP ({player.hp}/{player.max_hp}).")]


def _fixture(state: GameState, content: Content, rng: random.Random, verb: str) -> list[Event]:
    room, player = state.room, state.player
    room.fixture_used = True
    if verb == "shrine_blood":
        player.hp -= 6
        if player.fate < player.max_fate():
            player.fate += 1
            return [Event("shrine", f"You bleed on the shrine. It drinks, and the dark grants you a Fate token "
                                    f"({player.fate}/{player.max_fate()}).")]
        state.souls += 8
        return [Event("shrine", "You bleed on the shrine. Your Fate is already full, so it gives you 8 souls instead.")]
    if verb == "shrine_gold":
        player.gold -= 10
        healed = player.max_hp - player.hp
        player.hp = player.max_hp
        return [Event("shrine", f"The coins vanish into the shrine and warmth floods through you (+{healed} HP).")]
    if verb == "chest":
        roll = dice.check(rng, "agility (disarm)", [("agility", player.agility)], 11 + state.floor)
        events = fortune(state, roll)
        if roll.success:
            events.insert(0, Event("chest", "You ease the lid open and catch the needle trap before it fires.",
                                   dice=roll, data={"rerollable": True}))
        else:
            damage = dice.roll("1d6", rng) + state.floor
            player.hp = max(1, player.hp - damage)
            events.insert(0, Event("chest", f"A poisoned needle jabs your thumb for {damage} damage "
                                            f"({player.hp}/{player.max_hp}).", dice=roll, data={"rerollable": True}))
        key = rng.choice(CHEST_LOOT.get(state.floor, CHEST_LOOT[3]))
        gold = rng.randint(5, 15) * state.floor
        player.gold += gold
        events.append(Event("find", f"Inside: the {content.item(key).name} and {gold} gold."))
        return events + gain_item(state, content, key)
    if verb == "fountain":
        roll = dice.check(rng, "luck (fountain)", [], 15)
        events = fortune(state, roll)
        if roll.kept <= 5:
            damage = dice.roll("1d4+1", rng)
            player.hp = max(1, player.hp - damage)
            text = f"The water is bitter and burns going down (-{damage} HP)."
        elif roll.kept <= 14:
            healed = min(6, player.max_hp - player.hp)
            player.hp += healed
            text = f"The water is cool and clean (+{healed} HP)."
        elif roll.kept <= 19:
            if player.fate < player.max_fate():
                player.fate += 1
            text = f"The water tastes like luck. You gain a Fate token ({player.fate}/{player.max_fate()})."
        else:
            stat = rng.choice(["might", "agility", "wits"])
            setattr(player, stat, player.stat(stat) + 1)
            text = f"The water blazes gold inside you: +1 {stat}, permanently!"
        return [Event("fountain", text, dice=roll, data={"rerollable": roll.kept <= 14})] + events
    return []
