"""Aggregate best times and build leaderboard data structures."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List


@dataclass
class LeaderboardEntry:
    """A single row in a per-piste best-time leaderboard."""

    rank: int
    user_slug: str
    display_name: str
    colour: str
    best_time_seconds: float


@dataclass
class MetaStatEntry:
    """A single row in a meta-stat leaderboard (days, pistes, king count)."""

    rank: int
    user_slug: str
    display_name: str
    colour: str
    value: int


def get_leaderboard(db_path: Path, piste_id: int) -> List[LeaderboardEntry]:
    """Return ranked leaderboard for a single piste."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    rows = con.execute(
        """
        SELECT u.slug, u.display_name, u.colour, MIN(r.duration_seconds) AS best_time
        FROM runs r
        JOIN users u ON r.user_id = u.id
        WHERE r.piste_id = ?
        GROUP BY r.user_id
        ORDER BY best_time ASC
        LIMIT 5
        """,
        (piste_id,),
    ).fetchall()

    con.close()

    return [
        LeaderboardEntry(
            rank=i + 1,
            user_slug=row["slug"],
            display_name=row["display_name"],
            colour=row["colour"],
            best_time_seconds=row["best_time"],
        )
        for i, row in enumerate(rows)
    ]


def get_all_piste_ids(db_path: Path) -> List[int]:
    """Return all piste IDs that have at least one recorded run."""
    con = sqlite3.connect(db_path)
    rows = con.execute("SELECT DISTINCT piste_id FROM runs").fetchall()
    con.close()
    return [r[0] for r in rows]


def get_map_data(db_path: Path) -> dict:
    """Return all data needed for the interactive map as a JSON-serialisable dict.

    Keys:
      users  — {user_id: {display_name, colour}}
      pistes — {piste_id: {name, difficulty, osm_id}}
      runs   — [{user_id, piste_id, run_date, duration_seconds}, ...]
    """
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    users = {
        row["id"]: {"display_name": row["display_name"], "colour": row["colour"]}
        for row in con.execute(
            "SELECT id, display_name, colour FROM users"
        ).fetchall()
    }

    pistes = {
        row["id"]: {
            "name": row["name"],
            "difficulty": row["difficulty"],
            "osm_id": row["osm_id"],
        }
        for row in con.execute(
            "SELECT id, name, difficulty, osm_id FROM pistes"
        ).fetchall()
    }

    runs = [
        {
            "user_id": row["user_id"],
            "piste_id": row["piste_id"],
            "run_date": row["run_date"],
            "duration_seconds": row["duration_seconds"],
        }
        for row in con.execute(
            "SELECT user_id, piste_id, run_date, duration_seconds FROM runs"
        ).fetchall()
    ]

    con.close()
    return {"users": users, "pistes": pistes, "runs": runs}


def get_total_days(db_path: Path) -> List[MetaStatEntry]:
    """Return users ranked by total distinct ski days recorded."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT u.slug, u.display_name, u.colour,
               COUNT(DISTINCT r.run_date) AS total_days
        FROM runs r
        JOIN users u ON r.user_id = u.id
        GROUP BY r.user_id
        ORDER BY total_days DESC
        """
    ).fetchall()
    con.close()
    return [
        MetaStatEntry(
            rank=i + 1,
            user_slug=row["slug"],
            display_name=row["display_name"],
            colour=row["colour"],
            value=row["total_days"],
        )
        for i, row in enumerate(rows)
    ]


def get_total_pistes(db_path: Path) -> List[MetaStatEntry]:
    """Return users ranked by total number of runs recorded."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT u.slug, u.display_name, u.colour,
               COUNT(*) AS total_runs
        FROM runs r
        JOIN users u ON r.user_id = u.id
        GROUP BY r.user_id
        ORDER BY total_runs DESC
        """
    ).fetchall()
    con.close()
    return [
        MetaStatEntry(
            rank=i + 1,
            user_slug=row["slug"],
            display_name=row["display_name"],
            colour=row["colour"],
            value=row["total_runs"],
        )
        for i, row in enumerate(rows)
    ]


@dataclass
class MedalEntry:
    """A single row in the medals leaderboard (gold/silver/bronze counts)."""

    rank: int
    user_slug: str
    display_name: str
    colour: str
    gold: int
    silver: int
    bronze: int


def get_medals(db_path: Path) -> List[MedalEntry]:
    """Return users ranked by gold, then silver, then bronze count."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        WITH best_per_piste AS (
            SELECT piste_id, user_id, MIN(duration_seconds) AS best_time,
                   ROW_NUMBER() OVER (
                       PARTITION BY piste_id ORDER BY MIN(duration_seconds)
                   ) AS rn
            FROM runs
            GROUP BY piste_id, user_id
        )
        SELECT u.slug, u.display_name, u.colour,
               COUNT(CASE WHEN b.rn = 1 THEN 1 END) AS gold,
               COUNT(CASE WHEN b.rn = 2 THEN 1 END) AS silver,
               COUNT(CASE WHEN b.rn = 3 THEN 1 END) AS bronze
        FROM best_per_piste b
        JOIN users u ON b.user_id = u.id
        GROUP BY b.user_id
        ORDER BY gold DESC, silver DESC, bronze DESC
        """
    ).fetchall()
    con.close()
    return [
        MedalEntry(
            rank=i + 1,
            user_slug=row["slug"],
            display_name=row["display_name"],
            colour=row["colour"],
            gold=row["gold"],
            silver=row["silver"],
            bronze=row["bronze"],
        )
        for i, row in enumerate(rows)
    ]
