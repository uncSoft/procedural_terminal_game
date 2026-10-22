"""Everything that outlives a run, in SQLite (~/.ptg/profile.db): souls, unlocks, the Hall of Legends,
the bestiary, restless ghosts, and a log of every turn."""

from __future__ import annotations

import json
import random
import sqlite3
import time
from pathlib import Path

from .config import home

SCHEMA = """
create table if not exists meta (key text primary key, value text not null);
create table if not exists runs (
    id integer primary key autoincrement,
    seed integer, name text, daily text default '', started real, ended real,
    status text default 'playing', floor integer default 1, level integer default 1,
    kills integer default 0, gold integer default 0, souls integer default 0, turns integer default 0,
    cause text default '', epitaph text default '', epithet text default '',
    traits text default '[]', perks text default '[]', themes text default '[]'
);
create table if not exists unlocks (key text primary key, unlocked real);
create table if not exists bestiary (
    monster text primary key, seen integer default 0, killed integer default 0, pacified integer default 0,
    killed_you integer default 0, weak text default '[]', lore text default '', first_seen real
);
create table if not exists ghosts (
    id integer primary key autoincrement, run_id integer, name text, level integer, floor integer,
    items text default '[]', gold integer default 0, epitaph text default '', cause text default '',
    status text default 'restless'
);
create table if not exists turns (run_id integer, turn integer, kind text, text text);
create table if not exists story_seen (event text primary key, count integer default 0, first_at real);
create table if not exists marks (key text primary key, set_at real);
create table if not exists secrets (event text primary key, found_at real, run_id integer);
"""


