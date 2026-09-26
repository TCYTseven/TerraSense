#!/usr/bin/env python3
"""Build the canonical (cell, reference-time) training table for 72-hour risk.

The builder is intentionally strict about provenance and time.  It accepts a feature table made
from archived observations/forecasts and one or more GeoJSON event inventories.  It does not turn
an undated inventory point into a 72-hour label, and it refuses a table where any observation
feature is newer than its reference timestamp.

Example:
  ml/.venv/bin/python ml/scripts/build_risk_dataset.py \
    --samples data/raw/risk_samples.parquet \
    --labels data/seed/landslides.geojson \
    --out data/processed/landslide_risk.parquet
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pyproj import Transformer
from shapely.geometry import shape

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ml.risk_contract import (  # noqa: E402
    DEFAULT_CELL_SIZE_M,
    DEFAULT_HARD_NEGATIVE_FRACTION,
    DEFAULT_SUSCEPTIBLE_NEGATIVE_FRACTION,
    MODEL_FEATURES,
    PREDICTION_HORIZON_HOURS,
)
from app.ml.risk_features import event_cell_id  # noqa: E402

DEFAULT_LABELS = REPO_ROOT / "data" / "seed" / "landslides.geojson"
DEFAULT_OUT = REPO_ROOT / "data" / "processed" / "landslide_risk.parquet"
GRID_CRS = "EPSG:32610"
WGS84_TO_GRID = Transformer.from_crs("EPSG:4326", GRID_CRS, always_xy=True)

RAIN_TRIGGERS = (
    "rain",
    "downpour",
    "storm",
    "tropical cyclone",
    "hurricane",
    "typhoon",
    "monsoon",
    "snowmelt",
    "rain-on-snow",
)
EXCLUDED_TRIGGERS = ("earthquake", "mining", "volcanic", "construction", "unknown")
CATALOG_PRIORITY = {"NASA COOLR / Global Landslide Catalog": 3, "NASA Global Landslide Catalog": 3, "USGS Inventories v3": 2}
LOCATION_CONFIDENCE_SCORES = {
    "exact": 3,
    "high": 3,
    "1km": 2,
    "medium": 2,
    "5km": 1,
    "low": 1,
    "unknown": 0,
}


@dataclass(frozen=True)
class Event:
    event_id: str
    dataset: str
    source_url: str | None
    event_time: datetime
    timestamp_uncertainty_days: float
    cell_id: str
    lon: float
    lat: float
    trigger: str
    confidence: str | None
    geometry_type: str
    ingestion_timestamp: str


def parse_datetime(value: Any) -> datetime | None:
    """Parse ISO, common inventory dates, or ArcGIS epoch milliseconds."""
    if value in (None, "", "null"):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / 1000, tz=UTC)
    text = str(value).strip()
    for fmt in ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or UTC)


def _properties(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties") or {}
    return {str(key).lower(): value for key, value in props.items()}


def _first(props: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = props.get(key.lower())
        if value not in (None, ""):
            return value
    return None


def normalize_trigger(value: Any) -> str:
    return str(value or "unknown").strip().lower().replace("_", " ")


def rainfall_trigger(value: Any) -> bool:
    trigger = normalize_trigger(value)
    if any(excluded in trigger for excluded in EXCLUDED_TRIGGERS):
        return False
    return any(allowed in trigger for allowed in RAIN_TRIGGERS)


def _event_geometry(feature: dict[str, Any]) -> tuple[float, float, str] | None:
    geometry = feature.get("geometry")
    if not geometry:
        return None
    geom = shape(geometry)
    if geom.is_empty:
        return None
    point = geom if geom.geom_type == "Point" else geom.representative_point()
    return float(point.x), float(point.y), str(geom.geom_type)


def _event_from_values(
    *,
    index: int,
    dataset_default: str,
    event_id_value: Any,
    dataset_value: Any,
    source_url: Any,
    start: datetime | None,
    end: datetime | None,
    uncertainty_value: Any,
    lon: Any,
    lat: Any,
    trigger_value: Any,
    confidence: Any,
    geometry_type: str,
    max_date_uncertainty_days: float,
    minimum_location_confidence: int,
) -> Event | None:
    if not rainfall_trigger(trigger_value) or start is None:
        return None
    end = end or start
    if end < start:
        start, end = end, start
    uncertainty = uncertainty_value
    if uncertainty in (None, ""):
        uncertainty = max(0.0, (end - start).total_seconds() / 86_400 / 2)
    try:
        uncertainty = float(uncertainty)
        lon_value, lat_value = float(lon), float(lat)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lon_value) and math.isfinite(lat_value)):
        return None
    if uncertainty > max_date_uncertainty_days:
        return None
    confidence_text = str(confidence).strip().lower() if confidence not in (None, "") else "unknown"
    if LOCATION_CONFIDENCE_SCORES.get(confidence_text, 0) < minimum_location_confidence:
        return None
    easting, northing = WGS84_TO_GRID.transform(lon_value, lat_value)
    if not (math.isfinite(easting) and math.isfinite(northing)):
        return None
    dataset = str(dataset_value or dataset_default)
    event_id = str(event_id_value or f"{dataset}:{index}")
    return Event(
        event_id=event_id,
        dataset=dataset,
        source_url=source_url,
        event_time=start + (end - start) / 2,
        timestamp_uncertainty_days=uncertainty,
        cell_id=event_cell_id(easting, northing, DEFAULT_CELL_SIZE_M),
        lon=lon_value,
        lat=lat_value,
        trigger=normalize_trigger(trigger_value),
        confidence=str(confidence) if confidence not in (None, "") else None,
        geometry_type=geometry_type,
        ingestion_timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def _read_csv_events(path: Path, *, max_date_uncertainty_days: float, minimum_location_confidence: int) -> list[Event]:
    """Read the NASA GLC CSV export directly, including the user-supplied local export format."""
    events: list[Event] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for index, raw in enumerate(reader):
            row = {str(key).lower(): value for key, value in raw.items()}
            event_date = _first(row, "event_date", "date")
            event_time = str(_first(row, "event_time") or "").strip()
            start = parse_datetime(event_date)
            if start is not None and event_time:
                combined = parse_datetime(f"{event_date} {event_time}")
                start = combined or start
            event = _event_from_values(
                index=index,
                dataset_default="NASA COOLR / Global Landslide Catalog",
                event_id_value=_first(row, "event_id", "id"),
                dataset_value=_first(row, "dataset", "catalog"),
                source_url=_first(row, "source_link", "source_url", "url"),
                start=start,
                end=start,
                uncertainty_value=_first(row, "timestamp_uncertainty_days", "date_uncertainty_days"),
                lon=_first(row, "longitude", "lon"),
                lat=_first(row, "latitude", "lat"),
                trigger_value=_first(row, "landslide_trigger", "trigger", "event_type"),
                confidence=_first(row, "confidence", "location_accuracy"),
                geometry_type="Point",
                max_date_uncertainty_days=max_date_uncertainty_days,
                minimum_location_confidence=minimum_location_confidence,
            )
            if event is not None:
                events.append(event)
    return deduplicate_events(events)


def read_events(
    path: Path,
    *,
    max_date_uncertainty_days: float = 1.0,
    minimum_location_confidence: int = 0,
) -> list[Event]:
    """Read NASA CSV or NASA/USGS-style GeoJSON and keep only dated rainfall-triggered events."""
    if path.suffix.lower() == ".csv":
        return _read_csv_events(
            path,
            max_date_uncertainty_days=max_date_uncertainty_days,
            minimum_location_confidence=minimum_location_confidence,
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("type") != "FeatureCollection":
        raise ValueError(f"{path} is not a GeoJSON FeatureCollection")
    events: list[Event] = []
    dataset_default = path.stem
    for index, feature in enumerate(payload.get("features", [])):
        props = _properties(feature)
        trigger_value = _first(props, "trigger", "landslide_trigger", "event_type", "landslide_trigger_event")
        start = parse_datetime(_first(props, "date_min", "event_date", "date", "event_time"))
        end = parse_datetime(_first(props, "date_max", "event_date", "date", "event_time")) or start
        if start is None or end is None:
            # A 72-hour label cannot be created from an undated inventory event.
            continue
        if end < start:
            start, end = end, start
        geometry = _event_geometry(feature)
        if geometry is None:
            continue
        lon, lat, geometry_type = geometry
        event = _event_from_values(
            index=index,
            dataset_default=dataset_default,
            event_id_value=_first(props, "event_id", "id", "source_id") or feature.get("id"),
            dataset_value=_first(props, "dataset", "catalog", "source_dataset"),
            source_url=_first(props, "source_url", "source_link", "url"),
            start=start,
            end=end,
            uncertainty_value=_first(props, "timestamp_uncertainty_days", "date_uncertainty_days"),
            lon=lon,
            lat=lat,
            trigger_value=trigger_value,
            confidence=_first(props, "confidence", "inventory_confidence", "certainty", "location_accuracy"),
            geometry_type=geometry_type,
            max_date_uncertainty_days=max_date_uncertainty_days,
            minimum_location_confidence=minimum_location_confidence,
        )
        if event is not None:
            events.append(event)
    return deduplicate_events(events)


def deduplicate_events(events: list[Event], window_days: float = 3.0) -> list[Event]:
    """Deduplicate inventory copies by metric cell and time, retaining best provenance."""
    kept: list[Event] = []
    for event in sorted(events, key=lambda item: item.event_time):
        duplicate_index = next(
            (index for index, previous in enumerate(kept)
             if previous.cell_id == event.cell_id
             and abs((previous.event_time - event.event_time).total_seconds()) <= window_days * 86_400),
            None,
        )
        if duplicate_index is None:
            kept.append(event)
            continue
        previous = kept[duplicate_index]
        previous_score = CATALOG_PRIORITY.get(previous.dataset, 1)
        event_score = CATALOG_PRIORITY.get(event.dataset, 1)
        if event_score > previous_score or event.timestamp_uncertainty_days < previous.timestamp_uncertainty_days:
            kept[duplicate_index] = event
    return kept


def assert_no_future_leakage(frame: pd.DataFrame) -> None:
    """Reject observed or forecast features that were created after the sample's T."""
    if "reference_timestamp" not in frame:
        raise ValueError("risk samples need reference_timestamp")
    reference = pd.to_datetime(frame["reference_timestamp"], utc=True)
    for column in ("feature_asof", "observation_asof", "observed_asof"):
        if column in frame:
            asof = pd.to_datetime(frame[column], utc=True)
            if bool((asof > reference).any()):
                rows = frame.index[asof > reference].tolist()[:3]
                raise ValueError(f"future-data leakage in {column} for rows {rows}")
    if "forecast_initialization" in frame:
        init = pd.to_datetime(frame["forecast_initialization"], utc=True)
        if bool((init > reference).any()):
            rows = frame.index[init > reference].tolist()[:3]
            raise ValueError(f"forecast initialized after reference_timestamp for rows {rows}")
    for column in frame.columns:
        if column.startswith("observed_future_") or column.startswith("actual_future_"):
            raise ValueError(f"future observed target-like feature is not allowed: {column}")


