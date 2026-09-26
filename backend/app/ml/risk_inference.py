"""Production inference for calibrated rainfall-triggered landslide risk.

The legacy susceptibility/Model-B path remains available to the map and agents.  This module is
the stricter cell-level classifier: missing calibration, stale forecast data, or out-of-domain
features produce ``UNCERTAIN`` rather than a confident negative.
"""

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
from rasterio.windows import Window
from rasterio.warp import transform as warp_transform

from app.config import REPO_ROOT
from app.ml.risk_contract import (
    DEFAULT_ABSTENTION_BAND,
    DEFAULT_MIN_DATA_QUALITY,
    DEFAULT_OOD_THRESHOLD,
    MODEL_FEATURES,
    PREDICTION_HORIZON_HOURS,
    PredictionState,
)
from app.ml.risk_features import hourly_dynamic_features
from app.risk import LIVE_BBOX
from app.weather import HourlyRain, as_of, try_hourly_rain

RISK_MODEL_PATH = REPO_ROOT / "ml" / "artifacts" / "landslide_risk_lgbm.txt"
RISK_METADATA_PATH = REPO_ROOT / "ml" / "artifacts" / "risk_model.json"
RISK_CALIBRATION_PATH = REPO_ROOT / "ml" / "artifacts" / "risk_calibration.json"
FEATURE_STACK_PATH = REPO_ROOT / "data" / "processed" / "features.tif"
STATIC_CELLS_JSON_PATH = REPO_ROOT / "data" / "processed" / "static" / "static_cells.json"
RAINIER_BBOX = LIVE_BBOX  # shared fact, from app/risk.py

_model_cache: tuple[float, Any, dict[str, Any], dict[str, Any]] | None = None
_static_cells_cache: tuple[float, dict[str, dict[str, Any]]] | None = None


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class RiskPrediction:
    latitude: float
    longitude: float
    window_start: datetime
    window_end: datetime
    state: PredictionState
    calibrated_probability: float | None
    high_risk_threshold: float | None
    confidence_lower: float | None
    confidence_upper: float | None
    data_quality_score: float
    ood_score: float | None
    reason_codes: list[str]
    drivers: list[dict[str, Any]]
    data_sources: dict[str, Any]
    model: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "location": {"latitude": self.latitude, "longitude": self.longitude},
            "prediction_window": {"start": self.window_start.isoformat(), "end": self.window_end.isoformat()},
            "state": self.state,
            "calibrated_probability": self.calibrated_probability,
            "high_risk_threshold": self.high_risk_threshold,
            "confidence": {"lower": self.confidence_lower, "upper": self.confidence_upper},
            "data_quality_score": round(self.data_quality_score, 3),
            "ood_score": None if self.ood_score is None else round(self.ood_score, 3),
            "reason_codes": self.reason_codes,
            "drivers": self.drivers,
            "data_sources": self.data_sources,
            "model": self.model,
        }


def _now() -> datetime:
    return datetime.now(UTC).replace(minute=0, second=0, microsecond=0)


def _in_bbox(latitude: float, longitude: float) -> bool:
    west, south, east, north = RAINIER_BBOX
    return west <= longitude <= east and south <= latitude <= north


def _load_artifacts() -> tuple[Any | None, dict[str, Any], dict[str, Any], list[str]]:
    """Load the model, metadata, and calibration lazily; no import-time crash when unbuilt."""
    global _model_cache
    paths = (RISK_MODEL_PATH, RISK_METADATA_PATH, RISK_CALIBRATION_PATH)
    if not all(path.is_file() for path in paths):
        missing = [str(path.relative_to(REPO_ROOT)) for path in paths if not path.is_file()]
        return None, {}, {}, ["MODEL_ARTIFACT_MISSING" if "landslide_risk_lgbm" in item else "CALIBRATION_MISSING" for item in missing]
    stamp = max(path.stat().st_mtime for path in paths)
    if _model_cache and _model_cache[0] == stamp:
        return _model_cache[1], _model_cache[2], _model_cache[3], []
    try:
        import lightgbm as lgb

        metadata = json.loads(RISK_METADATA_PATH.read_text(encoding="utf-8"))
        calibration = json.loads(RISK_CALIBRATION_PATH.read_text(encoding="utf-8"))
        model = lgb.Booster(model_file=str(RISK_MODEL_PATH))
        if metadata.get("feature_names") != list(MODEL_FEATURES):
            return None, metadata, calibration, ["MODEL_ARTIFACT_MISSING"]
    except (ImportError, OSError, ValueError, json.JSONDecodeError):
        return None, {}, {}, ["MODEL_ARTIFACT_MISSING"]
    _model_cache = (stamp, model, metadata, calibration)
    return model, metadata, calibration, []


