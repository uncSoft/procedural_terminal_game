"""The interaction grid: what comes of doing something with one thing to another. A use is (verb, subject, target):
what you do, what you do it with (an item's key, "bomb", "small_key", "gold" and how much of it, or nothing), and
what you do it to (a scene.RoomView ref: "monster:goblin", "fixture:chest", "exit:north", "gear:weapon", "room"...).
Each verb has a planner that says what that comes to, here and now:

    throw   at a monster       thrown at it, a calm one provoked first: made to be thrown (oil, holy water), it hits
                               for its own dice, anything else throwable for what it's made of; gone, hit or miss (a
                               spare weapon lands at its feet). A bomb is your bomb, a smoke bomb your getaway.
            anywhere else      out of a fight, with nothing at stake, it lands here (to take back)
    give    to a character     what it wants, it takes (npcs.wants: Lenny his tooth, an angry Swoogy anything, a
                               shopkeeper buys it), and the rest it hands back
            to a monster       a bribe (one that talks takes gold, shiny things and food) or a lure (a beast, with
                               what it's weak to): a wits roll, and it's handed over only if it works
            to the shrine      gold: its 10 gold for a full heal
    show    to a monster       something it can't take its eyes off (a distract power, or a shiny, bright or loud
                               thing it's weak to) costs it its next attack, once a fight; a calm one just looks
    pour    on a monster       a splash, thrown (holy water, oil); on your weapon, a coating (RECIPES); on you, drunk
    use     X on Y             whatever X does to Y: a small key opens a chest or a shop's door, the boss's key its
                               door, a bomb blows a wall, a shop's door or a chest open, a weapon forces a chest, a
                               tool (a weapon, a pole, a torch) searches a feature for its own loot, a glow stick
                               lights the room; on you, it's eaten or drunk; on a monster, it's thrown, shown or given
    open    a chest or a door  a small key if you have one, else the chest's lock is picked; smash forces it (a door
                               won't give); search, a feature: what's in it, not some random find
    equip, unequip, drop, sell  inventory.py's moves (unequip names the slot: "unequip:armor")

Never a key, nor what someone's waiting for, nor a curse that won't let go (inventory.keeps): they're refused.

An action id says the whole use, and goes to rules.perform like any other action:

    give:pickle@monster:lucky_lenny     give:gold*30@monster:goblin      use:small_key@fixture:chest
    throw:holy_water@monster:ghoul      use:bomb@exit:north              pour:holy_water@gear:weapon

An id with a gap is a picker: "give:@monster:lucky_lenny" (nothing to give named), "use:holy_water@" (nowhere named).
choices() fills the gap with each option, as its own whole id. Performed, a picker only says what there is to pick
("Give Lucky Lenny what? ..."), at no cost.

What the grid knows can't work is refused, saying why, at no cost: nothing used up, no turn ("The Ghoul sniffs the
Wheel of Cheese and ignores it."). A use it has no row for at all is a stunt: creative.py's, which wastes nothing.

For the UI (the Here panel's tiles, the inventory's), with the refs of scene.RoomView (things(), carried()):

    verbs(state, content, ref)              a thing's verbs, as Actions, the most useful first: Attack, Use…, Talk,
                                            Give…, Take, Equip, Search, Unlock, Drop, Use on…. Only what would do
                                            something now. Each id goes to rules.perform, but a picker's (is_picker),
                                            which opens a picker of choices() instead. A character (or a keeper) has
                                            what it's after first, then Talk (talk:<key>: its own words, no turn) and
                                            Ask, and Attack last; what someone's waiting for has "Give it to Lucky
                                            Lenny" first on its own tile
    choices(state, content, picker)         what a picker offers, each a whole use: for a picker of things, the ones
                                            that would work first, named by the thing ("Lenny's Bad Tooth", "10 gold")
                                            with what'd happen as the hint ("he wants it back!"), then the rest, their
                                            hint NO; for a picker of targets, only the ones that would work, named by
                                            what'd happen ("Pour the Vial of Holy Water on your Silvered Blade")
    is_picker(action_id)                    whether an id is a picker
    use_id(verb, subject, target, amount)   an action id from its parts: what the interpreter is to emit too

The numbered choices (rules.available_actions) still list a row for each potion, throw and distraction, which the
inventory panel uses today; an angry Swoogy has just one for his gold and one picker ("Give Swoogy something…"). An id
that names a grid verb and an "@" belongs on a tile.

For the interpreter: read(view, summary) reads a stunt's words into a use, if they're plainly one ("splash the holy
water in its face" is holy water poured on the monster: thrown), and from_intent(state, content, intent) is the action
a creative intent really is (its verb, subject and target if the interpreter gave them, else read from its words), or
None for a stunt. rules.perform_creative and rules.perform_flavor run that instead, so the same act always comes out
the same way, however it was put. unlisted() is what the grid can do here that no numbered choice does, for the
interpreter to match.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Callable

from . import dice, inventory, light, npcs, powers
from .combat import (bomb_monster, defeat, discover, distract, fortune, holds_its_ground, provoked, throw,
                     thrown_damage)
from .content import Content, ItemDef
from .events import Action, Event
from .intent import Intent
from .models import GameState
from .scene import Ref, RoomView, words
from .text import a, cap, the

GRID_VERBS = {"use", "throw", "give", "show", "pour", "open", "smash", "search"}
PICKS = {"use", "throw", "give", "show", "pour", "sell"}  # an id of one of these with a gap is a picker
CARRY = {"equip", "unequip", "drop", "sell"}  # inventory.py's moves
LURES = {"food", "shiny", "light"}  # what a beast is drawn to, when it's weak to it
LIKES = {"food", "shiny"}  # what anything that talks takes as a bribe
DISTRACTIONS = {"shiny", "light", "loud"}  # what catches a monster's eye, when it's weak to it
BRIBE_DC, LURE_DC, FANCY_DC, ODD_DC = 15, 13, 15, 17  # gold; what it's weak to; food or shiny; anything else
COATS = 3  # hits a coating lasts
RECIPES = {("holy_water", "weapon"): "holy", ("oil_flask", "weapon"): "fire"}  # (what, on what): the tag it gives
COATED = {"holy": "blessed: it glows a soft white", "fire": "slick and burning"}
TOOLS = {"heavy", "light", "fire"}  # what a feature can be searched with, beside a weapon
REVERSED = {"coat", "dip", "dunk", "soak", "anoint", "smear", "rub"}  # "coat the blade in oil": it's the blade coated

# The words a stunt's verb may be (their roots), by what they come to. Not "brandish", "jingle", "topple" or "lure":
# those are stunts with the thing, for creative to roll.
CLASSES = {
    "throw": {"throw", "toss", "hurl", "fling", "lob", "chuck", "pitch", "bowl", "launch", "sling", "heave"},
    "pour": {"pour", "splash", "douse", "drench", "drizzle", "sprinkle", "spill", "splatter", "squirt", "smear",
             "slather", "coat", "anoint", "daub", "dab", "rub", "dip", "dunk", "soak"},
    "give": {"give", "hand", "offer", "feed", "pay", "bribe", "gift", "present", "pass", "donate", "return", "calm",
             "soothe", "appease", "placate", "pacify"},
    "show": {"show", "flash", "shine", "point", "dangle", "wave"},
    "distract": {"distract"},
    "use": {"use", "apply", "insert", "try", "jam", "wedge", "stick"},
    "open": {"open", "unlock", "unbolt", "pick"},
    "smash": {"smash", "break", "bash", "force", "pry", "prise", "prize", "lever", "kick", "ram", "batter", "hack",
              "chop", "crack", "split", "bust", "wrench"},
    "bomb": {"bomb", "blast", "blow", "explode", "detonate"},
    "search": {"search", "rummage", "dig", "poke", "prod", "probe", "sift", "scour", "ransack", "examine", "inspect",
               "check"},
    "eat": {"eat", "drink", "quaff", "chug", "gulp", "swallow", "munch", "nibble", "sip", "guzzle"},
    "burn": {"burn", "ignite", "scorch", "singe", "sear", "torch", "kindle"},  # your torch on it (light.py)
}
# Saying you put on, take off, put down or sell a thing you carry is that move (inventory.py), when the verb starts
# what you say (or a part of it after "and") with the thing as what it's done to: not "leave the room with the war
# pick", "wear a grin", "remove the cobwebs from the chain shirt". The first that's said, in this order.
CARRY_MOVES = {"equip": {"wield", "wear", "equip", "don", "swap", "switch", "put on", "change into", "ready"},
               "unequip": {"unequip", "doff", "remove", "take off"},
               "drop": inventory.DROP_WORDS,
               "sell": {"sell", "pawn"}}
IRREGULAR = {"threw": "throw", "thrown": "throw", "flung": "fling", "gave": "give", "given": "give", "fed": "feed",
             "paid": "pay", "drank": "drink", "ate": "eat", "eaten": "eat", "spilt": "spill", "burnt": "burn",
             "took": "take", "wore": "wear", "worn": "wear", "sold": "sell", "got": "get", "broke": "break",
             "broken": "break", "shone": "shine", "dug": "dig", "struck": "strike"}
PREPOSITIONS = {"at", "to", "toward", "towards", "on", "onto", "upon", "into", "in", "inside", "with", "using", "from",
                "over", "under", "underneath", "beneath", "below", "against", "across", "through", "around", "behind",
                "by", "near", "for", "as", "past", "about", "off", "out", "like"}
PARTICLES = {"up", "down", "away", "open", "back", "aside", "off", "out", "over", "around", "on"}  # after a verb
AIMED = {"at", "to", "toward", "towards", "on", "onto", "upon", "into", "in", "over", "against", "across", "through"}
BREAKS = {"and", "then", "but", "or"}  # a new part of what's said
TAILS = {"while", "whilst", "before", "after", "until"}  # what's said after these is only how it's done
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
           "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
           "hundred": 100, "a": 1}
ATTEMPT = re.compile(r"^(?:attempt(?:ing|s)?|try(?:ing)?|tries)\s+to\s+", re.I)  # "You attempt to attempt to..." no


@dataclass(frozen=True)
class Use:
    """One use of the grid (see the module's docstring)."""

    verb: str
    subject: str = ""  # an item's key, "bomb", "small_key", "gold", or "" for none
    target: str = ""  # a RoomView ref's id, or "" for none
    amount: int = 0  # how much gold


@dataclass
class Row:
    """What a use comes to: an engine action that does it (`alias`, performed as it is), one of this module's to run
    (`run`: returns the events and whether it took a turn), or why it can't be (`refusal`: nothing spent, no turn;
    a character handing it back says its piece too: `speaker`, and the `moment` of its line, npcs.say). `label` is how
    a choice for it reads ("Throw the Pickle at the Goblin"), `hint` what it would do, in a few words."""

    alias: str = ""
    run: Callable | None = None
    refusal: str = ""
    label: str = ""
    hint: str = ""
    speaker: str = ""
    moment: str = ""

    @property
    def works(self) -> bool:
        return not self.refusal


# --- action ids ----------------------------------------------------------------------------------------------------

def use_id(verb: str, subject: str = "", target: str = "", amount: int = 0) -> str:
    """An action id from its parts: use_id("give", "gold", "monster:goblin", 30) is "give:gold*30@monster:goblin"."""
    return f"{verb}:{subject}{f'*{amount}' if amount else ''}@{target}"


def parse(action_id: str) -> Use | None:
    """The use an action id names, or None if it isn't one of the grid's (`attack`, `use:healing_potion`...)."""
    verb, _, rest = action_id.partition(":")
    if verb not in GRID_VERBS | {"sell"} or "@" not in rest:
        return None
    subject, _, target = rest.partition("@")
    subject, _, amount = subject.partition("*")
    return Use(verb, subject, target, int(amount) if amount.isdigit() else 0)


def is_picker(action_id: str) -> bool:
    use = parse(action_id)
    return use is not None and use.verb in PICKS and not (use.subject and use.target)


# --- planning: what a use comes to ----------------------------------------------------------------------------------

def plan(state: GameState, content: Content, use: Use, view: RoomView | None = None) -> Row | None:
    """What `use` comes to here and now: a Row, or None if the grid has no row for it (a stunt: creative's). An engine
    action it comes to that can't be taken right now is refused, with the reason it gives (rules.why_not)."""
    from .rules import available_actions, off_the_list, why_not

    view = view or RoomView(state, content)
    target = view.get(use.target) if use.target else None
    if use.target and target is None:
        return Row(refusal=_gone(state, content, use.target))
    if use.subject:
        why = _lacking(state, content, use)
        if why:
            return Row(refusal=why)
    planner = PLANNERS.get(use.verb)
    row = planner(state, content, view, use, target) if planner else None
    if row and row.alias and row.alias not in {a.id for a in available_actions(state, content)} and \
            not off_the_list(state, content, row.alias):
        return Row(refusal=why_not(state, content, row.alias) or "You can't do that right now.", label=row.label)
    return row


def _gone(state: GameState, content: Content, ref: str) -> str:
    """Why a target isn't there to be aimed at."""
    kind, _, key = ref.partition(":")
    if kind == "exit":
        return f"There is no way {key}."
    if kind in ("monster", "keeper"):
        return "There's no one like that here." if not state.room.monster else \
            f"There's no one like that here: only {the(state.room.monster.name)}."
    if kind == "wall":
        return f"There's only solid earth behind the {key} wall: it isn't worth a bomb."
    return "That isn't here."


def _lacking(state: GameState, content: Content, use: Use) -> str:
    """Why you can't use what a use names (you haven't got it, or that much of it), or ""."""
    player, key = state.player, use.subject
    if key == "gold":
        if not player.gold:
            return "You have no gold."
        return f"You have only {player.gold} gold." if use.amount > player.gold else ""
    if key not in content.items:
        return "You have nothing like that."
    if key in inventory.PICKUPS:
        return "" if getattr(player, inventory.PICKUPS[key]) else f"You have no {content.item(key).name.lower()}s."
    return "" if key in inventory.carried_keys(state) else f"You have no {content.item(key).name}."


def _name(state: GameState, content: Content, use: Use) -> str:
    """What a use's subject is called mid-sentence: "the Pickle", "30 gold", "a bomb"."""
    if use.subject == "gold":
        return f"{use.amount or 'some'} gold"
    if use.subject in inventory.PICKUPS:
        return a(content.item(use.subject).name.lower())
    return the(content.item(use.subject).name)


def _keeps(state: GameState, content: Content, use: Use) -> str:
    """Why you won't let go of what a use names (a key, what someone's waiting for, a curse), or ""."""
    if use.subject in ("", "gold") or use.subject in inventory.PICKUPS:
        return ""
    return inventory.keeps(state, content, use.subject)


def throwable(item: ItemDef) -> bool:
    """Something you could throw at a monster: made to be (a throw power), throwable by what it is, or a weapon."""
    return "throw" in item.powers or "throwable" in item.tags or item.kind == "weapon"


def _plan_throw(state, content, view, use, target) -> Row | None:
    if not use.subject or use.subject == "gold":
        return _plan_give(state, content, view, use, target) if use.subject else None
    if target is not None and target.kind == "monster":
        return _at_creature(state, content, view, use, target)
    if target is not None and target.kind == "keeper":
        return Row(refusal=f"{target.name} ducks behind her counter. \"Not in my shop, dearie!\"")
    if use.subject in inventory.PICKUPS:  # (a bomb or a small key thrown at a door or a chest is used on it)
        return _plan_use(state, content, view, use, target) if target is not None and target.kind != "room" else None
    if state.in_combat:
        monster = view.monster
        return Row(refusal=f"Not now: in a fight, you'd throw it at {the(monster.name)}.") if monster else None
    if target is not None and target.kind not in ("room", "feature", "fixture", "exit", "wall"):
        return None
    why = _keeps(state, content, use)
    if why:
        return Row(refusal=why)
    if use.subject not in state.player.inventory:
        return None  # (tossing the weapon in your hand, or the armor on your back, about is a stunt)
    return Row(run=_toss, label=f"Throw {_name(state, content, use)} down", hint="it lands here")


def _at_creature(state, content, view, use, target: Ref) -> Row | None:
    """Throwing at whoever's here: a calm one is provoked first."""
    item, player = content.item(use.subject), state.player
    label = f"Throw {_name(state, content, use)} at {the(target.name)}"
    if use.subject == "bomb":
        return Row(alias="bomb", label=label) if target.state["hostile"] else \
            Row(run=_bomb_at, label=label, hint="it's calm: it'll fight")
    why = _keeps(state, content, use)
    if why:
        return Row(refusal=why)
    if use.subject == player.weapon and use.subject not in player.inventory:
        return Row(refusal="That's the weapon in your hand: you'd have nothing left to fight with.")
    if use.subject == player.armor and use.subject not in player.inventory:
        return Row(refusal=f"You're wearing {the(item.name)}.")
    if item.escape:
        return Row(alias=f"use:{use.subject}", label=f"Throw {the(item.name)} down", hint="get away")
    if not throwable(item):
        return None
    calm = "" if target.state["hostile"] else "it's calm: it'll fight"
    damage = thrown_damage(item)
    gone = "it lands at its feet" if item.kind == "weapon" else "gone after"
    return Row(run=_throw_at, label=label, hint=" · ".join(filter(None, [damage, gone, calm])))


def _plan_give(state, content, view, use, target) -> Row | None:
    if not use.subject:
        return None
    target = target or view.monster or view.keeper
    if target is None:
        return Row(refusal="There's no one here to give it to.")
    what = _name(state, content, use)
    if target.kind == "self":  # (giving yourself a potion: drinking it)
        eats = use.subject in content.items and content.item(use.subject).kind == "consumable"
        return _plan_use(state, content, view, Use("use", use.subject, "self"), target) if eats else None
    if target.kind == "keeper":
        if use.subject == "gold":
            return Row(refusal=f"{target.name} pushes the coins back across the counter. \"Buy something, dearie.\"")
        if use.subject in inventory.PICKUPS:
            return Row(refusal=f"{target.name} has plenty of those.")
        return Row(alias=f"sell:{use.subject}", label=f"Sell {what}",
                   hint=f"{inventory.sale_price(state, content, use.subject)} gold")
    if target.kind == "fixture" and target.key == "shrine":
        if use.subject != "gold":
            return Row(refusal="The shrine wants gold, or blood.")
        if use.amount and use.amount < 10:
            return Row(refusal="The shrine wants 10 gold, no less.")
        return Row(alias="shrine_gold", label="Offer 10 gold at the shrine", hint="full heal")
    if target.kind != "monster":
        return Row(refusal=f"There's no one there to give {what} to.")
    if use.subject in inventory.PICKUPS:  # (bombs and small keys are for walls, doors and chests)
        return Row(refusal=f"{cap(the(state.room.monster.name))} has no use for {what}.")
    if use.subject != "gold" and use.subject not in state.player.inventory:  # (what you have on)
        return Row(refusal="That's the weapon in your hand: you'd have nothing left to fight with."
                   if use.subject == state.player.weapon else f"You'd have to take off {what} first.")
    monster = state.room.monster
    known = content.monster(monster.key)
    if use.subject == known.wants and target.state["hostile"]:  # (what it came for: cursed or not, it'll take it)
        return Row(run=_trade, label=f"Give {the(monster.name)} {what}", hint="it wants it! · stops the fight")
    lenny_s = monster.key == npcs.LENNY and use.subject == npcs.BAD_TOOTH  # (his own tooth isn't kept from him)
    why = "" if lenny_s else _keeps(state, content, use)
    if why:
        return Row(refusal=why)
    if target.state["npc"]:
        return _wanted(state, content, use, monster)
    if use.subject == "gold" and not use.amount:
        what = f"{bribe_gold(state)} gold"
    if target.state["boss"]:
        return Row(refusal=f"{cap(the(monster.name))} can't be bought.")
    if not target.state["hostile"]:
        return Row(refusal=f"{cap(the(monster.name))} isn't fighting you any more: keep {what}.")
    dc, tag = _bribe_dc(state, content, use, monster)
    if dc is None:
        if use.subject == "gold":
            return Row(refusal=f"{cap(the(monster.name))} doesn't care about gold. You keep it.")
        return Row(refusal=f"{cap(the(monster.name))} sniffs {what} and ignores it. You keep it.")
    if use.subject == "gold" and (use.amount or bribe_gold(state)) < bribe_gold(state):
        return Row(refusal=f"{cap(the(monster.name))} sneers at {use.amount} gold: it'd take {bribe_gold(state)} "
                           "at least.")
    verb = "Bribe" if content.monster(monster.key).intelligent else "Feed"
    return Row(run=_bribe, label=f"{verb} {the(monster.name)} with {what}",
               hint=f"wits{' · it loves ' + tag if tag else ''} · stops the fight")


def bribe_gold(state: GameState) -> int:
    """The least gold a monster that talks would be bought off with: 5 a floor."""
    return 5 * state.floor


def _bribe_dc(state, content, use: Use, monster) -> tuple[int | None, str]:
    """How hard a gift is to get taken (None: it won't be), and which of the monster's weaknesses it plays on, if
    any."""
    monster_def = content.monster(monster.key)
    tags = {"shiny"} if use.subject == "gold" else set(content.item(use.subject).tags)
    weak = sorted(tags & set(monster_def.weak) & LURES)
    if not monster_def.intelligent:
        return (LURE_DC, weak[0]) if weak else (None, "")
    if weak:
        return LURE_DC, weak[0]
    if use.subject == "gold":
        return BRIBE_DC, ""
    return (FANCY_DC if tags & LIKES else ODD_DC), ""


def _wanted(state, content, use: Use, monster) -> Row:
    """A character handed something: what it wants it takes, the rest it hands back, saying so (npcs.wants)."""
    taker, words_, moment = npcs.wants(state, content, monster, use.subject, use.amount)
    if not taker:
        return Row(refusal=words_, speaker=monster.key if moment else "", moment=moment)
    hint = {"lenny": "he wants it back!", "appease": "calms him down · no diaper"}[taker]
    what = f"{use.amount or npcs.SWOOGY_PRICE * state.floor} gold" if use.subject == "gold" else \
        _name(state, content, use)
    label = f"Turn in: give {the(monster.name)} his bad tooth" if taker == "lenny" else f"Calm Swoogy down with {what}"
    return Row(run=_npc_takes, label=label, hint=hint)


def _plan_show(state, content, view, use, target) -> Row | None:
    if not use.subject:
        return None
    target = target or view.monster or view.keeper
    if target is None or target.kind not in ("monster", "keeper"):
        return None
    what = _name(state, content, use)
    if target.kind == "keeper":
        if use.subject == "gold" or use.subject in inventory.PICKUPS:
            return Row(refusal=f"{target.name} eyes {what}. \"Spend it, dearie, don't wave it about.\"")
        return Row(run=_quote, label=f"Show {target.name} {what}", hint="what she'd pay")
    monster = state.room.monster
    if target.state["hostile"]:
        if not distracts(content, use.subject, monster):
            return None  # (a stunt with it, if you like)
        if monster.distracted:
            return Row(refusal=f"{cap(the(monster.name))} won't fall for that again this fight.")
        return Row(run=_distract, label=f"Distract {the(monster.name)} with {what}", hint="it loses its next attack")
    return Row(run=_react, label=f"Show {the(monster.name)} {what}", hint="see what it makes of it")


def distracts(content: Content, key: str, monster) -> bool:
    """Whether something would catch a monster's eye: a distract power, or a shiny, bright or loud thing it's weak
    to (gold's shiny too)."""
    if key in inventory.PICKUPS:
        return False
    tags = {"shiny"} if key == "gold" else set(content.item(key).tags)
    return (key != "gold" and "distract" in content.item(key).powers) or \
        bool(tags & DISTRACTIONS & set(content.monster(monster.key).weak))


def _plan_pour(state, content, view, use, target) -> Row | None:
    if not use.subject or use.subject in ("gold", "bomb", "small_key"):
        return None
    item = content.item(use.subject)
    target = target or (view.monster if state.in_combat else None)
    if target is None:
        return None
    if target.kind == "self":
        return _plan_use(state, content, view, Use("use", use.subject, "self"), target) if item.heal else None
    if target.kind == "monster":
        if "throw" in item.powers or ("liquid" in item.tags and not item.heal):
            return _at_creature(state, content, view, use, target)
        return None
    if target.kind in ("gear", "item"):
        return _recipe(state, content, use, target)
    return None


def _plan_use(state, content, view, use, target) -> Row | None:
    if not use.subject:
        return None
    key, player = use.subject, state.player
    target = target or view.get("self")
    if key == "gold":
        return None if target.kind == "self" else _plan_give(state, content, view, use, target)
    item = content.item(key)
    what = _name(state, content, use)
    if target.kind == "self":
        if key in inventory.PICKUPS:
            return None
        if item.kind == "consumable":
            return Row(alias=f"use:{key}", label=f"{'Eat' if 'food' in item.tags else 'Drink'} {what}",
                       hint=f"heals {item.heal}" if item.heal else "")
        if "reveal" in item.powers:
            return Row(alias=f"reveal:{key}", label=f"Light up the room with {what}", hint="shows what's hidden")
        if item.kind in inventory.GEAR:  # (on already, there's nothing to do)
            return None if key == inventory.worn(state, item.kind) and key not in player.inventory else \
                Row(alias=f"equip:{key}", label=f"Equip {what}", hint=inventory.versus(state, content, key))
        return Row(refusal=f"{cap(what)} is no use on its own: try it on something.")
    if target.kind == "monster":
        monster = state.room.monster
        if key == "bomb":
            return _at_creature(state, content, view, use, target)
        if "torch" in item.powers and light.fire(state, content):
            return Row(alias="burn", label=f"Burn {the(monster.name)} with your torch",
                       hint=f"a flame ({light.flames(state)})")
        if item.escape or ("dazzle" in item.powers and state.in_combat):
            firm = monster is not None and holds_its_ground(state, content, monster)
            return Row(alias=f"use:{key}", label=f"{'Throw' if item.escape else 'Eat'} {what}",
                       hint=("a run for it: no sure escape" if firm else "get away") if item.escape else
                       ("it won't scare it" if firm else "it glows!"))
        if "throw" in item.powers:
            return _at_creature(state, content, view, use, target)
        if target.state["hostile"] and distracts(content, key, monster):
            return _plan_show(state, content, view, use, target)
        if set(item.tags) & (LIKES | LURES) or target.state["npc"]:
            return _plan_give(state, content, view, use, target)
        if "throwable" in item.tags:
            return _at_creature(state, content, view, use, target)
        return Row(refusal=f"{cap(what)} is no use against {the(monster.name)}.")
    if target.kind == "keeper":
        return _plan_give(state, content, view, use, target)
    if target.kind == "room":
        return Row(alias=f"reveal:{key}", label=f"Light up the room with {what}", hint="shows what's hidden") \
            if "reveal" in item.powers else None
    if target.kind == "fixture":
        return _on_fixture(state, content, use, target)
    if target.kind in ("exit", "wall"):
        return _on_exit(state, content, use, target)
    if target.kind == "feature":
        return _on_feature(state, content, use, target)
    if target.kind in ("gear", "item", "floor"):
        return _recipe(state, content, use, target)
    return None


def _on_fixture(state, content, use: Use, target: Ref) -> Row | None:
    """A key, a bomb, a tool or gold on the room's chest or shrine."""
    key, room = use.subject, state.room
    if room.monster and room.monster.hostile:
        return Row(refusal=f"Not with {the(room.monster.name)} at you.")
    if target.key == "shrine":
        return _plan_give(state, content, RoomView(state, content), use, target) if key == "gold" else \
            Row(refusal="The shrine wants gold, or blood.")
    if target.key != "chest":
        return Row(refusal=f"Nothing comes of using {_name(state, content, use)} on the {target.name}.")
    if room.fixture_used:
        return Row(refusal="The chest is open already.")
    if key == "small_key":
        return Row(alias="chest_key", label="Unlock the chest with a small key", hint="safe")
    if key == "bomb":
        return Row(alias="chest_bomb", label="Blow the chest open with a bomb", hint="what's inside breaks")
    item = content.item(key) if key in content.items else None
    if item and (item.kind == "weapon" or {"heavy", "sharp", "metal"} & set(item.tags)):
        return Row(alias="chest_smash", label=f"Force the chest open with {_name(state, content, use)}",
                   hint="might · it may break")
    if item and item.kind == "key":
        return Row(refusal=f"{cap(the(item.name))} doesn't fit the chest's lock: it's for a door.")
    return Row(refusal=f"{cap(_name(state, content, use))} won't open the chest.")


def _on_exit(state, content, use: Use, target: Ref) -> Row | None:
    """A key, a bomb or a weapon on a door (or a wall worth a bomb)."""
    key, direction = use.subject, target.key
    what = _name(state, content, use)
    if target.kind == "wall":
        if key == "bomb":
            return Row(alias=f"bomb:{direction}", label=f"Bomb the {direction} wall")
        return _breach_row(state, content, direction, key) or \
            Row(refusal=f"Nothing comes of {what} against the {direction} wall.")
    exit_ = state.room.exits[direction]
    if exit_.webbed:
        return _web(state, content, direction, key)
    if not exit_.locked:
        undo = "blow" if key == "bomb" else "open"
        return Row(refusal=f"The {direction} door isn't locked: there's nothing to {undo}.")
    boss_key = content.themes[state.theme].key_item
    needs = "a small key would open it, or two bombs break it" if exit_.key == "small_key" else \
        f"it needs {the(content.item(boss_key).name)}"
    if key == ("small_key" if exit_.key == "small_key" else boss_key):
        return Row(alias=f"go:{direction}", label=f"Unlock the {direction} door with {what}")
    if key == "bomb":
        if exit_.key == "small_key":
            return Row(alias=f"bomb:{direction}", label=f"Bomb the shop door {direction}",
                       hint="cracked!" if exit_.cracked else "two bombs break it")
        return Row(refusal=f"The {direction} door is far too stout for a bomb: {needs}.")
    item = content.item(key)
    if item.kind == "weapon" or "heavy" in item.tags:
        return Row(refusal=f"You bash at the {direction} door with {what}. It doesn't budge: {needs}.")
    return Row(refusal=f"{cap(what)} won't open the {direction} door: {needs}.")


def _web(state, content, direction: str, key: str = "") -> Row:
    """Anything at a doorway sealed with web (a lair's: Exit.webbed): fire burns through it (your torch: rules._burn_web),
    and nothing else gets through."""
    item = content.item(key) if key in content.items else None
    if light.fire(state, content) and (item is None or "torch" in item.powers):
        return Row(alias=f"burn:{direction}", label=f"Burn through the web {direction} with your torch")
    if key == "bomb":
        return Row(refusal=f"The bomb would only bounce off the web over the {direction} doorway, and stick there. "
                           "Only fire gets through it.")
    how = f" with {the(item.name)}" if item else ""
    return Row(refusal=f"You hack at the web over the {direction} doorway{how}. It gives like rubber and springs back, "
                       "sticky as glue: only fire would get through it.")


def _on_feature(state, content, use: Use, target: Ref) -> Row | None:
    """A tool on a feature (a weapon, a pole, a torch: anything heavy or bright, or made for searching): searching
    it with it, for what's in it. Anything else on a feature is a stunt."""
    item = content.item(use.subject) if use.subject in content.items else None
    if not (item and use.subject not in inventory.PICKUPS and (item.kind == "weapon" or set(item.tags) & TOOLS
                                                               or {"seeker", "careful"} & set(item.powers))):
        return None
    feature = state.room.features[int(target.key)]
    if feature.searched:
        return Row(refusal=f"You've been through {the(target.name)} already: there's nothing more in it.")
    if light.wrapped(state, content, feature):  # (only fire opens it: a torch burning, down in the dark)
        if "torch" in item.powers:
            return Row(alias=f"burn:{target.key}", label=f"Burn {the(target.name)} open with your torch",
                       hint=f"a flame ({light.flames(state)})")
        return Row(refusal=f"{cap(_name(state, content, use))} won't get through the threads: fire would.")
    return Row(alias=f"search:{target.key}", label=f"Search {the(target.name)} with {_name(state, content, use)}")


def _recipe(state, content, use: Use, target: Ref) -> Row:
    """One thing on another (RECIPES): holy water or lamp oil on the weapon in your hand. Anything else comes to
    nothing, and nothing's used up."""
    item = content.item(use.subject) if use.subject in content.items else None
    on = content.item(target.key) if target.key in content.items else None
    if use.subject == light.OIL and on and "torch" in on.powers:  # (lamp oil on a torch: every flame back)
        return Row(alias="refill", label=f"Fill your torch with {the(item.name)}", hint="every flame back")
    tag = RECIPES.get((use.subject, on.kind)) if on else None
    if tag and target.kind != "gear":
        return Row(refusal=f"Take {the(on.name)} in hand first: a coating's no good on a spare.")
    if tag:
        return Row(run=_coat, label=f"Pour {the(item.name)} on your {on.name}", hint=f"its hits count as {tag}")
    name = the(on.name) if on else "that"
    return Row(refusal=f"Nothing comes of putting {_name(state, content, use)} and {name} together. You keep both.")


def _plan_open(state, content, view, use, target) -> Row | None:
    if target is None:
        return None
    if target.kind == "fixture" and target.key == "chest":
        if use.subject:
            return _on_fixture(state, content, use, target)
        if state.room.fixture_used:
            return Row(refusal="The chest is open already.")
        if state.room.monster and state.room.monster.hostile:
            return Row(refusal=f"Not with {the(state.room.monster.name)} at you.")
        return Row(alias="chest_key" if state.player.keys else "chest")
    if target.kind == "exit":
        if use.subject:
            return _on_exit(state, content, use, target)
        exit_ = state.room.exits[target.key]
        if exit_.webbed:
            return _web(state, content, target.key)
        if not exit_.locked:
            return Row(refusal=f"The {target.key} door stands open: go through it, if you like.")
        return Row(alias=f"go:{target.key}")  # (unlocked, if you've what opens it; if not, it says so)
    if target.kind == "feature":
        return _plan_search(state, content, view, use, target)
    return None


def _breach_row(state, content, direction: str, key: str = "") -> Row | None:
    """Breaking through a wall worth a bomb, without one: with something to swing (the tool named, else your weapon)."""
    if key and key not in content.items:
        return None
    item = content.item(key or state.player.weapon) if (key or state.player.weapon) in content.items else None
    if key and not (item.kind == "weapon" or {"heavy", "metal", "sharp"} & set(item.tags)):
        return None
    if state.room.monster and state.room.monster.hostile:
        return Row(refusal=f"Not with {the(state.room.monster.name)} at you.")
    swing = f" with {the(item.name)}" if item else ""
    return Row(alias=f"breach:{direction}" + (f":{key}" if key else ""),
               label=f"Smash through the {direction} wall{swing}", hint="might · hard · no bomb")


def _plan_smash(state, content, view, use, target) -> Row | None:
    if target is None:
        return None
    if target.kind == "wall" and use.subject != "bomb":
        return _breach_row(state, content, target.key, use.subject) or \
            Row(refusal=f"Nothing comes of {_name(state, content, use)} against the {target.key} wall.")
    if target.kind == "fixture" and target.key == "chest":
        if use.subject in ("bomb", "small_key"):
            return _on_fixture(state, content, use, target)
        if state.room.fixture_used:
            return Row(refusal="The chest is open already.")
        if state.room.monster and state.room.monster.hostile:
            return Row(refusal=f"Not with {the(state.room.monster.name)} at you.")
        return Row(alias="chest_smash")
    if target.kind == "exit":
        exit_ = state.room.exits[target.key]
        if exit_.webbed:
            return _web(state, content, target.key, use.subject)
        if use.subject == "bomb" or not exit_.locked:
            return _on_exit(state, content, use, target) if use.subject else \
                Row(refusal=f"The {target.key} door stands open: there's nothing to break.")
        boss_key = content.themes[state.theme].key_item
        needs = "a small key would open it, or two bombs break it" if exit_.key == "small_key" else \
            f"it needs {the(content.item(boss_key).name)}"
        how = f" with {_name(state, content, use)}" if use.subject else ""
        return Row(refusal=f"You bash at the {target.key} door{how}. It doesn't budge: {needs}.")
    if target.kind == "feature":
        return _plan_search(state, content, view, use, target)
    return None


def _plan_search(state, content, view, use, target) -> Row | None:
    if target is None or target.kind != "feature":
        return None
    feature = state.room.features[int(target.key)]
    if feature.searched:
        return Row(refusal=f"You've been through {the(target.name)} already: there's nothing more in it.")
    return Row(alias=f"search:{target.key}", label=f"Search {the(target.name)}")


def _plan_sell(state, content, view, use, target) -> Row | None:
    return Row(alias=f"sell:{use.subject}") if use.subject else None


PLANNERS = {"throw": _plan_throw, "give": _plan_give, "show": _plan_show, "pour": _plan_pour, "use": _plan_use,
            "open": _plan_open, "smash": _plan_smash, "search": _plan_search, "sell": _plan_sell}


# --- running a row ----------------------------------------------------------------------------------------------------

def perform(state: GameState, content: Content, rng: random.Random, use: Use, row: Row) -> tuple[list[Event], bool]:
    """Run a planned row (rules.perform does the aliases and the refusals): its events, and whether it took a turn."""
    return row.run(state, content, rng, use)


def _provoke(state: GameState, content: Content) -> list[Event]:
    """A hostile act on a creature that wasn't fighting you: it is now."""
    monster = state.room.monster
    if monster.hostile:
        return []
    monster.hostile = True
    return [provoked(monster, content)]


def _throw_at(state, content, rng, use):
    return _provoke(state, content) + throw(state, content, rng, use.subject), True


def _bomb_at(state, content, rng, use):
    return _provoke(state, content) + bomb_monster(state, content, rng), True


def _toss(state, content, rng, use):
    """Out of a fight, a thing thrown at nothing in particular lands here, there to take back."""
    player, item = state.player, content.item(use.subject)
    player.inventory.remove(use.subject)
    state.room.items.append(use.subject)
    return [Event("drop", f"You throw {the(item.name)} down. It lands at your feet.",
                  data={"quiet": True, **inventory.moved(use.subject, "throw", "pack", "room")})], False


def _bribe(state, content, rng, use):
    """A gift to stop a fight: a wits roll, better for what it's weak to (and found out), gold the more of it there
    is. It works, and it's handed over and the monster's talked down (flair for it); it doesn't, and you keep it."""
    player, monster = state.player, state.room.monster
    dc, tag = _bribe_dc(state, content, use, monster)
    amount = use.amount or bribe_gold(state)
    what = f"{amount} gold" if use.subject == "gold" else the(content.item(use.subject).name)
    name = "gold" if use.subject == "gold" else content.item(use.subject).name
    bonuses = [("wits", player.wits), (f"✦ {name}", 2)]
    if use.subject == "gold":
        bonuses.append(("more gold", min(4, amount // bribe_gold(state) - 1)))
    bonuses += powers.roll_bonuses(state, content, "talk")
    advantage = int(bool(tag) or "silver_tongue" in player.traits)
    talks = content.monster(monster.key).intelligent
    roll = dice.check(rng, "wits (bribe)" if talks else "wits (lure)", bonuses, dc, advantage=advantage)
    events = fortune(state, roll)
    if tag:
        events = discover(state, monster, tag) + events
    if not roll.success:
        refuse = "knocks it out of your hand" if talks else "snaps at your fingers"
        return [Event("check", f"You hold out {what} to {the(monster.name)}, but it {refuse}. You keep {what}.",
                      dice=roll, data={"success": False, "rerollable": True})] + events, True
    if use.subject == "gold":
        player.gold -= amount
        given = {"gold": amount, "how": "give", "from": "purse", "to": monster.key}
    else:
        given = inventory.give(state, use.subject, monster.key)
    took = "snatches it" if talks else "gobbles it up"
    done = [Event("check", f"You hold out {what} to {the(monster.name)}. It works: it {took}.", dice=roll,
                  data={"success": True, "rerollable": True, "props": [name], **given})]
    monster.hostile = False
    return done + events + flair(state) + defeat(state, content, rng, how="pacified"), True


def _trade(state, content, rng, use):
    """What a monster came for (MonsterDef.wants: the Sporefang Matriarch, the Ring), handed over. Cursed or not, it
    takes it, the fight's over (as if talked down), and it leaves what it had for you (gives) at your feet."""
    monster = state.room.monster
    known = content.monster(monster.key)
    thing, gift = content.item(use.subject), content.item(known.gives)
    given = inventory.give(state, use.subject, monster.key)
    name = cap(the(monster.name))
    events = [Event("trade", f"You hold out {the(thing.name)}. {name} goes still, every eye on it. It takes "
                             f"{the(thing.name)} from your hand so gently you hardly feel it, and the fight goes out of "
                             "it.", data={"props": [thing.name], **given})]
    monster.hostile = False
    events += defeat(state, content, rng, how="pacified")
    events.append(Event("drop", f"In its place, {the(monster.name)} leaves {a(gift.name)} at your feet.",
                        data=inventory.lay(state, gift.key, "drop", monster.key)))
    return events, True


def _npc_takes(state, content, rng, use):
    """A character takes what it wants (npcs.wants): Lenny his tooth, an angry Swoogy whatever calms him."""
    return npcs.take(state, content, rng, use.subject, use.amount), True


def _distract(state, content, rng, use):
    return distract(state, content, use.subject), True


def _quote(state, content, rng, use):
    """Show the shopkeeper something: what she'd give you for it (free)."""
    keeper = content.monster(state.room.shop.keeper).name
    item = content.item(use.subject)
    why = inventory.unsellable(state, content, use.subject)
    if why:
        return [Event("info", why, data={"quiet": True})], False
    price = inventory.sale_price(state, content, use.subject)
    return [Event("info", f"{keeper} squints at {the(item.name)}. \"I'd give you {price} gold for that, dearie.\"",
                  data={"quiet": True})], False


def _react(state, content, rng, use):
    """Show a calm creature something: it has a look (free)."""
    return npcs.shown(state, content, state.room.monster, use.subject), False


def _coat(state, content, rng, use):
    """Holy water or lamp oil on the weapon in your hand: its next few hits count as holy, or fire."""
    player = state.player
    item, weapon = content.item(use.subject), content.item(player.weapon)
    tag = RECIPES[(use.subject, "weapon")]
    used = inventory.consume(state, use.subject, "use")
    player.coating, player.coated = tag, COATS
    return [Event("coat", f"You pour {the(item.name)} over your {weapon.name}. It's {COATED[tag]}: its next "
                          f"{COATS} hits count as {tag}.", data=used)], True


def flair(state: GameState) -> list[Event]:
    """Using a real thing to change how things stand earns a soul and, with room for it, a Fate token."""
    player = state.player
    player.bump("flair")
    state.souls += 1
    if player.fate >= player.max_fate():
        return []
    player.fate += 1
    return [Event("fate", f"Style points! The dungeon rewards flair with a Fate token ({player.fate}/"
                          f"{player.max_fate()}).")]


# --- for the UI: each thing's verbs, and what a picker offers ------------------------------------------------------

def verbs(state: GameState, content: Content, ref_id: str) -> list[Action]:
    """What you can do with one thing right now, as engine actions, the most useful first: a Here tile's buttons, or
    an inventory tile's. Each id goes to rules.perform as it is, but a picker's (is_picker: "Give…" is
    give:@monster:lucky_lenny, "Use on…" use:holy_water@), which opens a picker of choices() instead. Only what would
    do something is offered (a picker, if anything in it would). Nothing, if it isn't here (or the game's over, or a
    perk's to be picked first)."""
    from .rules import available_actions, off_the_list

    if state.over or state.pending_perks:
        return []
    view = RoomView(state, content)
    ref = view.get(ref_id)
    if ref is None:
        return []
    listed = {a.id: a for a in available_actions(state, content)}
    out: list[Action] = []

    def offer(action_id: str, label: str, hint: str | None = None) -> None:
        """An engine action, if it can be taken now: a numbered choice, or one off the list."""
        if action_id not in {a.id for a in out} and (action_id in listed or off_the_list(state, content, action_id)):
            out.append(Action(action_id, label, listed[action_id].hint if hint is None and action_id in listed
                              else hint or ""))

    def picker(picker_id: str, label: str, covered: tuple[str, ...] = ()) -> None:
        """A picker, if anything in it would work that isn't offered already (`covered`: its subjects)."""
        options = [o for o in choices(state, content, picker_id)
                   if o.hint != NO and (parse(o.id) or Use("", o.id.partition(":")[2])).subject not in covered]
        if options:
            out.append(Action(picker_id, label, f"{len(options)} to pick from"))

    kind, key = ref.kind, ref.key
    if kind == "monster":
        named = {"lenny": "Turn in his tooth", "lenny_quest": "Take his quest", "lenny_hint": "Ask where it flew",
                 "lenny_reward": "Claim reward", "swoogy": "Play his game"}
        if ref.state["hostile"]:
            offer("lenny", named["lenny"])  # (hit, his tooth still calms Lenny down)
            offer("attack", "Attack")
            offer("burn", "Burn")
            picker(use_id("use", target=ref.id), "Use…")
            if ref.state["npc"]:  # (an angry Swoogy: what calms him)
                picker(use_id("give", target=ref.id), "Calm him down…" if key == npcs.SWOOGY else "Give…",
                       (npcs.BAD_TOOTH,) if "lenny" in listed else ())
        else:  # a character: what it's after, then talking, asking, giving; attacking it, last
            for action in npcs.actions(state, content):
                offer(action.id, named.get(action.id, action.label.removeprefix("Guess ")))
            offer(f"talk:{key}", "Talk")
            offer("ask", "Ask" if ref.state["intelligent"] else "Watch")
            if ref.state["npc"]:
                picker(use_id("give", target=ref.id), "Give…", (npcs.BAD_TOOTH,) if "lenny" in listed else ())
            offer("attack", "Attack")
    elif kind == "foe":  # (one of the others in the fight: turned to, it's the one your blows go to)
        offer(f"face:{key}", "Face it", "no turn")
    elif kind == "keeper":
        offer("shop", "Browse")
        offer(f"talk:{key}", "Talk")
        offer("ask", "Ask")
        picker(use_id("sell", target=ref.id), "Sell…")
    elif kind == "ware":
        offer(f"buy:{key}", "Buy", f"{ref.state['price']} gold")
        if not ref.state["haggled"]:
            offer(f"barter:{key}", "Haggle", "wits")
    elif kind == "floor":
        offer(f"take:{key}", "Take", "cursed!" if ref.state["cursed"] else "no turn")
        if content.item(key).kind in inventory.GEAR:
            offer(f"equip:{key}", "Equip", inventory.versus(state, content, key))
    elif kind == "feature":
        offer(f"burn:{key}", "Burn it open")
        offer(f"search:{key}", "Search")
    elif kind == "fixture":
        names = {"chest_key": "Unlock", "chest": "Pick the lock", "chest_smash": "Smash it open",
                 "chest_bomb": "Bomb it", "descend": "Descend", "shrine_pray": "Pray", "shrine_blood": "Offer blood",
                 "shrine_gold": "Offer gold", "fountain": "Drink", "shop": "Browse"}
        for action_id, label in names.items():
            offer(action_id, label)
    elif kind == "exit":
        offer(f"burn:{key}", "Burn the web")
        offer(f"go:{key}", "Unlock" if ref.state["locked"] else "Go")
        offer(f"bomb:{key}", "Bomb it")
    elif kind == "wall":
        offer(f"bomb:{key}", "Bomb it")
        if ref.state["draft"]:  # (a cracked wall: something heavy might do what a bomb would)
            offer(f"breach:{key}", "Smash through it")
    elif kind in ("item", "gear"):
        item = content.item(key)
        waiting = view.monster if kind == "item" and view.monster and view.monster.state["npc"] else None
        if waiting and npcs.wants(state, content, state.room.monster, key)[0] == "lenny":  # (what he's waiting for)
            row = plan(state, content, Use("give", key, waiting.id), view)
            if row and row.works:
                out.append(Action(use_id("give", key, waiting.id), f"Give it to {the(waiting.name)}", row.hint))
        for prefix, label in (("use", "Eat" if "food" in item.tags else "Drink" if item.heal else "Use"),
                              ("throw", "Throw"), ("distract", "Distract"), ("reveal", "Light it")):
            offer(f"{prefix}:{key}", label)
        if key == light.OIL or "torch" in item.powers:
            offer("refill", "Fill your torch" if key == light.OIL else "Fill it with oil")
        if kind == "item" and item.kind in inventory.GEAR:
            offer(f"equip:{key}", "Equip", inventory.versus(state, content, key))
        if kind == "gear" and ref.state["slot"] == "armor":
            offer("unequip:armor", "Take off")
        if not inventory.keeps(state, content, key) and key != (state.player.weapon if kind == "gear" else None):
            offer(f"drop:{key}", "Drop")
            if not inventory.unsellable(state, content, key):
                offer(f"sell:{key}", "Sell", f"{inventory.sale_price(state, content, key)} gold")
        if kind == "item":
            picker(use_id("give", key), "Give to…")
        picker(use_id("use", key), "Use on…")
    elif kind == "bombs":
        offer("bomb", "Throw")
        picker(use_id("use", key), "Use on…")
    elif kind == "keys":
        picker(use_id("use", key), "Use on…")
    elif kind == "gold":
        picker(use_id("give", key), "Give to…")
    elif kind == "self":
        picker(use_id("use", target="self"), "Use…")
    elif kind == "room":
        offer("search_room", "Search it")
        picker(use_id("use", target="room"), "Light it up…")
        offer("rest", "Rest")
    return out


NO = "won't work"  # a picker's hint for an option that's refused (it's still shown, greyed out)


def said(state: GameState, content: Content, action: Action) -> str:
    """How the story tells an option picked from a picker: as the whole use it is ("Throw the Healing Potion at the
    Lantern Moth", "Sell the Stale Bread for 5 gold"), not the thing it's listed by ("Healing Potion"). One that's
    neither, as it is."""
    from .rules import unlisted

    use = parse(action.id)
    row = plan(state, content, use, RoomView(state, content)) if use else None
    if row is not None and row.label:
        return row.label
    return next((a.label for a in unlisted(state, content) if a.id == action.id), action.label)


def choices(state: GameState, content: Content, picker_id: str) -> list[Action]:
    """What a picker offers: for "give:@monster:lucky_lenny", one Action for each thing you could give him (named by
    the thing: "Lenny's Bad Tooth", "10 gold"); for "use:holy_water@", one for each thing here you could use it on
    (named by what it'd do: "Throw the Vial of Holy Water at the Ghoul"). Each id is a whole use, for rules.perform.
    The ones that would work come first, their hint what they'd do; a picker of things also lists the rest after,
    their hint NO (a picker of targets leaves those out)."""
    use = parse(picker_id)
    if use is None or not is_picker(picker_id):
        return []
    view = RoomView(state, content)
    options: list[tuple[Use, str]] = []
    if not use.subject:
        if use.verb == "sell":
            hand = state.player.weapon if state.player.weapon not in state.player.inventory else ""
            return [Action(a.id, cap(a.label.removeprefix("Sell ").removeprefix("the ")), a.hint)
                    for a in inventory.moves(state, content)
                    if a.id.startswith("sell:") and a.id[5:] != hand and not inventory.unsellable(state, content,
                                                                                                   a.id[5:])]
        for ref in view.carried():
            if ref.kind == "gear" and (use.verb != "use" or use.target == "self"):
                continue
            label = f"{a(ref.name)}" if ref.kind in ("bombs", "keys") else "gold" if ref.kind == "gold" else ref.name
            options.append((Use(use.verb, ref.key, use.target), label))
    else:
        for ref in view.things() + view.of("self", "room", "gear", "item"):
            if ref.kind not in ("ware", "floor") and ref.key != use.subject:
                options.append((Use(use.verb, use.subject, ref.id, use.amount), ref.name))
    good, bad = [], []
    for option, label in options:
        row = plan(state, content, option, view)
        if row is None or (use.subject and not row.works):
            continue
        name = (row.label or cap(the(label))) if use.subject else cap(label)
        if not use.subject and option.subject == "gold" and row.works and " with " in row.label:
            name = row.label.rpartition(" with ")[2]  # ("10 gold": his price, or the least it'd take)
        action = Action(use_id(option.verb, option.subject, option.target, option.amount), cap(name),
                        (row.hint or "") if row.works else NO)
        (good if row.works else bad).append(action)
    return good + bad


# --- for the interpreter ------------------------------------------------------------------------------------------

def unlisted(state: GameState, content: Content) -> list[Action]:
    """What the grid can do here that the numbered choices don't offer, for the interpreter to match ("give the
    pickle to Swoogy", "pour the holy water on my sword"): gifts a character here would take, and coatings you could
    make."""
    if state.over or state.pending_perks:
        return []
    view = RoomView(state, content)
    out = []
    monster = view.monster
    if monster and monster.state["npc"]:
        for option in choices(state, content, use_id("give", target=monster.id)):
            row = plan(state, content, parse(option.id), view) if option.hint != NO else None
            if row and row.works:
                out.append(Action(option.id, row.label, row.hint))
    for (key, slot), _ in RECIPES.items():
        if key in state.player.inventory and slot == "weapon":
            row = plan(state, content, Use("pour", key, "gear:weapon"), view)
            if row and row.works:
                out.append(Action(use_id("pour", key, "gear:weapon"), row.label, row.hint))
    return out


def from_intent(state: GameState, content: Content, intent: Intent) -> str | None:
    """The engine action a creative intent really is, or None if it's a stunt the grid has no row for. Its verb,
    subject and target, if the interpreter gave them; else read from its words (read). Moving what you carry about
    (equip, drop...) or throwing a thing down only counts when nothing's at stake (no roll, no effects): "drop the
    bread" is a drop, but "toss my lucky foot over my shoulder for luck" is a stunt."""
    view = RoomView(state, content)
    calm = intent.difficulty == "trivial" or not intent.success_effects
    if intent.verb:
        use = Use(intent.verb, intent.subject, intent.target, intent.amount)
    else:
        use = read(view, intent.summary, moves=calm)
    if use is None:
        return None
    if use.verb in CARRY:
        return carry_id(state, content, use) if calm else None
    use = _aimed(state, view, use)
    if use is None or use.verb == "throw" and not use.target.startswith("monster:") and not calm:
        return None
    row = plan(state, content, use, view)
    if row is None:
        return None
    return use_id(use.verb, use.subject, use.target, use.amount)


def _aimed(state: GameState, view: RoomView, use: Use) -> Use | None:
    """A use said with nothing it's aimed at, aimed where it would be: a throw at whoever you're fighting (else it's
    thrown down here), a gift to whoever's here, a potion drunk. None if there's nowhere it could go."""
    if use.target or not use.subject:
        return use if use.target else None
    creature = view.monster or view.keeper
    if use.verb == "throw":
        aim = view.monster if state.in_combat and view.monster else view.get("room")
    elif use.verb in ("give", "show"):
        aim = creature
    elif use.verb in ("use", "pour"):
        aim = view.get("self")
    else:
        aim = None
    return Use(use.verb, use.subject, aim.id, use.amount) if aim else None


def carry_id(state: GameState, content: Content, use: Use) -> str | None:
    """A move with what you carry, as inventory.py's action: "equip:war_pick", "unequip:armor", "drop:stale_bread"."""
    key = use.subject
    if key not in content.items or key in inventory.PICKUPS:
        return None
    item = content.item(key)
    if use.verb == "equip":
        return f"equip:{key}" if item.kind in inventory.GEAR else None
    if use.verb == "unequip":
        return "unequip:armor" if key == state.player.armor else None
    return f"{use.verb}:{key}"


# --- reading a stunt's words ----------------------------------------------------------------------------------------

def forms(word: str) -> set[str]:
    """What a word might be at its root: "bribing" → bribe, "dropped" → drop, "emptied" → empty."""
    word = IRREGULAR.get(word, word)
    found = {word}
    for ending in ("ing", "ies", "ied", "es", "ed", "s"):
        if word.endswith(ending):
            stem = word[:-len(ending)]
            found |= {stem, stem + "e", stem[:-1], stem + "y"}
    return found


def verb_class(word: str) -> str:
    """What a verb comes to here (CLASSES), or ""."""
    roots = forms(word)
    return next((name for name, verbs in CLASSES.items() if roots & verbs), "")


@dataclass
class Clause:
    """A part of what's said: its verb (as said), the thing it's done to (its direct object, up to the first
    preposition) and the phrases after it, (preposition, words)."""

    verb: str
    particle: str
    obj: list[str]
    phrases: list[tuple[str, list[str]]]
    purpose: Clause | None = None  # "...to open the chest"

    def phrase(self, *preps: str) -> list[str]:
        return next((said for prep, said in self.phrases if prep in preps), [])

    def aimed(self) -> list[str]:
        """The words after the first preposition that aims it: "at the goblin", "in its face", "over the altar"."""
        return next((said for prep, said in self.phrases if prep in AIMED), [])


def clauses(summary: str) -> list[Clause]:
    """What's said, in its parts (BREAKS), each read from its verb: what follows "while" is only how it's done, and
    "to <verb>..." the reason ("throw the duck to distract the goblin")."""
    text = ATTEMPT.sub("", summary.strip().lower())
    out = []
    for chunk in re.split(r"[,;.!?]+", text):
        part: list[str] = []
        for word in re.findall(r"[a-z0-9]+(?:'[a-z]+)?", chunk) + ["and"]:
            if word in TAILS:
                break
            if word in BREAKS:
                if part:
                    out.append(_clause(part))
                part = []
            else:
                part.append(word)
        if part:
            out.append(_clause(part))
    return [c for c in out if c.verb]


def _clause(words_: list[str]) -> Clause:
    """One part of what's said, read from its first word: the verb, a particle straight after it ("throw away",
    "take off", "pry open"), what it's done to and the phrases after that."""
    if words_[:1] == ["i"]:
        words_ = words_[1:]
    if not words_:
        return Clause("", "", [], [])
    verb, rest = words_[0], words_[1:]
    particle = ""
    if rest[:1] and rest[0] in PARTICLES:
        particle, rest = rest[0], rest[1:]
    purpose = None
    for i, word in enumerate(rest):  # "to" and a verb: the reason for it
        if word == "to" and i + 1 < len(rest) and (verb_class(rest[i + 1]) or rest[i + 1] in ("lure", "bait")):
            purpose, rest = _clause(rest[i + 1:]), rest[:i]
            break
    obj: list[str] = []
    phrases: list[tuple[str, list[str]]] = []
    for word in rest:
        if word in PREPOSITIONS:
            phrases.append((word, []))
        elif phrases:
            phrases[-1][1].append(word)
        else:
            obj.append(word)
    return Clause(verb, particle, obj, phrases, purpose)


def read(view: RoomView, summary: str, moves: bool = True) -> Use | None:
    """What a stunt's words come to on the grid, if they're plainly one use: one part (and maybe its reason), its verb
    one the grid knows, and what it names really here. None for anything else: two things at once, a verb that's a
    stunt ("topple", "jingle"), or nothing real named ("throw sand at its eyes": you have no sand). Only the thing the
    verb is done to is what's used: "throw sand at the rat's eyes" never reads your Pizza Rat, "rub the key and jingle
    it" never gives the key away. `moves`: read moves with what you carry ("drop the bread") too."""
    said = clauses(summary)
    if moves:
        for clause in said:
            move = _carry_move(view, clause)
            if move:
                return move
    if len(said) != 1:
        return None
    clause = said[0]
    kind = verb_class(clause.verb)
    if clause.purpose is not None:
        aim = verb_class(clause.purpose.verb)
        if aim in ("distract", "open", "smash", "search") and kind in ("throw", "use", "show", "pour", "open", ""):
            subject = _subject(view, clause.obj)
            aimed = clause.purpose.obj or clause.purpose.aimed()
            target = _target(view, aimed, "show" if aim == "distract" else "open")
            if subject and target:
                verb = "show" if aim == "distract" else aim
                return Use(verb, subject.key, target.id, amount_said(clause.obj))
        return None
    if kind in ("throw", "pour", "show", "use", "eat", "distract"):
        reversed_ = kind == "pour" and forms(clause.verb) & REVERSED and clause.phrase("in", "into", "with")
        if reversed_:  # "coat the blade in holy water", "dip the sword in the oil"
            subject = _subject(view, clause.phrase("in", "into", "with"))
            target = _target(view, clause.obj, "pour")
            return Use("pour", subject.key, target.id) if subject and target else None
        verb = {"eat": "use", "distract": "show"}.get(kind, kind)
        aimed = clause.aimed()
        both = verb == "show" and not aimed  # "show Lenny the tooth": who it's shown to, and what, in one
        subject = _subject(view, _besides(clause.obj, _target(view, clause.obj, "show")) if both else clause.obj)
        if subject is None:
            return None
        if kind == "eat":
            target = view.get("self")
        elif aimed:  # (aimed at something the grid doesn't know: "pour it over the altar", with no altar, is a stunt)
            target = _target(view, aimed, verb)
            if target is None and kind != "throw":
                return None
        else:  # "show Lenny the tooth"; or nothing said, and it goes where it would (_aimed)
            target = _target(view, clause.obj, "show") if verb == "show" else None
        return Use(verb, subject.key, target.id if target else "", amount_said(clause.obj))
    if kind == "give":
        return _read_give(view, clause)
    if kind == "burn":  # your torch on it, named or not ("burn the cocoon open", "singe the cap with the torch")
        target = _target(view, clause.obj, "use") or _target(view, clause.aimed(), "use")
        lamp = light.torch(view.state, view.content)
        tool = _subject(view, clause.phrase("with", "using")) or (view.get(f"item:{lamp.key}") if lamp else None)
        return Use("use", tool.key, target.id) if tool and target and target.kind in ("monster", "feature") else None
    if kind in ("open", "smash", "search", "bomb"):
        target = _target(view, clause.obj, "open") or _target(view, clause.aimed(), "open")
        if target is None or target.kind in ("monster", "keeper", "self"):
            return None
        if any(view.match(set(words(" ".join(w))), ("monster",)) for _, w in clause.phrases):
            return None  # (knocking it over onto the goblin is a stunt)
        tool = _subject(view, clause.phrase("with", "using"))
        if kind == "bomb":
            return Use("use", "bomb", target.id) if view.get("bombs") else None
        if kind == "open" and clause.verb == "pick" and clause.particle == "up":
            return None
        return Use(kind, tool.key if tool else "", target.id)
    return None


def _read_give(view: RoomView, clause: Clause) -> Use | None:
    """"give the bread to the orc", "give the orc the bread", "bribe the orc with the bread", "offer 30 gold"."""
    to = clause.phrase("to")
    with_ = clause.phrase("with", "using")
    if with_:  # "bribe the orc with the bread": the one bribed, then what with
        subject, target = _subject(view, with_), _target(view, clause.obj, "give")
        amount = amount_said(with_)
    elif to:
        subject, target = _subject(view, clause.obj), _target(view, to, "give")
        amount = amount_said(clause.obj)
    else:  # "give the ghoul the cheese", "pay him 10 gold": both in one
        target = _target(view, clause.obj, "give")
        subject = _subject(view, _besides(clause.obj, target))
        amount = amount_said(clause.obj)
    if subject is None:
        return None
    return Use("give", subject.key, target.id if target else "", amount)


def _besides(said: list[str], ref: Ref | None) -> list[str]:
    """Some words without those that name `ref`: what's handed to Lenny is named by more than "lenny" ("give lenny a
    hug" hands him no Lenny's Bad Tooth)."""
    return [w for w in said if not words(w) & ref.words()] if ref else said


def _subject(view: RoomView, said: list[str]) -> Ref | None:
    """What you use, from what you carry, named in some words."""
    if not said:
        return None
    found = view.match(set(words(" ".join(said))), ("gear", "item", "bombs", "keys", "gold"))
    return found


AIMS = {  # what each kind of verb may be aimed at
    "throw": ("monster", "keeper", "feature", "fixture", "exit", "wall", "room"),
    "give": ("monster", "keeper", "fixture", "self"),
    "show": ("monster", "keeper"),
    "pour": ("monster", "keeper", "gear", "item", "feature", "fixture", "self"),
    "use": ("monster", "keeper", "gear", "item", "feature", "fixture", "exit", "wall", "self", "room"),
    "open": ("fixture", "feature", "exit", "wall"),
}


def _target(view: RoomView, said: list[str], kind: str = "use") -> Ref | None:
    """What it's aimed at, of what a `kind` of verb may be aimed at (AIMS), named in some words."""
    if not said:
        return None
    return view.match(set(words(" ".join(said))), AIMS.get(kind, AIMS["open"]))


def amount_said(said: list[str]) -> int:
    """How much gold some words say: "30 gold" is 30, "ten coins" 10, "gold" nothing in particular (0)."""
    for i, word in enumerate(said):
        if i + 1 < len(said) and forms(said[i + 1]) & {"gold", "coin", "piece"}:
            if word.isdigit():
                return int(word)
            if word in NUMBERS:
                return NUMBERS[word]
    return 0


TAIL_PARTICLES = {"on", "off", "down", "away"}  # a phrasal verb's last word, said after the thing: "put the vest on"
FILLER = {"here", "there", "now", "too", "back", "again"}  # words with a thing that don't make it another thing


def _carry_move(view: RoomView, clause: Clause) -> Use | None:
    """The move with what you carry a part of what's said is (CARRY_MOVES): its verb (with its particle, before the
    thing or after it) a move's, and the thing it's done to something you carry, and nothing else: "drop the bread",
    "take the chain shirt off", "toss the bread away into the corner", "get rid of the bread". Not "leave the room
    with the war pick" (the room isn't yours), "wear a grin", "remove the cobwebs from the chain shirt", nor "leave
    the chain shirt on"."""
    roots = forms(clause.verb)
    obj = list(clause.obj)
    said = set(roots) | ({f"{root} {clause.particle}" for root in roots} if clause.particle else set())
    if clause.verb == "get" and obj[:2] == ["rid", "of"]:
        said.add("get rid")
        obj = obj[2:]
    tail = ""
    if obj and obj[-1] in TAIL_PARTICLES:  # "toss the bread away (into the corner)", "put the bread down"
        tail, obj = obj[-1], obj[:-1]
    elif clause.phrases and not clause.phrases[-1][1] and clause.phrases[-1][0] in TAIL_PARTICLES:
        tail = clause.phrases[-1][0]  # "put the vest on", "take the chain shirt off"
    said |= {f"{root} {tail}" for root in roots} if tail else set()
    for move, verbs_ in CARRY_MOVES.items():
        if not verbs_ & said or (move == "drop" and tail == "on"):
            continue
        named = words(" ".join(obj))
        thing = view.match(named, ("gear", "item", "floor") if move == "equip" else ("gear", "item")) if obj else None
        if thing is None or named - thing.words() - FILLER:
            continue
        return Use(move, thing.key)
    return None


HANDING = {"give", "offer", "bribe", "feed", "trade", "pay", "lure", "bait"}  # done to someone, with what's handed over


def spent_by(view: RoomView, summary: str, spending: set[str]) -> list[str]:
    """What a stunt's words use up of what's in your pack: the thing a `spending` verb is done to ("throw the bread at
    the wall"), or what's handed over to someone ("bribe the orc with the bread", "lure it with the cheese"); never a
    word that merely turns up ("throw sand at the rat's eyes" spends no Pizza Rat, "jingle the key to lure the goblin"
    no key), nor a tool ("burn the cobwebs with the torch"). Item keys, and "gold"."""
    found = []
    for clause in clauses(summary):
        roots = forms(clause.verb)
        if not roots & spending:
            continue
        thing = _subject(view, clause.obj) or (_subject(view, clause.phrase("with")) if roots & HANDING else None)
        if thing and thing.kind in ("item", "gold") and thing.key not in found:
            found.append(thing.key)
    return found
