"""Filter and cluster dated, plausibly rain-triggered landslides for the Model B event-time check.

`python ml/scripts/event_catalog.py [--region W S E N] [--start-year Y] [--end-year Y] [--out PATH]`

Reads the USGS Landslide Inventory v3 (points and polygons) and the NASA Global Landslide Catalog
export, keeps records whose date is known to one day and whose type or trigger is plausibly
rainfall, and collapses them into event clusters: one per weather cell (a 0.1 degree grid, the
unit the Open-Meteo archive is sampled on) per storm, where records in one cell less than
`CLUSTER_GAP_DAYS` apart are the same storm. Clusters on dates less than `STORM_GAP_DAYS` apart
anywhere in the region share a storm id, which is the grouping unit for cross-validation and the
bootstrap. Every inclusion rule records how many records it removed.

Writes `data/processed/events/events.parquet` (clusters), `records.parquet` (the kept records with
their cluster id), and `catalog_summary.json` (rule counts).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
USGS_DIR = REPO_ROOT / "data" / "raw" / "usgs_v3" / "US_Landslide_v3_csv"
GLC_CSV = REPO_ROOT / "data" / "raw" / "coolr" / "global_landslide_catalog_export.csv"
OUT_DIR = REPO_ROOT / "data" / "processed" / "events"

# Western Washington and northwest Oregon, around the shared Rainier box
# [-121.93, 46.76, -121.54, 46.96]. Wider than the box because Rainier alone has too few dated events.
REGION = (-124.8, 45.5, -120.5, 49.0)  # west, south, east, north
# ERA5 has assimilated satellite data since 1979; the first year needs a week of antecedent rain.
START_YEAR = 1980
END_YEAR = 2023
MAX_DATE_SPAN_HOURS = 24
WEATHER_GRID_DEG = 0.1  # ERA5-Land resolution; one archive series per cell
CLUSTER_GAP_DAYS = 3  # same cell, records closer than this are one storm's cluster
STORM_GAP_DAYS = 2  # cluster dates closer than this anywhere in the region are one storm
# Records of any type dated to within this many days still block control days near them.
EXCLUSION_MAX_SPAN_DAYS = 31

# Not rainfall-triggered, or not a slope failure a rain threshold could predict.
EXCLUDED_TYPE_PATTERN = re.compile(
    r"snow|ice|avalanche - snow|creep|lateral spread|outburst|riverbank|subsidence|sinkhole", re.I
)
# Inventories whose dates are detection times of non-rain processes (volcano rock and ice falls).
EXCLUDED_INVENTORIES = {"USGS Seismogenic Mass Movements"}
# The v3 "NASA" inventory is the Global Landslide Catalog without its trigger field: read the
# catalog export instead so the trigger can be filtered.
DUPLICATE_INVENTORIES = {"NASA"}
GLC_RAIN_TRIGGERS = {"rain", "downpour", "continuous_rain", "flooding", "tropical_cyclone",
                     "extra_tropical_cyclone", "monsoon"}
GLC_LOCATION_ACCURACY = {"exact", "1km", "5km"}
GLC_EXCLUDED_CATEGORIES = {"snow_avalanche", "riverbank_collapse"}
# Washington Geological Survey storm reconnaissance: each source names the storm, and records
# dated outside it carry the mapping date, not the failure date.
WGS_STORM_DATES = {
    "storm event of December 1-3, 2007": ("2007-12-01", "2007-12-03"),
    "after the January 7, 2009, storm": ("2009-01-07", "2009-01-07"),
}


def normalize_lon(lon: pd.Series) -> pd.Series:
    """USGS v3 stores some west longitudes as positive numbers."""
    return lon.where(lon < 0, -lon)


def in_region(lon: pd.Series, lat: pd.Series, region: tuple[float, float, float, float]) -> pd.Series:
    west, south, east, north = region
    return (lon >= west) & (lon <= east) & (lat >= south) & (lat <= north)


class RuleLog:
    """Ordered record of how many rows each inclusion rule removed."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def apply(self, frame: pd.DataFrame, keep: pd.Series, source: str, rule: str) -> pd.DataFrame:
        keep = keep.fillna(False).astype(bool)
        self.rows.append({"source": source, "rule": rule, "before": int(len(frame)),
                          "removed": int((~keep).sum()), "after": int(keep.sum())})
        return frame[keep]


