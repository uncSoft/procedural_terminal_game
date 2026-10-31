"""Between runs: building your adventurer from unlocks, starting a descent, and scoring the end of one."""

from __future__ import annotations

import datetime as dt
import random

from . import dice, powers
from .config import save_game
from .content import Content, load_content
from .integrity import shipped_report
from .models import DEEPEST, FLOORS, GameState, Player
from .profile import Profile
from .world import generate

EPITHETS = {
    "pacify": "the Silver-Tongued", "flair": "the Showboat", "kills": "the Butcher", "fled": "the Swift",
    "searched": "the Nosy", "fumbles": "the Unlucky", "weakness": "the Scholar", "dodged": "the Nimble",
    "creative_win": "the Clever", "stuns": "the Bewildering", "flawless": "the Untouched", "exploited": "the Cunning",
}


def make_player(name: str, profile: Profile, content: Content, gift: str | None = None) -> Player:
    unlocked = profile.unlocked()
    blessings = [k for k in unlocked if k in content.unlocks and content.unlocks[k].kind == "blessing"]
    player = Player(name=name, blessings=blessings)
    for key in ("vigor", "vigor_2"):
        if key in blessings:
            player.max_hp += 5
            player.hp += 5
    if "fortune" in blessings:
        player.fate += 1
    gift = gift if gift in unlocked else profile.gift
    if gift not in unlocked or gift not in content.unlocks:
        gift = "coin_bag"
    player.gift = gift
    if gift == "coin_bag":
        player.gold += 15
    elif content.unlocks[gift].item:
        player.inventory.append(content.unlocks[gift].item)
    return player


def daily_seed(date: dt.date | None = None) -> tuple[int, str]:
    date = date or dt.date.today()
    return int(date.strftime("%Y%m%d")), date.isoformat()


def floors_for(profile: Profile, daily: bool = False) -> int:
    """How deep a run goes: four floors (FLOORS), and once you've won one (beaten Serpentis), on down to the
    Underbloom under her (DEEPEST). A daily run is four for everyone, as everyone's daily is the same."""
    return DEEPEST if not daily and profile.totals()["wins"] else FLOORS


def start_run(profile: Profile, content: Content, name: str, seed: int | None = None,
              daily: bool = False, gift: str | None = None) -> GameState:
    label = ""
    if daily:
        seed, label = daily_seed()
    elif seed is None:
        seed = random.randrange(1_000_000)
    player = make_player(name, profile, content, gift)
    floors = floors_for(profile, daily)
    # Daily runs are the same for everyone, so no personal ghosts in them.
    ghost = None if daily else profile.pick_ghost(dice.stream(seed, "ghost"))
    if ghost:
        ghost["floor"] = max(1, min(floors, int(ghost.get("floor", 1))))
    state = generate(seed, player=player, ghost=ghost, content=content, floors=floors)
    state.known_weak = profile.weaknesses()
    state.daily = label
    state.modded = shipped_report().tampered
    state.run_id = profile.start_run(seed, name, state.themes, label, modded=state.modded)
    return state


def souls_earned(state: GameState) -> int:
    souls = state.souls + state.player.gold // 10
    souls += 30 * len(powers.holders(state, load_content(), "valuable"))  # treasure you made it out with
    if "soul_siphon" in state.player.blessings:
        souls = round(souls * 1.25)
    return souls


def epithet(state: GameState) -> str:
    style = {k: v for k, v in state.player.style.items() if k in EPITHETS and v > 0}
    if not style:
        return "the Brief"
    return EPITHETS[max(style, key=lambda k: (style[k], k))]


def fallback_epitaph(state: GameState) -> str:
    who = f"{state.player.name} {epithet(state)}"
    if state.status == "won":
        return f"{who}, who went all the way down and came back up."
    return f"Here lies {who}, {state.cause or 'lost in the dark'}."


SUNGLASSES = "(⌐■_■)"  # for bordered terminal UI, where emoji widths are unreliable


def share_card(state: GameState, emoji: bool = False) -> str:
    """A spoiler-free result to paste in a chat, Wordle style. Runs on edited game data say so."""
    player = state.player
    floors = "▰" * (state.floor if state.status == "won" else state.floor - 1) + "▱" * (state.floors_total - (state.floor if state.status == "won" else state.floor - 1))
    outcome = "★ VICTORY" if state.status == "won" else f"☠ floor {state.floor}"
    title = f"Daily {state.daily}" if state.daily else f"seed {state.seed}"
    if state.modded:
        title += f" · {'🕶️' if emoji else SUNGLASSES} modded"
    return (f"Procedural Terminal Game · {title}\n"
            f"{player.name} {epithet(state)}  {outcome}\n"
            f"{floors}  ⚔{player.kills}  ✦{player.style.get('flair', 0)}  ☽{souls_earned(state)}  ⏱{state.turn}\n"
            f"\"{state.epitaph or fallback_epitaph(state)}\"")


def run_summary(state: GameState) -> list[str]:
    """A run in progress, in short: who, where, and how they're doing."""
    player = state.player
    return [f"{player.name}, level {player.level}",
            f"Floor {state.floor}/{state.floors_total} · {load_content().themes[state.theme].name}",
            f"{player.hp}/{player.max_hp} HP · turn {state.turn}"]


def abandon(profile: Profile, state: GameState) -> int:
    """A run left unfinished for a new one ends as a death: a line in the Hall of Legends, its souls banked and,
    as from any death, a ghost left on its floor. Returns the souls."""
    state.status, state.cause = "dead", f"abandoned on floor {state.floor}"
    souls = record_end(profile, state)
    save_game(state)  # (over: nothing left to continue)
    return souls


def record_end(profile: Profile, state: GameState) -> int:
    """Write the finished run to the Hall of Legends, bank the souls, and leave a ghost if you died."""
    if state.test_room:  # (a test room's run counts for nothing)
        return 0
    souls = souls_earned(state)
    profile.add_souls(souls)
    if state.run_id is not None:
        player = state.player
        profile.finish_run(state.run_id, status=state.status, floor=state.floor, level=player.level,
                           kills=player.kills, gold=player.gold, souls=souls, turns=state.turn, cause=state.cause,
                           epitaph=state.epitaph or fallback_epitaph(state), epithet=epithet(state),
                           traits=player.traits, perks=player.perks)
        if state.status == "dead" and not state.daily:
            carried = [*player.gear, *player.inventory]
            profile.add_ghost(state.run_id, player.name, player.level, state.floor, carried, player.gold,
                              state.epitaph or fallback_epitaph(state), state.cause)
    return souls
