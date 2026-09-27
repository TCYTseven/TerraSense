"""Fail-closed live inference for the avalanche-risk model."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.transform import rowcol
from rasterio.warp import transform as warp_transform

from app.config import REPO_ROOT
from app.ml.avalanche_contract import (
    CRITICAL_FEATURES,
    DEFAULT_ABSTENTION_BAND,
    DEFAULT_CELL_SIZE_M,
    DEFAULT_MIN_DATA_QUALITY,
    DEFAULT_MIN_REPORTED_PROBABILITY,
    DEFAULT_OOD_THRESHOLD,
    MODEL_FEATURES,
    PREDICTION_HORIZON_HOURS,
    PredictionState,
)
from app.ml.avalanche_features import avalanche_dynamic_features
from app.risk import cap_probability
from app.weather import HourlyRain, as_of, try_hourly_rain

_configured_artifacts = os.environ.get("AVALANCHE_ARTIFACT_DIR", "").strip()
AVALANCHE_ARTIFACTS = Path(_configured_artifacts) if _configured_artifacts else REPO_ROOT / "ml" / "artifacts" / "avalanche"
if not AVALANCHE_ARTIFACTS.is_absolute():
    AVALANCHE_ARTIFACTS = REPO_ROOT / AVALANCHE_ARTIFACTS
MODEL_PATH = AVALANCHE_ARTIFACTS / "avalanche_lgbm.model"
METADATA_PATH = AVALANCHE_ARTIFACTS / "avalanche_model.json"
CALIBRATION_PATH = AVALANCHE_ARTIFACTS / "avalanche_calibration.json"
STATIC_CELLS_PATH = REPO_ROOT / "data" / "processed" / "static" / "static_cells.json"
FEATURE_STACK_PATH = REPO_ROOT / "data" / "processed" / "features.tif"
AVALANCHE_BBOX = (-121.93, 46.76, -121.54, 46.96)

_cache: tuple[float, Any, dict[str, Any], dict[str, Any]] | None = None
_static_cache: tuple[float, dict[str, dict[str, Any]]] | None = None


@dataclass(frozen=True)
class AvalanchePrediction:
    latitude: float
    longitude: float
    window_start: datetime
    window_end: datetime
    state: PredictionState
    probability: float | None
    high_risk_threshold: float | None
    confidence_lower: float | None
    confidence_upper: float | None
    data_quality_score: float
    ood_score: float | None
    reason_codes: list[str]
    drivers: list[dict[str, Any]]
    snowpack: dict[str, Any]
    data_sources: dict[str, Any]
    model: dict[str, Any]
    # ``probability`` is the API headline; this exact value is retained for calibration and audit.
    calibrated_probability: float | None = None
    probability_floor_applied: bool = False
    probability_floor: float = DEFAULT_MIN_REPORTED_PROBABILITY

    def to_dict(self) -> dict[str, Any]:
        return {
            "location": {"latitude": self.latitude, "longitude": self.longitude},
            "prediction_window": {"start": self.window_start.isoformat(), "end": self.window_end.isoformat()},
            "state": self.state,
            "probability": self.probability,
            "calibrated_probability": self.calibrated_probability,
            "probability_floor_applied": self.probability_floor_applied,
            "probability_floor": round(self.probability_floor, 3),
            "high_risk_threshold": self.high_risk_threshold,
            "confidence": {"lower": self.confidence_lower, "upper": self.confidence_upper},
            "data_quality_score": round(self.data_quality_score, 3),
            "ood_score": None if self.ood_score is None else round(self.ood_score, 3),
            "reason_codes": self.reason_codes,
            "drivers": self.drivers,
            "snowpack": self.snowpack,
            "data_sources": self.data_sources,
            "model": self.model,
        }


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _reported_probability(value: float) -> tuple[float, bool, float]:
    """Apply the API headline floor without changing calibrated model semantics."""
    configured = _env_float("MIN_REPORTED_HAZARD_PROBABILITY", DEFAULT_MIN_REPORTED_PROBABILITY)
    floor = max(DEFAULT_MIN_REPORTED_PROBABILITY, min(1.0, configured))
    bounded = cap_probability(value)
    return round(max(floor, bounded), 4), bounded < floor, floor


def _in_bbox(latitude: float, longitude: float) -> bool:
    west, south, east, north = AVALANCHE_BBOX
    return west <= longitude <= east and south <= latitude <= north


def _load_artifacts() -> tuple[Any | None, dict[str, Any], dict[str, Any], list[str]]:
    global _cache
    if not all(path.is_file() for path in (MODEL_PATH, METADATA_PATH, CALIBRATION_PATH)):
        missing = []
        if not MODEL_PATH.is_file():
            missing.append("MODEL_ARTIFACT_MISSING")
        if not CALIBRATION_PATH.is_file():
            missing.append("CALIBRATION_MISSING")
        return None, {}, {}, missing
    stamp = max(path.stat().st_mtime for path in (MODEL_PATH, METADATA_PATH, CALIBRATION_PATH))
    if _cache and _cache[0] == stamp:
        return _cache[1], _cache[2], _cache[3], []
    try:
        import lightgbm as lgb

        metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
        calibration = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
        feature_names = metadata.get("feature_names")
        if not isinstance(feature_names, list) or not feature_names or not set(feature_names).issubset(set(MODEL_FEATURES)):
            return None, metadata, calibration, ["MODEL_ARTIFACT_MISSING"]
        model = lgb.Booster(model_file=str(MODEL_PATH))
    except (ImportError, OSError, ValueError, json.JSONDecodeError):
        return None, {}, {}, ["MODEL_ARTIFACT_MISSING"]
    _cache = (stamp, model, metadata, calibration)
    return model, metadata, calibration, []


def _load_static_cells() -> dict[str, dict[str, Any]]:
    global _static_cache
    if not STATIC_CELLS_PATH.is_file():
        return {}
    stamp = STATIC_CELLS_PATH.stat().st_mtime
    if _static_cache and _static_cache[0] == stamp:
        return _static_cache[1]
    try:
        rows = json.loads(STATIC_CELLS_PATH.read_text(encoding="utf-8"))
        cells = {str(row["cell_id"]): row for row in rows if row.get("cell_id") is not None}
    except (OSError, ValueError, TypeError, KeyError):
        return {}
    _static_cache = (stamp, cells)
    return cells


def _static_features(latitude: float, longitude: float) -> tuple[dict[str, float | None], dict[str, Any]]:
    features = {name: None for name in MODEL_FEATURES}
    source: dict[str, Any] = {"copernicus_dem": {"available": False}, "static_cells": {"available": False}}
    x, y = warp_transform("EPSG:4326", "EPSG:32610", [longitude], [latitude])
    cell_id = f"{math.floor(x[0] / DEFAULT_CELL_SIZE_M)}:{math.floor(y[0] / DEFAULT_CELL_SIZE_M)}"
    cell = _load_static_cells().get(cell_id)
    if cell:
        for name in MODEL_FEATURES:
            value = cell.get(name)
            if value is not None:
                try:
                    features[name] = float(value)
                except (TypeError, ValueError):
                    pass
        source["static_cells"] = {"available": True, "cell_id": cell_id}
        source["copernicus_dem"] = {"available": bool(features.get("elevation_mean") is not None), "resolution_m": 30}
        return features, source
    if not FEATURE_STACK_PATH.is_file():
        return features, source
    try:
        with rasterio.open(FEATURE_STACK_PATH) as dataset:
            x, y = warp_transform("EPSG:4326", dataset.crs, [longitude], [latitude])
            row, col = rowcol(dataset.transform, x[0], y[0])
            radius = max(1, int(round(500 / max(dataset.res))))
            window = rasterio.windows.Window(col - radius, row - radius, radius * 2 + 1, radius * 2 + 1)
            values = dataset.read(window=window, boundless=True, masked=True).astype("float64")
            descriptions = list(dataset.descriptions)
    except (OSError, ValueError, rasterio.errors.RasterioError):
        return features, source
    bands = {name: np.asarray(values[index].filled(np.nan), dtype="float64") for index, name in enumerate(descriptions) if name}

    def clean(name: str) -> np.ndarray:
        return bands.get(name, np.array([], dtype="float64"))[np.isfinite(bands.get(name, np.array([], dtype="float64")))]

    elevation, slope, aspect = clean("elevation"), clean("slope"), clean("aspect")
    curvature, drainage, landcover = clean("curvature"), clean("dist_drainage"), clean("landcover")
    if elevation.size:
        features.update({"elevation_mean": float(elevation.mean()), "elevation_std": float(elevation.std()), "local_relief_100m": float(elevation.max() - elevation.min()), "local_relief_500m": float(elevation.max() - elevation.min()), "local_relief_1km": float(elevation.max() - elevation.min())})
    if slope.size:
        features.update({
            "slope_mean": float(slope.mean()), "slope_max": float(slope.max()), "slope_p90": float(np.quantile(slope, 0.9)),
            "slope_28_45_fraction": float(np.mean((slope >= 28) & (slope <= 45)),),
            "slope_30_45_fraction": float(np.mean((slope >= 30) & (slope <= 45)),),
            "slope_gt_45_fraction": float(np.mean(slope > 45)),
        })
    if aspect.size:
        features.update({"aspect_sin_mean": float(np.sin(np.deg2rad(aspect)).mean()), "aspect_cos_mean": float(np.cos(np.deg2rad(aspect)).mean()), "northness_mean": float(np.cos(np.deg2rad(aspect)).mean()), "eastness_mean": float(np.sin(np.deg2rad(aspect)).mean())})
    if curvature.size:
        features.update({"profile_curvature_mean": float(curvature.mean()), "plan_curvature_mean": float(curvature.mean())})
    if elevation.size:
        features.update({"roughness_mean": float(elevation.std()), "terrain_ruggedness_mean": float(elevation.std())})
    if drainage.size:
        features["dist_drainage_mean"] = float(drainage.mean())
    if landcover.size:
        features["forest_fraction"] = float(np.mean(landcover == 10))
        features["snow_ice_fraction"] = float(np.mean(landcover == 70))
    features["dem_available"] = 1.0 if elevation.size else 0.0
    features["terrain_resolution_m"] = 30.0
    source["copernicus_dem"] = {"available": bool(elevation.size), "resolution_m": 30}
    return features, source


def _calibrate(raw: float, calibration: dict[str, Any]) -> float:
    if calibration.get("method") == "isotonic":
        return float(np.interp(raw, calibration["x_thresholds"], calibration["y_thresholds"]))
    if calibration.get("method") == "platt":
        value = float(calibration["coef"]) * raw + float(calibration["intercept"])
        return float(1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, value)))))
    return float(raw)


def _ood(features: dict[str, float | None], metadata: dict[str, Any]) -> tuple[float, list[str]]:
    distributions = metadata.get("feature_distributions", {})
    checked = 0
    outliers = 0
    for name in MODEL_FEATURES:
        value = features.get(name)
        low, high = distributions.get(name, {}).get("p01"), distributions.get(name, {}).get("p99")
        if value is None or low is None or high is None:
            continue
        checked += 1
        outliers += int(float(value) < float(low) or float(value) > float(high))
    score = outliers / max(1, checked)
    threshold = float(metadata.get("ood_threshold", DEFAULT_OOD_THRESHOLD))
    return score, ["OUT_OF_DISTRIBUTION"] if score >= threshold else []


def _quality(features: dict[str, float | None]) -> tuple[float, list[str]]:
    missing = sum(features.get(name) is None for name in MODEL_FEATURES)
    score = max(0.0, 1.0 - missing / len(MODEL_FEATURES))
    reasons: list[str] = []
    for name in CRITICAL_FEATURES:
        if features.get(name) is None or (name.endswith("available") and not features.get(name)):
            reasons.append("SNOWPACK_MISSING" if name == "snowpack_available" else "FORECAST_UNAVAILABLE" if name == "forecast_available" else "STATIC_DATA_MISSING")
    if features.get("snowpack_age_hours") is not None and features["snowpack_age_hours"] > 24:
        reasons.append("SNOWPACK_STALE")
    if features.get("forecast_age_hours") is not None and features["forecast_age_hours"] > 12:
        reasons.append("FORECAST_STALE")
    if features.get("feature_missing_fraction", 1.0) > 0.65:
        reasons.append("LOW_DATA_QUALITY")
    return score, list(dict.fromkeys(reasons))


def _empty(latitude: float, longitude: float, start: datetime, reasons: list[str], sources: dict[str, Any] | None = None) -> AvalanchePrediction:
    return AvalanchePrediction(latitude, longitude, start, start + timedelta(hours=PREDICTION_HORIZON_HOURS), "UNCERTAIN", None, None, None, None, 0.0, None, list(dict.fromkeys(reasons)), [], {}, sources or {}, {"available": False})


def _drivers(model: Any, features: dict[str, float | None]) -> list[dict[str, Any]]:
    try:
        names = list(model.feature_name())
        importance = model.feature_importance(importance_type="gain")
    except Exception:
        return []
    labels = {
        "slope_30_45_fraction": "30–45° starting-zone terrain",
        "new_snow_24h_cm": "new snow in the last 24 hours",
        "wind_loading_proxy_24h": "wind loading proxy",
        "rain_on_snow_24h": "rain on an existing snowpack",
        "temperature_change_24h": "rapid temperature change",
        "forecast_snowfall_0_72h": "forecast snowfall over 72 hours",
        "persistent_weak_layer_signal": "reported persistent weak-layer signal",
    }
    ranked = sorted(zip(names, importance, strict=False), key=lambda item: float(item[1]), reverse=True)
    return [{"feature": name, "label": labels.get(name, name.replace("_", " ")), "value": features.get(name), "importance": round(float(score), 4), "direction": "model risk driver"} for name, score in ranked[:6] if features.get(name) is not None]


def predict_location(latitude: float, longitude: float, timestamp: datetime | None = None, *, conditions_override: HourlyRain | None = None, static_override: dict[str, float | None] | None = None) -> AvalanchePrediction:
    if timestamp is not None and timestamp.tzinfo is None:
        start = timestamp.replace(tzinfo=UTC)
        return _empty(latitude, longitude, start, ["TIMESTAMP_ALIGNMENT_ERROR"])
    start = (timestamp or datetime.now(UTC).replace(minute=0, second=0, microsecond=0)).astimezone(UTC)
    if timestamp is not None and abs((datetime.now(UTC) - start).total_seconds()) > 3600:
        return _empty(latitude, longitude, start, ["HISTORICAL_INFERENCE_UNSUPPORTED"])
    if not _in_bbox(latitude, longitude):
        return _empty(latitude, longitude, start, ["OUT_OF_DISTRIBUTION"])
    conditions, error = (conditions_override, None) if conditions_override is not None else try_hourly_rain(latitude, longitude)
    if static_override is not None:
        static, sources = static_override, {"static_override": {"available": True}}
    else:
        static, sources = _static_features(latitude, longitude)
    if conditions is None:
        sources["forecast"] = {"available": False, "error": error}
        return _empty(latitude, longitude, start, ["FORECAST_UNAVAILABLE", "WEATHER_DATA_MISSING"], sources)

    provider = os.environ.get("AVALANCHE_FORECAST_PROVIDER", "gfs").strip().lower()
    forecast_is_operational = provider in {"gfs", "gefs"} and conditions.source.lower() in {"gfs", "gefs"}
    features = avalanche_dynamic_features(
        conditions.times,
        start,
        precipitation_mm=conditions.precipitation_mm,
        snowfall_cm=conditions.snowfall_cm,
        snow_depth_m=conditions.snow_depth_m,
        snow_water_equivalent_mm=conditions.snow_water_equivalent_mm,
        temperature_c=conditions.temperature_c,
        wind_speed_kmh=conditions.wind_kmh,
        wind_gust_kmh=conditions.wind_gust_kmh,
        wind_direction_deg=conditions.wind_direction_deg,
        freezing_level_m=conditions.freezing_level_m,
        forecast_times=conditions.times,
        forecast_precipitation_mm=conditions.precipitation_mm,
        forecast_snowfall_cm=conditions.snowfall_cm,
        forecast_temperature_c=conditions.temperature_c,
        forecast_wind_speed_kmh=conditions.wind_kmh,
        forecast_wind_gust_kmh=conditions.wind_gust_kmh,
        forecast_freezing_level_m=conditions.freezing_level_m,
        static=static,
        quality={
            "dem_available": static.get("elevation_mean") is not None,
            "static_snow_terrain_available": static.get("snow_ice_fraction") is not None,
            "snowpack_available": bool(conditions.snow_depth_m or conditions.snow_water_equivalent_mm),
            "snowpack_age_hours": 0.0 if conditions.snow_depth_m or conditions.snow_water_equivalent_mm else None,
            "forecast_available": forecast_is_operational,
            "forecast_age_hours": 0.0 if forecast_is_operational else None,
            "weather_station_available": False,
            "terrain_resolution_m": 30.0 if static.get("elevation_mean") is not None else None,
            "weather_resolution_km": 13.0 if forecast_is_operational else None,
        },
    )
    sources.update({
        "forecast": {"provider": provider, "available": forecast_is_operational, "actual_source": conditions.source, "as_of": as_of(conditions).isoformat()},
        "snowpack": {"available": bool(conditions.snow_depth_m or conditions.snow_water_equivalent_mm), "source": conditions.source},
    })
    quality, reasons = _quality(features)
    if not forecast_is_operational:
        reasons.extend(["FORECAST_UNAVAILABLE", "FORECAST_STALE"])
    model, metadata, calibration, artifact_reasons = _load_artifacts()
    reasons.extend(artifact_reasons)
    ood_score, ood_reasons = _ood(features, metadata) if metadata else (None, [])
    reasons.extend(ood_reasons)
    threshold = metadata.get("selected_threshold") if metadata else None
    if model is None or calibration.get("method") not in {"isotonic", "platt", "raw"}:
        reasons.append("CALIBRATION_MISSING") if model is not None else None
        return AvalanchePrediction(latitude, longitude, start, start + timedelta(hours=PREDICTION_HORIZON_HOURS), "UNCERTAIN", None, threshold, None, None, quality, ood_score, list(dict.fromkeys(reasons)), [], {
            "snow_depth_m": features.get("snow_depth_m"), "new_snow_24h_cm": features.get("new_snow_24h_cm"), "forecast_snowfall_72h_cm": features.get("forecast_snowfall_0_72h"),
        }, sources, {"available": False, "version": metadata.get("model_version")})
    model_features = metadata.get("feature_names", list(MODEL_FEATURES))
    row = np.array([[np.nan if features.get(name) is None else float(features[name]) for name in model_features]], dtype="float64")
    raw = float(model.predict(row)[0])
    probability = max(0.0, min(1.0, _calibrate(raw, calibration)))
    band = float(metadata.get("abstention_band", DEFAULT_ABSTENTION_BAND))
    if threshold is None or abs(probability - float(threshold)) <= band:
        reasons.append("ABSTENTION_BAND")
    state: PredictionState = "UNCERTAIN" if reasons or quality < _env_float("AVALANCHE_MIN_DATA_QUALITY", DEFAULT_MIN_DATA_QUALITY) else ("HIGH_RISK" if probability >= float(threshold) else "NOT_HIGH_RISK")
    uncertainty = min(0.45, 0.08 + (ood_score or 0.0) * 0.5 + (1.0 - quality) * 0.4)
    reported_probability, floor_applied, floor = _reported_probability(probability)
    return AvalanchePrediction(latitude, longitude, start, start + timedelta(hours=PREDICTION_HORIZON_HOURS), state, reported_probability, threshold, round(cap_probability(probability - uncertainty), 4), round(cap_probability(probability + uncertainty), 4), quality, ood_score, list(dict.fromkeys(reasons)), _drivers(model, features), {
        "snow_depth_m": features.get("snow_depth_m"), "new_snow_24h_cm": features.get("new_snow_24h_cm"), "forecast_snowfall_72h_cm": features.get("forecast_snowfall_0_72h"), "wind_loading_proxy_24h": features.get("wind_loading_proxy_24h"),
    }, sources, {"available": True, "version": metadata.get("model_version"), "trained_at": metadata.get("training_date"), "calibration_method": calibration.get("method"), "validation": metadata.get("validation")}, calibrated_probability=round(cap_probability(probability), 4), probability_floor_applied=floor_applied, probability_floor=floor)