def load_usgs(region, start_year: int, end_year: int, log: RuleLog, usgs_dir: Path = USGS_DIR) -> pd.DataFrame:
    frames = []
    for geometry in ("point", "poly"):
        raw = pd.read_csv(usgs_dir / f"us_ls_v3_{geometry}.csv", low_memory=False)
        raw["geometry_type"] = geometry
        frames.append(raw)
    df = pd.concat(frames, ignore_index=True)
    source = "usgs_v3"
    df["lon"] = normalize_lon(df["Lon_W"].astype(float))
    df["lat"] = df["Lat_N"].astype(float)
    log.rows.append({"source": source, "rule": "all records (point + polygon)", "before": int(len(df)),
                     "removed": 0, "after": int(len(df))})
    df = log.apply(df, in_region(df.lon, df.lat, region), source, f"inside region {list(region)}")
    df = log.apply(df, ~df.Inventory.isin(DUPLICATE_INVENTORIES), source,
                   "not the v3 'NASA' inventory (read from the GLC export with its trigger field)")
    df = df.copy()
    df["date_min"] = pd.to_datetime(df.Date_Min, errors="coerce", format="%Y/%m/%d %H:%M:%S")
    df["date_max"] = pd.to_datetime(df.Date_Max, errors="coerce", format="%Y/%m/%d %H:%M:%S")
    df = log.apply(df, df.date_min.notna(), source, "has a Date_Min")
    span_h = (df.date_max.fillna(df.date_min) - df.date_min).dt.total_seconds() / 3600
    df = log.apply(df, (span_h >= 0) & (span_h <= MAX_DATE_SPAN_HOURS), source,
                   f"Date_Max - Date_Min <= {MAX_DATE_SPAN_HOURS} h (or no Date_Max)")
    df = log.apply(df, df.date_min.dt.year.between(start_year, end_year), source,
                   f"year {start_year}-{end_year} (ERA5 satellite era, archive available)")
    df = log.apply(df, ~df.Inventory.isin(EXCLUDED_INVENTORIES), source,
                   "not 'USGS Seismogenic Mass Movements' (volcano rock/ice falls, not rain)")
    df = log.apply(df, ~df.LS_Type.fillna("").str.contains(EXCLUDED_TYPE_PATTERN), source,
                   "type not snow/ice avalanche, creep, lateral spread, outburst, riverbank")
    placeholder = (df.date_min.dt.day == 1) & (df.date_min.dt.hour == 0) & (df.date_min.dt.minute == 0) \
        & df.date_max.isna()
    df = log.apply(df, ~placeholder, source,
                   "not dated the 1st of a month at 00:00 with no Date_Max (month/year placeholders)")
    df = log.apply(df, wgs_date_consistent(df), source,
                   "WA WGS storm reconnaissance records dated inside the named storm")
    out = pd.DataFrame({
        "record_id": "usgs:" + df.USGS_ID.astype(str),
        "source": source,
        "inventory": df.Inventory.astype(str),
        "ls_type": df.LS_Type.fillna("").astype(str),
        "trigger": "",
        "lon": df.lon, "lat": df.lat,
        "date": df.date_min.dt.normalize(),
    })
    return out


def wgs_date_consistent(df: pd.DataFrame) -> pd.Series:
    """True unless a WA WGS record names a storm and is dated outside that storm."""
    keep = pd.Series(True, index=df.index)
    info = df.Info_Source.fillna("")
    for phrase, (start, end) in WGS_STORM_DATES.items():
        named = (df.Inventory == "WA WGS") & info.str.contains(phrase, regex=False)
        inside = df.date_min.dt.normalize().between(pd.Timestamp(start), pd.Timestamp(end))
        keep &= ~named | inside
    return keep


