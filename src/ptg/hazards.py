"""Hazards: what a floor with poison of its own (Norfel) puts in your way, after Metroid's Norfair
(docs/plans/floor-4-and-statuses.md §3.1). One of each, never next door to each other, and nothing rolls as you walk
in: you see them, and choose.

    a poison river   across a room on the way to the boss: the way on is on its far bank. Leap it (agility: fall in
                     and you're poisoned, but across), wade it (poisoned for sure, unless a snakeskin keeps it off),
                     or vault it with a ten-foot pole (no roll). Across once, you know its stepping stones: from then
                     on it's a stroll, both ways.
    a gas vent       in another room, right under a crust of crystals with something good in it. Disarm it first (wits;
                     a ten-foot pole's care helps; XP for it, and a failed try gasses you), or grab what's there and
                     take the gas. There's no resting beside a live vent.

A guard (Pure) stops what would have poisoned you, and so does anything that wards poison off, every time: the Shed
Snakeskin, worn (Granny's, on floor 3: see rules._snakeskin).
"""

from __future__ import annotations

import random
from collections import deque
from typing import TYPE_CHECKING

from . import dice, loot, powers, statuses
from .events import Action, Event
from .models import OPPOSITE, Feature

if TYPE_CHECKING:
    from .content import Content
    from .models import GameState, Room

RIVER, VENT = "river_crossing", "vent_field"  # the kinds of room they're in (rooms.toml), and nowhere else
DC = {"leap": 12, "disarm": 13}
VENT_XP = 15
POLES = ("ten_foot_pole",)  # what you can vault a river with
CACHE = "a crust of yellow crystals"  # what the vent's under, with something good in it
CACHE_SLOTS = ["potion 3+", "rare", "pure"]  # what's in it (loot.py slots)


def shape(state: GameState, content: Content, rooms: list[Room], end_id: int) -> None:
    """A poison floor's river and vent, from a random stream of their own (so they change nothing else about the
    floor): the river in a room on the way from the entrance to the boss (not the first room, nor the one by the
    boss's door), the vent in another, not next door to it. Each room is made the kind it is."""
    rng = dice.stream(state.seed, "hazards", state.floor)
    path = _path(rooms, end_id)
    gate = path[-2] if len(path) > 1 else None
    on_way = [r for r in path[1:-1] if r != gate] or [r for r in path[1:-1]]
    if on_way:
        river = rooms[rng.choice(on_way)]
        _become(rng, content, river, RIVER)
        river.river = True
        river.across = next(d for d, e in river.exits.items() if e.to == path[path.index(river.id) + 1])
    else:
        river = None
    near = {river.id, *(e.to for e in river.exits.values())} if river else set()
    spots = [r for r in rooms if r.id not in (0, end_id) and r.id not in near]
    if spots:
        vent = rng.choice(spots)
        _become(rng, content, vent, VENT)
        vent.vent = "live"
        key = loot.produce(rng, content, state.rares, [rng.choice(CACHE_SLOTS)], "chest")
        vent.features.append(Feature(name=CACHE, loot=[key] if key else [], gold=rng.randint(10, 25), trapped=True))


def blocked(state: GameState, direction: str) -> bool:
    """Whether the way `direction` is across this room's river from you, and you haven't crossed it yet."""
    room = state.room
    return room.river and not room.stones and (direction == room.across) != room.far


def came_in(state: GameState, direction: str) -> None:
    """You've come into this room going `direction`: on which bank of its river."""
    room = state.room
    if room.river:
        room.far = OPPOSITE[direction] == room.across


def crossings(state: GameState, content: Content) -> list[Action]:
    """The ways over this room's river, if there's somewhere you'd go on its other side."""
    room = state.room
    if not room.river or room.stones:
        return []
    ward = statuses.warded(state, content, "poison")
    wade = "poisoned already" if statuses.has(state, "poison") else \
        f"your {ward.name} keeps it off" if ward else "you'll be poisoned"
    actions = [Action("cross:leap", "Leap the poison river", "agility"),
               Action("cross:wade", "Wade across the poison river", wade)]
    pole = next((content.item(k) for k in POLES if k in state.player.inventory), None)
    if pole:
        actions.append(Action("cross:vault", f"Vault the river with your {pole.name}", "no roll"))
    return actions


