"""Tests for powpal.piste_matcher."""

from pathlib import Path

import geopandas as gpd

from powpal.gpx_parser import parse_gpx, to_geodataframe
from powpal.piste_matcher import assign_nearest_piste, load_pistes

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "Slopes_A_day_snowboarding_at_Vichères_Liddes.gpx"
)
PISTE_GEOJSON = (
    Path(__file__).parent.parent
    / "data" / "raw" / "pistes" / "vicheres_liddes.geojson"
)


def test_load_pistes_returns_geodataframe():
    pistes = load_pistes(PISTE_GEOJSON)
    assert isinstance(pistes, gpd.GeoDataFrame)
    assert len(pistes) > 0


def test_pistes_have_required_columns():
    pistes = load_pistes(PISTE_GEOJSON)
    for col in ("id", "piste:difficulty", "name"):
        assert col in pistes.columns


def test_assign_nearest_adds_piste_columns():
    points = parse_gpx(FIXTURE)
    gdf = to_geodataframe(points)
    pistes = load_pistes(PISTE_GEOJSON)
    result = assign_nearest_piste(gdf, pistes)
    for col in ("piste_idx", "piste_id", "piste_difficulty", "piste_name",
                "distance_to_piste_m"):
        assert col in result.columns


def test_no_duplicates_after_join():
    points = parse_gpx(FIXTURE)
    gdf = to_geodataframe(points)
    pistes = load_pistes(PISTE_GEOJSON)
    result = assign_nearest_piste(gdf, pistes)
    assert not result.index.duplicated().any()


def test_all_points_get_a_piste():
    points = parse_gpx(FIXTURE)
    gdf = to_geodataframe(points)
    pistes = load_pistes(PISTE_GEOJSON)
    result = assign_nearest_piste(gdf, pistes)
    assert result["piste_id"].notna().all()


def test_crs_preserved():
    points = parse_gpx(FIXTURE)
    gdf = to_geodataframe(points)
    pistes = load_pistes(PISTE_GEOJSON)
    result = assign_nearest_piste(gdf, pistes)
    assert result.crs.to_epsg() == 4326
