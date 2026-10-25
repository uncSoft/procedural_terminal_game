"""Game rules: which actions are possible right now, and what actually happens when you take one.

Every function here mutates GameState and returns Events: plain-English facts the narrator turns into prose.
The language model never changes state directly.

An action is the numbered choices' (available_actions), one that may be done though it isn't a choice
(off_the_list: picking up any one thing, moves with what you carry...), or a whole use of the interaction grid
("give:pickle@monster:lucky_lenny": interactions.py), which perform plans and runs. One that can't be done right now
says why (why_not), costing nothing: "You're not hurt, so you keep the Healing Potion."
"""

from __future__ import annotations

import random

from . import dice, interactions, inventory, layout, loot, npcs, powers
from .combat import (bomb_monster, discover, distract, dodge, flee, flee_direction, fortune, monster_turn,
                     player_attack, telegraph, throw, what_is_left)
from .content import Content, ItemDef
from .creative import perform_creative as _creative
from .events import Action, Event
from .intent import Intent
from .inventory import PICKUPS
from .models import DELTA, DIRECTIONS, OPPOSITE, Exit, Feature, GameState, MonsterState, Room
from .scene import RoomView
from .text import a, cap, the
from .world import build_floor, monster_for, tier_for

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

    actions += _character_actions(state, content)  # whoever's here first: Lenny's tooth, Swoogy's game, talking...
    actions += _take_actions(state, content)
    actions += inventory.choices(state, content)  # better gear in your pack, to put on
    for index, feature in room.visible_features():
        if not feature.searched:
            actions.append(Action(f"search:{index}", f"Search {the(feature.name)}", TIP if feature.told else ""))
    actions += _fixture_actions(state, content)
    theme = content.themes[state.theme]
    for direction in DIRECTIONS:
        exit_ = room.exits.get(direction)
        if not exit_:
            continue
        dest = state.rooms[exit_.to]
        if exit_.locked and exit_.key == "small_key":  # a shop's door (with no key, it's no choice: see locked_doors)
            if player.keys:
                keys = f"{player.keys} key{'s' if player.keys > 1 else ''}"
                actions.append(Action(f"go:{direction}", f"Unlock the shop door {direction}", f"shop · {keys}"))
            if player.bombs:
                bombs = f"{player.bombs} bomb{'s' if player.bombs > 1 else ''}"
                actions.append(Action(f"bomb:{direction}", f"Bomb the shop door {direction}",
                                      f"cracked! · {bombs}" if exit_.cracked else f"two bombs break it · {bombs}"))
            continue
        if exit_.locked:
            if theme.key_item in player.inventory:
                actions.append(Action(f"go:{direction}", f"Unlock the door {direction}", "boss"))
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
        actions.append(Action("rest", "Rest a while", "safe here" if safe_to_rest(state) else "risky"))
    if room.monster:  # last of all: it isn't fighting you (and one click shouldn't end a quest)
        monster = room.monster
        actions.append(Action("attack", f"Attack {the(monster.name)}", "it's calm · no reward" if monster.rewarded
                              else "it's calm"))
    return actions


def _character_actions(state: GameState, content: Content) -> list[Action]:
    """What whoever's here and not fighting you offers, first among the choices: a shop's keeper her wares; a
    character what it's after (npcs.actions: Lenny's tooth, Swoogy's game and his guesses); talking to them (no roll,
    no turn); asking what they know (a wits roll, once: a creature that can't talk, you watch instead)."""
    room, player = state.room, state.player
    talk = npcs.talk_action(state, content)
    if room.shop:
        keeper = content.monster(room.shop.keeper).name
        wares = Action("shop", f"Browse {keeper}'s wares", f"¤ {player.gold} gold" if room.shop.wares else "sold out")
        ask = [] if room.shop.asked else [Action("ask", f"Ask {keeper} what she knows", "wits")]
        return [wares, talk] + ask
    monster = room.monster
    if monster is None:
        return []
    actions = npcs.actions(state, content) + ([talk] if talk else [])
    if not monster.asked:
        talks = content.monster(monster.key).intelligent
        knows = "they know" if content.monster(monster.key).named else "it knows"
        actions.append(Action("ask", f"Ask {the(monster.name)} what {knows}" if talks
                              else f"Watch {the(monster.name)} for a while",
                              "his tooth first" if npcs.tooth_first(state) else "wits"))
    return actions


