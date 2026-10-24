"""Game rules: which actions are possible right now, and what actually happens when you take one.

Every function here mutates GameState and returns Events: plain-English facts the narrator turns into prose.
The language model never changes state directly.
"""

from __future__ import annotations

import random

from . import dice, layout, loot, npcs, powers
from .combat import (bomb_monster, discover, distract, dodge, flee, flee_direction, fortune, monster_turn,
                     player_attack, telegraph, throw, what_is_left)
from .content import Content, ItemDef
from .creative import perform_creative as _creative
from .events import Action, Event
from .intent import Intent
from .models import DELTA, DIRECTIONS, OPPOSITE, Exit, Feature, GameState, MonsterState, Room
from .text import a, cap, the
from .world import build_floor, monster_for, tier_for

PICKUPS = {"bomb": "bombs", "small_key": "keys"}  # picked up, they go on a counter rather than in your pack
ASK_DC = 12  # getting a calm creature to tell you what it knows (wits)
BARTER_DC = 12  # talking a shopkeeper down (wits): a third off; fail, and it's a quarter dearer (once a ware)
BARTER_DOWN, BARTER_UP = 2 / 3, 1.25
TIP = "a tip!"  # the hint on a choice that something you were told about is here

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



def heal_verb(item: ItemDef) -> str:
    """Food is eaten; anything else that heals is drunk."""
    return "Eat" if "food" in item.tags else "Drink"


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
            if item.escape or player.hp < player.max_hp or "dazzle" in item.powers:
                verb = "Throw" if item.escape else heal_verb(item)
                hints = [how_many(player, item.key), "it glows!" if "dazzle" in item.powers else ""]
                actions.append(Action(f"use:{item.key}", f"{verb} {the(item.name)}", " · ".join(filter(None, hints))))
        for item in (content.item(k) for k in _distinct(player.inventory)):
            if "throw" in item.powers:
                actions.append(Action(f"throw:{item.key}", f"Throw {the(item.name)} at {the(monster.name)}",
                                      how_many(player, item.key)))
            if "distract" in item.powers and not monster.distracted:
                actions.append(Action(f"distract:{item.key}", f"Distract {the(monster.name)} with {the(item.name)}",
                                      "once a fight"))
        if player.bombs:
            actions.append(Action("bomb", f"Throw a bomb at {the(monster.name)}", f"{player.bombs} left"))
        actions += npcs.actions(state, content)  # an angry Swoogy can still be calmed down
        if flee_direction(state) and not player.tangled:
            actions.append(Action("flee", "Try to flee"))
        return actions

    if len(room.items) == 1:  # picking up is free: one choice for the lot (or click each one's card in the story)
        actions.append(Action(f"take:{room.items[0]}", f"Pick up {the(content.item(room.items[0]).name)}", "no turn"))
    elif room.items:
        actions.append(Action("take_all", f"Pick up everything here ({len(room.items)})", "no turn"))
    for index, feature in room.visible_features():
        if not feature.searched:
            actions.append(Action(f"search:{index}", f"Search {the(feature.name)}", TIP if feature.told else ""))
    actions += _fixture_actions(state, content)
    if room.monster:
        monster = room.monster
        actions += npcs.actions(state, content)  # Lucky Lenny's tooth, Swoogy's game
        if not monster.asked:
            talks = content.monster(monster.key).intelligent
            knows = "they know" if content.monster(monster.key).named else "it knows"
            actions.append(Action("ask", f"Ask {the(monster.name)} what {knows}" if talks
                                  else f"Watch {the(monster.name)} for a while", "wits"))
        actions.append(Action("attack", f"Attack {the(monster.name)}", "it's calm"))
    theme = content.themes[state.theme]
    for direction in DIRECTIONS:
        exit_ = room.exits.get(direction)
        if not exit_:
            continue
        dest = state.rooms[exit_.to]
        if exit_.locked and exit_.key == "small_key":  # a shop's door
            keys = f"{player.keys} key{'s' if player.keys > 1 else ''}"
            actions.append(Action(f"go:{direction}", f"Unlock the shop door {direction}" if player.keys
                                  else f"Go {direction}", f"shop · {keys}" if player.keys else "a locked shop"))
            if player.bombs:
                bombs = f"{player.bombs} bomb{'s' if player.bombs > 1 else ''}"
                actions.append(Action(f"bomb:{direction}", f"Bomb the shop door {direction}",
                                      f"cracked! · {bombs}" if exit_.cracked else f"two bombs break it · {bombs}"))
            continue
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
                actions.append(Action(f"use:{item.key}", f"{heal_verb(item)} {the(item.name)}",
                                      how_many(player, item.key)))
    if not room.room_searched and not room.shop:  # (her shop is hers: nothing hidden for you to find)
        actions.append(Action("search_room", "Search the room for secrets"))
        for item in (content.item(k) for k in _distinct(player.inventory)):
            if "reveal" in item.powers:
                actions.append(Action(f"reveal:{item.key}", f"Light up the room with {the(item.name)}",
                                      " · ".join(filter(None, [how_many(player, item.key), "shows what's hidden"]))))
    if player.bombs and not room.shop:  # not in her shop, you don't
        told = hidden_room_beside(state) if any(r.secret and r.told for r in state.rooms) else None
        for direction in bombable_walls(state):
            count = f"{player.bombs} bomb{'s' if player.bombs > 1 else ''}"
            sign = TIP if direction == told else ("a draft!" if room.draft == direction else "")
            actions.append(Action(f"bomb:{direction}", f"Bomb the {direction} wall",
                                  f"{sign} · {count}" if sign else count))
    if not room.rested and player.hp < player.max_hp:
        actions.append(Action("rest", "Rest a while", "risky"))
    return actions


