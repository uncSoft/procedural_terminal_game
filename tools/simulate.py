"""A balance report: the action-only bot (tests/bot.py) plays many seeds, and this says how each floor went.

    uv run --frozen python tools/simulate.py              # 300 seeds, the plain bot
    uv run --frozen python tools/simulate.py 1000 --start 5000
    uv run --frozen python tools/simulate.py --player average   # a bot with a person's habits (tests/bot.py PLAYERS)
    uv run --frozen python tools/simulate.py --compare          # every player, a line each

Per floor: how many runs reached it, died on it, and what they took down the stairs (HP, level, gold, potions). Then
what killed them, and the run as a whole. The plain bot is thorough and never misses a warning, but never improvises,
shops or bombs a wall; the players with habits miss warnings, hoard potions, walk past things and rush the stairs.
Between them they bracket a person, they don't forecast one: compare a change's report with the last one (docs/plans/progression-loot-
difficulty.md has the baseline)."""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from bot import PLAYERS, Player, choose

from ptg.content import load_content
from ptg.rules import perform
from ptg.world import generate


def potions(state) -> int:
    return sum(1 for key in state.player.inventory if "potion" in key)


def run(seed: int, content, player: str = "bot", max_turns: int = 900) -> dict:
    """One bot run: where it ended, and a row for each floor it left by the stairs."""
    state = generate(seed, content=content)
    who = Player(PLAYERS[player], seed) if player != "bot" else None
    left: dict[int, dict] = {}
    turns_in: Counter = Counter()
    killer = ""
    for _ in range(max_turns):
        if state.over:
            break
        floor, monster = state.floor, state.room.monster
        perform(state, content, choose(state, content, who))
        turns_in[floor] += 1
        if state.floor != floor:  # down the stairs: how you went
            player = state.player
            left[floor] = {"hp": player.hp / player.max_hp, "level": player.level, "gold": player.gold,
                           "potions": potions(state), "turns": turns_in[floor]}
        if state.status == "dead" and monster is not None:
            killer = monster.name
    return {"seed": seed, "status": state.status, "floor": state.floor, "level": state.player.level,
            "turns": state.turn, "left": left, "killer": killer, "gold": state.player.gold,
            "potions": potions(state), "kills": state.player.kills}


def median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def report(results: list[dict], floors: int) -> str:
    n = len(results)
    won = sum(r["status"] == "won" for r in results)
    stuck = sum(r["status"] == "playing" for r in results)
    lines = [f"{n} bot runs · won {won} ({100 * won / n:.0f}%) · stuck {stuck}", ""]
    lines.append(f"{'floor':>5} {'reached':>8} {'died':>6} {'death%':>7} {'HP% at stairs':>14} {'level':>6} "
                 f"{'gold':>6} {'potions':>8} {'turns':>6}")
    for floor in range(1, floors + 1):
        reached = [r for r in results if r["floor"] >= floor]
        died = [r for r in reached if r["status"] == "dead" and r["floor"] == floor]
        out = [r["left"][floor] for r in reached if floor in r["left"]]
        rate = 100 * len(died) / len(reached) if reached else 0
        row = f"{floor:>5} {len(reached):>8} {len(died):>6} {rate:>6.0f}% "
        if out:  # (the last floor has no stairs: it ends with its boss)
            row += (f"{100 * median([o['hp'] for o in out]):>13.0f}% {median([o['level'] for o in out]):>6.1f} "
                    f"{median([o['gold'] for o in out]):>6.0f} {median([o['potions'] for o in out]):>8.1f} "
                    f"{median([o['turns'] for o in out]):>6.0f}")
        else:
            row += f"{'—':>14}"
        lines.append(row)
    killers = Counter(r["killer"] or "(unknown)" for r in results if r["status"] == "dead")
    by_floor: dict[str, Counter] = defaultdict(Counter)
    for r in results:
        if r["status"] == "dead":
            by_floor[r["killer"] or "(unknown)"][r["floor"]] += 1
    lines += ["", "what killed them (floors):"]
    for name, count in killers.most_common(12):
        where = ", ".join(f"F{f}×{c}" for f, c in sorted(by_floor[name].items()))
        lines.append(f"  {count:>4}  {name}  ({where})")
    lines.append("")
    lines.append(f"median level at the end {median([r['level'] for r in results]):.1f} · "
                 f"median turns {median([r['turns'] for r in results]):.0f} · "
                 f"median kills {median([r['kills'] for r in results]):.0f} · "
                 f"median gold unspent {median([r['gold'] for r in results]):.0f} · "
                 f"median potions left {median([r['potions'] for r in results]):.1f}")
    return "\n".join(lines)


def compare(by_player: dict[str, list[dict]], floors: int) -> str:
    """A line for each player: how often it won, where it died, and what it left unused."""
    head = f"{'player':>8} {'won':>5} " + " ".join(f"{'F' + str(f) + ' death%':>10}" for f in range(1, floors + 1))
    lines = [head + f" {'potions left':>13} {'gold left':>10}"]
    for name, results in by_player.items():
        won = 100 * sum(r["status"] == "won" for r in results) / len(results)
        deaths = []
        for floor in range(1, floors + 1):
            reached = [r for r in results if r["floor"] >= floor]
            died = sum(r["status"] == "dead" and r["floor"] == floor for r in reached)
            deaths.append(f"{100 * died / len(reached) if reached else 0:>9.0f}%")
        lines.append(f"{name:>8} {won:>4.0f}% " + " ".join(deaths) +
                     f" {median([r['potions'] for r in results]):>13.1f} {median([r['gold'] for r in results]):>10.0f}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("seeds", nargs="?", type=int, default=300)
    parser.add_argument("--start", type=int, default=0, help="the first seed")
    parser.add_argument("--player", choices=sorted(PLAYERS), default="bot", help="whose habits (tests/bot.py)")
    parser.add_argument("--compare", action="store_true", help="every player, a line each")
    args = parser.parse_args()
    content = load_content()
    seeds = range(args.start, args.start + args.seeds)
    floors = generate(0, content=content).floors_total
    if args.compare:
        print(compare({name: [run(seed, content, name) for seed in seeds] for name in PLAYERS}, floors))
        return
    print(report([run(seed, content, args.player) for seed in seeds], floors))


if __name__ == "__main__":
    main()