def _take_actions(state: GameState, content: Content) -> list[Action]:
    """Picking up is free: one choice for the lot (or click each one's card in the story). Not what you put down here
    yourself; and never a cursed thing with the rest: alone, its choice says it's cursed and warns you when you go to
    take it (inventory.take); among other things, the lot is everything but it (take it by its card, or say so)."""
    lying = inventory.takeable(state.room)
    cursed = [k for k in lying if inventory.sticky(state, content, k)]
    plain = [k for k in lying if k not in cursed]
    if plain and cursed:
        one = len(set(cursed)) == 1
        but = the(content.item(cursed[0]).name) if one else "what's cursed"
        return [Action("take_all", f"Pick up everything but {but} ({len(plain)})",
                       "it's cursed! · no turn" if one else "no turn")]
    if len(plain) > 1:
        return [Action("take_all", f"Pick up everything here ({len(plain)})", "no turn")]
    if plain:
        return [Action(f"take:{plain[0]}", f"Pick up {the(content.item(plain[0]).name)}", "no turn")]
    if cursed:
        key, name = cursed[0], the(content.item(cursed[0]).name)
        if key in state.warned:
            return [Action(f"take:{key}", f"Take {name} anyway", "cursed! · no turn")]
        return [Action(f"take:{key}", f"Pick up {name}", "cursed! · no turn")]
    return []


def locked_doors(state: GameState, content: Content) -> list[Action]:
    """The doors here you can't open yet (a shop's with no small key, the boss's without its key): not numbered
    choices, since there's nothing to do with them, but there to say so if you try one ("go south": it's locked), and
    on the arrow pad."""
    if state.over or state.pending_perks or state.in_combat:
        return []
    have = {"small_key": state.player.keys > 0, "": content.themes[state.theme].key_item in state.player.inventory}
    return [Action(f"go:{d}", f"Go {d}", "a locked shop" if state.rooms[e.to].shop else "locked")
            for d in DIRECTIONS for e in [state.room.exits.get(d)] if e and e.locked and not have.get(e.key, False)]


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
    if not room.fixture or (room.monster and room.monster.hostile):
        return []
    cursed = [content.item(k).name for k in inventory.carried_keys(state) if inventory.sticky(state, content, k)]
    pray = [Action("shrine_pray", f"Pray at the shrine to lift your curse{'s' * (len(cursed) > 1)}", ", ".join(cursed))]
    if room.fixture_used:  # (a shrine you've bled or paid at still hears a prayer: it isn't one of its uses)
        return pray if room.fixture == "shrine" and cursed else []
    if room.fixture == "shop":  # (her wares are hers to offer: _character_actions)
        return []
    if room.fixture == "stairs":
        return [Action("descend", f"Descend the stairs to floor {state.floor + 1}", "no way back")]
    if room.fixture == "shrine":
        actions = pray if cursed else []
        if player.hp > 6:
            actions.append(Action("shrine_blood", "Offer blood at the shrine", "-6 HP, +1 Fate"))
        if player.gold >= 10 and player.hp < player.max_hp:  # (at full health it would take your gold for nothing)
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
    """Resolve one engine action. Unknown or impossible actions return an info event saying why, and cost nothing."""
    if state.over:
        return []
    use = interactions.parse(action_id)
    if use is not None:
        return _interact(state, content, action_id, use)
    if action_id not in {a.id for a in available_actions(state, content)} and \
            not off_the_list(state, content, action_id):
        return [Event("info", why_not(state, content, action_id) or "You can't do that right now.")]
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
        events, took_turn = quietly(inventory.take(state, content, arg)), False
    elif verb == "take_all":
        events, took_turn = quietly(inventory.take_all(state, content)), False
    elif verb in ("equip", "unequip", "drop", "sell"):  # free out of a fight; in one, putting gear on takes a turn
        # (with nothing named, "equip:", the interpreter knew the verb but not the thing: you're told you haven't it)
        events = getattr(inventory, verb)(state, content, arg) if arg else inventory.nothing_like(state, content, verb)
        took_turn = state.in_combat and events[0].kind != "info"
        if not took_turn:
            events = quietly(events)
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
        events, took_turn = _ask(state, content, rng)
    elif verb == "talk":  # their own words, for nothing: no roll, no turn
        events, took_turn = npcs.talk(state, content, arg), False
    elif verb == "shop":
        keeper = content.monster(state.room.shop.keeper).name
        events, took_turn = [Event("shop", f"{keeper} spreads her wares across the counter.", data={"quiet": True})], False
    elif verb == "buy":
        events, took_turn = _buy(state, content, int(arg)), False
    elif verb == "barter":
        events = _barter(state, content, rng, int(arg))
    elif verb in FIXTURE_VERBS:
        events = _fixture(state, content, rng, verb)
    elif verb == "descend":
        events = _descend(state, content)
    elif verb in ("lenny", "lenny_quest", "lenny_hint", "lenny_reward", "swoogy", "guess", "appease"):
        events = npcs.perform(state, content, rng, verb, arg)
        # (taking his quest or his reward costs nothing, nor does handing him his tooth, unless he's fighting you)
        took_turn = verb not in ("lenny_quest", "lenny_reward") and (verb != "lenny" or was_in_combat)
    else:
        return [Event("info", "You can't do that right now.")]
    return finish_turn(state, content, rng, events, took_turn, was_in_combat, room_before)