def how_many(player, key: str) -> str:
    """A choice's hint when you carry more than one of what it uses up: "×2"."""
    count = player.inventory.count(key)
    return f"×{count}" if count > 1 else ""


def bombable_walls(state: GameState) -> list[str]:
    """The walls worth a bomb here: no door, and beyond them a gap in the floor's map that touches two rooms or more.
    That's the only kind of place a floor's secret room is ever built, so a careful player can work out where it is.
    There's one a floor: once it's open, no wall is worth a bomb."""
    if any(r.secret and r.exits for r in state.rooms):
        return []
    room = state.room
    taken = {(r.x, r.y) for r in state.rooms if not r.secret or r.exits}  # a sealed secret room still looks a gap
    rooms = {(r.x, r.y) for r in state.rooms if not r.secret and not r.shop}  # (a shop isn't one it's built against)
    walls = []
    for direction in DIRECTIONS:
        dx, dy = DELTA[direction]
        cell = (room.x + dx, room.y + dy)
        if direction not in room.exits and cell not in taken and \
                sum((cell[0] + ex, cell[1] + ey) in rooms for ex, ey in DELTA.values()) >= 2:
            walls.append(direction)
    return walls


def hidden_room_beside(state: GameState) -> str | None:
    """The direction of a sealed secret room on the other side of one of this room's walls, if there is one."""
    room = state.room
    for direction in bombable_walls(state):
        dx, dy = DELTA[direction]
        if any(r.secret and not r.exits and (r.x, r.y) == (room.x + dx, room.y + dy) for r in state.rooms):
            return direction
    return None


def _fixture_actions(state: GameState, content: Content) -> list[Action]:
    room, player = state.room, state.player
    if not room.fixture or room.fixture_used or (room.monster and room.monster.hostile):
        return []
    if room.fixture == "shop" and room.shop:
        keeper = content.monster(room.shop.keeper).name
        return [Action("shop", f"Browse {keeper}'s wares", f"¤ {player.gold} gold" if room.shop.wares else "sold out")]
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
        actions = []
        if player.keys:
            actions.append(Action("chest_key", "Unlock the chest with a small key",
                                  f"{player.keys} key{'s' if player.keys > 1 else ''}"))
        actions.append(Action("chest", "Pick the chest's lock", "agility · trapped?"))
        actions.append(Action("chest_smash", "Smash the chest open", "might · it may break"))
        return actions
    if room.fixture == "fountain":
        return [Action("fountain", "Drink from the strange fountain", "roll the dice")]
    return []


# --- resolving actions -----------------------------------------------------

def perform(state: GameState, content: Content, action_id: str) -> list[Event]:
    """Resolve one engine action. Unknown or impossible actions return an info event and cost nothing."""
    if state.over:
        return []
    if action_id not in {a.id for a in available_actions(state, content)} and \
            not off_the_list(state, content, action_id):
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
    elif verb == "take":  # free, and no narrator for it: picking up is bookkeeping
        state.room.items.remove(arg)
        events, took_turn = quietly(gain_item(state, content, arg)), False
    elif verb == "take_all":
        events, took_turn = quietly(_take_all(state, content)), False
    elif verb == "search":
        events = _search_feature(state, content, state.room.features[int(arg)])
    elif verb == "search_room":
        events = _search_room(state, content, rng)
    elif verb == "use":
        events, took_turn = _use(state, content, rng, arg)
    elif verb == "bomb":
        events = _bomb_wall(state, content, arg) if arg else bomb_monster(state, content, rng)
    elif verb == "throw":
        events = throw(state, content, rng, arg)
    elif verb == "distract":
        events = distract(state, content, arg)
    elif verb == "reveal":
        events = _reveal(state, content, arg)
    elif verb == "flee":
        events = flee(state, content, rng)
    elif verb == "rest":
        events = _rest(state, content, rng)
    elif verb == "ask":
        events = _ask(state, content, rng)
    elif verb == "shop":
        keeper = content.monster(state.room.shop.keeper).name
        events, took_turn = [Event("shop", f"{keeper} spreads her wares across the counter.", data={"quiet": True})], False
    elif verb == "buy":
        events, took_turn = _buy(state, content, int(arg)), False
    elif verb == "barter":
        events = _barter(state, content, rng, int(arg))
    elif verb in ("shrine_blood", "shrine_gold", "chest", "chest_key", "chest_smash", "fountain"):
        events = _fixture(state, content, rng, verb)
    elif verb == "descend":
        events = _descend(state, content)
    elif verb in ("lenny", "swoogy", "guess", "appease"):
        events = npcs.perform(state, content, rng, verb, arg)
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
        # what a monster dropped and you pocket at once is told with its drop, not after a level-up (run 44)
        after_drops = max((i + 1 for i, e in enumerate(events) if e.kind == "drop"), default=len(events))
        events[after_drops:after_drops] = collect(state, content)
    powers.settle_stats(state, content)  # what you carry now, in your stats
    return events


