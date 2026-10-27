"""What you carry, and every way a thing changes hands: what comes your way (picked up, found, bought, given, won),
and what you drop, equip, take off, hand over, sell or use up. Each move is told the same way, as an Event whose data
says what moved where, so the story's cards and the narrator hear of every one alike:

    {"item": "war_pick", "how": "take", "from": "room", "to": "pack", "slot": "", "replaced": ""}

    how       take, find, buy, give, win, story, drop, equip, unequip, sell, use, throw, spend, steal, lose
    from, to  room (lying where you are), pack, weapon or armor (in your hand, on your back), counter (bombs and small
              keys), shop, gone (used up), or whoever had it or gets it (a monster's key, a feature's name)
    slot      weapon or armor, when it goes on or comes off; replaced, what it took the place of

Gear you gain goes in your pack, never on the floor. It goes on by itself only into an empty slot (that's armor, when
you wear none: there's always a weapon in your hand), and never when it's cursed. Better gear in your pack is a free
choice, "Equip the War Pick (1d6 → 1d10)  [replaces Rusty Sword · no turn]", and what it replaces goes in your pack;
any other piece can be put on too, by saying so. A weapon's or armor's powers and stats count only while it's on
(powers.carried).

Finds lie where they turn up (a feature you search, a chest, a monster's body, Swoogy's game), to take one by one or
all at once, or leave; bombs and small keys go on their counters as soon as there's no fight (rules.collect). What
you put down yourself stays where you leave it, and no choice keeps offering it back.

Cursed things stick: once yours, they can't be dropped, sold, handed over or used up, nor taken off once worn, until a
shrine lifts the curse. Taking one warns you first, so you can leave it, and picking up everything here never takes
one: it's taken only on its own.

Shopkeepers buy anything of yours for half what they'd ask, but not a key, nor a quest's things (Lenny's teeth,
Swoogy's diaper), nor anything cursed, nor the weapon in your hand (take up another first).

Said of something you haven't got ("wield the snitch"), any of these moves only tells you so (nothing_like).
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from . import dice, loot, powers
from .events import Action, Event
from .text import cap, the

if TYPE_CHECKING:
    from .content import Content
    from .models import GameState, Room

PICKUPS = {"bomb": "bombs", "small_key": "keys"}  # gained, they go on a counter rather than in your pack
GEAR = powers.GEAR
SELL_SHARE = 0.5  # what a shopkeeper pays for a thing of yours: half what she'd ask for it
# Saying you leave a thing you carry (drop), for the interpreter and a creative attempt alike
# (interactions.CARRY_MOVES): it stays where you leave it, not used up.
DROP_WORDS = {"drop", "discard", "ditch", "dump", "leave", "put down", "set down", "throw away", "toss away", "get rid"}


def moved(key: str, how: str, source: str, to: str, slot: str = "", replaced: str = "") -> dict:
    """An item's move, as its event's data (see the module's docstring)."""
    return {"item": key, "how": how, "from": source, "to": to, "slot": slot, "replaced": replaced}


# --- what you have on, and how gear compares ------------------------------------

def worn(state: GameState, slot: str) -> str | None:
    """What's in a gear slot: the weapon in your hand, or the armor on your back (None for none)."""
    return state.player.weapon if slot == "weapon" else state.player.armor


def sticky(state: GameState, content: Content, key: str) -> bool:
    """Whether it's cursed, and the curse not lifted: once yours, it won't leave you."""
    return "cursed" in powers.powers_of(state, content.item(key))


def keeps(state: GameState, content: Content, key: str) -> str:
    """Why you won't part with something (drop it, hand it over, use it up), or "" if you would: a curse, or a key or
    what a character's waiting for (npcs.needed: a run could hang on it)."""
    from . import npcs

    name = content.item(key).name
    if sticky(state, content, key):
        return f"{cap(the(name))} won't leave you: it's cursed. Praying at a shrine would lift the curse."
    if npcs.needed(state, content, key):
        return f"You'll be needing {the(name)}: you keep hold of it."
    return ""


def rating(state: GameState, content: Content, key: str) -> float:
    """How good a piece of gear is, beside another of its kind: its average damage (a weapon) or its defense (armor),
    and half a point for each power and each point it adds to your stats (five max HP count as one). A curse costs
    five."""
    item = content.item(key)
    shown = powers.powers_of(state, item)
    base = dice.average(item.damage) if item.kind == "weapon" else item.defense
    stats = sum(change / 5 if stat == "max_hp" else change for stat, change in item.stats.items())
    return base + 0.5 * (len([p for p in shown if p != "cursed"]) + len(item.wards) + stats) - 5 * ("cursed" in shown)


def gear_words(state: GameState, content: Content, key: str) -> str:
    """A piece of gear in a few words: "1d10", "1d8+1 & goblin-bane", "+2"."""
    item = content.item(key)
    base = item.damage if item.kind == "weapon" else f"+{item.defense}"
    return " & ".join([base] + [powers.SHORT[p] for p in powers.powers_of(state, item) if p in powers.SHORT]
                      + powers.ward_words(item))


def versus(state: GameState, content: Content, key: str) -> str:
    """How a piece of gear compares with what you have on in its slot, the numbers first (they're what's cut short
    in a narrow choices box): "1d6 → 1d10", "+1 → +2 defense", or, the slot empty, what it gives: "+2 defense"."""
    item = content.item(key)
    new = gear_words(state, content, key)
    if item.kind == "armor":
        base = f"+{item.defense}"
        new = new.replace(base, f"{base} defense", 1)
    current = worn(state, item.kind)
    if current is None:
        return new
    return f"{gear_words(state, content, current)} → {new}"


def upgrade(state: GameState, content: Content, key: str) -> bool:
    """Whether a piece of gear beats what you have on in its slot (anything does, in an empty one, unless it's
    cursed)."""
    item = content.item(key)
    current = worn(state, item.kind)
    if current is None:
        return not sticky(state, content, key)
    return key != current and rating(state, content, key) > rating(state, content, current)


# --- coming your way --------------------------------------------------------------

def gain(state: GameState, content: Content, key: str, how: str = "take", source: str = "room", says: str = "",
         kind: str = "") -> list[Event]:
    """Something comes your way: onto its counter (a bomb, a small key), into your pack, or, gear for an empty slot,
    straight on. `says` is how it's told, when that isn't "You take X" (a purchase, with its price); `kind`, the
    event's kind, when that isn't where it went (take, equip, key)."""
    player, item = state.player, content.item(key)
    lead = says or f"You take {the(item.name)}"
    if key in PICKUPS:
        fairy = powers.holders(state, content, "twin_bombs") if key == "bomb" else []
        count = getattr(player, PICKUPS[key]) + 1 + bool(fairy)
        setattr(player, PICKUPS[key], count)
        tally = f", and have {count} now." if says else f" ({count} now)."  # (a price says "(88 left)" already)
        if fairy:  # (a bomb found, bought or won)
            tally = f". {cap(the(fairy[0].name))} cackles and makes it two" + tally.replace(", and have", ": you have")
        return [Event(kind or "take", lead + tally, data=moved(key, how, source, "counter"))]
    if item.kind in GEAR and worn(state, item.kind) is None and not sticky(state, content, key):
        gives = versus(state, content, key)
        setattr(player, item.kind, key)
        on = "put it on" if item.kind == "armor" else "take it in hand"
        return [Event(kind or "equip", f"{lead} and {on} ({gives}).",
                      data=moved(key, how, source, item.kind, slot=item.kind))]
    player.inventory.append(key)
    data = moved(key, how, source, "pack")
    if item.kind in GEAR:
        stat = "" if says else f" ({gear_words(state, content, key)})"
        return [Event(kind or "take", f"{lead}{stat} and put it in your pack.", data=data)]
    if item.kind == "key":
        return [Event(kind or "key", f"{lead}. It must open something important.", data=data)]
    events = [Event(kind or "take", f"{lead}.", data=data)]
    if "mapper" in item.powers and state.mapped_floor != state.floor:
        state.mapped_floor = state.floor
        events.append(Event("map", f"Somehow {the(item.name)} puts the whole floor in your head: every room is on "
                                   "your map now."))
    return events


def lay(state: GameState, key: str, how: str, source: str) -> dict:
    """A find or a drop, lying where you are to take or leave: the move, for its event's data. (Bombs and small keys
    go on their counters once there's no fight: rules.collect.)"""
    state.room.items.append(key)
    return moved(key, how, source, "room")


def takeable(room: Room) -> list[str]:
    """What's lying here for the taking as the choices go: not what you put down here yourself (that's still yours to
    take, by its card or by saying so)."""
    mine = Counter(room.left)
    out = []
    for key in room.items:
        if mine[key]:
            mine[key] -= 1
        else:
            out.append(key)
    return out


def off_the_floor(room: Room, key: str) -> None:
    """One of `key` gone from where it lay (and from what you put down there, once there's less of it than that)."""
    room.items.remove(key)
    if room.left.count(key) > room.items.count(key):
        room.left.remove(key)


def take(state: GameState, content: Content, key: str) -> list[Event]:
    """Pick up one thing lying here (free). A cursed thing only warns you, the first time: take it again to keep it."""
    room = state.room
    if sticky(state, content, key) and key not in state.warned:
        state.warned.append(key)
        return [Event("warn", warning(content, key), data={"item": key})]
    off_the_floor(room, key)
    return gain(state, content, key, "take", "room")


def warning(content: Content, key: str) -> str:
    """What you're told before you take something cursed."""
    item = content.item(key)
    gear = item.kind in GEAR
    nots = "sold, given away or taken off" if gear else "sold or given away"
    return (f"{cap(the(item.name))} is cursed! Once it's yours it won't leave you: it can't be dropped, {nots} until a "
            f"shrine lifts the curse, and the stairs take 2 of your most HP each time you go down them with it"
            f"{' on' if gear else ''}. Take it anyway, or leave it where it is.")


def take_all(state: GameState, content: Content) -> list[Event]:
    """Pick up everything lying here that the choices offer: not what you put down yourself, and never anything
    cursed, warned of or not (that's taken only on its own: take)."""
    events = []
    for key in takeable(state.room):
        if not sticky(state, content, key):
            events += take(state, content, key)
    return events


# --- what you do with what you have ---------------------------------------------

def equip(state: GameState, content: Content, key: str) -> list[Event]:
    """Put on a piece of gear from your pack, or take it in hand: what it replaces goes in your pack. Gear lying here
    is picked up first (out of a fight)."""
    player, item = state.player, content.item(key)
    slot = item.kind
    if slot in GEAR and key == worn(state, slot):
        return [Event("info", f"You have {the(item.name)} {'in hand' if slot == 'weapon' else 'on'} already.")]
    if key not in player.inventory and key in state.room.items and slot in GEAR and not state.in_combat:
        taken = take(state, content, key)
        if key not in player.inventory:  # a curse's warning, or it went straight on
            return taken
        return taken + equip(state, content, key)
    if key not in player.inventory:
        return [Event("info", f"You have no {item.name}.")]
    if slot not in GEAR:
        return [Event("info", f"{cap(the(item.name))} isn't something to equip.")]
    current = worn(state, slot)
    if current and sticky(state, content, current):
        return [Event("info", f"Your {content.item(current).name} won't come off: it's cursed. Praying at a shrine "
                              "would lift the curse.")]
    player.inventory.remove(key)
    setattr(player, slot, key)
    if current:
        player.inventory.append(current)
    on = (f"You take {the(item.name)} in hand ({item.damage})" if slot == "weapon"
          else f"You put on {the(item.name)} (+{item.defense} defense)")
    old = f" and put your {content.item(current).name} in your pack" if current else ""
    stuck = " It's cursed: it won't come off until a shrine lifts the curse." if sticky(state, content, key) else ""
    return [Event("equip", f"{on}{old}.{stuck}", data=moved(key, "equip", "pack", slot, slot=slot,
                                                          replaced=current or ""))]


def unequip(state: GameState, content: Content, slot: str) -> list[Event]:
    """Take off your armor, into your pack. (A weapon isn't taken off: there's always one in your hand. Take up
    another instead.)"""
    player = state.player
    key = player.armor if slot == "armor" else None
    if key is None:
        return [Event("info", "You can't do that right now.")]
    name = content.item(key).name
    if sticky(state, content, key):
        return [Event("info", f"{cap(the(name))} won't come off: it's cursed. Praying at a shrine would lift the "
                              "curse.")]
    player.armor = None
    player.inventory.append(key)
    return [Event("unequip", f"You take off {the(name)} and put it in your pack.",
                  data=moved(key, "unequip", "armor", "pack", slot="armor"))]


def drop(state: GameState, content: Content, key: str) -> list[Event]:
    """Leave something you carry here (free, and not in a fight): from your pack, or the armor off your back. Not a
    key, nor what a character's waiting for, nor anything cursed; and not the weapon in your hand (take up another
    first)."""
    player, room = state.player, state.room
    name = content.item(key).name
    if state.in_combat:
        return [Event("info", "Not in the middle of a fight.")]
    source = "pack" if key in player.inventory else "armor" if key == player.armor else ""
    if not source:
        if key == player.weapon:
            return [Event("info", f"You'd have nothing to fight with: take up another weapon before you leave "
                                  f"{the(name)} anywhere.")]
        return [Event("info", f"You have no {name}.")]
    why = keeps(state, content, key)
    if why:
        return [Event("info", why)]
    if source == "pack":
        player.inventory.remove(key)
        text = f"You leave {the(name)} here."
    else:
        player.armor = None
        text = f"You take off {the(name)} and leave it here."
    room.items.append(key)
    room.left.append(key)
    return [Event("drop", text, data=moved(key, "drop", source, "room", slot="armor" if source == "armor" else ""))]


def give(state: GameState, key: str, to: str, how: str = "give") -> dict:
    """Hand something from your pack to someone (`to`, their key): it's theirs now. The move, for its event's data.
    (Whether you would is the caller's to ask: see keeps.)"""
    state.player.inventory.remove(key)
    return moved(key, how, "pack", to)


def consume(state: GameState, key: str, how: str = "use", source: str = "pack") -> dict:
    """Use something up (drunk, eaten, thrown, spent), from your pack or lying here: it's gone. The move, for its
    event's data."""
    if source == "room":
        off_the_floor(state.room, key)
    else:
        state.player.inventory.remove(key)
    return moved(key, how, source, "gone")


def lose(state: GameState, content: Content, key: str) -> tuple[dict | None, str]:
    """Something taken off you (a story's [take]): from your pack first, then your back, a counter, or your hand, if
    there's another weapon in your pack to take up instead. The move (None if you had none to lose), and a note."""
    player, name = state.player, content.item(key).name
    if key in player.inventory:
        player.inventory.remove(key)
        return moved(key, "lose", "pack", "gone"), f"lost {the(name)}"
    if key in PICKUPS and getattr(player, PICKUPS[key]):
        setattr(player, PICKUPS[key], getattr(player, PICKUPS[key]) - 1)
        return moved(key, "lose", "counter", "gone"), f"lost {the(name)}"
    if key == player.armor:
        player.armor = None
        return moved(key, "lose", "armor", "gone", slot="armor"), f"lost {the(name)}"
    spares = [k for k in player.inventory if content.item(k).kind == "weapon"]
    if key == player.weapon and spares:
        spare = max(spares, key=lambda k: rating(state, content, k))
        player.inventory.remove(spare)
        player.weapon = spare
        return (moved(key, "lose", "weapon", "gone", slot="weapon"),
                f"lost {the(name)}, and took up {the(content.item(spare).name)}")
    if key == player.weapon:
        return None, f"kept {the(name)}: it's the only weapon you have"
    return None, f"you had no {name} to lose"


def sale_price(state: GameState, content: Content, key: str) -> int:
    """What the shopkeeper here would pay for something of yours: half what she'd ask."""
    shiny = state.room.shop is not None and state.room.shop.keeper == loot.SHINY
    return max(1, int(loot.price(content.item(key), state.floor, shiny) * SELL_SHARE))


def unsellable(state: GameState, content: Content, key: str) -> str:
    """Why the shopkeeper here won't buy something of yours, or "" if she would: a key, a quest's things (Lenny's
    teeth, Swoogy's diaper), a curse."""
    item = content.item(key)
    quest = "quest" in item.found or any(p in content.monsters and content.monster(p).npc for p in item.found)
    if item.kind == "key" or quest:
        keeper = content.monster(state.room.shop.keeper).name if state.room.shop else "She"
        return f"{keeper} pushes {the(item.name)} back across the counter: \"You'll be wanting that, dearie.\""
    return keeps(state, content, key)


def sell(state: GameState, content: Content, key: str) -> list[Event]:
    """Sell something from your pack, or the armor off your back, at a shop, for half what she'd ask for it. (Not the
    weapon in your hand: take up another first.)"""
    player, shop = state.player, state.room.shop
    name = content.item(key).name
    source = "pack" if key in player.inventory else "armor" if key == player.armor else ""
    if shop is not None and not source and key == player.weapon:
        keeper = content.monster(shop.keeper).name
        return [Event("info", f"{keeper} won't take {the(name)} out of your hand. Take up another weapon first.",
                      data={"quiet": True})]
    if shop is None:
        return [Event("info", "There's no one here to sell anything to.", data={"quiet": True})]
    if not source:
        return [Event("info", f"You have no {name}.", data={"quiet": True})]
    why = unsellable(state, content, key)
    if why:
        return [Event("info", why, data={"quiet": True})]
    price = sale_price(state, content, key)
    if source == "pack":
        player.inventory.remove(key)
    else:
        player.armor = None
    player.gold += price
    keeper = content.monster(shop.keeper).name
    return [Event("sell", f"{keeper} gives you {price} gold for {the(name)} ({player.gold} gold now).",
                  data=moved(key, "sell", source, "shop", slot="armor" if source == "armor" else ""))]


def lift_curses(state: GameState, content: Content) -> list[str]:
    """A shrine's blessing: the curse is lifted from everything cursed you carry (it's yours to keep, or leave, now, and
    does the rest of what it does). The names of what it lifted."""
    cursed = [k for k in carried_keys(state) if sticky(state, content, k)]
    state.player.lifted += cursed
    return [content.item(k).name for k in cursed]


def carried_keys(state: GameState) -> list[str]:
    """Everything you carry, on you or in your pack, each once."""
    player = state.player
    return list(dict.fromkeys(k for k in [player.weapon, player.armor, *player.inventory] if k))


# --- the choices -------------------------------------------------------------------

def choices(state: GameState, content: Content) -> list[Action]:
    """The numbered choices for what you carry, out of a fight: the best piece of gear in your pack for each slot,
    when it beats what you have on (or anything not cursed, for an empty slot). Free. The numbers come first, so a
    narrow choices box cuts off what it replaces (the hint), not by how much: "Equip the War Pick (1d6 → 1d10)
    [replaces Rusty Sword · no turn]"."""
    if state.in_combat:
        return []
    player, actions = state.player, []
    for slot in GEAR:
        better = [k for k in dict.fromkeys(player.inventory) if content.item(k).kind == slot
                  and upgrade(state, content, k)]
        if better:
            best, current = max(better, key=lambda k: rating(state, content, k)), worn(state, slot)
            hint = f"replaces {content.item(current).name} · no turn" if current else "no turn"
            actions.append(Action(f"equip:{best}", f"Equip {the(content.item(best).name)} "
                                                   f"({versus(state, content, best)})", hint))
    return actions


WORN = {"weapon": "in hand", "armor": "worn"}  # how moves marks what you have on: "Drop the Chain Shirt (worn)"


def moves(state: GameState, content: Content) -> list[Action]:
    """What you can do with what you carry that isn't a numbered choice, for the interpreter to match ("wield the hand
    axe", "take off the chain shirt", "drop the bread", "sell my armor") and the panels to offer: put on any gear in
    your pack (in a fight too, for a turn) or lying here, take off your armor; out of a fight, leave anything here;
    and at a shop, sell it. What you have on is listed too, marked "(in hand)" or "(worn)", and some will only say why
    not (it's on already, a key, a curse, the only weapon you have)."""
    player, actions = state.player, []
    pack = [(k, "") for k in dict.fromkeys(player.inventory)]
    lying = [] if state.in_combat else [(k, "") for k in dict.fromkeys(state.room.items) if k not in player.inventory]
    on = [(key, f" ({WORN[slot]})") for slot, key in (("weapon", player.weapon), ("armor", player.armor)) if key]
    for key, mark in pack + lying + on:
        if content.item(key).kind in GEAR:
            actions.append(Action(f"equip:{key}", f"Equip {the(content.item(key).name)}{mark}"))
    if player.armor:
        actions.append(Action("unequip:armor", f"Take off {the(content.item(player.armor).name)}"))
    if state.in_combat:
        return actions
    for key, mark in pack + on:
        actions.append(Action(f"drop:{key}", f"Drop {the(content.item(key).name)}{mark}"))
    if state.room.shop:  # (her name's in the hint, not the label: "to Granny Gristle" matched every sale)
        keeper = content.monster(state.room.shop.keeper).name
        for key, mark in pack + on:
            actions.append(Action(f"sell:{key}", f"Sell {the(content.item(key).name)}{mark}",
                                  f"{sale_price(state, content, key)} gold from {keeper}"))
    return actions


def nothing_like(state: GameState, content: Content, verb: str) -> list[Event]:
    """What you're told when you'd equip, take off, drop or sell something you haven't got (the interpreter knew the
    verb, "wield the snitch", but nothing you carry by that name): free, and nothing changes."""
    player, pack = state.player, list(dict.fromkeys(state.player.inventory))
    if verb == "equip":
        spares = [the(content.item(k).name) for k in pack if content.item(k).kind in GEAR]
        text = f"Equip which? In your pack: {listing(spares)}." if spares else \
            "You've no other weapon or armor to equip."
    elif verb == "unequip":
        text = (f"Only armor comes off, and yours is {the(content.item(player.armor).name)}." if player.armor
                else "You've no armor on to take off.") + " A weapon stays in your hand till you take up another."
    elif verb == "drop":
        text = "Not in the middle of a fight." if state.in_combat else "You carry nothing like that."
    elif state.room.shop:
        wanted = [f"{the(content.item(k).name)} ({sale_price(state, content, k)} gold)" for k in pack
                  if not unsellable(state, content, k)]
        keeper = content.monster(state.room.shop.keeper).name
        text = f"{keeper} looks you over. " + (f"She'd buy {listing(wanted, 'or')}." if wanted
                                                else "You've nothing she'd buy.")
    else:
        text = "There's no one here to sell anything to."
    return [Event("info", text)]


def listing(names: list[str], last: str = "and") -> str:
    """"the War Pick, the Hand Axe and the Chain Shirt"."""
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} {last} {names[-1]}"
