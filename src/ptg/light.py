"""Light and the dark (docs/plans/floor-5.md §4). A dark floor (`dark = true` in themes.toml: the Underbloom) has no
light but what grows there and what you bring down. Your light is a torch you carry in your pack (an item with the
`torch` power), lit as soon as you're on a dark floor. It's a fire on hand too: each thing you burn with it costs a
flame of its light, FLAMES a torch. The last one spent, it's gone, and the next torch in your pack is lit. A Flask of
Lamp Oil poured over it puts every flame back.

Without one, you're down there by the glow of what grows (DIM): your searches for secrets are at a disadvantage. In a
room nothing lights (its archetype's decor says `dark`: the Dark Hollow) you're in the DARK: every roll of yours is at
a disadvantage, and whatever's there gets the first blow as you come in (rules._move). Granny's shop has her lamp.

    darkness(state, content)    DIM, DARK, or "" (your torch is lit, or it isn't a dark floor)
    torch(state, content)       the torch you'd burn, if you carry one
    lit(state, content)         whether it's burning: a torch, on a dark floor
    left(state)                 its flames left, of FLAMES
    burn(state, content)        a flame of it spent burning something (combat.burn, rules._burn_open)
    refill(state, content)      Lamp Oil poured over it: every flame back
    hindrance(state, content)   what's off your rolls this turn, your statuses' and the dark's (rules.perform)
    settle(state, content)      your torch lit, or gone, since you were last told (rules.finish_turn)
    wrapped(state, content, f)  a thing wrapped tight in threads, that only fire opens
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from . import inventory, powers, statuses
from .dice import Hindrance
from .events import Event
from .text import the

if TYPE_CHECKING:
    from .content import Content, ItemDef
    from .models import Feature, GameState, Room

FLAMES = 5  # a torch's light: a flame for each thing it burns
OIL = "oil_flask"  # what fills a torch up again
DIM, DARK = "by the glow", "in the dark"  # what you're in down there with no light of your own (darkness)
WRAPS = ("cocoon", "wrapped", "curtain", "bundle")  # a dark floor's things wrapped tight in threads: fire opens them
HINT = "A light source would be super helpful down here!"  # (JT's words: what you're told with none)


def dark_floor(state: GameState, content: Content) -> bool:
    theme = content.themes.get(state.theme)
    return bool(theme and theme.dark)


def torch(state: GameState, content: Content) -> ItemDef | None:
    """The torch you'd burn, if you carry one. Two burn one at a time: the second is lit when the first is out."""
    return next(iter(powers.holders(state, content, "torch")), None)


def lit(state: GameState, content: Content) -> bool:
    return dark_floor(state, content) and torch(state, content) is not None


def pitch_dark(content: Content, room: Room) -> bool:
    """A room nothing lights, on a dark floor: its decor says so (the Dark Hollow)."""
    archetype = content.archetypes.get(room.archetype)
    return bool(archetype and "dark" in archetype.decor.split())


def darkness(state: GameState, content: Content, room: Room | None = None) -> str:
    """What you're in, in this room (or another on the floor), with no light of your own: DIM, DARK, or "" (your
    torch is lit, it isn't a dark floor, or it's Granny's shop)."""
    room = room or state.room
    if not dark_floor(state, content) or room.shop or torch(state, content):
        return ""
    return DARK if pitch_dark(content, room) else DIM


def left(state: GameState) -> int:
    return max(0, FLAMES - state.player.burnt)


def flames(state: GameState) -> str:
    """Its flames left, in words: "4 flames left", "its last flame"."""
    n = left(state)
    return "its last flame" if n == 1 else f"{n} flames left"


def hindrance(state: GameState, content: Content) -> Hindrance:
    """What's off your rolls this turn: what ails you (statuses.hindrance), and in the dark, a disadvantage on every
    one of them."""
    ailing = statuses.hindrance(state)
    if darkness(state, content) != DARK:
        return ailing
    return replace(ailing, disadvantage=True, why_worse=DARK)


def wrapped(state: GameState, content: Content, feature: Feature) -> bool:
    """A thing on a dark floor wrapped tight in threads (a cocoon, a curtain of them), not opened yet: no hand gets
    into it, only fire (rules._burn_open)."""
    name = feature.name.lower()
    return dark_floor(state, content) and not feature.searched and any(word in name for word in WRAPS)


def burn(state: GameState, content: Content) -> list[Event]:
    """A flame of your torch spent burning something. The last of them, and it's out: gone from your pack, and the
    next torch in it is lit, if there's one."""
    player, item = state.player, torch(state, content)
    if item is None:
        return []
    player.burnt += 1
    if player.burnt < FLAMES:
        return []
    player.burnt = 0
    used = inventory.consume(state, item.key, "use")
    after = torch(state, content)
    player.lit = lit(state, content)
    then = f" You light another from your pack ({FLAMES} flames)." if after else \
        f" The dark closes in, lit only by what grows. {HINT}"
    return [Event("light", f"Your torch gutters and goes out, burnt down to a stub.{then}",
                  data={**used, "lit": after is not None})]


def refill(state: GameState, content: Content) -> list[Event]:
    """Lamp Oil poured over your torch: every flame back, and the flask is gone."""
    player, oil = state.player, content.item(OIL)
    used = inventory.consume(state, OIL, "use")
    player.burnt = 0
    more = player.inventory.count(OIL)
    return [Event("light", f"You pour {the(oil.name)} over your torch. It drinks it up and roars back: every "
                           f"flame of it ({FLAMES}/{FLAMES})." + (f" ({more} more in your pack.)" if more else ""),
                  data={**used, "lit": True})]


def settle(state: GameState, content: Content) -> list[Event]:
    """Your torch lit (one in your pack on a dark floor: picked up, bought, or the floor just come down to), or gone
    out of your hands (dropped, sold, snatched), since you were last told: said once, as it happens."""
    player, now = state.player, lit(state, content)
    if now == player.lit:
        return []
    player.lit = now
    if now:
        return [Event("light", f"You light your torch. Warm light pushes the dark back a few steps "
                               f"({left(state)}/{FLAMES} flames).", data={"lit": True})]
    if not dark_floor(state, content):
        return []
    return [Event("light", f"Without a torch, the dark closes in, lit only by what grows. {HINT}",
                  data={"lit": False})]


def arrival(state: GameState, content: Content) -> list[Event]:
    """Come down to a dark floor with no light of your own: what you're in for (one with a torch lights it: settle)."""
    if not dark_floor(state, content) or torch(state, content):
        return []
    return [Event("warning", "There's no light down here but what grows, and you've brought none: your searches are "
                             f"at a disadvantage, and in the dark places, everything is. {HINT}", data={"lit": False})]


def entering(state: GameState, content: Content) -> list[Event]:
    """Walked into a room nothing lights, with no light of your own: said every time, it matters so much."""
    if darkness(state, content) != DARK:
        return []
    return [Event("warning", "It's pitch dark in here, and you've no light: every roll of yours is at a disadvantage, "
                             "and anything here gets the first blow.", data={"dark": True})]


def facts(state: GameState, content: Content) -> str:
    """The light here, for the narrator: so its prose has your torch in it, or the glow, or the dark."""
    if lit(state, content):
        return f"Your torch is lit ({flames(state)}): warm light round you, cold glowing fungus beyond it."
    gloom = darkness(state, content)
    if gloom == DARK:
        return "It's pitch dark here and you have no light: you're feeling your way."
    if gloom == DIM:
        return "You have no light of your own: you see only by the cold glow of what grows here."
    return ""
