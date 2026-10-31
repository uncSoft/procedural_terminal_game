"""A balance report: the action-only bot (tests/bot.py) plays many seeds, and this says how each floor went.

    uv run --frozen python tools/simulate.py              # 300 seeds, the plain bot
    uv run --frozen python tools/simulate.py 1000 --start 5000
    uv run --frozen python tools/simulate.py --player average   # a bot with a person's habits (tests/bot.py PLAYERS)
    uv run --frozen python tools/simulate.py --compare          # every player, a line each
    uv run --frozen python tools/simulate.py --veteran --fights # a veteran's adventurer, and how each fight went
    uv run --frozen python tools/simulate.py --venom dire_wolf,orc  # as if they bit with venom: what poison does
    uv run --frozen python tools/simulate.py --deep             # five floors, as a run goes once you've won one

Per floor: how many runs reached it, died on it, and what they took down the stairs (HP, level, gold, potions, keys,
bombs). Then what killed them, and the run as a whole. The plain bot is thorough and never misses a warning, but never
improvises, shops or bombs a wall; the players with habits miss warnings, hoard potions, walk past things and rush the
stairs. Between them they bracket a person, they don't forecast one: compare a change's report with the last one
(docs/plans/combat-and-balance.md has the baseline). The plain bot plays a newcomer's adventurer; --veteran gives it a
veteran's (tests/bot.py veteran: every blessing, the Rabbit's Foot, perks picked as the owner's run picked them).
--fights adds how the fights went, by floor and kind of foe: how many rounds, the HP they cost, and how hard you hit."""

from __future__ import annotations

import argparse
import dataclasses
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from bot import PLAYERS, VETERAN, Player, choose, veteran

from ptg.content import load_content
from ptg.models import DEEPEST, FLOORS
from ptg.rules import perform
from ptg.world import generate


def potions(state) -> int:
    return sum(1 for key in state.player.inventory if "potion" in key)


def kind_of(monster, content) -> str:
    """What sort of foe, for the fights' report: the boss, a character (Swoogy, King Mouse), the warden by the stairs,
    an elite, or an everyday monster."""
    known = content.monster(monster.key)
    if known.boss:
        return "boss"
    if known.npc or monster.tier:
        return "character"
    return "warden" if monster.warden else "elite" if monster.elite else "normal"


def run(seed: int, content, player: str = "bot", max_turns: int = 900, veteran_run: bool = False,
        floors: int = FLOORS) -> dict:
    """One bot run: where it ended, a row for each floor it left by the stairs, and each fight it had."""
    state = generate(seed, content=content, player=veteran(content) if veteran_run else None, floors=floors)
    habits = PLAYERS[player] if not veteran_run else VETERAN if player == "bot" else \
        dataclasses.replace(PLAYERS[player], perks=VETERAN.perks)
    who = Player(habits, seed) if habits != PLAYERS["bot"] else None
    left: dict[int, dict] = {}
    turns_in: Counter = Counter()
    killer = ""
    fights: list[dict] = []
    fight: dict | None = None
    poison = Counter()  # what poison did: times, the HP it took (and all the HP hits took), cures, guards spent
    for _ in range(max_turns):
        if state.over:
            break
        floor, monster = state.floor, state.room.monster
        if state.in_combat and (fight is None or fight["monster"] is not monster):
            fight = {"monster": monster, "floor": floor, "kind": kind_of(monster, content), "rounds": 0, "taken": 0,
                     "max_hp": state.player.max_hp, "hits": []}
        action = choose(state, content, who)
        events = perform(state, content, action)
        if fight is not None:
            fight["rounds"] += 1
            fight["taken"] += sum(e.data.get("damage", 0) for e in events if e.kind == "monster_hit")
            fight["hits"] += [e.data["damage"] for e in events
                              if e.kind == "hit" and action == "attack" and e.data.get("damage")]
            if not state.in_combat or state.room.monster is not fight["monster"] or state.floor != floor:
                fights.append(fight)
                fight = None
        for e in events:
            if e.kind == "status" and e.data.get("on"):
                poison["poisoned"] += 1
                poison[f"poisoned F{state.floor}"] += 1
            elif e.kind == "status_tick":
                poison["hp"] += e.data.get("damage", 0)
            elif e.kind == "monster_hit":
                poison["hits"] += e.data.get("damage", 0)
            elif e.kind == "cured":
                poison["shrine" if action == "shrine_pray" else "pure"] += 1
            elif e.kind == "guarded" and e.data.get("spent"):
                poison["guarded"] += 1
        turns_in[floor] += 1
        if state.floor != floor:  # down the stairs: how you went
            player = state.player
            left[floor] = {"hp": player.hp / player.max_hp, "level": player.level, "gold": player.gold,
                           "potions": potions(state), "keys": player.keys, "bombs": player.bombs,
                           "turns": turns_in[floor]}
        if state.status == "dead" and monster is not None:
            killer = monster.name
    return {"seed": seed, "status": state.status, "floor": state.floor, "level": state.player.level,
            "turns": state.turn, "left": left, "killer": killer, "gold": state.player.gold,
            "potions": potions(state), "keys": state.player.keys, "bombs": state.player.bombs,
            "kills": state.player.kills, "poison": poison,
            "died_poisoned": state.status == "dead" and bool(state.player.statuses), "fights": fights}


