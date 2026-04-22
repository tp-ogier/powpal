"""Export powpal.db to a GeoPackage for QGIS.

Usage:
    python scripts/export_qgis.py
    python scripts/export_qgis.py --output my_export.gpkg

Layers written:
  pistes       — piste linestrings (from GeoJSON), with name/difficulty
  runs         — per-run linestrings (from track_points), with user/piste/duration metadata
  track_points — individual GPS points with seq, timestamp, elevation, speed
"""

import argparse
import sqlite3
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

PISTE_GEOJSON = ROOT / "data" / "raw" / "pistes" / "vicheres_liddes.geojson"
DB_PATH = ROOT / "data" / "processed" / "powpal.db"
DEFAULT_OUTPUT = ROOT / "data" / "processed" / "powpal_qgis.gpkg"


def export_pistes(gpkg_path: Path) -> None:
    gdf = gpd.read_file(PISTE_GEOJSON)
    gdf.to_file(gpkg_path, layer="pistes", driver="GPKG")
    print(f"  pistes: {len(gdf)} features")


def export_runs(con: sqlite3.Connection, gpkg_path: Path) -> None:
    rows = con.execute(
        """
        SELECT
            r.id         AS run_id,
            u.slug       AS user_slug,
            u.display_name,
            u.colour,
            p.osm_id     AS piste_osm_id,
            p.name       AS piste_name,
            p.difficulty AS piste_difficulty,
            r.run_date,
            r.duration_seconds,
            r.source_file
        FROM runs r
        JOIN users u ON r.user_id = u.id
        JOIN pistes p ON r.piste_id = p.id
        ORDER BY r.id
        """
    ).fetchall()

    if not rows:
        print("  runs: 0 features (no data)")
        return

    col_names = [
        "run_id", "user_slug", "display_name", "colour",
        "piste_osm_id", "piste_name", "piste_difficulty",
        "run_date", "duration_seconds", "source_file",
    ]
    df = pd.DataFrame(rows, columns=col_names)

    # Build per-run linestrings from track_points
    tp_rows = con.execute(
        "SELECT run_id, lon, lat FROM track_points ORDER BY run_id, seq"
    ).fetchall()

    from collections import defaultdict
    run_coords: dict[int, list] = defaultdict(list)
    for run_id, lon, lat in tp_rows:
        run_coords[run_id].append((lon, lat))

    def make_geom(run_id):
        coords = run_coords.get(run_id, [])
        if len(coords) >= 2:
            return LineString(coords)
        elif len(coords) == 1:
            return Point(coords[0])
        return None

    df["geometry"] = df["run_id"].apply(make_geom)
    valid = df[df["geometry"].notna()].copy()

    if valid.empty:
        print("  runs: 0 features (no track points recorded — re-ingest files to populate)")
        return

    gdf = gpd.GeoDataFrame(valid, geometry="geometry", crs="EPSG:4326")
    gdf.to_file(gpkg_path, layer="runs", driver="GPKG")
    print(f"  runs: {len(gdf)} features")


def export_track_points(con: sqlite3.Connection, gpkg_path: Path) -> None:
    rows = con.execute(
        """
        SELECT
            tp.id,
            tp.run_id,
            tp.seq,
            tp.timestamp,
            tp.lat,
            tp.lon,
            tp.elevation_m,
            tp.speed_ms,
            u.slug       AS user_slug,
            u.display_name,
            p.id         AS piste_db_id,
            p.osm_id     AS piste_osm_id,
            p.name       AS piste_name,
            p.difficulty AS piste_difficulty,
            r.run_date
        FROM track_points tp
        JOIN runs r ON tp.run_id = r.id
        JOIN users u ON r.user_id = u.id
        JOIN pistes p ON r.piste_id = p.id
        ORDER BY tp.run_id, tp.seq
        """
    ).fetchall()

    if not rows:
        print("  track_points: 0 features (no data — re-ingest files to populate)")
        return

    col_names = [
        "id", "run_id", "seq", "timestamp", "lat", "lon",
        "elevation_m", "speed_ms", "user_slug", "display_name",
        "piste_db_id", "piste_osm_id", "piste_name", "piste_difficulty", "run_date",
    ]
    df = pd.DataFrame(rows, columns=col_names)
    gdf = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df["lon"], df["lat"]),
        crs="EPSG:4326",
    )
    gdf = gdf.drop(columns=["lat", "lon"])
    gdf.to_file(gpkg_path, layer="track_points", driver="GPKG")
    print(f"  track_points: {len(gdf)} features")


