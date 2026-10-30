"""Statuses: what stays with you between turns and does something on its own, after Final Fantasy 1's (poison first:
docs/plans/floor-4-and-statuses.md). Each one is a row in data/statuses.toml: when it ticks, what a tick costs, whether
it can kill you, whether it puts your rolls at a disadvantage, and whether a shrine cures it.

    inflict(state, "poison", by)    a bite, a vent, a puddle: poisoned, unless a guard stops it (one guard spent)
    tick(state, "step")             a room walked into (or passed on quick travel), or a fight's turn ("round"):
                                    each status that ticks then; one that `lasts` a few ticks wears off after them
    cure(state, "poison")           a shrine's prayer, Pure: it's gone
    hindrance(state)                what's off your rolls now (-2, poisoned), for dice.HINDERED
    stunned(state) / spend_stun     whether your next go is lost (a `skip` status), and losing it
    afflict(monster, "burn")        a status on a monster (MonsterState.statuses: its ticks left); monster_tick, its
                                    burn (or mending) on a fight's turn

Some last a few ticks (`lasts`: Burning, 3), kept in Player.timers (and a monster's ticks left are its statuses'
values); some cost a go (`skip`: Stunned); some help (`mend`, `good`: Mending).

A guard (Player.guards) is a charge against a status: Pure cures poison and leaves one, so the next poisoning doesn't
take. Statuses are kept on the player as {status: strength} (Player.statuses).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, replace
from importlib import resources
from typing import TYPE_CHECKING

from . import powers
from .dice import Hindrance
from .events import Event

if TYPE_CHECKING:  # models imports content, and content checks its items' statuses against DEFS
    from .content import Content, ItemDef
    from .models import GameState, MonsterState


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
    lasts: int = 0  # ticks before it wears off (0: till it's cured)
    skip: bool = False  # loses its bearer's next go in a fight (Stunned), spent with it
    mend: int = 0  # HP back each tick (Mending)
    good: bool = False  # a help, not something wrong with you


def _load() -> dict[str, StatusDef]:
    text = resources.files("ptg").joinpath("data", "statuses.toml").read_text(encoding="utf-8")
    rows = tomllib.loads(text).get("status", {})
    return {key: StatusDef(key=key, ticks=tuple(row.pop("ticks", ())), **row) for key, row in rows.items()}


DEFS = _load()
WORDS = {"poison": ("poisoned", "the poison"), "burn": ("set alight", "the fire"), "stun": ("stunned", "the daze"),
         "mend": ("mended", "the mending")}  # how a status is said: as a state, and as a thing
MONSTER_BURN = 3  # what Burning costs a monster each turn of a fight (they've more to lose than you)
MONSTER_MEND = 5  # and what Mending gives one back


def effects(status: StatusDef) -> str:
    """What a status does, in a line: "-2 to your rolls · -2 HP a step and a fight's turn, never the last · cure: pray
    at a shrine, or drink Pure"."""
    when = {"step": "a step", "round": "a fight's turn"}
    parts = [f"-{status.penalty} to your rolls"] if status.penalty else []
    parts += ["your rolls at a disadvantage"] if status.disadvantage else []
    if status.damage and status.ticks:
        parts.append(f"-{status.damage} HP {' and '.join(when.get(t, t) for t in status.ticks)}"
                     + ("" if status.lethal else ", never the last"))
    if status.mend and status.ticks:
        parts.append(f"+{status.mend} HP {' and '.join(when.get(t, t) for t in status.ticks)}")
    parts += ["your next go in a fight is lost"] if status.skip else []
    parts += [f"for {status.lasts}"] if status.lasts else []
    return " · ".join(parts + ([f"cure: {status.cured_by}"] if status.cured_by else []))


# What each does to a foe in a fight (monster_tick, combat), for its card.
ON_FOES = {"burn": f"A foe set alight burns for {MONSTER_BURN} HP each turn of the fight, and can fall to it.",
           "mend": f"A foe mending gets {MONSTER_MEND} HP back each turn of the fight: kill its mender first.",
           "stun": "A stunned foe loses its next go.",
           "poison": "Venom does nothing to a foe that bites with it."}


def card(key: str, content: Content | None = None) -> list[tuple[str, str]]:
    """A status's card, as (heading, words) lines: what it is, what it does to you, how long, what cures it, what of
    yours keeps it off for good, and what it does to a foe (ui's InfoScreen draws them)."""
    status = DEFS[key]
    lines = [("", status.blurb)]
    what = effects(replace(status, cured_by=""))
    if what:
        lines.append(("What it does", what))
    lines.append(("How long", f"{status.lasts} of them, then it wears off" if status.lasts else
                  "with the go it costs you" if status.skip else "till it's cured"))
    if status.cured_by:
        lines.append(("Cured by", status.cured_by))
    if content is not None:
        wards = [item.name for item in content.items.values() if key in item.wards]
        if wards:
            lines.append(("Kept off by", ", ".join(wards) + " (worn or carried)"))
    if key in ON_FOES:
        lines.append(("On a foe", ON_FOES[key]))
    return lines