def median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def report(results: list[dict], floors: int, fights: bool = False) -> str:
    n = len(results)
    won = sum(r["status"] == "won" for r in results)
    stuck = sum(r["status"] == "playing" for r in results)
    lines = [f"{n} bot runs · won {won} ({100 * won / n:.0f}%) · stuck {stuck}", ""]
    lines.append(f"{'floor':>5} {'reached':>8} {'died':>6} {'death%':>7} {'HP% at stairs':>14} {'level':>6} "
                 f"{'gold':>6} {'potions':>8} {'keys':>5} {'bombs':>6} {'turns':>6}")
    for floor in range(1, floors + 1):
        reached = [r for r in results if r["floor"] >= floor]
        died = [r for r in reached if r["status"] == "dead" and r["floor"] == floor]
        out = [r["left"][floor] for r in reached if floor in r["left"]]
        rate = 100 * len(died) / len(reached) if reached else 0
        row = f"{floor:>5} {len(reached):>8} {len(died):>6} {rate:>6.0f}% "
        if out:  # (the last floor has no stairs: it ends with its boss)
            row += (f"{100 * median([o['hp'] for o in out]):>13.0f}% {median([o['level'] for o in out]):>6.1f} "
                    f"{median([o['gold'] for o in out]):>6.0f} {median([o['potions'] for o in out]):>8.1f} "
                    f"{median([o['keys'] for o in out]):>5.1f} {median([o['bombs'] for o in out]):>6.1f} "
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
                 f"median potions left {median([r['potions'] for r in results]):.1f} · "
                 f"keys {median([r['keys'] for r in results]):.1f} · "
                 f"bombs {median([r['bombs'] for r in results]):.1f}")
    lines += poison_lines(results, floors)
    lines += fight_lines(results, floors) if fights else []
    return "\n".join(lines)


def fight_lines(results: list[dict], floors: int) -> list[str]:
    """How the fights went, by floor and kind of foe: how many, their rounds and the HP they cost (as a share of your
    most: the median, and the worst tenth's), and your hits (the median, and the best tenth's). A floor-4 fight that
    costs nothing is one nobody remembers (docs/plans/combat-and-balance.md §1)."""
    def tenth(values: list[float]) -> float:
        values = sorted(values)
        return values[min(len(values) - 1, int(0.9 * len(values)))] if values else 0.0

    by: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for r in results:
        for f in r["fights"]:
            by[(f["floor"], f["kind"])].append(f)
    lines = ["", "fights: how many · rounds (median, worst tenth) · HP lost (median, worst tenth) · your hit (median, "
                 "best tenth)"]
    for floor in range(1, floors + 1):
        for kind in ("normal", "elite", "warden", "character", "boss"):
            group = by.get((floor, kind))
            if not group:
                continue
            rounds = [f["rounds"] for f in group]
            lost = [100 * f["taken"] / f["max_hp"] for f in group]
            hits = [h for f in group for h in f["hits"]]
            lines.append(f"  F{floor} {kind:<9} {len(group):>5} · rounds {median(rounds):>4.1f} "
                         f"({tenth(rounds):>2.0f}) · HP lost {median(lost):>3.0f}% ({tenth(lost):>3.0f}%) · "
                         f"hit {median(hits):>4.1f} ({tenth(hits):>2.0f})")
    return lines


def poison_lines(results: list[dict], floors: int) -> list[str]:
    """How poison went (docs/plans/floor-4-and-statuses.md's targets: poisoned 2-4 times a run where there's venom,
    10-25% of the HP lost lost to it, under a third of deaths with it in you)."""
    total = Counter()
    for r in results:
        total.update(r["poison"])
    if not total["poisoned"]:
        return []
    hit = [r for r in results if r["poison"]["poisoned"]]
    dead = [r for r in results if r["status"] == "dead"]
    share = 100 * total["hp"] / max(1, total["hp"] + total["hits"])
    where = ", ".join(f"F{f}×{total[f'poisoned F{f}']}" for f in range(1, floors + 1) if total[f"poisoned F{f}"])
    line = (f"poison: {len(hit)} runs poisoned ({100 * len(hit) / len(results):.0f}%), "
            f"median {median([r['poison']['poisoned'] for r in hit]):.0f} times ({where}) · "
            f"{share:.0f}% of the HP lost lost to it · "
            f"cured by Pure {total['pure']}, a shrine {total['shrine']} · guards spent {total['guarded']} · "
            f"died poisoned {sum(r['died_poisoned'] for r in dead)} of {len(dead)} deaths")
    return ["", line]


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
    parser.add_argument("--veteran", action="store_true", help="a veteran's adventurer: every blessing, the Rabbit's "
                                                               "Foot, its perks picked as the owner's run did")
    parser.add_argument("--fights", action="store_true", help="how the fights went, by floor and kind of foe")
    parser.add_argument("--deep", action="store_true", help="five floors, as a run goes once you've won one")
    parser.add_argument("--venom", default="", help="monsters (keys, comma separated) to give a venomous bite, to "
                                                    "see what poison would do (\"all\": every roaming one)")
    args = parser.parse_args()
    content = load_content()
    venomous = [k for k, m in content.monsters.items() if m.roams] if args.venom == "all" else \
        [k for k in args.venom.split(",") if k]
    for key in venomous:  # (this run's content only: nothing's saved)
        monster = content.monster(key)
        content.monsters[key] = dataclasses.replace(monster, tricks=[*monster.tricks, "venom"])
    seeds = range(args.start, args.start + args.seeds)
    floors = DEEPEST if args.deep else FLOORS
    if args.compare:
        print(compare({name: [run(seed, content, name, veteran_run=args.veteran, floors=floors) for seed in seeds]
                       for name in PLAYERS}, floors))
        return
    print(report([run(seed, content, args.player, veteran_run=args.veteran, floors=floors) for seed in seeds], floors,
                 args.fights))


if __name__ == "__main__":
    main()
