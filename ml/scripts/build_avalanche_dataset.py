#!/usr/bin/env python3
"""Build the canonical avalanche (cell, reference-time) training table.

The input is a normalized hourly table containing observations and historical forecasts.  Event
labels are intentionally supplied separately because avalanche occurrence catalogs are not
complete observations of "no avalanche".  Missing events remain explicit in the negative-label
metadata instead of being silently treated as certain negatives.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ml.avalanche_contract import (  # noqa: E402
    DEFAULT_MIN_NEGATIVE_COVERAGE,
    MODEL_FEATURES,
    PREDICTION_HORIZON_HOURS,
)
from app.ml.avalanche_features import avalanche_dynamic_features  # noqa: E402


def read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() in {".json", ".geojson"}:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("type") == "FeatureCollection":
            rows = []
            for feature in payload.get("features", []):
                geometry = feature.get("geometry") or {}
                coords = geometry.get("coordinates") or [None, None]
                props = dict(feature.get("properties") or {})
                props.setdefault("longitude", coords[0] if geometry.get("type") == "Point" else None)
                props.setdefault("latitude", coords[1] if geometry.get("type") == "Point" else None)
                props.setdefault("event_id", feature.get("id"))
                rows.append(props)
            return pd.DataFrame(rows)
        return pd.DataFrame(payload if isinstance(payload, list) else payload.get("events", []))
    return pd.read_csv(path)


def _first(row: pd.Series, *names: str) -> Any:
    for name in names:
        if name in row and pd.notna(row[name]):
            return row[name]
    return None


def _parse_bool(value: Any) -> bool | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return None


def read_events(path: Path, *, require_verified: bool = False) -> pd.DataFrame:
    """Normalize CAIC/NWAC/other occurrence exports without inventing missing events."""
    frame = read_table(path).copy()
    rows: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        timestamp = _first(row, "event_timestamp", "timestamp", "date", "event_date", "occurrence_date")
        if timestamp is None:
            continue
        parsed = pd.to_datetime(timestamp, utc=True, errors="coerce")
        if pd.isna(parsed):
            continue
        verified = _parse_bool(_first(row, "verified", "is_verified", "confirmed"))
        if require_verified and verified is not True:
            continue
        lat = _first(row, "latitude", "lat", "y")
        lon = _first(row, "longitude", "lon", "lng", "x")
        if lat is None or lon is None:
            continue
        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            continue
        rows.append({
            "event_id": str(_first(row, "event_id", "id", "observation_id") or f"event-{index}"),
            "event_timestamp": parsed.to_pydatetime(),
            "latitude": lat,
            "longitude": lon,
            "event_type": str(_first(row, "event_type", "avalanche_type", "type") or "avalanche"),
            "trigger": str(_first(row, "trigger", "trigger_type") or "unknown"),
            "size": _first(row, "size", "size_r", "destructive_size"),
            "verified": verified,
            "source": str(_first(row, "source", "source_name", "agency") or path.name),
        })
    return pd.DataFrame(rows)


def _nearest_cell(event: pd.Series, cells: pd.DataFrame) -> str | None:
    if cells.empty:
        return None
    lat, lon = float(event["latitude"]), float(event["longitude"])
    distances = ((cells["latitude"] - lat) ** 2 + ((cells["longitude"] - lon) * math.cos(math.radians(lat))) ** 2)
    return str(cells.loc[distances.idxmin(), "cell_id"])


def _region(latitude: float, longitude: float) -> str:
    return f"{math.floor(latitude):+03d}:{math.floor(longitude):+04d}"


def assert_no_future_leakage(frame: pd.DataFrame) -> None:
    reference = pd.to_datetime(frame["reference_timestamp"], utc=True)
    feature_asof = pd.to_datetime(frame["feature_asof"], utc=True)
    if (feature_asof > reference).any():
        raise ValueError("future-data leakage: feature_asof is after reference_timestamp")
    if "forecast_initialization" in frame:
        initialization = pd.to_datetime(frame["forecast_initialization"], utc=True, errors="coerce")
        invalid = initialization.notna() & (initialization > reference)
        if invalid.any():
            raise ValueError("future-data leakage: forecast initialized after reference_timestamp")


def label_samples(
    samples: pd.DataFrame,
    events: pd.DataFrame,
    *,
    min_negative_coverage: float = DEFAULT_MIN_NEGATIVE_COVERAGE,
) -> pd.DataFrame:
    output = samples.copy()
    output["label"] = 0
    output["positive_event_id"] = None
    output["event_group"] = None
    output["label_confidence"] = "unknown_absence"
    output["negative_source_type"] = "unknown_absence"
    output["negative_eligible"] = False
    event_by_cell: dict[str, list[pd.Series]] = {}
    if not events.empty:
        for _, event in events.iterrows():
            event_by_cell.setdefault(str(event["cell_id"]), []).append(event)
    for index, sample in output.iterrows():
        start = pd.Timestamp(sample["reference_timestamp"]).to_pydatetime()
        end = start + timedelta(hours=PREDICTION_HORIZON_HOURS)
        matches = [event for event in event_by_cell.get(str(sample["cell_id"]), [])
                   if start <= event["event_timestamp"] < end]
        if matches:
            event = sorted(matches, key=lambda item: item["event_timestamp"])[0]
            output.at[index, "label"] = 1
            output.at[index, "positive_event_id"] = str(event["event_id"])
            output.at[index, "event_group"] = str(event["event_id"])
            output.at[index, "label_confidence"] = "high" if event.get("verified") is True else "medium"
            output.at[index, "negative_source_type"] = "positive_event"
            output.at[index, "negative_eligible"] = True
        else:
            coverage = pd.to_numeric(pd.Series([sample.get("event_observation_coverage")]), errors="coerce").iloc[0]
            if pd.notna(coverage) and float(coverage) >= min_negative_coverage:
                output.at[index, "label_confidence"] = "high_negative"
                output.at[index, "negative_source_type"] = "observed_no_event"
                output.at[index, "negative_eligible"] = True
    return output


def build_samples(
    dynamic: pd.DataFrame,
    static: pd.DataFrame | None,
    events: pd.DataFrame | None,
    reference_stride_hours: int = 6,
    min_negative_coverage: float = DEFAULT_MIN_NEGATIVE_COVERAGE,
) -> pd.DataFrame:
    required = {"timestamp", "latitude", "longitude", "cell_id", "is_forecast"}
    missing = sorted(required - set(dynamic.columns))
    if missing:
        raise ValueError(f"dynamic table missing required columns: {missing}")
    dynamic = dynamic.copy()
    dynamic["timestamp"] = pd.to_datetime(dynamic["timestamp"], utc=True)
    if "forecast_initialization" in dynamic:
        dynamic["forecast_initialization"] = pd.to_datetime(dynamic["forecast_initialization"], utc=True, errors="coerce")
    dynamic = dynamic.sort_values(["cell_id", "timestamp"])
    static_by_cell = static.set_index("cell_id").to_dict("index") if static is not None and "cell_id" in static else {}
    output: list[dict[str, Any]] = []
    columns = (
        "precipitation_mm", "snowfall_cm", "snow_depth_m", "snow_water_equivalent_mm", "snow_cover_fraction",
        "snowmelt_mm", "temperature_c", "wind_speed_kmh", "wind_gust_kmh", "wind_direction_deg", "freezing_level_m",
    )
    for cell_id, group in dynamic.groupby("cell_id", sort=False):
        group = group.sort_values("timestamp")
        observed = group[~group["is_forecast"].astype(bool)]
        forecasts = group[group["is_forecast"].astype(bool)]
        if observed.empty:
            continue
        for reference in observed["timestamp"].iloc[::max(1, int(reference_stride_hours))]:
            available = forecasts[(forecasts["timestamp"] > reference) & (
                forecasts.get("forecast_initialization", pd.Series(pd.NaT, index=forecasts.index)) <= reference
            )]
            static_values = {key: value for key, value in static_by_cell.get(cell_id, {}).items() if key not in {"label"}}
            observed_times = observed.loc[observed["timestamp"] <= reference, "timestamp"].tolist()
            dynamic_kwargs: dict[str, Any] = {"times": observed_times, "reference_time": reference.to_pydatetime(), "static": static_values}
            for name in columns:
                dynamic_kwargs[name] = observed.loc[observed["timestamp"] <= reference, name].tolist() if name in observed else []
            dynamic_kwargs.update({
                "forecast_times": available["timestamp"].tolist(),
                "forecast_precipitation_mm": available["precipitation_mm"].tolist() if "precipitation_mm" in available else [],
                "forecast_snowfall_cm": available["snowfall_cm"].tolist() if "snowfall_cm" in available else [],
                "forecast_temperature_c": available["temperature_c"].tolist() if "temperature_c" in available else [],
                "forecast_wind_speed_kmh": available["wind_speed_kmh"].tolist() if "wind_speed_kmh" in available else [],
                "forecast_wind_gust_kmh": available["wind_gust_kmh"].tolist() if "wind_gust_kmh" in available else [],
                "forecast_wind_direction_deg": available["wind_direction_deg"].tolist() if "wind_direction_deg" in available else [],
                "forecast_snowmelt_mm": available["snowmelt_mm"].tolist() if "snowmelt_mm" in available else [],
                "forecast_snow_cover_fraction": available["snow_cover_fraction"].tolist() if "snow_cover_fraction" in available else [],
                "forecast_freezing_level_m": available["freezing_level_m"].tolist() if "freezing_level_m" in available else [],
                "forecast_ensemble_snowfall_cm": [member["snowfall_cm"].tolist() for _, member in available.groupby("forecast_ensemble_id")]
                if "forecast_ensemble_id" in available and "snowfall_cm" in available else [],
                "context": {
                    name: float(observed.loc[observed["timestamp"] <= reference, name].iloc[-1])
                    for name in ("recent_avalanche_count_7d", "persistent_weak_layer_signal", "snowpack_stability_observation", "published_danger_rating_numeric", "event_observation_coverage")
                    if name in observed and not observed.loc[observed["timestamp"] <= reference, name].empty and pd.notna(observed.loc[observed["timestamp"] <= reference, name].iloc[-1])
                },
                "quality": {
                    "dem_available": static_values.get("dem_available", False),
                    "static_snow_terrain_available": static_values.get("snow_ice_fraction") is not None,
                    "snowpack_available": "snow_depth_m" in observed or "snow_water_equivalent_mm" in observed,
                    "snowpack_age_hours": 0.0 if "snow_depth_m" in observed or "snow_water_equivalent_mm" in observed else None,
                    "forecast_available": not available.empty,
                    "forecast_age_hours": ((reference - available["forecast_initialization"].iloc[0]).total_seconds() / 3600)
                    if not available.empty and "forecast_initialization" in available and pd.notna(available["forecast_initialization"].iloc[0]) else None,
                    "weather_station_available": False,
                    "terrain_resolution_m": static_values.get("terrain_resolution_m"),
                    "weather_resolution_km": static_values.get("weather_resolution_km"),
                },
            })
            features = avalanche_dynamic_features(**dynamic_kwargs)
            row = {**static_values, **features}
            row.update({
                "cell_id": str(cell_id),
                "latitude": float(group["latitude"].iloc[0]),
                "longitude": float(group["longitude"].iloc[0]),
                "region": str(group["region"].iloc[0]) if "region" in group else _region(float(group["latitude"].iloc[0]), float(group["longitude"].iloc[0])),
                "reference_timestamp": reference.isoformat(),
                "feature_asof": observed.loc[observed["timestamp"] <= reference, "timestamp"].max().isoformat(),
                "forecast_initialization": available["forecast_initialization"].iloc[0].isoformat()
                if not available.empty and "forecast_initialization" in available and pd.notna(available["forecast_initialization"].iloc[0]) else None,
            })
            output.append(row)
    frame = pd.DataFrame(output)
    if frame.empty:
        raise ValueError("dynamic table produced no reference-time samples")
    for name in MODEL_FEATURES:
        if name not in frame:
            frame[name] = None
        frame[name] = pd.to_numeric(frame[name], errors="coerce")
    if events is not None and not events.empty:
        cells = frame[["cell_id", "latitude", "longitude"]].drop_duplicates()
        events = events.copy()
        events["cell_id"] = events.apply(
            lambda row: str(row["cell_id"]) if "cell_id" in row and pd.notna(row["cell_id"]) else _nearest_cell(row, cells),
            axis=1,
        )
    frame = label_samples(
        frame,
        events if events is not None else pd.DataFrame(),
        min_negative_coverage=min_negative_coverage,
    )
    assert_no_future_leakage(frame)
    return frame


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dynamic", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--static", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference-stride-hours", type=int, default=6)
    parser.add_argument("--require-verified", action="store_true")
    parser.add_argument(
        "--min-negative-coverage",
        type=float,
        default=float(os.environ.get("AVALANCHE_MIN_NEGATIVE_COVERAGE", DEFAULT_MIN_NEGATIVE_COVERAGE)),
    )
    args = parser.parse_args()
    dynamic = read_table(args.dynamic)
    static = read_table(args.static) if args.static else None
    events = read_events(args.events, require_verified=args.require_verified)
    frame = build_samples(dynamic, static, events, args.reference_stride_hours, args.min_negative_coverage)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.out, index=False)
    print(json.dumps({"rows": len(frame), "positives": int(frame["label"].sum()), "events": len(events), "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