def has(state: GameState, key: str) -> bool:
    return key in state.player.statuses


def ailing(state: GameState) -> list[StatusDef]:
    """What's wrong with you (not a help like Mending), worst first as they took hold."""
    return [DEFS[key] for key in state.player.statuses if key in DEFS and not DEFS[key].good]


def left(state: GameState, key: str) -> int:
    """Ticks a status of yours has left (0: one that lasts till it's cured)."""
    return state.player.timers.get(key, 0)


def stunned(state: GameState) -> bool:
    """Whether your next go is lost (a `skip` status: Stunned)."""
    return any(DEFS[key].skip for key in state.player.statuses if key in DEFS)


def spend_stun(state: GameState) -> list[Event]:
    """Your go, lost to a daze: it's spent, and you're clear-headed again."""
    for key in [k for k in state.player.statuses if k in DEFS and DEFS[k].skip]:
        del state.player.statuses[key]
        state.player.timers.pop(key, None)
        state.player.guards[key] = max(state.player.guards.get(key, 0), 1)  # (braced now: not twice running)
    return [Event("stunned_you", "Your head's still ringing: your go is lost, and they come on.",
                  data={"status": "stun"})]


def hindered(state: GameState) -> str:
    """Why your rolls are worse now (the first status that makes them so, as a word: "poisoned"), or ""."""
    return next((WORDS.get(key, (key,))[0] for key in state.player.statuses
                 if key in DEFS and (DEFS[key].penalty or DEFS[key].disadvantage)), "")


def hindrance(state: GameState) -> Hindrance:
    """What's off your rolls now, all your statuses' together (dice.HINDERED)."""
    ailing = [DEFS[key] for key in state.player.statuses if key in DEFS]
    return Hindrance(hindered(state), sum(s.penalty for s in ailing), any(s.disadvantage for s in ailing))


def warded(state: GameState, content: Content, key: str) -> ItemDef | None:
    """What of yours keeps a status off for good (an item that `wards` it, working for you: worn, or carried), if
    anything does."""
    return next((item for item in powers.carried(state, content) if key in item.wards), None)


def inflict(state: GameState, key: str, by: str = "", content: Content | None = None) -> list[Event]:
    """A status taking hold (`by`: what did it, for the story), unless something of yours wards it off (given the
    content to know what you have: the Shed Snakeskin, for poison), or a guard is spent stopping it. Already suffering
    it, nothing more happens."""
    player, status = state.player, DEFS[key]
    if key in player.statuses:
        if status.lasts:  # (a fresh one: as long again)
            player.timers[key] = max(player.timers.get(key, 0), status.lasts)
        return []
    ward = warded(state, content, key) if content else None
    if ward:
        return [Event("guarded", f"{by or 'It'} would have {WORDS.get(key, (key,))[0]} you, but it never gets past "
                                 f"your {ward.name}.", data={"status": key, "ward": ward.key})]
    if player.guards.get(key, 0) > 0:
        player.guards[key] -= 1
        left = player.guards[key]
        if not left:
            del player.guards[key]
        if status.skip:  # (braced, after the last daze)
            return [Event("guarded", f"{by or 'It'} would have stunned you, but you're braced for it this time.",
                          data={"status": key, "spent": True})]
        return [Event("guarded", f"{by or 'It'} should have {WORDS.get(key, (key,))[0]} you, but the Pure in your blood "
                                 f"burns it away ({left} guard{'s' if left != 1 else ''} left).",
                      data={"status": key, "guards": left, "spent": True})]
    player.statuses[key] = 1
    if status.lasts:
        player.timers[key] = status.lasts
    player.bump(f"{key}_taken")
    what = WORDS.get(key, (key, key))
    cure = f" To cure it: {status.cured_by}." if status.cured_by else ""
    return [Event("status", f"{by or 'Something'} has {what[0]} you.", data={"status": key, "on": True}),
            Event("good" if status.good else "warning",
                  f"You're {status.name.lower()}: {status.blurb.split(': ', 1)[-1]}{cure}", data={"status": key})]


def cure(state: GameState, key: str, how: str = "") -> list[Event]:
    """A status gone (`how`: "The shrine's light..."), if you had it."""
    state.player.timers.pop(key, None)
    if state.player.statuses.pop(key, None) is None:
        return []
    what = WORDS.get(key, (key, key))[1]
    return [Event("cured", f"{how or 'At last'}: {what} is gone.", data={"status": key, "on": False})]


