#!/usr/bin/env python3
"""Assemble normalized hourly observations/forecasts into event-time model samples.

This is the bridge between source adapters and ``build_risk_dataset.py``.  Inputs are intentionally
normalized tables rather than provider-specific HDF/GRIB parsing in the labeler:

  timestamp, latitude, longitude, cell_id, precipitation_mm, is_forecast,
  forecast_initialization, temperature_c, surface_soil_moisture, ...

The same ``hourly_dynamic_features`` function is used by backend inference.  A row is emitted
only when the forecast initialization is no later than the reference timestamp.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ml.risk_contract import MODEL_FEATURES  # noqa: E402
from app.ml.risk_features import hourly_dynamic_features  # noqa: E402


def read_table(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path)


def build_samples(dynamic: pd.DataFrame, static: pd.DataFrame | None = None, reference_stride_hours: int = 6) -> pd.DataFrame:
    required = {"timestamp", "latitude", "longitude", "cell_id", "precipitation_mm", "is_forecast"}
    missing = sorted(required - set(dynamic.columns))
    if missing:
        raise ValueError(f"dynamic table missing required columns: {missing}")
    dynamic = dynamic.copy()
    dynamic["timestamp"] = pd.to_datetime(dynamic["timestamp"], utc=True)
    if "forecast_initialization" in dynamic:
        dynamic["forecast_initialization"] = pd.to_datetime(dynamic["forecast_initialization"], utc=True, errors="coerce")
    dynamic = dynamic.sort_values(["cell_id", "timestamp"])
    static_by_cell = static.set_index("cell_id").to_dict("index") if static is not None and "cell_id" in static else {}
    output: list[dict] = []
    for cell_id, group in dynamic.groupby("cell_id", sort=False):
        group = group.sort_values("timestamp")
        observed = group[~group["is_forecast"].astype(bool)]
        forecast_rows = group[group["is_forecast"].astype(bool)]
        if observed.empty:
            continue
        reference_times = list(observed["timestamp"].iloc[::max(1, int(reference_stride_hours))])
        for reference in reference_times:
            past = observed[observed["timestamp"] <= reference]
            available_forecast = forecast_rows[
                (forecast_rows["timestamp"] > reference)
                & (forecast_rows.get("forecast_initialization", pd.Series(pd.NaT, index=forecast_rows.index)) <= reference)
            ]
            observed_times = past["timestamp"].tolist()
            observed_rain = past["precipitation_mm"].astype(float).tolist()
            forecast_times = available_forecast["timestamp"].tolist()
            forecast_rain = available_forecast["precipitation_mm"].astype(float).tolist()
            extras = {}
            for name in ("temperature_c", "surface_soil_moisture", "root_zone_soil_moisture", "runoff", "evapotranspiration", "snowmelt", "snow_depth", "snow_fraction"):
                if name in past:
                    extras[name] = past[name].astype(float).tolist()
            if "temperature_c" in available_forecast:
                extras["forecast_temperature"] = available_forecast["temperature_c"].astype(float).tolist()
            if "snowmelt" in available_forecast:
                extras["forecast_snowmelt"] = available_forecast["snowmelt"].astype(float).tolist()
            static_values = static_by_cell.get(cell_id, {})
            quality = {
                "dem_available": static_values.get("dem_available", False),
                "soilgrids_available": static_values.get("soilgrids_available", False),
                "worldcover_available": static_values.get("worldcover_available", False),
                "smap_available": bool("surface_soil_moisture" in past),
                "smap_quality_flag": 1.0 if "surface_soil_moisture" in past else None,
                "forecast_available": bool(forecast_times),
                "gfs_forecast_age_hours": ((reference - available_forecast["forecast_initialization"].iloc[0]).total_seconds() / 3600)
                if not available_forecast.empty and "forecast_initialization" in available_forecast and pd.notna(available_forecast["forecast_initialization"].iloc[0]) else None,
            }
            features = hourly_dynamic_features(
                observed_times,
                observed_rain,
                reference.to_pydatetime(),
                extras=extras,
                forecast_times=forecast_times,
                forecast_precipitation_mm=forecast_rain,
                quality=quality,
            )
            row = {**static_values, **features}
            row.update({
                "cell_id": cell_id,
                "latitude": float(group["latitude"].iloc[0]),
                "longitude": float(group["longitude"].iloc[0]),
                "reference_timestamp": reference.isoformat(),
                "feature_asof": past["timestamp"].max().isoformat(),
                "forecast_initialization": available_forecast["forecast_initialization"].iloc[0].isoformat()
                if not available_forecast.empty and "forecast_initialization" in available_forecast and pd.notna(available_forecast["forecast_initialization"].iloc[0]) else None,
                "storm_group": str(group.get("storm_group", pd.Series([reference.date().isoformat()])).iloc[0]),
            })
            output.append(row)
    frame = pd.DataFrame(output)
    for name in MODEL_FEATURES:
        if name not in frame:
            frame[name] = None
    return frame


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dynamic", type=Path, required=True)
    parser.add_argument("--static", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference-stride-hours", type=int, default=6)
    args = parser.parse_args()
    frame = build_samples(read_table(args.dynamic), read_table(args.static) if args.static else None, args.reference_stride_hours)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.out, index=False)
    print(f"wrote {len(frame)} event-time samples to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