def label_samples(samples: pd.DataFrame, events: list[Event]) -> pd.DataFrame:
    """Assign y=1 when an event occurs in the same cell during [T, T+72h]."""
    required = {"cell_id", "reference_timestamp"}
    missing = sorted(required - set(samples.columns))
    if missing:
        raise ValueError(f"samples missing label-join columns: {missing}")
    frame = samples.copy()
    frame["reference_timestamp"] = pd.to_datetime(frame["reference_timestamp"], utc=True)
    frame["label"] = 0
    frame["positive_event_id"] = None
    frame["positive_event_dataset"] = None
    frame["positive_event_source_url"] = None
    frame["positive_event_trigger"] = None
    frame["positive_event_confidence"] = None
    frame["positive_event_timestamp_uncertainty_days"] = None
    frame["positive_event_ingestion_timestamp"] = None
    by_cell: dict[str, list[Event]] = {}
    for event in events:
        by_cell.setdefault(event.cell_id, []).append(event)
    for index, row in frame.iterrows():
        start = row["reference_timestamp"].to_pydatetime()
        end = start + timedelta(hours=PREDICTION_HORIZON_HOURS)
        matches = [event for event in by_cell.get(str(row["cell_id"]), []) if start <= event.event_time <= end]
        if matches:
            event = min(matches, key=lambda item: item.event_time)
            frame.at[index, "label"] = 1
            frame.at[index, "positive_event_id"] = event.event_id
            frame.at[index, "positive_event_dataset"] = event.dataset
            frame.at[index, "positive_event_source_url"] = event.source_url
            frame.at[index, "positive_event_trigger"] = event.trigger
            frame.at[index, "positive_event_confidence"] = event.confidence
            frame.at[index, "positive_event_timestamp_uncertainty_days"] = event.timestamp_uncertainty_days
            frame.at[index, "positive_event_ingestion_timestamp"] = event.ingestion_timestamp
    return frame


