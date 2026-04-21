"""Assign each trackpoint to its nearest piste using a spatial join."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd

# Swiss national grid — accurate for distance calculations in the Alps
PROJECTED_CRS = "EPSG:2056"


def load_pistes(geojson_path: Path) -> gpd.GeoDataFrame:
    """Load piste GeoJSON in its native CRS (EPSG:4326)."""
    return gpd.read_file(geojson_path)


def assign_nearest_piste(
    points: gpd.GeoDataFrame,
    pistes: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Spatial join: attach the nearest piste to each trackpoint.

    Both inputs are projected to EPSG:2056 for accurate distance
    calculation, then the result is returned in the original CRS.

    The output GeoDataFrame gains these columns from the piste layer:
      piste_idx, piste_id, piste_difficulty, piste_name,
      distance_to_piste_m
    """
    orig_crs = points.crs

    pts = points.to_crs(PROJECTED_CRS).copy()
    pst = pistes.to_crs(PROJECTED_CRS)[
        ["id", "piste:difficulty", "name", "geometry"]
    ].copy()
    pst = pst.reset_index(drop=True)
    pst.index.name = "piste_idx"

    joined = gpd.sjoin_nearest(
        pts,
        pst.reset_index(),   # expose piste_idx as a regular column
        how="left",
        distance_col="distance_to_piste_m",
    )

    joined = joined.rename(columns={
        "piste_idx": "piste_idx",
        "id": "piste_id",
        "piste:difficulty": "piste_difficulty",
        "name": "piste_name",
    })

    # sjoin can produce duplicates when a point is equidistant to two pistes
    joined = joined[~joined.index.duplicated(keep="first")]

    return joined.to_crs(orig_crs)