def load_glc(region, start_year: int, end_year: int, log: RuleLog, path: Path = GLC_CSV) -> pd.DataFrame:
    source = "nasa_glc"
    df = pd.read_csv(path, low_memory=False)
    log.rows.append({"source": source, "rule": "all records", "before": int(len(df)), "removed": 0,
                     "after": int(len(df))})
    df = log.apply(df, in_region(df.longitude, df.latitude, region), source, f"inside region {list(region)}")
    df = df.copy()
    df["dt"] = pd.to_datetime(df.event_date, format="%m/%d/%Y %I:%M:%S %p", errors="coerce")
    df = log.apply(df, df.dt.notna(), source, "has an event_date")
    df = log.apply(df, df.dt.dt.year.between(start_year, end_year), source, f"year {start_year}-{end_year}")
    df = log.apply(df, df.landslide_trigger.isin(GLC_RAIN_TRIGGERS), source,
                   f"trigger in {sorted(GLC_RAIN_TRIGGERS)} (drops unknown, snowmelt, freeze-thaw, ...)")
    df = log.apply(df, ~df.landslide_category.isin(GLC_EXCLUDED_CATEGORIES), source,
                   "category not snow avalanche or riverbank collapse")
    df = log.apply(df, df.location_accuracy.isin(GLC_LOCATION_ACCURACY), source,
                   f"location_accuracy in {sorted(GLC_LOCATION_ACCURACY)}")
    return pd.DataFrame({
        "record_id": "glc:" + df.event_id.astype(str),
        "source": source,
        "inventory": "NASA GLC",
        "ls_type": df.landslide_category.fillna("").astype(str),
        "trigger": df.landslide_trigger.astype(str),
        "lon": df.longitude.astype(float), "lat": df.latitude.astype(float),
        "date": df.dt.dt.normalize(),
    })


def exclusion_records(region, start_year: int, usgs_dir: Path = USGS_DIR, glc_path: Path = GLC_CSV,
                      max_span_days: int = EXCLUSION_MAX_SPAN_DAYS) -> pd.DataFrame:
    """Every dated record in the region, whatever its type, trigger, or location accuracy.

    Controls must avoid these too: a slide the inclusion rules dropped still happened, so a day
    near it is not a clean no-event day.
    """
    frames = []
    for geometry in ("point", "poly"):
        raw = pd.read_csv(usgs_dir / f"us_ls_v3_{geometry}.csv", low_memory=False,
                          usecols=["USGS_ID", "Date_Min", "Date_Max", "Lat_N", "Lon_W"])
        lon = normalize_lon(raw.Lon_W.astype(float))
        raw = raw[in_region(lon, raw.Lat_N, region)]
        start = pd.to_datetime(raw.Date_Min, errors="coerce", format="%Y/%m/%d %H:%M:%S")
        end = pd.to_datetime(raw.Date_Max, errors="coerce", format="%Y/%m/%d %H:%M:%S").fillna(start)
        frames.append(pd.DataFrame({"record_id": "usgs:" + raw.USGS_ID.astype(str),
                                    "lon": normalize_lon(raw.Lon_W.astype(float)), "lat": raw.Lat_N.astype(float),
                                    "start": start.dt.normalize(), "end": end.dt.normalize()}))
    glc = pd.read_csv(glc_path, low_memory=False)
    glc = glc[in_region(glc.longitude, glc.latitude, region)]
    when = pd.to_datetime(glc.event_date, format="%m/%d/%Y %I:%M:%S %p", errors="coerce").dt.normalize()
    frames.append(pd.DataFrame({"record_id": "glc:" + glc.event_id.astype(str), "lon": glc.longitude,
                                "lat": glc.latitude, "start": when, "end": when}))
    out = pd.concat(frames, ignore_index=True).dropna(subset=["start"])
    span = (out.end - out.start).dt.days
    return out[(span >= 0) & (span <= max_span_days) & (out.end.dt.year >= start_year - 1)].reset_index(drop=True)


def snap(values: pd.Series | np.ndarray, grid: float = WEATHER_GRID_DEG) -> np.ndarray:
    """Center of the grid cell holding each coordinate, rounded to avoid float noise in keys."""
    return np.round((np.floor(np.asarray(values, dtype=float) / grid) + 0.5) * grid, 4)