def quietly(events: list[Event]) -> list[Event]:
    """Events that need no narrator: they're shown as they are (see Game.finish)."""
    for event in events:
        event.data["quiet"] = True
    return events


def collect(state: GameState, content: Content) -> list[Event]:
    """Bombs and small keys lying where you are go straight on their counters, Isaac-style, once there's no fight:
    there's nothing to choose about them."""
    room = state.room
    if state.in_combat or not any(key in PICKUPS for key in room.items):
        return []
    events = []
    for key in [k for k in room.items if k in PICKUPS]:
        room.items.remove(key)
        events += gain_item(state, content, key)
    return quietly(events)


def things_here(state: GameState, content: Content) -> list[Action]:
    """Taking any one thing lying here: not numbered choices (click its card, or say so), but the interpreter's to
    match, as in "grab the potion"."""
    if state.in_combat or len(state.room.items) < 2:
        return []
    return [Action(f"take:{key}", f"Pick up {the(content.item(key).name)}") for key in _distinct(state.room.items)]


def _take_all(state: GameState, content: Content) -> list[Event]:
    events = []
    for key in list(state.room.items):  # (not what you leave behind as you take something better)
        state.room.items.remove(key)
        events += gain_item(state, content, key)
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
    if exit_.locked and exit_.key == "small_key":
        if not state.player.keys:
            return [Event("locked", f"The shop door to the {direction} is locked. A small key would open it, or two "
                                    "bombs would break it.")], False
        state.player.keys -= 1
        exit_.locked = False
        events.append(Event("unlock", f"You unlock the shop door with a small key ({state.player.keys} left)."))
    elif exit_.locked:
        key = content.item(content.themes[state.theme].key_item)
        if key.key not in state.player.inventory:
            return [Event("locked", f"The door to the {direction} is locked. It looks like it needs {the(key.name)}.")], False
        exit_.locked = False
        events.append(Event("unlock", f"You unlock the door to the {direction} with {the(key.name)}."))
    return events + travel(state, content, direction, exit_.to), True


def travel(state: GameState, content: Content, direction: str, to: int) -> list[Event]:
    state.prev_room_id, state.room_id = state.room_id, to
    room = state.room
    room.entered_from = OPPOSITE[direction]
    first = not room.visited
    room.visited = True
    arrival = f"You go {direction} into {the(room.name)}" + (" for the first time." if first else ", where you've been before.")
    journal = f"You went {direction} into {the(room.name)}" + (" for the first time." if first else ".")
    events = [Event("enter", f"{arrival} {room_facts(state, content)}",
                    data={"first": first, "room": room.id,  # whoever's here goes in the bestiary, a shopkeeper too
                          "monster": room.monster.key if room.monster else (room.shop.keeper if room.shop else ""),
                          "journal": journal, "direction": direction})]
    if room.monster and room.monster.hostile:
        events += telegraph(state, content)
    return events


def exit_notes(state: GameState) -> str:
    """Each exit with what the player knows lies beyond it: "east (the Ossuary, where you came from)"."""
    room = state.room
    notes = []
    for direction, exit_ in room.exits.items():
        dest = state.rooms[exit_.to]
        if exit_.locked:
            beyond = "locked; a shop beyond" if dest.shop else "locked"
        elif dest.visited:
            beyond = the(dest.name) + (", where you came from" if exit_.to == state.prev_room_id else "")
        elif dest.fixture and not dest.fixture_used:
            beyond = "unexplored; " + {"stairs": "the stairs down"}.get(dest.fixture, a(dest.fixture)) + " beyond"
        else:
            beyond = "unexplored"
        notes.append(f"{direction} ({beyond})")
    return ", ".join(notes)