def assign_negative_source(
    frame: pd.DataFrame,
    seed: int = 31,
    hard_negative_fraction: float = DEFAULT_HARD_NEGATIVE_FRACTION,
    susceptible_negative_fraction: float = DEFAULT_SUSCEPTIBLE_NEGATIVE_FRACTION,
) -> pd.DataFrame:
    """Tag negatives as hard, susceptible, or background without changing their labels.

    The sampler is intentionally transparent.  Callers may provide ``storm_group`` and
    ``susceptibility_score``; absent those, the row is conservatively background.
    """
    rng = np.random.default_rng(seed)
    out = frame.copy()
    out["negative_source_type"] = np.where(out["label"] == 1, "positive_event", "background")
    out["negative_confidence"] = np.where(out["label"] == 1, None, "low")
    negatives = out.index[out["label"] == 0].to_numpy()
    if len(negatives) == 0:
        return out

    def cell_parts(value: object) -> tuple[int, int] | None:
        try:
            east, north = str(value).split(":", 1)
            return int(east), int(north)
        except (TypeError, ValueError):
            return None

    # Hard negatives are drawn from the same storm groups and nearby cells as positive events when
    # those provenance fields exist. They are not invented by perturbing a positive row.
    positive_storms = set(out.loc[out["label"] == 1, "storm_group"].astype(str)) if "storm_group" in out else set()
    positive_cells = [cell_parts(value) for value in out.loc[out["label"] == 1, "cell_id"]] if "cell_id" in out else []
    positive_cells = [value for value in positive_cells if value is not None]
    hard_candidates = []
    for index in negatives.tolist():
        same_storm = "storm_group" in out and str(out.at[index, "storm_group"]) in positive_storms
        candidate_cell = cell_parts(out.at[index, "cell_id"]) if "cell_id" in out else None
        nearby = bool(candidate_cell and positive_cells and any(
            abs(candidate_cell[0] - cell[0]) <= 2 and abs(candidate_cell[1] - cell[1]) <= 2
            for cell in positive_cells
        ))
        if same_storm and (nearby or not positive_cells):
            hard_candidates.append(index)
    rng.shuffle(hard_candidates)
    hard_count = min(len(hard_candidates), math.floor(len(negatives) * hard_negative_fraction))
    used = set(hard_candidates[:hard_count])
    out.loc[list(used), "negative_source_type"] = "storm_matched_hard_negative"
    out.loc[list(used), "negative_confidence"] = "medium"

    remaining = [index for index in negatives.tolist() if index not in used]
    if "susceptibility_score" in out:
        susceptibility = pd.to_numeric(out.loc[remaining, "susceptibility_score"], errors="coerce")
    elif "slope_mean" in out:
        susceptibility = pd.to_numeric(out.loc[remaining, "slope_mean"], errors="coerce")
    else:
        susceptibility = pd.Series(np.nan, index=remaining)
    valid_susceptibility = susceptibility.dropna()
    cutoff = float(valid_susceptibility.quantile(0.70)) if not valid_susceptibility.empty else None
    susceptible_candidates = susceptibility.index[susceptibility >= cutoff].tolist() if cutoff is not None else []
    rng.shuffle(susceptible_candidates)
    susceptible_count = min(len(susceptible_candidates), math.floor(len(negatives) * susceptible_negative_fraction))
    susceptible = susceptible_candidates[:susceptible_count]
    out.loc[susceptible, "negative_source_type"] = "susceptible_terrain_negative"
    out.loc[susceptible, "negative_confidence"] = "medium"
    background = [index for index in remaining if index not in set(susceptible)]
    out.loc[background, "negative_confidence"] = "low"
    return out


