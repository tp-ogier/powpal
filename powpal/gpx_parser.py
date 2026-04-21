"""GPX parsing and trackpoint enrichment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

import geopandas as gpd
import gpxpy
import numpy as np
import pandas as pd
from shapely.geometry import Point


@dataclass
class TrackPoint:
    lat: float
    lon: float
    elevation: float
    timestamp: datetime


def parse_gpx(path: Path) -> List[TrackPoint]:
    """Parse a Slopes-exported GPX file into a list of TrackPoints.

    Drops points with missing timestamps or elevation.
    """
    with open(path, "r") as f:
        gpx = gpxpy.parse(f)

    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for pt in segment.points:
                if pt.time is None:
                    continue
                if pt.elevation is None:
                    continue
                points.append(TrackPoint(
                    lat=pt.latitude,
                    lon=pt.longitude,
                    elevation=pt.elevation,
                    timestamp=pt.time,
                ))
    return points


def to_geodataframe(
    points: List[TrackPoint], crs: str = "EPSG:4326"
) -> gpd.GeoDataFrame:
    """Convert a list of TrackPoints to a GeoDataFrame."""
    return gpd.GeoDataFrame(
        {
            "timestamp": [p.timestamp for p in points],
            "elevation_m": [p.elevation for p in points],
            "lat": [p.lat for p in points],
            "lon": [p.lon for p in points],
        },
        geometry=[Point(p.lon, p.lat) for p in points],
        crs=crs,
    )


def validate_gpx_stats(points: List[TrackPoint]) -> dict:
    """Sanity-check a parsed track. Returns a stats dict and flags anomalies."""
    if not points:
        return {"error": "no points"}

    n = len(points)
    duration_s = (points[-1].timestamp - points[0].timestamp).total_seconds()
    elevations = [p.elevation for p in points]

    # Compute horizontal speeds using projected coords
    gdf = to_geodataframe(points).to_crs("EPSG:3857")
    prev_geom = gdf.geometry.shift()
    dist_m = gdf.geometry.distance(prev_geom).fillna(0)
    timestamps = pd.Series([p.timestamp for p in points])
    dt_s = (
        timestamps.diff().dt.total_seconds().fillna(0.001).clip(lower=0.001)
    )
    speed_ms = dist_m / dt_s

    stats = {
        "n_points": n,
        "duration_hours": round(duration_s / 3600, 2),
        "elevation_range_m": round(max(elevations) - min(elevations), 1),
        "max_speed_kmh": round(float(speed_ms.max()) * 3.6, 1),
        "mean_speed_kmh": round(float(speed_ms.mean()) * 3.6, 1),
    }

    warnings = []
    if stats["elevation_range_m"] < 10:
        warnings.append("suspiciously low elevation range")
    if stats["max_speed_kmh"] > 250:
        warnings.append("impossibly high max speed")
    if stats["duration_hours"] == 0:
        warnings.append("zero duration")

    if warnings:
        stats["warnings"] = warnings

    return stats
