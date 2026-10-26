"""A balance report: the action-only bot (tests/bot.py) plays many seeds, and this says how each floor went.

    uv run --frozen python tools/simulate.py              # 300 seeds
    uv run --frozen python tools/simulate.py 1000 --start 5000

Per floor: how many runs reached it, died on it, and what they took down the stairs (HP, level, gold, potions). Then
what killed them, and the run as a whole. The bot never improvises, shops or bombs a wall, so its numbers are a floor
under a person's, not a forecast: compare a change's report with the last one (docs/plans/progression-loot-
difficulty.md has the baseline)."""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from bot import choose

from ptg.content import load_content
from ptg.rules import perform
from ptg.world import generate


def potions(state) -> int:
    return sum(1 for key in state.player.inventory if "potion" in key)


def run(seed: int, content, max_turns: int = 900) -> dict:
    """One bot run: where it ended, and a row for each floor it left by the stairs."""
    state = generate(seed, content=content)
    left: dict[int, dict] = {}
    turns_in: Counter = Counter()
    killer = ""
    for _ in range(max_turns):
        if state.over:
            break
        floor, monster = state.floor, state.room.monster
        perform(state, content, choose(state, content))
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("seeds", nargs="?", type=int, default=300)
    parser.add_argument("--start", type=int, default=0, help="the first seed")
    args = parser.parse_args()
    content = load_content()
    results = [run(seed, content) for seed in range(args.start, args.start + args.seeds)]
    print(report(results, generate(0, content=content).floors_total))


if __name__ == "__main__":
    main()
