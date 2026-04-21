"""CLI: ingest a GPX file (or directory of GPX files) for a named user.

Usage:
    python scripts/ingest.py --user theo data/raw/tracks/theo/file.gpx
    python scripts/ingest.py --user theo --dir data/raw/tracks/theo/
    python scripts/ingest.py --dir data/raw/tracks/theo/   # infers user from dir name
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from powpal.gpx_parser import (  # noqa: E402
    parse_gpx,
    to_geodataframe,
    validate_gpx_stats,
)
from powpal.piste_matcher import (  # noqa: E402
    assign_nearest_piste,
    load_pistes,
)
from powpal.run_segmenter import segment_and_filter  # noqa: E402
from powpal.timing import make_timed_run  # noqa: E402

PISTE_GEOJSON = ROOT / "data" / "raw" / "pistes" / "vicheres_liddes.geojson"
USERS_JSON = ROOT / "users.json"
DB_PATH = ROOT / "data" / "processed" / "powpal.db"


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            slug TEXT UNIQUE,
            display_name TEXT,
            colour TEXT
        );
        CREATE TABLE IF NOT EXISTS pistes (
            id INTEGER PRIMARY KEY,
            osm_id TEXT UNIQUE,
            resort TEXT,
            name TEXT,
            difficulty TEXT
        );
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            piste_id INTEGER REFERENCES pistes(id),
            run_date DATE,
            duration_seconds REAL,
            source_file TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS track_points (
            id INTEGER PRIMARY KEY,
            run_id INTEGER REFERENCES runs(id) ON DELETE CASCADE,
            seq INTEGER,
            timestamp TEXT,
            lat REAL,
            lon REAL,
            elevation_m REAL,
            speed_ms REAL
        );
        CREATE INDEX IF NOT EXISTS idx_track_points_run_id
            ON track_points(run_id);
        CREATE TABLE IF NOT EXISTS rejected_runs (
            id INTEGER PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            piste_id INTEGER REFERENCES pistes(id),
            run_date DATE,
            duration_seconds REAL,
            source_file TEXT,
            filter_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS rejected_track_points (
            id INTEGER PRIMARY KEY,
            rejected_run_id INTEGER REFERENCES rejected_runs(id) ON DELETE CASCADE,
            seq INTEGER,
            timestamp TEXT,
            lat REAL,
            lon REAL,
            elevation_m REAL,
            speed_ms REAL
        );
        CREATE INDEX IF NOT EXISTS idx_rejected_track_points_run_id
            ON rejected_track_points(rejected_run_id);
    """)
    con.commit()


def get_or_create_user(
    con: sqlite3.Connection, slug: str, users: list
) -> int:
    row = con.execute(
        "SELECT id FROM users WHERE slug = ?", (slug,)
    ).fetchone()
    if row:
        return row[0]

    user = next((u for u in users if u["slug"] == slug), None)
    if user is None:
        sys.exit(f"Error: user '{slug}' not found in users.json")

    con.execute(
        "INSERT INTO users (slug, display_name, colour) VALUES (?, ?, ?)",
        (user["slug"], user["display_name"], user["colour"]),
    )
    con.commit()
    return con.execute(
        "SELECT id FROM users WHERE slug = ?", (slug,)
    ).fetchone()[0]


def get_or_create_piste(
    con: sqlite3.Connection, osm_id: str, name: str | None, difficulty: str
) -> int:
    row = con.execute(
        "SELECT id FROM pistes WHERE osm_id = ?", (osm_id,)
    ).fetchone()
    if row:
        return row[0]

    con.execute(
        "INSERT INTO pistes (osm_id, resort, name, difficulty) "
        "VALUES (?, ?, ?, ?)",
        (osm_id, "vicheres-liddes", name, difficulty),
    )
    con.commit()
    return con.execute(
        "SELECT id FROM pistes WHERE osm_id = ?", (osm_id,)
    ).fetchone()[0]


def _write_track_points(
    con: sqlite3.Connection,
    table: str,
    id_col: str,
    row_id: int,
    gdf: "gpd.GeoDataFrame",
    start_time,
    end_time,
) -> int:
    """Slice gdf to [start_time, end_time], compute speed, insert into table.

    Returns the number of points written.
    """
    import geopandas as gpd  # noqa: F401 — type hint only above

    mask = (gdf["timestamp"] >= start_time) & (gdf["timestamp"] <= end_time)
    pts = gdf[mask].sort_values("timestamp").reset_index(drop=True)

    if len(pts) > 1:
        pts_proj = pts.to_crs("EPSG:2056")
        dist_m = pts_proj.geometry.distance(pts_proj.geometry.shift()).fillna(0)
        dt_s = (
            pd.Series(pts["timestamp"].values)
            .diff()
            .dt.total_seconds()
            .fillna(0.001)
            .clip(lower=0.001)
        )
        speed = dist_m.values / dt_s.values
    else:
        speed = [0.0] * len(pts)

    con.executemany(
        f"INSERT INTO {table} ({id_col}, seq, timestamp, lat, lon, elevation_m, speed_ms)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                row_id,
                i,
                str(pts.loc[i, "timestamp"]),
                float(pts.loc[i, "lat"]),
                float(pts.loc[i, "lon"]),
                float(pts.loc[i, "elevation_m"]),
                float(speed[i]),
            )
            for i in range(len(pts))
        ],
    )
    return len(pts)