def _load_static_cells() -> dict[str, dict[str, Any]]:
    """Load the cell-aggregated static artifact without adding a dataframe dependency to the API."""
    global _static_cells_cache
    if not STATIC_CELLS_JSON_PATH.is_file():
        return {}
    stamp = STATIC_CELLS_JSON_PATH.stat().st_mtime
    if _static_cells_cache and _static_cells_cache[0] == stamp:
        return _static_cells_cache[1]
    try:
        rows = json.loads(STATIC_CELLS_JSON_PATH.read_text(encoding="utf-8"))
        cells = {str(row["cell_id"]): row for row in rows if row.get("cell_id") is not None}
    except (OSError, ValueError, TypeError, KeyError):
        return {}
    _static_cells_cache = (stamp, cells)
    return cells


def _calibrate(raw: float, calibration: dict[str, Any]) -> float:
    if calibration.get("method") == "isotonic":
        value = float(np.interp(raw, calibration["x_thresholds"], calibration["y_thresholds"]))
    elif calibration.get("method") == "platt":
        logit = float(calibration["coef"]) * raw + float(calibration["intercept"])
        value = 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, logit))))
    else:
        raise ValueError("unknown calibration method")
    return max(0.0, min(1.0, value))


def _static_features(latitude: float, longitude: float) -> tuple[dict[str, float | None], dict[str, Any]]:
    """Aggregate currently available 30m terrain cells around a 1km prediction cell.

    The current Rainier stack contains the legacy terrain bands.  New SoilGrids, roads, and
    geology fields remain explicitly missing until their source adapters populate the stack; the
    quality gate then abstains instead of silently treating them as zero.
    """
    features = {name: None for name in MODEL_FEATURES}
    source = {"copernicus_dem": {"available": False}, "worldcover": {"available": False}, "soilgrids": {"available": False}, "osm": {"available": False}, "geology": {"available": False}}
    x, y = warp_transform("EPSG:4326", "EPSG:32610", [longitude], [latitude])
    cell_id = f"{math.floor(x[0] / 1000)}:{math.floor(y[0] / 1000)}"
    static_cell = _load_static_cells().get(cell_id)
    if static_cell:
        for name in MODEL_FEATURES:
            value = static_cell.get(name)
            if value is not None:
                try:
                    features[name] = float(value)
                except (TypeError, ValueError):
                    pass
        source["copernicus_dem"] = {"available": bool(features.get("dem_available", 0.0)), "resolution_m": 30}
        source["worldcover"] = {"available": bool(features.get("worldcover_available", 0.0)), "resolution_m": 10}
        source["soilgrids"] = {"available": bool(features.get("soilgrids_available", 0.0)), "resolution_m": "source"}
        return features, source
    if not FEATURE_STACK_PATH.is_file():
        return features, source
    with rasterio.open(FEATURE_STACK_PATH) as dataset:
        x, y = warp_transform("EPSG:4326", dataset.crs, [longitude], [latitude])
        row, col = dataset.index(x[0], y[0])
        radius = max(1, int(round(500 / max(dataset.res))))
        window = Window(col - radius, row - radius, radius * 2 + 1, radius * 2 + 1)
        values = dataset.read(window=window, boundless=True, masked=True).astype("float64")
        descriptions = list(dataset.descriptions)
    bands: dict[str, np.ndarray] = {}
    for index, description in enumerate(descriptions):
        if description:
            bands[description] = np.asarray(values[index].filled(np.nan), dtype="float64")
    elevation = bands.get("elevation")
    slope = bands.get("slope")
    aspect = bands.get("aspect")
    curvature = bands.get("curvature")
    drainage = bands.get("dist_drainage")
    landcover = bands.get("landcover")
    twi = bands.get("twi")

    def clean(band: np.ndarray | None) -> np.ndarray:
        return band[np.isfinite(band)] if band is not None else np.array([], dtype="float64")

    def avg(band: np.ndarray | None) -> float | None:
        data = clean(band)
        return round(float(data.mean()), 6) if data.size else None

    def pct(band: np.ndarray | None, q: float) -> float | None:
        data = clean(band)
        return round(float(np.quantile(data, q)), 6) if data.size else None

    features.update({
        "elevation_mean": avg(elevation),
        "elevation_std": round(float(np.nanstd(elevation)), 6) if elevation is not None else None,
        "slope_mean": avg(slope),
        "slope_max": float(np.nanmax(slope)) if slope is not None and clean(slope).size else None,
        "slope_p90": pct(slope, 0.9),
        "aspect_sin_mean": avg(np.sin(np.deg2rad(aspect))) if aspect is not None else None,
        "aspect_cos_mean": avg(np.cos(np.deg2rad(aspect))) if aspect is not None else None,
        "profile_curvature_mean": avg(curvature),
        "plan_curvature_mean": avg(curvature),
        "roughness_mean": round(float(np.nanstd(elevation)), 6) if elevation is not None else None,
        "terrain_ruggedness_mean": round(float(np.nanstd(elevation)), 6) if elevation is not None else None,
        "local_relief_100m": round(float(np.nanmax(elevation) - np.nanmin(elevation)), 6) if elevation is not None else None,
        "local_relief_500m": round(float(np.nanmax(elevation) - np.nanmin(elevation)), 6) if elevation is not None else None,
        "local_relief_1km": round(float(np.nanmax(elevation) - np.nanmin(elevation)), 6) if elevation is not None else None,
        "twi_mean": avg(twi),
        "flow_accumulation_mean": None,
        "dist_drainage_mean": avg(drainage),
    })
    if landcover is not None:
        valid = clean(landcover)
        if valid.size:
            features.update({
                "forest_fraction": float(np.mean(valid == 10)),
                "shrub_fraction": float(np.mean(valid == 20)),
                "grassland_fraction": float(np.mean(valid == 30)),
                "cropland_fraction": float(np.mean(valid == 40)),
                "built_fraction": float(np.mean(valid == 50)),
                "bare_fraction": float(np.mean(valid == 60)),
                "water_fraction": float(np.mean(valid == 80)),
                "snow_ice_fraction": float(np.mean(valid == 70)),
            })
    source["copernicus_dem"] = {"available": bool(elevation is not None and clean(elevation).size), "resolution_m": 30}
    source["worldcover"] = {"available": bool(landcover is not None and clean(landcover).size), "resolution_m": 10}
    features["dem_available"] = float(source["copernicus_dem"]["available"])
    features["worldcover_available"] = float(source["worldcover"]["available"])
    return features, source