def room_facts(state: GameState, content: Content) -> str:
    room = state.room
    lines = ["A secret room, walled off until a bomb opened it."] if room.secret else []
    features = [_feature_note(f) for _, f in room.visible_features()]
    if features:
        lines.append("In the room: " + ", ".join(features) + ".")
    beside = hidden_room_beside(state)
    told = next((r.told for r in state.rooms if r.secret and r.told and not r.exits), "")
    if beside and told:
        lines.append(f"Behind the {beside} wall is the hidden room {the(told)} told you about.")
    if room.items:
        lines.append("On the floor: " + ", ".join(content.item(k).name for k in room.items) + ".")
    if room.shop:
        lines.append(shop_facts(room.shop, content))
    elif room.fixture and not room.fixture_used:
        lines.append(FIXTURE_FACTS[room.fixture])
    lines.append(f"Exits: {exit_notes(state)}.")
    monster = room.monster
    if monster:
        if monster.ghost_of and state.ghost:
            ghost = state.ghost
            lines.append(f"The restless ghost of {monster.ghost_of} is here and hostile. {ghost_truth(monster)} "
                         f"In that life they were {ghost.get('cause', 'killed down here')}. "
                         f"Their epitaph read: \"{ghost.get('epitaph', '')}\"")
        elif monster.hostile:
            elite = " It looks unusually dangerous." if monster.elite else ""
            lines.append(f"{cap(the(monster.name))} is here ({layout.where(room.monster_pos)}) and hostile. "
                         f"A fight begins.{elite}")
        elif content.monster(monster.key).npc:
            lines.append(f"{cap(the(monster.name))} is here ({layout.where(room.monster_pos)}).")
        else:
            lines.append(f"{cap(the(monster.name))} is here, but no longer wants to fight.")
        told = npcs.facts(state, content)
        if told:
            lines.append(told)
        if state.player.tangled:
            lines.append(f"Your legs are tangled in {the(monster.name)}'s vines: you can't run this turn.")
    if room.history:
        lines.append("Earlier here: " + "; ".join(room.history) + ".")
    return " ".join(lines)


def ghost_truth(monster: MonsterState) -> str:
    """Who a ghost really is, for the narrator and the interpreter: without it, a player telling their own ghost "it's
    me" was narrated as a con."""
    return (f"It's your own ghost: {monster.ghost_of} was the adventurer you played before, in a life that ended on "
            "this floor. Anything you say about having been them, or knowing them, is true.")


def _feature_note(feature: Feature) -> str:
    notes = [layout.where(feature.pos)]
    if feature.used:
        notes.append(f"already used: {feature.used}")
    if feature.told and not feature.searched:
        notes.append(f"{the(feature.told)} said something's hidden here")
    return f"{feature.name} ({'; '.join(notes)})"


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
    journal = f"You went down to floor {state.floor}, {theme.name}, arriving in {the(room.name)}."
    events = [Event("descend", text, data={"first": True, "room": room.id, "floor": state.floor, "journal": journal})]
    player = state.player
    for item in powers.holders(state, content, "cursed"):
        player.max_hp = max(10, player.max_hp - 2)
        player.hp = min(player.hp, player.max_hp)
        events.append(Event("curse", f"{cap(the(item.name))} grows heavier on the stairs. Your most HP falls to "
                                     f"{player.max_hp}."))
    for item in powers.holders(state, content, "prophecy"):
        if player.fate < player.max_fate():
            player.fate += 1
            events.append(Event("fate", f"{cap(the(item.name))} saw this coming: you gain a Fate token "
                                        f"({player.fate}/{player.max_fate()})."))
    return events


# --- items and searching -----------------------------------------------------

def gain_item(state: GameState, content: Content, key: str) -> list[Event]:
    player, item = state.player, content.item(key)
    if key in PICKUPS:
        count = getattr(player, PICKUPS[key]) + 1
        setattr(player, PICKUPS[key], count)
        return [Event("take", f"You take {the(item.name)} ({count} now).", data={"item": key})]
    if "mapper" in item.powers and state.mapped_floor != state.floor:
        state.mapped_floor = state.floor
        player.inventory.append(key)
        return [Event("take", f"You take {the(item.name)}.", data={"item": key}),
                Event("map", f"Somehow {the(item.name)} puts the whole floor in your head: every room is on your "
                             "map now.")]
    if item.kind == "weapon":
        current = content.item(player.weapon)
        if item.tier > current.tier:
            player.weapon = key
            state.room.items.append(current.key)  # it's on the floor, where you tossed it
            state.room.remember(f"you left your old {current.name} here")  # so it isn't anyone else's
            return [Event("equip", f"You take {the(item.name)} ({item.damage}) and toss aside your {current.name}.",
                          data={"item": key, "left": current.key})]
    if item.kind == "armor":
        current = content.item(player.armor) if player.armor else None
        if current is None or item.tier > current.tier:
            player.armor = key
            if current:
                state.room.items.append(current.key)
                state.room.remember(f"you left your old {current.name} here")
            swap = f" and leave your {current.name} behind" if current else ""
            left = {"left": current.key} if current else {}
            return [Event("equip", f"You put on {the(item.name)} (+{item.defense} defense){swap}.",
                          data={"item": key, **left})]
    player.inventory.append(key)
    if item.kind == "key":
        return [Event("key", f"You take {the(item.name)}. It must open something important.", data={"item": key})]
    return [Event("take", f"You take {the(item.name)}.", data={"item": key})]


