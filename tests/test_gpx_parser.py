"""Tests for powpal.gpx_parser."""

from pathlib import Path

from powpal.gpx_parser import (
    TrackPoint,
    parse_gpx,
    to_geodataframe,
    validate_gpx_stats,
)

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "Slopes_A_day_snowboarding_at_Vichères_Liddes.gpx"
)


def test_parse_returns_trackpoints():
    points = parse_gpx(FIXTURE)
    assert len(points) > 0
    assert all(isinstance(p, TrackPoint) for p in points)


def test_parse_no_missing_timestamps():
    points = parse_gpx(FIXTURE)
    assert all(p.timestamp is not None for p in points)


def test_parse_no_missing_elevation():
    points = parse_gpx(FIXTURE)
    assert all(p.elevation is not None for p in points)


def test_to_geodataframe_shape():
    import geopandas as gpd
    points = parse_gpx(FIXTURE)
    gdf = to_geodataframe(points)
    assert isinstance(gdf, gpd.GeoDataFrame)
    assert len(gdf) == len(points)
    assert gdf.crs.to_epsg() == 4326


def test_validate_stats_keys():
    points = parse_gpx(FIXTURE)
    stats = validate_gpx_stats(points)
    for key in ("n_points", "duration_hours", "elevation_range_m",
                "max_speed_kmh"):
        assert key in stats


def test_validate_stats_reasonable_values():
    points = parse_gpx(FIXTURE)
    stats = validate_gpx_stats(points)
    assert stats["n_points"] > 100
    assert stats["elevation_range_m"] > 50
    assert 0 < stats["duration_hours"] < 24