class Profile:
    def __init__(self, path: Path | str):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    @classmethod
    def open(cls) -> Profile:
        return cls(home() / "profile.db")

    def close(self) -> None:
        self.db.close()

    # --- meta values ---

    def get(self, key: str, default: str = "") -> str:
        row = self.db.execute("select value from meta where key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set(self, key: str, value: object) -> None:
        self.db.execute("insert into meta values (?, ?) on conflict(key) do update set value = excluded.value",
                        (key, str(value)))
        self.db.commit()

    @property
    def souls(self) -> int:
        return int(self.get("souls", "0"))

    def add_souls(self, amount: int) -> None:
        self.set("souls", self.souls + amount)

    @property
    def gift(self) -> str:
        return self.get("gift", "coin_bag")

    # --- unlocks ---

    def unlocked(self) -> set[str]:
        return {row["key"] for row in self.db.execute("select key from unlocks")} | {"coin_bag"}

    def buy(self, key: str, cost: int) -> bool:
        if key in self.unlocked() or self.souls < cost:
            return False
        self.set("souls", self.souls - cost)
        self.db.execute("insert into unlocks values (?, ?)", (key, time.time()))
        self.db.commit()
        return True

    # --- runs ---

    def start_run(self, seed: int, name: str, themes: list[str], daily: str = "") -> int:
        cursor = self.db.execute("insert into runs (seed, name, daily, started, themes) values (?, ?, ?, ?, ?)",
                                 (seed, name, daily, time.time(), json.dumps(themes)))
        self.db.commit()
        return int(cursor.lastrowid)

    def finish_run(self, run_id: int, **fields) -> None:
        for key in ("traits", "perks"):
            if key in fields:
                fields[key] = json.dumps(fields[key])
        fields["ended"] = time.time()
        assignments = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"update runs set {assignments} where id = ?", (*fields.values(), run_id))
        self.db.commit()

    def runs(self, limit: int = 20, finished: bool = True) -> list[dict]:
        where = "where status != 'playing'" if finished else ""
        rows = self.db.execute(f"select * from runs {where} order by id desc limit ?", (limit,))
        return [dict(r) for r in rows]

    def run(self, run_id: int) -> dict | None:
        row = self.db.execute("select * from runs where id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def daily_run(self, date: str) -> dict | None:
        row = self.db.execute("select * from runs where daily = ? and status != 'playing' order by id limit 1",
                              (date,)).fetchone()
        return dict(row) if row else None

    def totals(self) -> dict:
        row = self.db.execute("select count(*) runs, sum(status = 'won') wins, sum(kills) kills, "
                              "max(floor) deepest from runs where status != 'playing'").fetchone()
        return {k: (row[k] or 0) for k in ("runs", "wins", "kills", "deepest")}

    # --- turn log ---

    def log(self, run_id: int | None, turn: int, entries: list[tuple[str, str]]) -> None:
        if run_id is None or not entries:
            return
        self.db.executemany("insert into turns values (?, ?, ?, ?)", [(run_id, turn, k, t) for k, t in entries])
        self.db.commit()

    # --- bestiary ---

    def _beast(self, monster: str) -> None:
        self.db.execute("insert or ignore into bestiary (monster, first_seen) values (?, ?)", (monster, time.time()))

    def bump_beast(self, monster: str, column: str) -> int:
        """Increment seen/killed/pacified/killed_you; returns the new count."""
        assert column in ("seen", "killed", "pacified", "killed_you")
        self._beast(monster)
        self.db.execute(f"update bestiary set {column} = {column} + 1 where monster = ?", (monster,))
        self.db.commit()
        return int(self.db.execute(f"select {column} from bestiary where monster = ?", (monster,)).fetchone()[0])

    def add_weakness(self, monster: str, tag: str) -> None:
        self._beast(monster)
        known = self.weaknesses().get(monster, [])
        if tag not in known:
            self.db.execute("update bestiary set weak = ? where monster = ?", (json.dumps(known + [tag]), monster))
            self.db.commit()

    def weaknesses(self) -> dict[str, list[str]]:
        return {r["monster"]: json.loads(r["weak"]) for r in self.db.execute("select monster, weak from bestiary")}

    def set_lore(self, monster: str, lore: str) -> None:
        self._beast(monster)
        self.db.execute("update bestiary set lore = ? where monster = ?", (lore, monster))
        self.db.commit()

    def bestiary(self) -> dict[str, dict]:
        return {r["monster"]: {**dict(r), "weak": json.loads(r["weak"])}
                for r in self.db.execute("select * from bestiary")}

    # --- story memory (survives death) ---

    def story_seen(self) -> set[str]:
        return {r["event"] for r in self.db.execute("select event from story_seen")}

    def mark_seen(self, event: str) -> None:
        self.db.execute("insert into story_seen (event, count, first_at) values (?, 1, ?) "
                        "on conflict(event) do update set count = count + 1", (event, time.time()))
        self.db.commit()

    def marks(self) -> set[str]:
        return {r["key"] for r in self.db.execute("select key from marks")}

    def set_mark(self, key: str) -> None:
        self.db.execute("insert or ignore into marks values (?, ?)", (key, time.time()))
        self.db.commit()

    def secrets(self) -> dict[str, float]:
        """Book of Secrets: event id -> when it was found."""
        return {r["event"]: r["found_at"] for r in self.db.execute("select event, found_at from secrets")}

    def add_secret(self, event: str, run_id: int | None) -> bool:
        cursor = self.db.execute("insert or ignore into secrets values (?, ?, ?)", (event, time.time(), run_id))
        self.db.commit()
        return cursor.rowcount > 0

    # --- ghosts ---

    def add_ghost(self, run_id: int, name: str, level: int, floor: int, items: list[str], gold: int,
                  epitaph: str, cause: str) -> None:
        self.db.execute("insert into ghosts (run_id, name, level, floor, items, gold, epitaph, cause) "
                        "values (?, ?, ?, ?, ?, ?, ?, ?)",
                        (run_id, name, level, floor, json.dumps(items), gold, epitaph, cause))
        self.db.commit()

    def pick_ghost(self, rng: random.Random, chance: float = 0.6) -> dict | None:
        rows = [dict(r) for r in self.db.execute("select * from ghosts where status = 'restless' order by id desc limit 5")]
        if not rows or rng.random() > chance:
            return None
        ghost = rng.choice(rows)
        ghost["items"] = json.loads(ghost["items"])
        return ghost

    def rest_ghost(self, ghost_id: int) -> None:
        self.db.execute("update ghosts set status = 'rested' where id = ?", (ghost_id,))
        self.db.commit()
