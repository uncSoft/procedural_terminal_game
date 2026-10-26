"""Hazards: what a floor with poison of its own (Norfell) has waiting in its doorways and its rooms, after Metroid's
Norfair (docs/plans/floor-4-and-statuses.md §3.1).

    a poison puddle across a doorway   jump it going through (agility), or land in it: poisoned
    a poison river across a room       cross it coming in (agility, harder), or slip in: poisoned
    a gas vent in a room's floor       unseen, it catches you coming in unless you spot it in time (wits); seen, you
                                       walk wide of it, but there's no resting beside it until it's disarmed (wits,
                                       and a ten-foot pole's care helps: XP for it, and a failed try poisons you)

Each is a roll every time you come through (a vent's, until it's seen). Already poisoned, there's nothing more for it
to do to you, so there's no roll. A guard (Pure) stops what would have poisoned you. Quick travel crosses them all on
the way, room by room.
"""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

from . import dice, powers, statuses
from .events import Event
from .models import OPPOSITE

if TYPE_CHECKING:
    from .content import Content
    from .models import GameState, Room

PUDDLES = 0.25  # of a poison floor's doorways between its rooms
VENTS = 0.25  # of its rooms (and every vent field)
RIVERS = ("river_crossing",)  # the kinds of room a river runs through
DC = {"puddle": 10, "river": 12, "spot": 12, "disarm": 13}
VENT_XP = 15
SAID = {  # what each roll is, and how it went: (the roll's label, made it, didn't, what poisoned you)
    "puddle": ("agility (jump the puddle)",
               "A puddle of glowing poison lies across the doorway: you jump it cleanly.",
               "A puddle of glowing poison lies across the doorway. You jump, and land right in it.",
               "The poison puddle"),
    "river": ("agility (cross the river)",
              "A river of poison runs across the room: you cross on its stepping stones without a splash.",
              "A river of poison runs across the room. A stepping stone rolls under your foot, and in you go.",
              "The poison river"),
    "spot": ("wits (spot the vent)",
             "A gas vent hisses in the floor ahead: you see it in time, and keep wide of it.",
             "A gas vent you never saw breathes a yellow-green cloud right in your face.",
             "The gas vent"),
    "disarm": ("wits (disarm the vent)",
               f"You jam the gas vent shut. It coughs once, and goes quiet for good. +{VENT_XP} XP.",
               "The vent spits gas in your face while you work at it.",
               "The gas vent"),
}


def place(state: GameState, rooms: list[Room], end_id: int) -> None:
    """A poison floor's hazards, from a random stream of their own (so they change nothing else about the floor). A
    river wherever a room's kind has one; no vent in the first room, the boss's, a shop or the secret room; no puddle
    in a locked doorway."""
    rng = dice.stream(state.seed, "hazards", state.floor)
    for room in rooms:
        room.river = room.archetype in RIVERS
    open_rooms = [r for r in rooms if r.id not in (0, end_id) and not (r.shop or r.secret)]
    for room in open_rooms:
        if room.archetype == "vent_field" or rng.random() < VENTS:
            room.vent = "hidden"
    doorways = {r.id for r in open_rooms} | {0}
    for room in rooms:
        for direction, exit_ in sorted(room.exits.items()):
            if room.id < exit_.to and {room.id, exit_.to} <= doorways and not exit_.locked \
                    and rng.random() < PUDDLES:
                exit_.puddle = rooms[exit_.to].exits[OPPOSITE[direction]].puddle = True


def crossing(state: GameState, content: Content, direction: str) -> list[Event]:
    """Come into this room going `direction`: the puddle in its doorway, its river, its unseen vent, a roll each."""
    room = state.room
    came = room.exits.get(OPPOSITE[direction])
    rng = dice.stream(state.seed, "hazard", state.turn, state.reroll, room.id)
    events = []
    for kind, there in (("puddle", bool(came and came.puddle)), ("river", room.river), ("spot", room.vent == "hidden")):
        if there:
            events += _roll(state, content, rng, kind)
    return events


def disarm(state: GameState, content: Content, rng: random.Random) -> list[Event]:
    """Work a seen vent shut: done, it's dead and there's XP for it; failed, it gets you (and is still there)."""
    return _roll(state, content, rng, "disarm")


def dozed(state: GameState) -> list[Event]:
    """Resting in a room with a vent you never saw: it finds you asleep."""
    state.room.vent = "seen"
    return [Event("hazard", "As you doze, a gas vent you never saw breathes on you.")] + \
        statuses.inflict(state, "poison", "The gas vent")


def facts(state: GameState) -> list[str]:
    """What there is to say of this room's hazards that you know of, for a look around."""
    room = state.room
    said = ["A river of glowing poison runs across the room."] if room.river else []
    said += {"seen": ["A gas vent hisses in the floor: you keep wide of it."],
             "dead": ["A dead gas vent, jammed shut."]}.get(room.vent, [])
    puddles = [d for d, e in room.exits.items() if e.puddle]
    if puddles:
        said.append("A poison puddle lies across the doorway " + " and ".join(puddles) + ".")
    return said


def _roll(state: GameState, content: Content, rng: random.Random, kind: str) -> list[Event]:
    player = state.player
    if kind != "disarm" and statuses.has(state, "poison"):  # (it can't do more to you: on you go)
        if kind == "spot":
            state.room.vent = "seen"  # (you smell it, poisoned or not)
        return []
    label, made, missed, by = SAID[kind]
    stat = "wits" if kind in ("spot", "disarm") else "agility"
    bonuses = [(stat, getattr(player, stat))] + powers.roll_bonuses(state, content, "disarm" if kind == "disarm"
                                                                   else "search" if kind == "spot" else "dodge")
    roll = dice.check(rng, label, bonuses, DC[kind])
    if kind == "spot":
        state.room.vent = "seen"
    if roll.success:
        if kind == "disarm":
            state.room.vent = "dead"
            player.xp += VENT_XP
        return [Event("hazard", made, dice=roll, data={"rerollable": True, "hazard": kind})]
    return [Event("hazard", missed, dice=roll, data={"rerollable": True, "hazard": kind})] + \
        statuses.inflict(state, "poison", by)