def _search_feature(state: GameState, content: Content, feature: Feature) -> list[Event]:
    feature.searched = True
    state.player.bump("searched")
    events = []
    for key in feature.loot:
        events.append(Event("find", f"You search {the(feature.name)} and find {the(content.item(key).name)}.",
                            data={"item": key}))
        events += gain_item(state, content, key)
    feature.loot = []
    gold = feature.gold + (3 if feature.gold and "scavenger" in state.player.perks else 0)
    if gold:
        state.player.gold += gold
        events.append(Event("find", f"You search {the(feature.name)} and find {gold} gold."))
        feature.gold = 0
    return events or [Event("search", f"You search {the(feature.name)} but find nothing useful.")]


def _search_room(state: GameState, content: Content, rng: random.Random) -> list[Event]:
    room, player = state.room, state.player
    room.room_searched = True
    player.bump("searched")
    bonuses = [("wits", player.wits)]
    if "keen_eye" in player.blessings:
        bonuses.append(("Keen Eye", 3))
    if "treasure_nose" in player.traits:
        bonuses.append(("Treasure Nose", 2))
    roll = dice.check(rng, "wits (search)", bonuses + powers.roll_bonuses(state, content, "search"), 12)
    hidden = [f for f in room.features if f.hidden]
    beside = hidden_room_beside(state)
    events = fortune(state, roll)
    if roll.success and (hidden or beside):
        found = []
        if hidden:
            for feature in hidden:
                feature.hidden = False
            found.append(Event("secret", "Searching carefully, you discover something hidden: "
                                         f"{', '.join(f.name for f in hidden)}.", dice=roll, data={"rerollable": True}))
        if beside:
            found.append(_draft(state, beside, None if hidden else roll))
        return found + events
    # Only worth a Fate reroll if there really was something to find.
    return [Event("search_room", "You search every corner but find nothing hidden.", dice=roll,
                  data={"rerollable": bool(hidden or beside)})] + events


def _draft(state: GameState, direction: str, roll: dice.Roll | None = None) -> Event:
    """The sign of a secret room next door, for anyone who looks hard enough."""
    state.room.draft = direction
    return Event("secret", f"A faint draft whistles through a crack in the {direction} wall. There's space behind it.",
                 dice=roll, data={"rerollable": True} if roll else {})


# --- what a calm creature knows ------------------------------------------------

def _ask(state: GameState, content: Content, rng: random.Random) -> list[Event]:
    """Ask a creature that's stopped fighting what it knows, or watch where it goes if it can't talk: a wits roll, once
    each. It knows its floor: where the secret room is, or what's hidden where, and that goes on your map. Failing
    those, one that talks knows what one of the floor's monsters can't stand."""
    monster, player = state.room.monster, state.player
    monster.asked = True
    talks = content.monster(monster.key).intelligent
    tooth = npcs.tooth_spot(state) if monster.key == npcs.LENNY and monster.mood == "tooth" else None
    hidden = [tooth] if tooth else _hidden_things(state)  # Lenny knows where his tooth went
    weak = _weak_spots(state, content) if talks else []
    if not (hidden or weak):  # nothing it could tell you, so nothing to roll for
        return [Event("ask", f"{cap(the(monster.name))} doesn't know anything about this floor that you don't." if talks
                      else f"You watch {the(monster.name)} for a while. It doesn't lead you anywhere new.")]
    bonuses = [("wits", player.wits)] + powers.roll_bonuses(state, content, "ask")
    roll = dice.check(rng, "wits (ask)" if talks else "wits (watch it)", bonuses, ASK_DC,
                      advantage=int(talks and "silver_tongue" in player.traits))
    events = fortune(state, roll)
    if not roll.success:
        return [Event("ask", f"{cap(the(monster.name))} hums and haws, and tells you nothing you can use." if talks
                      else f"You watch {the(monster.name)} for a while, but it never goes anywhere that matters.",
                      dice=roll, data={"rerollable": True})] + events
    if hidden:
        room, feature = rng.choice(hidden)
        told = (_tell_feature(state, content, monster, talks, room, feature) if feature
                else _tell_room(state, monster, talks, room))
    else:
        room, target, tag = weak[0]
        where = ("behind the locked door" if room.is_boss else "by the stairs" if room.fixture == "stairs"
                 else _place(state, room))
        told = [Event("tip", f"{cap(the(monster.name))} tells you a thing or two about {the(target.name)} "
                             f"{where}.")] + discover(state, target, tag)
    told[0].dice, told[0].data["rerollable"] = roll, True
    return told + events


