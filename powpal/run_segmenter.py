"""Segment trackpoints into individual runs.

Logic (matching the original notebook):
  1. Sort points by time.
  2. Declare a new run when: time gap > GAP_SECONDS OR piste changes.
  3. Compute per-run stats (duration, distance, elevation change, n_points).
  4. Apply quality filters; record the reason for each rejection.

Returns a tuple (valid, rejected) where rejected has a filter_reason column.
"""

from __future__ import annotations

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

# Tuning constants — match notebook values
GAP_SECONDS = 180       # time gap that forces a new run
MIN_POINTS = 10         # minimum trackpoints for a valid run
ELEV_DROP_M = 25        # minimum elevation drop (descent) for a valid run

# Quality filters
MAX_FAR_POINTS = 5      # reject run if ≥ this many points are > FAR_DIST_M from piste
FAR_DIST_M = 100        # distance threshold for "far from piste"
ENDPOINT_DIST_M = 100   # run must have a point within this distance of each piste endpoint

PROJECTED_CRS = "EPSG:2056"


def segment_and_filter(
    points: gpd.GeoDataFrame,
    pistes: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Split piste-assigned trackpoints into valid and rejected descent runs.

    Expects columns: timestamp, elevation_m, piste_idx, distance_to_piste_m
    (output of assign_nearest_piste).

    Returns:
        (valid, rejected) — both DataFrames share the same columns;
        rejected additionally has a filter_reason column explaining why
        the run was dropped. First failing filter wins.

    Filter reasons:
        too_few_points              — n_points ≤ MIN_POINTS
        insufficient_elevation_drop — elev_change_m ≥ -ELEV_DROP_M
        too_many_far_points         — ≥ MAX_FAR_POINTS points > FAR_DIST_M from piste
        endpoint_not_reached        — track doesn't reach within ENDPOINT_DIST_M of
                                      both ends of the piste linestring
    """
    df = points.copy()
    df["timestamp"] = pd.to_datetime(
        df["timestamp"], utc=True, errors="coerce"
    )
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Time gap between consecutive points
    df["dt_sec"] = df["timestamp"].diff().dt.total_seconds()

    # New run condition: first point, time gap, or piste change
    prev_piste = df["piste_idx"].shift()
    piste_changed = df["piste_idx"] != prev_piste
    new_run = (
        df["dt_sec"].isna() | (df["dt_sec"] > GAP_SECONDS) | piste_changed
    )

    df["run_id"] = new_run.cumsum().astype(str)

    # Project for distance calculations
    df_proj = df.to_crs(PROJECTED_CRS)
    prev_geom = df_proj.groupby("run_id").geometry.shift()
    df["segment_m"] = df_proj.geometry.distance(prev_geom).fillna(0)

    # Aggregate per run
    run_stats = (
        df.groupby("run_id")
        .agg(
            piste_idx=("piste_idx", "first"),
            piste_id=("piste_id", "first"),
            piste_difficulty=("piste_difficulty", "first"),
            piste_name=("piste_name", "first"),
            start_time=("timestamp", "min"),
            end_time=("timestamp", "max"),
            distance_m=("segment_m", "sum"),
            elev_start=("elevation_m", "first"),
            elev_end=("elevation_m", "last"),
            n_points=("geometry", "size"),
        )
        .reset_index()
    )

    run_stats["duration_s"] = (
        (run_stats["end_time"] - run_stats["start_time"]).dt.total_seconds()
    )
    run_stats["elev_change_m"] = (
        run_stats["elev_end"] - run_stats["elev_start"]
    )

    all_runs = run_stats.copy()
    all_runs["filter_reason"] = pd.NA

    # --- Filter 1: basic descent quality ---
    untagged = all_runs["filter_reason"].isna()
    all_runs.loc[untagged & (all_runs["n_points"] <= MIN_POINTS), "filter_reason"] = (
        "too_few_points"
    )
    untagged = all_runs["filter_reason"].isna()
    all_runs.loc[
        untagged & (all_runs["elev_change_m"] >= -ELEV_DROP_M), "filter_reason"
    ] = "insufficient_elevation_drop"

    # --- Filter 2: too many points far from the piste ---
    far_counts = (
        df[df["distance_to_piste_m"] > FAR_DIST_M]
        .groupby("run_id")
        .size()
        .rename("far_point_count")
    )
    all_runs = all_runs.join(far_counts, on="run_id").fillna({"far_point_count": 0})
    untagged = all_runs["filter_reason"].isna()
    all_runs.loc[
        untagged & (all_runs["far_point_count"] >= MAX_FAR_POINTS), "filter_reason"
    ] = "too_many_far_points"

    # --- Filter 3: run must reach within ENDPOINT_DIST_M of both piste endpoints ---
    pistes_proj = pistes.to_crs(PROJECTED_CRS)
    df_proj_indexed = df_proj.copy()
    df_proj_indexed["run_id"] = df["run_id"]

    def covers_both_endpoints(row) -> bool:
        piste_geom = pistes_proj.iloc[int(row["piste_idx"])].geometry
        if piste_geom is None:
            return False
        coords = list(piste_geom.coords)
        start_pt = Point(coords[0])
        end_pt = Point(coords[-1])
        run_pts = df_proj_indexed[
            df_proj_indexed["run_id"] == row["run_id"]
        ].geometry
        near_start = run_pts.distance(start_pt).min() <= ENDPOINT_DIST_M
        near_end = run_pts.distance(end_pt).min() <= ENDPOINT_DIST_M
        return bool(near_start and near_end)

    still_valid = all_runs["filter_reason"].isna()
    for idx in all_runs[still_valid].index:
        if not covers_both_endpoints(all_runs.loc[idx]):
            all_runs.loc[idx, "filter_reason"] = "endpoint_not_reached"

    # Split into valid and rejected
    drop_cols = ["far_point_count"]
    valid = (
        all_runs[all_runs["filter_reason"].isna()]
        .drop(columns=drop_cols + ["filter_reason"])
        .reset_index(drop=True)
    )
    rejected = (
        all_runs[all_runs["filter_reason"].notna()]
        .drop(columns=drop_cols)
        .reset_index(drop=True)
    )

    return valid, rejected