def finalize_dataset(
    samples: pd.DataFrame,
    events: list[Event],
    *,
    hard_negative_fraction: float = DEFAULT_HARD_NEGATIVE_FRACTION,
    susceptible_negative_fraction: float = DEFAULT_SUSCEPTIBLE_NEGATIVE_FRACTION,
) -> pd.DataFrame:
    assert_no_future_leakage(samples)
    frame = label_samples(samples, events)
    if hard_negative_fraction < 0 or susceptible_negative_fraction < 0 or hard_negative_fraction + susceptible_negative_fraction > 1:
        raise ValueError("negative sampling fractions must be non-negative and sum to at most 1")
    frame = assign_negative_source(
        frame,
        hard_negative_fraction=hard_negative_fraction,
        susceptible_negative_fraction=susceptible_negative_fraction,
    )
    missing_features = [name for name in MODEL_FEATURES if name not in frame.columns]
    if missing_features:
        raise ValueError(f"risk sample table is missing canonical features: {missing_features}")
    frame["reference_timestamp"] = pd.to_datetime(frame["reference_timestamp"], utc=True).astype("string")
    frame["reference_year"] = pd.to_datetime(frame["reference_timestamp"], utc=True).dt.year.astype("int16")
    # Keep both metric axes in the holdout key.  Holding out only the easting index lets adjacent
    # north/south cells from the same storm cross the evaluation seam.
    cell_parts = frame["cell_id"].astype("string").str.split(":", expand=True)
    if cell_parts.shape[1] != 2:
        raise ValueError("cell_id must have the form '<easting_index>:<northing_index>'")
    frame["spatial_group"] = (
        (pd.to_numeric(cell_parts[0], errors="raise") // 5).astype("string")
        + ":"
        + (pd.to_numeric(cell_parts[1], errors="raise") // 5).astype("string")
    )
    if "storm_group" not in frame:
        frame["storm_group"] = frame["reference_timestamp"].str.slice(0, 10)
    frame["storm_group"] = frame["storm_group"].astype("string")
    return frame


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=Path, required=True, help="observed/forecast feature rows")
    parser.add_argument("--labels", type=Path, action="append", default=[], help="GeoJSON event inventory (repeatable)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--max-date-uncertainty-days", type=float, default=1.0)
    parser.add_argument("--minimum-location-confidence", type=int, choices=(0, 1, 2, 3), default=0, help="0=unknown, 1=low/5km, 2=medium/1km, 3=high/exact")
    parser.add_argument("--hard-negative-fraction", type=float, default=DEFAULT_HARD_NEGATIVE_FRACTION)
    parser.add_argument("--susceptible-negative-fraction", type=float, default=DEFAULT_SUSCEPTIBLE_NEGATIVE_FRACTION)
    args = parser.parse_args()
    samples = read_table(args.samples)
    events = []
    label_paths = args.labels or [DEFAULT_LABELS]
    for path in label_paths:
        events.extend(
            read_events(
                path,
                max_date_uncertainty_days=args.max_date_uncertainty_days,
                minimum_location_confidence=args.minimum_location_confidence,
            )
        )
    events = deduplicate_events(events)
    table = finalize_dataset(
        samples,
        events,
        hard_negative_fraction=args.hard_negative_fraction,
        susceptible_negative_fraction=args.susceptible_negative_fraction,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(args.out, index=False)
    print(json.dumps({
        "out": str(args.out),
        "rows": len(table),
        "positive_rows": int(table["label"].sum()),
        "events": len(events),
        "cells": int(table["cell_id"].nunique()),
        "years": sorted(table["reference_year"].unique().tolist()),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