FIXTURE_VERBS = ("shrine_blood", "shrine_gold", "shrine_pray", "chest", "chest_key", "chest_smash", "chest_bomb",
                 "fountain")


def _interact(state: GameState, content: Content, action_id: str, use: interactions.Use) -> list[Event]:
    """A use of the interaction grid: what it comes to (interactions.plan) is an engine action to take as any other,
    one of the grid's own to run, or why it can't be (nothing spent, no turn). A picker only says what there is to
    pick from."""
    if interactions.is_picker(action_id):
        options = [o for o in interactions.choices(state, content, action_id) if o.hint != interactions.NO]
        if not options:
            return [Event("info", "You've nothing that would do.", data={"quiet": True, "picker": action_id})]
        ref = RoomView(state, content).get(use.target) if use.target else None
        ask = (f"{cap(use.verb)} what?" if ref is None or ref.kind in ("self", "room") else
               f"{cap(use.verb)} {the(ref.name)} what?" if use.verb == "give" else
               f"{cap(use.verb)} what on {the(ref.name)}?") if not use.subject else "On what?"
        listed = inventory.listing([o.label for o in options], "or")
        return [Event("info", f"{ask} {listed}.", data={"quiet": True, "picker": action_id})]
    row = interactions.plan(state, content, use)
    if row is None:
        return [Event("info", "Nothing would come of that.")]
    if row.alias:
        return perform(state, content, row.alias)
    if row.refusal:  # (a character handing it back says so, in its own words)
        return [Event("info", row.refusal)] + (npcs.say(state, content, row.speaker, row.moment) if row.speaker else [])
    rng = _rng(state)
    was_in_combat, room_before = state.in_combat, state.room_id
    events, took_turn = interactions.perform(state, content, rng, use, row)
    return finish_turn(state, content, rng, events, took_turn, was_in_combat, room_before)


def perform_creative(state: GameState, content: Content, intent: Intent) -> tuple[Intent, list[Event]]:
    """A creative attempt. If it's plainly one of the interaction grid's uses ("splash the holy water in its face",
    "give the ghoul the cheese", "drop the bread"), that's what happens, the grid's way (interactions.from_intent); if
    not, it's a stunt (creative.py), which wastes nothing."""
    if state.over:
        return intent, []
    action = interactions.from_intent(state, content, intent)
    talk = npcs.talk_action(state, content)  # (talking down someone who isn't fighting you is just talking to them)
    if not action and talk and intent.success_effects and set(intent.success_effects) <= {"pacify"}:
        action = talk.id
    if action:
        return intent, perform(state, content, action)
    rng = _rng(state)
    was_in_combat, room_before = state.in_combat, state.room_id
    intent, events, took_turn = _creative(state, content, intent, rng)
    return intent, finish_turn(state, content, rng, events, took_turn, was_in_combat, room_before)


def perform_flavor(state: GameState, content: Content, words: str = "") -> list[Event]:
    """Harmless free text. Costs nothing outside a fight, but in a fight the monster gets its turn. Unless the words
    are plainly one of the interaction grid's uses, said with nothing at stake ("give Lenny the potion", "show him
    the tooth"): then that's what happens, as if chosen (the keyword matcher knows no gifts). Words said to someone
    here who'd answer ("talk to lenny", "ask granny how she's keeping") are talking to them: they answer in their own
    words (or, fighting you, it says why not, for nothing)."""
    action = interactions.from_intent(state, content, Intent(kind="creative", difficulty="trivial", summary=words)) \
        if words else None
    action = action or (npcs.talked_to(state, content, words) if words else None)
    if action:
        return perform(state, content, action)
    if not state.in_combat:
        return []
    return finish_turn(state, content, _rng(state), [], True, True, state.room_id)


def finish_turn(state, content, rng, events, took_turn, was_in_combat, room_before) -> list[Event]:
    if took_turn:
        state.turn += 1
        state.reroll = 0
        if was_in_combat and state.room_id == room_before and state.in_combat and not state.over:
            events += monster_turn(state, content, rng)
    if not state.in_combat:  # the fight's over: no vines left to hold you, nothing to dodge
        state.player.tangled = state.player.dodging = False
    events = npcs.react(state, content, events)  # what the characters say to it all, each right after what it's about
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
        inventory.off_the_floor(room, key)
        events += inventory.gain(state, content, key, "take", "room")
    return quietly(events)