def _ood(features: dict[str, float | None], metadata: dict[str, Any]) -> tuple[float, list[str]]:
    distributions = metadata.get("feature_distributions", {})
    outliers = 0
    checked = 0
    for name in MODEL_FEATURES:
        low = distributions.get(name, {}).get("p01")
        high = distributions.get(name, {}).get("p99")
        value = features.get(name)
        if low is None or high is None or value is None:
            continue
        checked += 1
        if value < low or value > high:
            outliers += 1
    range_score = outliers / max(1, checked)
    expected_missing = metadata.get("feature_missing_rates", {})
    observed_missing = sum(features.get(name) is None for name in MODEL_FEATURES) / len(MODEL_FEATURES)
    expected_missing_rate = sum(float(expected_missing.get(name, 0.0)) for name in MODEL_FEATURES) / len(MODEL_FEATURES)
    missing_pattern_score = min(1.0, abs(observed_missing - expected_missing_rate) * 2.0)
    score = min(1.0, range_score * 0.8 + missing_pattern_score * 0.2)
    reasons = ["OUT_OF_DISTRIBUTION"] if score >= float(metadata.get("ood_threshold", _env_float("LANDSLIDE_OOD_THRESHOLD", DEFAULT_OOD_THRESHOLD))) else []
    return score, reasons


def _drivers(model: Any, features: dict[str, float | None]) -> list[dict[str, Any]]:
    try:
        importance = model.feature_importance(importance_type="gain")
        names = list(model.feature_name())
    except Exception:
        return []
    ranked = sorted(zip(names, importance, strict=False), key=lambda pair: float(pair[1]), reverse=True)
    return [
        {"feature": name, "value": features.get(name), "importance": round(float(score), 4), "direction": "model risk driver"}
        for name, score in ranked[:5]
        if features.get(name) is not None
    ]


