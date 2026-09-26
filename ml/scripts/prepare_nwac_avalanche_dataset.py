#!/usr/bin/env python3
"""Prepare a Rainier NWAC observed-weather avalanche table.

This script deliberately builds a retrospective *observed-weather proxy*: it uses weather up to
the reference timestamp and does not manufacture future forecast values.  The canonical feature
function is shared with live inference, while forecast features remain missing.  The resulting
artifact is useful for testing labels, terrain/snowpack feature behavior, and software plumbing;
it is not an operational forecast model until historical as-of GFS/GEFS forecasts are joined.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.ml.avalanche_contract import MODEL_FEATURES  # noqa: E402
from app.ml.avalanche_features import avalanche_dynamic_features  # noqa: E402


def _json_results(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("results", []))


def load_records(nwac_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    avalanche_records: list[dict[str, Any]] = []
    field_records: list[dict[str, Any]] = []
    for path in sorted(nwac_dir.glob("avalanche_observations*.json")):
        avalanche_records.extend(_json_results(path))
    for path in sorted(nwac_dir.glob("field_observations*.json")):
        field_records.extend(_json_results(path))
    # A downloaded run and a manually cached page can coexist.  De-duplicate by source id so
    # repeated downloads cannot inflate recent-activity features or the apparent sample count.
    def unique(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        output: list[dict[str, Any]] = []
        for record in records:
            key = str(record.get("id") or record.get("observation_id") or repr(record))
            if key not in seen:
                seen.add(key)
                output.append(record)
        return output

    avalanche_records = unique(avalanche_records)
    field_records = unique(field_records)
    if not avalanche_records or not field_records:
        raise ValueError(f"expected both NWAC avalanche and field records in {nwac_dir}")
    return avalanche_records, field_records


def load_snotel(path: Path) -> pd.DataFrame:
    """Parse the NRCS HTML export without adding a heavyweight HTML dependency."""
    text = path.read_text(encoding="utf-8", errors="ignore")
    start = text.find('<tbody id="tabPanel:formReport:tblViewData_data"')
    end = text.find("</tbody>", start)
    if start < 0 or end < 0:
        raise ValueError(f"NRCS report table not found: {path}")
    rows: list[dict[str, Any]] = []
    for raw_row in re.findall(r"<tr[^>]*>(.*?)</tr>", text[start:end], re.DOTALL):
        cells = []
        for raw_cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", raw_row, re.DOTALL):
            value = html.unescape(re.sub(r"<[^>]+>", " ", raw_cell))
            cells.append(" ".join(value.split()))
        if len(cells) < 5:
            continue
        parsed = pd.to_datetime(cells[0], errors="coerce")
        if pd.isna(parsed):
            continue
        # The report is in Pacific local time.  For the repeated fall-back hour, choose the
        # second (standard-time) occurrence; the one-hour ambiguity is smaller than inventing
        # a future observation and is recorded by the source's hourly quality limitations.
        timestamp = parsed.tz_localize("America/Los_Angeles", ambiguous=False, nonexistent="shift_forward").tz_convert("UTC")
        values = []
        for item in cells[1:5]:
            try:
                values.append(float(item))
            except ValueError:
                values.append(None)
        rows.append({"timestamp": timestamp, "snotel_swe_mm": None if values[0] is None else values[0] * 25.4, "snotel_snow_depth_m": None if values[1] is None else values[1] * 0.0254})
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError(f"NRCS report has no hourly rows: {path}")
    return frame.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)


def load_weather(path: Path, snotel_path: Path | None = None) -> pd.DataFrame:
    payload = json.loads(path.read_text(encoding="utf-8"))
    hourly = payload.get("hourly", {})
    frame = pd.DataFrame(hourly)
    if frame.empty or "time" not in frame:
        raise ValueError(f"weather file has no hourly time series: {path}")
    frame["timestamp"] = pd.to_datetime(frame.pop("time"), utc=True)
    rename = {
        "precipitation": "precipitation_mm",
        "snowfall": "snowfall_cm",
        "snow_depth": "snow_depth_m",
        "temperature_2m": "temperature_c",
        "wind_speed_10m": "wind_speed_kmh",
        "wind_gusts_10m": "wind_gust_kmh",
        "wind_direction_10m": "wind_direction_deg",
    }
    frame = frame.rename(columns=rename).sort_values("timestamp").reset_index(drop=True)
    if snotel_path is not None and snotel_path.is_file():
        snotel = load_snotel(snotel_path)
        merged = pd.merge_asof(frame[["timestamp"]], snotel, on="timestamp", direction="backward", tolerance=pd.Timedelta(hours=6))
        frame["snow_depth_m"] = merged["snotel_snow_depth_m"].combine_first(frame.get("snow_depth_m"))
        frame["snow_water_equivalent_mm"] = merged["snotel_swe_mm"]
    return frame.reset_index(drop=True)


def _nearest_cell(latitude: float, longitude: float, static: pd.DataFrame) -> pd.Series:
    distance = (static["latitude"] - latitude) ** 2 + ((static["longitude"] - longitude) * math.cos(math.radians(latitude))) ** 2
    return static.loc[distance.idxmin()]


def _timestamp(value: str | None, *, fallback_hour: int = 0) -> pd.Timestamp | None:
    if not value:
        return None
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        return None
    if parsed.hour == 0 and parsed.minute == 0 and parsed.second == 0 and fallback_hour:
        parsed = parsed + pd.Timedelta(hours=fallback_hour)
    return parsed


def _record_time(record: dict[str, Any], date_key: str) -> pd.Timestamp | None:
    date_value = record.get(date_key) or record.get("date")
    if not date_value:
        return None
    clock = str(record.get("time") or "00:00:00").replace("Z", "+00:00")
    try:
        return pd.Timestamp(f"{date_value}T{clock}", tz="UTC")
    except (TypeError, ValueError):
        parsed = pd.to_datetime(date_value, utc=True, errors="coerce")
        return None if pd.isna(parsed) else parsed


def _instability_signal(record: dict[str, Any]) -> float | None:
    instability = record.get("instability") or {}
    if not instability:
        return None
    return float(bool(instability.get("cracking") or instability.get("collapsing") or instability.get("avalanches_triggered")))


def _recent_event_count(events: list[dict[str, Any]], reference: pd.Timestamp, cell_id: str, static: pd.DataFrame) -> int:
    start = reference - pd.Timedelta(days=7)
    count = 0
    for event in events:
        event_time = _record_time(event, "date")
        point = event.get("location_point") or {}
        # Strictly before T: an event reported on the reference date is part of the target
        # window and must never be used as a "recent activity" feature for that sample.
        if event_time is None or event_time >= reference or event_time < start or point.get("lat") is None:
            continue
        mapped = str(_nearest_cell(float(point["lat"]), float(point["lng"]), static)["cell_id"])
        count += int(mapped == cell_id)
    return count


def _weather_arrays(weather: pd.DataFrame, reference: pd.Timestamp) -> dict[str, list[Any]]:
    history = weather.loc[weather["timestamp"] <= reference].copy()
    if history.empty:
        return {"times": [], "reference_time": reference.to_pydatetime()}
    values: dict[str, Any] = {"times": history["timestamp"].dt.to_pydatetime().tolist(), "reference_time": reference.to_pydatetime()}
    for name in ("precipitation_mm", "snowfall_cm", "snow_depth_m", "temperature_c", "wind_speed_kmh", "wind_gust_kmh", "wind_direction_deg"):
        values[name] = history[name].where(history[name].notna(), None).tolist() if name in history else []
    return values


def _forecast_arrays(forecast: pd.DataFrame | None, reference: pd.Timestamp) -> dict[str, Any]:
    """Convert long NOAA forecast rows into the canonical forecast arrays at ``T``."""
    if forecast is None or forecast.empty:
        return {"forecast_times": [], "forecast_available": False, "forecast_age_hours": None}
    frame = forecast.copy()
    frame["forecast_timestamp"] = pd.to_datetime(frame["forecast_timestamp"], utc=True)
    frame = frame.loc[
        (frame["forecast_timestamp"] >= reference)
        & (frame["forecast_timestamp"] < reference + pd.Timedelta(hours=72))
    ].sort_values("forecast_timestamp")
    if frame.empty:
        return {"forecast_times": [], "forecast_available": False, "forecast_age_hours": None}
    output: dict[str, Any] = {"forecast_times": frame["forecast_timestamp"].dt.to_pydatetime().tolist(), "forecast_available": True}
    mapping = {
        "forecast_precipitation_mm": "forecast_precipitation_mm",
        "forecast_snowfall_cm": "forecast_snowfall_cm",
        "forecast_temperature_c": "forecast_temperature_c",
        "forecast_wind_speed_kmh": "forecast_wind_speed_kmh",
        "forecast_wind_gust_kmh": "forecast_wind_gust_kmh",
        "forecast_wind_direction_deg": "forecast_wind_direction_deg",
    }
    for source, target in mapping.items():
        output[target] = frame[source].where(frame[source].notna(), None).tolist() if source in frame else []
    summary = frame.iloc[0]
    output["forecast_ensemble_snowfall_summary"] = {
        "mean": summary.get("forecast_snowfall_ensemble_mean"),
        "p90": summary.get("forecast_snowfall_ensemble_p90"),
        "p95": summary.get("forecast_snowfall_ensemble_p95"),
        "spread": summary.get("forecast_snowfall_ensemble_spread"),
        "exceedance_probability": summary.get("forecast_exceedance_probability"),
    }
    initialization = pd.to_datetime(frame["forecast_initialization"].iloc[0], utc=True, errors="coerce") if "forecast_initialization" in frame else pd.NaT
    output["forecast_age_hours"] = None if pd.isna(initialization) else float((reference - initialization).total_seconds() / 3600.0)
    return output


def _feature_row(
    *,
    latitude: float,
    longitude: float,
    reference: pd.Timestamp,
    label: int,
    cell: pd.Series,
    weather: pd.DataFrame,
    events: list[dict[str, Any]],
    coverage: float | None,
    positive_event_id: str | None,
    source_record_id: str,
    label_confidence: str,
    forecast: pd.DataFrame | None = None,
) -> dict[str, Any]:
    static = {key: value for key, value in cell.to_dict().items() if key != "cell_id"}
    kwargs = _weather_arrays(weather, reference)
    forecast_kwargs = _forecast_arrays(forecast, reference)
    kwargs.update({key: value for key, value in forecast_kwargs.items() if key not in {"forecast_available", "forecast_age_hours"}})
    kwargs["static"] = static
    kwargs["context"] = {
        "event_observation_coverage": coverage,
        "recent_avalanche_count_7d": float(_recent_event_count(events, reference, str(cell["cell_id"]), pd.DataFrame([cell]))),
    }
    kwargs["quality"] = {
        "dem_available": bool(cell.get("dem_available", False)),
        "static_snow_terrain_available": pd.notna(cell.get("snow_ice_fraction")),
        "snowpack_available": True,
        "snowpack_age_hours": 6.0 if "snow_water_equivalent_mm" in weather else 0.0,
        "forecast_available": forecast_kwargs.get("forecast_available", False),
        "forecast_age_hours": forecast_kwargs.get("forecast_age_hours"),
        "weather_station_available": False,
        "terrain_resolution_m": 30.0,
        "weather_resolution_km": 11.0,
    }
    features = avalanche_dynamic_features(**kwargs)
    row = {**static, **features}
    forecast_initialization = None
    forecast_source = None
    if forecast is not None and not forecast.empty:
        forecast_initialization = str(forecast["forecast_initialization"].iloc[0]) if "forecast_initialization" in forecast else None
        forecast_source = str(forecast["forecast_source"].iloc[0]) if "forecast_source" in forecast else None
    row.update(
        {
            "cell_id": str(cell["cell_id"]),
            "latitude": float(latitude),
            "longitude": float(longitude),
            "region": f"{math.floor(latitude):+03d}:{math.floor(longitude):+04d}",
            "reference_timestamp": reference.isoformat(),
            "feature_asof": max(kwargs["times"]).isoformat() if kwargs["times"] else None,
            "forecast_initialization": forecast_initialization,
            "forecast_source": forecast_source,
            "label": int(label),
            "positive_event_id": positive_event_id,
            "source_record_id": source_record_id,
            "label_confidence": label_confidence,
            "negative_source_type": "observed_no_avalanche" if label == 0 else "nwac_avalanche_observation",
            "negative_eligible": bool(label == 1 or coverage is not None),
        }
    )
    for name in MODEL_FEATURES:
        row.setdefault(name, None)
    return row


def build_table(
    nwac_dir: Path,
    weather_path: Path,
    static_path: Path,
    snotel_path: Path | None = None,
    forecast_path: Path | None = None,
) -> pd.DataFrame:
    events, field = load_records(nwac_dir)
    static = pd.read_parquet(static_path)
    weather = load_weather(weather_path, snotel_path)
    forecast_table = pd.read_parquet(forecast_path) if forecast_path is not None and forecast_path.is_file() else pd.DataFrame()
    if not forecast_table.empty:
        forecast_table["reference_timestamp"] = pd.to_datetime(forecast_table["reference_timestamp"], utc=True)
        forecast_by_key = {
            (str(cell_id), str(reference)): group.copy()
            for (cell_id, reference), group in forecast_table.groupby(["cell_id", "reference_timestamp"], sort=False)
        }
    else:
        forecast_by_key = {}

    def forecast_for(cell_id: str, reference: pd.Timestamp) -> pd.DataFrame | None:
        return forecast_by_key.get((cell_id, str(reference)))

    rows: list[dict[str, Any]] = []
    positive_keys: set[tuple[str, str]] = set()
    for event in events:
        point = event.get("location_point") or {}
        event_time = _record_time(event, "date")
        if event_time is None or point.get("lat") is None or point.get("lng") is None:
            continue
        cell = _nearest_cell(float(point["lat"]), float(point["lng"]), static)
        reference = pd.Timestamp(event_time.date(), tz="UTC")
        key = (str(cell["cell_id"]), reference.date().isoformat())
        if key in positive_keys:
            continue
        positive_keys.add(key)
        # This field is a data-quality indicator, not a label proxy.  Keep its value
        # identical across classes; occurrence records do not provide areal no-event coverage.
        rows.append(_feature_row(latitude=float(point["lat"]), longitude=float(point["lng"]), reference=reference, label=1, cell=cell, weather=weather, events=events, coverage=0.85, positive_event_id=str(event.get("id") or event.get("observation_id")), source_record_id=str(event.get("id") or "unknown"), label_confidence="verified" if event.get("forecaster_verified") else "published", forecast=forecast_for(str(cell["cell_id"]), reference)))

    negative_keys: set[tuple[str, str]] = set()
    for report in field:
        point = report.get("location_point") or {}
        reference = _timestamp(report.get("start_date"))
        instability = report.get("instability") or {}
        if reference is None or point.get("lat") is None or point.get("lng") is None or instability.get("avalanches_observed") is not False:
            continue
        cell = _nearest_cell(float(point["lat"]), float(point["lng"]), static)
        reference = pd.Timestamp(reference.date(), tz="UTC")
        key = (str(cell["cell_id"]), reference.date().isoformat())
        if key in positive_keys or key in negative_keys:
            continue
        negative_keys.add(key)
        rows.append(_feature_row(latitude=float(point["lat"]), longitude=float(point["lng"]), reference=reference, label=0, cell=cell, weather=weather, events=events, coverage=0.85, positive_event_id=None, source_record_id=str(report.get("id") or "unknown"), label_confidence="field_observation_no_avalanche", forecast=forecast_for(str(cell["cell_id"]), reference)))
    frame = pd.DataFrame(rows)
    if frame.empty or frame["label"].nunique() < 2:
        raise ValueError("NWAC records did not produce both classes")
    frame["reference_timestamp"] = pd.to_datetime(frame["reference_timestamp"], utc=True).astype(str)
    frame = frame.sort_values(["reference_timestamp", "cell_id"]).reset_index(drop=True)
    return frame


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nwac-dir", type=Path, default=REPO_ROOT / "data/raw/avalanche/nwac")
    parser.add_argument("--weather", type=Path, default=REPO_ROOT / "data/raw/avalanche/weather/openmeteo_46.8500_-121.7500_2023-10-25_2026-07-20.json")
    parser.add_argument("--snotel", type=Path, default=REPO_ROOT / "data/raw/avalanche/snotel/paradise_679_2023-10-25_2026-07-20.html")
    parser.add_argument("--static", type=Path, default=REPO_ROOT / "data/processed/static/static_cells.parquet")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data/processed/avalanche_nwac_observed_proxy.parquet")
    parser.add_argument("--forecast", type=Path, help="Long NOAA forecast table produced by download_noaa_historical_forecasts.py")
    args = parser.parse_args()
    frame = build_table(args.nwac_dir, args.weather, args.static, args.snotel, args.forecast)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.out, index=False)
    summary = {"rows": len(frame), "positives": int(frame["label"].sum()), "negatives": int((frame["label"] == 0).sum()), "date_min": frame["reference_timestamp"].min(), "date_max": frame["reference_timestamp"].max(), "forecast_rows": int(frame["forecast_available"].fillna(0).sum()), "forecast_path": str(args.forecast) if args.forecast else None, "out": str(args.out)}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
