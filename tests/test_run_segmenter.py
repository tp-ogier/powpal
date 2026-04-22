"""Tests for powpal.run_segmenter."""

from pathlib import Path

from powpal.gpx_parser import parse_gpx, to_geodataframe
from powpal.piste_matcher import assign_nearest_piste, load_pistes
from powpal.run_segmenter import (
    ELEV_DROP_M,
    MIN_POINTS,
    segment_and_filter,
)

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "Slopes_A_day_snowboarding_at_Vichères_Liddes.gpx"
)
PISTE_GEOJSON = (
    Path(__file__).parent.parent
    / "data" / "raw" / "pistes" / "vicheres_liddes.geojson"
)


def _run_stats():
    points = parse_gpx(FIXTURE)
    gdf = to_geodataframe(points)
    pistes = load_pistes(PISTE_GEOJSON)
    gdf = assign_nearest_piste(gdf, pistes)
    return segment_and_filter(gdf)


def test_returns_dataframe():
    import pandas as pd
    assert isinstance(_run_stats(), pd.DataFrame)


def test_at_least_one_run():
    assert len(_run_stats()) >= 1


def test_all_descents():
    stats = _run_stats()
    assert (stats["elev_change_m"] < -ELEV_DROP_M).all()


def test_minimum_points():
    stats = _run_stats()
    assert (stats["n_points"] > MIN_POINTS).all()


def test_expected_columns():
    stats = _run_stats()
    for col in ("piste_id", "start_time", "end_time",
                "duration_s", "elev_change_m", "n_points"):
        assert col in stats.columns


def test_positive_duration():
    stats = _run_stats()
    assert (stats["duration_s"] > 0).all()
