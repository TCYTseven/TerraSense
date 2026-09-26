"""Inclusion rules and event clustering for the dated-landslide catalog."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ml" / "scripts"))

import event_catalog as ec  # noqa: E402


def test_positive_west_longitudes_are_normalized() -> None:
    assert list(ec.normalize_lon(pd.Series([121.7, -121.7]))) == [-121.7, -121.7]


def test_wgs_reconnaissance_dates_outside_the_storm_are_dropped() -> None:
    source = "Landslide reconnaissance following the storm event of December 1-3, 2007, in western Washington"
    df = pd.DataFrame({
        "Inventory": ["WA WGS", "WA WGS", "WA WGS", "OR DOGAMI"],
        "Info_Source": [source, source, "unpublished GIS data", source],
        "date_min": pd.to_datetime(["2007-12-03", "2008-09-22", "2008-09-22", "2008-09-22"]),
    })
    assert list(ec.wgs_date_consistent(df)) == [True, False, True, True]


def _records(rows):
    return pd.DataFrame(rows, columns=["record_id", "source", "inventory", "lon", "lat", "date"]).assign(
        date=lambda d: pd.to_datetime(d.date))


def test_same_cell_same_storm_is_one_cluster_and_storms_group_the_region() -> None:
    rec = _records([
        ("1", "usgs_v3", "WA WGS", -122.01, 47.01, "2009-01-07"),
        ("2", "usgs_v3", "WA WGS", -122.02, 47.02, "2009-01-08"),  # same cell, next day
        ("3", "nasa_glc", "NASA GLC", -122.03, 47.03, "2009-01-20"),  # same cell, new storm
        ("4", "usgs_v3", "WA SDIC", -123.51, 46.51, "2009-01-07"),  # other cell, same storm
        ("5", "usgs_v3", "WA SDIC", -123.51, 46.51, "2009-09-30"),
        ("6", "usgs_v3", "WA SDIC", -122.01, 47.01, "2009-10-01"),  # straddles the water-year boundary
    ])
    clusters, kept = ec.cluster_records(rec)
    assert len(clusters) == 5
    first = clusters[clusters.date == pd.Timestamp("2009-01-07")]
    assert len(first) == 2 and first.storm_id.nunique() == 1
    assert int(clusters.loc[clusters.date == "2009-01-07", "n_records"].max()) == 2
    assert kept.groupby("record_id").cluster_id.nunique().max() == 1
    assert (clusters.groupby("storm_id").water_year.nunique() == 1).all()
    assert (clusters.groupby("cluster_id").cell_id.nunique() == 1).all()


def test_built_catalog_contract() -> None:
    path = REPO_ROOT / "data" / "processed" / "events" / "events.parquet"
    if not path.is_file():
        return
    clusters = pd.read_parquet(path)
    assert clusters.cluster_id.is_unique
    assert (clusters.groupby("storm_id").water_year.nunique() == 1).all()
    assert clusters.date.dt.year.between(ec.START_YEAR, ec.END_YEAR).all()
    assert (clusters.last_date - clusters.date).dt.days.max() < 60