def _quality(features: dict[str, float | None], source: dict[str, Any]) -> tuple[float, list[str]]:
    missing = sum(features.get(name) is None for name in MODEL_FEATURES)
    score = max(0.0, 1.0 - missing / len(MODEL_FEATURES))
    reasons: list[str] = []
    if not source.get("copernicus_dem", {}).get("available"):
        reasons.append("STATIC_DATA_MISSING")
    if features.get("forecast_available", 0.0) < 0.5:
        reasons.append("FORECAST_UNAVAILABLE")
    forecast_age = features.get("gfs_forecast_age_hours")
    if features.get("forecast_available", 0.0) >= 0.5 and (forecast_age is None or forecast_age > 12.0):
        reasons.append("FORECAST_STALE")
    observation_ages = [
        features.get("imerg_age_minutes"),
        features.get("smap_age_hours"),
        features.get("era5_age_hours"),
    ]
    if any(age is not None and float(age) > limit for age, limit in zip(observation_ages, (180.0, 24.0, 6.0), strict=True)):
        reasons.append("OBSERVATION_STALE")
    if features.get("soilgrids_available", 0.0) < 0.5:
        reasons.append("SOIL_DATA_MISSING")
    if score < _env_float("LANDSLIDE_MIN_DATA_QUALITY", DEFAULT_MIN_DATA_QUALITY):
        reasons.append("LOW_DATA_QUALITY")
    return score, reasons


def _empty_prediction(latitude: float, longitude: float, start: datetime, reasons: list[str], source: dict[str, Any] | None = None) -> RiskPrediction:
    unique = list(dict.fromkeys(reasons))
    return RiskPrediction(
        latitude=latitude,
        longitude=longitude,
        window_start=start,
        window_end=start + timedelta(hours=PREDICTION_HORIZON_HOURS),
        state="UNCERTAIN",
        calibrated_probability=None,
        high_risk_threshold=None,
        confidence_lower=None,
        confidence_upper=None,
        data_quality_score=0.0,
        ood_score=None,
        reason_codes=unique,
        drivers=[],
        data_sources=source or {},
        model={"available": False},
    )


