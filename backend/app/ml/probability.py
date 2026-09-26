"""The 72-hour probability map that the heat map, the hazard zone, and the agents read (step 18).

Model B (app/ml/model_b.py, step 17) makes it from susceptibility and rain. The ML track is
rebuilding Model B, so this module is the one seam between it and everything downstream:

- When app/ml/model_b.py exists, score() calls model_b.run(rain) and reads `.probability`
  (float32 0-1 on the susceptibility grid, NaN outside the data), `.transform`, and `.crs`
  from the result. That is the shape step 17 first shipped with. If the rebuilt module
  differs, adapt _from_model_b() and nothing else.
- Until then, the map is the susceptibility map itself, and `method` says so. Rain does not
  move it. Every layer, hazard, and agent prompt carries that method, so nothing presents
  the stand-in as Model B.
"""

import importlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine

from app.config import REPO_ROOT
from app.risk import BIN_EDGES, RISK_LEVELS
from app.weather import HourlyRain

logger = logging.getLogger(__name__)

SUSCEPTIBILITY_PATH = REPO_ROOT / "ml" / "artifacts" / "susceptibility.tif"
PROBABILITY_PATH = REPO_ROOT / "ml" / "artifacts" / "probability.tif"
METRICS_PATH = REPO_ROOT / "ml" / "artifacts" / "metrics.json"
MODEL_B_VALIDATION_PATH = REPO_ROOT / "ml" / "artifacts" / "model_b_validation.json"

MODEL_B_METHOD = "model b"
STAND_IN_METHOD = "susceptibility stand-in (Model B pending)"


@dataclass(frozen=True)
class ProbabilityMap:
    values: np.ndarray  # float32 0-1 on the 30 m UTM grid, NaN outside the data
    transform: Affine
    crs: str
    method: str  # MODEL_B_METHOD, or STAND_IN_METHOD while step 17 is out

    @property
    def is_stand_in(self) -> bool:
        return self.method == STAND_IN_METHOD


def _model_b():
    """app.ml.model_b if the module exists, else None. Its own import errors still raise."""
    try:
        return importlib.import_module("app.ml.model_b")
    except ModuleNotFoundError as exc:
        if exc.name != "app.ml.model_b":
            raise
        return None


def _from_model_b(model_b, rain: HourlyRain | None, susceptibility: Path | None) -> ProbabilityMap:
    # Rainier keeps the pinned seam, model_b.run(rain); only a pack's raster adds the
    # path keyword (main's model_b takes it; a rebuilt module must keep it for packs).
    if susceptibility is None or susceptibility == SUSCEPTIBILITY_PATH:
        result = model_b.run(rain)
    else:
        result = model_b.run(rain, path=susceptibility)
    values = np.asarray(result.probability, dtype="float32")
    return ProbabilityMap(values, result.transform, str(result.crs), MODEL_B_METHOD)


def _stand_in(path: Path = SUSCEPTIBILITY_PATH) -> ProbabilityMap:
    if not path.exists():
        raise FileNotFoundError(
            f"{path.relative_to(REPO_ROOT)} is missing (susceptibility GeoTIFF). "
            "From repo root: python ml/scripts/download_sources.py --only dem,landcover && "
            "python ml/scripts/build_features.py && python ml/scripts/train_susceptibility.py"
        )
    with rasterio.open(path) as src:
        values = src.read(1).astype("float32")
        return ProbabilityMap(values, src.transform, src.crs.to_string(), STAND_IN_METHOD)


def score(rain: HourlyRain | None = None, susceptibility: Path | None = None) -> ProbabilityMap:
    """The current 72-hour probability map: Model B when it exists, else the stand-in.

    `susceptibility` points at one pack's raster (step 32); None keeps Rainier's.
    """
    model_b = _model_b()
    if model_b is not None:
        return _from_model_b(model_b, rain, susceptibility)
    logger.info("app/ml/model_b.py is not in the tree: the probability map is the susceptibility stand-in")
    return _stand_in(susceptibility or SUSCEPTIBILITY_PATH)


def explain(susceptibility: float, rain: HourlyRain | None) -> dict[str, float] | None:
    """Model B's logit terms at one cell, or None while the stand-in (which has no terms) is live."""
    model_b = _model_b()
    if model_b is None or not hasattr(model_b, "contributions"):
        return None
    return model_b.contributions(susceptibility, rain)


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def validation() -> dict | None:
    """The held-out skill behind the index, read from the two ML artifacts, or None if either is missing.

    Terrain: ROC-AUC over 10 km spatial block folds in the western Cascades, and on the Rainier
    box's own mapped slides (never trained on). Rain trigger: ROC-AUC over water-year folds on
    dated landslides, with storm-bootstrap 95% intervals.
    """
    terrain = _load_json(METRICS_PATH)
    trigger = _load_json(MODEL_B_VALIDATION_PATH)
    try:
        spatial = terrain["validation"]["spatial_cv"]["folds"]["roc_auc"]
        rainier = terrain["validation"]["external_rainier"]
        fitted = trigger["primary_year_blocked"]
        counts = trigger["counts"]
        return {
            "terrain_roc_auc": spatial["mean"],
            "terrain_roc_auc_ci95": spatial["ci95"],
            "terrain_positives": terrain["labels"]["train_positives"],
            "rainier_roc_auc": rainier["metrics"]["roc_auc"],
            "rainier_roc_auc_ci95": rainier["block_bootstrap_ci95"]["roc_auc"],
            "rainier_positives": rainier["metrics"]["positives"],
            "trigger_roc_auc": fitted["metrics"]["lr_model_b"]["roc_auc"],
            "trigger_roc_auc_ci95": fitted["bootstrap"]["ci95"]["lr_model_b"]["roc_auc"],
            "trigger_events": counts["n_cases"],
            "trigger_storms": counts["n_storms"],
            "trigger_years": [int(day[:4]) for day in counts["date_range"]],
        }
    except (TypeError, KeyError, IndexError, ValueError):
        return None


def summarize(values: np.ndarray) -> dict:
    """Cell count, range, and the share of cells in each shared risk bin."""
    valid = values[~np.isnan(values)]
    if valid.size == 0:
        return {"cells": 0, "min": None, "mean": None, "max": None, "share": dict.fromkeys(RISK_LEVELS, 0.0)}
    counts = np.bincount(np.digitize(valid, BIN_EDGES), minlength=len(RISK_LEVELS))
    return {
        "cells": int(valid.size),
        "min": round(float(valid.min()), 3),
        "mean": round(float(valid.mean()), 3),
        "max": round(float(valid.max()), 3),
        "share": {level: round(float(n) / valid.size, 3) for level, n in zip(RISK_LEVELS, counts, strict=True)},
    }


def write(probability: ProbabilityMap, path: Path = PROBABILITY_PATH) -> Path:
    """Save the map as a GeoTIFF for the tiler. METHOD rides along into the layer's metadata."""
    height, width = probability.values.shape
    profile = {
        "driver": "GTiff", "width": width, "height": height, "count": 1, "dtype": "float32",
        "crs": probability.crs, "transform": probability.transform, "nodata": np.nan,
        "tiled": True, "blockxsize": 256, "blockysize": 256, "compress": "deflate", "predictor": 3,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    with rasterio.open(partial, "w", **profile) as dst:
        dst.write(probability.values, 1)
        dst.set_band_description(1, "probability_72h")
        dst.update_tags(METHOD=probability.method)
    partial.replace(path)
    return path
