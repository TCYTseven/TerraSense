"""Live inference for the regional terrain-susceptibility LightGBM model, at one summit.

The heat map already carries this model: ml/scripts/apply_susceptibility_map.py bakes
ml/artifacts/susceptibility_lgbm.txt into ml/artifacts/susceptibility.tif offline. This module
is the live seam for a single point, so the agents and the catalog can read the model's own
answer for a mountain that has no baked raster: it loads the same booster and isotonic
calibration, pulls the 16 terrain features from the satellite-derived feature stack
(data/processed/rainier_regional_features.tif), and returns the calibrated probability with
the shared risk level. predict at a stack pixel matches the raster to within float32.

A summit outside the stack has no satellite terrain of its own yet. Until each catalog
mountain gets its own DEM and land-cover window, predict_summit falls back to a deterministic
stand-in: a real terrain sample drawn from the stack, seeded by the slug so it is stable
across restarts. The answer is labeled input_source="placeholder_terrain_sample" and its note
says so; nothing may present it as the mountain's own ground.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import rasterio
from rasterio.warp import transform as warp_transform
from rasterio.windows import Window

from app.config import REPO_ROOT
from app.risk import RiskLevel, risk_level

MODEL_PATH = REPO_ROOT / "ml" / "artifacts" / "susceptibility_lgbm.txt"
CALIBRATION_PATH = REPO_ROOT / "ml" / "artifacts" / "susceptibility_calibration.json"
STACK_PATH = REPO_ROOT / "data" / "processed" / "rainier_regional_features.tif"
METRICS_PATH = REPO_ROOT / "ml" / "artifacts" / "metrics.json"

METHOD = "regional terrain susceptibility (LightGBM)"
REAL_INPUT = "regional_feature_stack"
PLACEHOLDER_INPUT = "placeholder_terrain_sample"
PLACEHOLDER_NOTE = (
    "STAND-IN INPUT: this mountain has no satellite terrain window of its own yet, so the "
    "model scored a real terrain sample from the training stack, chosen deterministically "
    "from the mountain's slug. The probability is a live model output on placeholder ground, "
    "not a measurement of this summit."
)

# The booster was trained with landcover as a pandas Categorical over these WorldCover
# classes (the pandas_categorical footer of susceptibility_lgbm.txt), so a raw class value
# must be fed to the booster as its category code: the index into this tuple.
LANDCOVER_CLASSES = (10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100)
WATER_CLASS = 80  # never trained on water; the offline map zeroes it, so this seam does too
TOP_DRIVERS = 5
# The placeholder pool subsamples the stack on this pixel stride: dense enough that every
# slug lands on distinct ground, sparse enough to keep the pool under a megabyte.
POOL_STRIDE = 8

_model_cache: tuple[float, Any, list[str], np.ndarray, np.ndarray, dict] | None = None
_pool_cache: tuple[float, np.ndarray] | None = None
_prediction_cache: dict[tuple[str, float, float], dict] = {}


def _artifacts_stamp() -> float | None:
    paths = (MODEL_PATH, CALIBRATION_PATH, STACK_PATH)
    if not all(path.is_file() for path in paths):
        return None
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


def _stack_features(lat: float, lon: float, features: list[str]) -> dict[str, float] | None:
    """The 16 band values at this point, or None outside the stack or on a nodata pixel."""
    with rasterio.open(STACK_PATH) as src:
        try:
            x, y = warp_transform("EPSG:4326", src.crs, [lon], [lat])
            row, col = src.index(x[0], y[0])
        except rasterio.errors.RasterioError:
            # UTM and other projected stacks cannot warp polar catalog peaks (|lat| > ~84).
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


def _placeholder_pool(features: list[str]) -> np.ndarray | None:
    """Valid feature rows subsampled from the stack, for the slug-seeded stand-in."""
    global _pool_cache
    stamp = STACK_PATH.stat().st_mtime
    if _pool_cache and _pool_cache[0] == stamp:
        return _pool_cache[1]
    with rasterio.open(STACK_PATH) as src:
        stack = src.read()[:, ::POOL_STRIDE, ::POOL_STRIDE].astype("float64")
        names = list(src.descriptions)
    if any(name not in names for name in features):
        return None
    bands = np.stack([stack[names.index(name)] for name in features])
    valid = np.isfinite(bands).all(axis=0)
    landcover = bands[features.index("landcover")]
    valid &= landcover != WATER_CLASS  # a stand-in on water would pin the answer to zero
    pool = bands[:, valid].T  # (n_pixels, n_features)
    if pool.shape[0] == 0:
        return None
    _pool_cache = (stamp, pool)
    return pool


def _slug_seed(slug: str) -> int:
    """FNV-1a, so the same slug samples the same stand-in terrain on every process."""
    h = 2166136261
    for char in slug:
        h = ((h ^ ord(char)) * 16777619) & 0xFFFFFFFF
    return h


def _placeholder_features(slug: str, features: list[str]) -> dict[str, float] | None:
    pool = _placeholder_pool(features)
    if pool is None:
        return None
    row = pool[_slug_seed(slug) % pool.shape[0]]
    return dict(zip(features, (float(v) for v in row), strict=True))


def _predict(booster: Any, features: list[str], values: dict[str, float],
             x_thresholds: np.ndarray, y_thresholds: np.ndarray) -> tuple[float, float]:
    """(raw booster score, calibrated probability), mirroring apply_susceptibility_map.py."""
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
    return raw, probability


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
    """The regional model's answer at one summit, on real or clearly labeled stand-in terrain.

    Always JSON-native. `probability` is the isotonic-calibrated relative susceptibility (the
    same quantity as the heat map's pixels), `risk_level` its shared bin. Cached per point per
    artifact build, so the catalog and repeated agent runs pay the raster read once.
    """
    stamp = _artifacts_stamp()
    if stamp is None:
        missing = [str(p.relative_to(REPO_ROOT)) if p.is_relative_to(REPO_ROOT) else str(p)
                   for p in (MODEL_PATH, CALIBRATION_PATH, STACK_PATH) if not p.is_file()]
        return _unavailable(f"model artifacts missing: {', '.join(missing)}")
    key = (slug, round(lat, 4), round(lon, 4))
    cached = _prediction_cache.get(key)
    if cached is not None and cached.get("_stamp") == stamp:
        return {k: v for k, v in cached.items() if k != "_stamp"}
    loaded = _load()
    if loaded is None:
        return _unavailable("model artifacts could not be loaded")
    booster, features, x_thresholds, y_thresholds, metrics = loaded

    values = _stack_features(lat, lon, features)
    if values is not None:
        input_source, note = REAL_INPUT, "Scored on this point's own satellite-derived terrain."
    else:
        values = _placeholder_features(slug, features)
        if values is None:
            return _unavailable("no terrain features: the feature stack has no valid pixels")
        input_source, note = PLACEHOLDER_INPUT, PLACEHOLDER_NOTE

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
            "auc": metrics.get("auc"),
            "note": metrics.get("note"),
            "probability_meaning": metrics.get("probability_meaning"),
        },
    }
    _prediction_cache[key] = {**result, "_stamp": stamp}
    return result