def guard(state: GameState, key: str, charges: int) -> None:
    state.player.guards[key] = state.player.guards.get(key, 0) + charges


def tick(state: GameState, when: str) -> list[Event]:
    """Each status that ticks `when` ("step", "round"): what it costs you (one that isn't lethal stops at 1 HP), or
    gives you back (Mending); and one that `lasts` a few ticks, one tick nearer wearing off."""
    player, events = state.player, []
    for key in list(player.statuses):
        status = DEFS.get(key)
        if status is None or when not in status.ticks:
            continue
        if status.mend:
            healed = min(status.mend, player.max_hp - player.hp)
            player.hp += healed
            if healed:
                events.append(Event("status_tick", f"{status.icon} {WORDS.get(key, (key, key))[1].capitalize()} gives "
                                                   f"you back {healed} HP ({player.hp}/{player.max_hp}).",
                                    data={"status": key, "healed": healed}))
        if not status.damage:
            events += _wear(state, key, status)
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
        if player.hp <= 0:  # (a lethal one: Burning)
            events += fall(state, WORDS.get(key, (key, key))[1], f"{'burnt' if key == 'burn' else 'killed'} to "
                                                                  f"death on floor {state.floor}")
            if state.over:
                break
        events += _wear(state, key, status)  # (its last tick still burns: then it's out)
    return events


def fall(state: GameState, by: str, cause: str, data: dict | None = None) -> list[Event]:
    """Your health gone, to a blow or a burn (`by`: what did it, mid-sentence): a reprieve if you've one left (Second
    Wind, a floor; Last Breath, a run), else the end (`cause`, for the Hall of Legends)."""
    player = state.player
    if "second_wind" in player.perks and player.second_wind_floor != state.floor:
        player.second_wind_floor = state.floor
        player.hp = 1
        return [Event("reprieve", "Second Wind! You refuse to fall and stagger up with 1 HP.")]
    if "last_breath" in player.blessings and not player.last_breath_used:
        player.last_breath_used = True
        player.hp = 1
        return [Event("reprieve", "Last Breath: something in the dark isn't finished with you. You live, with 1 HP.")]
    state.status = "dead"
    state.cause = cause
    return [Event("death", f"You fall to {by}. Your adventure ends here.", data=data or {})]


def _wear(state: GameState, key: str, status: StatusDef) -> list[Event]:
    """A tick off a status that lasts a while: its last, and it's gone (said once it's had its effect)."""
    player = state.player
    if not status.lasts or key not in player.timers:
        return []
    player.timers[key] -= 1
    if player.timers[key] > 0:
        return []
    del player.timers[key]
    player.statuses.pop(key, None)
    return [Event("cured", f"{WORDS.get(key, (key, key))[1].capitalize()} has run its course.",
                  data={"status": key, "on": False, "worn": True})]


# --- on a monster ----------------------------------------------------------------------------------------------

def afflict(monster: MonsterState, key: str) -> bool:
    """A status on a monster, for as long as it lasts (Stunned: its next go, as a stun always was). Whether it's new
    (a fresh one is as long again)."""
    status = DEFS[key]
    if status.skip:
        new = not monster.stunned
        monster.stunned = max(monster.stunned, 1)
        return new
    new = key not in monster.statuses
    monster.statuses[key] = max(monster.statuses.get(key, 0), status.lasts or 1)
    return new


def monster_tick(monster: MonsterState) -> list[Event]:
    """A fight's turn of a monster's statuses: Burning costs it MONSTER_BURN, Mending gives it MONSTER_MEND, and each
    wears off after its ticks. (It falling to its burns is combat's to see to.)"""
    events = []
    for key in list(monster.statuses):
        status = DEFS.get(key)
        if status is None or "round" not in status.ticks:
            continue
        if status.damage:
            monster.hp -= MONSTER_BURN if key == "burn" else status.damage
            events.append(Event("monster_status", f"{status.icon} {the_name(monster)} burns: -"
                                                  f"{MONSTER_BURN if key == 'burn' else status.damage} HP "
                                                  f"({max(monster.hp, 0)}/{monster.max_hp}).",
                                data={"status": key, "monster": monster.key}))
        if status.mend and monster.hp < monster.max_hp:
            healed = min(MONSTER_MEND, monster.max_hp - monster.hp)
            monster.hp += healed
            events.append(Event("monster_status", f"{status.icon} {the_name(monster)} mends: +{healed} HP "
                                                  f"({monster.hp}/{monster.max_hp}).",
                                data={"status": key, "monster": monster.key}))
        monster.statuses[key] -= 1
        if monster.statuses[key] <= 0:
            del monster.statuses[key]
    return events


def the_name(monster: MonsterState) -> str:
    from .text import cap, the

    return cap(the(monster.name))


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