def _hidden_things(state: GameState) -> list[tuple[Room, Feature | None]]:
    """What's still hidden on this floor that nobody's told you about: the sealed secret room (unless you've felt its
    draft already), and anything tucked away in a room (every floor hides a stash)."""
    things: list[tuple[Room, Feature | None]] = [
        (r, None) for r in state.rooms
        if r.secret and not r.exits and not r.told and not any(other.draft for other in state.rooms)]
    things += [(r, f) for r in state.rooms for f in r.features if f.hidden and not f.told and (f.loot or f.gold)]
    return things


def _weak_spots(state: GameState, content: Content) -> list[tuple[Room, MonsterState, str]]:
    """What this floor's monsters can't stand that you haven't found out yet: the boss's first, then the warden's by
    the stairs."""
    spots = []
    for room in sorted(state.rooms, key=lambda r: (not r.is_boss, r.fixture != "stairs", r.id)):
        monster = room.monster
        if monster and monster.hostile and room.id != state.room_id:
            known = state.known_weak.get(monster.key, [])
            spots += [(room, monster, tag) for tag in content.monster(monster.key).weak if tag not in known]
    return spots


def _place(state: GameState, room: Room, preposition: str = "in") -> str:
    """Where a room is, in words you'd know it by: "here", "in the Mossy Archive", "in a room you haven't found yet"."""
    if room.id == state.room_id:
        return "here"
    return f"{preposition} {the(room.name)}" if room.visited else f"{preposition} a room you haven't found yet"


def _tell_room(state: GameState, monster: MonsterState, talks: bool, room: Room) -> list[Event]:
    """Where the floor's secret room is: it goes on your map, and the wall to bomb says so."""
    room.told = monster.name
    near = [r for r in state.rooms if not r.secret and abs(r.x - room.x) + abs(r.y - room.y) == 1]
    beside = min(near, key=lambda r: (r.id != state.room_id, not r.visited, r.id))
    direction = next(d for d, (dx, dy) in DELTA.items() if (beside.x + dx, beside.y + dy) == (room.x, room.y))
    wall = f"this room's {direction} wall" if beside.id == state.room_id else \
        f"the {direction} wall {_place(state, beside, 'of')}"
    if talks:
        text = f"{cap(the(monster.name))} tells you there's a hidden room behind {wall}."
    else:
        text = (f"You watch {the(monster.name)} for a while. It keeps going back to {wall} and scratching at it, as "
                "if something's behind it.")
    return [Event("tip", f"{text} It's on your map now.", data={"room": room.id})]


def _tell_feature(state: GameState, content: Content, monster: MonsterState, talks: bool, room: Room,
                  feature: Feature) -> list[Event]:
    """Where something's hidden (a floor's stash): you can see it now, and search it when you get there."""
    feature.told, feature.hidden = monster.name, False
    here = room.id == state.room_id
    if talks:
        thing = a(content.item(feature.loot[0]).name) if feature.loot else "a stash of gold"
        text = (f"{cap(the(monster.name))} lets slip that {thing} is hidden {_place(state, room)}: look for "
                f"{feature.name}.")
    elif here:
        text = (f"You watch {the(monster.name)} for a while. It keeps nosing at {feature.name}: something's hidden "
                "there.")
    else:
        text = (f"You watch {the(monster.name)} for a while. It keeps wandering off {_place(state, room, 'to')} to "
                f"nose at {feature.name}: something's hidden there.")
    return [Event("tip", text + ("" if here else " It's on your map now."), data={"room": room.id})]


def _reveal(state: GameState, content: Content, key: str) -> list[Event]:
    """Light the room with something bright (a reveal power): it's used up, and nothing here stays hidden."""
    room, item = state.room, content.item(key)
    state.player.inventory.remove(key)
    room.room_searched = True
    events = [Event("use", f"You light up the room with {the(item.name)}. It's spent, but every corner is bright."
                           f"{what_is_left(state.player, key)}")]
    hidden = [f for f in room.features if f.hidden]
    for feature in hidden:
        feature.hidden = False
    if hidden:
        events.append(Event("secret", f"The light shows something hidden: {', '.join(f.name for f in hidden)}."))
    beside = hidden_room_beside(state)
    if beside:
        events.append(_draft(state, beside))
    if not hidden and not beside:
        events.append(Event("search_room", "Nothing here was hiding after all."))
    return events


def _bomb_wall(state: GameState, content: Content, direction: str) -> list[Event]:
    """Blow a hole in a wall. If the floor's secret room is behind it, there's a doorway now."""
    room, player = state.room, state.player
    door = room.exits.get(direction)
    if door and door.locked and door.key == "small_key":
        return _bomb_door(state, door, direction)
    player.bombs -= 1
    dx, dy = DELTA[direction]
    secret = next((r for r in state.rooms if r.secret and not r.exits and (r.x, r.y) == (room.x + dx, room.y + dy)),
                  None)
    if secret is None:
        return [Event("bomb", f"The bomb goes off against the {direction} wall. Dust rains down, but the wall holds: "
                              f"there's only earth behind it. ({player.bombs} bomb{'s' if player.bombs != 1 else ''} "
                              "left.)")]
    room.exits[direction] = Exit(to=secret.id)
    secret.exits[OPPOSITE[direction]] = Exit(to=room.id)
    room.remember(f"you blew open the {direction} wall")
    return [Event("secret_room", f"The bomb blows the {direction} wall apart. Behind it is a hidden room, sealed off "
                                 "until now!", data={"room": secret.id})]