def things_here(state: GameState, content: Content) -> list[Action]:
    """Taking any one thing lying here that isn't a numbered choice of its own: click its card, or say so ("grab the
    potion"), for the interpreter to match."""
    if state.in_combat:
        return []
    numbered = {a.id for a in _take_actions(state, content)}
    return [Action(f"take:{key}", f"Pick up {the(content.item(key).name)}") for key in _distinct(state.room.items)
            if f"take:{key}" not in numbered]


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
        events.append(Event("level", f"You reach level {player.level}! Choose a perk.",
                            data={"level": player.level, "journal": f"You reached level {player.level}."}))
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
    state.player.tangled = state.player.dodging = False  # (out of its vines, and out of the way of what was there)
    room = state.room
    room.entered_from = OPPOSITE[direction]
    first = not room.visited
    room.visited = True
    arrival = f"You go {direction} into {the(room.name)}" + (" for the first time." if first else ", where you've been before.")
    journal = f"You went {direction} into {the(room.name)}" + (" for the first time." if first else ".")
    events = [Event("enter", f"{arrival} {arrival_facts(state, content)}".strip(),
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


def arrival_facts(state: GameState, content: Content) -> str:
    """What there is to tell of a room just come into, which isn't the room: its things, who's here and the ways out are
    on the screen (the stage, Here, the choices). The narrator is told only what stands out: a secret room, a shop's
    keeper, a ghost, a fight about to begin, and on a return what happened here since. (room_facts is the whole room,
    for a question about it.)"""
    room = state.room
    lines = ["A secret room, walled off until a bomb opened it."] if room.secret else []
    if room.shop:
        lines.append(shop_facts(room.shop, content))
    monster = room.monster
    if monster and monster.ghost_of and state.ghost:
        lines.append(_ghost_facts(state, monster))
    elif monster and monster.hostile:
        elite = " It looks unusually dangerous." if monster.elite else ""
        lines.append(f"{cap(the(monster.name))} is here and hostile. A fight begins.{elite}")
    if room.history:
        lines.append("Earlier here: " + "; ".join(room.history) + ".")
    return " ".join(lines)


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
            lines.append(_ghost_facts(state, monster))
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


def _ghost_facts(state: GameState, monster: MonsterState) -> str:
    ghost = state.ghost
    return (f"The restless ghost of {monster.ghost_of} is here and hostile. {ghost_truth(monster)} "
            f"In that life they were {ghost.get('cause', 'killed down here')}. "
            f"Their epitaph read: \"{ghost.get('epitaph', '')}\"")


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
    state.floor += 1
    state.souls += 10
    build_floor(state, content)
    theme = content.themes[state.theme]
    room = state.room
    goal = f"Your goal: {theme.goal}" if state.final_floor else ""
    told = [f"You go down the stairs to floor {state.floor}, {theme.name}, and arrive in {the(room.name)}.",
            arrival_facts(state, content), goal]  # (the floor's header has its blurb, the HUD its souls)
    text = " ".join(part for part in told if part)
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

def _search_feature(state: GameState, content: Content, feature: Feature) -> list[Event]:
    feature.searched = True
    state.player.bump("searched")
    events = []
    for key in feature.loot:  # it lies there, to take or leave (bombs and small keys are yours at once: collect)
        events.append(Event("find", f"You search {the(feature.name)} and find {the(content.item(key).name)}.",
                            data=inventory.lay(state, key, "find", feature.name)))
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
    if roll.crit:  # (a natural 20 always turns something up: with nothing hidden, a few coins someone dropped)
        gold = rng.randint(2, 6) * state.floor + 3
        player.gold += gold
        roll.effects.append(f"+{gold} gold")
        return [Event("search_room", f"Nothing's hidden here, but your fingers find a few coins wedged under a loose "
                                     f"stone (+{gold} gold).", dice=roll, data={"gold": gold})] + events
    # Only worth a Fate reroll if there really was something to find.
    return [Event("search_room", "You search every corner but find nothing hidden.", dice=roll,
                  data={"rerollable": bool(hidden or beside)})] + events


def _draft(state: GameState, direction: str, roll: dice.Roll | None = None) -> Event:
    """The sign of a secret room next door, for anyone who looks hard enough."""
    state.room.draft = direction
    return Event("secret", f"A faint draft whistles through a crack in the {direction} wall. There's space behind it.",
                 dice=roll, data={"rerollable": True} if roll else {})


# --- what a calm creature knows ------------------------------------------------

def _ask(state: GameState, content: Content, rng: random.Random) -> tuple[list[Event], bool]:
    """Ask a creature that's stopped fighting what it knows (or a shop's keeper), or watch where it goes if it can't
    talk: a wits roll, once each. It knows its floor: where the secret room is, or what's hidden where, and that goes
    on your map. Failing those, one that talks knows what one of the floor's monsters can't stand. Lucky Lenny tells
    you where his own tooth went for nothing, and as often as you ask (npcs.talk): that's no gossip. The events, and
    whether it took a turn."""
    room, player = state.room, state.player
    if npcs.tooth_first(state):
        return npcs.talk(state, content, npcs.LENNY), False
    if room.monster is None and room.shop:  # (she's no monster, but she knows her floor as well as any)
        keeper = content.monster(room.shop.keeper)
        monster = MonsterState(key=keeper.key, name=keeper.name, hp=keeper.hp, max_hp=keeper.hp, hostile=False)
        room.shop.asked = True
    else:
        monster = room.monster
        monster.asked = True
    talks = content.monster(monster.key).intelligent
    hidden = [(r, f) for r, f in _hidden_things(state)  # (his own tooth he'd tell you of anyway: it's no gossip)
              if not (monster.key == npcs.LENNY and f and npcs.BAD_TOOTH in f.loot)]
    weak = _weak_spots(state, content) if talks else []
    if not (hidden or weak):  # nothing it could tell you, so nothing to roll for
        return [Event("ask", f"{cap(the(monster.name))} doesn't know anything about this floor that you don't." if talks
                      else f"You watch {the(monster.name)} for a while. It doesn't lead you anywhere new.")], True
    bonuses = [("wits", player.wits)] + powers.roll_bonuses(state, content, "ask")
    roll = dice.check(rng, "wits (ask)" if talks else "wits (watch it)", bonuses, ASK_DC,
                      advantage=int(talks and "silver_tongue" in player.traits))
    events = fortune(state, roll)
    if not roll.success:
        return [Event("ask", f"{cap(the(monster.name))} hums and haws, and tells you nothing you can use." if talks
                      else f"You watch {the(monster.name)} for a while, but it never goes anywhere that matters.",
                      dice=roll, data={"rerollable": True})] + events, True
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
    return told + events, True


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
    if talks:  # (Lenny tells of his own tooth in his own words: npcs.point)
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
    used = inventory.consume(state, key, "use")
    room.room_searched = True
    events = [Event("use", f"You light up the room with {the(item.name)}. It's spent, but every corner is bright."
                           f"{what_is_left(state.player, key)}", data=used)]
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
    """A shop as the narrator knows it: who keeps it, and what she's like. Her wares are the shop's to show."""
    keeper = content.monster(shop.keeper)
    return f"{keeper.name} keeps a shop here. About {keeper.name}: {keeper.desc}"


def off_the_list(state: GameState, content: Content, action_id: str) -> bool:
    """What may be done now that isn't one of the numbered choices: picking up any one thing lying here (by its card
    in the story, or by saying so), equipping, taking off, leaving or selling what you carry (inventory.moves),
    trying a door that's locked, buying or haggling at a shop's counter (its own screen does those), handing an
    angry Swoogy anything you carry, and blowing a chest open with a bomb (the interaction grid's)."""
    verb, _, arg = action_id.partition(":")
    if verb == "take":
        return arg in state.room.items and not state.in_combat
    if verb in ("equip", "unequip", "drop", "sell"):  # (nothing named: to be told you haven't it)
        return not arg or action_id in {a.id for a in inventory.moves(state, content)}
    if verb == "go":  # a locked door you try anyway: it says so, and costs nothing
        return action_id in {a.id for a in locked_doors(state, content)}
    if verb == "appease":  # anything of yours, to calm Swoogy down
        return action_id in {a.id for a in npcs.unlisted(state, content)}
    if verb == "chest_bomb":
        room = state.room
        return room.fixture == "chest" and not room.fixture_used and state.player.bombs > 0 and not state.in_combat
    shop = state.room.shop
    return verb in ("buy", "barter") and shop is not None and not state.in_combat and arg.isdigit() \
        and int(arg) < len(shop.wares)


def unlisted(state: GameState, content: Content) -> list[Action]:
    """Everything that may be said here that isn't a numbered choice, for the interpreter to match: any one thing
    lying here, moves with what you carry, gifts to an angry Swoogy, locked doors, the interaction grid's other uses
    here, and what can't be done right now but would be told why (unavailable). Each once."""
    listed = available_actions(state, content)
    seen, said = {a.id for a in listed}, {a.label for a in listed}
    out = []
    for action in (things_here(state, content) + inventory.moves(state, content) + npcs.unlisted(state, content)
                   + locked_doors(state, content) + interactions.unlisted(state, content)
                   + unavailable(state, content)):
        if action.id not in seen and action.label not in said:
            seen.add(action.id)
            said.add(action.label)
            out.append(action)
    return out


def unavailable(state: GameState, content: Content) -> list[Action]:
    """What you might well say that can't be done right now, each told why if you do (why_not), at no cost: eating
    or drinking with nothing to heal, asking a creature what it knows or talking to a character in the middle of a
    fight, resting, searching what you've searched already, a bomb for a wall with nothing behind it. Their hints say
    why not."""
    if state.over or state.pending_perks:
        return []
    room, player, out = state.room, state.player, []
    listed = {a.id for a in available_actions(state, content)}
    for key in _distinct(player.inventory):
        item = content.item(key)
        if item.kind == "consumable" and item.heal and f"use:{key}" not in listed:
            why = why_not(state, content, f"use:{key}")
            out.append(Action(f"use:{key}", f"{heal_verb(item)} {the(item.name)}", why))
    monster = room.monster if room.monster and room.monster.hp > 0 else None
    if monster and "ask" not in listed:
        knows = "they know" if content.monster(monster.key).named else "it knows"
        out.append(Action("ask", f"Ask {the(monster.name)} what {knows}", why_not(state, content, "ask")))
    if room.shop and "ask" not in listed:
        keeper = content.monster(room.shop.keeper).name
        out.append(Action("ask", f"Ask {keeper} what she knows", why_not(state, content, "ask")))
    if monster and npcs.speaks(content, monster.key) and f"talk:{monster.key}" not in listed:
        out.append(Action(f"talk:{monster.key}", f"Talk to {the(monster.name)}",
                          why_not(state, content, f"talk:{monster.key}")))
    if "rest" not in listed:
        out.append(Action("rest", "Rest a while", why_not(state, content, "rest")))
    if "search_room" not in listed:
        out.append(Action("search_room", "Search the room for secrets", why_not(state, content, "search_room")))
    for index, feature in room.visible_features():
        if feature.searched and not state.in_combat:
            out.append(Action(f"search:{index}", f"Search {the(feature.name)}", "searched already"))
    if player.bombs and not state.in_combat:
        walls = [d for d in DIRECTIONS if d not in room.exits and f"bomb:{d}" not in listed]
        out += [Action(f"bomb:{d}", f"Bomb the {d} wall", "nothing behind it") for d in walls]
    return [a for a in out if a.hint]


def why_not(state: GameState, content: Content, action_id: str) -> str:
    """Why an action you might name can't be done right now, in a word to the player ("You're not hurt, so you keep
    the Healing Potion."), or "" if there's nothing particular to say."""
    room, player = state.room, state.player
    verb, _, arg = action_id.partition(":")
    monster = room.monster if room.monster and room.monster.hp > 0 else None
    name = cap(the(monster.name)) if monster else ""
    if state.pending_perks:
        return "First, choose a perk."
    item = content.item(arg) if arg in content.items else None
    if verb in ("use", "throw", "distract", "reveal") and item and arg not in player.inventory:
        return f"You have no {item.name}."
    if verb == "use" and item:
        if item.escape and not state.in_combat:
            return f"You decide to save {the(item.name)} for an emergency."
        if item.heal and player.hp >= player.max_hp:
            return f"You're not hurt, so you keep {the(item.name)}."
        if item.kind != "consumable":
            return f"{cap(the(item.name))} is no use on its own: try it on something."
    if verb in ("attack", "throw", "distract") or (verb == "bomb" and not arg):
        if verb == "bomb" and not player.bombs:
            return "You have no bombs."
        if not monster:
            return "There's nothing here to fight." if verb == "attack" else "There's nothing here to throw it at."
        if verb != "attack" and not monster.hostile:
            return f"{name} isn't fighting you."
        if verb == "distract" and monster.distracted:
            return f"{name} won't fall for that again this fight."
    if verb == "bomb" and arg in DIRECTIONS:
        if not player.bombs:
            return "You have no bombs."
        if room.shop:
            return "Not in her shop, you don't."
        exit_ = room.exits.get(arg)
        if exit_ and not exit_.locked:
            return f"The {arg} door stands open: there's nothing there to blow."
        if exit_:
            return f"The {arg} door is far too stout for a bomb."
        if state.in_combat:
            return f"Not with {the(monster.name)} at you."
        if any(r.secret and r.exits for r in state.rooms):
            return "You've found this floor's hidden room already: no other wall is worth a bomb."
        return f"There's only solid earth behind the {arg} wall: it isn't worth a bomb."
    if verb in ("dodge", "flee") and not state.in_combat:
        return "There's nothing here to get away from."
    if verb == "flee" and player.tangled:
        return f"You're tangled in {the(monster.name)}'s vines: no running until it's had its next go."
    if verb == "ask":
        if not monster:
            if room.shop and room.shop.asked:
                return f"{content.monster(room.shop.keeper).name} has told you all she knows."
            return "" if room.shop else "There's no one here to ask."
        talks = content.monster(monster.key).intelligent
        if state.in_combat:
            return f"{name} is fighting you, not chatting." if talks else f"{name} is too busy fighting you."
        if monster.asked:
            return f"{name} has told you all {'they know' if content.monster(monster.key).named else 'it knows'}."
    if verb == "talk":
        keeper = content.monster(room.shop.keeper) if room.shop else None
        if keeper and arg in ("", keeper.key):
            return ""
        if not monster:
            return "There's no one here to talk to."
        if arg and arg != monster.key:
            return f"There's no one like that here: only {the(monster.name)}."
        talks = content.monster(monster.key).intelligent
        if state.in_combat:
            return f"{name} is fighting you, not chatting." if talks else f"{name} is too busy fighting you."
        if not npcs.speaks(content, monster.key):
            return f"{name} has nothing to say to you." if talks else f"{name} doesn't understand a word."
    if verb == "rest":
        if state.in_combat:
            return "Not in the middle of a fight."
        if room.rested:
            return "You've rested here already."
        if player.hp >= player.max_hp:
            return "You're not hurt: there's nothing to rest off."
    if verb == "search_room":
        if state.in_combat:
            return "Not in the middle of a fight."
        if room.shop:
            return "It's her shop: there's nothing hidden here for you to find."
        if room.room_searched:
            return "You've searched this room already."
    if verb == "search" and arg.isdigit() and int(arg) < len(room.features):
        feature = room.features[int(arg)]
        if feature.searched:
            return f"You've searched {the(feature.name)} already: there's nothing more in it."
    if verb in FIXTURE_VERBS or verb == "descend":
        fixture = {"descend": "stairs", "fountain": "fountain"}.get(verb, verb.partition("_")[0])
        if room.fixture != fixture:
            return {"stairs": "There are no stairs here.", "shrine": "There's no shrine here.",
                    "chest": "There's no chest here.", "fountain": "There's no fountain here."}[fixture]
        if monster and monster.hostile:
            return f"{name} stands in your way." if verb == "descend" else f"Not with {the(monster.name)} at you."
        if verb == "shrine_pray":
            return "You carry nothing cursed: there's no curse here to lift."
        if room.fixture_used:
            return {"chest": "The chest is open already.", "fountain": "You've drunk from the fountain already.",
                    "shrine": "The shrine has given all it will."}.get(fixture, "")
        if verb == "chest_key" and not player.keys:
            return "You have no small key."
        if verb == "chest_bomb" and not player.bombs:
            return "You have no bombs."
        if verb == "shrine_blood":
            return "You're too weak to give blood."
        if verb == "shrine_gold":
            return (f"The shrine wants 10 gold, and you have {player.gold}." if player.gold < 10
                    else "You're not hurt: the shrine would take your gold for nothing.")
    if verb.startswith("lenny"):
        if not (monster and monster.key == npcs.LENNY):
            return "Lucky Lenny isn't here."
        if monster.mood in ("owed", "happy") and verb != "lenny_reward":
            return "Lucky Lenny has his bad tooth back already."
        if verb == "lenny" and npcs.BAD_TOOTH not in player.inventory:
            return "You haven't got his tooth."
        if verb == "lenny_reward" and monster.mood != "owed":
            return ("You've had his reward already." if monster.mood == "happy"
                    else "Lucky Lenny will give you something once he has his tooth back.")
        if verb == "lenny_quest" and npcs.stage(state, npcs.LENNY) == "accepted":
            return "You've taken his quest already."
        if verb == "lenny_hint" and not npcs.asks_where(state):
            return "He's told you all he remembers."
    if verb == "take":
        if state.in_combat:
            return "Not in the middle of a fight."
        if item and arg not in room.items:
            return f"There's no {item.name} here."
    return ""


def _buy(state: GameState, content: Content, index: int) -> list[Event]:
    shop, player = state.room.shop, state.player
    ware = shop.wares[index]
    item = content.item(ware.item)
    if player.gold < ware.price:
        return [Event("info", f"{cap(the(item.name))} is {ware.price} gold, and you have {player.gold}.",
                      data={"quiet": True})]
    player.gold -= ware.price
    shop.wares.pop(index)
    says = f"You buy {the(item.name)} for {ware.price} gold ({player.gold} left)"
    return quietly(inventory.gain(state, content, ware.item, "buy", "shop", says=says, kind="buy"))


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
        used = inventory.consume(state, key, "use")
        return [Event("use", f"You hurl {the(item.name)} at your feet. Thick smoke fills the room."
                             f"{what_is_left(player, key)}", data=used)] + flee(
            state, content, rng, guaranteed=True), True
    glows = "dazzle" in item.powers and state.in_combat
    if player.hp >= player.max_hp and not glows:
        return [Event("info", f"You're not hurt, so you keep {the(item.name)}.")], False
    heal = round(item.heal * (1.5 if "alchemist" in player.perks else 1))
    healed = min(heal, player.max_hp - player.hp)
    player.hp += healed
    used = inventory.consume(state, key, "use")
    verb = heal_verb(item).lower()
    recover = f" and recover {healed} HP ({player.hp}/{player.max_hp})" if healed else ""  # (eaten for its glow)
    events = [Event("heal", f"You {verb} {the(item.name)}{recover}.{what_is_left(player, key)}", data=used)]
    return events + (_dazzle(state, content) if glows else []), True


def _dazzle(state: GameState, content: Content) -> list[Event]:
    """Glowing like a lantern (a dazzle power): the monster flees the room, no reward for it. A boss, a guardian, the
    warden at the stairs, a ghost, or one of the dungeon's characters (Swoogy: calm him down or fight him) stands its
    ground."""
    monster = state.room.monster
    monster_def = content.monster(monster.key)
    if monster_def.boss or monster_def.npc or "guardian" in monster_def.tags or monster.warden or monster.ghost_of:
        return [Event("dazzle", f"You glow like a lantern, but {the(monster.name)} only squints at you and stands its "
                                "ground.")]
    state.room.monster = None
    state.room.remember(f"your glow sent {the(monster.name)} running")
    return [Event("dazzle", f"You glow like a lantern! {cap(the(monster.name))} shrieks and flees the room in terror.")]


def _open_chest(state: GameState, content: Content, rng: random.Random, how: str) -> list[Event]:
    """A chest three ways: a small key opens it safely; picking the lock (agility) risks the needle trap; smashing it
    (might) skips the trap, but a blow that goes wrong breaks whatever's inside. And a fourth, if you'd rather: a bomb
    always opens it, trap and all, and whatever's inside but the gold goes with the lid."""
    player = state.player
    broken = False
    if how == "chest_key":
        player.keys -= 1
        events = [Event("chest", "The small key turns, and the lid lifts without a fight "
                                 f"({player.keys} key{'s' if player.keys != 1 else ''} left).")]
    elif how == "chest_bomb":
        player.bombs -= 1
        broken = True
        events = [Event("chest", f"The bomb blows the lid clean off, trap and all ({player.bombs} "
                                 f"bomb{'s' if player.bombs != 1 else ''} left).", data={"bomb": True})]
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
    return events + [Event("find", f"Inside: {the(name)} and {gold} gold.", data=inventory.lay(state, key, "find",
                                                                                              "chest"))]


def safe_to_rest(state: GameState) -> bool:
    """Whether nothing can creep up on you while you rest: not with someone already here (a calm character, or a
    monster you've talked down, keeps watch), nor in a shop."""
    return state.room.monster is not None or state.room.shop is not None


def _rest(state: GameState, content: Content, rng: random.Random) -> list[Event]:
    room, player = state.room, state.player
    room.rested = True
    if not safe_to_rest(state) and rng.random() < 0.25:
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
    """A fixture's use. Each is the fixture's one use, but a prayer: a shrine lifts a curse whenever you ask, used or
    not (so blood or gold first never leaves you stuck with one)."""
    room, player = state.room, state.player
    room.fixture_used = room.fixture_used or verb != "shrine_pray"
    room.remember({"shrine_blood": "you bled on the shrine", "shrine_gold": "you gave gold to the shrine",
                   "shrine_pray": "you prayed at the shrine",
                   "chest": "you picked the chest's lock", "chest_key": "you unlocked the chest with a key",
                   "chest_smash": "you smashed the chest open", "chest_bomb": "you blew the chest open with a bomb",
                   "fountain": "you drank from the fountain"}.get(verb, verb))
    if verb in ("chest", "chest_key", "chest_smash", "chest_bomb"):
        return _open_chest(state, content, rng, verb)
    if verb == "shrine_blood":
        player.hp -= 6
        if player.fate < player.max_fate():
            player.fate += 1
            return [Event("shrine", f"You bleed on the shrine. It drinks, and the dark grants you a Fate token "
                                    f"({player.fate}/{player.max_fate()}).")]
        state.souls += 8
        return [Event("shrine", "You bleed on the shrine. Your Fate is already full, so it gives you 8 souls instead.")]
    if verb == "shrine_pray":
        lifted = inventory.lift_curses(state, content)
        names, its = " and ".join(the(name) for name in lifted), "it's" if len(lifted) == 1 else "they're"
        return [Event("shrine", f"You kneel at the shrine and pray. Its light washes over {names}, and the curse "
                                f"lifts: {its} yours to keep or leave now.")]
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
            lost, player.hp = player.hp - max(1, player.hp - damage), max(1, player.hp - damage)
            text = f"The water is bitter and burns going down (-{lost} HP)."
            roll.effects.append(f"-{lost} HP")
        elif roll.kept <= 14:
            healed = min(6, player.max_hp - player.hp)
            player.hp += healed
            text = f"The water is cool and clean (+{healed} HP)." if healed else "The water is cool and clean."
            roll.effects.append(f"+{healed} HP" if healed else "no effect: you're at full health")
        elif roll.kept <= 19:
            if player.fate < player.max_fate():
                player.fate += 1
                text = f"The water tastes like luck. You gain a Fate token ({player.fate}/{player.max_fate()})."
                roll.effects.append(f"+1 Fate ({player.fate}/{player.max_fate()})")
            else:
                text = f"The water tastes like luck, but you can't hold any more ({player.fate}/{player.max_fate()} Fate)."
                roll.effects.append(f"Fate already full ({player.fate}/{player.max_fate()})")
        else:
            stat = rng.choice(["might", "agility", "wits"])
            setattr(player, stat, player.stat(stat) + 1)
            text = f"The water blazes gold inside you: +1 {stat}, permanently!"
            roll.effects.append(f"+1 {stat}, permanently")
        return [Event("fountain", text, dice=roll, data={"rerollable": roll.kept <= 14})] + events
    return []