def cross(state: GameState, content: Content, rng: random.Random, how: str) -> list[Event]:
    """Over the river: leaping (fall in, and you're poisoned, but over), wading, or vaulting. Either way you're on the
    other bank, and you know its stepping stones now."""
    room, player = state.room, state.player
    room.far, room.stones = not room.far, True
    if how == "vault":
        return [Event("hazard", "You plant your pole in the riverbed and vault the poison clean over. You'll know the "
                                "stepping stones from now on.")]
    if how == "wade":
        return [Event("hazard", "You wade across the poison river, gritting your teeth. You'll know the stepping "
                                "stones from now on.")] + statuses.inflict(state, "poison", "The poison river", content)
    roll = dice.check(rng, "agility (leap the river)", [("agility", player.agility)]
                      + powers.roll_bonuses(state, content, "dodge"), DC["leap"])
    if roll.success:
        return [Event("hazard", "You leap the poison river from stone to stone, and land dry on the far bank.",
                      dice=roll, data={"rerollable": True})]
    return [Event("hazard", "A stepping stone rolls under your foot, and in you go. You scramble out on the far bank, "
                            "dripping.", dice=roll, data={"rerollable": True})] + \
        statuses.inflict(state, "poison", "The poison river", content)


def disarm(state: GameState, content: Content, rng: random.Random) -> list[Event]:
    """Work a live vent shut: done, it's dead and there's XP for it; failed, it gets you (and it's still live)."""
    player, room = state.player, state.room
    roll = dice.check(rng, "wits (disarm the vent)", [("wits", player.wits)]
                      + powers.roll_bonuses(state, content, "disarm"), DC["disarm"])
    if roll.success:
        room.vent = "dead"
        player.xp += VENT_XP
        return [Event("hazard", f"You jam the gas vent shut. It coughs once, and goes quiet for good. +{VENT_XP} XP.",
                      dice=roll, data={"rerollable": True})]
    return [Event("hazard", "The vent spits gas in your face while you work at it.", dice=roll,
                  data={"rerollable": True})] + statuses.inflict(state, "poison", "The gas vent", content)


def grabbed(state: GameState, content: Content) -> list[Event]:
    """Searching what sits over a live vent: you get it, and a faceful of gas."""
    return [Event("hazard", "The vent breathes a yellow-green cloud right in your face as you reach in.")] + \
        statuses.inflict(state, "poison", "The gas vent", content)


def facts(state: GameState) -> list[str]:
    """What there is to say of this room's river and vent, for a look around (and on the way in)."""
    room = state.room
    said = []
    if room.river:  # (the room's own words say what the river is: this is where you stand)
        said.append("You know the poison river's stepping stones now." if room.stones
                    else f"The way {room.across} is on the poison river's {'near' if room.far else 'far'} bank.")
    said += {"live": [f"A gas vent hisses in the floor, right under {CACHE}."],
             "dead": ["A dead gas vent, jammed shut."]}.get(room.vent, [])
    return said


def _become(rng: random.Random, content: Content, room: Room, kind: str) -> None:
    archetype = content.archetypes[kind]
    room.archetype, room.name = kind, rng.choice(archetype.names)
    room.features = [Feature(name=f) for f in rng.sample(archetype.features, min(2, len(archetype.features)))]


def _path(rooms: list[Room], end_id: int) -> list[int]:
    """The shortest way from the entrance to `end_id`, room by room."""
    came: dict[int, int | None] = {0: None}
    queue = deque([0])
    while queue:
        here = queue.popleft()
        for exit_ in sorted(rooms[here].exits.values(), key=lambda e: e.to):
            if exit_.to not in came:
                came[exit_.to] = here
                queue.append(exit_.to)
    path, at = [], end_id
    while at is not None and at in came:
        path.append(at)
        at = came[at]
    return path[::-1]