def ingest_file(
    gpx_path: Path, user_slug: str, users: list, pistes, con: sqlite3.Connection
) -> None:
    print(f"\nParsing {gpx_path.name}...")
    points = parse_gpx(gpx_path)
    stats = validate_gpx_stats(points)
    print(f"  {stats}")
    if "warnings" in stats:
        print(f"  WARNINGS: {stats['warnings']}")

    print("  Assigning nearest piste to each point...")
    gdf = to_geodataframe(points)
    gdf = assign_nearest_piste(gdf, pistes)

    print("  Segmenting and filtering runs...")
    run_stats, rejected_stats = segment_and_filter(gdf, pistes)
    print(f"  Found {len(run_stats)} valid runs, {len(rejected_stats)} rejected")

    user_id = get_or_create_user(con, user_slug, users)

    for _, row in run_stats.iterrows():
        timed = make_timed_run(row.to_dict(), gpx_path.name)
        piste_db_id = get_or_create_piste(
            con,
            osm_id=timed.piste_id,
            name=timed.piste_name,
            difficulty=timed.piste_difficulty,
        )
        run_date = timed.start_time.date().isoformat()
        con.execute(
            "INSERT INTO runs "
            "(user_id, piste_id, run_date, duration_seconds, source_file) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, piste_db_id, run_date, timed.duration_s, gpx_path.name),
        )
        run_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        n_pts = _write_track_points(
            con, "track_points", "run_id", run_id,
            gdf, timed.start_time, timed.end_time,
        )
        label = timed.piste_name or timed.piste_id
        print(f"  Stored: {label} — {timed.duration_s:.0f}s ({n_pts} pts)")

    for _, row in rejected_stats.iterrows():
        timed = make_timed_run(row.to_dict(), gpx_path.name)
        piste_db_id = get_or_create_piste(
            con,
            osm_id=timed.piste_id,
            name=timed.piste_name,
            difficulty=timed.piste_difficulty,
        )
        run_date = timed.start_time.date().isoformat()
        con.execute(
            "INSERT INTO rejected_runs "
            "(user_id, piste_id, run_date, duration_seconds, source_file, filter_reason) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                user_id, piste_db_id, run_date, timed.duration_s,
                gpx_path.name, row["filter_reason"],
            ),
        )
        rejected_run_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        _write_track_points(
            con, "rejected_track_points", "rejected_run_id", rejected_run_id,
            gdf, timed.start_time, timed.end_time,
        )

    con.commit()


def purge_before(con: sqlite3.Connection, date_str: str) -> None:
    """Delete all runs before a given date (YYYY-MM-DD), with confirmation."""
    try:
        # Basic format validation
        year, month, day = date_str.split("-")
        if not (len(year) == 4 and len(month) == 2 and len(day) == 2):
            raise ValueError
    except ValueError:
        sys.exit(f"Error: --purge-before date must be YYYY-MM-DD, got '{date_str}'")

    count = con.execute(
        "SELECT COUNT(*) FROM runs WHERE run_date < ?", (date_str,)
    ).fetchone()[0]

    if count == 0:
        print(f"No runs found before {date_str}. Nothing to delete.")
        return

    # Show a breakdown by user before asking
    rows = con.execute(
        """
        SELECT u.display_name, COUNT(*) as n
        FROM runs r JOIN users u ON r.user_id = u.id
        WHERE r.run_date < ?
        GROUP BY r.user_id
        ORDER BY u.display_name
        """,
        (date_str,),
    ).fetchall()
    print(f"\nRuns to delete (before {date_str}):")
    for display_name, n in rows:
        print(f"  {display_name}: {n} run(s)")
    print(f"  Total: {count} run(s)\n")

    answer = input("Delete these runs? [y/N] ").strip().lower()
    if answer != "y":
        print("Aborted.")
        return

    con.execute("DELETE FROM runs WHERE run_date < ?", (date_str,))
    con.commit()
    print(f"Deleted {count} run(s) before {date_str}.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest GPX file(s) into the powpal database."
    )
    parser.add_argument(
        "--user", help="User slug (must exist in users.json). Inferred from --dir name if omitted."
    )
    parser.add_argument(
        "--purge-before",
        metavar="YYYY-MM-DD",
        help="Delete all runs before this date, then exit.",
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("gpx_file", type=Path, nargs="?", help="Path to a single GPX file")
    group.add_argument("--dir", type=Path, help="Directory of GPX files to ingest")
    args = parser.parse_args()

    if args.purge_before and not args.gpx_file and not args.dir:
        # Purge-only mode — no ingestion
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(DB_PATH)
        con.execute("PRAGMA foreign_keys = ON")
        ensure_schema(con)
        purge_before(con, args.purge_before)
        con.close()
        return

    if not args.gpx_file and not args.dir:
        parser.error("one of gpx_file or --dir is required (unless using --purge-before alone)")

    if args.dir:
        gpx_files = sorted(args.dir.glob("*.gpx"))
        if not gpx_files:
            sys.exit(f"Error: no GPX files found in {args.dir}")
        user_slug = args.user or args.dir.resolve().name
    else:
        if not args.gpx_file.exists():
            sys.exit(f"Error: file not found: {args.gpx_file}")
        gpx_files = [args.gpx_file]
        if not args.user:
            sys.exit("Error: --user is required when ingesting a single file")
        user_slug = args.user

    users = json.loads(USERS_JSON.read_text())
    pistes = load_pistes(PISTE_GEOJSON)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")
    ensure_schema(con)

    if args.purge_before:
        purge_before(con, args.purge_before)

    for gpx_path in gpx_files:
        ingest_file(gpx_path, user_slug, users, pistes, con)

    con.close()
    print(f"\nDone. Ingested {len(gpx_files)} file(s) for user '{user_slug}'.")


if __name__ == "__main__":
    main()