def predict_location(
    latitude: float,
    longitude: float,
    timestamp: datetime | None = None,
    *,
    rain_override: HourlyRain | None = None,
) -> RiskPrediction:
    """Return a fail-closed three-state prediction for a 1km cell around a location."""
    if timestamp is not None and timestamp.tzinfo is None:
        start = timestamp.replace(tzinfo=UTC)
        return _empty_prediction(latitude, longitude, start, ["TIMESTAMP_ALIGNMENT_ERROR"])
    start = (timestamp or _now()).astimezone(UTC)
    if timestamp is not None and abs((datetime.now(UTC) - start).total_seconds()) > 3600:
        return _empty_prediction(latitude, longitude, start, ["HISTORICAL_INFERENCE_UNSUPPORTED"])
    if not _in_bbox(latitude, longitude):
        return _empty_prediction(latitude, longitude, start, ["OUT_OF_DISTRIBUTION"])

    rain, rain_error = (rain_override, None) if rain_override is not None else try_hourly_rain(latitude, longitude)
    static, sources = _static_features(latitude, longitude)
    if rain is None:
        features = static
        sources["forecast"] = {"available": False, "error": rain_error}
        return _empty_prediction(latitude, longitude, start, ["FORECAST_UNAVAILABLE"], sources)

    source_name = os.environ.get("LANDSLIDE_FORECAST_PROVIDER", "open-meteo-compatibility").strip().lower()
    # The compatibility feed is useful for the legacy demo but is not a historical GFS archive.
    # Never let a configuration label turn Open-Meteo observations into a production forecast.
    production_forecast = source_name in {"gfs", "gefs"} and rain.source.lower() in {"gfs", "gefs"}
    use_smap = _env_bool("LANDSLIDE_USE_SMAP", True)
    use_snow = _env_bool("LANDSLIDE_USE_MODIS_SNOW", True)
    use_osm = _env_bool("LANDSLIDE_USE_OSM", True)
    use_geology = _env_bool("LANDSLIDE_USE_GEOLOGY", False)
    if not use_smap:
        rain_soil_moisture: list[float] = []
    else:
        rain_soil_moisture = rain.soil_moisture
    if not use_snow:
        static.update({name: None for name in ("snow_ice_fraction",)})
    if not use_osm:
        static.update({name: None for name in ("road_distance_m", "road_density_km_km2", "major_road_density_km_km2")})
        sources["osm"] = {"available": False, "reason": "disabled by LANDSLIDE_USE_OSM"}
    if not use_geology:
        static.update({name: None for name in ("geology_class_encoded", "fault_distance_m")})
        sources["geology"] = {"available": False, "reason": "disabled by LANDSLIDE_USE_GEOLOGY"}
    dynamic = hourly_dynamic_features(
        rain.times,
        rain.precipitation_mm,
        start,
        extras={
            "temperature_c": rain.temperature_c,
            "surface_soil_moisture": rain_soil_moisture,
            "snowfall": rain.snowfall_cm,
        },
        forecast_times=rain.times,
        forecast_precipitation_mm=rain.precipitation_mm,
        quality={
            "dem_available": static.get("dem_available", False),
            "worldcover_available": static.get("worldcover_available", False),
            "forecast_available": production_forecast,
            "gfs_forecast_age_hours": 0.0 if production_forecast else None,
            # HourlyRain's compatibility soil series is not SMAP L4 and must not be mislabeled.
            "smap_available": False,
            "smap_quality_flag": None,
        },
    )
    features = {**static, **dynamic}
    features["forecast_available"] = dynamic.get("forecast_available")
    sources["forecast"] = {
        "provider": source_name,
        "available": bool(features.get("forecast_available")),
        "as_of": as_of(rain).isoformat(),
        "actual_source": rain.source,
    }
    sources["imerg"] = {"available": False, "reason": "normalized IMERG archive not connected to live compatibility feed"}
    sources["era5_land"] = {"available": False, "reason": "normalized ERA5-Land archive not connected to live compatibility feed"}
    sources["smap"] = {"available": False, "reason": "compatibility soil series is not SMAP L4"}
    sources["feature_flags"] = {
        "use_smap": use_smap,
        "use_modis_snow": use_snow,
        "use_osm": use_osm,
        "use_geology": use_geology,
    }
    sources["open_meteo_compatibility"] = {"provider": rain.source, "as_of": as_of(rain).isoformat()}
    quality_score, quality_reasons = _quality(features, sources)
    model, metadata, calibration, artifact_reasons = _load_artifacts()
    reasons = quality_reasons + artifact_reasons
    if metadata.get("model_mode") == "modern" and features.get("smap_available", 0.0) < 0.5:
        reasons.append("SMAP_MISSING")
    if metadata.get("model_mode", "long-history") == "long-history" and features.get("era5_age_hours") is None:
        reasons.append("ERA5_LAND_MISSING")
    ood_score, ood_reasons = _ood(features, metadata) if metadata else (None, [])
    reasons.extend(ood_reasons)
    threshold = metadata.get("selected_threshold") if metadata else None
    if model is None or calibration.get("method") not in {"isotonic", "platt"}:
        if not artifact_reasons:
            reasons.append("CALIBRATION_MISSING")
        return RiskPrediction(latitude, longitude, start, start + timedelta(hours=PREDICTION_HORIZON_HOURS), "UNCERTAIN", None, threshold, None, None, quality_score, ood_score, list(dict.fromkeys(reasons)), [], sources, {"available": False, "version": metadata.get("model_version")} )

    row = np.array([[np.nan if features.get(name) is None else float(features[name]) for name in MODEL_FEATURES]], dtype="float64")
    raw = float(model.predict(row)[0])
    probability = _calibrate(raw, calibration)
    drivers = _drivers(model, features)
    band = float(metadata.get("abstention_band", _env_float("LANDSLIDE_ABSTENTION_BAND", DEFAULT_ABSTENTION_BAND)))
    if threshold is None:
        reasons.append("ABSTENTION_BAND")
    elif abs(probability - float(threshold)) <= band:
        reasons.append("ABSTENTION_BAND")
    if reasons:
        state: PredictionState = "UNCERTAIN"
    else:
        state = "HIGH_RISK" if probability >= float(threshold) else "NOT_HIGH_RISK"
    uncertainty = min(0.45, 0.08 + (ood_score or 0.0) * 0.5 + (1.0 - quality_score) * 0.4)
    return RiskPrediction(
        latitude, longitude, start, start + timedelta(hours=PREDICTION_HORIZON_HOURS), state,
        round(probability, 4), threshold,
        round(max(0.0, probability - uncertainty), 4), round(min(1.0, probability + uncertainty), 4),
        quality_score, ood_score, list(dict.fromkeys(reasons)), drivers, sources,
        {"available": True, "version": metadata.get("model_version"), "trained_at": metadata.get("training_date"), "calibration_method": calibration.get("method"), "validation": metadata.get("validation", {}).get("test")},
    )