def _bomb_door(state: GameState, door: Exit, direction: str) -> list[Event]:
    """A shop's door is sturdier than a wall: the first bomb cracks it, the second breaks it."""
    player = state.player
    player.bombs -= 1
    left = f"({player.bombs} bomb{'s' if player.bombs != 1 else ''} left.)"
    if not door.cracked:
        door.cracked = True
        return [Event("bomb", f"The bomb goes off against the shop door to the {direction}. It's cracked, but it "
                              f"holds: another would break it. {left}")]
    door.locked = False
    state.room.remember(f"you blew in the shop door to the {direction}")
    return [Event("bomb", f"The second bomb blows the shop door to the {direction} off its hinges. {left}")]


# --- shops --------------------------------------------------------------------

def shop_facts(shop, content: Content) -> str:
    """A shop as the narrator knows it: who keeps it, and what's on her counter at what price."""
    keeper = content.monster(shop.keeper)
    wares = ", ".join(f"{content.item(w.item).name} ({w.price} gold)" for w in shop.wares) or "nothing: sold out"
    return (f"{keeper.name} keeps a shop here, behind a counter: a shopkeeper, not a monster, and she won't fight "
            f"unless crossed. About her: {keeper.desc} On her counter: {wares}.")


def off_the_list(state: GameState, content: Content, action_id: str) -> bool:
    """What may be done now that isn't one of the numbered choices: picking up any one thing lying here (by its card
    in the story, or by saying so), buying or haggling at a shop's counter (its own screen does those), and handing an
    angry Swoogy anything you carry."""
    verb, _, arg = action_id.partition(":")
    if verb == "take":
        return arg in state.room.items and not state.in_combat
    if verb == "appease":  # anything of yours, to calm Swoogy down
        return action_id in {a.id for a in npcs.unlisted(state, content)}
    shop = state.room.shop
    return verb in ("buy", "barter") and shop is not None and not state.in_combat and arg.isdigit() \
        and int(arg) < len(shop.wares)


def _buy(state: GameState, content: Content, index: int) -> list[Event]:
    shop, player = state.room.shop, state.player
    ware = shop.wares[index]
    item = content.item(ware.item)
    if player.gold < ware.price:
        return [Event("info", f"{cap(the(item.name))} is {ware.price} gold, and you have {player.gold}.",
                      data={"quiet": True})]
    player.gold -= ware.price
    shop.wares.pop(index)
    events = [Event("buy", f"You buy {the(item.name)} for {ware.price} gold ({player.gold} left).",
                    data={"item": ware.item, "quiet": True})]
    for gained in gain_item(state, content, ware.item):
        gained.data["quiet"] = True
        events.append(gained)
    return events


def _barter(state: GameState, content: Content, rng: random.Random, index: int) -> list[Event]:
    """Haggle over a ware (wits, once each): talk her down a third, or put it up a quarter, like a shopkeeper in
    Kid Icarus."""
    shop, player = state.room.shop, state.player
    ware = shop.wares[index]
    item, keeper = content.item(ware.item), content.monster(shop.keeper).name
    if ware.haggled:
        return [Event("info", f"{keeper} won't haggle over {the(item.name)} again.")]
    bonuses = [("wits", player.wits)] + powers.roll_bonuses(state, content, "barter")
    roll = dice.check(rng, "wits (barter)", bonuses, BARTER_DC, advantage=int("silver_tongue" in player.traits))
    was = ware.price
    if roll.success:
        ware.price, ware.haggled = max(1, round(was * BARTER_DOWN)), "down"
        text = f"{keeper} grumbles, and lets {the(item.name)} go for {ware.price} gold instead of {was}."
    else:
        ware.price, ware.haggled = round(was * BARTER_UP), "up"
        text = f"{keeper} takes offence: {the(item.name)} is {ware.price} gold now, not {was}."
    return [Event("barter", text, dice=roll, data={"rerollable": True, "item": ware.item})] + fortune(state, roll)


