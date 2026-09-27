"""Live inference for the regional terrain-susceptibility LightGBM model, at one summit.

The heat map already carries this model: ml/scripts/apply_susceptibility_map.py bakes
ml/artifacts/susceptibility_lgbm.txt into ml/artifacts/susceptibility.tif offline. This module
is the live seam for a single point: it loads the same booster and isotonic calibration, pulls
the 16 terrain features from a built feature stack, and returns the calibrated probability with
the shared risk level. At a pixel inside data/processed/rainier_regional_features.tif the answer
matches the raster to within float32.

Catalog peaks outside that stack are scored only when they have their own hill feature window
(data/processed/hills/<slug>/features.tif). Otherwise predict_summit returns unavailable — no
synthetic or slug-seeded terrain samples.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.warp import transform as warp_transform
from rasterio.windows import Window

from app.config import REPO_ROOT
from app.hills import hill_model_input, hill_stack_path, is_hill
from app.risk import RiskLevel, cap_probability, risk_level

MODEL_PATH = REPO_ROOT / "ml" / "artifacts" / "susceptibility_lgbm.txt"
CALIBRATION_PATH = REPO_ROOT / "ml" / "artifacts" / "susceptibility_calibration.json"
STACK_PATH = REPO_ROOT / "data" / "processed" / "rainier_regional_features.tif"
METRICS_PATH = REPO_ROOT / "ml" / "artifacts" / "metrics.json"

METHOD = "regional terrain susceptibility (LightGBM)"
REAL_INPUT = "regional_feature_stack"

# The booster was trained with landcover as a pandas Categorical over these WorldCover
# classes (the pandas_categorical footer of susceptibility_lgbm.txt), so a raw class value
# must be fed to the booster as its category code: the index into this tuple.
LANDCOVER_CLASSES = (10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100)
WATER_CLASS = 80  # never trained on water; the offline map zeroes it, so this seam does too
TOP_DRIVERS = 5

_model_cache: tuple[float, Any, list[str], np.ndarray, np.ndarray, dict] | None = None
_prediction_cache: dict[tuple[str, float, float], dict] = {}


def _artifacts_stamp() -> float | None:
    """The booster and its calibration. The Rainier stack is optional: a hill has its own window."""
    paths = [MODEL_PATH, CALIBRATION_PATH]
    if not all(path.is_file() for path in paths):
        return None
    if STACK_PATH.is_file():
        paths.append(STACK_PATH)
    return max(path.stat().st_mtime for path in paths)


def _load() -> tuple[Any, list[str], np.ndarray, np.ndarray, dict] | None:
    """The booster, its feature order, the isotonic knots, and the model card. None when unbuilt."""
    global _model_cache
    stamp = _artifacts_stamp()
    if stamp is None:
        return None
    if _model_cache and _model_cache[0] == stamp:
        return _model_cache[1:]
    try:
        import lightgbm as lgb

        booster = lgb.Booster(model_file=str(MODEL_PATH))
        calibration = json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))
        if calibration.get("method") != "isotonic":
            return None
        x_thresholds = np.asarray(calibration["x_thresholds"], dtype="float64")
        y_thresholds = np.asarray(calibration["y_thresholds"], dtype="float64")
    except (ImportError, OSError, ValueError, KeyError):
        return None
    try:
        metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        metrics = {}
    features = list(booster.feature_name())
    _model_cache = (stamp, booster, features, x_thresholds, y_thresholds, metrics)
    return _model_cache[1:]


def _stack_features(
    lat: float, lon: float, features: list[str], path: Path | None = None
) -> dict[str, float] | None:
    """The 16 band values at this point, or None outside the stack or on a nodata pixel."""
    stack_path = path or STACK_PATH
    if not stack_path.is_file():
        return None
    with rasterio.open(stack_path) as src:
        try:
            x, y = warp_transform("EPSG:4326", src.crs, [lon], [lat])
            row, col = src.index(x[0], y[0])
        except Exception:
            # UTM and other projected stacks cannot warp far-away catalog peaks (PROJ raises
            # CPLE_AppDefinedError, which is not a RasterioError subclass, so catch broadly:
            # any point the stack cannot place is simply outside it).
            return None
        if not (math.isfinite(x[0]) and math.isfinite(y[0])):
            return None
        if not (0 <= row < src.height and 0 <= col < src.width):
            return None
        values = src.read(window=Window(col, row, 1, 1), boundless=True)[:, 0, 0]
        names = list(src.descriptions)
    out: dict[str, float] = {}
    for name in features:
        if name not in names:
            return None
        value = float(values[names.index(name)])
        if not math.isfinite(value):
            return None
        out[name] = value
    return out


def _predict(booster: Any, features: list[str], values: dict[str, float],
             x_thresholds: np.ndarray, y_thresholds: np.ndarray) -> tuple[float, float]:
    """(raw booster score, calibrated probability under the shared cap), mirroring apply_susceptibility_map.py."""
    row = []
    for name in features:
        value = values[name]
        if name == "landcover":
            cover = int(value)
            value = float(LANDCOVER_CLASSES.index(cover)) if cover in LANDCOVER_CLASSES else float("nan")
        row.append(value)
    raw = float(np.clip(booster.predict(np.asarray([row], dtype="float64"))[0], 0.0, 1.0))
    probability = float(np.clip(np.interp(raw, x_thresholds, y_thresholds), 0.0, 1.0))
    if int(values["landcover"]) == WATER_CLASS:
        probability = 0.0
    return raw, cap_probability(probability)


def _drivers(booster: Any, features: list[str], values: dict[str, float]) -> list[dict[str, Any]]:
    """The model's top gain features with this point's values, like the classifier's drivers."""
    try:
        importance = booster.feature_importance(importance_type="gain")
    except Exception:
        return []
    total = float(sum(importance)) or 1.0
    ranked = sorted(zip(features, importance, strict=True), key=lambda pair: -float(pair[1]))
    return [
        {"feature": name, "value": round(values[name], 4), "importance": round(float(gain) / total, 4)}
        for name, gain in ranked[:TOP_DRIVERS]
    ]