def export_rejected_runs(con: sqlite3.Connection, gpkg_path: Path) -> None:
    rows = con.execute(
        """
        SELECT
            rr.id        AS rejected_run_id,
            rr.filter_reason,
            u.slug       AS user_slug,
            u.display_name,
            p.id         AS piste_db_id,
            p.osm_id     AS piste_osm_id,
            p.name       AS piste_name,
            p.difficulty AS piste_difficulty,
            rr.run_date,
            rr.duration_seconds,
            rr.source_file
        FROM rejected_runs rr
        JOIN users u ON rr.user_id = u.id
        JOIN pistes p ON rr.piste_id = p.id
        ORDER BY rr.id
        """
    ).fetchall()

    if not rows:
        print("  rejected_runs: 0 features")
        return

    col_names = [
        "rejected_run_id", "filter_reason", "user_slug", "display_name",
        "piste_db_id", "piste_osm_id", "piste_name", "piste_difficulty",
        "run_date", "duration_seconds", "source_file",
    ]
    df = pd.DataFrame(rows, columns=col_names)

    tp_rows = con.execute(
        "SELECT rejected_run_id, lon, lat FROM rejected_track_points"
        " ORDER BY rejected_run_id, seq"
    ).fetchall()

    from collections import defaultdict
    run_coords: dict[int, list] = defaultdict(list)
    for run_id, lon, lat in tp_rows:
        run_coords[run_id].append((lon, lat))

    from shapely.geometry import LineString, Point

    def make_geom(run_id):
        coords = run_coords.get(run_id, [])
        if len(coords) >= 2:
            return LineString(coords)
        elif len(coords) == 1:
            return Point(coords[0])
        return None

    df["geometry"] = df["rejected_run_id"].apply(make_geom)
    valid = df[df["geometry"].notna()].copy()

    if valid.empty:
        print("  rejected_runs: 0 features (no track points)")
        return

    gdf = gpd.GeoDataFrame(valid, geometry="geometry", crs="EPSG:4326")
    gdf.to_file(gpkg_path, layer="rejected_runs", driver="GPKG")
    print(f"  rejected_runs: {len(gdf)} features")


def export_rejected_track_points(con: sqlite3.Connection, gpkg_path: Path) -> None:
    rows = con.execute(
        """
        SELECT
            tp.id,
            tp.rejected_run_id,
            tp.seq,
            tp.timestamp,
            tp.lat,
            tp.lon,
            tp.elevation_m,
            tp.speed_ms,
            rr.filter_reason,
            u.slug       AS user_slug,
            u.display_name,
            p.id         AS piste_db_id,
            p.osm_id     AS piste_osm_id,
            p.name       AS piste_name,
            p.difficulty AS piste_difficulty,
            rr.run_date
        FROM rejected_track_points tp
        JOIN rejected_runs rr ON tp.rejected_run_id = rr.id
        JOIN users u ON rr.user_id = u.id
        JOIN pistes p ON rr.piste_id = p.id
        ORDER BY tp.rejected_run_id, tp.seq
        """
    ).fetchall()

    if not rows:
        print("  rejected_track_points: 0 features")
        return

    col_names = [
        "id", "rejected_run_id", "seq", "timestamp", "lat", "lon",
        "elevation_m", "speed_ms", "filter_reason", "user_slug", "display_name",
        "piste_db_id", "piste_osm_id", "piste_name", "piste_difficulty", "run_date",
    ]
    df = pd.DataFrame(rows, columns=col_names)
    gdf = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df["lon"], df["lat"]),
        crs="EPSG:4326",
    )
    gdf = gdf.drop(columns=["lat", "lon"])
    gdf.to_file(gpkg_path, layer="rejected_track_points", driver="GPKG")
    print(f"  rejected_track_points: {len(gdf)} features")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export powpal.db to a GeoPackage for QGIS."
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"Output GeoPackage path (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    if not DB_PATH.exists():
        sys.exit(f"Error: database not found at {DB_PATH}. Run ingest.py first.")

    if not PISTE_GEOJSON.exists():
        sys.exit(f"Error: piste GeoJSON not found at {PISTE_GEOJSON}")

    args.output.parent.mkdir(parents=True, exist_ok=True)

    # Remove existing file so we can write fresh layers
    if args.output.exists():
        args.output.unlink()

    con = sqlite3.connect(DB_PATH)
    print(f"Exporting to {args.output} ...")

    export_pistes(args.output)
    export_runs(con, args.output)
    export_track_points(con, args.output)
    export_rejected_runs(con, args.output)
    export_rejected_track_points(con, args.output)

    con.close()
    print("Done.")


if __name__ == "__main__":
    main()