def cluster_records(records: pd.DataFrame, grid: float = WEATHER_GRID_DEG,
                    cluster_gap_days: int = CLUSTER_GAP_DAYS,
                    storm_gap_days: int = STORM_GAP_DAYS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Collapse records into (weather cell, storm) clusters and give each a regional storm id.

    The cluster date is the earliest record date in it; reference times are built from it.
    """
    rec = records.copy()
    rec["cell_lat"] = snap(rec.lat, grid)
    rec["cell_lon"] = snap(rec.lon, grid)
    rec["cell_id"] = rec.cell_lat.map("{:.4f}".format) + "," + rec.cell_lon.map("{:.4f}".format)
    rec = rec.sort_values(["cell_id", "date"]).reset_index(drop=True)
    gap = rec.groupby("cell_id").date.diff().dt.days
    new_cluster = gap.isna() | (gap >= cluster_gap_days)
    rec["cluster_seq"] = new_cluster.groupby(rec.cell_id).cumsum()
    rec["cluster_id"] = rec.cell_id + "#" + rec.cluster_seq.astype(int).astype(str)
    clusters = rec.groupby("cluster_id").agg(
        cell_id=("cell_id", "first"), cell_lat=("cell_lat", "first"), cell_lon=("cell_lon", "first"),
        date=("date", "min"), last_date=("date", "max"), n_records=("record_id", "size"),
        lat=("lat", "mean"), lon=("lon", "mean"),
        sources=("source", lambda s: ",".join(sorted(set(s)))),
        inventories=("inventory", lambda s: ",".join(sorted(set(s)))),
    ).reset_index()
    dates = np.sort(clusters.date.unique())
    storm_of_date = {}
    storm = 0
    for i, day in enumerate(dates):
        if i and (pd.Timestamp(day) - pd.Timestamp(dates[i - 1])).days >= storm_gap_days:
            storm += 1
        storm_of_date[pd.Timestamp(day)] = storm
    first_day = {}
    for day, sid in storm_of_date.items():
        first_day.setdefault(sid, day)
    clusters["storm_id"] = clusters.date.map(lambda d: f"storm_{first_day[storm_of_date[d]]:%Y%m%d}")
    clusters["water_year"] = clusters.date.dt.year + (clusters.date.dt.month >= 10).astype(int)
    storm_wy = clusters.groupby("storm_id").water_year.transform("min")
    clusters["water_year"] = storm_wy  # a storm never straddles water years
    rec = rec.merge(clusters[["cluster_id", "storm_id"]], on="cluster_id")
    return clusters.sort_values(["date", "cell_id"]).reset_index(drop=True), rec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--region", type=float, nargs=4, default=REGION, metavar=("W", "S", "E", "N"))
    parser.add_argument("--start-year", type=int, default=START_YEAR)
    parser.add_argument("--end-year", type=int, default=END_YEAR)
    parser.add_argument("--out", type=Path, default=OUT_DIR / "events.parquet")
    args = parser.parse_args(argv)
    region = tuple(args.region)

    log = RuleLog()
    usgs = load_usgs(region, args.start_year, args.end_year, log)
    glc = load_glc(region, args.start_year, args.end_year, log)
    records = pd.concat([usgs, glc], ignore_index=True)
    clusters, rec = cluster_records(records)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    clusters.to_parquet(args.out, index=False)
    rec.to_parquet(args.out.with_name("records.parquet"), index=False)
    blockers = exclusion_records(region, args.start_year)
    blockers.to_parquet(args.out.with_name("exclusion_records.parquet"), index=False)
    storms = clusters.groupby("storm_id").agg(n_clusters=("cluster_id", "size"), date=("date", "min"))
    summary = {
        "region": list(region), "years": [args.start_year, args.end_year],
        "weather_grid_deg": WEATHER_GRID_DEG, "cluster_gap_days": CLUSTER_GAP_DAYS,
        "storm_gap_days": STORM_GAP_DAYS, "rules": log.rows,
        "kept_records": {"total": int(len(records)), **records.source.value_counts().to_dict()},
        "kept_by_inventory": records.inventory.value_counts().to_dict(),
        "n_clusters": int(len(clusters)), "n_cells": int(clusters.cell_id.nunique()),
        "n_storms": int(len(storms)), "n_water_years": int(clusters.water_year.nunique()),
        "n_exclusion_records": int(len(blockers)),
        "exclusion_rule": f"any region record (any type/trigger/accuracy) dated to <= {EXCLUSION_MAX_SPAN_DAYS} days",
        "largest_storms": storms.sort_values("n_clusters", ascending=False).head(10)
        .assign(date=lambda s: s.date.dt.strftime("%Y-%m-%d")).reset_index().to_dict("records"),
    }
    args.out.with_name("catalog_summary.json").write_text(json.dumps(summary, indent=2))
    for row in log.rows:
        print(f"{row['source']:9s} {row['after']:7d} kept  {row['removed']:7d} removed  {row['rule']}")
    print(f"kept records {len(records)} -> {len(clusters)} clusters in {clusters.cell_id.nunique()} cells, "
          f"{len(storms)} storms, {clusters.water_year.nunique()} water years")
    print(f"exclusion records (block control days): {len(blockers)}")
    print("largest storms:", storms.sort_values("n_clusters", ascending=False).head(6).n_clusters.to_dict())
    print(f"wrote {args.out.relative_to(REPO_ROOT) if args.out.is_relative_to(REPO_ROOT) else args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