def _unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason, "probability": None, "risk_level": None,
            "input_source": None, "method": METHOD}


def predict_summit(slug: str, lat: float, lon: float) -> dict[str, Any]:
    """The regional model's answer at one summit when real terrain features exist.

    Always JSON-native. `probability` is the isotonic-calibrated relative susceptibility (the
    same quantity as the heat map's pixels), `risk_level` its shared bin. Cached per point per
    artifact build, so the catalog and repeated agent runs pay the raster read once.
    """
    stamp = _artifacts_stamp()
    if stamp is None:
        missing = [str(p.relative_to(REPO_ROOT)) if p.is_relative_to(REPO_ROOT) else str(p)
                   for p in (MODEL_PATH, CALIBRATION_PATH) if not p.is_file()]
        return _unavailable(f"model artifacts missing: {', '.join(missing)}")
    key = (slug, round(lat, 4), round(lon, 4))
    cache_stamp: Any = stamp
    if is_hill(slug):
        stack_path = hill_stack_path(slug)
        cache_stamp = (stamp, stack_path.stat().st_mtime_ns if stack_path.is_file() else 0)
    cached = _prediction_cache.get(key)
    if cached is not None and cached.get("_stamp") == cache_stamp:
        return {k: v for k, v in cached.items() if k != "_stamp"}
    loaded = _load()
    if loaded is None:
        return _unavailable("model artifacts could not be loaded")
    booster, features, x_thresholds, y_thresholds, metrics = loaded

    if is_hill(slug):
        values = _stack_features(lat, lon, features, hill_stack_path(slug))
        if values is None:
            return _unavailable(
                "hill terrain window is not built; this hill has no ground-truth raster"
            )
        input_source, note = hill_model_input(slug), (
            "Scored on this hill's own DEM and land-cover window. "
            "Washington validation scores are not this hill's accuracy."
        )
    else:
        values = _stack_features(lat, lon, features)
        if values is None:
            return _unavailable(
                "summit is outside the regional feature stack and has no dedicated terrain window"
            )
        input_source, note = REAL_INPUT, "Scored on this point's own satellite-derived terrain."

    raw, probability = _predict(booster, features, values, x_thresholds, y_thresholds)
    level: RiskLevel = risk_level(probability)
    result = {
        "available": True,
        "method": METHOD,
        "model_file": str(MODEL_PATH.relative_to(REPO_ROOT)),
        "probability": round(probability, 4),
        "raw_score": round(raw, 4),
        "risk_level": level,
        "input_source": input_source,
        "note": note,
        "features": {name: round(value, 4) for name, value in values.items()},
        "drivers": _drivers(booster, features, values),
        "model_card": {
            "trained": metrics.get("trained"),
            "auc": None if is_hill(slug) else metrics.get("auc"),
            "note": note if is_hill(slug) else metrics.get("note"),
            "probability_meaning": metrics.get("probability_meaning"),
        },
    }
    _prediction_cache[key] = {**result, "_stamp": cache_stamp}
    return result
