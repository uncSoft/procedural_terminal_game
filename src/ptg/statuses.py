"""Statuses: what stays with you between turns and does something on its own, after Final Fantasy 1's (poison first:
docs/plans/floor-4-and-statuses.md). Each one is a row in data/statuses.toml: when it ticks, what a tick costs, whether
it can kill you, whether it puts your rolls at a disadvantage, and whether a shrine cures it.

    inflict(state, "poison", by)    a bite, a vent, a puddle: poisoned, unless a guard stops it (one guard spent)
    tick(state, "step")             a room walked into (or passed on quick travel), or a fight's turn ("round"):
                                    each status that ticks then
    cure(state, "poison")           a shrine's prayer, Pure: it's gone
    hindrance(state)                what's off your rolls now (-2, poisoned), for dice.HINDERED

A guard (Player.guards) is a charge against a status: Pure cures poison and leaves one, so the next poisoning doesn't
take. Statuses are kept on the player as {status: strength} (Player.statuses).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib import resources
from typing import TYPE_CHECKING

from .dice import Hindrance
from .events import Event

if TYPE_CHECKING:  # models imports content, and content checks its items' statuses against DEFS
    from .models import GameState


@dataclass(frozen=True)
class StatusDef:
    key: str
    name: str
    icon: str
    colour: str
    ticks: tuple[str, ...] = ()
    damage: int = 0
    lethal: bool = True
    penalty: int = 0
    disadvantage: bool = False
    shrine: bool = False
    cured_by: str = ""
    blurb: str = ""


def _load() -> dict[str, StatusDef]:
    text = resources.files("ptg").joinpath("data", "statuses.toml").read_text(encoding="utf-8")
    rows = tomllib.loads(text).get("status", {})
    return {key: StatusDef(key=key, ticks=tuple(row.pop("ticks", ())), **row) for key, row in rows.items()}


DEFS = _load()
WORDS = {"poison": ("poisoned", "the poison")}  # how a status is said: as a state, and as a thing


def effects(status: StatusDef) -> str:
    """What a status does, in a line: "-2 to your rolls · -2 HP a step and a fight's turn, never the last · cure: pray
    at a shrine, or drink Pure"."""
    when = {"step": "a step", "round": "a fight's turn"}
    parts = [f"-{status.penalty} to your rolls"] if status.penalty else []
    parts += ["your rolls at a disadvantage"] if status.disadvantage else []
    if status.damage and status.ticks:
        parts.append(f"-{status.damage} HP {' and '.join(when.get(t, t) for t in status.ticks)}"
                     + ("" if status.lethal else ", never the last"))
    return " · ".join(parts + ([f"cure: {status.cured_by}"] if status.cured_by else []))


def has(state: GameState, key: str) -> bool:
    return key in state.player.statuses


def hindered(state: GameState) -> str:
    """Why your rolls are worse now (the first status that makes them so, as a word: "poisoned"), or ""."""
    return next((WORDS.get(key, (key,))[0] for key in state.player.statuses
                 if key in DEFS and (DEFS[key].penalty or DEFS[key].disadvantage)), "")


def hindrance(state: GameState) -> Hindrance:
    """What's off your rolls now, all your statuses' together (dice.HINDERED)."""
    ailing = [DEFS[key] for key in state.player.statuses if key in DEFS]
    return Hindrance(hindered(state), sum(s.penalty for s in ailing), any(s.disadvantage for s in ailing))


def inflict(state: GameState, key: str, by: str = "") -> list[Event]:
    """A status taking hold (`by`: what did it, for the story), or a guard spent stopping it. Already suffering it,
    nothing more happens."""
    player, status = state.player, DEFS[key]
    if key in player.statuses:
        return []
    if player.guards.get(key, 0) > 0:
        player.guards[key] -= 1
        left = player.guards[key]
        if not left:
            del player.guards[key]
        return [Event("guarded", f"{by or 'It'} should have {WORDS.get(key, (key,))[0]} you, but the Pure in your blood "
                                 f"burns it away ({left} guard{'s' if left != 1 else ''} left).",
                      data={"status": key, "guards": left, "spent": True})]
    player.statuses[key] = 1
    player.bump(f"{key}_taken")
    what = WORDS.get(key, (key, key))
    return [Event("status", f"{by or 'Something'} has {what[0]} you.", data={"status": key, "on": True}),
            Event("warning", f"You're {status.name.lower()}: {status.blurb.split(': ', 1)[-1]} "
                             f"To cure it: {status.cured_by}.", data={"status": key})]


def cure(state: GameState, key: str, how: str = "") -> list[Event]:
    """A status gone (`how`: "The shrine's light..."), if you had it."""
    if state.player.statuses.pop(key, None) is None:
        return []
    what = WORDS.get(key, (key, key))[1]
    return [Event("cured", f"{how or 'At last'}: {what} is gone.", data={"status": key, "on": False})]


def guard(state: GameState, key: str, charges: int) -> None:
    state.player.guards[key] = state.player.guards.get(key, 0) + charges


def tick(state: GameState, when: str) -> list[Event]:
    """Each status that ticks `when` ("step", "round"): what it costs you. One that isn't lethal stops at 1 HP."""
    player, events = state.player, []
    for key in list(player.statuses):
        status = DEFS.get(key)
        if status is None or when not in status.ticks or not status.damage:
            continue
        floor = 1 if not status.lethal else 0
        damage = max(0, min(status.damage * player.statuses[key], player.hp - floor))
        player.hp -= damage
        player.bump(f"{key}_hp", damage)
        if damage:
            text = f"{status.icon} {WORDS.get(key, (key, key))[1].capitalize()} burns: -{damage} HP " \
                   f"({player.hp}/{player.max_hp})."
        else:
            text = f"{status.icon} {WORDS.get(key, (key, key))[1].capitalize()} leaves you barely standing " \
                   f"({player.hp}/{player.max_hp}), but it won't finish you."
        events.append(Event("status_tick", text, data={"status": key, "damage": damage}))
    return events


def summed(events: list[Event]) -> list[Event]:
    """Several ticks of a journey (quick travel: one a room) told as one."""
    ticks = [e for e in events if e.kind == "status_tick"]
    if len(ticks) <= 1:
        return ticks
    total = sum(e.data.get("damage", 0) for e in ticks)
    last = ticks[-1].text
    hp = last[last.rfind("("):] if "(" in last else ""
    icon = ticks[0].text.split(" ", 1)[0]
    return [Event("status_tick", f"{icon} The poison burns all the way: -{total} HP {hp}".strip(),
                  data={"status": ticks[0].data.get("status"), "damage": total})]