def _use(state: GameState, content: Content, rng: random.Random, key: str) -> tuple[list[Event], bool]:
    player, item = state.player, content.item(key)
    if item.escape:
        if not state.in_combat:
            return [Event("info", f"You decide to save {the(item.name)} for an emergency.")], False
        player.inventory.remove(key)
        return [Event("use", f"You hurl {the(item.name)} at your feet. Thick smoke fills the room."
                             f"{what_is_left(player, key)}")] + flee(
            state, content, rng, guaranteed=True), True
    glows = "dazzle" in item.powers and state.in_combat
    if player.hp >= player.max_hp and not glows:
        return [Event("info", f"You're not hurt, so you keep {the(item.name)}.")], False
    heal = round(item.heal * (1.5 if "alchemist" in player.perks else 1))
    healed = min(heal, player.max_hp - player.hp)
    player.hp += healed
    player.inventory.remove(key)
    verb = heal_verb(item).lower()
    events = [Event("heal", f"You {verb} {the(item.name)} and recover {healed} HP ({player.hp}/{player.max_hp})."
                            f"{what_is_left(player, key)}")]
    return events + (_dazzle(state, content) if glows else []), True


def _dazzle(state: GameState, content: Content) -> list[Event]:
    """Glowing like a lantern (a dazzle power): the monster flees the room, no reward for it. A boss, or a guardian at
    the stairs, stands its ground."""
    monster = state.room.monster
    monster_def = content.monster(monster.key)
    if monster_def.boss or "guardian" in monster_def.tags or state.room.fixture == "stairs" or monster.ghost_of:
        return [Event("dazzle", f"You glow like a lantern, but {the(monster.name)} only squints at you and stands its "
                                "ground.")]
    state.room.monster = None
    state.room.remember(f"your glow sent {the(monster.name)} running")
    return [Event("dazzle", f"You glow like a lantern! {cap(the(monster.name))} shrieks and flees the room in terror.")]


def _open_chest(state: GameState, content: Content, rng: random.Random, how: str) -> list[Event]:
    """A chest three ways: a small key opens it safely; picking the lock (agility) risks the needle trap; smashing it
    (might) skips the trap, but a blow that goes wrong breaks whatever's inside."""
    player = state.player
    broken = False
    if how == "chest_key":
        player.keys -= 1
        events = [Event("chest", "The small key turns, and the lid lifts without a fight "
                                 f"({player.keys} key{'s' if player.keys != 1 else ''} left).")]
    elif how == "chest":
        bonuses = [("agility", player.agility)] + powers.roll_bonuses(state, content, "disarm")
        roll = dice.check(rng, "agility (pick the lock)", bonuses, 11 + state.floor)
        events = fortune(state, roll)
        if roll.success:
            events.insert(0, Event("chest", "You pick the lock and catch the needle trap before it fires.",
                                   dice=roll, data={"rerollable": True}))
        else:
            damage = dice.roll("1d6", rng) + state.floor
            player.hp = max(1, player.hp - damage)
            events.insert(0, Event("chest", f"A poisoned needle jabs your thumb for {damage} damage "
                                            f"({player.hp}/{player.max_hp}).", dice=roll, data={"rerollable": True}))
    else:
        bonuses = [("might", player.might)] + powers.roll_bonuses(state, content, "smash")
        roll = dice.check(rng, "might (smash it)", bonuses, 10 + state.floor)
        events = fortune(state, roll)
        broken = not roll.success
        text = ("You bring your weight down on the lid and the chest splinters open, trap and all." if roll.success
                else "The chest bursts open under your blows, and something inside cracks.")
        events.insert(0, Event("chest", text, dice=roll, data={"rerollable": True}))
    key = loot.produce(rng, content, state.rares, loot.CHESTS.get(state.floor, loot.CHESTS[3]), "chest")
    gold = rng.randint(5, 15) * state.floor
    player.gold += gold
    if key is None:
        return events + [Event("find", f"Inside: {gold} gold.")]
    name = content.item(key).name
    if broken:
        return events + [Event("find", f"Inside: {gold} gold, and what's left of {the(name)}, smashed beyond use.")]
    events.append(Event("find", f"Inside: {the(name)} and {gold} gold.", data={"item": key}))
    return events + gain_item(state, content, key)


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
    cook = powers.holders(state, content, "cook")
    healed = min(dice.roll("1d6", rng) + player.wits + state.floor + 4 * bool(cook), player.max_hp - player.hp)
    player.hp += healed
    meal = f" A hot meal cooked in your {cook[0].name} helps." if cook else ""
    return [Event("rest", f"You rest for a while and recover {healed} HP ({player.hp}/{player.max_hp}).{meal}")]


def _fixture(state: GameState, content: Content, rng: random.Random, verb: str) -> list[Event]:
    room, player = state.room, state.player
    room.fixture_used = True
    room.remember({"shrine_blood": "you bled on the shrine", "shrine_gold": "you gave gold to the shrine",
                   "chest": "you picked the chest's lock", "chest_key": "you unlocked the chest with a key",
                   "chest_smash": "you smashed the chest open",
                   "fountain": "you drank from the fountain"}.get(verb, verb))
    if verb in ("chest", "chest_key", "chest_smash"):
        return _open_chest(state, content, rng, verb)
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
